"""Tests for the Docker-based functional validator (unit tests, no Docker needed)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validator"))

from docker_validate import _sanity_checks, docker_validate


@pytest.fixture
def good_task(tmp_path):
    """Create a minimal valid task directory for sanity check tests."""
    (tmp_path / "task.yaml").write_text(yaml.dump({
        "instruction": "Fix the broken Python script that crashes when processing large CSV files with unicode characters and missing headers",
        "difficulty": "medium",
        "parser_name": "pytest",
    }))
    (tmp_path / "Dockerfile").write_text("FROM ubuntu:24.04\nWORKDIR /app\n")
    (tmp_path / "run-tests.sh").write_text("#!/bin/bash\npytest tests/ -v\n")
    (tmp_path / "solution.sh").write_text("#!/bin/bash\ncat > fixed.py << 'EOF'\nprint('fixed')\nEOF\n")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_outputs.py").write_text("def test_pass(): assert True\n")
    return tmp_path


class TestSanityChecks:
    """Tests for _sanity_checks (pre-Docker validation)."""

    def test_good_task_no_issues(self, good_task):
        issues = _sanity_checks(good_task)
        assert issues == []

    def test_short_instruction_flagged(self, good_task):
        (good_task / "task.yaml").write_text(yaml.dump({
            "instruction": "Fix it",
            "difficulty": "easy",
            "parser_name": "pytest",
        }))
        issues = _sanity_checks(good_task)
        assert any("too short" in i for i in issues)

    def test_empty_solution_flagged(self, good_task):
        (good_task / "solution.sh").write_text("")
        issues = _sanity_checks(good_task)
        assert any("solution.sh" in i and "too small" in i for i in issues)

    def test_empty_run_tests_flagged(self, good_task):
        (good_task / "run-tests.sh").write_text("#!/bin/b")
        issues = _sanity_checks(good_task)
        assert any("run-tests.sh" in i and "too small" in i for i in issues)

    def test_missing_task_yaml(self, good_task):
        (good_task / "task.yaml").unlink()
        issues = _sanity_checks(good_task)
        assert any("task.yaml" in i for i in issues)

    def test_50_char_instruction_passes(self, good_task):
        (good_task / "task.yaml").write_text(yaml.dump({
            "instruction": "x" * 50,
            "difficulty": "easy",
            "parser_name": "pytest",
        }))
        issues = _sanity_checks(good_task)
        assert issues == []

    def test_49_char_instruction_fails(self, good_task):
        (good_task / "task.yaml").write_text(yaml.dump({
            "instruction": "x" * 49,
            "difficulty": "easy",
            "parser_name": "pytest",
        }))
        issues = _sanity_checks(good_task)
        assert any("too short" in i for i in issues)


class TestDockerValidatePreflightOnly:
    """Tests for docker_validate that don't need Docker.

    These test early-exit paths: missing directories, missing files, sanity failures.
    """

    def test_nonexistent_dir(self):
        result = docker_validate("/nonexistent/dir")
        assert result["passed"] is False
        assert any("not found" in i for i in result["issues"])
        assert result["image_builds"] is False

    def test_missing_required_files(self, tmp_path):
        # Empty directory — missing everything
        result = docker_validate(str(tmp_path))
        assert result["passed"] is False
        assert any("Missing" in i for i in result["issues"])

    def test_sanity_check_failure_skips_docker(self, good_task):
        # Make instruction too short — should fail before Docker
        (good_task / "task.yaml").write_text(yaml.dump({
            "instruction": "Fix",
            "difficulty": "easy",
            "parser_name": "pytest",
        }))
        result = docker_validate(str(good_task))
        assert result["passed"] is False
        assert any("too short" in i for i in result["issues"])
        # Should not have attempted Docker build
        assert result["image_builds"] is False

    def test_result_structure(self, good_task):
        # Even on failure, all expected keys should be present
        (good_task / "solution.sh").write_text("")  # trigger sanity failure
        result = docker_validate(str(good_task))
        assert "passed" in result
        assert "image_builds" in result
        assert "tests_fail_without_solution" in result
        assert "tests_pass_with_solution" in result
        assert "solution_idempotent" in result
        assert "tests_deterministic" in result
        assert "issues" in result
        assert "warnings" in result
        assert "details" in result
        assert "execution_times" in result
