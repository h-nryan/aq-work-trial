"""
End-to-end pipeline — generate → validate → evaluate a single task.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "validator"))
import shutil

from config import (
    EVAL_TRIALS,
    LEARNABLE_MAX,
    LEARNABLE_MIN,
    MAX_GENERATION_RETRIES,
    MAX_SOLUTION_FIRST_RETRIES,
    SONNET_EXAMPLES_DIR,
)
from docker_validate import docker_validate
from evaluate import evaluate_task
from generate import adjust_difficulty, generate_task, generate_task_solution_first, regenerate_task

# Max rounds of difficulty adjustment after evaluation
MAX_DIFFICULTY_ADJUSTMENTS = 2


def _write_status(task_dir: str, stage: str, detail: str = "", **extra) -> None:
    """Write a lightweight status file for UI polling.

    The dashboard reads _status.json to show real-time pipeline progress.
    """
    import json as _json
    from datetime import datetime
    status = {
        "stage": stage,
        "detail": detail,
        "updated_at": datetime.now().isoformat(),
        **extra,
    }
    try:
        os.makedirs(task_dir, exist_ok=True)
        with open(os.path.join(task_dir, "_status.json"), "w") as f:
            _json.dump(status, f)
    except Exception as e:
        print(f"  WARNING: Failed to write status to {task_dir}: {e}", file=__import__('sys').stderr)


def _save_validation_log(task_dir: str, attempt: int, func_result: dict) -> None:
    """Save functional validation result to a per-attempt log file.

    Creates validation_attempt_{N}.json in the task dir with the full
    validation result (issues, execution times, phase details) for debugging.
    """
    import json as _json

    log_path = os.path.join(task_dir, f"validation_attempt_{attempt}.json")
    try:
        # Extract the most useful debugging info
        log_data = {
            "attempt": attempt,
            "passed": func_result.get("passed", False),
            "issues": func_result.get("issues", []),
            "tests_fail_without_solution": func_result.get("tests_fail_without_solution"),
            "tests_pass_with_solution": func_result.get("tests_pass_with_solution"),
            "solution_idempotent": func_result.get("solution_idempotent"),
            "execution_times": func_result.get("execution_times", {}),
            "image_builds": func_result.get("image_builds"),
        }
        # Include phase details (stdout/stderr tails) if available
        details = func_result.get("details", {})
        if details:
            log_data["details"] = details
        with open(log_path, "w") as f:
            _json.dump(log_data, f, indent=2, default=str)
    except Exception:
        pass  # Non-critical


_INFRA_FILES = {"_meta.yaml", "Dockerfile", "docker-compose.yaml", "run-tests.sh",
                "solution.sh", "task.yaml"}

# Jaccard similarity above this threshold = too similar to promote/eval
SIMILARITY_THRESHOLD = 0.7


def _source_file_hash(task_dir: str) -> str:
    """Hash the source files of a task for exact-match dedup."""
    import hashlib
    h = hashlib.sha256()
    for root, _, files in os.walk(task_dir):
        for fname in sorted(files):
            if fname.startswith("_") or fname.startswith("validation_") or fname in _INFRA_FILES:
                continue
            fpath = os.path.join(root, fname)
            try:
                h.update(open(fpath, "rb").read())
            except OSError:
                pass
    return h.hexdigest()[:16]


def _source_file_words(task_dir: str) -> set[str]:
    """Get the set of words from source files for Jaccard similarity."""
    words: set[str] = set()
    for root, _, files in os.walk(task_dir):
        for fname in sorted(files):
            if fname.startswith("_") or fname.startswith("validation_") or fname in _INFRA_FILES:
                continue
            fpath = os.path.join(root, fname)
            try:
                words.update(open(fpath).read().split())
            except (OSError, UnicodeDecodeError):
                pass
    return words


def _jaccard_similarity(dir_a: str, dir_b: str) -> float:
    """Compute Jaccard similarity between source files of two tasks."""
    words_a = _source_file_words(dir_a)
    words_b = _source_file_words(dir_b)
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _find_similar_example(task_dir: str) -> tuple[str | None, float]:
    """Check if task is too similar to any existing example.

    Returns (matching_example_name, similarity) or (None, 0.0).
    Checks exact hash first (fast), then Jaccard similarity (slower).
    """
    new_hash = _source_file_hash(task_dir)

    if not os.path.isdir(SONNET_EXAMPLES_DIR):
        return None, 0.0

    for existing in os.listdir(SONNET_EXAMPLES_DIR):
        existing_path = os.path.join(SONNET_EXAMPLES_DIR, existing)
        if not os.path.isdir(existing_path):
            continue
        # Fast path: exact hash match
        if _source_file_hash(existing_path) == new_hash:
            return existing, 1.0
        # Slow path: Jaccard similarity
        sim = _jaccard_similarity(task_dir, existing_path)
        if sim >= SIMILARITY_THRESHOLD:
            return existing, sim

    return None, 0.0


def _auto_promote(task_dir: str, result: dict) -> None:
    """Auto-promote a learnable task to examples-sonnet/.

    Skips if too similar to an existing example (Jaccard >= 0.7 or exact match).
    """
    from pathlib import Path

    task_path = Path(task_dir).resolve()
    task_name = task_path.name
    dest = Path(SONNET_EXAMPLES_DIR) / task_name

    if dest.exists():
        print(f"  [Auto-promote] Already exists: {dest}")
        return

    match, sim = _find_similar_example(str(task_path))
    if match:
        print(f"  [Auto-promote] Too similar to existing example: {match} ({sim:.0%} similarity)")
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


def _write_adjustment_snapshot(
    snapshot_dir: str,
    adj_round: int,
    classification: str,
    pass_rate: float,
    eval_result: dict,
) -> None:
    """Write metadata into a pre-adjustment snapshot for later analysis.

    Captures what the task looked like before adjustment, why it was adjusted,
    and the eval results that triggered the adjustment.
    """
    meta = {
        "adjustment_round": adj_round,
        "pre_adjustment_classification": classification,
        "pre_adjustment_pass_rate": pass_rate,
        "pre_adjustment_passes": eval_result.get("passes", 0),
        "pre_adjustment_total": eval_result.get("total", 0),
        "trigger": f"{classification} — pass_rate={pass_rate:.0%}",
    }
    # Include per-trial results if available
    trials = eval_result.get("trials")
    if trials:
        meta["trial_results"] = trials

    meta_path = os.path.join(snapshot_dir, "_adj_snapshot.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)


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

    topic = result.get("topic", "")

    meta = {
        "approx_tokens": approx_tokens,
        "classification": classification,
        "opus_pass_rate": pass_rate,
        "opus_passes": passes,
        "opus_total": total,
        "source": "pipeline-generated",
        "topic": topic,
    }
    if category:
        meta["category"] = category

    meta_path = os.path.join(task_dir, "_meta.yaml")
    with open(meta_path, "w") as f:
        yaml.dump(meta, f, default_flow_style=False, sort_keys=True)


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
        build_timeout=60,
        test_timeout=120,
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

        # Include test output excerpts for debugging context.
        # Use generous limits so Sonnet can see exactly which tests failed and why.
        details = func_result.get("details", {})
        for phase in ("without_solution", "with_solution"):
            phase_detail = details.get(phase, {})
            stdout = phase_detail.get("stdout_tail", "")
            stderr = phase_detail.get("stderr_tail", "")
            if stdout or stderr:
                parts.append(
                    f"\n{phase.upper()} output:\n"
                    f"stdout (last 1500 chars): {stdout[-1500:]}\n"
                    f"stderr (last 500 chars): {stderr[-500:]}"
                )

    return "\n\n".join(parts) if parts else "Validation failed (no details available)."


def _try_adjustment(
    topic: str,
    task_dir: str,
    classification: str,
    pass_rate: float,
    eval_result: dict,
    adj_round: int,
    model: str | None,
    result: dict,
    adjustment_history: list[tuple[str, float]] | None = None,
) -> bool:
    """Attempt a difficulty adjustment. Returns True if adjustment succeeded.

    Handles: snapshot, adjust_difficulty call, functional re-validation,
    and restoring from snapshot on failure.
    """
    from evaluate import _write_eval_phase
    _write_eval_phase(task_dir, "adjusting")

    snapshot_dir = task_dir + f".pre_adj{adj_round + 1}"
    if os.path.exists(snapshot_dir):
        shutil.rmtree(snapshot_dir)
    shutil.copytree(task_dir, snapshot_dir)

    _write_adjustment_snapshot(
        snapshot_dir, adj_round + 1, classification, pass_rate, eval_result,
    )

    adj_result = adjust_difficulty(
        topic, task_dir, classification, pass_rate, model=model,
        adjustment_history=adjustment_history,
    )
    result["stages"][f"difficulty_adj_{adj_round + 1}"] = adj_result

    if adj_result["status"] != "success":
        print(f"  Difficulty adjustment failed: {adj_result['status']}")
        shutil.rmtree(task_dir)
        shutil.copytree(snapshot_dir, task_dir)
        print(f"  Restored pre-adjustment snapshot")
        return False

    # Re-validate before re-evaluating
    print(f"\n[Re-validation after adjustment]")
    func_result = validate_functional(task_dir)
    result["stages"]["functional"] = func_result
    if not func_result["passed"]:
        print(f"  Adjusted task failed functional validation — restoring snapshot")
        shutil.rmtree(task_dir)
        shutil.copytree(snapshot_dir, task_dir)
        return False

    return True


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

    if output_dir:
        _write_status(output_dir, "generating", "Phase 1 + Phase 2" if solution_first else "Single phase",
                      **({"category": target_category} if target_category else {}))

    try:
        if solution_first:
            gen_result = generate_task_solution_first(
                topic, output_dir=output_dir, model=model,
                hint_style=hint_style, target_category=target_category,
            )
        else:
            gen_result = generate_task(
                topic, output_dir=output_dir, model=model,
                hint_style=hint_style, target_category=target_category,
            )
    except Exception as e:
        task_dir = output_dir or ""
        if task_dir:
            _write_status(task_dir, "failed", f"generation exception: {e}")
        result["status"] = "generation_exception"
        result["failed_stage"] = "generation"
        result["stages"]["generate"] = {"status": "exception", "error": str(e)}
        result["duration_sec"] = round(time.time() - start, 2)
        return result

    result["stages"]["generate"] = gen_result
    result["task_dir"] = gen_result["task_dir"]

    task_dir = gen_result.get("task_dir") or output_dir or ""

    if gen_result["status"] != "success":
        result["status"] = "generation_failed"
        result["failed_stage"] = "generation"
        _write_status(task_dir, "failed", "generation failed")
        result["duration_sec"] = round(time.time() - start, 2)
        return result

    # Stages 2-3: Validate with retry loop
    for attempt in range(1 + effective_retries):
        is_retry = attempt > 0
        if is_retry:
            result["retries"] = attempt
            print(f"\n[Retry {attempt}/{effective_retries}]")

        # Stage 2: Structural validation
        print(f"\n[Structural Validation]")
        _write_status(task_dir, "structural", f"attempt {attempt + 1}")
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
                    _write_status(task_dir, "failed", "retry generation failed (structural)")
                    result["duration_sec"] = round(time.time() - start, 2)
                    return result
                continue  # re-validate
            result["status"] = "structural_validation_failed"
            result["failed_stage"] = "structural"
            _write_status(task_dir, "failed", "structural validation failed")
            result["duration_sec"] = round(time.time() - start, 2)
            return result

        # Stage 3: Functional validation
        if not skip_functional:
            print(f"\n[Functional Validation]")
            _write_status(task_dir, "functional", f"Docker build + test, attempt {attempt + 1}")
            func_result = validate_functional(task_dir)
            result["stages"]["functional"] = func_result

            # Save per-attempt validation log for debugging
            _save_validation_log(task_dir, attempt + 1, func_result)

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
                        _write_status(task_dir, "failed", "retry generation failed (functional)")
                        result["duration_sec"] = round(time.time() - start, 2)
                        return result
                    continue  # re-validate from structural
                if is_environment_error:
                    result["status"] = "infrastructure_error"
                    result["failed_stage"] = "functional"
                    _write_status(task_dir, "failed", f"infrastructure error: {issues[0][:50] if issues else '?'}")
                    print(f"  True infrastructure error — skipping retries")
                else:
                    result["status"] = "functional_validation_failed"
                    result["failed_stage"] = "functional"
                    _write_status(task_dir, "failed", "functional validation failed")
                result["duration_sec"] = round(time.time() - start, 2)
                return result
        else:
            print(f"\n[Functional Validation] Skipped")

        # Dedup check: if too similar to existing example, regenerate
        match, sim = _find_similar_example(task_dir)
        if match:
            print(f"\n[Dedup] Too similar to existing example: {match} ({sim:.0%})")
            if attempt < effective_retries:
                print(f"  Regenerating for diversity...")
                feedback = f"Your generated task is too similar to an existing example ({match}, {sim:.0%} similarity). Generate a COMPLETELY DIFFERENT implementation — different variable names, different code structure, different bugs."
                retry_result = regenerate_task(topic, task_dir, feedback, model=model)
                result["stages"][f"retry_{attempt + 1}"] = retry_result
                if retry_result["status"] != "success":
                    result["status"] = "retry_generation_failed"
                    result["failed_stage"] = "dedup"
                    _write_status(task_dir, "failed", "dedup retry failed")
                    result["duration_sec"] = round(time.time() - start, 2)
                    return result
                continue  # re-validate from structural
            # Out of retries — skip eval to save Opus budget
            print(f"  No retries left — skipping eval.")
            result["status"] = "duplicate"
            result["failed_stage"] = "dedup"
            _write_status(task_dir, "completed", f"duplicate ({sim:.0%} similar to {match})",
                          classification="duplicate")
            result["duration_sec"] = round(time.time() - start, 2)
            return result

        # Validation passed + unique content — break out of retry loop
        break

    # Stage 4+5+6: Tiered evaluation with difficulty adjustment loop
    #
    # Early adjustment: after the initial 3-parallel Opus batch, if 0/3 passes
    # AND average test pass rate < 30%, adjust before burning 2 more Opus runs.
    # This saves cost on clearly-too-hard tasks while preserving accuracy for
    # "close" tasks (high test pass rate but 0 full solves).
    if not skip_eval:
        _write_status(task_dir, "evaluating", "Opus trials running")

        # After too_hard adjustment, skip Sonnet filter on re-eval
        # After a too_hard adjustment, skip Sonnet filter on re-eval — if the
        # task was too hard for Opus, it won't be too easy for Sonnet. Running
        # 5 Sonnet trials would be pure waste.
        _skip_sonnet_after_too_hard = False
        _adjustment_history: list[tuple[str, float]] = []

        for adj_round in range(1 + MAX_DIFFICULTY_ADJUSTMENTS):
            eval_result = evaluate_task(
                task_dir=task_dir,
                n_trials=n_eval_trials,
                skip_filters=skip_filters,
                skip_haiku=not include_haiku,
                skip_sonnet=_skip_sonnet_after_too_hard,
            )
            _skip_sonnet_after_too_hard = False  # reset after use
            result["stages"]["evaluation"] = eval_result
            result["classification"] = eval_result["classification"]
            result["passes"] = eval_result["passes"]
            result["total"] = eval_result["total"]
            result["pass_rate"] = eval_result["pass_rate"]

            # If learnable, we're done
            if eval_result["classification"] == "learnable":
                break

            # Determine if adjustment is warranted
            classification = eval_result["classification"]
            pass_rate = eval_result.get("pass_rate") or 0.0

            should_adjust = (
                adj_round < MAX_DIFFICULTY_ADJUSTMENTS
                and classification in ("too_easy", "too_hard")
            )

            if should_adjust:
                print(f"\n[Difficulty Adjustment {adj_round + 1}/{MAX_DIFFICULTY_ADJUSTMENTS}] "
                      f"Task is {classification} (pass_rate={pass_rate:.0%})")

                adjusted = _try_adjustment(
                    topic, task_dir, classification, pass_rate,
                    eval_result, adj_round, model, result,
                    adjustment_history=_adjustment_history,
                )
                _adjustment_history.append((classification, pass_rate))
                if not adjusted:
                    _write_status(task_dir, "completed",
                                  f"{classification} (adjustment failed)",
                                  classification=classification, pass_rate=pass_rate)
                    break
                # After too_hard adjustment, skip Sonnet on re-eval — task
                # was too hard for Opus, it won't be too easy for Sonnet
                if classification == "too_hard":
                    _skip_sonnet_after_too_hard = True
            else:
                print(f"\n  Task remains {eval_result['classification']} after "
                      f"{MAX_DIFFICULTY_ADJUSTMENTS} adjustment(s)")
                cl_final = eval_result["classification"]
                pr_final = eval_result.get("pass_rate") or 0.0
                _write_status(task_dir, "completed",
                              f"{cl_final} (adjustments exhausted)",
                              classification=cl_final, pass_rate=pr_final)
    else:
        print(f"\n[Evaluation] Skipped")

    result["status"] = "completed"
    result["duration_sec"] = round(time.time() - start, 2)

    # Write final status
    cl = result.get("classification", "unknown")
    pr = result.get("pass_rate")
    pr_s = f"{pr:.0%}" if isinstance(pr, (int, float)) else ""
    _write_status(task_dir, "completed", f"{cl} {pr_s}".strip(),
                  classification=cl, pass_rate=pr)

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
