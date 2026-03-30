"""
End-to-end pipeline — generate → validate → evaluate a single task.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "validator"))
import shutil

from config import EVAL_TRIALS, MAX_GENERATION_RETRIES, MAX_SOLUTION_FIRST_RETRIES, SONNET_EXAMPLES_DIR
from docker_validate import docker_validate
from evaluate import evaluate_task
from generate import adjust_difficulty, generate_task, generate_task_solution_first, regenerate_task

# Max rounds of difficulty adjustment after evaluation
MAX_DIFFICULTY_ADJUSTMENTS = 2


def _auto_promote(task_dir: str, result: dict) -> None:
    """Auto-promote a learnable task to examples-sonnet/."""
    from pathlib import Path

    task_path = Path(task_dir).resolve()
    task_name = task_path.name
    dest = Path(SONNET_EXAMPLES_DIR) / task_name

    if dest.exists():
        print(f"  [Auto-promote] Already exists: {dest}")
        return

    os.makedirs(SONNET_EXAMPLES_DIR, exist_ok=True)
    shutil.copytree(str(task_path), str(dest))

    # Clean up pipeline artifacts
    for pattern in ("_*.txt", "_*.json"):
        for f in dest.glob(pattern):
            if f.name != "_meta.yaml" and f.name != "_bugs.md":
                f.unlink()

    pass_rate = result.get("pass_rate", 0)
    passes = result.get("passes", "?")
    total = result.get("total", "?")
    print(f"  [Auto-promote] LEARNABLE task promoted to {dest}")
    print(f"  [Auto-promote] Opus {passes}/{total} ({pass_rate:.0%})")


def _write_task_meta(task_dir: str, result: dict, category: str | None = None) -> None:
    """Write _meta.yaml to a completed task directory.

    This metadata enables automated example selection — learnable tasks
    can be fed back into the prompt as few-shot examples.
    """
    classification = result.get("classification")
    if not classification:
        return

    passes = result.get("passes", 0)
    total = result.get("total", 0)
    pass_rate = result.get("pass_rate", 0.0)

    # Estimate token count from file sizes
    approx_tokens = 0
    for root, _, files in os.walk(task_dir):
        for fname in files:
            if not fname.startswith(".") and fname != "_meta.yaml":
                try:
                    approx_tokens += os.path.getsize(os.path.join(root, fname)) // 4
                except OSError:
                    pass

    meta_path = os.path.join(task_dir, "_meta.yaml")
    with open(meta_path, "w") as f:
        f.write(f"classification: {classification}\n")
        f.write(f"opus_pass_rate: {pass_rate}\n")
        f.write(f"opus_passes: {passes}\n")
        f.write(f"opus_total: {total}\n")
        if category:
            f.write(f"category: {category}\n")
        f.write(f"approx_tokens: {approx_tokens}\n")
        f.write(f"source: pipeline-generated\n")


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


def _build_feedback(struct_result: dict | None, func_result: dict | None) -> str:
    """Build a feedback string from validation results for the retry prompt."""
    parts = []

    if struct_result and not struct_result.get("passed"):
        output = struct_result.get("output", "")
        parts.append(f"STRUCTURAL VALIDATION FAILED:\n{output}")

    if func_result and not func_result.get("passed"):
        issues = func_result.get("issues", [])
        if issues:
            parts.append("FUNCTIONAL VALIDATION FAILED:\n" + "\n".join(f"- {i}" for i in issues))

        # Include test output excerpts for debugging context
        details = func_result.get("details", {})
        for phase in ("without_solution", "with_solution"):
            phase_detail = details.get(phase, {})
            stdout = phase_detail.get("stdout_tail", "")
            stderr = phase_detail.get("stderr_tail", "")
            if stdout or stderr:
                parts.append(f"\n{phase.upper()} output:\nstdout: {stdout[-500:]}\nstderr: {stderr[-500:]}")

    return "\n\n".join(parts) if parts else "Validation failed (no details available)."


def run_pipeline(
    topic: str,
    output_dir: str | None = None,
    n_eval_trials: int = EVAL_TRIALS,
    skip_filters: bool = False,
    skip_functional: bool = False,
    skip_eval: bool = False,
    max_retries: int | None = None,
    model: str | None = None,
    solution_first: bool = True,
    include_haiku: bool = False,
    prompt_variant: str = "A",
    hint_style: str = "none",
    target_category: str | None = None,
) -> dict:
    """Run the full pipeline for a single topic.

    Stages:
    1. Generate task (Sonnet/Opus) — optionally using solution-first strategy
    2. Structural validation
    3. Functional validation (Docker)
    4. If validation fails, retry with feedback (up to max_retries)
    5. Tiered evaluation: Haiku x5 → Sonnet x5 → Opus x5

    Args:
        solution_first: If True, use two-phase generation (write working
            code first, then introduce bugs). Higher functional validation
            pass rate but uses 2 API calls.
        hint_style: "none", "soft", or "full" — controls instruction hints.

    Returns:
        dict with all stage results and final classification.
    """
    # Solution-first gets more retries since each one gets closer to passing
    if max_retries is not None:
        effective_retries = max_retries
    elif solution_first:
        effective_retries = MAX_SOLUTION_FIRST_RETRIES
    else:
        effective_retries = MAX_GENERATION_RETRIES

    start = time.time()
    result = {
        "topic": topic,
        "stages": {},
        "retries": 0,
        "classification": None,
        "status": "incomplete",
        "failed_stage": None,  # set on failure: generation, structural, functional, evaluation
    }

    # Stage 1: Generate
    print(f"\n{'='*60}")
    print(f"Pipeline: {topic}")
    if solution_first:
        print(f"Strategy: solution-first (two-phase)")
    print(f"{'='*60}")

    if solution_first:
        gen_result = generate_task_solution_first(
            topic, output_dir=output_dir, model=model, prompt_variant=prompt_variant,
            hint_style=hint_style, target_category=target_category,
        )
    else:
        gen_result = generate_task(
            topic, output_dir=output_dir, model=model, prompt_variant=prompt_variant,
            hint_style=hint_style, target_category=target_category,
        )
    result["stages"]["generate"] = gen_result
    result["task_dir"] = gen_result["task_dir"]

    if gen_result["status"] != "success":
        result["status"] = "generation_failed"
        result["failed_stage"] = "generation"
        result["duration_sec"] = round(time.time() - start, 2)
        return result

    task_dir = gen_result["task_dir"]

    # Stages 2-3: Validate with retry loop
    for attempt in range(1 + effective_retries):
        is_retry = attempt > 0
        if is_retry:
            result["retries"] = attempt
            print(f"\n[Retry {attempt}/{effective_retries}]")

        # Stage 2: Structural validation
        print(f"\n[Structural Validation]")
        struct_result = validate_structural(task_dir)
        result["stages"]["structural"] = struct_result
        print(f"  {'PASSED' if struct_result['passed'] else 'FAILED'}")

        if not struct_result["passed"]:
            if attempt < effective_retries:
                feedback = _build_feedback(struct_result, None)
                retry_result = regenerate_task(topic, task_dir, feedback, model=model)
                result["stages"][f"retry_{attempt + 1}"] = retry_result
                if retry_result["status"] != "success":
                    result["status"] = "retry_generation_failed"
                    result["failed_stage"] = "structural"
                    result["duration_sec"] = round(time.time() - start, 2)
                    return result
                continue  # re-validate
            result["status"] = "structural_validation_failed"
            result["failed_stage"] = "structural"
            result["duration_sec"] = round(time.time() - start, 2)
            return result

        # Stage 3: Functional validation
        if not skip_functional:
            print(f"\n[Functional Validation]")
            func_result = validate_functional(task_dir)
            result["stages"]["functional"] = func_result

            if not func_result["passed"]:
                # Only skip retries for environment errors that regeneration
                # can't fix (Docker not available, image too large). Docker
                # build failures from bad Dockerfiles ARE fixable by
                # regeneration (e.g., conflicting packages).
                issues = func_result.get("issues", [])
                is_environment_error = any(
                    kw in issue.lower()
                    for issue in issues
                    for kw in ("docker is not available", "image size",
                               "no space left", "disk full", "permission denied")
                )

                if attempt < effective_retries and not is_environment_error:
                    feedback = _build_feedback(None, func_result)
                    retry_result = regenerate_task(topic, task_dir, feedback, model=model)
                    result["stages"][f"retry_{attempt + 1}"] = retry_result
                    if retry_result["status"] != "success":
                        result["status"] = "retry_generation_failed"
                        result["failed_stage"] = "functional"
                        result["duration_sec"] = round(time.time() - start, 2)
                        return result
                    continue  # re-validate from structural
                if is_environment_error:
                    result["status"] = "infrastructure_error"
                    result["failed_stage"] = "functional"
                    print(f"  True infrastructure error — skipping retries")
                else:
                    result["status"] = "functional_validation_failed"
                    result["failed_stage"] = "functional"
                result["duration_sec"] = round(time.time() - start, 2)
                return result
        else:
            print(f"\n[Functional Validation] Skipped")

        # Validation passed — break out of retry loop
        break

    # Stage 4+5+6: Tiered evaluation with difficulty adjustment loop
    if not skip_eval:
        for adj_round in range(1 + MAX_DIFFICULTY_ADJUSTMENTS):
            eval_result = evaluate_task(
                task_dir=task_dir,
                n_trials=n_eval_trials,
                skip_filters=skip_filters,
                skip_haiku=not include_haiku,
            )
            result["stages"]["evaluation"] = eval_result
            result["classification"] = eval_result["classification"]
            result["passes"] = eval_result["passes"]
            result["total"] = eval_result["total"]
            result["pass_rate"] = eval_result["pass_rate"]

            # If learnable, we're done
            if eval_result["classification"] == "learnable":
                break

            # If not learnable and we have adjustment budget, adjust difficulty
            if adj_round < MAX_DIFFICULTY_ADJUSTMENTS:
                classification = eval_result["classification"]
                pass_rate = eval_result.get("pass_rate") or 0.0
                print(f"\n[Difficulty Adjustment {adj_round + 1}/{MAX_DIFFICULTY_ADJUSTMENTS}] "
                      f"Task is {classification} (pass_rate={pass_rate:.0%})")

                # Backup task files before adjustment — restore if it breaks things
                import shutil
                backup_dir = task_dir + f"._backup_adj{adj_round + 1}"
                if os.path.exists(backup_dir):
                    shutil.rmtree(backup_dir)
                shutil.copytree(task_dir, backup_dir)

                adj_result = adjust_difficulty(
                    topic, task_dir, classification, pass_rate, model=model,
                )
                result["stages"][f"difficulty_adj_{adj_round + 1}"] = adj_result

                if adj_result["status"] != "success":
                    print(f"  Difficulty adjustment failed: {adj_result['status']}")
                    # Restore backup
                    shutil.rmtree(task_dir)
                    shutil.move(backup_dir, task_dir)
                    print(f"  Restored pre-adjustment backup")
                    break

                # Re-validate before re-evaluating
                print(f"\n[Re-validation after adjustment]")
                func_result = validate_functional(task_dir)
                result["stages"]["functional"] = func_result
                if not func_result["passed"]:
                    print(f"  Adjusted task failed functional validation — restoring backup")
                    shutil.rmtree(task_dir)
                    shutil.move(backup_dir, task_dir)
                    break  # Keep the original classification, don't return failure
                else:
                    # Adjustment worked, clean up backup
                    shutil.rmtree(backup_dir, ignore_errors=True)
            else:
                print(f"\n  Task remains {eval_result['classification']} after "
                      f"{MAX_DIFFICULTY_ADJUSTMENTS} adjustment(s)")
    else:
        print(f"\n[Evaluation] Skipped")

    result["status"] = "completed"
    result["duration_sec"] = round(time.time() - start, 2)

    # Auto-write _meta.yaml for learnable tasks (feeds back into example selection)
    if result.get("classification") and task_dir:
        _write_task_meta(task_dir, result, target_category)

    # Auto-promote learnable tasks to examples-sonnet/
    if result.get("classification") == "learnable" and task_dir:
        _auto_promote(task_dir, result)

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
    solution_first = "--no-solution-first" not in sys.argv
    include_haiku = "--include-haiku" in sys.argv

    gen_model = None
    for i, arg in enumerate(sys.argv):
        if arg == "--model" and i + 1 < len(sys.argv):
            gen_model = sys.argv[i + 1]

    result = run_pipeline(
        topic=topic,
        skip_eval=skip_eval,
        skip_functional=skip_functional,
        skip_filters=skip_filters,
        model=gen_model,
        solution_first=solution_first,
        include_haiku=include_haiku,
    )

    print(json.dumps(result, indent=2, default=str))
