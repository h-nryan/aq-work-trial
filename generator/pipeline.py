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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "validator"))
from config import EVAL_TRIALS, MAX_GENERATION_RETRIES, OUTPUT_DIR
from docker_validate import docker_validate
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

    Delegates to validator/docker_validate.py which performs:
    1. Pre-Docker sanity checks (instruction length, file sizes)
    2. Docker image build + size check
    3. Tests FAIL without solution
    4. Tests PASS with solution
    Uses --skip-extended in the pipeline for speed (idempotency and
    determinism checks can be run separately via scripts/docker-validate.sh).
    """
    return docker_validate(
        task_dir=task_dir,
        build_timeout=300,
        test_timeout=180,
        cleanup=True,
        skip_extended=True,
    )


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
