"""
Pipeline Dashboard — Single-page real-time view of task generation pipeline.

Run: streamlit run dashboard.py
"""

from __future__ import annotations

import json
import glob
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "generator"))
from metrics import (
    _load_batch_results,
    compute_aggregate_metrics,
    compute_per_batch_metrics,
    get_learnable_inventory,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

STAGE_ORDER = ["generating", "structural", "functional", "evaluating", "completed", "failed"]
STAGE_ICONS = {
    "generating": "🔧",
    "structural": "📋",
    "functional": "🐳",
    "evaluating": "🧪",
    "completed": "✅",
    "failed": "❌",
    "queued": "⏳",
}

CUSTOM_CSS = """
<style>
    .stApp { background-color: #0e1117; }

    .pipeline-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px; padding: 20px; margin-bottom: 20px;
        border: 1px solid #1f4068;
    }
    .pipeline-header h2 { margin: 0; color: #e8e8e8; }
    .pipeline-header .subtitle { color: #8892b0; font-size: 0.9em; }

    .task-row {
        display: grid;
        grid-template-columns: 250px repeat(5, 1fr) 120px;
        gap: 8px; align-items: center;
        padding: 10px 15px; margin: 4px 0;
        background: #1a1a2e; border-radius: 8px;
        border-left: 4px solid #2d3748;
    }
    .task-row.learnable { border-left-color: #00d4aa; }
    .task-row.too-hard { border-left-color: #ff6b6b; }
    .task-row.too-easy { border-left-color: #ffd93d; }
    .task-row.running { border-left-color: #4dabf7; }
    .task-row.failed { border-left-color: #718096; }

    .task-name {
        color: #e8e8e8; font-weight: 600; font-size: 0.85em;
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }

    .stage-cell {
        text-align: center; padding: 4px 8px; border-radius: 6px;
        font-size: 0.75em; font-weight: 600;
    }
    .stage-done { background: #22543d; color: #68d391; }
    .stage-active { background: #2a4365; color: #63b3ed; animation: pulse 2s infinite; }
    .stage-pending { background: #1a202c; color: #4a5568; }
    .stage-failed { background: #742a2a; color: #fc8181; }
    .stage-skipped { background: #1a202c; color: #4a5568; }

    .result-cell {
        text-align: center; font-weight: 700; font-size: 0.9em;
    }
    .result-learnable { color: #00d4aa; }
    .result-hard { color: #ff6b6b; }
    .result-easy { color: #ffd93d; }
    .result-running { color: #63b3ed; }
    .result-failed { color: #718096; }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }

    .header-row {
        display: grid;
        grid-template-columns: 250px repeat(5, 1fr) 120px;
        gap: 8px; padding: 8px 15px;
        color: #8892b0; font-size: 0.75em; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.5px;
    }

    .metric-bar {
        display: inline-block; height: 24px; border-radius: 4px;
        margin-right: 4px; vertical-align: middle;
    }

    .summary-grid {
        display: grid; grid-template-columns: repeat(5, 1fr);
        gap: 12px; margin: 15px 0;
    }
    .summary-card {
        background: #16213e; border-radius: 8px; padding: 15px;
        text-align: center; border: 1px solid #1f4068;
    }
    .summary-value { font-size: 1.8em; font-weight: 700; color: #e8e8e8; }
    .summary-value.highlight { color: #00d4aa; }
    .summary-label { color: #8892b0; font-size: 0.8em; margin-top: 2px; }
</style>
"""


def _get_task_statuses(batch_dir: str) -> list[dict]:
    """Get status of every task in a batch from _status.json files and incremental."""
    tasks = []
    batch_name = os.path.basename(batch_dir)

    # Get planned topics from meta, or fall back to report results
    meta_files = glob.glob(os.path.join(batch_dir, "batch-*-meta.json"))
    planned_topics = []
    if meta_files:
        try:
            planned_topics = json.load(open(meta_files[0])).get("topics", [])
        except Exception:
            pass

    # Fall back: extract topics from report if meta was cleaned up
    if not planned_topics:
        for f in glob.glob(os.path.join(batch_dir, "batch-*-report.json")):
            try:
                data = json.load(open(f))
                planned_topics = [r.get("topic", "") for r in data.get("results", []) if r.get("topic")]
            except Exception:
                pass

    # Get completed results from incremental
    completed = {}
    for f in glob.glob(os.path.join(batch_dir, "batch-*-incremental.jsonl")):
        for line in open(f):
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    topic = r.get("topic", "")
                    completed[topic] = r
                except Exception:
                    pass

    # Get report results too
    for f in glob.glob(os.path.join(batch_dir, "batch-*-report.json")):
        try:
            data = json.load(open(f))
            for r in data.get("results", []):
                topic = r.get("topic", "")
                if topic not in completed or not completed[topic].get("classification"):
                    completed[topic] = r
        except Exception:
            pass

    # Build task list from dirs + status files
    task_dirs = {}
    for d in sorted(glob.glob(os.path.join(batch_dir, "*"))):
        if os.path.isdir(d) and not os.path.basename(d).startswith("batch-"):
            task_dirs[os.path.basename(d)] = d

    # Match topics to dirs
    for topic in planned_topics:
        # Find matching dir
        matched_dir = None
        for dirname, dirpath in task_dirs.items():
            if topic[:20].lower().replace(" ", "-").replace(",", "") in dirname:
                matched_dir = dirpath
                break

        task_info = {
            "topic": topic,
            "dir": matched_dir,
            "stage": "queued",
            "detail": "",
            "classification": None,
            "pass_rate": None,
        }

        # Check if in completed results
        if topic in completed:
            r = completed[topic]
            cl = r.get("classification")
            status = r.get("status", "")
            if cl:
                task_info["stage"] = "completed"
                task_info["classification"] = cl
                task_info["pass_rate"] = r.get("pass_rate")
                task_info["detail"] = f"{cl}"
            elif "failed" in status or "error" in status:
                task_info["stage"] = "failed"
                task_info["detail"] = status.replace("_", " ")[:30]
        elif matched_dir:
            # Read _status.json if available
            status_file = os.path.join(matched_dir, "_status.json")
            if os.path.exists(status_file):
                try:
                    s = json.load(open(status_file))
                    task_info["stage"] = s.get("stage", "generating")
                    task_info["detail"] = s.get("detail", "")
                    if s.get("classification"):
                        task_info["classification"] = s["classification"]
                        task_info["pass_rate"] = s.get("pass_rate")
                except Exception:
                    task_info["stage"] = "generating"
            else:
                # Has dir but no status — probably generating
                has_yaml = os.path.exists(os.path.join(matched_dir, "task.yaml"))
                task_info["stage"] = "generating" if not has_yaml else "structural"

        tasks.append(task_info)

    return tasks


def _render_stage_cell(current_stage: str, cell_stage: str) -> str:
    """Render a single stage cell with appropriate styling."""
    stage_idx = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else -1
    cell_idx = STAGE_ORDER.index(cell_stage) if cell_stage in STAGE_ORDER else -1

    if current_stage == "failed":
        if cell_idx <= 2:  # generating/structural/functional could have been reached
            return '<div class="stage-cell stage-failed">FAIL</div>'
        return '<div class="stage-cell stage-pending">—</div>'

    if cell_idx < stage_idx:
        return '<div class="stage-cell stage-done">✓</div>'
    elif cell_idx == stage_idx:
        icon = STAGE_ICONS.get(cell_stage, "⏳")
        return f'<div class="stage-cell stage-active">{icon}</div>'
    else:
        return '<div class="stage-cell stage-pending">—</div>'


def render_pipeline_view():
    """Single-page pipeline view."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # Find the most recent active or completed batch
    all_batches = sorted(glob.glob(os.path.join(OUTPUT_DIR, "sonnet-batch-*")))
    if not all_batches:
        st.info("No batches found. Launch one from the sidebar.")
        return

    # Sidebar: batch selector + controls
    with st.sidebar:
        st.title("🔬 Pipeline")
        batch_names = [os.path.basename(b) for b in all_batches]
        selected = st.selectbox("Batch", batch_names, index=len(batch_names) - 1)
        batch_dir = os.path.join(OUTPUT_DIR, selected)

        auto_refresh = st.checkbox("Auto-refresh (10s)")
        if auto_refresh:
            time.sleep(10)
            st.rerun()

        if st.button("Refresh"):
            st.rerun()

        st.divider()
        st.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

    # Get task statuses
    tasks = _get_task_statuses(batch_dir)
    if not tasks:
        st.info(f"No tasks found in {selected}")
        return

    # Summary metrics
    n_total = len(tasks)
    n_learnable = sum(1 for t in tasks if t["classification"] == "learnable")
    n_hard = sum(1 for t in tasks if t["classification"] == "too_hard")
    n_easy = sum(1 for t in tasks if t["classification"] == "too_easy")
    n_failed = sum(1 for t in tasks if t["stage"] == "failed")
    n_running = sum(1 for t in tasks if t["stage"] in ("generating", "structural", "functional", "evaluating"))
    n_completed = sum(1 for t in tasks if t["stage"] == "completed")

    st.markdown(f"""
    <div class="pipeline-header">
        <h2>{selected}</h2>
        <div class="subtitle">{n_completed + n_failed}/{n_total} done · {n_running} running · {n_learnable} learnable</div>
    </div>
    """, unsafe_allow_html=True)

    # Summary cards
    st.markdown(f"""
    <div class="summary-grid">
        <div class="summary-card"><div class="summary-value">{n_total}</div><div class="summary-label">Total</div></div>
        <div class="summary-card"><div class="summary-value">{n_completed + n_failed}</div><div class="summary-label">Done</div></div>
        <div class="summary-card"><div class="summary-value highlight">{n_learnable}</div><div class="summary-label">Learnable</div></div>
        <div class="summary-card"><div class="summary-value">{n_hard}</div><div class="summary-label">Too Hard</div></div>
        <div class="summary-card"><div class="summary-value">{n_failed}</div><div class="summary-label">Failed</div></div>
    </div>
    """, unsafe_allow_html=True)

    # Progress bar
    if n_total > 0:
        st.progress((n_completed + n_failed) / n_total,
                     text=f"**{n_completed + n_failed}/{n_total}** tasks processed")

    # Pipeline table header
    st.markdown("""
    <div class="header-row">
        <div>Task</div>
        <div style="text-align:center">Generate</div>
        <div style="text-align:center">Structural</div>
        <div style="text-align:center">Functional</div>
        <div style="text-align:center">Sonnet</div>
        <div style="text-align:center">Opus</div>
        <div style="text-align:center">Result</div>
    </div>
    """, unsafe_allow_html=True)

    # Task rows
    for t in tasks:
        topic = t["topic"][:35] if t["topic"] else "?"
        stage = t["stage"]
        cl = t.get("classification")
        pr = t.get("pass_rate")

        # Row class
        if cl == "learnable":
            row_class = "learnable"
        elif cl == "too_hard":
            row_class = "too-hard"
        elif cl == "too_easy":
            row_class = "too-easy"
        elif stage == "failed":
            row_class = "failed"
        elif stage in ("generating", "structural", "functional", "evaluating"):
            row_class = "running"
        else:
            row_class = ""

        # Stage cells
        gen_cell = _render_stage_cell(stage, "generating")
        struct_cell = _render_stage_cell(stage, "structural")
        func_cell = _render_stage_cell(stage, "functional")

        # Sonnet/Opus depend on skip_filters
        if stage in ("completed", "evaluating") or cl:
            sonnet_cell = '<div class="stage-cell stage-skipped">skip</div>'
            opus_cell = _render_stage_cell(stage, "evaluating")
        elif stage == "failed":
            sonnet_cell = '<div class="stage-cell stage-pending">—</div>'
            opus_cell = '<div class="stage-cell stage-pending">—</div>'
        else:
            sonnet_cell = '<div class="stage-cell stage-pending">—</div>'
            opus_cell = '<div class="stage-cell stage-pending">—</div>'

        # Result cell
        if cl == "learnable":
            pr_s = f"{pr:.0%}" if isinstance(pr, (int, float)) else ""
            result_cell = f'<div class="result-cell result-learnable">✓ {pr_s}</div>'
        elif cl == "too_hard":
            result_cell = '<div class="result-cell result-hard">TOO HARD</div>'
        elif cl == "too_easy":
            result_cell = '<div class="result-cell result-easy">TOO EASY</div>'
        elif stage == "failed":
            result_cell = f'<div class="result-cell result-failed">FAIL</div>'
        elif stage == "queued":
            result_cell = '<div class="result-cell" style="color:#4a5568">—</div>'
        else:
            result_cell = '<div class="result-cell result-running">⏳</div>'

        st.markdown(f"""
        <div class="task-row {row_class}">
            <div class="task-name" title="{t['topic']}">{topic}</div>
            {gen_cell}
            {struct_cell}
            {func_cell}
            {sonnet_cell}
            {opus_cell}
            {result_cell}
        </div>
        """, unsafe_allow_html=True)

    # Aggregate stats across all batches at bottom
    with st.expander("All-time metrics"):
        batches = _load_batch_results(OUTPUT_DIR)
        if batches:
            agg = compute_aggregate_metrics(batches)
            learnable = get_learnable_inventory(batches)
            st.write(f"**{agg.get('total_tasks', 0)}** tasks across **{agg.get('num_batches', 0)}** batches")
            st.write(f"**{agg.get('learnable', 0)}** learnable ({agg.get('learnable_yield', 0):.0%} yield)")
            st.write(f"**{len(learnable) + 3}** total learnable (including hand-crafted + Opus)")


# ── Main ──

st.set_page_config(page_title="Pipeline Dashboard", page_icon="🔬", layout="wide")
render_pipeline_view()
