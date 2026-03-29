"""Tests for batch resume helpers (batch_io module).

Imports from batch_io directly — no openai/pydantic dependency.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from batch_io import load_incremental, load_meta, resolve_resume, save_meta


class TestSaveMeta:
    def test_creates_file(self, tmp_path):
        meta_path = str(tmp_path / "batch-test-meta.json")
        save_meta(meta_path, "test-id", ["topic a", "topic b"], seed=42)
        assert os.path.exists(meta_path)

    def test_contents(self, tmp_path):
        meta_path = str(tmp_path / "batch-test-meta.json")
        topics = ["fix a Python bug", "debug a C program"]
        save_meta(meta_path, "abc123", topics, seed=7)
        with open(meta_path) as f:
            data = json.load(f)
        assert data["batch_id"] == "abc123"
        assert data["topics"] == topics
        assert data["seed"] == 7

    def test_seed_none(self, tmp_path):
        meta_path = str(tmp_path / "batch-test-meta.json")
        save_meta(meta_path, "abc", ["topic"], seed=None)
        with open(meta_path) as f:
            data = json.load(f)
        assert data["seed"] is None


class TestLoadMeta:
    def test_missing_returns_none(self, tmp_path):
        assert load_meta(str(tmp_path / "nonexistent.json")) is None

    def test_roundtrip(self, tmp_path):
        meta_path = str(tmp_path / "meta.json")
        topics = ["topic 1", "topic 2", "topic 3"]
        save_meta(meta_path, "batch-xyz", topics, seed=99)
        meta = load_meta(meta_path)
        assert meta is not None
        assert meta["topics"] == topics
        assert meta["seed"] == 99


class TestLoadIncremental:
    def _write_results(self, path, results):
        with open(path, "w") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")

    def test_missing_file_returns_empty(self, tmp_path):
        results, completed = load_incremental(str(tmp_path / "nope.jsonl"))
        assert results == []
        assert completed == set()

    def test_loads_completed_topics(self, tmp_path):
        path = str(tmp_path / "incremental.jsonl")
        self._write_results(path, [
            {"topic": "fix a Python bug", "status": "completed"},
            {"topic": "debug a C program", "status": "completed"},
        ])
        results, completed = load_incremental(path)
        assert len(results) == 2
        assert "fix a Python bug" in completed
        assert "debug a C program" in completed

    def test_skips_malformed_lines(self, tmp_path):
        path = str(tmp_path / "incremental.jsonl")
        with open(path, "w") as f:
            f.write('{"topic": "good topic", "status": "completed"}\n')
            f.write('{"topic": "incomplete json...\n')  # partial write
        results, completed = load_incremental(path)
        assert len(results) == 1
        assert "good topic" in completed

    def test_empty_lines_ignored(self, tmp_path):
        path = str(tmp_path / "incremental.jsonl")
        with open(path, "w") as f:
            f.write('{"topic": "topic a", "status": "completed"}\n')
            f.write("\n")
            f.write('{"topic": "topic b", "status": "completed"}\n')
        results, completed = load_incremental(path)
        assert len(results) == 2

    def test_topic_without_key_not_counted(self, tmp_path):
        path = str(tmp_path / "incremental.jsonl")
        self._write_results(path, [{"status": "error", "classification": None}])
        _, completed = load_incremental(path)
        assert len(completed) == 0


class TestResolveResume:
    def _make_batch_files(self, tmp_path, batch_id, with_meta=True, with_incremental=True):
        if with_meta:
            meta = tmp_path / f"batch-{batch_id}-meta.json"
            meta.write_text(json.dumps({"batch_id": batch_id, "topics": [], "seed": None}))
        if with_incremental:
            inc = tmp_path / f"batch-{batch_id}-incremental.jsonl"
            inc.write_text("")

    def test_resolve_by_batch_id(self, tmp_path):
        bid = "20240101-120000"
        self._make_batch_files(tmp_path, bid)
        resolved_id, meta_path, inc_path = resolve_resume(bid, str(tmp_path))
        assert resolved_id == bid
        assert meta_path.endswith(f"batch-{bid}-meta.json")
        assert inc_path.endswith(f"batch-{bid}-incremental.jsonl")

    def test_resolve_auto_picks_most_recent(self, tmp_path):
        bid1 = "20240101-100000"
        bid2 = "20240101-120000"
        self._make_batch_files(tmp_path, bid1)
        time.sleep(0.02)
        self._make_batch_files(tmp_path, bid2)
        resolved_id, _, _ = resolve_resume("auto", str(tmp_path))
        assert resolved_id == bid2

    def test_resolve_auto_no_files_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_resume("auto", str(tmp_path))

    def test_resolve_unknown_id_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_resume("nonexistent-id", str(tmp_path))

    def test_meta_only_still_resolves(self, tmp_path):
        bid = "20240101-120000"
        self._make_batch_files(tmp_path, bid, with_meta=True, with_incremental=False)
        resolved_id, meta_path, _ = resolve_resume(bid, str(tmp_path))
        assert resolved_id == bid
        assert os.path.exists(meta_path)
