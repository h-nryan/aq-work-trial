"""
Pipeline Dashboard — Single-page real-time view of task generation pipeline.

Run: streamlit run dashboard.py
"""

from __future__ import annotations

import json
import glob
import os
import re
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
RUNS_DIR = os.path.join(os.path.dirname(__file__), "runs")

# ── Model pricing ($ per token) ──────────────────────────────────────────────
_SONNET_IN  = 3.00  / 1_000_000
_SONNET_OUT = 15.00 / 1_000_000
_OPUS_IN    = 15.00 / 1_000_000
_OPUS_OUT   = 75.00 / 1_000_000


def _task_cost(stages: dict) -> tuple[float, float]:
    """Return (gen_cost_$, opus_cost_$) from a task's stages dict."""
    gen_cost = 0.0
    for key, data in stages.items():
        if key in ("generate", "regenerate") or key.startswith("retry_") or key.startswith("difficulty_adj_"):
            u = data.get("usage", {})
            gen_cost += u.get("prompt_tokens", 0) * _SONNET_IN
            gen_cost += u.get("completion_tokens", 0) * _SONNET_OUT

    opus_cost = 0.0
    opus_tier = stages.get("evaluation", {}).get("tier_results", {}).get("opus", {})
    for batch in opus_tier.get("trials", []):
        for trial in batch.get("trials", []):
            opus_cost += (trial.get("input_tokens") or 0) * _OPUS_IN
            opus_cost += (trial.get("output_tokens") or 0) * _OPUS_OUT

    return gen_cost, opus_cost


def _fmt_cost(dollars: float) -> str:
    if dollars == 0:
        return "—"
    if dollars < 0.01:
        return f"<$0.01"
    return f"${dollars:.2f}"


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
        grid-template-columns: 250px repeat(5, 1fr) 70px 120px;
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
        min-width: 40px;
    }
    .stage-done { background: #22543d; color: #68d391; }
    .stage-active { background: #2a4365; color: #63b3ed; animation: pulse 2s infinite; }
    .stage-adjusting { background: #744210; color: #ffd93d; animation: pulse 2s infinite; }
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
        grid-template-columns: 250px repeat(5, 1fr) 70px 120px;
        gap: 8px; padding: 8px 15px;
        color: #8892b0; font-size: 0.75em; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.5px;
    }

    .metric-bar {
        display: inline-block; height: 24px; border-radius: 4px;
        margin-right: 4px; vertical-align: middle;
    }

    .summary-grid {
        display: grid; grid-template-columns: repeat(6, 1fr);
        gap: 12px; margin: 15px 0;
    }
    .summary-card {
        background: #16213e; border-radius: 8px; padding: 15px;
        text-align: center; border: 1px solid #1f4068;
    }
    .summary-value { font-size: 1.8em; font-weight: 700; color: #e8e8e8; }
    .summary-value.highlight { color: #00d4aa; }
    .summary-value.cost { color: #ffd93d; }
    .summary-label { color: #8892b0; font-size: 0.8em; margin-top: 2px; }

    .cost-grid {
        display: grid; grid-template-columns: repeat(3, 1fr);
        gap: 12px; margin: 10px 0 15px 0;
    }


    /* Make detail expanders flush with the task row above */
    .task-row + div .streamlit-expanderHeader {
        font-size: 0.7em;
        color: #4a5568;
        padding: 2px 15px;
        min-height: unset;
    }
    div[data-testid="stExpander"] {
        margin-top: -8px;
        margin-bottom: 4px;
    }
</style>
"""


def _render_eval_tier_cell(
    tier: str,
    tier_results: dict,
    eval_tiers: dict,
    filtered_at: str | None,
    is_adjusting: bool,
    stage: str,
    classification: str | None,
    task_dirname: str,
    batch_start_ts: int,
    adj_trigger: str | None = None,
) -> str:
    """Render a Sonnet or Opus eval cell.

    Step 1: Resolve scores from available data sources.
    Step 2: Determine the cell's display state.
    Step 3: Render.
    """
    # ── Step 1: Resolve scores ──
    # Priority: JSONL tier_results → _status.json eval_tiers → live runs/
    passes, total = None, None
    td = tier_results.get(tier, {})
    if td:
        passes, total = td.get("passes"), td.get("total")
    if passes is None:
        st = eval_tiers.get(tier, {})
        if st:
            passes, total = st.get("passes", 0), st.get("total", 0)
    if passes is None and stage == "evaluating":
        model_glob = "claude-sonnet*" if tier == "sonnet" else "claude-opus*"
        passes, total, has_active = _get_live_eval_scores(task_dirname, model_glob, batch_start_ts)
        if total == 0:
            passes, total = None, None  # no real data

    has_scores = passes is not None and total

    # ── Step 2: Determine display state ──
    was_filtered = (filtered_at == tier) or eval_tiers.get(tier, {}).get("filtered", False)
    opus_skipped_by_filter = (
        tier == "opus"
        and filtered_at in ("sonnet", "haiku")
        and not is_adjusting
    )
    opus_has_data = bool(eval_tiers.get("opus", {}).get("total") or tier_results.get("opus", {}).get("total"))
    is_latest_tier = (tier == "opus") or (tier == "sonnet" and not opus_has_data)

    # Determine state
    if opus_skipped_by_filter and stage == "completed":
        state = "skipped_filtered"
    elif is_adjusting and is_latest_tier and has_scores:
        state = "adjusting"
    elif has_scores and stage == "completed":
        if was_filtered or (classification in ("too_hard", "too_easy") and tier == "opus"):
            state = "done_bad"
        else:
            state = "done_good"
    elif has_scores and stage == "evaluating":
        state = "in_progress"
    elif stage == "evaluating":
        # No scores — check if a run dir exists
        model_glob = "claude-sonnet*" if tier == "sonnet" else "claude-opus*"
        _, _, has_active = _get_live_eval_scores(task_dirname, model_glob, batch_start_ts)
        state = "running" if has_active else "not_reached"
    else:
        state = "not_reached"

    # ── Step 3: Render ──
    cells = {
        "skipped_filtered": lambda: (
            f'<div class="stage-cell stage-skipped">'
            f'skip (too {"easy" if classification == "too_easy" else "hard"})</div>'
        ),
        "adjusting": lambda: (
            f'<div class="stage-cell stage-adjusting">'
            f'too {"easy" if (was_filtered or classification == "too_easy" or adj_trigger == "too_easy") else "hard"}'
            f' ({passes}/{total}): adjusting</div>'
        ),
        "done_good": lambda: f'<div class="stage-cell stage-done">{passes}/{total}</div>',
        "done_bad": lambda: f'<div class="stage-cell stage-failed">{passes}/{total}</div>',
        "in_progress": lambda: f'<div class="stage-cell stage-active">{passes}/{total}</div>',
        "running": lambda: '<div class="stage-cell stage-active">...</div>',
        "not_reached": lambda: '<div class="stage-cell stage-pending">—</div>',
    }
    return cells[state]()


def _get_batch_start_ts(batch_dir: str) -> int:
    """Get batch start as unix timestamp from meta file."""
    for f in glob.glob(os.path.join(batch_dir, "batch-*-meta.json")):
        try:
            batch_id = json.load(open(f)).get("batch_id", "")
            dt = datetime.strptime(batch_id, "%Y%m%d-%H%M%S")
            return int(dt.timestamp())
        except Exception:
            pass
    return 0


def _get_live_eval_scores(task_dirname: str, model_substr: str, batch_start_ts: int) -> tuple[int, int, bool]:
    """Get live pass/total from runs/ dir for a specific model, filtered to current batch.

    Only counts runs whose timestamp suffix is >= batch_start_ts.
    Returns (passes, total, has_active_run).
    """
    passes, total = 0, 0
    has_active_run = False
    for run_dir in glob.glob(os.path.join(RUNS_DIR, f"eval-{task_dirname}-{model_substr}-*")):
        # Extract timestamp from run dir name (last segment after final -)
        try:
            ts = int(os.path.basename(run_dir).rsplit("-", 1)[-1])
        except (ValueError, IndexError):
            continue
        if ts < batch_start_ts:
            continue  # Stale run from previous batch
        has_active_run = True
        results_file = os.path.join(run_dir, "results.json")
        if os.path.exists(results_file):
            try:
                rdata = json.load(open(results_file))
                for trial in rdata.get("results", []):
                    total += 1
                    if trial.get("is_resolved"):
                        passes += 1
            except Exception:
                pass
    return passes, total, has_active_run


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
            slug = re.sub(r"[^a-z0-9-]", "", topic[:30].lower().replace(" ", "-"))
            if slug in dirname:
                matched_dir = dirpath
                break

        task_info = {
            "topic": topic,
            "dir": matched_dir,
            "stage": "queued",
            "detail": "",
            "classification": None,
            "pass_rate": None,
            "duration_sec": None,
            "failed_stage": "",
        }

        # Check if in completed results
        if topic in completed:
            r = completed[topic]
            cl = r.get("classification")
            status = r.get("status", "")
            task_info["duration_sec"] = r.get("duration_sec")
            task_info["failed_stage"] = r.get("failed_stage", "")
            # Infer failed_stage from status if not explicitly set
            if not task_info["failed_stage"] and "functional" in status:
                task_info["failed_stage"] = "functional"
            elif not task_info["failed_stage"] and "structural" in status:
                task_info["failed_stage"] = "structural"
            elif not task_info["failed_stage"] and ("generation" in status or "retry_generation" in status):
                task_info["failed_stage"] = "generation"

            # Preserve full stages data for detail view
            task_info["stages"] = r.get("stages", {})

            if cl:
                task_info["stage"] = "completed"
                task_info["classification"] = cl
                task_info["pass_rate"] = r.get("pass_rate")
                task_info["detail"] = f"{cl}"
            elif status == "completed" and not cl:
                # Skip-eval tasks: passed functional validation, no Opus classification
                task_info["stage"] = "completed"
                task_info["classification"] = "eval_skipped"
                task_info["detail"] = "functional ✓ (eval skipped)"
            elif "failed" in status or "error" in status:
                task_info["stage"] = "failed"
                task_info["detail"] = status.replace("_", " ")[:30]

            # Override classification from _status.json — post-adjustment tasks have
            # stale JSONL data (the pre-adjustment eval result). _status.json always
            # reflects the final outcome.
            if matched_dir:
                _sf = os.path.join(matched_dir, "_status.json")
                if os.path.exists(_sf):
                    try:
                        _s = json.load(open(_sf))
                        if _s.get("classification"):
                            task_info["classification"] = _s["classification"]
                            task_info["pass_rate"] = _s.get("pass_rate")
                            task_info["detail"] = _s["classification"]
                    except Exception:
                        pass
                # Correct opus passes/total from _meta.yaml (authoritative after adjustment).
                # Only update passes/total — preserve existing trials data for cost calc.
                _mp = os.path.join(matched_dir, "_meta.yaml")
                if os.path.exists(_mp):
                    try:
                        import yaml as _yaml
                        _m = _yaml.safe_load(open(_mp))
                        if _m and _m.get("opus_passes") is not None and _m.get("opus_total"):
                            eval_section = task_info.setdefault("stages", {}).setdefault("evaluation", {})
                            tr = eval_section.setdefault("tier_results", {})
                            opus_entry = dict(tr.get("opus") or {})
                            opus_entry["passes"] = _m["opus_passes"]
                            opus_entry["total"] = _m["opus_total"]
                            tr["opus"] = opus_entry
                    except Exception:
                        pass

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
                    if s.get("category"):
                        task_info["category"] = s["category"]
                except Exception:
                    task_info["stage"] = "generating"
            else:
                # Has dir but no status — probably generating
                has_yaml = os.path.exists(os.path.join(matched_dir, "task.yaml"))
                task_info["stage"] = "generating" if not has_yaml else "structural"

            # Read the latest _adj_snapshot.json to know WHY we're currently adjusting
            # (e.g. round 2 triggers on "too_easy" even though live score may be 0)
            pre_adj_dirs = sorted(glob.glob(matched_dir + ".pre_adj*"))
            if pre_adj_dirs:
                snap_path = os.path.join(pre_adj_dirs[-1], "_adj_snapshot.json")
                if os.path.exists(snap_path):
                    try:
                        snap = json.load(open(snap_path))
                        task_info["adj_trigger"] = snap.get("pre_adjustment_classification")
                    except Exception:
                        pass

        # Category: _meta.yaml is authoritative for completed tasks; _status.json for in-progress
        if matched_dir and "category" not in task_info:
            meta_path = os.path.join(matched_dir, "_meta.yaml")
            if os.path.exists(meta_path):
                try:
                    import yaml as _yaml
                    m = _yaml.safe_load(open(meta_path))
                    if m and m.get("category"):
                        task_info["category"] = m["category"]
                except Exception:
                    pass

        tasks.append(task_info)

    return tasks


def _render_stage_cell(current_stage: str, cell_stage: str, failed_stage: str = "") -> str:
    """Render a single stage cell with appropriate styling.

    failed_stage indicates WHICH stage actually failed — prior stages passed.
    """
    stage_idx = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else -1
    cell_idx = STAGE_ORDER.index(cell_stage) if cell_stage in STAGE_ORDER else -1

    if current_stage == "failed" and failed_stage:
        # Map failed_stage string to a stage index
        fail_map = {
            "generation": 0, "generating": 0,
            "structural": 1,
            "functional": 2,
            "evaluating": 3, "evaluation": 3,
        }
        fail_idx = fail_map.get(failed_stage, -1)

        if cell_idx < fail_idx:
            # Stages before the failure passed
            return '<div class="stage-cell stage-done">✓</div>'
        elif cell_idx == fail_idx:
            return '<div class="stage-cell stage-failed">FAIL</div>'
        else:
            return '<div class="stage-cell stage-pending">—</div>'
    elif current_stage == "failed":
        # No failed_stage info — show ambiguous
        if cell_idx <= 2:
            return '<div class="stage-cell stage-failed">?</div>'
        return '<div class="stage-cell stage-pending">—</div>'

    if cell_idx < stage_idx:
        return '<div class="stage-cell stage-done">✓</div>'
    elif cell_idx == stage_idx:
        icon = STAGE_ICONS.get(cell_stage, "⏳")
        return f'<div class="stage-cell stage-active">{icon}</div>'
    else:
        return '<div class="stage-cell stage-pending">—</div>'


def _render_task_details(task_dir: str, task_info: dict):
    """Render detailed task information inside an expander."""
    dirname = os.path.basename(task_dir)

    # --- Stage timeline with durations ---
    st.markdown("**Stage Timeline**")
    timeline_parts = []

    # Generation info
    status_file = os.path.join(task_dir, "_status.json")
    if os.path.exists(status_file):
        try:
            status = json.load(open(status_file))
            stage = status.get("stage", "?")
            detail = status.get("detail", "")
            updated = status.get("updated_at", "")
            timeline_parts.append(f"Current: **{stage}** — {detail}")
            if updated:
                timeline_parts.append(f"Last updated: `{updated}`")
        except Exception:
            pass

    # Validation attempts
    val_files = sorted(glob.glob(os.path.join(task_dir, "validation_attempt_*.json")))
    if val_files:
        st.markdown(f"**Functional Validation** ({len(val_files)} attempt{'s' if len(val_files) != 1 else ''})")
        for vf in val_files:
            try:
                v = json.load(open(vf))
                attempt = v.get("attempt", "?")
                passed = v.get("passed", False)
                issues = v.get("issues", [])
                times = v.get("execution_times", {})

                status_icon = "✅" if passed else "❌"
                time_parts = []
                for phase, secs in times.items():
                    if isinstance(secs, (int, float)):
                        time_parts.append(f"{phase}: {secs:.1f}s")
                time_str = " | ".join(time_parts) if time_parts else ""

                st.markdown(f"Attempt {attempt} {status_icon} {time_str}")
                if issues and not passed:
                    for issue in issues[:3]:
                        st.markdown(f"  - `{issue[:120]}`")

                # Show test output excerpt on failure
                if not passed:
                    details = v.get("details", {})
                    for phase in ("without_solution", "with_solution"):
                        pd = details.get(phase, {})
                        stdout = pd.get("stdout_tail", "")
                        if stdout and len(stdout) > 20:
                            with st.expander(f"  {phase} output"):
                                st.code(stdout[-800:], language="text")
            except Exception:
                pass

    # Eval results — skip entirely for eval_skipped tasks
    if task_info.get("classification") == "eval_skipped":
        eval_data = {}
    else:
        stages = task_info.get("stages", {})
        eval_data = stages.get("evaluation", {})
    opus_tier = eval_data.get("tier_results", {}).get("opus", {})
    opus_trials = opus_tier.get("trials", [])

    # Flatten: each "trial batch" from run_opus_eval has a sub-list of trials
    all_trials = []
    for batch in opus_trials:
        if isinstance(batch, dict):
            sub = batch.get("trials", [])
            if sub:
                all_trials.extend(sub)
            # Do NOT append batch-level dicts as trials — different schema.

    # Only show eval block when at least one real trial completed
    has_real_eval = bool(all_trials) or (eval_data.get("total") or 0) > 0
    if has_real_eval:
        passes = opus_tier.get("passes", eval_data.get("passes", 0))
        total = opus_tier.get("total", eval_data.get("total", 0))
        early = opus_tier.get("early_stopped", False)
        detail_parts = []
        if early:
            detail_parts.append("early stop")
        if all_trials:
            detail_parts.append(f"{len(all_trials)} trial{'s' if len(all_trials) != 1 else ''}")
        detail_str = f" ({', '.join(detail_parts)})" if detail_parts else ""
        st.markdown(f"**Opus Evaluation**: **{passes}/{total}**{detail_str}"
        )

        for trial in all_trials:
            resolved = trial.get("resolved", trial.get("is_resolved", False))
            tp = trial.get("tests_passed", 0)
            tt = trial.get("tests_total", 0)

            # Also check parser_results if available (from runs/ fallback)
            pr = trial.get("parser_results") or {}
            if pr and not tp:
                tp = sum(1 for v in pr.values() if v == "passed")
                tt = len(pr)

            fm = trial.get("failure_mode", "")
            icon = "✅" if resolved else "❌"

            # Agent timing
            agent_start = trial.get("agent_started_at", "")
            agent_end = trial.get("agent_ended_at", "")
            agent_dur = ""
            if agent_start and agent_end:
                try:
                    t0 = datetime.fromisoformat(agent_start.replace("+00:00", ""))
                    t1 = datetime.fromisoformat(agent_end.replace("+00:00", ""))
                    secs = (t1 - t0).total_seconds()
                    agent_dur = f" ({secs:.0f}s)"
                except Exception:
                    pass

            # Token usage
            in_tok = trial.get("input_tokens", trial.get("total_input_tokens"))
            out_tok = trial.get("output_tokens", trial.get("total_output_tokens"))
            tok_str = ""
            if in_tok or out_tok:
                tok_str = f" | {(in_tok or 0) + (out_tok or 0):,} tokens"

            st.markdown(
                f"  {icon} Tests: **{tp}/{tt}**{agent_dur}{tok_str}"
                + (f" — {fm}" if fm and not resolved else "")
            )

            # Show per-test results if available
            if pr and tt > 0:
                test_lines = []
                for tname, tresult in sorted(pr.items()):
                    t_icon = "✅" if tresult == "passed" else "❌"
                    test_lines.append(f"  {t_icon} {tname}")
                with st.expander(f"  Per-test results ({tp}/{tt})"):
                    st.text("\n".join(test_lines))

    # Adjustment snapshots
    adj_dirs = sorted(glob.glob(task_dir + ".pre_adj*"))
    if adj_dirs:
        st.markdown(f"**Difficulty Adjustments** ({len(adj_dirs)} round{'s' if len(adj_dirs) != 1 else ''})")
        for adj_dir in adj_dirs:
            snap_file = os.path.join(adj_dir, "_adj_snapshot.json")
            if os.path.exists(snap_file):
                try:
                    snap = json.load(open(snap_file))
                    rd = snap.get("adjustment_round", "?")
                    trigger = snap.get("trigger", "?")
                    st.markdown(f"Round {rd}: {trigger}")
                except Exception:
                    pass

        # Show adjustment response if available
        adj_response = os.path.join(task_dir, "_adjust_raw_response.txt")
        if os.path.exists(adj_response):
            with st.expander("Adjustment response"):
                try:
                    st.code(open(adj_response).read()[:2000], language="json")
                except Exception:
                    pass

    # Cost breakdown
    stages = task_info.get("stages", {})
    gc, oc = _task_cost(stages)
    if gc > 0 or oc > 0:
        st.markdown("**Cost Breakdown**")
        gen_tok = sum(
            s.get("usage", {}).get("total_tokens", 0)
            for k, s in stages.items()
            if k in ("generate", "regenerate") or k.startswith("retry_") or k.startswith("difficulty_adj_")
        )
        opus_trials_flat = [
            trial
            for batch in stages.get("evaluation", {}).get("tier_results", {}).get("opus", {}).get("trials", [])
            for trial in batch.get("trials", [])
        ]
        opus_tok = sum((t.get("input_tokens") or 0) + (t.get("output_tokens") or 0) for t in opus_trials_flat)
        rows = []
        if gc > 0:
            rows.append(f"| Generation | {_fmt_cost(gc)} | {gen_tok:,} tok |")
        if oc > 0:
            rows.append(f"| Opus eval | {_fmt_cost(oc)} | {opus_tok:,} tok |")
        rows.append(f"| **Total** | **{_fmt_cost(gc + oc)}** | |")
        st.markdown("| | Cost | Tokens |\n|---|---|---|\n" + "\n".join(rows))

    # Task files summary
    st.markdown("**Task Files**")
    files = [f for f in os.listdir(task_dir)
             if not f.startswith("_") and not f.startswith("validation_")]
    st.text(", ".join(sorted(files)) if files else "No files")


def _render_stage_dots(current_stage: str, failed_stage: str = "") -> str:
    """Render compact stage progress as text dots for expander labels."""
    stages = ["generating", "structural", "functional", "evaluating"]
    stage_idx = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else -1
    dots = []
    for i, s in enumerate(stages):
        s_idx = STAGE_ORDER.index(s) if s in STAGE_ORDER else -1
        if current_stage == "failed" and failed_stage:
            fail_map = {"generation": 0, "generating": 0, "structural": 1, "functional": 2, "evaluating": 3, "evaluation": 3}
            fail_idx = fail_map.get(failed_stage, -1)
            if i < fail_idx:
                dots.append("●")
            elif i == fail_idx:
                dots.append("✗")
            else:
                dots.append("○")
        elif s_idx < stage_idx:
            dots.append("●")
        elif s_idx == stage_idx:
            dots.append("◉")
        else:
            dots.append("○")
    return "".join(dots)


def render_pipeline_view():
    """Single-page pipeline view."""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # Find the most recent active or completed batch
    all_batches = sorted(glob.glob(os.path.join(OUTPUT_DIR, "sonnet-batch-*")),
                         key=lambda p: os.path.getmtime(p))
    if not all_batches:
        st.info("No batches found. Launch one from the sidebar.")
        return

    # Sidebar: batch selector + controls
    with st.sidebar:
        st.title("🔬 Pipeline")
        batch_names = [os.path.basename(b) for b in all_batches]
        selected = st.selectbox("Batch", batch_names, index=len(batch_names) - 1)
        batch_dir = os.path.join(OUTPUT_DIR, selected)

        if st.button("Refresh"):
            st.rerun()

        auto_refresh = st.checkbox("Auto-refresh (10s)")
        if auto_refresh:
            time.sleep(10)
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

    # Batch wall clock time (from report), not sum of individual durations
    batch_wall_time = None
    for f in glob.glob(os.path.join(batch_dir, "batch-*-report.json")):
        try:
            data = json.load(open(f))
            batch_wall_time = data.get("metrics", {}).get("total_duration_sec")
        except Exception:
            pass

    if batch_wall_time and batch_wall_time >= 60:
        duration_str = f"{batch_wall_time/60:.0f}m wall"
    elif batch_wall_time:
        duration_str = f"{batch_wall_time:.0f}s wall"
    else:
        # Fallback for running batches: show sum of completed tasks
        total_duration = sum(t.get("duration_sec") or 0 for t in tasks)
        if total_duration >= 60:
            duration_str = f"~{total_duration/60:.0f}m cumulative"
        elif total_duration > 0:
            duration_str = f"~{total_duration:.0f}s cumulative"
        else:
            duration_str = "—"

    st.markdown(f"""
    <div class="pipeline-header">
        <h2>{selected}</h2>
        <div class="subtitle">{n_completed + n_failed}/{n_total} done · {n_running} running · {n_learnable} learnable · {duration_str} total</div>
    </div>
    """, unsafe_allow_html=True)

    # Compute batch costs from stages token data
    batch_gen_cost = 0.0
    batch_opus_cost = 0.0
    for t in tasks:
        gc, oc = _task_cost(t.get("stages", {}))
        batch_gen_cost += gc
        batch_opus_cost += oc
    batch_total_cost = batch_gen_cost + batch_opus_cost
    cost_per_learnable = (batch_total_cost / n_learnable) if n_learnable > 0 else 0.0

    # Summary cards (row 1: counts)
    st.markdown(f"""
    <div class="summary-grid">
        <div class="summary-card"><div class="summary-value">{n_total}</div><div class="summary-label">Total</div></div>
        <div class="summary-card"><div class="summary-value">{n_completed + n_failed}</div><div class="summary-label">Done</div></div>
        <div class="summary-card"><div class="summary-value highlight">{n_learnable}</div><div class="summary-label">Learnable</div></div>
        <div class="summary-card"><div class="summary-value">{n_hard}</div><div class="summary-label">Too Hard</div></div>
        <div class="summary-card"><div class="summary-value">{n_easy}</div><div class="summary-label">Too Easy</div></div>
        <div class="summary-card"><div class="summary-value">{n_failed}</div><div class="summary-label">Failed</div></div>
    </div>
    """, unsafe_allow_html=True)

    # Cost cards (row 2)
    st.markdown(f"""
    <div class="cost-grid">
        <div class="summary-card"><div class="summary-value cost">{_fmt_cost(batch_gen_cost)}</div><div class="summary-label">Generation cost</div></div>
        <div class="summary-card"><div class="summary-value cost">{_fmt_cost(batch_opus_cost)}</div><div class="summary-label">Opus eval cost</div></div>
        <div class="summary-card"><div class="summary-value cost">{_fmt_cost(cost_per_learnable)}</div><div class="summary-label">Cost / learnable</div></div>
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
        <div style="text-align:center">Time</div>
        <div style="text-align:center">Result</div>
    </div>
    """, unsafe_allow_html=True)

    # Batch start timestamp for filtering runs/ to current batch only
    batch_start_ts = _get_batch_start_ts(batch_dir)

    # Task rows with color-coded pipeline + expandable details
    for t in tasks:
        topic = t["topic"][:35] if t["topic"] else "?"
        full_topic = t.get("topic", "?")
        stage = t["stage"]
        cl = t.get("classification")
        pr = t.get("pass_rate")

        # Row class — adjusting tasks show as running, not final
        task_dir_rc = t.get("dir")
        is_adj_rc = (
            stage == "evaluating"
            and task_dir_rc
            and bool(glob.glob(task_dir_rc + ".pre_adj*"))
        )
        if is_adj_rc:
            row_class = "running"
        elif cl == "learnable":
            row_class = "learnable"
        elif cl == "too_hard":
            row_class = "too-hard"
        elif cl == "too_easy":
            row_class = "too-easy"
        elif cl == "eval_skipped":
            row_class = "learnable"
        elif stage == "failed":
            row_class = "failed"
        elif stage in ("generating", "structural", "functional", "evaluating"):
            row_class = "running"
        else:
            row_class = ""

        # Stage cells
        fs = t.get("failed_stage", "")
        gen_cell = _render_stage_cell(stage, "generating", fs)
        struct_cell = _render_stage_cell(stage, "structural", fs)
        func_cell = _render_stage_cell(stage, "functional", fs)

        # Determine if task is actively adjusting
        task_dir_adj = t.get("dir")
        is_adjusting = (
            stage == "evaluating"
            and task_dir_adj
            and bool(glob.glob(task_dir_adj + ".pre_adj*"))
        )

        if cl == "eval_skipped":
            sonnet_cell = '<div class="stage-cell stage-skipped">skip</div>'
            opus_cell = '<div class="stage-cell stage-skipped">skip</div>'
        elif stage in ("completed", "evaluating") or cl:
            eval_stages = t.get("stages", {}).get("evaluation", {})
            tier_results = eval_stages.get("tier_results", {})
            filtered_at = eval_stages.get("filtered_at")

            # Read eval_tiers from _status.json (durable, survives run cleanup)
            _eval_tiers = {}
            _status_path = os.path.join(t.get("dir", ""), "_status.json")
            if os.path.exists(_status_path):
                try:
                    _eval_tiers = json.load(open(_status_path)).get("eval_tiers", {})
                except Exception:
                    pass

            # Render each tier with unified logic
            _dn = os.path.basename(t.get("dir", ""))
            _adj_trigger = t.get("adj_trigger")
            sonnet_cell = _render_eval_tier_cell(
                "sonnet", tier_results, _eval_tiers, filtered_at,
                is_adjusting, stage, cl, _dn, batch_start_ts, _adj_trigger,
            )
            opus_cell = _render_eval_tier_cell(
                "opus", tier_results, _eval_tiers, filtered_at,
                is_adjusting, stage, cl, _dn, batch_start_ts, _adj_trigger,
            )
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
        elif cl == "eval_skipped":
            result_cell = '<div class="result-cell result-learnable">✓ func</div>'
        elif cl == "too_hard":
            if is_adj_rc:
                result_cell = '<div class="result-cell result-running">⏳</div>'
            else:
                result_cell = '<div class="result-cell result-hard">TOO HARD</div>'
        elif cl == "too_easy":
            eval_stages_r = t.get("stages", {}).get("evaluation", {})
            filtered_at_r = eval_stages_r.get("filtered_at")
            if is_adj_rc:
                result_cell = '<div class="result-cell result-running">⏳</div>'
            elif filtered_at_r in ("sonnet", "haiku"):
                result_cell = f'<div class="result-cell result-easy">TOO EASY ({filtered_at_r})</div>'
            else:
                result_cell = '<div class="result-cell result-easy">TOO EASY</div>'
        elif stage == "failed":
            result_cell = '<div class="result-cell result-failed">FAIL</div>'
        elif stage == "queued":
            result_cell = '<div class="result-cell" style="color:#4a5568">—</div>'
        else:
            result_cell = '<div class="result-cell result-running">⏳</div>'

        # Time cell
        dur = t.get("duration_sec")
        if dur and isinstance(dur, (int, float)):
            time_str = f"{dur/60:.0f}m" if dur >= 60 else f"{dur:.0f}s"
            time_cell = f'<div style="text-align:center; color:#8892b0; font-size:0.8em">{time_str}</div>'
        else:
            time_cell = '<div style="text-align:center; color:#4a5568; font-size:0.8em">—</div>'

        # Color-coded pipeline row (always visible)
        st.markdown(f"""
        <div class="task-row {row_class}">
            <div class="task-name" title="{full_topic}">{topic}</div>
            {gen_cell}
            {struct_cell}
            {func_cell}
            {sonnet_cell}
            {opus_cell}
            {time_cell}
            {result_cell}
        </div>
        """, unsafe_allow_html=True)

        # Flush expander for details — sits right below the row
        task_dir = t.get("dir")
        if task_dir and os.path.isdir(task_dir):
            with st.expander("details", expanded=False):
                _render_task_details(task_dir, t)

    # Aggregate stats + trend charts at bottom
    with st.expander("All-time metrics"):
        batches = _load_batch_results(OUTPUT_DIR)
        if batches:
            agg = compute_aggregate_metrics(batches)
            per_batch = compute_per_batch_metrics(batches)
            learnable_inv = get_learnable_inventory(batches)
            st.write(f"**{agg.get('total_tasks', 0)}** tasks across **{agg.get('num_batches', 0)}** batches")
            st.write(f"**{agg.get('learnable', 0)}** learnable ({agg.get('learnable_yield', 0):.0%} yield)")
            st.write(f"**{len(learnable_inv) + 3}** total learnable (including hand-crafted + Opus)")

            # Per-batch cost + yield trend
            batch_trend = []
            for b in batches:
                b_gen, b_opus = 0.0, 0.0
                b_learnable = 0
                for r in b["results"]:
                    gc, oc = _task_cost(r.get("stages", {}))
                    b_gen += gc
                    b_opus += oc
                    if r.get("classification") == "learnable":
                        b_learnable += 1
                b_total = b_gen + b_opus
                batch_trend.append({
                    "batch": b["name"].replace("sonnet-batch-", "b"),
                    "learnable": b_learnable,
                    "yield_pct": round(b_learnable / len(b["results"]) * 100, 1) if b["results"] else 0,
                    "cost": round(b_total, 2),
                    "cost_per_learnable": round(b_total / b_learnable, 2) if b_learnable > 0 else 0,
                })

            if batch_trend:
                st.markdown("**Learnable yield % per batch**")
                st.bar_chart(
                    {t["batch"]: t["yield_pct"] for t in batch_trend},
                    y_label="Yield %",
                )

                costs_available = [t for t in batch_trend if t["cost"] > 0]
                if costs_available:
                    st.markdown("**Cost per learnable task ($) per batch**")
                    st.bar_chart(
                        {t["batch"]: t["cost_per_learnable"] for t in costs_available},
                        y_label="$/learnable",
                    )

            # Category diversity across current batch
            st.markdown("**Category diversity (current batch)**")
            cat_counts: dict[str, int] = {}
            for t in tasks:
                cat = t.get("category")
                if cat:
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            if cat_counts:
                st.bar_chart(cat_counts, y_label="Tasks")
            else:
                st.caption("No category data yet (tasks still generating)")


# ── Main ──

st.set_page_config(page_title="Pipeline Dashboard", page_icon="🔬", layout="wide")
render_pipeline_view()
