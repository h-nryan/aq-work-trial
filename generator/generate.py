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
    OUTPUT_DIR,
)


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


def _load_examples() -> str:
    """Load all example tasks as few-shot context for the generator."""
    examples = []
    examples_path = Path(EXAMPLES_DIR)

    for task_dir in sorted(examples_path.iterdir()):
        if not task_dir.is_dir():
            continue

        example_parts = [f"### Example: {task_dir.name}\n"]

        # Read all files in the task directory
        for fpath in sorted(task_dir.rglob("*")):
            if fpath.is_file() and not fpath.name.startswith("."):
                rel = fpath.relative_to(task_dir)
                try:
                    content = fpath.read_text()
                    example_parts.append(f"**{rel}**\n```\n{content}\n```\n")
                except UnicodeDecodeError:
                    continue  # skip binary files

        examples.append("\n".join(example_parts))

    return "\n---\n\n".join(examples)


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

MOST IMPORTANT — AVOID THESE COMMON FAILURES:
A. Tests MUST actually FAIL before solution.sh runs. The source files must have REAL bugs that cause test failures. If you write source code that already works, the task is broken. Verify mentally: "will running these tests against the buggy source files produce failures?"
B. solution.sh must fix ALL bugs, not just some. Mentally trace every test case through your solution and verify it passes.
C. solution.sh must write COMPLETE fixed files (using heredocs), not patches. It should be self-contained.
D. Keep the technology stack simple — prefer Python, Bash, C. Avoid Node.js/npm unless the topic requires it, as npm installs are slow and fragile in containers.
E. Dockerfile WORKDIR must match paths used in source files, tests, and solution.sh.
F. Tests should test concrete outputs (file contents, exit codes, stdout) not require running servers. Server-based tasks are harder to validate reliably.

DIFFICULTY CALIBRATION (CRITICAL):
These tasks will be solved by a very capable AI agent (Claude Opus). To land in the \
learnable range (1-3 out of 5 attempts pass), aim for:
- Include 3-5 distinct bugs or issues that interact with each other
- Use subtle bugs: off-by-one errors, type mismatches, missing edge cases, wrong variable references
- Require understanding of the FULL codebase to fix (not just one file)
- Include environment/dependency issues alongside code bugs
- Make some bugs only visible through specific test cases (edge cases)
- The task should take a skilled human 20-60 minutes
- Do NOT make it impossible — a capable agent should solve it ~40-60% of the time

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


def _build_user_prompt(topic: str) -> str:
    """Build the user prompt with topic and examples."""
    examples = _load_examples()
    return f"""Generate a Terminal Bench task for this topic: "{topic}"

Study these reference examples carefully and match their format exactly:

{examples}

Now generate a complete, high-quality task for: "{topic}"

Remember:
- Include realistic source files with subtle, interacting bugs
- Tests must fail before solution and pass after
- Dockerfile should set up a proper environment
- solution.sh must deterministically fix everything
- Difficulty should challenge a very capable AI agent (Claude Opus level)
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


def generate_task(topic: str, output_dir: str | None = None, model: str | None = None) -> dict:
    """Generate a Terminal Bench task for the given topic.

    Args:
        topic: A short description of the task to generate.
        output_dir: Where to write the generated task files.
        model: Override the generator model.

    Returns:
        dict with task_dir, status, usage, and duration.
    """
    slug = re.sub(r"[^a-z0-9-]", "", topic.lower().replace(" ", "-"))[:60]

    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR, slug)

    os.makedirs(output_dir, exist_ok=True)

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

    gen_model = model or GENERATOR_MODEL
    user_prompt = _build_user_prompt(topic)

    print(f"Generating task for: {topic}")
    print(f"  Model: {gen_model}")
    print(f"  Output: {output_dir}")

    start = time.time()

    response = _api_call_with_retry(
        client,
        model=gen_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=32000,
    )

    duration = time.time() - start
    response_text = response.choices[0].message.content

    usage = {}
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

    try:
        files = _parse_response(response_text)
        _write_task_files(files, output_dir)
        status = "success"
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        status = f"parse_error: {e}"
        # Write raw response for debugging
        with open(os.path.join(output_dir, "_raw_response.txt"), "w") as f:
            f.write(response_text)

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
    if "tests failed" in feedback_lower and "with solution" in feedback_lower:
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
        infrastructure = {"task.yaml", "Dockerfile", "run-tests.sh", "solution.sh", "tests/test_outputs.py"}
        source_files = [f for f in previous_files if f not in infrastructure]
        repair_instruction = (
            "The tests pass without solution.sh being applied, meaning the source files don't "
            "have real bugs. Fix the SOURCE FILES to introduce real bugs that cause test failures. "
            "Do NOT change task.yaml, Dockerfile, run-tests.sh, solution.sh, or tests/. "
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

    feedback_prompt = f"""The task you generated for "{topic}" failed validation:

{feedback}

Here is the complete task:
```json
{previous_json}
```

{repair_instruction}

Return ONLY the JSON object."""

    print(f"  Repairing ({repair_target}) with feedback ({len(feedback)} chars)...")
    print(f"  Model: {gen_model}")

    start = time.time()

    response = _api_call_with_retry(
        client,
        model=gen_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": feedback_prompt},
        ],
        temperature=0.3,  # Lower temp for repairs — we want precision
        max_tokens=32000,
    )

    duration = time.time() - start
    response_text = response.choices[0].message.content

    usage = {}
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

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
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        status = f"parse_error: {e}"
        with open(os.path.join(task_dir, "_retry_raw_response.txt"), "w") as f:
            f.write(response_text)

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
            "Make the task EASIER by:\n"
            "- Remove 1-2 of the most subtle/complex bugs\n"
            "- Make remaining bugs more discoverable (clearer error messages, more obvious symptoms)\n"
            "- Reduce the number of interacting files if possible\n"
            "- Keep the core challenge intact — don't make it trivial\n"
            "- Update solution.sh to match the simplified bugs\n"
            "- Tests must still FAIL before solution and PASS after\n\n"
            "Return the complete adjusted task as a JSON object with ALL files."
        )
    else:  # too_easy
        adjustment_instruction = (
            f"This task is TOO EASY. An expert AI agent (Claude Opus) scored {pass_rate:.0%} "
            f"({int(pass_rate * 5)} out of 5 attempts passed). The target is 1-3 out of 5 passes (~20-60%).\n\n"
            "Make the task HARDER by:\n"
            "- Add 1-2 more subtle bugs that interact with existing ones\n"
            "- Make bug symptoms misleading (error in file A, root cause in file B)\n"
            "- Add edge cases that only fail with specific inputs\n"
            "- Require understanding of multiple files to fix\n"
            "- Update solution.sh to fix the new bugs too\n"
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

    response = _api_call_with_retry(
        client,
        model=gen_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        max_tokens=32000,
    )

    duration = time.time() - start
    response_text = response.choices[0].message.content

    usage = {}
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

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
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        status = f"parse_error: {e}"
        with open(os.path.join(task_dir, "_adjust_raw_response.txt"), "w") as f:
            f.write(response_text)

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
