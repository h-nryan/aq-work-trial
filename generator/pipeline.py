"""
End-to-end pipeline — generate → validate → evaluate a single task.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from config import EVAL_TRIALS, MAX_GENERATION_RETRIES, OUTPUT_DIR
from evaluate import evaluate_task
from generate import generate_task


def validate_structural(task_dir: str) -> dict:
    """Run the structural validator on a task directory."""
    validator_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "validator", "validate.py"
    )
    result = subprocess.run(
        [sys.executable, validator_path, task_dir],
        capture_output=True,
        text=True,
    )
    passed = result.returncode == 0
    return {"passed": passed, "output": result.stdout + result.stderr}


def validate_functional(task_dir: str) -> dict:
    """Build Docker image and verify solution.sh passes tests.

    Steps:
    1. Build Docker image from the task's Dockerfile
    2. Run solution.sh inside the container
    3. Run run-tests.sh and verify all tests pass
    4. (Optional) Verify tests fail WITHOUT solution.sh
    """
    task_path = Path(task_dir)
    task_name = task_path.name
    image_name = f"tbench-gen-{task_name}".lower()

    print(f"  [Functional] Building Docker image: {image_name}")

    # Step 1: Build
    build_result = subprocess.run(
        ["docker", "build", "-t", image_name, "."],
        capture_output=True,
        text=True,
        cwd=task_dir,
        timeout=300,
    )
    if build_result.returncode != 0:
        return {
            "passed": False,
            "stage": "build",
            "error": build_result.stderr[:1000],
        }

    # Step 2: Verify tests FAIL on unsolved container
    print(f"  [Functional] Checking tests fail without solution...")
    unsolved_result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-e", f"TEST_DIR=/app/tests",
            image_name,
            "bash", "-c", "cd /app && bash run-tests.sh",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    tests_fail_unsolved = unsolved_result.returncode != 0

    if not tests_fail_unsolved:
        print(f"  [Functional] WARNING: Tests pass without solution (task is trivially solved)")
        # This is a soft warning — task might still be useful if the instruction
        # requires something beyond what the tests check

    # Step 3: Run solution.sh + tests
    print(f"  [Functional] Running solution.sh + tests...")
    solved_result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-e", f"TEST_DIR=/app/tests",
            image_name,
            "bash", "-c", "cd /app && bash solution.sh && bash run-tests.sh",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    tests_pass_solved = solved_result.returncode == 0

    # Cleanup
    subprocess.run(
        ["docker", "rmi", "-f", image_name],
        capture_output=True,
        timeout=30,
    )

    passed = tests_pass_solved and tests_fail_unsolved

    if not tests_pass_solved:
        print(f"  [Functional] FAIL: Tests don't pass after solution.sh")
        print(f"    stdout: {solved_result.stdout[-500:]}")
        print(f"    stderr: {solved_result.stderr[-500:]}")
    elif not tests_fail_unsolved:
        print(f"  [Functional] WARN: Tests don't fail without solution")
    else:
        print(f"  [Functional] PASS: Tests fail unsolved, pass after solution")

    return {
        "passed": passed,
        "tests_pass_solved": tests_pass_solved,
        "tests_fail_unsolved": tests_fail_unsolved,
        "stage": "complete",
        "solved_output": solved_result.stdout[-500:] if not tests_pass_solved else "",
    }


def run_pipeline(
    topic: str,
    output_dir: Optional[str] = None,
    n_eval_trials: int = EVAL_TRIALS,
    skip_filters: bool = False,
    skip_functional: bool = False,
    skip_eval: bool = False,
    max_retries: int = MAX_GENERATION_RETRIES,
) -> dict:
    """Run the full pipeline for a single topic.

    Stages:
    1. Generate task (Sonnet)
    2. Structural validation
    3. Functional validation (Docker)
    4. Tiered evaluation: Haiku x5 → Sonnet x3 → Opus x5

    Returns:
        dict with all stage results and final classification.
    """
    start = time.time()
    result = {
        "topic": topic,
        "stages": {},
        "classification": None,
        "status": "incomplete",
    }

    # Stage 1: Generate
    print(f"\n{'='*60}")
    print(f"Pipeline: {topic}")
    print(f"{'='*60}")

    gen_result = generate_task(topic, output_dir=output_dir)
    result["stages"]["generate"] = gen_result
    result["task_dir"] = gen_result["task_dir"]

    if gen_result["status"] != "success":
        result["status"] = "generation_failed"
        result["duration_sec"] = round(time.time() - start, 2)
        return result

    task_dir = gen_result["task_dir"]

    # Stage 2: Structural validation
    print(f"\n[Structural Validation]")
    struct_result = validate_structural(task_dir)
    result["stages"]["structural"] = struct_result
    print(f"  {'PASSED' if struct_result['passed'] else 'FAILED'}")

    if not struct_result["passed"]:
        result["status"] = "structural_validation_failed"
        result["duration_sec"] = round(time.time() - start, 2)
        return result

    # Stage 3: Functional validation
    if not skip_functional:
        print(f"\n[Functional Validation]")
        func_result = validate_functional(task_dir)
        result["stages"]["functional"] = func_result

        if not func_result["passed"]:
            result["status"] = "functional_validation_failed"
            result["duration_sec"] = round(time.time() - start, 2)
            return result
    else:
        print(f"\n[Functional Validation] Skipped")

    # Stage 4+5+6: Tiered evaluation (Haiku x5 → Sonnet x3 → Opus x5)
    if not skip_eval:
        eval_result = evaluate_task(
            task_dir=task_dir,
            n_trials=n_eval_trials,
            skip_filters=skip_filters,
        )
        result["stages"]["evaluation"] = eval_result
        result["classification"] = eval_result["classification"]
        result["passes"] = eval_result["passes"]
        result["total"] = eval_result["total"]
        result["pass_rate"] = eval_result["pass_rate"]
    else:
        print(f"\n[Evaluation] Skipped")

    result["status"] = "completed"
    result["duration_sec"] = round(time.time() - start, 2)

    print(f"\n{'='*60}")
    print(f"Pipeline complete: {topic}")
    print(f"  Status: {result['status']}")
    if result.get("classification"):
        print(f"  Classification: {result['classification']}")
        print(f"  Pass rate: {result.get('pass_rate', 'N/A')}")
    print(f"  Duration: {result['duration_sec']}s")
    print(f"{'='*60}")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <topic> [--skip-eval] [--skip-functional] [--skip-filters]")
        sys.exit(1)

    topic = sys.argv[1]
    skip_eval = "--skip-eval" in sys.argv
    skip_functional = "--skip-functional" in sys.argv
    skip_filters = "--skip-filters" in sys.argv

    result = run_pipeline(
        topic=topic,
        skip_eval=skip_eval,
        skip_functional=skip_functional,
        skip_filters=skip_filters,
    )

    print(json.dumps(result, indent=2, default=str))
