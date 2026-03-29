"""
Task generator — generates a Terminal Bench task from a topic string using Sonnet via OpenRouter.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI

from config import (
    EXAMPLES_DIR,
    GENERATOR_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OUTPUT_DIR,
)


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


DIFFICULTY_GUIDANCE = {
    "easy": """\
EASY difficulty — the agent should solve this ~80-90% of the time:
- Include 1-2 clear bugs that are relatively independent
- Bugs should be findable by reading the error messages or obvious code inspection
- Single-file tasks are fine; keep the codebase small
- The task should take a skilled human 5-15 minutes
- Examples: missing import, wrong function name, off-by-one in a loop, bad config value""",

    "medium": """\
MEDIUM difficulty — the agent should solve this ~40-60% of the time:
- Include 3-5 distinct bugs or issues that interact with each other
- Use subtle bugs: off-by-one errors, type mismatches, missing edge cases, wrong variable references
- Require understanding of the FULL codebase to fix (not just one file)
- Include environment/dependency issues alongside code bugs
- Make some bugs only visible through specific test cases (edge cases)
- The task should take a skilled human 20-60 minutes""",

    "hard": """\
HARD difficulty — the agent should solve this ~10-30% of the time:
- Include 5-7 bugs that form a dependency chain (fixing bug A reveals bug B)
- Require deep understanding of the system: concurrency, protocol details, or algorithmic subtlety
- Include at least one bug that requires multi-step reasoning (not just pattern matching)
- Some bugs should have misleading symptoms (the error appears in module X but the root cause is in module Y)
- Use multiple interacting files with non-obvious data flow
- The task should take a skilled human 45-90 minutes
- Do NOT make it impossible — there must be a clear, deterministic solution""",
}

_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert at creating coding tasks for evaluating AI agents. You generate \
Terminal Bench tasks — self-contained coding challenges that run in Docker containers \
and are verified by pytest.

CRITICAL RULES:
1. Every task MUST have these files: task.yaml, Dockerfile, run-tests.sh, solution.sh, tests/test_outputs.py
2. Tasks must include "source files" — the buggy/incomplete code the agent needs to fix or build upon.
3. solution.sh must be a deterministic bash script that solves the task completely. It writes fixed files and runs any setup needed.
4. Tests MUST FAIL on the unsolved container (before solution.sh runs) and PASS after solution.sh runs.
5. The Dockerfile must install all dependencies needed for both the task and testing.
6. run-tests.sh installs uv + pytest and runs the tests. Follow the exact boilerplate pattern from examples.
7. task.yaml must have: instruction (detailed), difficulty, category, tags, parser_name: pytest, and timeout fields.

DIFFICULTY CALIBRATION (CRITICAL):
These tasks will be solved by a very capable AI agent (Claude Opus). Adjust the difficulty \
based on the DIFFICULTY LEVEL specified in the user prompt. If no level is specified, default to "medium".

{difficulty_guidance}

OUTPUT FORMAT:
Return your response as a JSON object with this structure:
{{
  "files": {{
    "task.yaml": "content...",
    "Dockerfile": "content...",
    "run-tests.sh": "content...",
    "solution.sh": "content...",
    "tests/test_outputs.py": "content...",
    "source_file.ext": "content...",
    ...additional source files...
  }}
}}

Return ONLY the JSON object. No markdown fences, no explanation, just the JSON."""


def _build_system_prompt(difficulty: str = "medium") -> str:
    """Build the system prompt with difficulty-specific calibration guidance."""
    guidance = DIFFICULTY_GUIDANCE.get(difficulty, DIFFICULTY_GUIDANCE["medium"])
    return _SYSTEM_PROMPT_TEMPLATE.format(difficulty_guidance=guidance)


def _build_user_prompt(topic: str, difficulty: str = "medium") -> str:
    """Build the user prompt with topic, difficulty, and examples."""
    examples = _load_examples()
    difficulty_line = f"\nDIFFICULTY LEVEL: {difficulty.upper()}\n"
    return f"""Generate a Terminal Bench task for this topic: "{topic}"
{difficulty_line}
Study these reference examples carefully and match their format exactly:

{examples}

Now generate a complete, high-quality task for: "{topic}"
Target difficulty: {difficulty.upper()}

Remember:
- Include realistic source files with bugs calibrated to {difficulty.upper()} difficulty
- Tests must fail before solution and pass after
- Dockerfile should set up a proper environment
- solution.sh must deterministically fix everything
- Set difficulty: "{difficulty}" in task.yaml
- Return ONLY the JSON object with all files"""


def _parse_response(response_text: str) -> dict:
    """Parse the LLM response to extract files dict."""
    text = response_text.strip()

    # Try to extract JSON from markdown code fences if present
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the JSON object in the text
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
    """Write parsed files to the task directory."""
    for filepath, content in files.items():
        full_path = os.path.join(output_dir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)

        # Make shell scripts executable
        if filepath.endswith(".sh"):
            os.chmod(full_path, 0o755)


def generate_task(
    topic: str,
    output_dir: str | None = None,
    model: str | None = None,
    difficulty: str = "medium",
) -> dict:
    """Generate a Terminal Bench task for the given topic.

    Args:
        topic: A short description of the task to generate.
        output_dir: Where to write the generated task files.
        model: Override the generator model.
        difficulty: Target difficulty level (easy, medium, hard).

    Returns:
        dict with task_dir, status, usage, and duration.
    """
    slug = topic.lower().replace(" ", "-").replace("/", "-")[:60]

    if output_dir is None:
        output_dir = os.path.join(OUTPUT_DIR, slug)

    os.makedirs(output_dir, exist_ok=True)

    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

    gen_model = model or GENERATOR_MODEL
    system_prompt = _build_system_prompt(difficulty)
    user_prompt = _build_user_prompt(topic, difficulty)

    print(f"Generating task for: {topic}")
    print(f"  Model: {gen_model}")
    print(f"  Output: {output_dir}")

    start = time.time()

    response = client.chat.completions.create(
        model=gen_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=16000,
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


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "fix a broken Python script"
    result = generate_task(topic)
    if result:
        print(f"\nGenerated task at: {result['task_dir']}")
        print(json.dumps(result, indent=2))
