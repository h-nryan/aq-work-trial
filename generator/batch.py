"""
Batch generation — generate multiple tasks, validate, evaluate, and report metrics.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from config import EVAL_TRIALS, OUTPUT_DIR, TASK_CATEGORIES
from pipeline import run_pipeline
from prompts import select_topics


def run_batch(
    topics: Optional[list] = None,
    n_tasks: int = 10,
    skip_eval: bool = False,
    skip_functional: bool = False,
    skip_filters: bool = False,
    output_dir: Optional[str] = None,
) -> dict:
    """Generate and evaluate a batch of tasks.

    Args:
        topics: List of topic strings. If None, selects from prompt bank.
        n_tasks: Number of tasks to generate (caps topics list).
        skip_eval: Skip agent evaluation (useful for testing generation only).
        skip_functional: Skip Docker functional validation.
        skip_filters: Skip tiered filters.
        output_dir: Base output directory for generated tasks.

    Returns:
        dict with per-task results and aggregate metrics.
    """
    batch_start = time.time()
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    if topics is None:
        topics = select_topics(n=n_tasks, diverse=True)
    else:
        topics = topics[:n_tasks]

    print(f"\n{'#'*60}")
    print(f"Batch Generation: {batch_id}")
    print(f"Tasks to generate: {len(topics)}")
    print(f"{'#'*60}")

    results = []
    for i, topic in enumerate(topics):
        print(f"\n[{i+1}/{len(topics)}] {topic}")

        task_output_dir = None
        if output_dir:
            slug = topic.lower().replace(" ", "-").replace("/", "-")[:60]
            task_output_dir = os.path.join(output_dir, slug)

        try:
            result = run_pipeline(
                topic=topic,
                output_dir=task_output_dir,
                skip_eval=skip_eval,
                skip_functional=skip_functional,
                skip_filters=skip_filters,
            )
            results.append(result)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({
                "topic": topic,
                "status": f"error: {e}",
                "classification": None,
            })

    batch_duration = time.time() - batch_start

    # Aggregate metrics
    metrics = _compute_metrics(results, batch_duration, batch_id)

    # Save results
    report_path = os.path.join(output_dir or OUTPUT_DIR, f"batch-{batch_id}-report.json")
    with open(report_path, "w") as f:
        json.dump({"metrics": metrics, "results": results}, f, indent=2, default=str)

    _print_report(metrics, results)
    print(f"\nFull report saved to: {report_path}")

    return {"metrics": metrics, "results": results}


def _compute_metrics(results: list, duration: float, batch_id: str) -> dict:
    """Compute aggregate metrics from batch results."""
    total = len(results)
    generated = sum(1 for r in results if r.get("status") != "generation_failed")
    structural_pass = sum(
        1 for r in results
        if r.get("stages", {}).get("structural", {}).get("passed", False)
    )
    functional_pass = sum(
        1 for r in results
        if r.get("stages", {}).get("functional", {}).get("passed", False)
    )
    # If functional was skipped, count structural passes
    functional_tested = sum(
        1 for r in results if "functional" in r.get("stages", {})
    )

    evaluated = [r for r in results if r.get("stages", {}).get("evaluation")]
    learnable = sum(1 for r in evaluated if r.get("classification") == "learnable")
    too_easy = sum(1 for r in evaluated if r.get("classification") == "too_easy")
    too_hard = sum(1 for r in evaluated if r.get("classification") == "too_hard")

    # Token/cost estimation
    total_gen_tokens = sum(
        r.get("stages", {}).get("generate", {}).get("usage", {}).get("total_tokens", 0)
        for r in results
    )

    return {
        "batch_id": batch_id,
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
        "total_gen_tokens": total_gen_tokens,
        "total_duration_sec": round(duration, 2),
        "avg_duration_per_task_sec": round(duration / total, 2) if total > 0 else 0,
    }


def _print_report(metrics: dict, results: list) -> None:
    """Print a formatted metrics report."""
    print(f"\n{'#'*60}")
    print(f"BATCH METRICS REPORT")
    print(f"{'#'*60}")

    print(f"\n--- Generation ---")
    print(f"  Topics attempted:       {metrics['total_topics']}")
    print(f"  Successfully generated: {metrics['generated']}")

    print(f"\n--- Validation ---")
    print(f"  Structural pass:  {metrics['structural_pass']}/{metrics['generated']}")
    if metrics['functional_tested'] > 0:
        print(f"  Functional pass:  {metrics['functional_pass']}/{metrics['functional_tested']}")

    if metrics['evaluated'] > 0:
        print(f"\n--- Evaluation (Opus, {EVAL_TRIALS} trials each) ---")
        print(f"  Evaluated:   {metrics['evaluated']}")
        print(f"  Learnable:   {metrics['learnable']} ({metrics['learnable_rate']:.0%})")
        print(f"  Too easy:    {metrics['too_easy']}")
        print(f"  Too hard:    {metrics['too_hard']}")

    print(f"\n--- Cost & Time ---")
    print(f"  Generation tokens: {metrics['total_gen_tokens']:,}")
    print(f"  Total duration:    {metrics['total_duration_sec']:.0f}s ({metrics['total_duration_sec']/60:.1f}m)")
    print(f"  Avg per task:      {metrics['avg_duration_per_task_sec']:.0f}s")

    # Per-task summary table
    print(f"\n--- Per-Task Results ---")
    print(f"  {'Topic':<55} {'Status':<25} {'Class':<10} {'Pass Rate'}")
    print(f"  {'-'*55} {'-'*25} {'-'*10} {'-'*9}")
    for r in results:
        topic = r.get("topic", "?")[:54]
        status = r.get("status", "?")[:24]
        classification = r.get("classification", "-")
        pass_rate = r.get("pass_rate", "-")
        if isinstance(pass_rate, float):
            pass_rate = f"{pass_rate:.0%}"
        print(f"  {topic:<55} {status:<25} {classification:<10} {pass_rate}")


if __name__ == "__main__":
    skip_eval = "--skip-eval" in sys.argv
    skip_functional = "--skip-functional" in sys.argv
    skip_filters = "--skip-filters" in sys.argv

    n_tasks = 10
    for i, arg in enumerate(sys.argv):
        if arg == "--n-tasks" and i + 1 < len(sys.argv):
            n_tasks = int(sys.argv[i + 1])

    custom_topics = None
    for i, arg in enumerate(sys.argv):
        if arg == "--topic":
            if custom_topics is None:
                custom_topics = []
            if i + 1 < len(sys.argv):
                custom_topics.append(sys.argv[i + 1])

    # Prompt bank filters (only used when custom_topics is None)
    category = None
    difficulty = None
    language = None
    for i, arg in enumerate(sys.argv):
        if arg == "--category" and i + 1 < len(sys.argv):
            category = sys.argv[i + 1]
        elif arg == "--difficulty" and i + 1 < len(sys.argv):
            difficulty = sys.argv[i + 1]
        elif arg == "--language" and i + 1 < len(sys.argv):
            language = sys.argv[i + 1]

    if custom_topics is None and any([category, difficulty, language]):
        custom_topics = select_topics(
            n=n_tasks, category=category, difficulty=difficulty, language=language, diverse=True,
        )

    run_batch(
        topics=custom_topics,
        n_tasks=n_tasks,
        skip_eval=skip_eval,
        skip_functional=skip_functional,
        skip_filters=skip_filters,
    )
