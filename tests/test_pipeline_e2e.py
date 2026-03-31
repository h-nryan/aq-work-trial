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


def _mock_adjust_success(topic, task_dir, classification, pass_rate, model=None, adjustment_history=None):
    return {"status": "success"}


def _mock_regenerate_success(topic, task_dir, feedback, model=None):
    """Mock regenerate that re-writes valid files (simulating a fix)."""
    _write_valid_task(task_dir)
    return {"status": "success"}


def _mock_regenerate_fail(topic, task_dir, feedback, model=None):
    return {"status": "parse_error: mock retry failure"}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_examples(tmp_path, monkeypatch):
    """Prevent auto-promote from writing to the real examples-sonnet/ directory."""
    monkeypatch.setattr("pipeline.SONNET_EXAMPLES_DIR", str(tmp_path / "examples-sonnet-test"))


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

    def test_adjustment_history_passed_on_overshoot(self, tmp_path, monkeypatch):
        """When task oscillates too_hard → too_easy, history is passed to adjust_difficulty."""
        task_dir = str(tmp_path / "overshoot")
        captured_history = []

        def _mock_adjust_capture(topic, task_dir, classification, pass_rate,
                                 model=None, adjustment_history=None):
            captured_history.append(list(adjustment_history or []))
            return {"status": "success"}

        # First eval: too_hard. After adjustment: too_easy. After 2nd adjustment: still too_easy.
        eval_sequence = [
            {"classification": "too_hard", "passes": 0, "total": 5, "pass_rate": 0.0,
             "tier_results": {}, "recommend_early_adjust": False, "remaining_runs": 0,
             "opus_prior": {}},
            {"classification": "too_easy", "passes": 5, "total": 5, "pass_rate": 1.0,
             "tier_results": {}, "filtered_at": "sonnet",
             "recommend_early_adjust": False, "remaining_runs": 0, "opus_prior": {}},
            {"classification": "too_easy", "passes": 4, "total": 5, "pass_rate": 0.8,
             "tier_results": {}, "filtered_at": "sonnet",
             "recommend_early_adjust": False, "remaining_runs": 0, "opus_prior": {}},
        ]
        call_count = [0]
        def _mock_eval_sequence(*args, **kwargs):
            idx = min(call_count[0], len(eval_sequence) - 1)
            call_count[0] += 1
            return eval_sequence[idx]

        monkeypatch.setattr("pipeline.generate_task_solution_first", _mock_generate(task_dir))
        monkeypatch.setattr("pipeline.docker_validate", _mock_docker_validate_pass)
        monkeypatch.setattr("pipeline.evaluate_task", _mock_eval_sequence)
        monkeypatch.setattr("pipeline.adjust_difficulty", _mock_adjust_capture)

        result = run_pipeline("overshoot topic", output_dir=task_dir)

        # First adjustment: no history
        assert captured_history[0] == []
        # Second adjustment: has the too_hard round in history
        assert len(captured_history[1]) == 1
        assert captured_history[1][0][0] == "too_hard"
        assert captured_history[1][0][1] == 0.0

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


class TestWriteTaskMeta:
    """Tests for _write_task_meta topic field population."""

    def test_meta_includes_topic(self, tmp_path):
        import yaml
        from pipeline import _write_task_meta

        task_dir = str(tmp_path / "test-task")
        os.makedirs(task_dir)
        # Write a dummy file so approx_tokens > 0
        with open(os.path.join(task_dir, "main.py"), "w") as f:
            f.write("print('hello')\n")

        result = {
            "topic": "fix a Python script that crashes on empty input",
            "classification": "learnable",
            "passes": 2,
            "total": 5,
            "pass_rate": 0.4,
        }
        _write_task_meta(task_dir, result, category="debugging")

        meta = yaml.safe_load(open(os.path.join(task_dir, "_meta.yaml")))
        assert meta["topic"] == "fix a Python script that crashes on empty input"
        assert meta["classification"] == "learnable"
        assert meta["category"] == "debugging"
        assert meta["opus_passes"] == 2

    def test_meta_without_topic(self, tmp_path):
        import yaml
        from pipeline import _write_task_meta

        task_dir = str(tmp_path / "test-task")
        os.makedirs(task_dir)
        with open(os.path.join(task_dir, "main.py"), "w") as f:
            f.write("x = 1\n")

        result = {"classification": "too_hard", "passes": 0, "total": 5, "pass_rate": 0.0}
        _write_task_meta(task_dir, result)

        meta = yaml.safe_load(open(os.path.join(task_dir, "_meta.yaml")))
        assert meta["topic"] == ""  # empty but present
        assert meta["classification"] == "too_hard"

    def test_meta_not_written_without_classification(self, tmp_path):
        from pipeline import _write_task_meta

        task_dir = str(tmp_path / "test-task")
        os.makedirs(task_dir)

        result = {"topic": "some topic", "classification": None}
        _write_task_meta(task_dir, result)

        assert not os.path.exists(os.path.join(task_dir, "_meta.yaml"))


class TestAutoPromoteDedup:
    """Tests for _auto_promote duplicate prevention."""

    def test_skips_duplicate_content(self, tmp_path, monkeypatch):
        from pipeline import _auto_promote

        examples_dir = tmp_path / "examples-sonnet"
        existing = examples_dir / "existing-task"
        existing.mkdir(parents=True)
        (existing / "main.py").write_text("print('hello world')\n")
        (existing / "task.yaml").write_text("instruction: fix it\n")

        monkeypatch.setattr("pipeline.SONNET_EXAMPLES_DIR", str(examples_dir))

        # New task with identical source content
        new_task = tmp_path / "new-task-abc123"
        new_task.mkdir()
        (new_task / "main.py").write_text("print('hello world')\n")
        (new_task / "task.yaml").write_text("instruction: different wording\n")

        result = {"topic": "same topic", "classification": "learnable",
                  "passes": 1, "total": 5, "pass_rate": 0.2}
        _auto_promote(str(new_task), result)

        # Should NOT have been promoted (identical source)
        assert not (examples_dir / "new-task-abc123").exists()

    def test_promotes_different_content_same_topic(self, tmp_path, monkeypatch):
        from pipeline import _auto_promote

        examples_dir = tmp_path / "examples-sonnet"
        existing = examples_dir / "existing-task"
        existing.mkdir(parents=True)
        (existing / "main.py").write_text("print('version 1')\n")
        (existing / "task.yaml").write_text("instruction: fix it\n")

        monkeypatch.setattr("pipeline.SONNET_EXAMPLES_DIR", str(examples_dir))

        # New task with different source content but same topic
        new_task = tmp_path / "new-task-abc123"
        new_task.mkdir()
        (new_task / "main.py").write_text("def totally_different():\n    return 42\n")
        (new_task / "task.yaml").write_text("instruction: fix it\n")

        result = {"topic": "same topic", "classification": "learnable",
                  "passes": 2, "total": 5, "pass_rate": 0.4}
        _auto_promote(str(new_task), result)

        # SHOULD be promoted (different content)
        assert (examples_dir / "new-task-abc123").exists()

    def test_no_duplicate_content_in_examples_sonnet(self):
        """Validate no byte-identical tasks exist in the actual examples-sonnet/ dir."""
        from pipeline import _source_file_hash

        examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples-sonnet")
        if not os.path.isdir(examples_dir):
            pytest.skip("examples-sonnet/ not found")

        hashes = {}
        for d in sorted(os.listdir(examples_dir)):
            task_path = os.path.join(examples_dir, d)
            if os.path.isdir(task_path):
                h = _source_file_hash(task_path)
                assert h not in hashes, f"Duplicate content: {d} == {hashes[h]}"
                hashes[h] = d

    def test_promotes_new_topic(self, tmp_path, monkeypatch):
        import yaml
        from pipeline import _auto_promote

        examples_dir = tmp_path / "examples-sonnet"
        examples_dir.mkdir(parents=True)
        monkeypatch.setattr("pipeline.SONNET_EXAMPLES_DIR", str(examples_dir))

        new_task = tmp_path / "new-task-abc123"
        new_task.mkdir()
        (new_task / "task.yaml").write_text("instruction: fix it\n")

        result = {"topic": "brand new topic", "classification": "learnable",
                  "passes": 2, "total": 5, "pass_rate": 0.4}
        _auto_promote(str(new_task), result)

        assert (examples_dir / "new-task-abc123").exists()
