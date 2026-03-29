"""
Tiered evaluation pipeline — progressively filters tasks through cheaper models
before expensive Opus evaluation.

Filter chain (each tier gates the next):
  Tier 1: Haiku × 5 runs   (~$0.05-0.25)  — catches trivially easy tasks
  Tier 2: Sonnet × 3 runs  (~$0.30-1.00)  — closer proxy for Opus capability
  Tier 3: Opus × 5 runs    (~$2-5.00)     — final calibration (the ground truth)

Design rationale: model capability is Haiku < Sonnet < Opus, so if a weaker model
finds a task easy, a stronger one definitely will. We filter from the "too easy"
side cheaply and only spend Opus budget on tasks with real uncertainty.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    EVAL_MODEL,
    EVAL_TRIALS,
    HAIKU_FILTER_RUNS,
    HAIKU_SKIP_THRESHOLD,
    LEARNABLE_MAX,
    LEARNABLE_MIN,
    PREFILTER_MODEL,
    SONNET_FILTER_MODEL,
    SONNET_FILTER_RUNS,
    SONNET_SKIP_THRESHOLD,
)


def _run_tb(
    task_dir: str,
    model: str,
    n_attempts: int = 1,
    run_id: str | None = None,
    output_path: str = "runs",
    timeout_sec: float = 900.0,
) -> dict:
    """Run the tb harness against a single task.

    Args:
        task_dir: Path to the task directory.
        model: Model name for the agent (OpenRouter format).
        n_attempts: Number of trial attempts.
        run_id: Unique run identifier.
        output_path: Where to store run results.
        timeout_sec: Max time per attempt.

    Returns:
        dict with passes, total, results_dir, and raw trial data.
    """
    dataset_path = str(Path(task_dir).resolve().parent)
    task_id = Path(task_dir).name

    # Ensure model uses openrouter/ prefix for litellm routing via OpenRouter
    tb_model = model if model.startswith("openrouter/") else f"openrouter/{model}"

    if run_id is None:
        run_id = f"eval-{task_id}-{model.split('/')[-1]}-{int(time.time())}"

    cmd = [
        "tb", "run",
        "--dataset-path", dataset_path,
        "--task-id", task_id,
        "--agent", "terminus-1",
        "--model", tb_model,
        "--n-attempts", str(n_attempts),
        "--output-path", output_path,
        "--run-id", run_id,
        "--n-concurrent", str(min(n_attempts, 4)),
    ]

    print(f"  Running: {' '.join(cmd)}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec * n_attempts,
            cwd=os.path.dirname(os.path.dirname(__file__)),
        )
        duration = time.time() - start

        if result.returncode != 0:
            print(f"  tb run failed (exit {result.returncode})")
            if result.stderr:
                print(f"  stderr: {result.stderr[:500]}")
            if result.stdout:
                print(f"  stdout: {result.stdout[:500]}")
    except subprocess.TimeoutExpired:
        duration = time.time() - start
        print(f"  tb run timed out after {duration:.0f}s")
        return {
            "passes": 0,
            "total": n_attempts,
            "duration_sec": round(duration, 2),
            "status": "timeout",
            "trials": [],
        }

    # Resolve results path relative to repo root (where tb run executes)
    repo_root = Path(os.path.dirname(os.path.dirname(__file__)))
    results_dir = repo_root / output_path / run_id
    return _parse_run_results(results_dir, task_id, n_attempts, duration)


def _parse_run_results(
    results_dir: Path, task_id: str, n_attempts: int, duration: float
) -> dict:
    """Parse trial results from the run output directory."""
    trials = []
    passes = 0

    task_results_dir = results_dir / task_id
    if not task_results_dir.exists():
        return {
            "passes": 0,
            "total": n_attempts,
            "duration_sec": round(duration, 2),
            "status": "no_results",
            "trials": [],
        }

    for trial_dir in sorted(task_results_dir.iterdir()):
        if not trial_dir.is_dir():
            continue

        results_file = trial_dir / "results.json"
        if not results_file.exists():
            trials.append({"trial": trial_dir.name, "resolved": False, "status": "no_results"})
            continue

        try:
            trial_data = json.loads(results_file.read_text())
            resolved = trial_data.get("is_resolved", False)
            if resolved:
                passes += 1
            trials.append({
                "trial": trial_dir.name,
                "resolved": resolved,
                "failure_mode": trial_data.get("failure_mode"),
                "input_tokens": trial_data.get("total_input_tokens"),
                "output_tokens": trial_data.get("total_output_tokens"),
            })
        except (json.JSONDecodeError, KeyError) as e:
            trials.append({"trial": trial_dir.name, "resolved": False, "status": f"parse_error: {e}"})

    return {
        "passes": passes,
        "total": len(trials) if trials else n_attempts,
        "duration_sec": round(duration, 2),
        "status": "completed",
        "trials": trials,
    }


def _run_filter_tier(
    task_dir: str,
    model: str,
    model_label: str,
    n_runs: int,
    skip_threshold: int,
    output_path: str = "runs",
) -> dict:
    """Run a single filter tier and return verdict.

    Args:
        task_dir: Path to the task directory.
        model: Model ID for OpenRouter.
        model_label: Human-readable model name for logging.
        n_runs: Number of runs for this tier.
        skip_threshold: Skip task if passes >= this threshold.
        output_path: Where to store run results.

    Returns:
        dict with passes, total, skip (bool), and raw result.
    """
    task_name = Path(task_dir).name
    print(f"\n  [Tier: {model_label} x{n_runs}] Running on {task_name}...")

    result = _run_tb(
        task_dir=task_dir,
        model=model,
        n_attempts=n_runs,
        output_path=output_path,
    )

    passes = result["passes"]
    total = result["total"]
    should_skip = passes >= skip_threshold

    verdict = "SKIP (too easy)" if should_skip else "PROCEED"
    print(f"  [Tier: {model_label}] {passes}/{total} passed → {verdict}")

    return {
        "model": model,
        "model_label": model_label,
        "passes": passes,
        "total": total,
        "skip_threshold": skip_threshold,
        "should_skip": should_skip,
        "result": result,
    }


def evaluate_task(
    task_dir: str,
    n_trials: int = EVAL_TRIALS,
    skip_filters: bool = False,
    skip_haiku: bool = False,
    skip_sonnet: bool = False,
    output_path: str = "runs",
) -> dict:
    """Full tiered evaluation pipeline for a single task.

    Tier 1: Haiku × 5 runs — skip if >= 4/5 pass (definitely too easy)
    Tier 2: Sonnet × 3 runs — skip if 3/3 pass (probably too easy for Opus)
    Tier 3: Opus × 5 runs — final calibration, classify as learnable/too_easy/too_hard

    Returns:
        dict with classification, pass_rate, passes, total, and tier details.
    """
    task_name = Path(task_dir).name
    print(f"\n{'='*60}")
    print(f"Evaluating: {task_name}")
    print(f"{'='*60}")

    tier_results = {}

    # ── Tier 1: Haiku × 5 ──
    if not skip_filters and not skip_haiku:
        haiku_tier = _run_filter_tier(
            task_dir=task_dir,
            model=PREFILTER_MODEL,
            model_label="Haiku",
            n_runs=HAIKU_FILTER_RUNS,
            skip_threshold=HAIKU_SKIP_THRESHOLD,
            output_path=output_path,
        )
        tier_results["haiku"] = haiku_tier

        if haiku_tier["should_skip"]:
            print(f"\n  FILTERED at Tier 1: Haiku passed {haiku_tier['passes']}/{haiku_tier['total']}")
            print(f"  Task is too easy for Opus — skipping Sonnet and Opus tiers.")
            return _build_result(
                task_dir=task_dir,
                classification="too_easy",
                filtered_at="haiku",
                tier_results=tier_results,
            )

    # ── Tier 2: Sonnet × 3 ──
    if not skip_filters and not skip_sonnet:
        sonnet_tier = _run_filter_tier(
            task_dir=task_dir,
            model=SONNET_FILTER_MODEL,
            model_label="Sonnet",
            n_runs=SONNET_FILTER_RUNS,
            skip_threshold=SONNET_SKIP_THRESHOLD,
            output_path=output_path,
        )
        tier_results["sonnet"] = sonnet_tier

        if sonnet_tier["should_skip"]:
            print(f"\n  FILTERED at Tier 2: Sonnet passed {sonnet_tier['passes']}/{sonnet_tier['total']}")
            print(f"  Task is too easy for Opus — skipping Opus tier.")
            return _build_result(
                task_dir=task_dir,
                classification="too_easy",
                filtered_at="sonnet",
                tier_results=tier_results,
            )

    # ── Tier 3: Opus × 5 (ground truth) ──
    print(f"\n  [Tier: Opus x{n_trials}] Running on {task_name}...")

    opus_result = _run_tb(
        task_dir=task_dir,
        model=EVAL_MODEL,
        n_attempts=n_trials,
        output_path=output_path,
    )
    tier_results["opus"] = {
        "model": EVAL_MODEL,
        "model_label": "Opus",
        "passes": opus_result["passes"],
        "total": opus_result["total"],
        "result": opus_result,
    }

    passes = opus_result["passes"]
    total = opus_result["total"]

    if LEARNABLE_MIN <= passes <= LEARNABLE_MAX:
        classification = "learnable"
    elif passes > LEARNABLE_MAX:
        classification = "too_easy"
    else:
        classification = "too_hard"

    print(f"\n  Opus result: {passes}/{total} → {classification}")

    return _build_result(
        task_dir=task_dir,
        classification=classification,
        filtered_at=None,
        tier_results=tier_results,
        opus_passes=passes,
        opus_total=total,
    )


def _build_result(
    task_dir: str,
    classification: str,
    filtered_at: str | None,
    tier_results: dict,
    opus_passes: int | None = None,
    opus_total: int | None = None,
) -> dict:
    """Build a standardized evaluation result dict."""
    task_name = Path(task_dir).name
    pass_rate = None
    if opus_passes is not None and opus_total:
        pass_rate = round(opus_passes / opus_total, 4)

    return {
        "task_dir": task_dir,
        "task_name": task_name,
        "classification": classification,
        "filtered_at": filtered_at,
        "passes": opus_passes,
        "total": opus_total,
        "pass_rate": pass_rate,
        "tier_results": {
            tier: {
                "model": v["model_label"],
                "passes": v["passes"],
                "total": v["total"],
                "should_skip": v.get("should_skip"),
            }
            for tier, v in tier_results.items()
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evaluate.py <task_dir> [--skip-filters] [--skip-haiku] [--skip-sonnet] [--trials N]")
        sys.exit(1)

    task_dir = sys.argv[1]
    skip_filters = "--skip-filters" in sys.argv
    skip_haiku = "--skip-haiku" in sys.argv
    skip_sonnet = "--skip-sonnet" in sys.argv
    n_trials = EVAL_TRIALS

    for i, arg in enumerate(sys.argv):
        if arg == "--trials" and i + 1 < len(sys.argv):
            n_trials = int(sys.argv[i + 1])

    result = evaluate_task(
        task_dir=task_dir,
        n_trials=n_trials,
        skip_filters=skip_filters,
        skip_haiku=skip_haiku,
        skip_sonnet=skip_sonnet,
    )

    print(f"\n{'='*60}")
    print(json.dumps(result, indent=2, default=str))
