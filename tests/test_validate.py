"""Tests for the structural validator."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validator"))

from validate import validate_task


@pytest.fixture
def good_task(tmp_path):
    """Create a minimal valid task directory."""
    (tmp_path / "task.yaml").write_text(yaml.dump({
        "instruction": "Fix the broken script",
        "difficulty": "medium",
        "parser_name": "pytest",
    }))
    (tmp_path / "Dockerfile").write_text("FROM ubuntu:24.04\nWORKDIR /app\n")
    (tmp_path / "run-tests.sh").write_text("#!/bin/bash\npytest tests/\n")
    (tmp_path / "solution.sh").write_text("#!/bin/bash\necho fixed\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_outputs.py").write_text("def test_pass(): assert True\n")
    return tmp_path


class TestValidateTask:
    """Tests for validate_task."""

    def test_valid_task_passes(self, good_task):
        result = validate_task(str(good_task))
        assert result["passed"] is True
        assert result["issues"] == []

    def test_nonexistent_dir_fails(self):
        result = validate_task("/nonexistent/path")
        assert result["passed"] is False
        assert any("does not exist" in i for i in result["issues"])

    def test_missing_task_yaml(self, good_task):
        (good_task / "task.yaml").unlink()
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("task.yaml" in i for i in result["issues"])

    def test_missing_dockerfile(self, good_task):
        (good_task / "Dockerfile").unlink()
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("Dockerfile" in i for i in result["issues"])

    def test_missing_run_tests(self, good_task):
        (good_task / "run-tests.sh").unlink()
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("run-tests.sh" in i for i in result["issues"])

    def test_missing_tests_dir(self, good_task):
        import shutil
        shutil.rmtree(good_task / "tests")
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("tests/" in i for i in result["issues"])

    def test_empty_tests_dir(self, good_task):
        (good_task / "tests" / "test_outputs.py").unlink()
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("No .py" in i for i in result["issues"])

    def test_invalid_difficulty(self, good_task):
        (good_task / "task.yaml").write_text(yaml.dump({
            "instruction": "Fix it",
            "difficulty": "nightmare",
            "parser_name": "pytest",
        }))
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("difficulty" in i for i in result["issues"])

    def test_missing_yaml_field(self, good_task):
        (good_task / "task.yaml").write_text(yaml.dump({
            "instruction": "Fix it",
            "difficulty": "easy",
            # missing parser_name
        }))
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("parser_name" in i for i in result["issues"])

    def test_dockerfile_missing_from(self, good_task):
        (good_task / "Dockerfile").write_text("RUN echo hello\n")
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("FROM" in i for i in result["issues"])

    def test_malformed_yaml(self, good_task):
        (good_task / "task.yaml").write_text("{{invalid yaml: [")
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("parse error" in i for i in result["issues"])
