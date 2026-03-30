"""
Batch generation — generate multiple tasks, validate, evaluate, and report metrics.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from batch_io import load_incremental, load_meta, resolve_resume, save_meta
from config import GENERATOR_MODEL, OPENROUTER_API_KEY, OUTPUT_DIR, SONNET_FILTER_MODEL, _slugify
from evaluate import cleanup_stale_resources
from pipeline import run_pipeline
from prompts import get_category_for_topic, select_topics


def _atexit_cleanup() -> None:
    """Kill orphaned Docker containers and stale processes on batch exit.

    Registered via atexit so that if the batch process crashes, gets killed,
    or finishes normally, we don't leave zombie containers running.
    Uses a short age threshold (60s) since we know the batch is over.
    """
    cleaned = cleanup_stale_resources(max_age_sec=60)
    if cleaned:
        print(f"\natexit: cleaned up {cleaned} orphaned resource(s)")


atexit.register(_atexit_cleanup)


def preflight_checks(
    output_dir: str,
    skip_functional: bool = False,
    skip_eval: bool = False,
) -> list[str]:
    """Run pre-batch sanity checks. Returns a list of warnings (empty = all clear).

    Raises RuntimeError for fatal issues that would waste money/time.
    """
    warnings: list[str] = []

    # 1. API key
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Export it before running a batch."
        )

    # 2. Docker (only needed for functional validation / eval)
    if not skip_functional or not skip_eval:
        docker_path = shutil.which("docker")
        if not docker_path:
            raise RuntimeError(
                "Docker CLI not found on PATH. Install Docker Desktop or "
                "pass --skip-functional --skip-eval to skip Docker steps."
            )
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "Docker daemon is not running. Start Docker Desktop or "
                    "pass --skip-functional --skip-eval to skip Docker steps."
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker daemon did not respond within 10s.")

    # 3. tb CLI (needed for evaluation)
    if not skip_eval:
        if not shutil.which("tb"):
            raise RuntimeError(
                "tb CLI not found on PATH. Install terminal_bench or "
                "pass --skip-eval to skip evaluation."
            )

    # 4. Output directory writable
    os.makedirs(output_dir, exist_ok=True)
    test_file = os.path.join(output_dir, ".preflight-test")
    try:
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
    except OSError as e:
        raise RuntimeError(f"Output directory not writable: {output_dir} ({e})")

    # 5. Disk space (warn if < 5 GB free)
    try:
        stat = os.statvfs(output_dir)
        free_gb = (stat.f_frsize * stat.f_bavail) / (1024 ** 3)
        if free_gb < 5:
            warnings.append(f"Low disk space: {free_gb:.1f} GB free in {output_dir}")
    except (OSError, AttributeError):
        pass  # statvfs not available on all platforms

    return warnings

# Approximate per-token costs (USD) for OpenRouter models.
# Used for cost estimation only — actual costs may vary.
MODEL_COSTS_PER_1K = {
    "anthropic/claude-sonnet-4.5": {"input": 0.003, "output": 0.015},
    "anthropic/claude-3.5-haiku": {"input": 0.0008, "output": 0.004},
    "anthropic/claude-opus-4": {"input": 0.015, "output": 0.075},
}


def run_batch(
    topics: list | None = None,
    n_tasks: int = 10,
    skip_eval: bool = False,
    skip_functional: bool = False,
    skip_filters: bool = False,
    output_dir: str | None = None,
    seed: int | None = None,
    n_concurrent: int = 1,
    resume_from: str | None = None,
    solution_first: bool = True,
    prompt_variant: str = "A",
    hint_style: str = "none",
) -> dict:
    """Generate and evaluate a batch of tasks.

    Args:
        topics: List of topic strings. If None, selects from prompt bank.
        n_tasks: Number of tasks to generate (caps topics list).
        skip_eval: Skip agent evaluation (useful for testing generation only).
        skip_functional: Skip Docker functional validation.
        skip_filters: Skip tiered filters.
        output_dir: Base output directory for generated tasks.
        seed: Random seed for prompt bank selection (reproducibility).
        n_concurrent: Number of tasks to run in parallel.
        resume_from: Batch ID or path to resume an interrupted batch. Pass
            "auto" to resume the most recent incomplete batch in output_dir.

    Returns:
        dict with per-task results and aggregate metrics.
    """
    batch_start = time.time()
    batch_output_dir = output_dir or OUTPUT_DIR

    # ── Pre-flight checks ─────────────────────────────────────────────────────
    warnings = preflight_checks(
        output_dir=batch_output_dir,
        skip_functional=skip_functional,
        skip_eval=skip_eval,
    )
    for w in warnings:
        print(f"  WARNING: {w}")

    # ── Resume path ──────────────────────────────────────────────────────────
    prior_results: list[dict] = []
    completed_topics: set[str] = set()

    if resume_from is not None:
        batch_id, meta_path, incremental_path = resolve_resume(
            resume_from, batch_output_dir
        )
        meta = load_meta(meta_path)
        if meta is not None:
            # Restore original topic list from saved metadata
            topics = meta["topics"]
            n_tasks = len(topics)
            if seed is None:
                seed = meta.get("seed")
        prior_results, completed_topics = load_incremental(incremental_path)
        print(f"\n{'#'*60}")
        print(f"Resuming batch: {batch_id}")
        print(f"  Already done: {len(completed_topics)}/{len(topics or [])}")
        print(f"  Remaining:    {len(topics or []) - len(completed_topics)}")
        print(f"{'#'*60}")
    else:
        batch_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        meta_path = os.path.join(batch_output_dir, f"batch-{batch_id}-meta.json")
        incremental_path = os.path.join(
            batch_output_dir, f"batch-{batch_id}-incremental.jsonl"
        )

    # ── Topic selection ───────────────────────────────────────────────────────
    if topics is None:
        topics = select_topics(n=n_tasks, diverse=True, seed=seed)
    else:
        topics = topics[:n_tasks]

    # Save metadata on first run (not on resume — it already exists)
    if resume_from is None:
        save_meta(meta_path, batch_id, topics, seed)

    remaining = [t for t in topics if t not in completed_topics]

    print(f"\n{'#'*60}")
    print(f"Batch Generation: {batch_id}")
    print(f"Tasks planned: {len(topics)}  |  Remaining: {len(remaining)}")
    if seed is not None:
        print(f"Seed: {seed}")
    print(f"Output: {batch_output_dir}")
    print(f"{'#'*60}")

    # ── Per-task runner ───────────────────────────────────────────────────────
    # Build a lookup of topic → original plan index for progress display.
    topic_plan_index = {t: i for i, t in enumerate(topics)}
    write_lock = threading.Lock()

    def _run_one(topic: str) -> dict:
        global_idx = topic_plan_index.get(topic, 0) + 1
        print(f"\n[{global_idx}/{len(topics)}] {topic}")
        task_output_dir = os.path.join(batch_output_dir, _slugify(topic))
        try:
            result = run_pipeline(
                topic=topic,
                output_dir=task_output_dir,
                skip_eval=skip_eval,
                skip_functional=skip_functional,
                skip_filters=skip_filters,
                solution_first=solution_first,
                prompt_variant=prompt_variant,
                hint_style=hint_style,
                target_category=get_category_for_topic(topic),
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            result = {
                "topic": topic,
                "status": f"error: {e}",
                "classification": None,
            }
        # Lock around file append — concurrent threads writing to the same file
        # without synchronisation can interleave bytes and corrupt the JSONL.
        with write_lock:
            with open(incremental_path, "a") as f:
                f.write(json.dumps(result, default=str) + "\n")
        return result

    new_results: list[dict] = []
    if remaining:
        workers = min(n_concurrent, len(remaining))
        if workers <= 1:
            for topic in remaining:
                new_results.append(_run_one(topic))
        else:
            print(f"Running {workers} tasks concurrently ({len(remaining)} remaining)")
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_run_one, topic): i
                    for i, topic in enumerate(remaining)
                }
                new_results = [None] * len(remaining)
                for future in as_completed(futures):
                    idx = futures[future]
                    new_results[idx] = future.result()

    # Merge in original topic order: prior results first, then new, preserving
    # the order topics were originally planned so the report is consistent.
    completed_map = {r["topic"]: r for r in prior_results}
    completed_map.update({r["topic"]: r for r in new_results if r is not None})
    results = [completed_map[t] for t in topics if t in completed_map]

    batch_duration = time.time() - batch_start

    # ── Final report ──────────────────────────────────────────────────────────
    metrics = _compute_metrics(results, batch_duration, batch_id)
    report_path = os.path.join(batch_output_dir, f"batch-{batch_id}-report.json")
    with open(report_path, "w") as f:
        json.dump({"metrics": metrics, "results": results}, f, indent=2, default=str)

    _print_report(metrics, results)
    print(f"\nFull report saved to: {report_path}")

    # Clean up working files now that the final report is written
    for path in (incremental_path, meta_path):
        if os.path.exists(path):
            os.remove(path)

    return {"metrics": metrics, "results": results}


def _estimate_cost(results: list) -> dict:
    """Estimate dollar costs from token counts.

    Returns dict with generation_cost, eval_cost, total_cost (all USD floats).
    """
    gen_cost = 0.0
    eval_cost = 0.0

    for r in results:
        stages = r.get("stages", {})

        # Generation cost (Sonnet)
        gen_usage = stages.get("generate", {}).get("usage", {})
        gen_model = stages.get("generate", {}).get("model", GENERATOR_MODEL)
        rates = MODEL_COSTS_PER_1K.get(gen_model, MODEL_COSTS_PER_1K.get(GENERATOR_MODEL, {}))
        if gen_usage and rates:
            gen_cost += gen_usage.get("prompt_tokens", 0) / 1000 * rates.get("input", 0)
            gen_cost += gen_usage.get("completion_tokens", 0) / 1000 * rates.get("output", 0)

        # Evaluation cost (from trial token counts across all tiers)
        eval_stages = stages.get("evaluation", {})
        for tier_key in ("haiku_filter", "sonnet_filter", "opus_eval", "trials"):
            tier = eval_stages.get(tier_key, {})
            trials = tier.get("trials", []) if isinstance(tier, dict) else []
            for trial in trials:
                if not isinstance(trial, dict):
                    continue
                in_tok = trial.get("input_tokens") or 0
                out_tok = trial.get("output_tokens") or 0
                # Rough model assignment by tier name
                if "haiku" in str(tier_key):
                    tier_rates = MODEL_COSTS_PER_1K.get("anthropic/claude-3.5-haiku", {})
                elif "sonnet" in str(tier_key):
                    tier_rates = MODEL_COSTS_PER_1K.get(SONNET_FILTER_MODEL, {})
                else:
                    tier_rates = MODEL_COSTS_PER_1K.get("anthropic/claude-opus-4", {})
                eval_cost += in_tok / 1000 * tier_rates.get("input", 0)
                eval_cost += out_tok / 1000 * tier_rates.get("output", 0)

    return {
        "generation_cost_usd": round(gen_cost, 4),
        "evaluation_cost_usd": round(eval_cost, 4),
        "total_cost_usd": round(gen_cost + eval_cost, 4),
    }


def _compute_metrics(results: list, duration: float, batch_id: str) -> dict:
    """Compute aggregate metrics from batch results."""
    total = len(results)

    # Pipeline funnel counts
    generated = sum(1 for r in results if r.get("status") != "generation_failed"
                    and not str(r.get("status", "")).startswith("error"))
    structural_pass = sum(
        1 for r in results
        if r.get("stages", {}).get("structural", {}).get("passed", False)
    )
    functional_tested = sum(
        1 for r in results if "functional" in r.get("stages", {})
    )
    functional_pass = sum(
        1 for r in results
        if r.get("stages", {}).get("functional", {}).get("passed", False)
    )
    evaluated = [r for r in results if r.get("stages", {}).get("evaluation")]
    learnable = sum(1 for r in evaluated if r.get("classification") == "learnable")
    too_easy = sum(1 for r in evaluated if r.get("classification") == "too_easy")
    too_hard = sum(1 for r in evaluated if r.get("classification") == "too_hard")

    # Error categorization — group failures by the stage where they stopped.
    # Prefers the structured failed_stage field (set by pipeline.py); falls back
    # to parsing the status string for results from older runs or bare exceptions.
    error_categories: dict[str, int] = {}
    for r in results:
        status = str(r.get("status", ""))
        if status == "completed":
            continue
        stage = r.get("failed_stage")
        if stage:
            error_categories[stage] = error_categories.get(stage, 0) + 1
        elif status == "generation_failed" or status.startswith("phase"):
            error_categories["generation"] = error_categories.get("generation", 0) + 1
        elif "structural" in status:
            error_categories["structural"] = error_categories.get("structural", 0) + 1
        elif "functional" in status or "infrastructure" in status:
            error_categories["functional"] = error_categories.get("functional", 0) + 1
        elif status.startswith("error"):
            error_categories["exception"] = error_categories.get("exception", 0) + 1
        else:
            error_categories["other"] = error_categories.get("other", 0) + 1

    # Token counts
    total_gen_tokens = sum(
        r.get("stages", {}).get("generate", {}).get("usage", {}).get("total_tokens", 0)
        for r in results
    )

    # Cost estimates
    costs = _estimate_cost(results)

    return {
        "batch_id": batch_id,
        # Funnel
        "total_topics": total,
        "generated": generated,
        "structural_pass": structural_pass,
        "functional_tested": functional_tested,
        "functional_pass": functional_pass,
        "evaluated": len(evaluated),
        "learnable": learnable,
        "too_easy": too_easy,
        "too_hard": too_hard,
        "learnable_rate": round(learnable / len(evaluated), 4) if evaluated else 0,
        # Errors
        "error_categories": error_categories,
        # Tokens & cost
        "total_gen_tokens": total_gen_tokens,
        **costs,
        # Time
        "total_duration_sec": round(duration, 2),
        "avg_duration_per_task_sec": round(duration / total, 2) if total > 0 else 0,
    }


def _print_report(metrics: dict, results: list) -> None:
    """Print a formatted metrics report."""
    print(f"\n{'#'*60}")
    print(f"BATCH METRICS REPORT")
    print(f"{'#'*60}")

    # Pipeline funnel
    total = metrics["total_topics"]
    gen = metrics["generated"]
    sp = metrics["structural_pass"]
    ft = metrics["functional_tested"]
    fp = metrics["functional_pass"]
    ev = metrics["evaluated"]
    lr = metrics["learnable"]

    print(f"\n--- Pipeline Funnel ---")
    print(f"  Topics attempted:       {total}")
    print(f"  Generated successfully: {gen:>3}  ({_pct(gen, total)})")
    print(f"  Structural pass:        {sp:>3}  ({_pct(sp, gen)})")
    if ft > 0:
        print(f"  Functional pass:        {fp:>3}  ({_pct(fp, ft)})")
    if ev > 0:
        print(f"  Evaluated:              {ev:>3}")
        print(f"  Learnable (1-3/5):      {lr:>3}  ({_pct(lr, ev)})")
        print(f"  Too easy (4-5/5):       {metrics['too_easy']:>3}")
        print(f"  Too hard (0/5):         {metrics['too_hard']:>3}")

    # Yield: what fraction of attempted topics produced a learnable task
    if total > 0 and lr > 0:
        print(f"\n  Yield (learnable/attempted): {_pct(lr, total)}")

    # Error breakdown
    errors = metrics.get("error_categories", {})
    if errors:
        print(f"\n--- Errors by Stage ---")
        for stage, count in sorted(errors.items(), key=lambda x: -x[1]):
            print(f"  {stage:<20} {count:>3}")

    print(f"\n--- Cost & Time ---")
    print(f"  Generation tokens: {metrics['total_gen_tokens']:,}")
    gen_cost = metrics.get("generation_cost_usd", 0)
    eval_cost = metrics.get("evaluation_cost_usd", 0)
    total_cost = metrics.get("total_cost_usd", 0)
    if total_cost > 0:
        print(f"  Est. generation cost:  ${gen_cost:.4f}")
        print(f"  Est. evaluation cost:  ${eval_cost:.4f}")
        print(f"  Est. total cost:       ${total_cost:.4f}")
        if lr > 0:
            print(f"  Est. cost/learnable:   ${total_cost / lr:.4f}")
    print(f"  Total duration:    {metrics['total_duration_sec']:.0f}s ({metrics['total_duration_sec']/60:.1f}m)")
    print(f"  Avg per task:      {metrics['avg_duration_per_task_sec']:.0f}s")

    # Per-task summary table
    print(f"\n--- Per-Task Results ---")
    print(f"  {'#':<4} {'Topic':<50} {'Status':<20} {'Class':<10} {'Rate'}")
    print(f"  {'-'*4} {'-'*50} {'-'*20} {'-'*10} {'-'*6}")
    for i, r in enumerate(results, 1):
        topic = r.get("topic", "?")[:49]
        status = r.get("status", "?")[:19]
        classification = r.get("classification") or "-"
        pass_rate = r.get("pass_rate")
        pass_rate_str = f"{pass_rate:.0%}" if isinstance(pass_rate, (int, float)) else "-"
        print(f"  {i:<4} {topic:<50} {status:<20} {classification:<10} {pass_rate_str}")


def _pct(num: int, denom: int) -> str:
    """Format a percentage string, handling zero denominator."""
    if denom == 0:
        return "- %"
    return f"{num/denom:.0%}"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Batch task generation with validation and evaluation.",
    )
    parser.add_argument(
        "--n-tasks", type=int, default=10,
        help="Number of tasks to generate (default: 10)",
    )
    parser.add_argument(
        "--topic", action="append", dest="topics",
        help="Specific topic string (can be repeated). Overrides prompt bank.",
    )
    parser.add_argument(
        "--category",
        help="Filter prompt bank by category (e.g., debugging, networking)",
    )
    parser.add_argument(
        "--difficulty",
        help="Filter prompt bank by difficulty (easy, medium, hard)",
    )
    parser.add_argument(
        "--language",
        help="Filter prompt bank by language (e.g., python, bash, go)",
    )
    parser.add_argument(
        "--output-dir",
        help="Base output directory for generated tasks and reports",
    )
    parser.add_argument(
        "--seed", type=int,
        help="Random seed for reproducible prompt bank selection",
    )
    parser.add_argument(
        "--n-concurrent", type=int, default=1,
        help="Number of tasks to run concurrently (default: 1, sequential)",
    )
    parser.add_argument(
        "--skip-eval", action="store_true",
        help="Skip agent evaluation (generation + validation only)",
    )
    parser.add_argument(
        "--skip-functional", action="store_true",
        help="Skip Docker functional validation",
    )
    parser.add_argument(
        "--skip-filters", action="store_true",
        help="Skip Haiku/Sonnet filter tiers (go straight to Opus)",
    )
    parser.add_argument(
        "--no-solution-first", action="store_true",
        help="Disable solution-first generation (use single-phase instead). Not recommended.",
    )
    parser.add_argument(
        "--resume", metavar="BATCH_ID_OR_PATH", nargs="?", const="auto",
        help=(
            "Resume an interrupted batch. Omit the value to auto-detect the most "
            "recent incomplete batch in --output-dir, or pass a batch ID "
            "(e.g. 20240101-120000) or path to a *-incremental.jsonl file."
        ),
    )
    parser.add_argument(
        "--prompt-variant", choices=["A", "B"], default="A",
        help="Prompt variant: A (verbose constraints) or B (trimmed, example-driven)",
    )
    parser.add_argument(
        "--hint-style", choices=["none", "soft", "full"], default="none",
        help="Instruction hint style: none, soft (high-level area), or full (specific areas)",
    )

    args = parser.parse_args()

    # Resolve topics: explicit --topic flags, or prompt bank with filters.
    # Ignored when resuming (original topics are loaded from the meta file).
    topics = args.topics
    if topics is None and any([args.category, args.difficulty, args.language]):
        topics = select_topics(
            n=args.n_tasks,
            category=args.category,
            difficulty=args.difficulty,
            language=args.language,
            diverse=True,
            seed=args.seed,
        )

    run_batch(
        topics=topics,
        n_tasks=args.n_tasks,
        skip_eval=args.skip_eval,
        skip_functional=args.skip_functional,
        skip_filters=args.skip_filters,
        output_dir=args.output_dir,
        seed=args.seed,
        n_concurrent=args.n_concurrent,
        resume_from=args.resume,
        solution_first=not args.no_solution_first,
        prompt_variant=args.prompt_variant,
        hint_style=args.hint_style,
    )
