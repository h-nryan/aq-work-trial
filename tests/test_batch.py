"""Tests for batch runner metrics and reporting."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from batch import _compute_metrics, _estimate_cost, _pct, _slugify


class TestSlugify:
    def test_basic(self):
        assert _slugify("Fix a broken Python script") == "fix-a-broken-python-script"

    def test_slashes(self):
        assert _slugify("fix a/b issue") == "fix-a-b-issue"

    def test_truncates_at_60(self):
        long = "a " * 50
        assert len(_slugify(long)) <= 60


class TestPct:
    def test_normal(self):
        assert _pct(3, 10) == "30%"

    def test_zero_denom(self):
        assert _pct(5, 0) == "- %"

    def test_full(self):
        assert _pct(10, 10) == "100%"


class TestEstimateCost:
    def test_empty_results(self):
        costs = _estimate_cost([])
        assert costs["total_cost_usd"] == 0

    def test_generation_cost(self):
        results = [{
            "stages": {
                "generate": {
                    "model": "anthropic/claude-sonnet-4.5",
                    "usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 500,
                        "total_tokens": 1500,
                    },
                },
            },
        }]
        costs = _estimate_cost(results)
        # 1000/1000 * 0.003 + 500/1000 * 0.015 = 0.003 + 0.0075 = 0.0105
        assert costs["generation_cost_usd"] == 0.0105
        assert costs["evaluation_cost_usd"] == 0

    def test_no_stages(self):
        results = [{"status": "error", "classification": None}]
        costs = _estimate_cost(results)
        assert costs["total_cost_usd"] == 0


class TestComputeMetrics:
    def _make_result(self, status="completed", structural=True, functional=True,
                     classification=None, pass_rate=None, gen_tokens=100):
        r = {
            "topic": "test topic",
            "status": status,
            "stages": {},
        }
        if structural is not None:
            r["stages"]["structural"] = {"passed": structural}
        if functional is not None:
            r["stages"]["functional"] = {"passed": functional}
        if classification is not None:
            r["stages"]["evaluation"] = {"classification": classification}
            r["classification"] = classification
            r["pass_rate"] = pass_rate
        r["stages"]["generate"] = {"usage": {"total_tokens": gen_tokens}}
        return r

    def test_all_learnable(self):
        results = [self._make_result(classification="learnable", pass_rate=0.4) for _ in range(3)]
        m = _compute_metrics(results, 60.0, "test-batch")
        assert m["total_topics"] == 3
        assert m["generated"] == 3
        assert m["learnable"] == 3
        assert m["learnable_rate"] == 1.0

    def test_mixed_classifications(self):
        results = [
            self._make_result(classification="learnable"),
            self._make_result(classification="too_easy"),
            self._make_result(classification="too_hard"),
        ]
        m = _compute_metrics(results, 30.0, "test")
        assert m["learnable"] == 1
        assert m["too_easy"] == 1
        assert m["too_hard"] == 1
        assert m["evaluated"] == 3

    def test_generation_failure(self):
        results = [
            self._make_result(status="generation_failed", structural=None, functional=None),
            self._make_result(status="completed"),
        ]
        m = _compute_metrics(results, 20.0, "test")
        assert m["generated"] == 1

    def test_error_status_not_counted_as_generated(self):
        results = [
            {"topic": "bad", "status": "error: timeout", "classification": None},
            self._make_result(),
        ]
        m = _compute_metrics(results, 10.0, "test")
        assert m["generated"] == 1

    def test_funnel_counts(self):
        results = [
            self._make_result(structural=True, functional=True, classification="learnable"),
            self._make_result(structural=True, functional=False),
            self._make_result(structural=False, functional=None),
        ]
        m = _compute_metrics(results, 30.0, "test")
        assert m["structural_pass"] == 2
        assert m["functional_pass"] == 1
        assert m["evaluated"] == 1

    def test_token_aggregation(self):
        results = [
            self._make_result(gen_tokens=500),
            self._make_result(gen_tokens=300),
        ]
        m = _compute_metrics(results, 10.0, "test")
        assert m["total_gen_tokens"] == 800

    def test_timing(self):
        results = [self._make_result()]
        m = _compute_metrics(results, 45.7, "test")
        assert m["total_duration_sec"] == 45.7
        assert m["avg_duration_per_task_sec"] == 45.7

    def test_cost_included(self):
        results = [self._make_result()]
        m = _compute_metrics(results, 10.0, "test")
        assert "generation_cost_usd" in m
        assert "evaluation_cost_usd" in m
        assert "total_cost_usd" in m
