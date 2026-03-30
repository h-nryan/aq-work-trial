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

from openai import OpenAI

API_MAX_RETRIES = 3
API_RETRY_DELAY = 5  # seconds, doubles each retry

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


# Instruction hint styles for task.yaml — controls how much the instruction
# reveals about bug locations. Affects difficulty: full hints make tasks easier.
HINT_RULES = {
    "none": {
        "long": (
            "8. The instruction in task.yaml should describe WHAT the program does and "
            "WHAT the expected behavior is, but should NOT hint at where the bugs are or "
            "what's broken. The agent should have to read the code to find the bugs."
        ),
        "short": (
            "task.yaml instruction should describe what the program does and expected "
            "behavior, but NOT hint at where bugs are"
        ),
    },
    "soft": {
        "long": (
            "8. The instruction in task.yaml should describe what the program does, its "
            "expected behavior, and a HIGH-LEVEL hint about what area is broken — e.g. "
            "\"the output formatting and error handling have issues\" — but NOT name specific "
            "functions, variables, or line numbers. The agent should know roughly WHERE to "
            "look but still have to figure out WHAT is wrong."
        ),
        "short": (
            "task.yaml instruction should describe expected behavior and give a high-level "
            "hint about what area is broken (NOT specific functions or lines)"
        ),
    },
    "full": {
        "long": (
            "8. The instruction in task.yaml MUST hint at what areas have bugs — e.g. "
            "\"the delimiter handling and header parsing have issues\" or \"there are bugs in "
            "the sorting logic and edge case handling.\" The agent only reads the instruction "
            "and source code ONCE before attempting a fix, so vague instructions like "
            "\"fix the bugs\" make the task too hard."
        ),
        "short": (
            "task.yaml instruction MUST hint at specific bug areas (e.g. \"the delimiter "
            "handling has issues\")"
        ),
    },
}


def _api_call_with_retry(client: OpenAI, **kwargs) -> object:
    """Call the OpenAI chat completions API with retry on transient failures.

    Retries on network errors, malformed responses, and server errors.
    Does NOT retry on auth errors or invalid requests (4xx).
    """
    last_error = None
    for attempt in range(API_MAX_RETRIES):
        try:
            return client.chat.completions.create(**kwargs)
        except (json.JSONDecodeError, ConnectionError, TimeoutError) as e:
            last_error = e
            delay = API_RETRY_DELAY * (2 ** attempt)
            print(f"  API error (attempt {attempt + 1}/{API_MAX_RETRIES}): {e}")
            print(f"  Retrying in {delay}s...")
            time.sleep(delay)
        except Exception as e:
            # Don't retry on auth errors, bad requests, etc.
            err_str = str(e).lower()
            if any(code in err_str for code in ("401", "403", "422", "invalid")):
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
DEFAULT_EXAMPLE_TOKEN_BUDGET = 20000


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
    token_budget: int = DEFAULT_EXAMPLE_TOKEN_BUDGET,
) -> str:
    """Select examples using _meta.yaml metadata, optimizing for diversity and relevance.

    Selection algorithm:
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

    # Phase 1: category diversity — one example per category
    selected = []
    selected_tokens = 0
    seen_categories = set()

    # Sort candidates by score for each category
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

    # Phase 2: fill remaining budget with highest-scored remaining candidates
    remaining = [
        (td, m, c) for td, m, c in candidates
        if (td, m, c) not in selected
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

# Variant B: trimmed prompt — fewer explicit constraints, relies on examples
SYSTEM_PROMPT_B = """\
You are an expert at creating coding tasks for evaluating AI agents. You generate \
Terminal Bench tasks — self-contained coding challenges that run in Docker containers \
and are verified by pytest.

REQUIRED FILES: task.yaml, Dockerfile, run-tests.sh, solution.sh, tests/test_outputs.py, plus buggy source files.
- solution.sh uses `cat > filename << 'EOF'` heredocs to write complete fixed files.
- Dockerfile MUST install tmux and asciinema. Prefer Python/Bash/C stacks.
- ALL source files must live in WORKDIR (usually /app). Never use system directories like /etc/.
- Tests MUST FAIL before solution.sh and PASS after.
- run-tests.sh installs uv + pytest. Follow the boilerplate from examples.

DIFFICULTY — THE MOST IMPORTANT THING:
Study the examples below. They show EXACTLY the right difficulty. Match them:
- Put all bugs in ONE source file under 150 lines
- 3-4 bugs that each produce a clear, distinct test failure
- 5-7 tests total (not 9-11) — fewer tests with clear criteria give margin for implementation differences
- {instruction_hint_rule_short}
- The examples show what "learnable" looks like. Copy their style, not just their format.

OUTPUT FORMAT:
Return ONLY a raw JSON object: {{"files": {{"filename": "content", ...}}}}
Start with {{ and end with }}. No markdown fences."""

PHASE2_PROMPT_B = """\
Given this WORKING program, introduce exactly 3-4 bugs in the source file(s) only.

Rules:
- Bugs must be realistic (off-by-one, wrong variable, missing edge case, wrong operator)
- Do NOT change tests, Dockerfile, run-tests.sh, or task.yaml
- Each bug should cause at least one test to fail with a clear error message
- The original working code IS the solution

VERIFY: For each test, confirm it WILL FAIL with your buggy code. If any test still \
passes, add another bug that breaks it.

Here is the working program:
```json
{working_json}
```

Return JSON with two keys:
1. "verification" — one line per test: "test_name: WILL FAIL because [reason]"
2. "files" — ONLY the modified source files (buggy versions)"""


def _build_user_prompt(topic: str, variant: str = "A", target_category: str | None = None) -> str:
    """Build the user prompt with topic and examples."""
    examples = select_examples(target_category=target_category)

    if variant == "B":
        # Trimmed variant: examples do the teaching, minimal reminders
        return f"""Generate a Terminal Bench task for this topic: "{topic}"

Study these examples — they define the target difficulty and format:

{examples}

Generate a task for: "{topic}"
Match the examples' difficulty closely. Return ONLY the JSON object."""

    # Variant A: verbose reminders (default)
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


def _parse_response(response_text: str) -> dict:
    """Parse the LLM response to extract files dict.

    Handles: raw JSON, JSON in markdown fences (even when content contains ```),
    and JSON embedded in surrounding text.
    """
    text = response_text.strip()

    # Strategy 1: Strip leading/trailing markdown fences if present.
    # Can't use regex with .*? because the JSON content may itself contain ```
    # (e.g. code blocks inside task.yaml instructions).
    if text.startswith("```"):
        # Remove opening fence line
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
        # Remove closing fence (last ```)
        last_fence = text.rfind("```")
        if last_fence != -1:
            text = text[:last_fence]
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Strategy 2: find outermost { ... } braces
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
        full_path = os.path.join(output_dir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

        # Make shell scripts executable
        if filepath.endswith(".sh"):
            os.chmod(full_path, 0o755)


def _format_prompt(template: str, hint_style: str = "none", variant: str = "A") -> str:
    """Fill hint-style placeholders in a system prompt template."""
    rules = HINT_RULES.get(hint_style, HINT_RULES["none"])
    result = template.replace("{instruction_hint_rule}", rules["long"])
    result = result.replace("{instruction_hint_rule_short}", rules["short"])
    return result


def generate_task(
    topic: str,
    output_dir: str | None = None,
    model: str | None = None,
    prompt_variant: str = "A",
    hint_style: str = "none",
    target_category: str | None = None,
) -> dict:
    """Generate a Terminal Bench task for the given topic.

    Args:
        topic: A short description of the task to generate.
        output_dir: Where to write the generated task files.
        model: Override the generator model.
        prompt_variant: "A" (verbose constraints) or "B" (trimmed, example-driven).
        hint_style: "none", "soft", or "full" — controls instruction hints.

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
    raw_prompt = SYSTEM_PROMPT_B if prompt_variant == "B" else SYSTEM_PROMPT
    sys_prompt = _format_prompt(raw_prompt, hint_style=hint_style, variant=prompt_variant)
    user_prompt = _build_user_prompt(topic, variant=prompt_variant, target_category=target_category)

    print(f"Generating task for: {topic}")
    print(f"  Model: {gen_model}  |  Prompt variant: {prompt_variant}")
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
            temperature=0.7, max_tokens=32000,
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
1. All source files (working, bug-free code)
2. A Dockerfile (Ubuntu-based, include `tmux asciinema` in apt-get install)
3. A run-tests.sh (use the uv + pytest boilerplate from examples)
4. A tests/test_outputs.py with 6-10 thorough test functions that all PASS
5. A task.yaml with instruction, difficulty: medium, category, tags, parser_name: pytest

The code must be CORRECT — all tests must pass when run against this code.

{examples}

Return a JSON object: {{"files": {{"filename": "content", ...}}}}
Return ONLY the JSON object."""

PHASE2_PROMPT = """\
You are an expert at creating coding challenges. Given a WORKING program below, \
introduce exactly 3-4 independently discoverable bugs to create a debugging challenge.

The bugs should:
- Be realistic (off-by-one, wrong variable, missing edge case, type error, bad config)
- Each be INDEPENDENTLY discoverable — a failing test should point toward the specific \
bug that caused it, without needing to fix other bugs first
- Do NOT create cascading bugs where fixing Bug A is a prerequisite to diagnosing Bug B
- Stay in a SINGLE source file — do not spread bugs across multiple files
- NOT change tests, Dockerfile, run-tests.sh, or task.yaml
- Be fixable — the original working code IS the solution
- Produce CLEAR test failures (wrong output, wrong type, missing value) — avoid bugs \
that cause undefined behavior, segfaults, or intermittent failures

CRITICAL — VERIFY YOUR WORK:
After introducing bugs, trace through EACH test function step by step:
1. Read the test assertion
2. Trace the code path with your buggy source files
3. Confirm the test WILL FAIL (wrong return value, exception, etc.)
4. Confirm each bug can be diagnosed INDEPENDENTLY from its test failure

If a test would still pass with your buggy code, you MUST add another bug \
that breaks it. The test suite MUST exit non-zero.

Common mistakes to avoid:
- Introducing a bug in a code path that no test exercises
- Changing a variable name that's only used internally (no observable effect)
- Adding a bug that causes an import error (too obvious, agent fixes instantly)
- Creating cascading failures where one bug masks or blocks diagnosis of another
- Adding 5+ bugs (too many for the time limit — cap at 3-4)

Here is the working program:
```json
{working_json}
```

Return a JSON object with TWO keys:
1. "verification" — for each test function, one line: "test_name: WILL FAIL because [reason]" or "test_name: STILL PASSES — need another bug"
2. "files" — ONLY the modified source files (buggy versions)

Example format:
{{"verification": "test_add: WILL FAIL because add() returns x-y instead of x+y\\ntest_multiply: WILL FAIL because wrong variable used", "files": {{"math.py": "buggy content..."}}}}"""


def generate_task_solution_first(
    topic: str,
    output_dir: str | None = None,
    model: str | None = None,
    prompt_variant: str = "A",
    hint_style: str = "none",
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

    prompt_variant: "A" (verbose constraints) or "B" (trimmed, example-driven).
    hint_style: "none", "soft", or "full" — controls instruction hints.
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
    examples = select_examples(target_category=target_category)

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
            temperature=0.5, max_tokens=32000,
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
    p2_template = PHASE2_PROMPT_B if prompt_variant == "B" else PHASE2_PROMPT
    phase2_prompt = p2_template.format(working_json=working_json)
    raw_prompt = SYSTEM_PROMPT_B if prompt_variant == "B" else SYSTEM_PROMPT
    sys_prompt = _format_prompt(raw_prompt, hint_style=hint_style, variant=prompt_variant)
    phase2_messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": phase2_prompt},
    ]

    buggy_files = None
    for parse_attempt in range(3):
        response2 = _api_call_with_retry(
            client, model=gen_model, messages=phase2_messages,
            temperature=0.7, max_tokens=16000,
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

    # Merge: infrastructure + tests from phase 1, buggy source from phase 2
    final_files = dict(working_files)  # start with everything from phase 1
    for filepath, content in buggy_files.items():
        if filepath not in infrastructure and not filepath.startswith("tests/"):
            final_files[filepath] = content  # overwrite source with buggy version

    _write_task_files(final_files, output_dir)
    duration = time.time() - start

    result = {
        "task_dir": output_dir,
        "status": "success",
        "model": gen_model,
        "strategy": "solution_first",
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

    previous_json = json.dumps({"files": previous_files}, indent=2)

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
    elif "tests failed" in feedback_lower and "with solution" in feedback_lower:
        # Only fix solution.sh — source files and tests are fine
        repair_target = "solution_only"
        repair_instruction = (
            "The source files and tests are correct, but solution.sh does not fix all bugs. "
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
            max_tokens=32000,
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


def adjust_difficulty(
    topic: str,
    task_dir: str,
    classification: str,
    pass_rate: float,
    model: str | None = None,
) -> dict:
    """Adjust task difficulty based on evaluation results.

    When a task is too_hard (0/5 Opus passes) or too_easy (4-5/5), this
    modifies the source files and solution to shift difficulty toward the
    learnable range (1-3/5).

    Strategy:
    - too_hard: Simplify — remove 1-2 bugs, make remaining bugs more obvious,
      reduce file count, add hints in error messages
    - too_easy: Harden — add subtle bugs, introduce interactions between bugs,
      add edge cases, make error messages less obvious

    Args:
        topic: The original topic string.
        task_dir: Path to the task directory.
        classification: "too_hard" or "too_easy".
        pass_rate: Opus pass rate (0.0 to 1.0).
        model: Override the generator model.

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
        adjustment_instruction = (
            f"This task is TOO HARD. An expert AI agent (Claude Opus) scored {pass_rate:.0%} "
            f"(0 out of 5 attempts passed). The target is 1-3 out of 5 passes (~20-60%).\n\n"
            "Make the task EASIER — focus on bug DISCOVERABILITY, not quantity:\n"
            "- Make bug symptoms more obvious (clear error messages, stack traces that point to the right file)\n"
            "- Move bugs from edge cases to common code paths (fail on normal inputs, not just corner cases)\n"
            "- Reduce indirection — bugs should be in the same file as the symptoms, not hidden across files\n"
            "- Replace subtle logic bugs (operator precedence, off-by-one) with more obvious ones (wrong variable, missing check)\n"
            "- Keep the same number of bugs if they're now individually easier to find\n"
            "- Update solution.sh to match any changes\n"
            "- Tests must still FAIL before solution and PASS after\n\n"
            "Return the complete adjusted task as a JSON object with ALL files."
        )
    else:  # too_easy
        adjustment_instruction = (
            f"This task is TOO EASY. An expert AI agent (Claude Opus) scored {pass_rate:.0%} "
            f"({int(pass_rate * 5)} out of 5 attempts passed). The target is 1-3 out of 5 passes (~20-60%).\n\n"
            "Make the task HARDER — focus on bug SUBTLETY, not quantity:\n"
            "- Make bug symptoms misleading (error appears in file A, root cause is in file B)\n"
            "- Move bugs from obvious code paths to edge cases (only fail with specific inputs)\n"
            "- Add indirection — require tracing data flow across multiple functions/files to find the bug\n"
            "- Replace obvious bugs (wrong variable name) with subtle ones (off-by-one, wrong operator, race condition)\n"
            "- Make error messages point to the wrong location\n"
            "- Update solution.sh to fix any new bugs too\n"
            "- Tests must still FAIL before solution and PASS after\n\n"
            "Return the complete adjusted task as a JSON object with ALL files."
        )

    prompt = f"""The task for "{topic}" needs difficulty adjustment.

{adjustment_instruction}

Here is the current task:
```json
{previous_json}
```

Return ONLY the JSON object with all files."""

    print(f"  Adjusting difficulty ({classification}, pass_rate={pass_rate:.0%})...")
    print(f"  Model: {gen_model}")

    start = time.time()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    status = None

    for parse_attempt in range(3):
        response = _api_call_with_retry(
            client, model=gen_model, messages=messages,
            temperature=0.5, max_tokens=32000,
        )

        response_text = response.choices[0].message.content
        if response.usage:
            for k in usage:
                usage[k] += getattr(response.usage, k, 0)

        try:
            files = _parse_response(response_text)
            # Full replacement — difficulty adjustment changes everything
            for item in task_path.iterdir():
                if item.name.startswith("_"):
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            _write_task_files(files, task_dir)
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
