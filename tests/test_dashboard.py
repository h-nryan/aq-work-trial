"""Tests for dashboard.py helper functions (no Streamlit dependency needed)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dashboard import (
    _diversity_scores,
    _fmt_cost,
    _infer_language,
    _jaccard,
    _render_stage_cell,
    _task_cost,
)


# ── _infer_language ─────────────────────────────────────────────────────────


class TestInferLanguage:
    def test_known_topic_from_prompt_bank(self):
        # Topics in PROMPT_BANK should return their metadata language
        lang = _infer_language("fix a broken Python script")
        assert isinstance(lang, str)
        assert lang != ""

    def test_keyword_fallback_python(self):
        assert _infer_language("debug a python web scraper") == "python"

    def test_keyword_fallback_bash(self):
        assert _infer_language("fix a bash deployment script") == "bash"

    def test_keyword_fallback_shell(self):
        assert _infer_language("repair a shell script") == "bash"

    def test_keyword_fallback_go(self):
        assert _infer_language("debug a go HTTP server") == "go"

    def test_keyword_fallback_cpp(self):
        assert _infer_language("fix a c++ memory leak") == "cpp"

    def test_keyword_fallback_java(self):
        assert _infer_language("repair a java build tool") == "java"

    def test_unknown_topic_returns_other(self):
        assert _infer_language("zzz_nonexistent_topic_xyz") == "other"


# ── _diversity_scores ───────────────────────────────────────────────────────


class TestDiversityScores:
    def test_empty_counts(self):
        coverage, evenness = _diversity_scores({})
        assert coverage == 0.0
        assert evenness == 0.0

    def test_single_category(self):
        coverage, evenness = _diversity_scores({"debugging": 5})
        assert coverage == 1 / 6
        assert evenness == 0.0  # only 1 category, no evenness

    def test_all_six_categories_equal(self):
        cats = {
            "debugging": 2, "data-processing": 2, "system-administration": 2,
            "software-engineering": 2, "build-systems": 2, "networking": 2,
        }
        coverage, evenness = _diversity_scores(cats)
        assert coverage == 1.0
        assert abs(evenness - 1.0) < 0.01  # perfectly even

    def test_all_six_categories_uneven(self):
        cats = {
            "debugging": 10, "data-processing": 1, "system-administration": 1,
            "software-engineering": 1, "build-systems": 1, "networking": 1,
        }
        coverage, evenness = _diversity_scores(cats)
        assert coverage == 1.0
        assert 0.0 < evenness < 1.0  # uneven but present

    def test_unknown_category_not_counted_for_coverage(self):
        coverage, _ = _diversity_scores({"unknown-cat": 5, "debugging": 3})
        assert coverage == 1 / 6  # only debugging matches

    def test_two_categories(self):
        coverage, evenness = _diversity_scores({"debugging": 5, "networking": 5})
        assert coverage == 2 / 6
        assert abs(evenness - 1.0) < 0.01  # perfectly even across 2


# ── _jaccard ────────────────────────────────────────────────────────────────


class TestJaccard:
    def test_identical_sets(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        sim = _jaccard({"a", "b", "c"}, {"b", "c", "d"})
        assert abs(sim - 0.5) < 0.01  # 2/4

    def test_both_empty(self):
        assert _jaccard(set(), set()) == 1.0

    def test_one_empty(self):
        assert _jaccard(set(), {"a"}) == 0.0


# ── _task_cost ──────────────────────────────────────────────────────────────


class TestTaskCost:
    def test_empty_stages(self):
        gen, sonnet_eval, opus = _task_cost({})
        assert gen == 0.0
        assert opus == 0.0

    def test_generation_cost(self):
        stages = {
            "generate": {
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500}
            }
        }
        gen, sonnet_eval, opus = _task_cost(stages)
        assert gen > 0.0
        assert opus == 0.0

    def test_retry_cost_included(self):
        stages = {
            "retry_1": {
                "usage": {"prompt_tokens": 100, "completion_tokens": 50}
            }
        }
        gen, _, _ = _task_cost(stages)
        assert gen > 0.0

    def test_difficulty_adjustment_cost_included(self):
        stages = {
            "difficulty_adj_1": {
                "usage": {"prompt_tokens": 200, "completion_tokens": 100}
            }
        }
        gen, _, _ = _task_cost(stages)
        assert gen > 0.0

    def test_opus_cost_from_trials(self):
        stages = {
            "evaluation": {
                "tier_results": {
                    "opus": {
                        "trials": [{
                            "trials": [
                                {"input_tokens": 10000, "output_tokens": 5000},
                                {"input_tokens": 10000, "output_tokens": 5000},
                            ]
                        }]
                    }
                }
            }
        }
        _, _, opus = _task_cost(stages)
        assert opus > 0.0

    def test_opus_cost_with_none_tokens(self):
        stages = {
            "evaluation": {
                "tier_results": {
                    "opus": {
                        "trials": [{
                            "trials": [
                                {"input_tokens": None, "output_tokens": None},
                            ]
                        }]
                    }
                }
            }
        }
        _, _, opus = _task_cost(stages)
        assert opus == 0.0


# ── _fmt_cost ───────────────────────────────────────────────────────────────


class TestFmtCost:
    def test_zero(self):
        assert _fmt_cost(0) == "—"

    def test_small_cost(self):
        assert _fmt_cost(0.005) == "<$0.01"

    def test_normal_cost(self):
        assert _fmt_cost(1.50) == "$1.50"

    def test_large_cost(self):
        assert _fmt_cost(100.0) == "$100.00"


# ── _render_stage_cell ──────────────────────────────────────────────────────


class TestRenderStageCell:
    def test_completed_stage(self):
        html = _render_stage_cell("evaluating", "generating")
        assert "stage-done" in html
        assert "✓" in html

    def test_active_stage(self):
        html = _render_stage_cell("evaluating", "evaluating")
        assert "stage-active" in html

    def test_pending_stage(self):
        html = _render_stage_cell("generating", "evaluating")
        assert "stage-pending" in html

    def test_failed_stage_with_info(self):
        html = _render_stage_cell("failed", "functional", failed_stage="functional")
        assert "stage-failed" in html
        assert "FAIL" in html

    def test_failed_stage_prior_passed(self):
        html = _render_stage_cell("failed", "generating", failed_stage="functional")
        assert "stage-done" in html

    def test_failed_stage_after_failure_pending(self):
        html = _render_stage_cell("failed", "evaluating", failed_stage="functional")
        assert "stage-pending" in html

    def test_failed_no_info(self):
        html = _render_stage_cell("failed", "generating")
        assert "stage-failed" in html
