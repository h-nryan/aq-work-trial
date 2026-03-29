"""Tests for batch runner metrics and reporting."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from batch import _compute_metrics, _estimate_cost, _pct, run_batch


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


class TestRunBatchConcurrency:
    """Tests for concurrent execution parameter handling and thread safety."""

    def test_n_concurrent_defaults_to_1(self):
        import inspect
        sig = inspect.signature(run_batch)
        assert sig.parameters["n_concurrent"].default == 1

    def test_workers_capped_to_remaining(self, tmp_path, monkeypatch):
        """min(n_concurrent, len(remaining)) — no idle threads when batch is small."""
        import threading

        worker_counts = []

        original_tpe = __import__(
            "concurrent.futures", fromlist=["ThreadPoolExecutor"]
        ).ThreadPoolExecutor

        class CapturingTPE(original_tpe):
            def __init__(self, *args, max_workers=None, **kwargs):
                worker_counts.append(max_workers)
                super().__init__(*args, max_workers=max_workers, **kwargs)

        monkeypatch.setattr("batch.ThreadPoolExecutor", CapturingTPE)
        monkeypatch.setattr(
            "batch.run_pipeline",
            lambda **kw: {"topic": kw["topic"], "status": "completed", "stages": {}},
        )

        run_batch(
            topics=["topic a", "topic b"],
            n_tasks=2,
            n_concurrent=10,  # more workers requested than topics
            output_dir=str(tmp_path),
        )
        # ThreadPoolExecutor should be called with 2, not 10
        assert worker_counts == [2]

    def test_sequential_path_skips_executor(self, tmp_path, monkeypatch):
        """n_concurrent=1 must not spin up a ThreadPoolExecutor at all."""
        executor_created = []

        original_tpe = __import__(
            "concurrent.futures", fromlist=["ThreadPoolExecutor"]
        ).ThreadPoolExecutor

        class TrackingTPE(original_tpe):
            def __init__(self, *args, **kwargs):
                executor_created.append(True)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr("batch.ThreadPoolExecutor", TrackingTPE)
        monkeypatch.setattr(
            "batch.run_pipeline",
            lambda **kw: {"topic": kw["topic"], "status": "completed", "stages": {}},
        )

        run_batch(
            topics=["only one topic"],
            n_tasks=1,
            n_concurrent=1,
            output_dir=str(tmp_path),
        )
        assert executor_created == [], "ThreadPoolExecutor should not be used for n_concurrent=1"

    def test_concurrent_writes_are_valid_jsonl(self, tmp_path, monkeypatch):
        """Concurrent workers writing to the same file must produce valid JSONL."""
        import time

        def slow_pipeline(**kw):
            time.sleep(0.01)  # interleave writes
            return {"topic": kw["topic"], "status": "completed", "stages": {}}

        monkeypatch.setattr("batch.run_pipeline", slow_pipeline)

        topics = [f"topic {i}" for i in range(8)]
        run_batch(
            topics=topics,
            n_tasks=8,
            n_concurrent=4,
            output_dir=str(tmp_path),
        )

        # The incremental file is cleaned up after a successful run; check report instead
        import json
        reports = list(tmp_path.glob("batch-*-report.json"))
        assert len(reports) == 1
        with open(reports[0]) as f:
            report = json.load(f)
        assert report["metrics"]["total_topics"] == 8
        result_topics = {r["topic"] for r in report["results"]}
        assert result_topics == set(topics)

    def test_topic_plan_index_preserves_order(self, tmp_path, monkeypatch):
        """Results in the final report appear in original topic order."""
        import json
        import time
        import random

        def staggered_pipeline(**kw):
            time.sleep(random.uniform(0, 0.02))
            return {"topic": kw["topic"], "status": "completed", "stages": {}}

        monkeypatch.setattr("batch.run_pipeline", staggered_pipeline)

        topics = [f"topic {i}" for i in range(6)]
        run_batch(
            topics=topics,
            n_tasks=6,
            n_concurrent=3,
            output_dir=str(tmp_path),
        )

        reports = list(tmp_path.glob("batch-*-report.json"))
        with open(reports[0]) as f:
            report = json.load(f)

        result_order = [r["topic"] for r in report["results"]]
        assert result_order == topics
