"""Tests for the diversity analysis module."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from diversity import (
    _infer_language,
    _jaccard_similarity,
    _normalized_entropy,
    _word_set,
    analyze_diversity,
)


class TestInferLanguage:
    def test_python(self):
        assert _infer_language("fix a broken Python script") == "python"

    def test_bash(self):
        assert _infer_language("fix a Bash deployment script") == "bash"

    def test_shell(self):
        assert _infer_language("fix a shell script issue") == "bash"

    def test_cpp(self):
        assert _infer_language("debug a C++ program") == "cpp"

    def test_c(self):
        assert _infer_language("fix a C program with memory bugs") == "c"

    def test_nodejs(self):
        assert _infer_language("fix a Node.js REST API") == "nodejs"

    def test_go(self):
        assert _infer_language("debug a Go HTTP server") == "go"

    def test_unknown(self):
        assert _infer_language("fix something") == "unknown"


class TestJaccardSimilarity:
    def test_identical(self):
        assert _jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        assert _jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial(self):
        assert _jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"}) == 0.5

    def test_empty(self):
        assert _jaccard_similarity(set(), set()) == 1.0


class TestNormalizedEntropy:
    def test_uniform(self):
        # 4 equal categories → max entropy
        result = _normalized_entropy([5, 5, 5, 5])
        assert abs(result - 1.0) < 0.01

    def test_single_category(self):
        # All in one category → 0 entropy
        result = _normalized_entropy([10])
        assert result == 0.0

    def test_skewed(self):
        # Very skewed → low entropy
        result = _normalized_entropy([100, 1, 1])
        assert result < 0.5

    def test_empty(self):
        assert _normalized_entropy([]) == 0.0


class TestAnalyzeDiversity:
    def _make_result(self, topic, category="debugging", difficulty="medium", status="completed"):
        return {
            "topic": topic,
            "status": status,
            "task_dir": None,  # No actual files
            "stages": {},
        }

    def test_basic_analysis(self):
        results = [
            self._make_result("fix a Python script"),
            self._make_result("debug a Bash tool"),
        ]
        analysis = analyze_diversity(results)
        assert analysis["total_tasks"] == 2
        assert analysis["successful_tasks"] == 2

    def test_near_duplicates_detected(self):
        results = [
            self._make_result("fix a broken Python web scraper with rate limiting"),
            self._make_result("fix a broken Python web scraper with rate limiting bugs"),
        ]
        analysis = analyze_diversity(results, similarity_threshold=0.7)
        assert len(analysis["topic_uniqueness"]["near_duplicate_pairs"]) == 1

    def test_distinct_topics_not_flagged(self):
        results = [
            self._make_result("fix a Python web scraper"),
            self._make_result("debug a C++ memory corruption issue"),
        ]
        analysis = analyze_diversity(results, similarity_threshold=0.7)
        assert len(analysis["topic_uniqueness"]["near_duplicate_pairs"]) == 0

    def test_failed_tasks_excluded(self):
        results = [
            self._make_result("fix a thing", status="completed"),
            self._make_result("fix another thing", status="generation_failed"),
        ]
        analysis = analyze_diversity(results)
        assert analysis["successful_tasks"] == 1

    def test_language_distribution(self):
        results = [
            self._make_result("fix a Python script"),
            self._make_result("fix a Python web app"),
            self._make_result("debug a Bash tool"),
        ]
        analysis = analyze_diversity(results)
        assert analysis["language_distribution"]["python"] == 2
        assert analysis["language_distribution"]["bash"] == 1

    def test_category_coverage_missing(self):
        results = [self._make_result("fix a Python script")]
        analysis = analyze_diversity(results)
        # Without task.yaml, category defaults to "unknown"
        assert len(analysis["category_coverage"]["missing"]) > 0
