"""Tests for analyze.py — post-classification task analysis."""

from __future__ import annotations

import os
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from analyze import (
    _classify_hunk,
    _classify_single_line_change,
    _lines_similar,
    analyze_code_structure,
    analyze_diff_locality,
    analyze_instruction,
    analyze_patterns,
    analyze_task,
    analyze_tests,
    extract_bug_types,
)


@pytest.fixture
def task_with_bugs(tmp_path):
    """Create a task with known buggy source and solution."""
    (tmp_path / "task.yaml").write_text(yaml.dump({
        "instruction": "Fix the broken add() and multiply() functions in math_utils.py",
        "difficulty": "medium",
        "parser_name": "pytest",
    }))
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\nWORKDIR /app\n")
    (tmp_path / "run-tests.sh").write_text("pytest tests/\n")

    # Buggy source
    (tmp_path / "math_utils.py").write_text(
        "def add(a, b):\n"
        "    return a - b\n"
        "\n"
        "def multiply(a, b):\n"
        "    return a + b\n"
        "\n"
        "def divide(a, b):\n"
        "    return a / b\n"
    )

    # Solution fixes two bugs
    (tmp_path / "solution.sh").write_text(
        "#!/bin/bash\n"
        "cat > /app/math_utils.py << 'EOF'\n"
        "def add(a, b):\n"
        "    return a + b\n"
        "\n"
        "def multiply(a, b):\n"
        "    return a * b\n"
        "\n"
        "def divide(a, b):\n"
        "    return a / b\n"
        "EOF\n"
    )

    # Test file
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_outputs.py").write_text(
        "def test_add_positive():\n"
        '    """Test adding two positive numbers."""\n'
        "    from math_utils import add\n"
        "    assert add(2, 3) == 5\n"
        "\n"
        "def test_multiply_basics():\n"
        '    """Test basic multiplication."""\n'
        "    from math_utils import multiply\n"
        "    assert multiply(4, 5) == 20\n"
        "    assert multiply(0, 5) == 0\n"
        "\n"
        "def test_divide():\n"
        "    from math_utils import divide\n"
        "    assert divide(10, 2) == 5.0\n"
    )

    return tmp_path


class TestClassifySingleLineChange:
    def test_wrong_operator(self):
        assert _classify_single_line_change(
            "    return a - b", "    return a + b"
        ) == "wrong_operator"

    def test_off_by_one_comparison(self):
        assert _classify_single_line_change(
            "    if x < 10:", "    if x <= 10:"
        ) == "off_by_one"

    def test_off_by_one_number(self):
        assert _classify_single_line_change(
            "    return data[n]", "    return data[n-1]"
        ) == "off_by_one"

    def test_wrong_variable(self):
        assert _classify_single_line_change(
            "    return width * width", "    return width * height"
        ) == "wrong_variable"

    def test_wrong_constant_string(self):
        assert _classify_single_line_change(
            '    delimiter = ";"', '    delimiter = ","'
        ) == "wrong_constant"

    def test_missing_edge_case(self):
        assert _classify_single_line_change(
            "    result = process(data)",
            "    if data is None: return None"
        ) == "missing_edge_case"


class TestClassifyHunk:
    def test_missing_code(self):
        assert _classify_hunk([], ["    return None"]) == "missing_code"

    def test_extra_code(self):
        assert _classify_hunk(["    debug_print(x)"], []) == "extra_code"

    def test_single_line_delegates(self):
        result = _classify_hunk(["    return a - b"], ["    return a + b"])
        assert result == "wrong_operator"


class TestLinesSimilar:
    def test_similar_lines(self):
        assert _lines_similar("return a + b", "return a - b", threshold=0.5)

    def test_dissimilar_lines(self):
        assert not _lines_similar("import os", "def hello(): pass", threshold=0.5)

    def test_empty_lines(self):
        assert not _lines_similar("", "", threshold=0.5)


class TestExtractBugTypes:
    def test_extracts_bugs_from_diff(self, task_with_bugs):
        bugs = extract_bug_types(str(task_with_bugs))
        assert len(bugs) == 2
        assert all(b["filename"] == "math_utils.py" for b in bugs)

    def test_no_solution_returns_empty(self, tmp_path):
        assert extract_bug_types(str(tmp_path)) == []


class TestAnalyzeTests:
    def test_counts_tests(self, task_with_bugs):
        result = analyze_tests(str(task_with_bugs))
        assert result["test_count"] == 3

    def test_detects_docstrings(self, task_with_bugs):
        result = analyze_tests(str(task_with_bugs))
        assert result["has_docstrings"] == 2  # test_add and test_multiply have docstrings

    def test_descriptive_names(self, task_with_bugs):
        result = analyze_tests(str(task_with_bugs))
        assert result["descriptive_names"] == 2  # add_positive, multiply_basics

    def test_no_tests_dir(self, tmp_path):
        result = analyze_tests(str(tmp_path))
        assert result["test_count"] == 0


class TestAnalyzeCodeStructure:
    def test_counts_functions(self, task_with_bugs):
        result = analyze_code_structure(str(task_with_bugs))
        assert result["function_count"] == 3  # add, multiply, divide
        assert result["language"] == "python"

    def test_counts_loc(self, task_with_bugs):
        result = analyze_code_structure(str(task_with_bugs))
        assert result["total_loc"] > 0

    def test_source_file_count(self, task_with_bugs):
        result = analyze_code_structure(str(task_with_bugs))
        assert result["source_file_count"] == 1  # math_utils.py only


class TestAnalyzeInstruction:
    def test_word_count(self, task_with_bugs):
        result = analyze_instruction(str(task_with_bugs))
        assert result["word_count"] > 0

    def test_mentions_files(self, task_with_bugs):
        result = analyze_instruction(str(task_with_bugs))
        assert result["mentions_files"] is True  # math_utils.py

    def test_mentions_functions(self, task_with_bugs):
        result = analyze_instruction(str(task_with_bugs))
        assert result["mentions_functions"] is True  # add() and multiply()

    def test_no_task_yaml(self, tmp_path):
        result = analyze_instruction(str(tmp_path))
        assert result["specificity"] == "unknown"


class TestAnalyzeDiffLocality:
    def test_two_hunks_spread(self, task_with_bugs):
        result = analyze_diff_locality(str(task_with_bugs))
        assert "spread_ratio" in result
        assert result["spread_ratio"] > 0

    def test_no_solution(self, tmp_path):
        result = analyze_diff_locality(str(tmp_path))
        assert result == {}


class TestAnalyzeTask:
    def test_full_analysis(self, task_with_bugs):
        result = analyze_task(str(task_with_bugs))
        assert result["bug_count"] == 2
        assert result["tests"]["test_count"] == 3
        assert result["structure"]["function_count"] == 3
        assert result["instruction"]["word_count"] > 0
        assert "bug_type_summary" in result


class TestAnalyzePatterns:
    def test_finds_bug_count_difference(self):
        learnable = [{"bug_count": 3, "structure": {"total_loc": 100, "language": "python"},
                       "diff": {"files_changed": 1, "total_hunks": 3, "total_lines_changed": 20},
                       "tests": {"test_count": 5}, "instruction": {"word_count": 100},
                       "locality": {"spread_ratio": 0.5}, "bug_type_summary": {"wrong_operator": 3}}]
        too_hard = [{"bug_count": 8, "structure": {"total_loc": 300, "language": "python"},
                      "diff": {"files_changed": 3, "total_hunks": 8, "total_lines_changed": 80},
                      "tests": {"test_count": 10}, "instruction": {"word_count": 200},
                      "locality": {"spread_ratio": 0.9}, "bug_type_summary": {"logic_change": 8}}]

        result = analyze_patterns({"learnable": learnable, "too_hard": too_hard})
        assert result["per_group"]["learnable"]["avg_bug_count"] == 3
        assert result["per_group"]["too_hard"]["avg_bug_count"] == 8
        assert len(result["findings"]) > 0
        assert any("bug" in f.lower() or "file" in f.lower() for f in result["findings"])

    def test_empty_groups(self):
        result = analyze_patterns({"learnable": [], "too_hard": []})
        assert result["findings"] == []
