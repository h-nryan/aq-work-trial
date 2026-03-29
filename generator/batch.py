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

# Diverse topics that should produce Opus-challenging tasks
DEFAULT_TOPICS = [
    "fix a broken Python async web scraper with rate limiting bugs",
    "debug a C program with memory corruption in a linked list implementation",
    "fix a broken Bash deployment script with race conditions and path issues",
    "repair a Python data pipeline that silently drops records during CSV transformation",
    "fix a broken Node.js REST API with authentication and database connection bugs",
    "debug a broken Makefile for a multi-target C project with linking errors",
    "fix a Python logging system with broken rotation, formatting, and handler issues",
    "repair a broken shell script that manages systemd services with incorrect status parsing",
    "fix a broken Python SQLite database migration script with schema and data bugs",
    "debug a broken Docker Compose setup for a multi-service application",
    "fix a Python config parser that mishandles nested YAML, environment overrides, and defaults",
    "repair a broken Git hooks setup with pre-commit validation and commit message formatting",
    "fix a broken Python test framework with fixture scoping and assertion bugs",
    "debug a broken Nginx reverse proxy configuration with routing and SSL issues",
    "fix a Python CLI tool with broken argument parsing, subcommands, and output formatting",
]


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
        topics: List of topic strings. If None, uses DEFAULT_TOPICS.
        n_tasks: Number of tasks to generate (caps topics list).
        skip_eval: Skip agent evaluation (useful for testing generation only).
        skip_functional: Skip Docker functional validation.
        skip_prefilter: Skip Haiku pre-filter.
        output_dir: Base output directory for generated tasks.

    Returns:
        dict with per-task results and aggregate metrics.
    """
    batch_start = time.time()
    batch_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    if topics is None:
        topics = DEFAULT_TOPICS

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
        classification = r.get("classification") or "-"
        pass_rate = r.get("pass_rate")
        pass_rate_str = f"{pass_rate:.0%}" if isinstance(pass_rate, (int, float)) else "-"
        print(f"  {topic:<55} {status:<25} {classification:<10} {pass_rate_str}")


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

    run_batch(
        topics=custom_topics,
        n_tasks=n_tasks,
        skip_eval=skip_eval,
        skip_functional=skip_functional,
        skip_filters=skip_filters,
    )
