"""
Quality comparison: generated tasks vs. hand-crafted examples (Stretch Goal D).

Computes structural metrics for individual tasks and compares generated batches
against the reference examples in examples/. Metrics are intentionally simple
and file-derived — no LLM calls, no Docker builds.

Metrics per task:
  - instruction_length: character count of the task.yaml instruction
  - solution_lines: line count of solution.sh
  - test_lines: line count of tests/test_outputs.py
  - test_count: number of `def test_` functions in the test file
  - file_count: total files in the task directory (excl. dotfiles and _debug files)
  - source_file_count: files that aren't infrastructure (task.yaml, Dockerfile, etc.)
  - has_dockerfile: bool
  - has_docker_compose: bool
  - dockerfile_installs_tmux: bool (required by harness)

Comparison output:
  - Per-metric min/mean/median/max for examples and generated sets
  - Delta between means (generated - example) with direction indicator
  - Flags for outliers (generated tasks far outside the example range)
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from config import EXAMPLES_DIR

# Infrastructure files that every task must have — not "source code"
INFRASTRUCTURE_FILES = {
    "task.yaml",
    "Dockerfile",
    "docker-compose.yaml",
    "run-tests.sh",
    "solution.sh",
}


def analyze_task(task_dir: str) -> dict | None:
    """Compute quality metrics for a single task directory.

    Returns None if task_dir is missing task.yaml (not a valid task).
    """
    task_path = Path(task_dir)
    yaml_path = task_path / "task.yaml"
    if not yaml_path.exists():
        return None

    # Instruction length from task.yaml
    try:
        import yaml

        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        instruction = data.get("instruction", "") if isinstance(data, dict) else ""
    except Exception:
        instruction = ""

    # Solution lines
    solution_path = task_path / "solution.sh"
    solution_lines = _count_lines(solution_path)

    # Test file metrics
    test_path = task_path / "tests" / "test_outputs.py"
    test_lines = _count_lines(test_path)
    test_count = _count_test_functions(test_path)

    # File counts
    all_files = [
        f
        for f in task_path.rglob("*")
        if f.is_file() and not f.name.startswith(".") and not f.name.startswith("_")
    ]
    file_count = len(all_files)

    source_files = [
        f
        for f in all_files
        if f.relative_to(task_path).parts[0] not in ("tests",)
        and f.name not in INFRASTRUCTURE_FILES
    ]
    source_file_count = len(source_files)

    # Dockerfile checks
    dockerfile_path = task_path / "Dockerfile"
    has_dockerfile = dockerfile_path.exists()
    dockerfile_installs_tmux = False
    if has_dockerfile:
        try:
            content = dockerfile_path.read_text()
            dockerfile_installs_tmux = "tmux" in content
        except OSError:
            pass

    has_docker_compose = (task_path / "docker-compose.yaml").exists()

    return {
        "task_name": task_path.name,
        "task_dir": str(task_path),
        "instruction_length": len(instruction),
        "solution_lines": solution_lines,
        "test_lines": test_lines,
        "test_count": test_count,
        "file_count": file_count,
        "source_file_count": source_file_count,
        "has_dockerfile": has_dockerfile,
        "has_docker_compose": has_docker_compose,
        "dockerfile_installs_tmux": dockerfile_installs_tmux,
    }


def analyze_examples(examples_dir: str | None = None) -> list[dict]:
    """Analyze all hand-crafted example tasks."""
    examples_path = Path(examples_dir or EXAMPLES_DIR)
    results = []
    for task_dir in sorted(examples_path.iterdir()):
        if not task_dir.is_dir():
            continue
        metrics = analyze_task(str(task_dir))
        if metrics is not None:
            results.append(metrics)
    return results


def analyze_generated(task_dirs: list[str]) -> list[dict]:
    """Analyze a list of generated task directories."""
    results = []
    for td in task_dirs:
        metrics = analyze_task(td)
        if metrics is not None:
            results.append(metrics)
    return results


def compare(
    example_metrics: list[dict],
    generated_metrics: list[dict],
) -> dict:
    """Compare generated task metrics against example baselines.

    Returns a dict with per-metric stats for both sets and deltas.
    """
    numeric_keys = [
        "instruction_length",
        "solution_lines",
        "test_lines",
        "test_count",
        "file_count",
        "source_file_count",
    ]

    comparison = {}
    for key in numeric_keys:
        ex_values = [m[key] for m in example_metrics if m[key] is not None]
        gen_values = [m[key] for m in generated_metrics if m[key] is not None]

        ex_stats = _compute_stats(ex_values)
        gen_stats = _compute_stats(gen_values)

        delta_mean = None
        if ex_stats["mean"] is not None and gen_stats["mean"] is not None:
            delta_mean = round(gen_stats["mean"] - ex_stats["mean"], 1)

        comparison[key] = {
            "examples": ex_stats,
            "generated": gen_stats,
            "delta_mean": delta_mean,
        }

    # Boolean checks for generated tasks
    bool_keys = ["has_dockerfile", "has_docker_compose", "dockerfile_installs_tmux"]
    for key in bool_keys:
        gen_true = sum(1 for m in generated_metrics if m.get(key))
        gen_total = len(generated_metrics)
        comparison[key] = {
            "generated_true": gen_true,
            "generated_total": gen_total,
            "generated_pct": round(gen_true / gen_total * 100, 1) if gen_total else None,
        }

    # Flag outlier generated tasks (outside example range by >50%)
    outliers = []
    for key in numeric_keys:
        ex_values = [m[key] for m in example_metrics if m[key] is not None]
        if not ex_values:
            continue
        ex_min, ex_max = min(ex_values), max(ex_values)
        ex_range = ex_max - ex_min or 1
        for m in generated_metrics:
            val = m.get(key)
            if val is None:
                continue
            if val < ex_min - ex_range * 0.5 or val > ex_max + ex_range * 0.5:
                outliers.append({
                    "task": m["task_name"],
                    "metric": key,
                    "value": val,
                    "example_range": [ex_min, ex_max],
                })

    comparison["outliers"] = outliers

    return comparison


def print_comparison(comparison: dict) -> None:
    """Print a human-readable quality comparison report."""
    print(f"\n{'#' * 60}")
    print("QUALITY COMPARISON: Generated vs. Examples")
    print(f"{'#' * 60}")

    numeric_keys = [
        "instruction_length",
        "solution_lines",
        "test_lines",
        "test_count",
        "file_count",
        "source_file_count",
    ]

    print(f"\n{'Metric':<22} {'Examples':>22}  {'Generated':>22}  {'Delta':>8}")
    print("-" * 78)

    for key in numeric_keys:
        if key not in comparison:
            continue
        c = comparison[key]
        ex = c["examples"]
        gen = c["generated"]
        delta = c["delta_mean"]

        ex_str = _format_stats(ex)
        gen_str = _format_stats(gen)
        delta_str = f"{delta:+.1f}" if delta is not None else "N/A"

        print(f"  {key:<20} {ex_str:>22}  {gen_str:>22}  {delta_str:>8}")

    # Boolean checks
    bool_keys = ["has_dockerfile", "has_docker_compose", "dockerfile_installs_tmux"]
    print(f"\n{'Check':<30} {'Generated':>10}")
    print("-" * 42)
    for key in bool_keys:
        if key not in comparison:
            continue
        c = comparison[key]
        pct = c.get("generated_pct")
        pct_str = f"{pct:.0f}%" if pct is not None else "N/A"
        print(f"  {key:<28} {c['generated_true']}/{c['generated_total']} ({pct_str})")

    # Outliers
    outliers = comparison.get("outliers", [])
    if outliers:
        print(f"\n--- Outliers (outside example range) ---")
        for o in outliers:
            print(f"  {o['task']}: {o['metric']}={o['value']} "
                  f"(examples: {o['example_range'][0]}-{o['example_range'][1]})")


def _count_lines(filepath: Path) -> int | None:
    """Count lines in a file, or None if it doesn't exist."""
    if not filepath.exists():
        return None
    try:
        return len(filepath.read_text().splitlines())
    except OSError:
        return None


def _count_test_functions(filepath: Path) -> int | None:
    """Count `def test_*` functions in a Python test file."""
    if not filepath.exists():
        return None
    try:
        content = filepath.read_text()
        return len(re.findall(r"^\s*def\s+test_", content, re.MULTILINE))
    except OSError:
        return None


def _compute_stats(values: list[int | float]) -> dict:
    """Compute min/mean/median/max for a list of numbers."""
    if not values:
        return {"min": None, "max": None, "mean": None, "median": None, "count": 0}
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(statistics.mean(values), 1),
        "median": round(statistics.median(values), 1),
        "count": len(values),
    }


def _format_stats(stats: dict) -> str:
    """Format stats dict as a compact string."""
    if stats["count"] == 0:
        return "N/A"
    return f"{stats['mean']:.0f} ({stats['min']}-{stats['max']})"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python quality.py <task_dir> [<task_dir> ...]")
        print("       python quality.py <output_dir>  (analyzes all tasks in directory)")
        print("\nCompares generated tasks against hand-crafted examples.")
        sys.exit(1)

    # Collect task directories
    task_dirs = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir() and (p / "task.yaml").exists():
            task_dirs.append(str(p))
        elif p.is_dir():
            # Directory of tasks
            for sub in sorted(p.iterdir()):
                if sub.is_dir() and (sub / "task.yaml").exists():
                    task_dirs.append(str(sub))

    if not task_dirs:
        print("No valid task directories found.")
        sys.exit(1)

    example_metrics = analyze_examples()
    generated_metrics = analyze_generated(task_dirs)

    print(f"\nExamples: {len(example_metrics)} tasks")
    print(f"Generated: {len(generated_metrics)} tasks")

    comparison = compare(example_metrics, generated_metrics)
    print_comparison(comparison)

    # Save JSON output
    output = {
        "example_metrics": example_metrics,
        "generated_metrics": generated_metrics,
        "comparison": comparison,
    }
    json_out = "quality-report.json"
    with open(json_out, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nFull report saved to: {json_out}")
