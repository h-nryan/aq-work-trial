"""Tests for the pipeline metrics module."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from metrics import (
    _load_batch_results,
    compute_aggregate_metrics,
    compute_per_batch_metrics,
    get_learnable_inventory,
    render_html,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(
    topic="test-topic",
    status="completed",
    structural=True,
    functional=True,
    classification=None,
    pass_rate=None,
    retries=0,
    gen_tokens=100,
    duration_sec=10.0,
):
    """Build a single result dict matching the shape produced by the pipeline."""
    r = {
        "topic": topic,
        "status": status,
        "stages": {},
        "duration_sec": duration_sec,
    }
    if structural is not None:
        r["stages"]["structural"] = {"passed": structural}
    if functional is not None:
        r["stages"]["functional"] = {"passed": functional}
    r["stages"]["generate"] = {"usage": {"total_tokens": gen_tokens}}
    if classification is not None:
        r["classification"] = classification
        r["pass_rate"] = pass_rate
        r["retries"] = retries
    return r


def _make_batch(name="sonnet-batch-001", results=None):
    """Wrap results into a batch dict."""
    return {"name": name, "results": results or []}


# ---------------------------------------------------------------------------
# compute_aggregate_metrics
# ---------------------------------------------------------------------------

class TestComputeAggregateMetrics:

    def test_empty_batches(self):
        m = compute_aggregate_metrics([])
        assert m["total_tasks"] == 0
        assert m["generated"] == 0
        assert m["learnable_yield"] == 0
        assert m["functional_rate"] == 0
        assert m["learnable_of_evaluated"] == 0
        assert m["num_batches"] == 0

    def test_single_batch_all_learnable(self):
        results = [
            _make_result(topic=f"t{i}", classification="learnable", pass_rate=0.4)
            for i in range(3)
        ]
        m = compute_aggregate_metrics([_make_batch(results=results)])
        assert m["total_tasks"] == 3
        assert m["generated"] == 3
        assert m["structural_pass"] == 3
        assert m["functional_pass"] == 3
        assert m["evaluated"] == 3
        assert m["learnable"] == 3
        assert m["too_easy"] == 0
        assert m["too_hard"] == 0
        assert m["learnable_yield"] == 1.0
        assert m["learnable_of_evaluated"] == 1.0
        assert m["num_batches"] == 1

    def test_multiple_batches_aggregated(self):
        b1 = _make_batch("batch-1", [
            _make_result(topic="a", classification="learnable"),
            _make_result(topic="b", classification="too_easy"),
        ])
        b2 = _make_batch("batch-2", [
            _make_result(topic="c", classification="too_hard"),
            _make_result(topic="d", classification="learnable"),
        ])
        m = compute_aggregate_metrics([b1, b2])
        assert m["total_tasks"] == 4
        assert m["learnable"] == 2
        assert m["too_easy"] == 1
        assert m["too_hard"] == 1
        assert m["num_batches"] == 2

    def test_generation_failures_excluded(self):
        results = [
            _make_result(status="generation_failed", structural=None, functional=None),
            _make_result(status="retry_generation_failed", structural=None, functional=None),
            _make_result(status="error: timeout", structural=None, functional=None),
            _make_result(status="completed"),
        ]
        m = compute_aggregate_metrics([_make_batch(results=results)])
        assert m["total_tasks"] == 4
        assert m["generated"] == 1

    def test_functional_rate_denominator_is_generated(self):
        results = [
            _make_result(functional=True),
            _make_result(functional=False),
            _make_result(status="generation_failed", structural=None, functional=None),
        ]
        m = compute_aggregate_metrics([_make_batch(results=results)])
        assert m["generated"] == 2
        assert m["functional_pass"] == 1
        assert m["functional_rate"] == 0.5

    def test_token_aggregation(self):
        results = [
            _make_result(gen_tokens=500),
            _make_result(gen_tokens=300),
        ]
        m = compute_aggregate_metrics([_make_batch(results=results)])
        assert m["total_gen_tokens"] == 800

    def test_duration_aggregation(self):
        results = [
            _make_result(duration_sec=12.5),
            _make_result(duration_sec=7.5),
        ]
        m = compute_aggregate_metrics([_make_batch(results=results)])
        assert m["total_duration_sec"] == 20.0

    def test_mixed_classifications(self):
        results = [
            _make_result(classification="learnable"),
            _make_result(classification="too_easy"),
            _make_result(classification="too_hard"),
            _make_result(),  # no classification
        ]
        m = compute_aggregate_metrics([_make_batch(results=results)])
        assert m["evaluated"] == 3
        assert m["learnable_of_evaluated"] == round(1 / 3, 4)
        assert m["learnable_yield"] == round(1 / 4, 4)

    def test_no_evaluated_tasks(self):
        results = [_make_result(), _make_result()]
        m = compute_aggregate_metrics([_make_batch(results=results)])
        assert m["evaluated"] == 0
        assert m["learnable_of_evaluated"] == 0


# ---------------------------------------------------------------------------
# compute_per_batch_metrics
# ---------------------------------------------------------------------------

class TestComputePerBatchMetrics:

    def test_empty_batches(self):
        assert compute_per_batch_metrics([]) == []

    def test_single_batch(self):
        results = [
            _make_result(functional=True, classification="learnable", duration_sec=60),
            _make_result(functional=False, classification="too_hard", duration_sec=120),
        ]
        per_batch = compute_per_batch_metrics([_make_batch("b1", results)])
        assert len(per_batch) == 1
        b = per_batch[0]
        assert b["name"] == "b1"
        assert b["total"] == 2
        assert b["functional"] == 1
        assert b["evaluated"] == 2
        assert b["learnable"] == 1
        assert b["too_hard"] == 1
        assert b["too_easy"] == 0
        assert b["duration_min"] == 3.0  # 180s / 60

    def test_multiple_batches_independent(self):
        b1 = _make_batch("b1", [_make_result(classification="learnable")])
        b2 = _make_batch("b2", [
            _make_result(classification="too_easy"),
            _make_result(classification="too_easy"),
        ])
        per_batch = compute_per_batch_metrics([b1, b2])
        assert len(per_batch) == 2
        assert per_batch[0]["learnable"] == 1
        assert per_batch[0]["too_easy"] == 0
        assert per_batch[1]["learnable"] == 0
        assert per_batch[1]["too_easy"] == 2

    def test_duration_converted_to_minutes(self):
        results = [_make_result(duration_sec=90)]
        per_batch = compute_per_batch_metrics([_make_batch(results=results)])
        assert per_batch[0]["duration_min"] == 1.5


# ---------------------------------------------------------------------------
# get_learnable_inventory
# ---------------------------------------------------------------------------

class TestGetLearnableInventory:

    def test_empty_batches(self):
        assert get_learnable_inventory([]) == []

    def test_no_learnable_tasks(self):
        results = [
            _make_result(classification="too_easy"),
            _make_result(classification="too_hard"),
            _make_result(),  # no classification
        ]
        assert get_learnable_inventory([_make_batch(results=results)]) == []

    def test_extracts_learnable_only(self):
        results = [
            _make_result(topic="good-one", classification="learnable", pass_rate=0.4, retries=2),
            _make_result(topic="easy", classification="too_easy"),
            _make_result(topic="another-good", classification="learnable", pass_rate=0.6, retries=0),
        ]
        inv = get_learnable_inventory([_make_batch("batch-x", results)])
        assert len(inv) == 2
        assert inv[0]["batch"] == "batch-x"
        assert inv[0]["topic"] == "good-one"
        assert inv[0]["pass_rate"] == 0.4
        assert inv[0]["retries"] == 2
        assert inv[1]["topic"] == "another-good"

    def test_across_multiple_batches(self):
        b1 = _make_batch("b1", [_make_result(topic="t1", classification="learnable", pass_rate=0.3)])
        b2 = _make_batch("b2", [_make_result(topic="t2", classification="learnable", pass_rate=0.5)])
        inv = get_learnable_inventory([b1, b2])
        assert len(inv) == 2
        assert inv[0]["batch"] == "b1"
        assert inv[1]["batch"] == "b2"

    def test_missing_optional_fields(self):
        """Results without pass_rate or retries should default gracefully."""
        r = {"topic": "bare", "classification": "learnable"}
        inv = get_learnable_inventory([_make_batch(results=[r])])
        assert len(inv) == 1
        assert inv[0]["pass_rate"] == 0
        assert inv[0]["retries"] == 0


# ---------------------------------------------------------------------------
# _load_batch_results — filesystem integration tests
# ---------------------------------------------------------------------------

class TestLoadBatchResults:

    def _write_report(self, batch_dir, results):
        """Write a report JSON into the batch directory."""
        report_path = os.path.join(batch_dir, "batch-001-report.json")
        with open(report_path, "w") as f:
            json.dump({"results": results}, f)

    def _write_incremental(self, batch_dir, results):
        """Write an incremental JSONL file into the batch directory."""
        incr_path = os.path.join(batch_dir, "batch-001-incremental.jsonl")
        with open(incr_path, "w") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")

    def test_empty_output_dir(self, tmp_path):
        assert _load_batch_results(str(tmp_path)) == []

    def test_no_matching_dirs(self, tmp_path):
        (tmp_path / "unrelated-dir").mkdir()
        assert _load_batch_results(str(tmp_path)) == []

    def test_report_only(self, tmp_path):
        batch_dir = tmp_path / "sonnet-batch-001"
        batch_dir.mkdir()
        results = [_make_result(topic="alpha")]
        self._write_report(str(batch_dir), results)

        batches = _load_batch_results(str(tmp_path))
        assert len(batches) == 1
        assert batches[0]["name"] == "sonnet-batch-001"
        assert len(batches[0]["results"]) == 1
        assert batches[0]["results"][0]["topic"] == "alpha"

    def test_incremental_only(self, tmp_path):
        batch_dir = tmp_path / "sonnet-batch-002"
        batch_dir.mkdir()
        results = [
            _make_result(topic="beta"),
            _make_result(topic="gamma"),
        ]
        self._write_incremental(str(batch_dir), results)

        batches = _load_batch_results(str(tmp_path))
        assert len(batches) == 1
        assert len(batches[0]["results"]) == 2

    def test_incremental_with_blank_lines(self, tmp_path):
        """Blank lines in JSONL should be silently skipped."""
        batch_dir = tmp_path / "sonnet-batch-003"
        batch_dir.mkdir()
        incr_path = batch_dir / "batch-001-incremental.jsonl"
        incr_path.write_text(
            json.dumps(_make_result(topic="a")) + "\n"
            + "\n"
            + "   \n"
            + json.dumps(_make_result(topic="b")) + "\n"
        )

        batches = _load_batch_results(str(tmp_path))
        assert len(batches[0]["results"]) == 2

    def test_corrupt_report_json_skipped(self, tmp_path):
        batch_dir = tmp_path / "sonnet-batch-004"
        batch_dir.mkdir()
        (batch_dir / "batch-001-report.json").write_text("{invalid json!!")

        batches = _load_batch_results(str(tmp_path))
        assert batches == []

    def test_corrupt_jsonl_lines_skipped(self, tmp_path):
        """Bad lines in JSONL should be skipped without crashing."""
        batch_dir = tmp_path / "sonnet-batch-005"
        batch_dir.mkdir()
        incr_path = batch_dir / "batch-001-incremental.jsonl"
        incr_path.write_text(
            json.dumps(_make_result(topic="good")) + "\n"
            + "{bad json}\n"
            + json.dumps(_make_result(topic="also-good")) + "\n"
        )

        batches = _load_batch_results(str(tmp_path))
        assert len(batches[0]["results"]) == 2

    def test_multiple_batch_dirs_sorted(self, tmp_path):
        for name in ["sonnet-batch-003", "sonnet-batch-001", "sonnet-batch-002"]:
            d = tmp_path / name
            d.mkdir()
            self._write_report(str(d), [_make_result(topic=name)])

        batches = _load_batch_results(str(tmp_path))
        assert len(batches) == 3
        assert [b["name"] for b in batches] == [
            "sonnet-batch-001", "sonnet-batch-002", "sonnet-batch-003",
        ]

    def test_batch_dir_with_no_files_skipped(self, tmp_path):
        (tmp_path / "sonnet-batch-empty").mkdir()
        assert _load_batch_results(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# Incremental JSONL merge logic
# ---------------------------------------------------------------------------

class TestIncrementalMerge:
    """Tests for the merge behavior when both report and incremental files exist."""

    def _setup_batch(self, tmp_path, report_results, incr_results):
        batch_dir = tmp_path / "sonnet-batch-001"
        batch_dir.mkdir(exist_ok=True)
        report_path = batch_dir / "batch-001-report.json"
        report_path.write_text(json.dumps({"results": report_results}))
        incr_path = batch_dir / "batch-001-incremental.jsonl"
        incr_path.write_text(
            "\n".join(json.dumps(r) for r in incr_results) + "\n"
        )
        return str(tmp_path)

    def test_report_with_null_classification_replaced_by_incremental(self, tmp_path):
        """Stub results (null classification) in report should be replaced by incremental data."""
        report_results = [
            {"topic": "topic-a", "classification": None, "status": "completed"},
            {"topic": "topic-b", "classification": "learnable", "status": "completed"},
        ]
        incr_results = [
            {"topic": "topic-a", "classification": "too_easy", "status": "completed"},
        ]
        output_dir = self._setup_batch(tmp_path, report_results, incr_results)
        batches = _load_batch_results(output_dir)

        results_by_topic = {r["topic"]: r for r in batches[0]["results"]}
        # topic-a should have been replaced with incremental data
        assert results_by_topic["topic-a"]["classification"] == "too_easy"
        # topic-b was already good in the report, should be unchanged
        assert results_by_topic["topic-b"]["classification"] == "learnable"

    def test_report_with_real_classification_not_overwritten(self, tmp_path):
        """If report already has a classification, incremental data should NOT replace it."""
        report_results = [
            {"topic": "topic-a", "classification": "learnable", "status": "completed"},
        ]
        incr_results = [
            {"topic": "topic-a", "classification": "too_hard", "status": "completed"},
        ]
        output_dir = self._setup_batch(tmp_path, report_results, incr_results)
        batches = _load_batch_results(output_dir)

        assert batches[0]["results"][0]["classification"] == "learnable"

    def test_incremental_adds_topics_missing_from_report(self, tmp_path):
        """Topics present in incremental but absent from report should be appended."""
        report_results = [
            {"topic": "topic-a", "classification": "learnable", "status": "completed"},
        ]
        incr_results = [
            {"topic": "topic-b", "classification": "too_hard", "status": "completed"},
        ]
        output_dir = self._setup_batch(tmp_path, report_results, incr_results)
        batches = _load_batch_results(output_dir)

        topics = {r["topic"] for r in batches[0]["results"]}
        assert topics == {"topic-a", "topic-b"}

    def test_incremental_without_classification_not_merged(self, tmp_path):
        """Incremental records with no classification should not replace anything."""
        report_results = [
            {"topic": "topic-a", "classification": None, "status": "completed"},
        ]
        incr_results = [
            {"topic": "topic-a", "status": "completed"},  # no classification key
        ]
        output_dir = self._setup_batch(tmp_path, report_results, incr_results)
        batches = _load_batch_results(output_dir)

        # Should stay as the report stub since incremental has no classification
        assert batches[0]["results"][0]["classification"] is None

    def test_merge_with_multiple_stub_results(self, tmp_path):
        """Multiple stub results should each be replaceable independently."""
        report_results = [
            {"topic": "t1", "classification": None, "status": "completed"},
            {"topic": "t2", "classification": None, "status": "completed"},
            {"topic": "t3", "classification": "learnable", "status": "completed"},
        ]
        incr_results = [
            {"topic": "t1", "classification": "too_easy", "status": "completed"},
            {"topic": "t2", "classification": "too_hard", "status": "completed"},
        ]
        output_dir = self._setup_batch(tmp_path, report_results, incr_results)
        batches = _load_batch_results(output_dir)

        by_topic = {r["topic"]: r for r in batches[0]["results"]}
        assert by_topic["t1"]["classification"] == "too_easy"
        assert by_topic["t2"]["classification"] == "too_hard"
        assert by_topic["t3"]["classification"] == "learnable"


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------

class TestRenderHtml:

    def _sample_metrics(self):
        return {
            "aggregate": {
                "total_tasks": 10,
                "generated": 9,
                "structural_pass": 8,
                "functional_pass": 7,
                "evaluated": 6,
                "learnable": 3,
                "too_easy": 2,
                "too_hard": 1,
                "learnable_yield": 0.3,
                "functional_rate": 0.7778,
                "learnable_of_evaluated": 0.5,
                "total_gen_tokens": 5000,
                "total_duration_sec": 600.0,
                "num_batches": 2,
            },
            "per_batch": [
                {
                    "name": "sonnet-batch-001",
                    "total": 5, "functional": 4, "evaluated": 3,
                    "learnable": 2, "too_easy": 1, "too_hard": 0,
                    "duration_min": 5.0,
                },
                {
                    "name": "sonnet-batch-002",
                    "total": 5, "functional": 3, "evaluated": 3,
                    "learnable": 1, "too_easy": 1, "too_hard": 1,
                    "duration_min": 5.0,
                },
            ],
            "learnable": [
                {"batch": "sonnet-batch-001", "topic": "fix-broken-parser", "pass_rate": 0.4, "retries": 1},
                {"batch": "sonnet-batch-002", "topic": "repair-template-engine", "pass_rate": 0.6, "retries": 0},
            ],
        }

    def test_produces_valid_html_file(self, tmp_path):
        out = str(tmp_path / "dashboard.html")
        render_html(self._sample_metrics(), out)
        assert os.path.isfile(out)
        html = open(out).read()
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_aggregate_values(self, tmp_path):
        out = str(tmp_path / "dashboard.html")
        render_html(self._sample_metrics(), out)
        html = open(out).read()
        assert ">10<" in html  # total_tasks
        assert ">3<" in html   # learnable count
        assert "5,000" in html  # total_gen_tokens with comma

    def test_contains_per_batch_rows(self, tmp_path):
        out = str(tmp_path / "dashboard.html")
        render_html(self._sample_metrics(), out)
        html = open(out).read()
        assert "sonnet-batch-001" in html
        assert "sonnet-batch-002" in html

    def test_contains_learnable_inventory(self, tmp_path):
        out = str(tmp_path / "dashboard.html")
        render_html(self._sample_metrics(), out)
        html = open(out).read()
        assert "fix-broken-parser" in html
        assert "repair-template-engine" in html

    def test_empty_metrics(self, tmp_path):
        out = str(tmp_path / "empty.html")
        render_html({"aggregate": {}, "per_batch": [], "learnable": []}, out)
        html = open(out).read()
        assert "<!DOCTYPE html>" in html
        assert "</html>" in html

    def test_no_learnable_section_when_empty(self, tmp_path):
        out = str(tmp_path / "no-learn.html")
        render_html({"aggregate": {"total_tasks": 1}, "per_batch": [], "learnable": []}, out)
        html = open(out).read()
        assert "Learnable Task Inventory" not in html

    def test_learnable_section_present_when_populated(self, tmp_path):
        out = str(tmp_path / "with-learn.html")
        render_html(self._sample_metrics(), out)
        html = open(out).read()
        assert "Learnable Task Inventory" in html

    def test_funnel_bars_present(self, tmp_path):
        out = str(tmp_path / "funnel.html")
        render_html(self._sample_metrics(), out)
        html = open(out).read()
        assert "funnel-fill" in html
        assert "Generated:" in html
        assert "Learnable:" in html
