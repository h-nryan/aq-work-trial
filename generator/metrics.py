"""
Pipeline metrics — aggregates results across all batches and renders a summary.

Reads batch report JSON files and incremental JSONL files to produce:
- Structural / functional / learnable pass rates
- Per-batch breakdown
- Cost and time totals
- Learnable task inventory

Usage:
    python metrics.py [output_dir]       # defaults to ../output
    python metrics.py --html report.html # render HTML dashboard
"""

from __future__ import annotations

import json
import glob
import os
import sys
from datetime import datetime
from pathlib import Path


def _load_batch_results(output_dir: str) -> list[dict]:
    """Load all batch results from report and incremental files.

    When both a report and incremental file exist, the report is primary but
    incremental results are merged in for any topic where the report has
    null/missing classification but the incremental file has real data.
    This handles crashed/aborted batches that wrote stub reports.
    """
    batches = []

    for batch_dir in sorted(glob.glob(os.path.join(output_dir, "sonnet-batch-*"))):
        batch_name = os.path.basename(batch_dir)

        report = glob.glob(os.path.join(batch_dir, "batch-*-report.json"))
        incremental = glob.glob(os.path.join(batch_dir, "batch-*-incremental.jsonl"))

        results = []
        if report:
            try:
                data = json.load(open(report[0]))
                results = data.get("results", [])
            except (json.JSONDecodeError, KeyError):
                pass

            # Merge incremental data for tasks the report missed (crashed/aborted)
            if incremental:
                incr_by_topic: dict[str, dict] = {}
                for line in open(incremental[0]):
                    line = line.strip()
                    if line:
                        try:
                            r = json.loads(line)
                            topic = r.get("topic")
                            if topic and r.get("classification"):
                                incr_by_topic[topic] = r
                        except json.JSONDecodeError:
                            pass

                if incr_by_topic:
                    report_topics = {r.get("topic") for r in results}
                    # Replace stub results with real incremental data
                    results = [
                        incr_by_topic.get(r.get("topic"), r)
                        if not r.get("classification") and r.get("topic") in incr_by_topic
                        else r
                        for r in results
                    ]
                    # Add any incremental results for topics not in report at all
                    for topic, r in incr_by_topic.items():
                        if topic not in report_topics:
                            results.append(r)

        elif incremental:
            for line in open(incremental[0]):
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        if results:
            batches.append({"name": batch_name, "results": results})

    return batches


def compute_aggregate_metrics(batches: list[dict]) -> dict:
    """Compute aggregate metrics across all batches."""
    all_results = []
    for b in batches:
        all_results.extend(b["results"])

    total = len(all_results)
    generated = sum(1 for r in all_results
                    if r.get("status") not in ("generation_failed", "retry_generation_failed")
                    and not str(r.get("status", "")).startswith("error"))
    structural = sum(1 for r in all_results
                     if r.get("stages", {}).get("structural", {}).get("passed", False))
    functional = sum(1 for r in all_results
                     if r.get("stages", {}).get("functional", {}).get("passed", False))
    evaluated = [r for r in all_results if r.get("classification")]
    learnable = sum(1 for r in evaluated if r.get("classification") == "learnable")
    too_easy = sum(1 for r in evaluated if r.get("classification") == "too_easy")
    too_hard = sum(1 for r in evaluated if r.get("classification") == "too_hard")

    # Cost estimation (rough, from generation tokens)
    total_gen_tokens = sum(
        r.get("stages", {}).get("generate", {}).get("usage", {}).get("total_tokens", 0)
        for r in all_results
    )

    # Time
    total_duration = sum(r.get("duration_sec", 0) for r in all_results)

    return {
        "total_tasks": total,
        "generated": generated,
        "structural_pass": structural,
        "functional_pass": functional,
        "evaluated": len(evaluated),
        "learnable": learnable,
        "too_easy": too_easy,
        "too_hard": too_hard,
        "learnable_yield": round(learnable / total, 4) if total > 0 else 0,
        "functional_rate": round(functional / generated, 4) if generated > 0 else 0,
        "learnable_of_evaluated": round(learnable / len(evaluated), 4) if evaluated else 0,
        "total_gen_tokens": total_gen_tokens,
        "total_duration_sec": round(total_duration, 1),
        "num_batches": len(batches),
    }


def compute_per_batch_metrics(batches: list[dict]) -> list[dict]:
    """Compute metrics per batch."""
    per_batch = []
    for b in batches:
        results = b["results"]
        total = len(results)
        functional = sum(1 for r in results
                         if r.get("stages", {}).get("functional", {}).get("passed", False))
        evaluated = [r for r in results if r.get("classification")]
        learnable = sum(1 for r in evaluated if r.get("classification") == "learnable")
        too_hard = sum(1 for r in evaluated if r.get("classification") == "too_hard")
        too_easy = sum(1 for r in evaluated if r.get("classification") == "too_easy")
        duration = sum(r.get("duration_sec", 0) for r in results)

        per_batch.append({
            "name": b["name"],
            "total": total,
            "functional": functional,
            "evaluated": len(evaluated),
            "learnable": learnable,
            "too_easy": too_easy,
            "too_hard": too_hard,
            "duration_min": round(duration / 60, 1),
        })
    return per_batch


def get_learnable_inventory(batches: list[dict]) -> list[dict]:
    """Extract all learnable tasks."""
    inventory = []
    for b in batches:
        for r in b["results"]:
            if r.get("classification") == "learnable":
                inventory.append({
                    "batch": b["name"],
                    "topic": r.get("topic", "?"),
                    "pass_rate": r.get("pass_rate", 0),
                    "retries": r.get("retries", 0),
                })
    return inventory


def print_metrics(output_dir: str) -> dict:
    """Print formatted metrics report."""
    batches = _load_batch_results(output_dir)
    if not batches:
        print(f"No batch results found in {output_dir}")
        return {}

    agg = compute_aggregate_metrics(batches)
    per_batch = compute_per_batch_metrics(batches)
    learnable_tasks = get_learnable_inventory(batches)

    print(f"\n{'='*70}")
    print(f"PIPELINE METRICS REPORT")
    print(f"{'='*70}")

    print(f"\n--- Aggregate ({agg['num_batches']} batches, {agg['total_tasks']} tasks) ---")
    print(f"  Generated:          {agg['generated']:>4}")
    print(f"  Structural pass:    {agg['structural_pass']:>4}")
    print(f"  Functional pass:    {agg['functional_pass']:>4}  ({agg['functional_rate']:.0%} of generated)")
    print(f"  Evaluated:          {agg['evaluated']:>4}")
    print(f"  Learnable:          {agg['learnable']:>4}  ({agg['learnable_yield']:.0%} of total, "
          f"{agg['learnable_of_evaluated']:.0%} of evaluated)")
    print(f"  Too easy:           {agg['too_easy']:>4}")
    print(f"  Too hard:           {agg['too_hard']:>4}")
    print(f"  Gen tokens:         {agg['total_gen_tokens']:>10,}")
    print(f"  Total time:         {agg['total_duration_sec']/60:>7.0f} min")

    print(f"\n--- Pipeline Funnel ---")
    steps = [
        ("Tasks attempted", agg["total_tasks"]),
        ("Generated", agg["generated"]),
        ("Structural pass", agg["structural_pass"]),
        ("Functional pass", agg["functional_pass"]),
        ("Evaluated", agg["evaluated"]),
        ("Learnable", agg["learnable"]),
    ]
    for i, (label, count) in enumerate(steps):
        bar = "#" * min(count, 50)
        prev = steps[i-1][1] if i > 0 else count
        pct = f"({count/prev:.0%})" if prev > 0 and i > 0 else ""
        print(f"  {label:<20} {count:>4} {pct:>6}  {bar}")

    print(f"\n--- Per-Batch Breakdown ---")
    print(f"  {'Batch':<40} {'Total':>5} {'Func':>5} {'Eval':>5} {'Learn':>5} {'Easy':>5} {'Hard':>5} {'Time':>6}")
    print(f"  {'-'*40} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*6}")
    for b in per_batch:
        print(f"  {b['name']:<40} {b['total']:>5} {b['functional']:>5} "
              f"{b['evaluated']:>5} {b['learnable']:>5} {b['too_easy']:>5} "
              f"{b['too_hard']:>5} {b['duration_min']:>5.0f}m")

    if learnable_tasks:
        print(f"\n--- Learnable Task Inventory ({len(learnable_tasks)} tasks) ---")
        for t in learnable_tasks:
            print(f"  [{t['pass_rate']:.0%}] {t['topic'][:55]} ({t['batch']})")

    print(f"\n{'='*70}")

    return {"aggregate": agg, "per_batch": per_batch, "learnable": learnable_tasks}


def render_html(metrics: dict, output_path: str) -> None:
    """Render metrics as a standalone HTML dashboard."""
    agg = metrics.get("aggregate", {})
    per_batch = metrics.get("per_batch", [])
    learnable = metrics.get("learnable", [])

    html = f"""<!DOCTYPE html>
<html>
<head>
<title>Pipeline Metrics Dashboard</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #f8f9fa; }}
  h1 {{ color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: 10px; }}
  h2 {{ color: #16213e; margin-top: 30px; }}
  .metrics-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 15px; margin: 20px 0; }}
  .metric-card {{ background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
  .metric-value {{ font-size: 2.5em; font-weight: bold; color: #0f3460; }}
  .metric-label {{ color: #666; font-size: 0.9em; margin-top: 5px; }}
  .metric-highlight {{ color: #e94560; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  th {{ background: #16213e; color: white; padding: 12px 15px; text-align: left; }}
  td {{ padding: 10px 15px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #f0f4ff; }}
  .funnel {{ background: white; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .funnel-bar {{ background: #e8eaf6; border-radius: 4px; margin: 8px 0; overflow: hidden; }}
  .funnel-fill {{ background: linear-gradient(90deg, #0f3460, #16213e); padding: 8px 15px; color: white; font-size: 0.9em; border-radius: 4px; }}
  .learnable-item {{ background: white; border-radius: 8px; padding: 15px; margin: 10px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; justify-content: space-between; align-items: center; }}
  .pass-rate {{ font-size: 1.3em; font-weight: bold; color: #0f3460; }}
  .timestamp {{ color: #999; font-size: 0.85em; margin-top: 10px; }}
</style>
</head>
<body>
<h1>Task Generation Pipeline Metrics</h1>
<p class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="metrics-grid">
  <div class="metric-card">
    <div class="metric-value">{agg.get('total_tasks', 0)}</div>
    <div class="metric-label">Tasks Attempted</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">{agg.get('functional_pass', 0)}</div>
    <div class="metric-label">Functional Pass</div>
  </div>
  <div class="metric-card">
    <div class="metric-value metric-highlight">{agg.get('learnable', 0)}</div>
    <div class="metric-label">Learnable</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">{agg.get('learnable_yield', 0):.0%}</div>
    <div class="metric-label">Learnable Yield</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">{agg.get('total_gen_tokens', 0):,}</div>
    <div class="metric-label">Generation Tokens</div>
  </div>
  <div class="metric-card">
    <div class="metric-value">{agg.get('total_duration_sec', 0)/60:.0f}m</div>
    <div class="metric-label">Total Time</div>
  </div>
</div>

<h2>Pipeline Funnel</h2>
<div class="funnel">"""

    max_val = max(agg.get("total_tasks", 1), 1)
    for label, key in [("Generated", "generated"), ("Structural", "structural_pass"),
                        ("Functional", "functional_pass"), ("Evaluated", "evaluated"),
                        ("Learnable", "learnable")]:
        val = agg.get(key, 0)
        width = max(val / max_val * 100, 5)
        html += f"""
  <div class="funnel-bar">
    <div class="funnel-fill" style="width: {width:.0f}%">{label}: {val}</div>
  </div>"""

    html += """
</div>

<h2>Per-Batch Breakdown</h2>
<table>
<tr><th>Batch</th><th>Total</th><th>Functional</th><th>Evaluated</th><th>Learnable</th><th>Too Easy</th><th>Too Hard</th><th>Time</th></tr>"""

    for b in per_batch:
        html += f"""
<tr>
  <td>{b['name']}</td><td>{b['total']}</td><td>{b['functional']}</td>
  <td>{b['evaluated']}</td><td><strong>{b['learnable']}</strong></td>
  <td>{b['too_easy']}</td><td>{b['too_hard']}</td><td>{b['duration_min']:.0f}m</td>
</tr>"""

    html += "</table>"

    if learnable:
        html += """
<h2>Learnable Task Inventory</h2>"""
        for t in learnable:
            html += f"""
<div class="learnable-item">
  <div>
    <strong>{t['topic'][:60]}</strong><br>
    <small>{t['batch']} | {t['retries']} retries</small>
  </div>
  <div class="pass-rate">{t['pass_rate']:.0%}</div>
</div>"""

    html += """
</body>
</html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"\nHTML dashboard saved to: {output_path}")


if __name__ == "__main__":
    output_dir = "../output"
    html_path = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--html" and i + 1 < len(args):
            html_path = args[i + 1]
            i += 2
        else:
            output_dir = args[i]
            i += 1

    metrics = print_metrics(output_dir)

    if html_path and metrics:
        render_html(metrics, html_path)

    # Save JSON
    if metrics:
        json_path = os.path.join(output_dir, "pipeline-metrics.json")
        with open(json_path, "w") as f:
            json.dump(metrics, f, indent=2, default=str)
        print(f"JSON metrics saved to: {json_path}")
