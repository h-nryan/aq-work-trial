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
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Max age (seconds) before a Docker container is considered stale and killed.
# tb's max_agent_timeout_sec defaults to 360s (6 min). With --n-concurrent 4,
# each trial gets its own container running in parallel, so max wall time is
# ~6-7 min per batch. 20 min threshold gives ample margin.
STALE_CONTAINER_AGE_SEC = 1200

# Number of times _run_tb retries on transient infrastructure failures
# (e.g. Docker daemon restart, temporary connection refused).
_MAX_TB_RETRIES = 1

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


def _cleanup_stale_containers(max_age_sec: int = STALE_CONTAINER_AGE_SEC) -> int:
    """Kill Docker containers that have been running longer than max_age_sec.

    Returns the number of containers killed.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}} {{.CreatedAt}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0

    killed = 0
    now = time.time()
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        container_id = parts[0]
        # CreatedAt format: "2026-03-29 17:36:08 -0700 PDT"
        try:
            created_str = f"{parts[1]} {parts[2]}"
            # Parse without timezone — use local time approximation
            created = time.mktime(time.strptime(created_str, "%Y-%m-%d %H:%M:%S"))
            age = now - created
            if age > max_age_sec:
                subprocess.run(
                    ["docker", "kill", container_id],
                    capture_output=True, timeout=10,
                )
                killed += 1
        except (ValueError, subprocess.TimeoutExpired):
            continue

    if killed:
        print(f"  Cleaned up {killed} stale container(s) (>{max_age_sec}s old)")
    return killed


def _prune_exited_containers() -> int:
    """Remove all stopped (exited) Docker containers.

    tb leaves behind exited containers after each eval run. Without pruning,
    these accumulate (100+ per batch) and clutter Docker Desktop.
    Returns the number of containers removed.
    """
    try:
        result = subprocess.run(
            ["docker", "container", "prune", "-f"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0

    # Parse output like "Deleted Containers:\n<id>\n<id>\n\nTotal reclaimed space: 1.2GB"
    deleted = [
        line for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("Deleted") and not line.startswith("Total")
    ]
    if deleted:
        print(f"  Pruned {len(deleted)} exited container(s)")
    return len(deleted)


def _cleanup_stale_tb_processes(max_age_sec: int = STALE_CONTAINER_AGE_SEC) -> int:
    """Kill stale `tb run` processes and their orphaned parent evaluators.

    tb run processes that outlive their containers become zombies waiting
    on subprocess.run() that will never return. This also catches parent
    Python processes that spawned evaluate_task() calls and are stuck
    waiting on a dead tb run child.

    Returns the number of processes killed.
    """
    import signal

    try:
        # Find all tb run processes with their PIDs and start times
        result = subprocess.run(
            ["ps", "-eo", "pid,etimes,args"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0

    killed = 0
    my_pid = os.getpid()

    for line in result.stdout.strip().splitlines()[1:]:  # skip header
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            elapsed_sec = int(parts[1])
            cmd = parts[2]
        except (ValueError, IndexError):
            continue

        # Don't kill ourselves or our parent
        if pid == my_pid or pid == os.getppid():
            continue

        if elapsed_sec <= max_age_sec:
            continue

        # Kill stale tb run processes
        is_stale_tb = "tb run" in cmd and "eval-" in cmd
        # Kill stale evaluate_task parent processes (the python -c wrappers)
        is_stale_eval_parent = "from evaluate import" in cmd

        if is_stale_tb or is_stale_eval_parent:
            try:
                os.kill(pid, signal.SIGTERM)
                killed += 1
            except ProcessLookupError:
                pass

    if killed:
        print(f"  Cleaned up {killed} stale process(es) (>{max_age_sec}s old)")
    return killed


def _cleanup_stale_networks() -> int:
    """Remove orphaned Docker networks created by parallel task runs.

    docker-compose creates a network per task. If the container is killed
    without docker-compose down, the network leaks. Eventually Docker's
    address pool is exhausted and new runs fail.

    Returns the number of networks removed.
    """
    try:
        result = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.ID}} {{.Name}}",
             "--filter", "type=custom"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0

    removed = 0
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        net_id, name = parts
        # Skip well-known networks
        if name in ("bridge", "host", "none"):
            continue
        try:
            # docker network rm only succeeds if no containers are connected
            rm_result = subprocess.run(
                ["docker", "network", "rm", net_id],
                capture_output=True, text=True, timeout=10,
            )
            if rm_result.returncode == 0:
                removed += 1
        except subprocess.TimeoutExpired:
            continue

    if removed:
        print(f"  Cleaned up {removed} orphaned Docker network(s)")
    return removed


def cleanup_stale_resources(max_age_sec: int = STALE_CONTAINER_AGE_SEC) -> int:
    """Kill stale Docker containers, orphaned processes, and leaked networks.

    Call this before starting new eval runs to prevent resource accumulation.
    Returns total number of resources cleaned up.
    """
    containers = _cleanup_stale_containers(max_age_sec)
    exited = _prune_exited_containers()
    processes = _cleanup_stale_tb_processes(max_age_sec)
    networks = _cleanup_stale_networks()
    return containers + exited + processes + networks


def _kill_containers_for_task(task_id: str) -> int:
    """Kill all running Docker containers whose name contains the given task_id.

    Used for targeted cleanup after a timeout — rather than waiting for the
    age-based stale cleanup, immediately kill containers we know are orphaned.

    Returns the number of containers killed.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}} {{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0

    killed = 0
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        container_id, name = parts
        if task_id in name:
            try:
                subprocess.run(
                    ["docker", "kill", container_id],
                    capture_output=True, timeout=10,
                )
                killed += 1
            except subprocess.TimeoutExpired:
                continue

    if killed:
        print(f"  Killed {killed} orphaned container(s) for {task_id}")
    return killed


def _run_tb(
    task_dir: str,
    model: str,
    n_attempts: int = 1,
    run_id: str | None = None,
    output_path: str = "runs",
    timeout_sec: float = 900.0,
    cleanup: bool = True,
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
    # Kill any hung containers/processes before starting new trials
    cleanup_stale_resources()

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

    # Timeout budget: runs execute with --n-concurrent min(n,4), so wall time
    # is ceil(n / concurrent) waves × timeout_sec, not n × timeout_sec.
    # Example: n_attempts=5, concurrent=4 → 2 waves → 2 × 900s = 1800s,
    # not 5 × 900s = 4500s. Overly large timeouts mask hung runs.
    _n_concurrent = min(n_attempts, 4)
    _n_waves = math.ceil(n_attempts / _n_concurrent)
    _total_timeout = timeout_sec * _n_waves

    start = time.time()
    for tb_attempt in range(1 + _MAX_TB_RETRIES):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_total_timeout,
                cwd=os.path.dirname(os.path.dirname(__file__)),
            )
            duration = time.time() - start

            if result.returncode != 0:
                print(f"  tb run failed (exit {result.returncode})")
                if result.stderr:
                    print(f"  stderr: {result.stderr[:500]}")
                if result.stdout:
                    print(f"  stdout: {result.stdout[:500]}")
                # Retry on transient infrastructure errors
                stderr_lower = (result.stderr or "").lower()
                transient = any(s in stderr_lower for s in [
                    "connection refused", "daemon is not running",
                    "no space left", "resource temporarily unavailable",
                ])
                if transient and tb_attempt < _MAX_TB_RETRIES:
                    print(f"  Transient error — retrying tb run ({tb_attempt + 1}/{_MAX_TB_RETRIES})")
                    _kill_containers_for_task(task_id)
                    time.sleep(5)
                    start = time.time()  # reset for fresh timing
                    continue
            break  # success or non-transient failure
        except subprocess.TimeoutExpired:
            duration = time.time() - start
            print(f"  tb run timed out after {duration:.0f}s — killing orphaned containers")
            _kill_containers_for_task(task_id)
            if tb_attempt < _MAX_TB_RETRIES:
                print(f"  Retrying tb run after timeout ({tb_attempt + 1}/{_MAX_TB_RETRIES})")
                time.sleep(5)
                start = time.time()
                continue
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
    parsed = _parse_run_results(results_dir, task_id, n_attempts, duration)

    # Clean up run artifacts — all data is captured in the return dict
    if cleanup and results_dir.exists():
        shutil.rmtree(results_dir, ignore_errors=True)

    return parsed


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
            # Count test results
            parser_results = trial_data.get("parser_results") or {}
            tests_passed = sum(1 for v in parser_results.values() if v == "passed")
            tests_total = len(parser_results)

            trials.append({
                "trial": trial_dir.name,
                "resolved": resolved,
                "failure_mode": trial_data.get("failure_mode"),
                "input_tokens": trial_data.get("total_input_tokens"),
                "output_tokens": trial_data.get("total_output_tokens"),
                "agent_started_at": trial_data.get("agent_started_at"),
                "agent_ended_at": trial_data.get("agent_ended_at"),
                "tests_passed": tests_passed,
                "tests_total": tests_total,
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
    """Run a single filter tier with early stopping.

    Hybrid strategy: first 3 runs in parallel, then sequential with
    early-stop checks. Stops as soon as the skip/proceed decision is certain.

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

    PARALLEL_BATCH = min(3, n_runs)
    passes = 0
    total = 0
    all_results = []

    # Phase A: parallel batch
    batch_result = _run_tb(
        task_dir=task_dir,
        model=model,
        n_attempts=PARALLEL_BATCH,
        output_path=output_path,
    )
    passes = batch_result["passes"]
    total = batch_result["total"] or PARALLEL_BATCH
    all_results.append(batch_result)
    remaining = n_runs - total

    # Check if decision is already certain
    def _decided(p: int, rem: int) -> bool | None:
        """Returns True (skip/too_easy), False (proceed), or None (undecided)."""
        if p >= skip_threshold:
            return True  # already too easy
        if p + rem < skip_threshold:
            return False  # can't reach threshold
        return None

    decision = _decided(passes, remaining)
    if decision is not None:
        saved = remaining
        if saved > 0:
            print(f"    Batch 1-{total}: {passes}/{total} → early stop (saved {saved} runs)")
    else:
        # Phase B: sequential with early-stop
        for _ in range(remaining):
            single = _run_tb(
                task_dir=task_dir,
                model=model,
                n_attempts=1,
                output_path=output_path,
            )
            total += 1
            if single["passes"] > 0:
                passes += 1
            all_results.append(single)

            decision = _decided(passes, n_runs - total)
            if decision is not None:
                saved = n_runs - total
                if saved > 0:
                    print(f"    Run {total}/{n_runs}: {passes} passes → early stop (saved {saved} runs)")
                break

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
        "early_stopped": total < n_runs,
        "results": all_results,
    }


def _can_stop(passes: int, remaining: int) -> str | None:
    """Check if we can classify early based on passes and remaining runs."""
    if passes >= LEARNABLE_MIN and passes + remaining <= LEARNABLE_MAX:
        return "learnable"
    if passes > LEARNABLE_MAX:
        return "too_easy"
    if passes + remaining < LEARNABLE_MIN:
        return "too_hard"
    return None


def _extract_test_stats(trials: list[dict]) -> dict:
    """Extract per-test pass rates from trial data.

    Returns dict with avg_test_pass_rate (0.0-1.0) and per-trial counts.
    """
    test_counts = []
    for batch in trials:
        for trial in batch.get("trials", []):
            tp = trial.get("tests_passed", 0)
            tt = trial.get("tests_total", 0)
            if tt > 0:
                test_counts.append({"passed": tp, "total": tt, "rate": tp / tt})
    if not test_counts:
        return {"avg_test_pass_rate": 0.0, "trials": test_counts}
    avg = sum(t["rate"] for t in test_counts) / len(test_counts)
    return {"avg_test_pass_rate": avg, "trials": test_counts}


def run_opus_eval(
    task_dir: str,
    n_trials: int = EVAL_TRIALS,
    output_path: str = "runs",
    prior_passes: int = 0,
    prior_total: int = 0,
    prior_trials: list | None = None,
) -> dict:
    """Run Opus evaluation with early stopping.

    Supports resuming from prior results (e.g., after early adjustment).
    First batch runs in parallel, then sequential with early-stop checks.

    Returns dict with passes, total, trials, classification, and test_stats.
    """
    opus_passes = prior_passes
    opus_total = prior_total
    opus_trials = list(prior_trials or [])
    remaining = n_trials - opus_total

    if remaining <= 0:
        # Already have enough data
        if LEARNABLE_MIN <= opus_passes <= LEARNABLE_MAX:
            classification = "learnable"
        elif opus_passes > LEARNABLE_MAX:
            classification = "too_easy"
        else:
            classification = "too_hard"
        return {
            "passes": opus_passes,
            "total": opus_total,
            "trials": opus_trials,
            "classification": classification,
            "test_stats": _extract_test_stats(opus_trials),
        }

    # If no prior results, run first batch in parallel
    if opus_total == 0:
        parallel_batch = min(3, remaining)
        batch_result = _run_tb(
            task_dir=task_dir,
            model=EVAL_MODEL,
            n_attempts=parallel_batch,
            output_path=output_path,
        )
        opus_passes = batch_result["passes"]
        opus_total = batch_result["total"] or parallel_batch
        opus_trials.append(batch_result)
        remaining = n_trials - opus_total

        print(f"    Batch 1-{parallel_batch}: {opus_passes}/{opus_total} passes")

        early_class = _can_stop(opus_passes, remaining)
        if early_class:
            print(f"    → {early_class} (early stop after {opus_total} runs, saved {remaining})")
            test_stats = _extract_test_stats(opus_trials)

            # Signal early adjustment opportunity: 0 passes + low test pass rate
            recommend_early_adj = (
                opus_passes == 0
                and remaining > 0
                and test_stats["avg_test_pass_rate"] < 0.3
            )

            return {
                "passes": opus_passes,
                "total": opus_total,
                "trials": opus_trials,
                "classification": early_class,
                "test_stats": test_stats,
                "recommend_early_adjust": recommend_early_adj,
                "remaining_runs": remaining,
            }

        # Check if early adjustment is recommended (0/3 + low test rate)
        test_stats = _extract_test_stats(opus_trials)
        if opus_passes == 0 and test_stats["avg_test_pass_rate"] < 0.3:
            print(f"    0/{opus_total} passes, avg test rate {test_stats['avg_test_pass_rate']:.0%}"
                  f" — recommending early adjustment")
            return {
                "passes": opus_passes,
                "total": opus_total,
                "trials": opus_trials,
                "classification": "too_hard",
                "test_stats": test_stats,
                "recommend_early_adjust": True,
                "remaining_runs": remaining,
            }

    # Sequential runs with early-stop checks
    for run_idx in range(remaining):
        single_result = _run_tb(
            task_dir=task_dir,
            model=EVAL_MODEL,
            n_attempts=1,
            output_path=output_path,
        )
        opus_total += 1
        if single_result["passes"] > 0:
            opus_passes += 1
        opus_trials.append(single_result)

        runs_left = n_trials - opus_total
        early_class = _can_stop(opus_passes, runs_left)
        if early_class:
            print(f"    Run {opus_total}/{n_trials}: {opus_passes} passes — "
                  f"{early_class} (early stop, saved {runs_left} runs)")
            break
        else:
            print(f"    Run {opus_total}/{n_trials}: {opus_passes}/{opus_total} passes")

    if LEARNABLE_MIN <= opus_passes <= LEARNABLE_MAX:
        classification = "learnable"
    elif opus_passes > LEARNABLE_MAX:
        classification = "too_easy"
    else:
        classification = "too_hard"

    return {
        "passes": opus_passes,
        "total": opus_total,
        "trials": opus_trials,
        "classification": classification,
        "test_stats": _extract_test_stats(opus_trials),
        "recommend_early_adjust": False,
        "remaining_runs": 0,
    }


def evaluate_task(
    task_dir: str,
    n_trials: int = EVAL_TRIALS,
    skip_filters: bool = False,
    skip_haiku: bool = True,
    skip_sonnet: bool = False,
    output_path: str = "runs",
) -> dict:
    """Full tiered evaluation pipeline for a single task.

    Tier 1: Haiku × 5 runs — DISABLED by default (Haiku scores 0/5 on every
        task tested, including trivially easy ones; pure overhead). Enable
        with skip_haiku=False or --include-haiku CLI flag.
    Tier 2: Sonnet × 5 runs — skip if >= 4/5 pass (very likely too easy for Opus)
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

    # ── Tier 3: Opus × 5 (ground truth) with early stopping ──
    # Hybrid strategy: first 3 runs in parallel for speed, then sequential
    # with early-stop checks for cost efficiency.
    print(f"\n  [Tier: Opus x{n_trials}] Running on {task_name}...")

    opus_result = run_opus_eval(
        task_dir=task_dir,
        n_trials=n_trials,
        output_path=output_path,
    )
    opus_passes = opus_result["passes"]
    opus_total = opus_result["total"]
    opus_trials = opus_result["trials"]
    early_class = opus_result.get("classification")

    tier_results["opus"] = {
        "model": EVAL_MODEL,
        "model_label": "Opus",
        "passes": opus_passes,
        "total": opus_total,
        "early_stopped": opus_total < n_trials,
        "trials": opus_trials,
        "test_stats": opus_result.get("test_stats"),
    }

    classification = opus_result["classification"]

    print(f"\n  Opus result: {opus_passes}/{opus_total} → {classification}")

    result = _build_result(
        task_dir=task_dir,
        classification=classification,
        filtered_at=None,
        tier_results=tier_results,
        opus_passes=opus_passes,
        opus_total=opus_total,
    )
    # Pass through early adjustment signal from run_opus_eval
    result["recommend_early_adjust"] = opus_result.get("recommend_early_adjust", False)
    result["remaining_runs"] = opus_result.get("remaining_runs", 0)
    result["opus_prior"] = {
        "passes": opus_passes,
        "total": opus_total,
        "trials": opus_trials,
    }
    return result


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
                "early_stopped": v.get("early_stopped"),
                "trials": v.get("trials", []),
                "test_stats": v.get("test_stats"),
            }
            for tier, v in tier_results.items()
        },
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python evaluate.py <task_dir> [--skip-filters] [--include-haiku] [--skip-sonnet] [--trials N]")
        sys.exit(1)

    task_dir = sys.argv[1]
    skip_filters = "--skip-filters" in sys.argv
    skip_haiku = "--include-haiku" not in sys.argv
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
