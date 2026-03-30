"""End-to-end integration tests for the pipeline.

Mocks API calls and Docker but exercises the full generate → validate → evaluate
flow through run_pipeline() to catch regressions in stage wiring and control flow.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validator"))

from pipeline import run_pipeline


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_valid_task(task_dir: str) -> None:
    """Write minimal files that pass structural validation."""
    os.makedirs(os.path.join(task_dir, "tests"), exist_ok=True)

    with open(os.path.join(task_dir, "task.yaml"), "w") as f:
        f.write("instruction: Fix the bug\ndifficulty: medium\nparser_name: terminus_1\n")

    with open(os.path.join(task_dir, "Dockerfile"), "w") as f:
        f.write("FROM python:3.12-slim\nRUN echo hello\n")

    with open(os.path.join(task_dir, "run-tests.sh"), "w") as f:
        f.write("#!/bin/bash\npytest tests/\n")

    with open(os.path.join(task_dir, "solution.sh"), "w") as f:
        f.write("#!/bin/bash\necho fixed\n")

    with open(os.path.join(task_dir, "tests", "test_outputs.py"), "w") as f:
        f.write("def test_something():\n    assert True\n")


def _mock_generate(task_dir: str):
    """Return a mock generate function that writes valid fixture files."""
    def generate(topic, output_dir=None, model=None, **kwargs):
        out = output_dir or task_dir
        os.makedirs(out, exist_ok=True)
        _write_valid_task(out)
        return {
            "task_dir": out,
            "status": "success",
            "model": "mock-model",
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            "duration_sec": 0.1,
        }
    return generate


def _mock_generate_fail(topic, output_dir=None, model=None, **kwargs):
    """Mock generate that returns a failure."""
    out = output_dir or "/tmp/mock-fail"
    os.makedirs(out, exist_ok=True)
    return {
        "task_dir": out,
        "status": "parse_error: mock failure",
        "model": "mock-model",
        "usage": {},
        "duration_sec": 0.1,
    }


def _mock_docker_validate_pass(**kwargs):
    return {"passed": True, "issues": []}


def _mock_docker_validate_fail(**kwargs):
    return {"passed": False, "issues": ["Tests PASSED without solution applied"]}


def _mock_docker_validate_infra_fail(**kwargs):
    return {"passed": False, "issues": ["Docker build failed: no space left on device"]}


def _mock_evaluate_learnable(**kwargs):
    return {
        "task_dir": kwargs.get("task_dir", ""),
        "task_name": "mock-task",
        "classification": "learnable",
        "filtered_at": None,
        "passes": 2,
        "total": 5,
        "pass_rate": 0.4,
        "tier_results": {},
    }


def _mock_evaluate_too_easy(**kwargs):
    return {
        "task_dir": kwargs.get("task_dir", ""),
        "task_name": "mock-task",
        "classification": "too_easy",
        "filtered_at": "haiku",
        "passes": 5,
        "total": 5,
        "pass_rate": 1.0,
        "tier_results": {},
    }


def _mock_evaluate_too_hard(**kwargs):
    return {
        "task_dir": kwargs.get("task_dir", ""),
        "task_name": "mock-task",
        "classification": "too_hard",
        "filtered_at": None,
        "passes": 0,
        "total": 5,
        "pass_rate": 0.0,
        "tier_results": {},
    }


def _mock_adjust_success(topic, task_dir, classification, pass_rate, model=None):
    return {"status": "success"}


def _mock_regenerate_success(topic, task_dir, feedback, model=None):
    """Mock regenerate that re-writes valid files (simulating a fix)."""
    _write_valid_task(task_dir)
    return {"status": "success"}


def _mock_regenerate_fail(topic, task_dir, feedback, model=None):
    return {"status": "parse_error: mock retry failure"}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHappyPath:
    """Full pipeline: generate → structural → functional → evaluate → learnable."""

    def test_learnable_result(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "test-task")
        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_pass)
        monkeypatch.setattr("pipeline.evaluate_task", _mock_evaluate_learnable)

        result = run_pipeline("fix a test bug", output_dir=task_dir)

        assert result["status"] == "completed"
        assert result["classification"] == "learnable"
        assert result["passes"] == 2
        assert result["total"] == 5
        assert result["pass_rate"] == 0.4
        assert result["failed_stage"] is None
        assert "generate" in result["stages"]
        assert "structural" in result["stages"]
        assert "functional" in result["stages"]
        assert "evaluation" in result["stages"]

    def test_skip_functional_and_eval(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "test-task-skip")
        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))

        result = run_pipeline(
            "fix a test bug",
            output_dir=task_dir,
            skip_functional=True,
            skip_eval=True,
        )

        assert result["status"] == "completed"
        assert result["classification"] is None
        assert "functional" not in result["stages"]
        assert "evaluation" not in result["stages"]


class TestGenerationFailure:
    def test_generation_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate_fail)

        result = run_pipeline("bad topic", output_dir=str(tmp_path / "fail"))

        assert result["status"] == "generation_failed"
        assert result["failed_stage"] == "generation"
        assert result["classification"] is None


class TestStructuralValidation:
    def test_structural_failure_no_retries(self, tmp_path, monkeypatch):
        """Task missing required files fails structural validation."""
        task_dir = str(tmp_path / "bad-struct")

        def generate_bad(topic, output_dir=None, model=None, **kwargs):
            out = output_dir or task_dir
            os.makedirs(out, exist_ok=True)
            # Write incomplete task — missing Dockerfile, tests/
            with open(os.path.join(out, "task.yaml"), "w") as f:
                f.write("instruction: Fix it\ndifficulty: medium\nparser_name: terminus_1\n")
            with open(os.path.join(out, "run-tests.sh"), "w") as f:
                f.write("#!/bin/bash\n")
            return {
                "task_dir": out, "status": "success", "model": "m",
                "usage": {}, "duration_sec": 0.1,
            }

        monkeypatch.setattr("pipeline.generate_task_solution_first", generate_bad)

        result = run_pipeline("bad struct", output_dir=task_dir, max_retries=0)

        assert result["status"] == "structural_validation_failed"
        assert result["failed_stage"] == "structural"

    def test_structural_failure_with_retry_success(self, tmp_path, monkeypatch):
        """Structural failure triggers regenerate, which fixes the issue."""
        task_dir = str(tmp_path / "retry-struct")
        call_count = [0]

        def generate_first_bad(topic, output_dir=None, model=None, **kwargs):
            out = output_dir or task_dir
            os.makedirs(out, exist_ok=True)
            # Missing Dockerfile
            with open(os.path.join(out, "task.yaml"), "w") as f:
                f.write("instruction: Fix\ndifficulty: easy\nparser_name: terminus_1\n")
            with open(os.path.join(out, "run-tests.sh"), "w") as f:
                f.write("#!/bin/bash\n")
            os.makedirs(os.path.join(out, "tests"), exist_ok=True)
            with open(os.path.join(out, "tests", "test_x.py"), "w") as f:
                f.write("def test_x(): pass\n")
            return {
                "task_dir": out, "status": "success", "model": "m",
                "usage": {}, "duration_sec": 0.1,
            }

        monkeypatch.setattr("pipeline.generate_task_solution_first", generate_first_bad)
        monkeypatch.setattr("pipeline.regenerate_task", _mock_regenerate_success)
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_pass)
        monkeypatch.setattr("pipeline.evaluate_task", _mock_evaluate_learnable)

        result = run_pipeline("fix retry", output_dir=task_dir, max_retries=2)

        assert result["status"] == "completed"
        assert result["retries"] >= 1
        assert result["classification"] == "learnable"


class TestFunctionalValidation:
    def test_functional_failure_no_retries(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "func-fail")
        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_fail)

        result = run_pipeline("func fail", output_dir=task_dir, max_retries=0)

        assert result["status"] == "functional_validation_failed"
        assert result["failed_stage"] == "functional"

    def test_functional_failure_with_retry(self, tmp_path, monkeypatch):
        """Functional failure triggers regenerate, then passes on retry."""
        task_dir = str(tmp_path / "func-retry")
        call_count = [0]

        def docker_validate_eventually_passes(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"passed": False, "issues": ["Tests PASSED without solution"]}
            return {"passed": True, "issues": []}

        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", docker_validate_eventually_passes)
        monkeypatch.setattr("pipeline.regenerate_task", _mock_regenerate_success)
        monkeypatch.setattr("pipeline.evaluate_task", _mock_evaluate_learnable)

        result = run_pipeline("func retry", output_dir=task_dir, max_retries=2)

        assert result["status"] == "completed"
        assert result["retries"] >= 1

    def test_infrastructure_error_skips_retries(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "infra-fail")
        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_infra_fail)

        result = run_pipeline("infra fail", output_dir=task_dir, max_retries=3)

        assert result["status"] == "infrastructure_error"
        assert result["failed_stage"] == "functional"
        assert result["retries"] == 0  # no retries attempted


class TestEvaluation:
    def test_too_easy_triggers_adjustment(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "too-easy")
        eval_calls = [0]

        def evaluate_then_learnable(**kwargs):
            eval_calls[0] += 1
            if eval_calls[0] == 1:
                return {
                    "task_dir": task_dir, "task_name": "t",
                    "classification": "too_easy", "filtered_at": "haiku",
                    "passes": 5, "total": 5, "pass_rate": 1.0,
                    "tier_results": {},
                }
            return _mock_evaluate_learnable(**kwargs)

        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_pass)
        monkeypatch.setattr("pipeline.evaluate_task", evaluate_then_learnable)
        monkeypatch.setattr("pipeline.adjust_difficulty", _mock_adjust_success)

        result = run_pipeline("easy topic", output_dir=task_dir)

        assert result["status"] == "completed"
        assert result["classification"] == "learnable"
        assert "difficulty_adj_1" in result["stages"]

    def test_too_hard_triggers_adjustment(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "too-hard")
        eval_calls = [0]

        def evaluate_then_learnable(**kwargs):
            eval_calls[0] += 1
            if eval_calls[0] == 1:
                return _mock_evaluate_too_hard(**kwargs)
            return _mock_evaluate_learnable(**kwargs)

        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_pass)
        monkeypatch.setattr("pipeline.evaluate_task", evaluate_then_learnable)
        monkeypatch.setattr("pipeline.adjust_difficulty", _mock_adjust_success)

        result = run_pipeline("hard topic", output_dir=task_dir)

        assert result["status"] == "completed"
        assert result["classification"] == "learnable"

    def test_stays_too_hard_after_max_adjustments(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "stuck-hard")
        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_pass)
        monkeypatch.setattr("pipeline.evaluate_task", _mock_evaluate_too_hard)
        monkeypatch.setattr("pipeline.adjust_difficulty", _mock_adjust_success)

        result = run_pipeline("impossible topic", output_dir=task_dir)

        assert result["status"] == "completed"
        assert result["classification"] == "too_hard"

    def test_skip_eval(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "skip-eval")
        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_pass)

        result = run_pipeline("skip eval", output_dir=task_dir, skip_eval=True)

        assert result["status"] == "completed"
        assert result["classification"] is None
        assert "evaluation" not in result["stages"]


class TestRetryRegenFailure:
    """Regeneration failing during retry should exit cleanly."""

    def test_structural_retry_regen_fails(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "regen-fail")

        def generate_bad(topic, output_dir=None, model=None, **kwargs):
            out = output_dir or task_dir
            os.makedirs(out, exist_ok=True)
            # Missing everything except task.yaml
            with open(os.path.join(out, "task.yaml"), "w") as f:
                f.write("instruction: X\ndifficulty: hard\nparser_name: terminus_1\n")
            return {
                "task_dir": out, "status": "success", "model": "m",
                "usage": {}, "duration_sec": 0.1,
            }

        monkeypatch.setattr("pipeline.generate_task_solution_first", generate_bad)
        monkeypatch.setattr("pipeline.regenerate_task", _mock_regenerate_fail)

        result = run_pipeline("regen fail", output_dir=task_dir, max_retries=1)

        assert result["status"] == "retry_generation_failed"
        assert result["failed_stage"] == "structural"

    def test_functional_retry_regen_fails(self, tmp_path, monkeypatch):
        task_dir = str(tmp_path / "func-regen-fail")
        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_fail)
        monkeypatch.setattr("pipeline.regenerate_task", _mock_regenerate_fail)

        result = run_pipeline("func regen fail", output_dir=task_dir, max_retries=1)

        assert result["status"] == "retry_generation_failed"
        assert result["failed_stage"] == "functional"
