"""
Pipeline Dashboard — Streamlit UI for monitoring and controlling task generation.

Run: streamlit run dashboard.py
"""

from __future__ import annotations

import json
import glob
import os
import subprocess
import sys
import time
from pathlib import Path

import streamlit as st

# Add generator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "generator"))
from metrics import _load_batch_results, compute_aggregate_metrics, compute_per_batch_metrics, get_learnable_inventory

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
EXAMPLES_DIRS = {
    "Hand-crafted": os.path.join(os.path.dirname(__file__), "examples"),
    "Opus-generated": os.path.join(os.path.dirname(__file__), "examples-opus"),
    "Sonnet-generated": os.path.join(os.path.dirname(__file__), "examples-sonnet"),
}


def load_data():
    """Load all batch data."""
    batches = _load_batch_results(OUTPUT_DIR)
    agg = compute_aggregate_metrics(batches) if batches else {}
    per_batch = compute_per_batch_metrics(batches) if batches else []
    learnable = get_learnable_inventory(batches) if batches else []
    return batches, agg, per_batch, learnable


def render_overview(agg: dict):
    """Render the overview metrics cards."""
    st.header("Pipeline Overview")

    cols = st.columns(6)
    metrics = [
        ("Tasks", agg.get("total_tasks", 0), None),
        ("Functional", agg.get("functional_pass", 0), f"{agg.get('functional_rate', 0):.0%}"),
        ("Evaluated", agg.get("evaluated", 0), None),
        ("Learnable", agg.get("learnable", 0), f"{agg.get('learnable_yield', 0):.0%} yield"),
        ("Too Easy", agg.get("too_easy", 0), None),
        ("Too Hard", agg.get("too_hard", 0), None),
    ]
    for col, (label, value, delta) in zip(cols, metrics):
        col.metric(label, value, delta)


def render_funnel(agg: dict):
    """Render the pipeline funnel."""
    st.header("Pipeline Funnel")

    steps = [
        ("Tasks Attempted", agg.get("total_tasks", 0)),
        ("Generated", agg.get("generated", 0)),
        ("Structural Pass", agg.get("structural_pass", 0)),
        ("Functional Pass", agg.get("functional_pass", 0)),
        ("Evaluated", agg.get("evaluated", 0)),
        ("Learnable", agg.get("learnable", 0)),
    ]

    max_val = max(v for _, v in steps) or 1
    for label, value in steps:
        pct = value / max_val
        col1, col2 = st.columns([1, 3])
        col1.write(f"**{label}**: {value}")
        col2.progress(pct)


def render_batch_table(per_batch: list[dict]):
    """Render per-batch breakdown."""
    st.header("Per-Batch Breakdown")

    if not per_batch:
        st.info("No batch data available.")
        return

    import pandas as pd
    df = pd.DataFrame(per_batch)
    df = df.rename(columns={
        "name": "Batch",
        "total": "Tasks",
        "functional": "Functional",
        "evaluated": "Evaluated",
        "learnable": "Learnable",
        "too_easy": "Too Easy",
        "too_hard": "Too Hard",
        "duration_min": "Time (min)",
    })
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_learnable_inventory(learnable: list[dict]):
    """Render learnable task inventory."""
    st.header(f"Learnable Tasks ({len(learnable)})")

    if not learnable:
        st.info("No learnable tasks yet.")
        return

    for t in learnable:
        col1, col2, col3 = st.columns([4, 1, 2])
        col1.write(f"**{t['topic'][:60]}**")
        col2.write(f"**{t['pass_rate']:.0%}**")
        col3.write(f"_{t['batch']}_")


def render_exemplar_browser():
    """Browse exemplar directories."""
    st.header("Exemplar Browser")

    for label, dir_path in EXAMPLES_DIRS.items():
        if not os.path.isdir(dir_path):
            continue
        tasks = [d for d in sorted(os.listdir(dir_path))
                 if os.path.isdir(os.path.join(dir_path, d)) and not d.startswith(".")]
        if tasks:
            with st.expander(f"{label} ({len(tasks)} tasks)"):
                for task in tasks:
                    task_dir = os.path.join(dir_path, task)
                    yaml_path = os.path.join(task_dir, "task.yaml")
                    bugs_path = os.path.join(task_dir, "_bugs.md")

                    st.subheader(task)

                    if os.path.exists(yaml_path):
                        with open(yaml_path) as f:
                            content = f.read()
                        # Show first few lines of instruction
                        lines = content.split("\n")
                        preview = "\n".join(lines[:8])
                        st.code(preview, language="yaml")

                    if os.path.exists(bugs_path):
                        with open(bugs_path) as f:
                            st.markdown(f.read())

                    # File inventory
                    files = [f for f in os.listdir(task_dir)
                             if not f.startswith(".") and not f.startswith("_")]
                    st.caption(f"Files: {', '.join(sorted(files))}")


def render_live_status():
    """Show currently running processes."""
    st.header("Live Status")

    # Check for running batch processes
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout.split("\n")

        batch_procs = [l for l in lines if "batch.py" in l and "grep" not in l]
        tb_procs = [l for l in lines if "tb run" in l and "grep" not in l]

        if batch_procs:
            st.success(f"{len(batch_procs)} batch process(es) running")
        else:
            st.info("No batch processes running")

        if tb_procs:
            st.write(f"**{len(tb_procs)} evaluation(s) in progress:**")
            for proc in tb_procs:
                # Extract task-id and model
                parts = proc.split()
                task_id = ""
                model = ""
                for i, p in enumerate(parts):
                    if p == "--task-id" and i + 1 < len(parts):
                        task_id = parts[i + 1][:45]
                    if p == "--model" and i + 1 < len(parts):
                        model = parts[i + 1].split("/")[-1]
                if task_id:
                    st.write(f"- `{task_id}` ({model})")

    except (subprocess.TimeoutExpired, FileNotFoundError):
        st.warning("Could not check process status")

    # Check for running batch incremental files (in-progress batches)
    incrementals = glob.glob(os.path.join(OUTPUT_DIR, "sonnet-batch-*", "batch-*-incremental.jsonl"))
    if incrementals:
        st.write("**In-progress batches:**")
        for inc in sorted(incrementals):
            batch_name = os.path.basename(os.path.dirname(inc))
            try:
                with open(inc) as f:
                    lines = [l.strip() for l in f if l.strip()]
                done = len(lines)
                # Get total from meta file
                meta = inc.replace("-incremental.jsonl", "-meta.json")
                total = "?"
                if os.path.exists(meta):
                    meta_data = json.load(open(meta))
                    total = len(meta_data.get("topics", []))
                st.write(f"- **{batch_name}**: {done}/{total} tasks completed")
            except Exception:
                st.write(f"- **{batch_name}**: reading...")


def render_launch_controls():
    """Controls to launch new batches."""
    st.header("Launch New Batch")

    with st.form("launch_batch"):
        col1, col2 = st.columns(2)
        n_tasks = col1.number_input("Number of tasks", min_value=1, max_value=20, value=6)
        n_concurrent = col2.number_input("Concurrency", min_value=1, max_value=10, value=6)

        col3, col4 = st.columns(2)
        seed = col3.number_input("Seed (0 = random)", min_value=0, max_value=9999, value=0)
        solution_first = col4.checkbox("Solution-first", value=True)

        col5, col6 = st.columns(2)
        variant = col5.selectbox("Prompt variant", ["A", "B"])
        hint_style = col6.selectbox("Hint style", ["none", "soft", "full"])

        batch_name = st.text_input("Batch name suffix (optional)", "")

        submitted = st.form_submit_button("Launch Batch")

        if submitted:
            cmd = [
                sys.executable, "generator/batch.py",
                "--n-tasks", str(n_tasks),
                "--n-concurrent", str(n_concurrent),
                "--output-dir", os.path.join(OUTPUT_DIR,
                    f"sonnet-batch-ui-{batch_name}" if batch_name else "sonnet-batch-ui"),
            ]
            if seed > 0:
                cmd.extend(["--seed", str(seed)])
            if solution_first:
                cmd.append("--solution-first")
            if variant != "A":
                cmd.extend(["--prompt-variant", variant])

            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key:
                st.error("OPENROUTER_API_KEY not set in environment")
            else:
                st.info(f"Launching: `{' '.join(cmd)}`")
                subprocess.Popen(
                    cmd,
                    env={**os.environ, "OPENROUTER_API_KEY": api_key},
                    cwd=os.path.dirname(__file__),
                )
                st.success("Batch launched! Refresh to see progress.")


# ── Main App ──

st.set_page_config(page_title="Task Generation Pipeline", layout="wide")
st.title("Task Generation Pipeline Dashboard")

# Sidebar navigation
page = st.sidebar.radio("Navigate", [
    "Overview",
    "Batch Details",
    "Learnable Tasks",
    "Exemplar Browser",
    "Live Status",
    "Launch Batch",
])

# Auto-refresh toggle
auto_refresh = st.sidebar.checkbox("Auto-refresh (30s)", value=False)
if auto_refresh:
    time.sleep(0.1)  # Prevent tight loop
    st.rerun()

# Load data
batches, agg, per_batch, learnable = load_data()

if page == "Overview":
    render_overview(agg)
    st.divider()
    render_funnel(agg)
    st.divider()
    render_batch_table(per_batch)

elif page == "Batch Details":
    render_batch_table(per_batch)

elif page == "Learnable Tasks":
    render_learnable_inventory(learnable)

elif page == "Exemplar Browser":
    render_exemplar_browser()

elif page == "Live Status":
    render_live_status()
    if st.button("Refresh"):
        st.rerun()

elif page == "Launch Batch":
    render_launch_controls()
    st.divider()
    render_live_status()
