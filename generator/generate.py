"""
Task generator — generates a Terminal Bench task from a topic string using Sonnet via OpenRouter.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import httpx
from openai import OpenAI

API_MAX_RETRIES = 3
API_RETRY_DELAY = 5  # seconds, doubles each retry
# Per-phase httpx timeout: short connect/write, 30s between chunks.
# Detects stalled connections without cutting off a slow-but-progressing
# response (unlike a blunt total timeout which would kill long generations).
API_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)

# Standard docker-compose.yaml — identical for every task.
# The tb harness uses `docker compose` (not raw docker) to build and run tasks.
DOCKER_COMPOSE_TEMPLATE = """\
services:
  client:
    container_name: ${T_BENCH_TASK_DOCKER_CLIENT_CONTAINER_NAME}
    image: ${T_BENCH_TASK_DOCKER_CLIENT_IMAGE_NAME}
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      - TEST_DIR=${T_BENCH_TEST_DIR:-/tests}
    stdin_open: true
    tty: true
"""

from config import (
    EXAMPLES_DIR,
    GENERATOR_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPUS_EXAMPLES_DIR,
    SONNET_EXAMPLES_DIR,
    OUTPUT_DIR,
    _slugify,
)


# Instruction style for task.yaml — based on what learnable tasks actually have.
# Every confirmed learnable task follows this pattern:
#   1. Names the exact file path ("/app/template_engine.py")
#   2. Describes what the program SHOULD do (numbered requirements)
#   3. Lists current broken behavior or bug symptoms
INSTRUCTION_RULE = {
    "long": (
        "8. The instruction in task.yaml MUST follow this pattern (all learnable tasks do):\n"
        "   a) Name the exact source file path (e.g. \"The script `/app/csv_processor.py`\")\n"
        "   b) Describe what the program is supposed to do (numbered list of requirements)\n"
        "   c) List the current broken behavior or symptoms (e.g. \"Currently: assumes comma "
        "delimiter, treats all rows as data, emits lists instead of dicts\")\n"
        "   The agent has limited turns, so it needs to know the file to read, the expected "
        "behavior, and what's currently wrong — without this context it wastes time on discovery."
    ),
    "short": (
        "task.yaml instruction MUST: name the file path, list expected behavior, "
        "describe current broken behavior"
    ),
}


def _api_call_with_retry(client: OpenAI, **kwargs) -> object:
    """Call the OpenAI chat completions API with retry on transient failures.

    Retries on network errors, malformed responses, and server errors.
    Does NOT retry on auth errors or invalid requests (4xx).
    """
    last_error = None
    for attempt in range(API_MAX_RETRIES):
        try:
            return client.chat.completions.create(timeout=API_TIMEOUT, **kwargs)
        except (json.JSONDecodeError, ConnectionError, TimeoutError) as e:
            last_error = e
            delay = API_RETRY_DELAY * (2 ** attempt)
            print(f"  API error (attempt {attempt + 1}/{API_MAX_RETRIES}): {e}")
            print(f"  Retrying in {delay}s...")
            time.sleep(delay)
        except Exception as e:
            # Don't retry on auth errors, bad requests, or unrecoverable client errors.
            # openai.APITimeoutError falls here and IS retried (timeout not in this list).
            err_str = str(e).lower()
            if any(code in err_str for code in ("401", "403", "422", "invalid_request")):
                raise
            last_error = e
            delay = API_RETRY_DELAY * (2 ** attempt)
            print(f"  API error (attempt {attempt + 1}/{API_MAX_RETRIES}): {e}")
            print(f"  Retrying in {delay}s...")
            time.sleep(delay)
    raise last_error


# Examples confirmed too easy by evaluation (Sonnet/Opus solve trivially).
# Included in few-shot context as NEGATIVE examples — "don't generate tasks this simple."
# Default token budget for examples in the prompt.
# Total learnable examples ~25k tokens; budget caps how many we include.
DEFAULT_EXAMPLE_TOKEN_BUDGET = 40000


def _load_task_dir(task_dir: Path) -> str:
    """Load all files from a task directory into a formatted string.

    If a _bugs.md file exists, it's included with a special header explaining
    the bug-to-test mapping. This teaches the generator what makes good bugs.
    """
    parts = [f"### Example: {task_dir.name}\n"]

    # Load _bugs.md first if it exists — gives context for reading the buggy code
    bugs_file = task_dir / "_bugs.md"
    if bugs_file.exists():
        try:
            content = bugs_file.read_text()
            parts.append(
                f"**BUG ANNOTATIONS** (study these — this is what makes good bugs):\n"
                f"```\n{content}\n```\n"
            )
        except UnicodeDecodeError:
            pass

    for fpath in sorted(task_dir.rglob("*")):
        if fpath.is_file() and not fpath.name.startswith(".") and fpath.name != "_bugs.md":
            rel = fpath.relative_to(task_dir)
            try:
                content = fpath.read_text()
                parts.append(f"**{rel}**\n```\n{content}\n```\n")
            except UnicodeDecodeError:
                continue
    return "\n".join(parts)


def _load_example_meta(task_dir: Path) -> dict | None:
    """Load _meta.yaml from an example directory. Returns None if missing."""
    import yaml
    meta_path = task_dir / "_meta.yaml"
    if not meta_path.exists():
        return None
    try:
        return yaml.safe_load(meta_path.read_text())
    except Exception:
        return None


def _score_example(meta: dict, target_category: str | None) -> float:
    """Score an example for selection. Higher = better candidate.

    Scoring factors:
    - Pass rate closeness to ideal (0.4-0.6) — best examples are solidly learnable
    - Category match to target topic — same-category examples are more relevant
    - Token efficiency — prefer smaller examples (more room for others)
    """
    score = 0.0
    pass_rate = meta.get("opus_pass_rate", 0.5)

    # Ideal pass rate is 0.4-0.6 (2-3/5). Score drops as it moves away.
    ideal_center = 0.5
    score += max(0, 1.0 - abs(pass_rate - ideal_center) * 3)

    # Category match bonus
    if target_category and meta.get("category") == target_category:
        score += 0.5

    # Token efficiency — slight preference for smaller examples
    tokens = meta.get("approx_tokens", 5000)
    score += max(0, (8000 - tokens) / 8000) * 0.3

    return score


def select_examples(
    target_category: str | None = None,
    target_topic: str | None = None,
    token_budget: int = DEFAULT_EXAMPLE_TOKEN_BUDGET,
) -> str:
    """Select examples using _meta.yaml metadata, optimizing for diversity and relevance.

    Selection algorithm:
    0. If a same-topic example exists, include it first (most relevant reference)
    1. Load all examples with _meta.yaml from all example directories
    2. Separate into learnable (positive) and too_easy (negative)
    3. Exclude too_hard examples entirely
    4. Ensure category diversity — pick one from each represented category first
    5. Fill remaining budget by score (pass rate closeness + category match)
    6. Include at most 1 negative (too_easy) example

    Returns formatted string for prompt injection.
    """
    candidates = []  # (task_dir, meta, content_str)
    negative = []

    for examples_path in [Path(EXAMPLES_DIR), Path(OPUS_EXAMPLES_DIR), Path(SONNET_EXAMPLES_DIR)]:
        if not examples_path.is_dir():
            continue
        for task_dir in sorted(examples_path.iterdir()):
            if not task_dir.is_dir():
                continue
            meta = _load_example_meta(task_dir)
            if meta is None:
                continue  # skip examples without metadata
            classification = meta.get("classification", "unknown")
            if classification == "too_hard":
                continue  # never show too-hard examples
            content = _load_task_dir(task_dir)
            if classification == "too_easy":
                negative.append((task_dir, meta, content))
            elif classification == "learnable":
                candidates.append((task_dir, meta, content))

    # Exclude same-topic examples to force diverse generation.
    # Showing Sonnet the exact same topic's code causes verbatim copying
    # (5/11 tasks in batch 27 were byte-identical to existing examples).
    if target_topic:
        candidates = [(td, m, c) for td, m, c in candidates if m.get("topic") != target_topic]

    selected = []
    selected_tokens = 0
    seen_categories = set()
    selected_dirs: set = set()

    # Phase 1: category diversity — one example per category
    by_category: dict[str, list] = {}
    for task_dir, meta, content in candidates:
        cat = meta.get("category", "unknown")
        by_category.setdefault(cat, []).append((task_dir, meta, content))

    for cat in sorted(by_category.keys()):
        items = by_category[cat]
        items.sort(key=lambda x: _score_example(x[1], target_category), reverse=True)
        best = items[0]
        tokens = best[1].get("approx_tokens", 5000)
        if selected_tokens + tokens <= token_budget:
            selected.append(best)
            selected_tokens += tokens
            seen_categories.add(cat)
            selected_dirs.add(best[0])

    # Phase 2: fill remaining budget with highest-scored remaining candidates
    remaining = [
        (td, m, c) for td, m, c in candidates
        if td not in selected_dirs
    ]
    remaining.sort(key=lambda x: _score_example(x[1], target_category), reverse=True)

    for td, m, c in remaining:
        tokens = m.get("approx_tokens", 5000)
        if selected_tokens + tokens <= token_budget:
            selected.append((td, m, c))
            selected_tokens += tokens

    # Build output
    sections = []
    if selected:
        positive_parts = [c for _, _, c in selected]
        sections.append(
            "## GOOD EXAMPLES (target this difficulty level)\n"
            "These tasks are in the learnable range — generate tasks similar to these.\n\n"
            + "\n---\n\n".join(positive_parts)
        )

    # Include at most 1 negative example if budget allows
    if negative:
        best_neg = negative[0]
        neg_tokens = best_neg[1].get("approx_tokens", 2000)
        if selected_tokens + neg_tokens <= token_budget:
            sections.append(
                "## TOO-EASY EXAMPLES (avoid this difficulty level)\n"
                "These tasks are too simple — an AI agent solves them trivially every time. "
                "Your generated tasks must be significantly harder than these.\n\n"
                + best_neg[2]
            )

    n_selected = len(selected)
    cats = sorted(seen_categories)
    print(f"  Examples: {n_selected} selected (~{selected_tokens} tokens), categories: {cats}")

    return "\n\n".join(sections)


SYSTEM_PROMPT = """\
You are an expert at creating coding tasks for evaluating AI agents. You generate \
Terminal Bench tasks — self-contained coding challenges that run in Docker containers \
and are verified by pytest.

CRITICAL RULES:
1. Every task MUST have these files: task.yaml, Dockerfile, run-tests.sh, solution.sh, tests/test_outputs.py
2. Tasks must include "source files" — the buggy/incomplete code the agent needs to fix or build upon.
3. solution.sh must be a deterministic bash script that solves the task completely. It uses `cat > filename << 'EOF'` heredocs to write fixed files and runs any setup needed.
4. Tests MUST FAIL on the unsolved container (before solution.sh runs) and PASS after solution.sh runs.
5. The Dockerfile MUST install tmux and asciinema alongside all other dependencies (required by the test harness). Example: `RUN apt-get update && apt-get install -y tmux asciinema curl && rm -rf /var/lib/apt/lists/*`
6. run-tests.sh installs uv + pytest and runs the tests. Follow the exact boilerplate pattern from examples.
7. task.yaml must have: instruction (detailed), difficulty, category, tags, parser_name: pytest, and timeout fields.
{instruction_hint_rule}

MOST IMPORTANT — AVOID THESE COMMON FAILURES:
A. Tests MUST actually FAIL before solution.sh runs. The source files must have REAL bugs that cause test failures. If you write source code that already works, the task is broken. Verify mentally: "will running these tests against the buggy source files produce failures?"
B. solution.sh must fix ALL bugs, not just some. Mentally trace every test case through your solution and verify it passes.
C. solution.sh must write COMPLETE fixed files (using heredocs), not patches. It should be self-contained.
D. Keep the technology stack simple — prefer Python, Bash, C. Avoid Node.js/npm unless the topic requires it, as npm installs are slow and fragile in containers.
E. ALL source files must live in WORKDIR (usually /app). Never put source files in system directories like /etc/ or /usr/. Dockerfile WORKDIR must match paths used in source files, tests, and solution.sh.
F. Tests should test concrete outputs (file contents, exit codes, stdout) not require running servers. Server-based tasks are harder to validate reliably.

DIFFICULTY CALIBRATION (CRITICAL):
These tasks will be solved by a very capable AI agent (Claude Opus) with a 6-minute \
time limit. To land in the learnable range (1-3 out of 5 attempts pass), aim for:
- Include exactly 3-4 bugs (NOT 5+, that's too hard)
- Each bug MUST be independently discoverable from test output — a failing test should \
point toward the bug that caused it, not require fixing other bugs first
- Do NOT create cascading bugs where Bug A must be fixed before Bug B can even be diagnosed
- Keep total source code under 150 lines — the agent must read and understand it in ~1 minute
- All bugs should be in a SINGLE source file — multi-file bug hunts are too slow for 6 minutes
- Use bugs that produce clear test failures: wrong output, wrong type, missing value. \
Avoid bugs that only show up in valgrind, cause undefined behavior, or produce intermittent failures
- Keep test count low: 5-7 tests, not 9-11. Each test should check one bug's behavior. \
Fewer tests with clear pass/fail criteria give the agent margin for implementation \
differences — the goal is testing bug-finding, not exact output formatting
- The task should take a skilled human 10-20 minutes (NOT 30-60 minutes)
- Do NOT make it impossible — a capable agent should solve it ~40-60% of the time

STRUCTURAL PATTERNS FOR LEARNABILITY (data-driven from 17 batch runs):
Tasks that land in the learnable range share these properties:
1. PARTIAL CREDIT: Each bug breaks only 1-2 tests. Fixing any single bug makes some \
tests pass. Avoid all-or-nothing designs where one remaining bug fails ALL tests \
(e.g., scripts with set -e that crash on the first error).
2. BEHAVIORAL TESTS: Tests invoke the program via subprocess or import and check behavior \
(output content, return codes, data structures). NOT exact string matching against \
pre-computed output files.
3. REQUIREMENT-BASED INSTRUCTIONS: task.yaml describes WHAT the code should do, not \
WHICH LINES to change. The agent should diagnose bugs by reading code, not by following \
a recipe. Good: "The parser should handle empty input gracefully". \
Bad: "Line 15 uses split() instead of csv.reader()".
4. MIXED BUG DIFFICULTY: Include 1-2 simple bugs (wrong operator, missing return) and \
1-2 subtle bugs (missing edge case, wrong data structure). The simple bugs provide \
partial credit; the subtle ones create the difficulty gradient that produces 40-60% \
solve rates.

STUDY THE EXAMPLES CAREFULLY. The examples below show the exact difficulty level and bug \
style to target. Match them closely — they are more important than the rules above.

OUTPUT FORMAT:
Return your response as a JSON object with this structure:
{
  "files": {
    "task.yaml": "content...",
    "Dockerfile": "content...",
    "run-tests.sh": "content...",
    "solution.sh": "content...",
    "tests/test_outputs.py": "content...",
    "source_file.ext": "content...",
    ...additional source files...
  }
}

IMPORTANT: Return ONLY raw JSON. Do NOT wrap it in ```json``` markdown fences or any other formatting. Start your response with { and end with }."""

def _build_user_prompt(topic: str, target_category: str | None = None) -> str:
    """Build the user prompt with topic and examples."""
    examples = select_examples(target_category=target_category, target_topic=topic)

    return f"""Generate a Terminal Bench task for this topic: "{topic}"

Study these reference examples carefully and match their format exactly:

{examples}

Now generate a complete, high-quality task for: "{topic}"

Remember:
- Include 3-4 independently discoverable bugs in a SINGLE source file (<150 lines)
- Each bug should produce a clear, diagnosable test failure on its own
- Do NOT create cascading bugs — each should be fixable without fixing others first
- Tests must fail before solution and pass after
- Dockerfile should set up a proper environment
- solution.sh must deterministically fix everything
- Target ~40-60% solve rate for Claude Opus (learnable, not impossible)
- Return ONLY the JSON object with all files"""


def _strip_fences(text: str) -> str:
    """Strip leading/trailing markdown code fences from an LLM response.

    Cannot use a simple regex because the JSON content itself may contain
    triple backticks (e.g. code blocks inside task.yaml instructions).
    Handles ```json...``` and plain ```...``` wrappers.
    """
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
        last_fence = text.rfind("```")
        if last_fence != -1:
            text = text[:last_fence]
        text = text.strip()
    return text


def _parse_response(response_text: str) -> dict:
    """Parse the LLM response to extract files dict.

    Handles: raw JSON, JSON in markdown fences (even when content contains ```),
    and JSON embedded in surrounding text.
    """
    text = _strip_fences(response_text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: find outermost { ... } braces
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            data = json.loads(text[brace_start : brace_end + 1])
        else:
            raise ValueError(f"Could not parse JSON from response: {text[:200]}...")

    if "files" not in data:
        raise ValueError(f"Response missing 'files' key. Keys found: {list(data.keys())}")

    return data["files"]


def _write_task_files(files: dict, output_dir: str) -> None:
    """Write parsed files to the task directory.

    Always injects a standard docker-compose.yaml so the tb harness
    (which uses `docker compose`) can build and run the task.
    """
    # Always write the standard docker-compose.yaml — it's identical for all tasks
    files = dict(files)  # don't mutate caller's dict
    files.setdefault("docker-compose.yaml", DOCKER_COMPOSE_TEMPLATE)

    for filepath, content in files.items():
        full_path = os.path.normpath(os.path.join(output_dir, filepath))
        # Guard against path traversal from LLM-generated file paths
        if not full_path.startswith(os.path.normpath(output_dir) + os.sep) and full_path != os.path.normpath(output_dir):
            print(f"  WARNING: Skipping file with path traversal: {filepath}")
            continue
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        # Guard against LLM returning list instead of string for file content
        if isinstance(content, list):
            content = "\n".join(str(line) for line in content)
        elif not isinstance(content, str):
            content = str(content)
        with open(full_path, "w") as f:
            f.write(content)

        # Make shell scripts executable
        if filepath.endswith(".sh"):
            os.chmod(full_path, 0o755)


def _format_prompt(template: str) -> str:
    """Fill instruction rule placeholders in a system prompt template."""
    result = template.replace("{instruction_hint_rule}", INSTRUCTION_RULE["long"])
    result = result.replace("{instruction_hint_rule_short}", INSTRUCTION_RULE["short"])
    return result


def generate_task(
    topic: str,
    output_dir: str | None = None,
    model: str | None = None,
    target_category: str | None = None,
) -> dict:
    """Generate a Terminal Bench task for the given topic.

    Args:
        topic: A short description of the task to generate.
        output_dir: Where to write the generated task files.
        model: Override the generator model.

    Returns:
        dict with task_dir, status, usage, and duration.
    """
    slug = _slugify(topic)

    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR, slug)

    os.makedirs(output_dir, exist_ok=True)

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

    gen_model = model or GENERATOR_MODEL
    sys_prompt = _format_prompt(SYSTEM_PROMPT)
    user_prompt = _build_user_prompt(topic, target_category=target_category)

    print(f"Generating task for: {topic}")
    print(f"  Model: {gen_model}")
    print(f"  Output: {output_dir}")

    start = time.time()

    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    status = None

    for parse_attempt in range(3):
        response = _api_call_with_retry(
            client, model=gen_model, messages=messages,
            temperature=0.7, max_tokens=8192,
        )

        response_text = response.choices[0].message.content
        if response.usage:
            for k in usage:
                usage[k] += getattr(response.usage, k, 0)

        try:
            files = _parse_response(response_text)
            _write_task_files(files, output_dir)
            status = "success"
            break
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            if parse_attempt < 2:
                print(f"  Parse attempt {parse_attempt + 1} failed: {e} — retrying...")
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": (
                    f"Your response was not valid JSON. Error: {e}\n"
                    "Return ONLY a raw JSON object starting with {{ and ending with }}. "
                    "No markdown fences, no explanation, just the JSON."
                )})
            else:
                status = f"parse_error: {e}"
                with open(os.path.join(output_dir, "_raw_response.txt"), "w") as f:
                    f.write(response_text)

    duration = time.time() - start

    result = {
        "task_dir": output_dir,
        "status": status,
        "model": gen_model,
        "usage": usage,
        "duration_sec": round(duration, 2),
    }

    print(f"  Status: {status}")
    print(f"  Duration: {duration:.1f}s")
    if usage:
        print(f"  Tokens: {usage.get('total_tokens', '?')}")

    return result


PHASE1_PROMPT = """\
You are an expert software engineer. Write a COMPLETE, WORKING program for the topic below.

Topic: "{topic}"

Create a fully functional implementation with:
1. All source files (working, bug-free code) — keep total source under 150 lines in a SINGLE file
2. A Dockerfile (Ubuntu-based, include `tmux asciinema` in apt-get install)
3. A run-tests.sh (use the uv + pytest boilerplate from examples)
4. A tests/test_outputs.py with 5-7 test functions that all PASS — each test should check one distinct behavior
5. A task.yaml with instruction, difficulty: medium, category, tags, parser_name: pytest

The code should be modular enough that 3-4 realistic bugs can be introduced independently \
(e.g., separate functions, clear data flow, distinct code paths for different features).

IMPORTANT constraints:
- All bugs must be in APPLICATION LOGIC only (the .py, .c, .sh source files)
- Do NOT put bugs in Dockerfiles, config files, build scripts, or infrastructure setup
- Do NOT require pip install, package building, or system-level tooling changes
- Tests should verify program behavior (output values, return codes, file contents), \
not infrastructure state (directories exist, packages installed, services running)

TEST DESIGN (critical for correct difficulty calibration):
- Tests MUST invoke the program directly (via subprocess or import) inside each test function
- Do NOT have run-tests.sh pre-execute the program and save output to files, then have \
tests read those files. This creates stale-output traps when the agent fixes the code \
but run-tests.sh cached the old buggy output.
- run-tests.sh should ONLY set up the environment (install pytest, create input fixtures). \
It must NOT run the program being tested — let pytest do that.
- Each test should be independent — passing or failing on its own, not depending on \
shared state from other tests or from run-tests.sh
- Prefer behavioral assertions (exit code, parsed output, data structure checks) over \
exact string matching. Use "assert X in output" rather than "assert output == exact_string"

TASK INSTRUCTIONS (task.yaml):
- Describe WHAT the program should do and WHAT is wrong at a requirements level
- Do NOT specify exact line numbers, exact variable names to change, or exact diffs
- Good: "The CSV parser does not handle empty files gracefully — it should return an empty list"
- Bad: "Line 15: change `data.split(',')` to `csv.reader(data)`"
- The agent should need to READ the code and DIAGNOSE the bugs, not just apply a recipe

The code must be CORRECT — all tests must pass when run against this code.

{examples}

Return a JSON object: {{"files": {{"filename": "content", ...}}}}
Return ONLY the JSON object."""

PHASE2_PROMPT = """\
You are an expert at creating coding challenges. Given a WORKING program below, \
introduce exactly 3-4 independently discoverable bugs to create a debugging challenge.

BUG DESIGN — CRITICAL FOR CORRECT DIFFICULTY:
The solving agent (Claude Opus) will read the code, diagnose bugs, and rewrite the \
source file to fix them. To land in the "learnable" range (1-3 out of 5 attempts pass):

USE A MIX of bug types — some simple, some subtle:
- Simple bugs (agent finds ~80% of the time): wrong operator, wrong variable, missing \
return statement, off-by-one error, wrong function call
- Subtle bugs (agent finds ~30% of the time): missing edge case handling, wrong data \
structure choice, inverted conditional logic, missing validation step
- Include 1-2 simple bugs and 1-2 subtle bugs. The simple ones provide partial credit \
while the subtle ones create the difficulty gradient.

EACH BUG should break 1-2 tests, not all tests. If fixing bug A fixes tests 1-2 \
and fixing bug B fixes tests 3-4, the agent gets partial credit for finding either one. \
DO NOT create bugs where all tests fail if ANY single bug remains (e.g., avoid \
set -e in bash scripts where one unfixed bug crashes the whole script).

The bugs should:
- Each be INDEPENDENTLY discoverable — a failing test should point toward the specific \
bug that caused it, without needing to fix other bugs first
- Do NOT create cascading bugs where fixing Bug A is a prerequisite to diagnosing Bug B
- Stay in a SINGLE source file — do not spread bugs across multiple files
- NOT change tests, Dockerfile, run-tests.sh, or task.yaml
- Be fixable — the original working code IS the solution
- Produce CLEAR test failures (wrong output, wrong type, missing value)

CRITICAL — VERIFY YOUR WORK:
After introducing bugs, trace through EACH test function step by step:
1. Read the test assertion
2. Trace the code path with your buggy source files
3. Confirm the test WILL FAIL (wrong return value, exception, etc.)
4. Confirm each bug can be diagnosed INDEPENDENTLY from its test failure
5. Confirm that fixing any ONE bug allows at least 1-2 tests to pass (partial credit)

If a test would still pass with your buggy code, you MUST add another bug \
that breaks it. The test suite MUST exit non-zero.

Common mistakes to avoid:
- Introducing a bug in a code path that no test exercises
- Changing a variable name that's only used internally (no observable effect)
- Adding a bug that causes an import error (too obvious, agent fixes instantly)
- Creating cascading failures where one bug masks or blocks diagnosis of another
- Adding 5+ bugs (too many for the time limit — cap at 3-4)
- Making ALL bugs single-token changes (produces all-or-nothing difficulty)

Here is the working program:
```json
{working_json}
```

Return a JSON object with TWO keys:
1. "verification" — for each test function, one line: "test_name: WILL FAIL because [reason]" or "test_name: STILL PASSES — need another bug". Also indicate which bug breaks which tests.
2. "files" — ONLY the modified source files (buggy versions)

Example format:
{{"verification": "test_add: WILL FAIL because add() returns x-y instead of x+y (Bug 1)\\ntest_multiply: WILL FAIL because wrong variable used (Bug 2)\\ntest_divide: WILL FAIL because missing zero-division check (Bug 3)\\ntest_format: STILL PASSES — not affected by any bug", "files": {{"math.py": "buggy content..."}}}}"""


def generate_task_solution_first(
    topic: str,
    output_dir: str | None = None,
    model: str | None = None,
    target_category: str | None = None,
) -> dict:
    """Generate a task using solution-first strategy (two-phase).

    Phase 1: Generate a complete, WORKING program with tests.
    Phase 2: Introduce bugs into the source files to create the challenge.

    The working code from Phase 1 becomes solution.sh.
    The buggy code from Phase 2 becomes the source files.
    Tests, Dockerfile, run-tests.sh come from Phase 1 (unchanged).

    This approach has much higher functional validation pass rates because
    the solution is guaranteed correct — it was written first.
    """
    slug = _slugify(topic)

    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR, slug)

    os.makedirs(output_dir, exist_ok=True)

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )
    gen_model = model or GENERATOR_MODEL
    examples = select_examples(target_category=target_category, target_topic=topic)

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    start = time.time()

    # ── Phase 1: Generate working code ──
    print(f"Generating task (solution-first) for: {topic}")
    print(f"  Model: {gen_model}")
    print(f"  Phase 1: Generating working code...")
    phase1_prompt = PHASE1_PROMPT.format(topic=topic, examples=examples)

    phase1_messages = [
        {"role": "system", "content": "You write correct, well-tested code. Return only JSON."},
        {"role": "user", "content": phase1_prompt},
    ]

    working_files = None
    for parse_attempt in range(3):
        response1 = _api_call_with_retry(
            client, model=gen_model, messages=phase1_messages,
            temperature=0.5, max_tokens=8192,
        )
        if response1.usage:
            for k in total_usage:
                total_usage[k] += getattr(response1.usage, k, 0)
        try:
            working_files = _parse_response(response1.choices[0].message.content)
            break
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Phase 1 parse error (attempt {parse_attempt + 1}/3): {e}")
            if parse_attempt == 2:
                with open(os.path.join(output_dir, "_phase1_raw.txt"), "w") as f:
                    f.write(response1.choices[0].message.content)
                return {
                    "task_dir": output_dir,
                    "status": f"phase1_parse_error: {e}",
                    "model": gen_model,
                    "usage": total_usage,
                    "duration_sec": round(time.time() - start, 2),
                }

    print(f"  Phase 1 complete: {len(working_files)} files")

    # Build solution.sh from the working source files
    # (solution.sh writes the working versions of all source files)
    infrastructure = {"task.yaml", "Dockerfile", "run-tests.sh", "docker-compose.yaml"}
    source_files = {k: v for k, v in working_files.items()
                    if k not in infrastructure and not k.startswith("tests/")}

    solution_lines = ["#!/bin/bash", "", "# Solution: restore the working versions of all source files"]
    for filepath, content in sorted(source_files.items()):
        # Use heredoc to write each file
        solution_lines.append(f"cat > {filepath} << 'SOLUTION_EOF'")
        solution_lines.append(content)
        solution_lines.append("SOLUTION_EOF")
        solution_lines.append("")
    working_files["solution.sh"] = "\n".join(solution_lines)

    # ── Phase 2: Introduce bugs ──
    print(f"  Phase 2: Introducing bugs...")

    working_json = json.dumps({"files": working_files}, indent=2)
    phase2_prompt = PHASE2_PROMPT.format(working_json=working_json)
    sys_prompt = _format_prompt(SYSTEM_PROMPT)
    phase2_messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": phase2_prompt},
    ]

    buggy_files = None
    for parse_attempt in range(3):
        response2 = _api_call_with_retry(
            client, model=gen_model, messages=phase2_messages,
            temperature=0.7, max_tokens=8192,
        )
        if response2.usage:
            for k in total_usage:
                total_usage[k] += getattr(response2.usage, k, 0)
        try:
            buggy_files = _parse_response(response2.choices[0].message.content)
            break
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Phase 2 parse error (attempt {parse_attempt + 1}/3): {e}")
            if parse_attempt == 2:
                with open(os.path.join(output_dir, "_phase2_raw.txt"), "w") as f:
                    f.write(response2.choices[0].message.content)
                return {
                    "task_dir": output_dir,
                    "status": f"phase2_parse_error: {e}",
                    "model": gen_model,
                    "usage": total_usage,
                    "duration_sec": round(time.time() - start, 2),
                }

    print(f"  Phase 2 complete: {len(buggy_files)} buggy files")

    # Validate Phase 2 actually changed something — if buggy files are identical
    # to working files, Phase 2 didn't introduce real bugs. Retry immediately
    # without burning a Docker validation.
    actually_changed = False
    for filepath, content in buggy_files.items():
        if filepath in working_files and content != working_files[filepath]:
            actually_changed = True
            break
    if not actually_changed:
        print(f"  WARNING: Phase 2 returned identical files — no bugs introduced")

    # Validate Phase 2 only modified known source files (not infra/tests/new files)
    for filepath in buggy_files:
        if filepath not in working_files:
            print(f"  WARNING: Phase 2 introduced unknown file '{filepath}' — ignoring")
        elif filepath in infrastructure or filepath.startswith("tests/"):
            print(f"  WARNING: Phase 2 modified infrastructure/test file '{filepath}' — ignoring")

    # Merge: infrastructure + tests from phase 1, buggy source from phase 2
    final_files = dict(working_files)  # start with everything from phase 1
    for filepath, content in buggy_files.items():
        if filepath not in infrastructure and not filepath.startswith("tests/") and filepath in working_files:
            final_files[filepath] = content  # overwrite source with buggy version

    _write_task_files(final_files, output_dir)
    duration = time.time() - start

    result = {
        "task_dir": output_dir,
        "status": "success",
        "model": gen_model,
        "strategy": "solution_first",
        "topic": topic,
        "usage": total_usage,
        "duration_sec": round(duration, 2),
    }

    print(f"  Status: success (solution-first)")
    print(f"  Duration: {duration:.1f}s")
    print(f"  Tokens: {total_usage['total_tokens']}")

    return result


def regenerate_task(
    topic: str,
    task_dir: str,
    feedback: str,
    model: str | None = None,
) -> dict:
    """Regenerate a task using validation feedback.

    Uses TARGETED repair: analyzes the feedback to determine which files need
    fixing, then asks the LLM to regenerate only those files. This prevents
    the "whack-a-mole" problem where fixing one file introduces bugs in others.

    Repair strategies:
    - "tests fail after solution" → only regenerate solution.sh
    - "tests pass without solution" → only regenerate source files (buggy code)
    - "structural issues" → regenerate all files (full rebuild)

    Args:
        topic: The original topic string.
        task_dir: Path to the previously generated (broken) task.
        feedback: Validation error description (from structural or functional validator).
        model: Override the generator model.

    Returns:
        dict with task_dir, status, usage, and duration.
    """
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )
    gen_model = model or GENERATOR_MODEL

    # Read the previously generated files
    previous_files = {}
    task_path = Path(task_dir)
    for fpath in sorted(task_path.rglob("*")):
        if fpath.is_file() and not fpath.name.startswith("_"):
            rel = str(fpath.relative_to(task_path))
            try:
                previous_files[rel] = fpath.read_text()
            except UnicodeDecodeError:
                continue

    # Determine repair strategy from feedback
    feedback_lower = feedback.lower()
    if "docker" in feedback_lower and ("build failed" in feedback_lower or "build error" in feedback_lower):
        # Dockerfile issue — only fix the Dockerfile
        repair_target = "dockerfile_only"
        repair_instruction = (
            "The Docker image failed to build. Fix ONLY the Dockerfile to resolve the "
            "build error. Do NOT change any other files — the source code, tests, and "
            "solution are fine. Common issues: conflicting packages, missing dependencies, "
            "wrong base image.\n"
            "Return a JSON object: {\"files\": {\"Dockerfile\": \"...\"}}"
        )
    elif "timed out" in feedback_lower and "with solution" in feedback_lower:
        # Solution causes a hang/infinite loop — different from just failing tests
        repair_target = "solution_only"
        repair_instruction = (
            "The solution causes the program to HANG (timeout). This usually means:\n"
            "- An infinite loop in the fixed code (missing break/termination condition)\n"
            "- Blocking I/O (reading from stdin when no input is provided)\n"
            "- A server that starts but never exits\n\n"
            "Fix solution.sh to produce code that runs to completion without hanging. "
            "Check every loop for proper termination and ensure no blocking reads.\n"
            "Return a JSON object: {\"files\": {\"solution.sh\": \"...\"}}"
        )
    elif "tests failed" in feedback_lower and "with solution" in feedback_lower:
        # Only fix solution.sh — include failing test details
        repair_target = "solution_only"
        test_files = {k: v for k, v in previous_files.items() if k.startswith("tests/")}
        test_context = "\n\n".join(
            f"**{name}**:\n```\n{content}\n```" for name, content in test_files.items()
        )
        # Extract failing test names from feedback if available
        failing_tests = ""
        for line in feedback.split("\n"):
            if "FAILED" in line and "test_" in line:
                failing_tests += f"  {line.strip()}\n"
        failing_info = f"\nFailing tests:\n{failing_tests}" if failing_tests else ""

        repair_instruction = (
            "The source files and tests are correct, but solution.sh does not fix all bugs. "
            f"{failing_info}\n"
            f"Here are the tests — study which ones fail and why:\n{test_context}\n\n"
            "Return ONLY a corrected solution.sh that fixes ALL bugs in the source files. "
            "Carefully trace through every test case and verify your solution passes each one. "
            "Return a JSON object: {\"files\": {\"solution.sh\": \"...\"}}"
        )
    elif "tests passed" in feedback_lower and "without solution" in feedback_lower:
        # Source files don't have real bugs — fix the buggy source files
        repair_target = "source_only"
        infrastructure = {"task.yaml", "Dockerfile", "run-tests.sh", "solution.sh"}
        test_files = {k: v for k, v in previous_files.items() if k.startswith("tests/")}
        source_files = [f for f in previous_files
                        if f not in infrastructure and not f.startswith("tests/")]
        # Include test code so the LLM knows what to break
        test_context = "\n\n".join(
            f"**{name}**:\n```\n{content}\n```" for name, content in test_files.items()
        )
        repair_instruction = (
            "The tests pass without solution.sh being applied, meaning the source files don't "
            "have real bugs. You MUST introduce bugs into the source files that cause the tests "
            "to FAIL.\n\n"
            f"Here are the test functions — study them to understand what to break:\n{test_context}\n\n"
            "For each test function, identify what it checks and introduce a bug in the source "
            "code that makes THAT specific check fail. Common approaches:\n"
            "- Wrong return values or calculations\n"
            "- Off-by-one errors in loops or indexing\n"
            "- Missing or incorrect error handling\n"
            "- Wrong variable names or swapped arguments\n"
            "- Incorrect string formatting or parsing\n\n"
            "Do NOT change tests, task.yaml, Dockerfile, run-tests.sh, or solution.sh.\n"
            f"Return a JSON object with only these source files: {source_files}"
        )
    else:
        # Full rebuild for structural issues or unclear problems
        repair_target = "full"
        repair_instruction = (
            "Return the complete corrected task as a JSON object with ALL files. "
            "Make sure: (1) Tests FAIL on the unsolved container, "
            "(2) solution.sh PASSES all tests, "
            "(3) All file paths are consistent."
        )

    # For Dockerfile fixes, only send the Dockerfile + error (self-contained).
    # For solution/source fixes, send full context — the LLM needs to see all
    # files to understand the relationships between source, tests, and solution.
    if repair_target == "dockerfile_only":
        context_files = {k: v for k, v in previous_files.items() if k == "Dockerfile"}
    else:
        context_files = previous_files

    context_json = json.dumps({"files": context_files}, indent=2)

    feedback_prompt = f"""The task you generated for "{topic}" failed validation:

{feedback}

Here are the relevant files:
```json
{context_json}
```

{repair_instruction}

Return ONLY the JSON object."""

    print(f"  Repairing ({repair_target}) with feedback ({len(feedback)} chars)...")
    print(f"  Model: {gen_model}")

    start = time.time()
    # Always use SYSTEM_PROMPT (Variant A) for repairs regardless of how the task
    # was originally generated — full constraints are more useful than trimmed
    # examples when the LLM needs to fix a specific structural/functional issue.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": feedback_prompt},
    ]

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    status = None

    for parse_attempt in range(3):
        response = _api_call_with_retry(
            client,
            model=gen_model,
            messages=messages,
            temperature=0.3,  # Lower temp for repairs — we want precision
            max_tokens=4096,
        )

        response_text = response.choices[0].message.content
        if response.usage:
            for k in usage:
                usage[k] += getattr(response.usage, k, 0)

        try:
            files = _parse_response(response_text)

            if repair_target == "full":
                # Clear old files and write all new ones
                for item in task_path.iterdir():
                    if item.name.startswith("_"):
                        continue
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                _write_task_files(files, task_dir)
            else:
                # Targeted repair: only overwrite the returned files
                _write_task_files(files, task_dir)

            status = "success"
            break
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            if parse_attempt < 2:
                # Ask Sonnet to fix its JSON
                print(f"  Parse attempt {parse_attempt + 1} failed: {e} — retrying...")
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": (
                    f"Your response was not valid JSON. Error: {e}\n"
                    "Return ONLY a raw JSON object starting with { and ending with }. "
                    "No markdown fences, no explanation, just the JSON."
                )})
            else:
                status = f"parse_error: {e}"
                with open(os.path.join(task_dir, "_retry_raw_response.txt"), "w") as f:
                    f.write(response_text)

    duration = time.time() - start

    result = {
        "task_dir": task_dir,
        "status": status,
        "model": gen_model,
        "usage": usage,
        "duration_sec": round(duration, 2),
    }

    print(f"  Retry status: {status}")
    print(f"  Retry duration: {duration:.1f}s")

    return result


def _apply_surgical_edits(task_dir: str, edits: list[dict]) -> tuple[int, list[str]]:
    """Apply surgical string-replacement edits to task files.

    Each edit is {"file": "relative/path", "old": "exact old text", "new": "replacement text"}.
    For deletions, "new" can be empty string.

    Returns (applied_count, errors).
    """
    applied = 0
    errors = []
    task_path = Path(task_dir)

    for i, edit in enumerate(edits):
        fpath = edit.get("file", "")
        old = edit.get("old", "")
        new = edit.get("new", "")

        if not fpath:
            errors.append(f"Edit {i}: missing 'file' key")
            continue
        if old == "" and new == "":
            errors.append(f"Edit {i}: both 'old' and 'new' are empty")
            continue

        full_path = task_path / fpath
        if not full_path.exists():
            errors.append(f"Edit {i}: file '{fpath}' does not exist")
            continue

        try:
            content = full_path.read_text()
        except UnicodeDecodeError:
            errors.append(f"Edit {i}: cannot read '{fpath}' as text")
            continue

        # Normalize whitespace for matching: strip trailing spaces per line
        # but preserve the exact replacement
        if old not in content:
            # Try with normalized line endings
            old_normalized = old.replace("\r\n", "\n")
            if old_normalized in content:
                old = old_normalized
            else:
                errors.append(
                    f"Edit {i}: exact match for 'old' not found in '{fpath}' "
                    f"(old starts with: {old[:80]!r}...)"
                )
                continue

        count = content.count(old)
        if count > 1:
            errors.append(
                f"Edit {i}: 'old' matches {count} times in '{fpath}' — "
                f"need unique match (old starts with: {old[:80]!r}...)"
            )
            continue

        content = content.replace(old, new, 1)
        full_path.write_text(content)
        applied += 1
        print(f"    Edit {i}: applied to {fpath} ({len(old)} chars -> {len(new)} chars)")

    return applied, errors


def adjust_difficulty(
    topic: str,
    task_dir: str,
    classification: str,
    pass_rate: float,
    model: str | None = None,
    adjustment_history: list[tuple[str, float]] | None = None,
) -> dict:
    """Adjust task difficulty with surgical edits (not full regeneration).

    Uses constrained string-replacement edits to preserve test/code alignment.
    For too_hard: remove a bug, add hints, or simplify a bug.
    For too_easy: add a bug, make bugs subtler, or remove hints.

    Args:
        topic: The original topic string.
        task_dir: Path to the task directory.
        classification: "too_hard" or "too_easy".
        pass_rate: Opus pass rate (0.0 to 1.0).
        model: Override the generator model.
        adjustment_history: List of (classification, pass_rate) from prior rounds,
            e.g. [("too_hard", 0.0), ("too_easy", 0.8)]. Helps Sonnet calibrate
            when it overshoots in one direction.

    Returns:
        dict with task_dir, status, usage, and duration.
    """
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )
    gen_model = model or GENERATOR_MODEL

    # Read current task files
    previous_files = {}
    task_path = Path(task_dir)
    for fpath in sorted(task_path.rglob("*")):
        if fpath.is_file() and not fpath.name.startswith("_"):
            rel = str(fpath.relative_to(task_path))
            try:
                previous_files[rel] = fpath.read_text()
            except UnicodeDecodeError:
                continue

    previous_json = json.dumps({"files": previous_files}, indent=2)

    if classification == "too_hard":
        # Distinguish severity: 0/5 with 0 tests passing needs aggressive changes,
        # while 0/5 but close (agent got some tests) needs just a nudge
        passes_int = int(pass_rate * 5) if pass_rate else 0

        if passes_int == 0:
            # Agent solved NOTHING — task is fundamentally too hard
            adjustment_instruction = (
                f"This task is WAY TOO HARD. An expert AI agent (Claude Opus) scored 0% "
                f"(0 out of 5 attempts, 0 tests passing in any attempt). "
                f"The target is 1-3 out of 5 passes (~20-60%).\n\n"
                "The agent couldn't solve ANY bugs. Removing one test won't help. "
                "You need to make the bugs MUCH more obvious.\n\n"
                "Apply ALL of these changes (not just one):\n\n"
                "1. SIMPLIFY THE HARDEST BUG — replace it with something obvious:\n"
                "   - Change a subtle off-by-one to a clearly wrong variable name\n"
                "   - Change a logic error to a missing function call\n"
                "   - Make the bug produce a clear, descriptive error message\n\n"
                "2. ADD CODE COMMENTS near each remaining bug like:\n"
                "   # BUG: this comparison should use > not >=\n"
                "   # FIXME: wrong variable used here\n\n"
                "3. IMPROVE task.yaml instruction — add the exact function name and\n"
                "   describe the symptom for each bug\n\n"
                "4. REMOVE ONE TEST if there are more than 5 tests\n\n"
                "CRITICAL RULES:\n"
                "- Do NOT rename any functions, classes, variables, or files\n"
                "- Do NOT restructure or rewrite code — only targeted edits\n"
                "- Do NOT change run-tests.sh or Dockerfile\n"
                "- Update solution.sh to match any bug changes\n"
                "- Each edit must use EXACT string matching from the current file content\n"
            )
        else:
            # Agent got some tests but not enough — surgical nudge
            adjustment_instruction = (
                f"This task is TOO HARD. An expert AI agent (Claude Opus) scored {pass_rate:.0%} "
                f"({passes_int} out of 5 attempts passed). The target is 1-3 out of 5 passes (~20-60%).\n\n"
                "The agent is CLOSE — pick ONE surgical operation:\n\n"
                "OPTION A — REMOVE ONE BUG:\n"
                "  - Identify the hardest bug in the source code\n"
                "  - Fix that bug in the source file (revert it to correct code)\n"
                "  - Remove the corresponding test function that tested for that bug\n"
                "  - Remove the fix for that bug from solution.sh\n"
                "  - Update task.yaml instructions to describe fewer bugs\n\n"
                "OPTION B — ADD HINTS:\n"
                "  - Add the exact function name and line number for each bug to task.yaml instructions\n"
                "  - Add a comment near each bug in the source code hinting at the issue\n"
                "  - Do NOT change any test code\n\n"
                "OPTION C — SIMPLIFY ONE BUG:\n"
                "  - Make the subtlest bug more obvious (e.g., change an off-by-one to a clearly wrong value)\n"
                "  - Update solution.sh to match the simplified bug\n"
                "  - Do NOT change any test code or other bugs\n\n"
                "CRITICAL RULES:\n"
                "- Do NOT rename any functions, classes, variables, or files\n"
                "- Do NOT restructure or rewrite code — only targeted edits\n"
                "- Do NOT change the test file except to delete an entire test function (Option A only)\n"
                "- Do NOT change run-tests.sh or Dockerfile\n"
                "- Each edit must use EXACT string matching from the current file content\n"
            )
    else:  # too_easy
        adjustment_instruction = (
            f"This task is TOO EASY. An expert AI agent (Claude Opus) scored {pass_rate:.0%} "
            f"({int(pass_rate * 5)} out of 5 attempts passed). The target is 1-3 out of 5 passes (~20-60%).\n\n"
            "You must make the task HARDER using ONE surgical operation. Pick exactly one:\n\n"
            "OPTION A — ADD ONE BUG:\n"
            "  - Add a subtle new bug to the source file (off-by-one, wrong operator, etc.)\n"
            "  - Add a test function that catches the new bug\n"
            "  - Add a fix for the new bug to solution.sh\n"
            "  - Update task.yaml to mention the new bug\n\n"
            "OPTION B — MAKE A BUG SUBTLER:\n"
            "  - Pick the most obvious bug and make it harder to spot\n"
            "  - E.g., change a wrong variable name to an off-by-one in a correct-looking expression\n"
            "  - Update solution.sh to match the new bug\n"
            "  - Do NOT change any test code\n\n"
            "OPTION C — REMOVE HINTS:\n"
            "  - Strip helpful comments near bugs in the source code\n"
            "  - Make task.yaml instructions less specific (remove line numbers, function names)\n"
            "  - Do NOT change any test code or solution.sh\n\n"
            "CRITICAL RULES:\n"
            "- Do NOT rename any functions, classes, variables, or files\n"
            "- Do NOT restructure or rewrite code — only targeted edits\n"
            "- Do NOT change run-tests.sh or Dockerfile\n"
            "- Each edit must use EXACT string matching from the current file content\n"
        )

    # Add overshoot context if we've bounced between too_hard and too_easy
    overshoot_context = ""
    if adjustment_history and len(adjustment_history) >= 1:
        prev_classifications = [c for c, _ in adjustment_history]
        if classification == "too_easy" and "too_hard" in prev_classifications:
            overshoot_context = (
                "\n⚠️ OVERSHOOT WARNING: This task was previously too_hard, and your last "
                "adjustment made it too_easy. You need to find the MIDDLE GROUND — make it "
                "slightly harder than it is now, but not as hard as it was before. "
                "History: " + " → ".join(f"{c} ({r:.0%})" for c, r in adjustment_history) +
                f" → {classification} ({pass_rate:.0%})\n"
            )
        elif classification == "too_hard" and "too_easy" in prev_classifications:
            overshoot_context = (
                "\n⚠️ OVERSHOOT WARNING: This task was previously too_easy, and your last "
                "adjustment made it too_hard. You need to find the MIDDLE GROUND — make it "
                "slightly easier than it is now, but not as easy as it was before. "
                "History: " + " → ".join(f"{c} ({r:.0%})" for c, r in adjustment_history) +
                f" → {classification} ({pass_rate:.0%})\n"
            )

    prompt = f"""The task for "{topic}" needs difficulty adjustment.
{overshoot_context}
{adjustment_instruction}

Here are the current task files:
```json
{previous_json}
```

Return a JSON object describing your surgical edits:
{{
  "operation": "remove_bug" | "add_hints" | "simplify_bug" | "add_bug" | "make_subtler" | "remove_hints",
  "reasoning": "Brief explanation of what you're changing and why",
  "edits": [
    {{
      "file": "relative/path/to/file",
      "old": "EXACT text to find in the file (copy-paste from above, whitespace-sensitive)",
      "new": "replacement text (use empty string to delete)"
    }}
  ]
}}

IMPORTANT:
- The "old" field must be an EXACT substring from the file content shown above — copy it character-for-character
- Include enough context in "old" to be unique within the file (at least 2-3 lines)
- Return ONLY the JSON object, no markdown fences, no explanation outside the JSON"""

    print(f"  Adjusting difficulty ({classification}, pass_rate={pass_rate:.0%})...")
    print(f"  Model: {gen_model}")

    start = time.time()
    messages = [
        {"role": "system", "content": "You are a precise code editor. You make minimal, surgical changes to code. You never rewrite or restructure — you make the smallest edit that achieves the goal."},
        {"role": "user", "content": prompt},
    ]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    status = None

    for parse_attempt in range(3):
        response = _api_call_with_retry(
            client, model=gen_model, messages=messages,
            temperature=0.3, max_tokens=4096,
        )

        response_text = response.choices[0].message.content
        if response.usage:
            for k in usage:
                usage[k] += getattr(response.usage, k, 0)

        try:
            # Parse the surgical edit response
            text = _strip_fences(response_text)

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                brace_start = text.find("{")
                brace_end = text.rfind("}")
                if brace_start != -1 and brace_end != -1:
                    data = json.loads(text[brace_start : brace_end + 1])
                else:
                    raise

            operation = data.get("operation", "unknown")
            reasoning = data.get("reasoning", "")
            edits = data.get("edits", [])

            if not edits:
                raise ValueError("No edits provided in response")

            print(f"  Operation: {operation}")
            print(f"  Reasoning: {reasoning[:120]}...")
            print(f"  Edits: {len(edits)}")

            # Save raw response for debugging
            with open(os.path.join(task_dir, "_adjust_raw_response.txt"), "w") as f:
                f.write(response_text)

            # Apply the surgical edits
            applied, errors = _apply_surgical_edits(task_dir, edits)

            if errors:
                print(f"  Edit errors: {errors}")

            if applied == 0:
                if parse_attempt < 2:
                    print(f"  No edits applied — retrying (attempt {parse_attempt + 1})...")
                    messages.append({"role": "assistant", "content": response_text})
                    error_detail = "; ".join(errors[:3])
                    messages.append({"role": "user", "content": (
                        f"None of your edits could be applied. Errors:\n{error_detail}\n\n"
                        "The 'old' field must be an EXACT character-for-character substring "
                        "from the file content I showed you. Copy it precisely, including "
                        "all whitespace, newlines, and indentation. Try again with the "
                        "same operation but corrected 'old' strings."
                    )})
                    continue
                else:
                    status = f"no_edits_applied: {'; '.join(errors[:3])}"
                    break
            else:
                print(f"  Successfully applied {applied}/{len(edits)} edits")
                status = "success"
                break

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            if parse_attempt < 2:
                print(f"  Parse attempt {parse_attempt + 1} failed: {e} — retrying...")
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": (
                    f"Your response was not valid JSON. Error: {e}\n"
                    "Return ONLY a raw JSON object starting with {{ and ending with }}. "
                    "No markdown fences, no explanation, just the JSON."
                )})
            else:
                status = f"parse_error: {e}"
                with open(os.path.join(task_dir, "_adjust_raw_response.txt"), "w") as f:
                    f.write(response_text)

    duration = time.time() - start

    result = {
        "task_dir": task_dir,
        "status": status,
        "model": gen_model,
        "usage": usage,
        "duration_sec": round(duration, 2),
    }

    print(f"  Adjustment status: {status}")
    print(f"  Adjustment duration: {duration:.1f}s")

    return result


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "fix a broken Python script"
    result = generate_task(topic)
    if result:
        print(f"\nGenerated task at: {result['task_dir']}")
        print(json.dumps(result, indent=2))
