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
from datetime import datetime
from pathlib import Path

import streamlit as st

# Add generator to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "generator"))
from metrics import (
    _load_batch_results,
    compute_aggregate_metrics,
    compute_per_batch_metrics,
    get_learnable_inventory,
)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
EXAMPLES_DIRS = {
    "Hand-crafted": os.path.join(os.path.dirname(__file__), "examples"),
    "Opus-generated": os.path.join(os.path.dirname(__file__), "examples-opus"),
    "Sonnet-generated": os.path.join(os.path.dirname(__file__), "examples-sonnet"),
}

# ── Theme / CSS ──

CUSTOM_CSS = """
<style>
    .stApp { background-color: #0e1117; }
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px;
        padding: 20px;
        text-align: center;
        border: 1px solid #1f4068;
    }
    .metric-value {
        font-size: 2.2em;
        font-weight: 700;
        color: #e8e8e8;
    }
    .metric-value-highlight {
        font-size: 2.2em;
        font-weight: 700;
        color: #00d4aa;
    }
    .metric-label {
        color: #8892b0;
        font-size: 0.85em;
        margin-top: 4px;
    }
    .task-card {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 16px;
        margin: 8px 0;
        border-left: 4px solid #00d4aa;
    }
    .task-card-hard {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 16px;
        margin: 8px 0;
        border-left: 4px solid #ff6b6b;
    }
    .task-card-easy {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 16px;
        margin: 8px 0;
        border-left: 4px solid #ffd93d;
    }
    .task-card-running {
        background: #1a1a2e;
        border-radius: 10px;
        padding: 16px;
        margin: 8px 0;
        border-left: 4px solid #4dabf7;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%, 100% { border-left-color: #4dabf7; }
        50% { border-left-color: #1a1a2e; }
    }
    .stage-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75em;
        font-weight: 600;
    }
    .badge-generating { background: #2d3748; color: #a0aec0; }
    .badge-validating { background: #2d3748; color: #63b3ed; }
    .badge-sonnet { background: #2d3748; color: #b794f4; }
    .badge-opus { background: #2d3748; color: #f6ad55; }
    .badge-learnable { background: #22543d; color: #68d391; }
    .badge-too-hard { background: #742a2a; color: #fc8181; }
    .badge-too-easy { background: #744210; color: #f6e05e; }
    .badge-failed { background: #1a202c; color: #718096; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; }
</style>
"""


def load_data():
    """Load all batch data."""
    batches = _load_batch_results(OUTPUT_DIR)
    agg = compute_aggregate_metrics(batches) if batches else {}
    per_batch = compute_per_batch_metrics(batches) if batches else []
    learnable = get_learnable_inventory(batches) if batches else []
    return batches, agg, per_batch, learnable


def _get_active_evals() -> list[dict]:
    """Get currently running tb evaluations with details."""
    evals = []
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.split("\n"):
            if "tb run" in line and "grep" not in line:
                task_id = model = ""
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "--task-id" and i + 1 < len(parts):
                        task_id = parts[i + 1]
                    if p == "--model" and i + 1 < len(parts):
                        model = parts[i + 1].split("/")[-1]
                    if p == "--n-attempts" and i + 1 < len(parts):
                        pass
                if task_id:
                    evals.append({"task_id": task_id, "model": model})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return evals


def _get_batch_progress() -> list[dict]:
    """Get in-progress batch details."""
    progress = []
    for inc in sorted(glob.glob(os.path.join(OUTPUT_DIR, "sonnet-batch-*", "batch-*-incremental.jsonl"))):
        batch_name = os.path.basename(os.path.dirname(inc))
        meta_path = inc.replace("-incremental.jsonl", "-meta.json")

        total_planned = "?"
        if os.path.exists(meta_path):
            try:
                total_planned = len(json.load(open(meta_path)).get("topics", []))
            except Exception:
                pass

        results = []
        try:
            for line in open(inc):
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass

        completed = len(results)
        learnable = sum(1 for r in results if r.get("classification") == "learnable")
        too_hard = sum(1 for r in results if r.get("classification") == "too_hard")
        too_easy = sum(1 for r in results if r.get("classification") == "too_easy")
        functional = sum(1 for r in results
                         if r.get("stages", {}).get("functional", {}).get("passed", False))
        failed = sum(1 for r in results
                     if r.get("status", "").endswith("failed") or "error" in r.get("status", ""))

        progress.append({
            "name": batch_name,
            "completed": completed,
            "total": total_planned,
            "learnable": learnable,
            "too_hard": too_hard,
            "too_easy": too_easy,
            "functional": functional,
            "failed": failed,
            "results": results,
        })
    return progress


# ── Page Renderers ──

def render_overview(agg: dict, per_batch: list, learnable: list):
    """Main overview page."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # Top metrics row
    cols = st.columns(6)
    metrics_data = [
        ("Total Tasks", agg.get("total_tasks", 0), False),
        ("Functional", agg.get("functional_pass", 0), False),
        ("Evaluated", agg.get("evaluated", 0), False),
        ("Learnable", agg.get("learnable", 0), True),
        ("Yield", f"{agg.get('learnable_yield', 0):.0%}", True),
        ("Time", f"{agg.get('total_duration_sec', 0)/60:.0f}m", False),
    ]
    for col, (label, value, highlight) in zip(cols, metrics_data):
        val_class = "metric-value-highlight" if highlight else "metric-value"
        col.markdown(f"""
        <div class="metric-card">
            <div class="{val_class}">{value}</div>
            <div class="metric-label">{label}</div>
        </div>
        """, unsafe_allow_html=True)

    st.write("")

    # Funnel
    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("Pipeline Funnel")
        steps = [
            ("Tasks Attempted", agg.get("total_tasks", 0)),
            ("Generated", agg.get("generated", 0)),
            ("Structural Pass", agg.get("structural_pass", 0)),
            ("Functional Pass", agg.get("functional_pass", 0)),
            ("Evaluated", agg.get("evaluated", 0)),
            ("Learnable", agg.get("learnable", 0)),
        ]
        max_val = max((v for _, v in steps), default=1) or 1
        for i, (label, value) in enumerate(steps):
            prev = steps[i-1][1] if i > 0 else value
            drop = f"({value}/{prev})" if i > 0 and prev > 0 else ""
            st.progress(value / max_val, text=f"{label}: **{value}** {drop}")

    with col_right:
        st.subheader("Classification")
        evaluated = agg.get("evaluated", 0)
        if evaluated > 0:
            import pandas as pd
            chart_data = pd.DataFrame({
                "Classification": ["Learnable", "Too Hard", "Too Easy"],
                "Count": [
                    agg.get("learnable", 0),
                    agg.get("too_hard", 0),
                    agg.get("too_easy", 0),
                ],
            })
            st.bar_chart(chart_data.set_index("Classification"))
        else:
            st.info("No evaluated tasks yet")

    # Batch table
    st.subheader("Batch History")
    if per_batch:
        import pandas as pd
        df = pd.DataFrame(per_batch)
        df = df.rename(columns={
            "name": "Batch", "total": "Tasks", "functional": "Func",
            "evaluated": "Eval", "learnable": "Learn",
            "too_easy": "Easy", "too_hard": "Hard", "duration_min": "Min",
        })

        def highlight_learnable(val):
            if isinstance(val, (int, float)) and val > 0:
                return "color: #00d4aa; font-weight: bold"
            return ""

        styled = df.style.applymap(highlight_learnable, subset=["Learn"])
        st.dataframe(styled, use_container_width=True, hide_index=True)


def render_live_status():
    """Live monitoring page with progress bars and task status."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.header("Live Pipeline Status")

    # Active evaluations
    active_evals = _get_active_evals()
    batch_progress = _get_batch_progress()

    if not active_evals and not batch_progress:
        st.info("No active runs. Use the **Launch Batch** page to start one.")
        return

    # Separate active (incremental file exists, no report) from completed (report exists)
    active_batches = []
    completed_batches = []
    for bp in batch_progress:
        report = glob.glob(os.path.join(OUTPUT_DIR, bp["name"], "batch-*-report.json"))
        if report:
            completed_batches.append(bp)
        else:
            active_batches.append(bp)

    # ── Active batches (top, prominent) ──
    if active_batches:
        for bp in active_batches:
            total = bp["total"] if isinstance(bp["total"], int) else 6
            completed = bp["completed"]
            pct = completed / total if total > 0 else 0

            st.subheader(f"🔄 {bp['name']}")
            st.progress(pct, text=f"**{completed}/{total}** tasks completed")

            # Result summary so far
            cols = st.columns(5)
            cols[0].metric("Functional", bp["functional"])
            cols[1].metric("Learnable", bp["learnable"])
            cols[2].metric("Too Hard", bp["too_hard"])
            cols[3].metric("Too Easy", bp["too_easy"])
            cols[4].metric("Failed", bp["failed"])

            # Per-task cards — completed results
            for r in bp["results"]:
                topic = r.get("topic", "?")[:55]
                status = r.get("status", "?")
                cl = r.get("classification")
                pr = r.get("pass_rate")

                if cl == "learnable":
                    card_class = "task-card"
                    badge = f'<span class="stage-badge badge-learnable">LEARNABLE {pr:.0%}</span>'
                elif cl == "too_hard":
                    card_class = "task-card-hard"
                    badge = '<span class="stage-badge badge-too-hard">TOO HARD</span>'
                elif cl == "too_easy":
                    card_class = "task-card-easy"
                    badge = '<span class="stage-badge badge-too-easy">TOO EASY</span>'
                elif "failed" in status or "error" in status:
                    card_class = "task-card-hard"
                    badge_text = status.replace("_", " ").title()[:25]
                    badge = f'<span class="stage-badge badge-failed">{badge_text}</span>'
                else:
                    card_class = "task-card-running"
                    badge = '<span class="stage-badge badge-generating">IN PROGRESS</span>'

                st.markdown(f"""
                <div class="{card_class}">
                    <strong>{topic}</strong><br>
                    {badge}
                </div>
                """, unsafe_allow_html=True)

            # Pending/queued tasks
            if isinstance(bp["total"], int) and completed < bp["total"]:
                remaining = bp["total"] - completed
                for _ in range(remaining):
                    st.markdown("""
                    <div class="task-card-running">
                        <strong>Pending...</strong><br>
                        <span class="stage-badge badge-generating">QUEUED</span>
                    </div>
                    """, unsafe_allow_html=True)

            st.divider()
    else:
        st.info("No batches currently running.")

    # ── Completed batches (collapsed) ──
    if completed_batches:
        with st.expander(f"Completed batches ({len(completed_batches)})"):
            for bp in completed_batches:
                total = bp["total"] if isinstance(bp["total"], int) else len(bp["results"])
                st.write(
                    f"**{bp['name']}** — {total} tasks | "
                    f"{bp['learnable']} learnable | "
                    f"{bp['too_hard']} hard | "
                    f"{bp['too_easy']} easy | "
                    f"{bp['failed']} failed"
                )

    # Active evaluations (from tb run processes)
    if active_evals:
        st.subheader("Active Evaluations")
        for ev in active_evals:
            model = ev["model"]
            task = ev["task_id"][:45]

            if "opus" in model:
                badge = '<span class="stage-badge badge-opus">OPUS EVAL</span>'
            elif "sonnet" in model:
                badge = '<span class="stage-badge badge-sonnet">SONNET FILTER</span>'
            else:
                badge = f'<span class="stage-badge badge-generating">{model}</span>'

            # Find trial pass rate from two sources:
            # 1. Run dirs (may be cleaned up)
            # 2. Pipeline's internal eval stage in incremental results
            trials_passed = 0
            trials_total = 0

            # Source 1: run dirs (live, may be partial)
            run_dirs = glob.glob(f"runs/*{ev['task_id']}*{model.replace('claude-', '')}*")
            for rd in sorted(run_dirs):
                rf = os.path.join(rd, "results.json")
                if os.path.exists(rf):
                    try:
                        data = json.load(open(rf))
                        for r in data.get("results", []):
                            resolved = r.get("is_resolved")
                            if resolved is not None:
                                trials_total += 1
                                if resolved:
                                    trials_passed += 1
                    except Exception:
                        pass

            # Source 2: check eval stages in all active batch incrementals
            # (captures data from cleaned-up runs)
            if trials_total == 0:
                for inc in glob.glob(os.path.join(OUTPUT_DIR, "sonnet-batch-*", "batch-*-incremental.jsonl")):
                    try:
                        for line in open(inc):
                            line = line.strip()
                            if not line:
                                continue
                            r = json.loads(line)
                            # Match by task_id in the task_dir path
                            task_dir = r.get("task_dir", "")
                            if ev["task_id"] not in task_dir:
                                continue
                            eval_data = r.get("stages", {}).get("evaluation", {})
                            opus_data = eval_data.get("tier_results", {}).get("opus", {})
                            if opus_data:
                                trials_passed = opus_data.get("passes", 0) or 0
                                trials_total = opus_data.get("total", 0) or 0
                            elif eval_data.get("passes") is not None:
                                trials_passed = eval_data.get("passes", 0) or 0
                                trials_total = eval_data.get("total", 0) or 0
                    except Exception:
                        pass

            trial_info = ""
            if trials_total > 0:
                trial_info = f" | Trials: **{trials_passed}/{trials_total}** passed"
                if trials_passed > 0:
                    trial_info += " ✓"

            st.markdown(f"""
            <div class="task-card-running">
                <strong>{task}</strong> {badge}{trial_info}
            </div>
            """, unsafe_allow_html=True)

    # Refresh button
    col1, col2 = st.columns([1, 5])
    if col1.button("Refresh Now"):
        st.rerun()


def render_learnable_inventory(learnable: list[dict]):
    """Learnable task inventory."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.header(f"Learnable Tasks ({len(learnable)})")

    if not learnable:
        st.info("No learnable tasks found yet. Run more batches!")
        return

    for t in learnable:
        rate = t.get("pass_rate", 0)
        topic = t.get("topic", "?")[:60]
        batch = t.get("batch", "?")

        st.markdown(f"""
        <div class="task-card">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong>{topic}</strong><br>
                    <span style="color: #8892b0; font-size: 0.85em;">{batch} | {t.get('retries', 0)} retries</span>
                </div>
                <div class="metric-value-highlight" style="font-size: 1.8em;">{rate:.0%}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)


def render_exemplar_browser():
    """Browse exemplar directories."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.header("Exemplar Browser")

    for label, dir_path in EXAMPLES_DIRS.items():
        if not os.path.isdir(dir_path):
            continue
        tasks = [d for d in sorted(os.listdir(dir_path))
                 if os.path.isdir(os.path.join(dir_path, d)) and not d.startswith(".")]
        if not tasks:
            continue

        st.subheader(f"{label} ({len(tasks)})")
        for task in tasks:
            task_dir = os.path.join(dir_path, task)
            bugs_path = os.path.join(task_dir, "_bugs.md")

            with st.expander(task):
                # File list
                files = sorted(f for f in os.listdir(task_dir)
                                if not f.startswith(".") and not f.startswith("_"))
                st.caption(f"Files: {', '.join(files)}")

                # Task instruction
                yaml_path = os.path.join(task_dir, "task.yaml")
                if os.path.exists(yaml_path):
                    with open(yaml_path) as f:
                        lines = f.read().split("\n")
                    st.code("\n".join(lines[:12]), language="yaml")

                # Bug annotations
                if os.path.exists(bugs_path):
                    with open(bugs_path) as f:
                        st.markdown(f.read())


def render_launch_controls():
    """Controls to launch new batches."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.header("Launch New Batch")

    with st.form("launch_batch"):
        col1, col2, col3 = st.columns(3)
        n_tasks = col1.number_input("Tasks", min_value=1, max_value=20, value=6)
        n_concurrent = col2.number_input("Concurrency", min_value=1, max_value=10, value=6)
        seed = col3.number_input("Seed (0=random)", min_value=0, max_value=9999, value=0)

        col4, col5, col6 = st.columns(3)
        solution_first = col4.checkbox("Solution-first", value=True)
        variant = col5.selectbox("Prompt variant", ["A", "B"])
        hint_style = col6.selectbox("Hint style", ["none", "soft", "full"])

        batch_name = st.text_input("Batch name", f"batch-{int(time.time())}")

        submitted = st.form_submit_button("Launch Batch", type="primary")

        if submitted:
            cmd = [
                sys.executable, "generator/batch.py",
                "--n-tasks", str(n_tasks),
                "--n-concurrent", str(n_concurrent),
                "--solution-first" if solution_first else "",
                "--output-dir", os.path.join(OUTPUT_DIR, f"sonnet-{batch_name}"),
            ]
            cmd = [c for c in cmd if c]  # remove empty strings
            if seed > 0:
                cmd.extend(["--seed", str(seed)])
            if variant != "A":
                cmd.extend(["--prompt-variant", variant])

            api_key = os.environ.get("OPENROUTER_API_KEY", "")
            if not api_key:
                st.error("Set OPENROUTER_API_KEY environment variable before launching.")
            else:
                st.code(" ".join(cmd), language="bash")
                subprocess.Popen(
                    cmd,
                    env={**os.environ, "OPENROUTER_API_KEY": api_key},
                    cwd=os.path.dirname(__file__),
                )
                st.success("Batch launched! Switch to **Live Status** to monitor.")


# ── Main App ──

st.set_page_config(
    page_title="Task Pipeline",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Sidebar
with st.sidebar:
    st.title("🔬 Task Pipeline")
    st.caption("Generate learnable coding tasks")
    st.divider()

    page = st.radio("", [
        "📊 Overview",
        "🔴 Live Status",
        "✅ Learnable Tasks",
        "📁 Exemplar Browser",
        "🚀 Launch Batch",
    ], label_visibility="collapsed")

    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (15s)")
    if auto_refresh:
        st.caption("Refreshing...")
        time.sleep(15)
        st.rerun()

    st.divider()
    st.caption(f"Last loaded: {datetime.now().strftime('%H:%M:%S')}")

# Load data
batches, agg, per_batch, learnable = load_data()

# Route to page
if "Overview" in page:
    render_overview(agg, per_batch, learnable)
elif "Live" in page:
    render_live_status()
elif "Learnable" in page:
    render_learnable_inventory(learnable)
elif "Exemplar" in page:
    render_exemplar_browser()
elif "Launch" in page:
    render_launch_controls()
