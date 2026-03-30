"""Tests for evaluate.py — tiered evaluation logic, early stopping, and cleanup."""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from evaluate import (
    _build_result,
    _cleanup_stale_containers,
    _cleanup_stale_tb_processes,
    _kill_containers_for_task,
    _parse_run_results,
    _run_filter_tier,
    cleanup_stale_resources,
    evaluate_task,
)


class TestCleanupStaleContainers:
    def _mock_docker_ps(self, monkeypatch, lines: list[str], now: float | None = None):
        """Mock docker ps to return the given lines."""
        output = "\n".join(lines) + "\n" if lines else ""

        def fake_run(cmd, **kwargs):
            if cmd[0] == "docker" and cmd[1] == "ps":
                return type("R", (), {"returncode": 0, "stdout": output, "stderr": ""})()
            if cmd[0] == "docker" and cmd[1] == "kill":
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("evaluate.subprocess.run", fake_run)
        if now is not None:
            monkeypatch.setattr("evaluate.time.time", lambda: now)

    def test_no_containers(self, monkeypatch):
        self._mock_docker_ps(monkeypatch, [])
        assert _cleanup_stale_containers() == 0

    def test_fresh_containers_not_killed(self, monkeypatch):
        now = time.time()
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 60))
        self._mock_docker_ps(monkeypatch, [f"abc123 {ts} -0700 PDT"], now=now)
        assert _cleanup_stale_containers(max_age_sec=1200) == 0

    def test_stale_containers_killed(self, monkeypatch):
        now = time.time()
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 2000))
        killed_ids = []

        def fake_run(cmd, **kwargs):
            if cmd[0] == "docker" and cmd[1] == "ps":
                output = f"abc123 {ts} -0700 PDT\ndef456 {ts} -0700 PDT\n"
                return type("R", (), {"returncode": 0, "stdout": output, "stderr": ""})()
            if cmd[0] == "docker" and cmd[1] == "kill":
                killed_ids.append(cmd[2])
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("evaluate.subprocess.run", fake_run)
        monkeypatch.setattr("evaluate.time.time", lambda: now)

        assert _cleanup_stale_containers(max_age_sec=1200) == 2
        assert set(killed_ids) == {"abc123", "def456"}

    def test_docker_not_available(self, monkeypatch):
        """Gracefully handles missing docker."""
        monkeypatch.setattr(
            "evaluate.subprocess.run",
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("docker")),
        )
        assert _cleanup_stale_containers() == 0

    def test_mixed_ages(self, monkeypatch):
        now = time.time()
        fresh_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 60))
        stale_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 2000))
        killed_ids = []

        def fake_run(cmd, **kwargs):
            if cmd[0] == "docker" and cmd[1] == "ps":
                output = f"fresh1 {fresh_ts} -0700 PDT\nstale1 {stale_ts} -0700 PDT\n"
                return type("R", (), {"returncode": 0, "stdout": output, "stderr": ""})()
            if cmd[0] == "docker" and cmd[1] == "kill":
                killed_ids.append(cmd[2])
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("evaluate.subprocess.run", fake_run)
        monkeypatch.setattr("evaluate.time.time", lambda: now)

        assert _cleanup_stale_containers(max_age_sec=1200) == 1
        assert killed_ids == ["stale1"]


class TestCleanupStaleProcesses:
    def _mock_ps(self, monkeypatch, lines: list[str]):
        """Mock ps output. Lines should be 'PID ELAPSED_SEC COMMAND'."""
        header = "  PID ELAPSED COMMAND\n"
        output = header + "\n".join(lines) + "\n"

        def fake_run(cmd, **kwargs):
            if cmd[0] == "ps":
                return type("R", (), {"returncode": 0, "stdout": output, "stderr": ""})()
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("evaluate.subprocess.run", fake_run)

    def test_no_stale_processes(self, monkeypatch):
        self._mock_ps(monkeypatch, [
            "12345 60 tb run --dataset eval-task-1",
        ])
        assert _cleanup_stale_tb_processes(max_age_sec=1200) == 0

    def test_stale_tb_run_killed(self, monkeypatch):
        killed_pids = []
        self._mock_ps(monkeypatch, [
            "12345 5000 /usr/bin/python tb run --dataset eval-task-1",
        ])
        monkeypatch.setattr("evaluate.os.kill", lambda pid, sig: killed_pids.append(pid))
        # Don't kill ourselves
        monkeypatch.setattr("evaluate.os.getpid", lambda: 99999)
        monkeypatch.setattr("evaluate.os.getppid", lambda: 99998)

        assert _cleanup_stale_tb_processes(max_age_sec=1200) == 1
        assert killed_pids == [12345]

    def test_stale_eval_parent_killed(self, monkeypatch):
        killed_pids = []
        self._mock_ps(monkeypatch, [
            '54321 5000 python -c from evaluate import evaluate_task',
        ])
        monkeypatch.setattr("evaluate.os.kill", lambda pid, sig: killed_pids.append(pid))
        monkeypatch.setattr("evaluate.os.getpid", lambda: 99999)
        monkeypatch.setattr("evaluate.os.getppid", lambda: 99998)

        assert _cleanup_stale_tb_processes(max_age_sec=1200) == 1
        assert killed_pids == [54321]

    def test_own_pid_not_killed(self, monkeypatch):
        killed_pids = []
        my_pid = os.getpid()
        self._mock_ps(monkeypatch, [
            f"{my_pid} 5000 python -c from evaluate import evaluate_task",
        ])
        monkeypatch.setattr("evaluate.os.kill", lambda pid, sig: killed_pids.append(pid))

        assert _cleanup_stale_tb_processes(max_age_sec=1200) == 0
        assert killed_pids == []

    def test_non_eval_processes_not_killed(self, monkeypatch):
        killed_pids = []
        self._mock_ps(monkeypatch, [
            "12345 5000 python some_other_script.py",
            "12346 5000 /usr/sbin/httpd",
        ])
        monkeypatch.setattr("evaluate.os.kill", lambda pid, sig: killed_pids.append(pid))
        monkeypatch.setattr("evaluate.os.getpid", lambda: 99999)
        monkeypatch.setattr("evaluate.os.getppid", lambda: 99998)

        assert _cleanup_stale_tb_processes(max_age_sec=1200) == 0

    def test_ps_not_available(self, monkeypatch):
        monkeypatch.setattr(
            "evaluate.subprocess.run",
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("ps")),
        )
        assert _cleanup_stale_tb_processes() == 0


class TestCleanupStaleResources:
    def test_combines_both_cleanups(self, monkeypatch):
        monkeypatch.setattr("evaluate._cleanup_stale_containers", lambda max_age_sec: 2)
        monkeypatch.setattr("evaluate._cleanup_stale_tb_processes", lambda max_age_sec: 3)
        assert cleanup_stale_resources() == 5


class TestKillContainersForTask:
    def test_kills_matching_containers(self, monkeypatch):
        killed_ids = []

        def fake_run(cmd, **kwargs):
            if cmd[0] == "docker" and cmd[1] == "ps":
                output = (
                    "abc123 my-task-abc-1-of-3-eval-run\n"
                    "def456 my-task-abc-2-of-3-eval-run\n"
                    "ghi789 other-task-xyz-1-of-3-eval-run\n"
                )
                return type("R", (), {"returncode": 0, "stdout": output, "stderr": ""})()
            if cmd[0] == "docker" and cmd[1] == "kill":
                killed_ids.append(cmd[2])
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("evaluate.subprocess.run", fake_run)
        assert _kill_containers_for_task("my-task-abc") == 2
        assert sorted(killed_ids) == ["abc123", "def456"]

    def test_no_matching_containers(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            if cmd[0] == "docker" and cmd[1] == "ps":
                output = "abc123 other-task-1-of-3-eval-run\n"
                return type("R", (), {"returncode": 0, "stdout": output, "stderr": ""})()
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("evaluate.subprocess.run", fake_run)
        assert _kill_containers_for_task("nonexistent-task") == 0

    def test_docker_ps_failure(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "error"})()

        monkeypatch.setattr("evaluate.subprocess.run", fake_run)
        assert _kill_containers_for_task("any-task") == 0

    def test_docker_ps_timeout(self, monkeypatch):
        import subprocess

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 10)

        monkeypatch.setattr("evaluate.subprocess.run", fake_run)
        assert _kill_containers_for_task("any-task") == 0


class TestRunTbTimeoutCleanup:
    """Verify that _run_tb kills orphaned containers on timeout."""

    def test_timeout_kills_containers(self, monkeypatch, tmp_path):
        """When subprocess.run raises TimeoutExpired, _kill_containers_for_task is called."""
        import subprocess as sp

        from evaluate import _run_tb

        killed_task_ids = []

        def fake_subprocess_run(cmd, **kwargs):
            raise sp.TimeoutExpired(cmd, 1)

        def fake_kill_containers(task_id):
            killed_task_ids.append(task_id)
            return 1

        monkeypatch.setattr("evaluate.subprocess.run", fake_subprocess_run)
        monkeypatch.setattr("evaluate._kill_containers_for_task", fake_kill_containers)
        monkeypatch.setattr("evaluate.cleanup_stale_resources", lambda: 0)

        task_dir = tmp_path / "my-test-task"
        task_dir.mkdir()

        result = _run_tb(str(task_dir), "anthropic/claude-opus-4", timeout_sec=0.001)
        assert result["status"] == "timeout"
        assert result["passes"] == 0
        assert killed_task_ids == ["my-test-task"]


class TestParseRunResults:
    def test_no_results_dir(self, tmp_path):
        result = _parse_run_results(tmp_path / "nonexistent", "task-1", 5, 10.0)
        assert result["passes"] == 0
        assert result["status"] == "no_results"

    def test_empty_results_dir(self, tmp_path):
        task_dir = tmp_path / "run-1" / "task-1"
        task_dir.mkdir(parents=True)
        result = _parse_run_results(tmp_path / "run-1", "task-1", 5, 10.0)
        assert result["passes"] == 0
        assert result["total"] == 5

    def test_mixed_results(self, tmp_path):
        import json
        run_dir = tmp_path / "run-1"
        task_dir = run_dir / "task-1"

        for i, resolved in enumerate([True, False, True, False, False]):
            trial_dir = task_dir / f"trial-{i}"
            trial_dir.mkdir(parents=True)
            (trial_dir / "results.json").write_text(
                json.dumps({"is_resolved": resolved})
            )

        result = _parse_run_results(run_dir, "task-1", 5, 25.0)
        assert result["passes"] == 2
        assert result["total"] == 5
        assert result["status"] == "completed"
        assert result["duration_sec"] == 25.0

    def test_corrupt_results_file(self, tmp_path):
        run_dir = tmp_path / "run-1"
        trial_dir = run_dir / "task-1" / "trial-0"
        trial_dir.mkdir(parents=True)
        (trial_dir / "results.json").write_text("not json")

        result = _parse_run_results(run_dir, "task-1", 1, 5.0)
        assert result["passes"] == 0
        assert result["total"] == 1
        assert "parse_error" in result["trials"][0]["status"]


# ── Helpers for tiered evaluation tests ───────────────────────────────────────

def _make_tb_result(passes: int, total: int) -> dict:
    """Build a mock _run_tb return value."""
    return {
        "passes": passes,
        "total": total,
        "duration_sec": 1.0,
        "status": "completed",
        "trials": [],
    }


class _MockRunTb:
    """Configurable mock for _run_tb that returns results from a sequence.

    Each call pops the next result from the sequence. Tracks call count
    and the n_attempts passed to each call.
    """
    def __init__(self, results: list[dict]):
        self._results = list(results)
        self._idx = 0
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._idx < len(self._results):
            r = self._results[self._idx]
            self._idx += 1
            return r
        return _make_tb_result(0, kwargs.get("n_attempts", 1))


def _mock_cleanup(monkeypatch):
    """Disable stale resource cleanup in tests."""
    monkeypatch.setattr("evaluate.cleanup_stale_resources", lambda: 0)


# ── Filter tier tests ────────────────────────────────────────────────────────

class TestRunFilterTier:
    """Tests for _run_filter_tier early stopping logic."""

    def test_all_pass_parallel_batch_early_stops(self, tmp_path, monkeypatch):
        """3/3 pass with threshold 4 and 5 total → can still reach 4, needs sequential."""
        mock = _MockRunTb([
            _make_tb_result(3, 3),  # parallel batch: 3/3
            _make_tb_result(1, 1),  # sequential run 4: pass → 4/4 >= threshold
        ])
        monkeypatch.setattr("evaluate._run_tb", mock)
        _mock_cleanup(monkeypatch)

        result = _run_filter_tier(
            task_dir=str(tmp_path), model="test-model",
            model_label="Test", n_runs=5, skip_threshold=4,
        )
        assert result["should_skip"] is True
        assert result["passes"] == 4
        assert result["early_stopped"] is True
        assert len(mock.calls) == 2  # batch + 1 sequential, saved 1

    def test_zero_pass_batch_early_stops(self, tmp_path, monkeypatch):
        """0/3 pass with threshold 4, 2 remaining → can't reach 4 → proceed immediately."""
        mock = _MockRunTb([_make_tb_result(0, 3)])
        monkeypatch.setattr("evaluate._run_tb", mock)
        _mock_cleanup(monkeypatch)

        result = _run_filter_tier(
            task_dir=str(tmp_path), model="test-model",
            model_label="Test", n_runs=5, skip_threshold=4,
        )
        assert result["should_skip"] is False
        assert result["passes"] == 0
        assert result["early_stopped"] is True
        assert len(mock.calls) == 1  # only the parallel batch

    def test_full_run_no_early_stop(self, tmp_path, monkeypatch):
        """2/3 batch, then 1/1, 0/1 → 3/5 < threshold 4 → proceed, no early stop possible."""
        mock = _MockRunTb([
            _make_tb_result(2, 3),  # parallel: 2/3
            _make_tb_result(1, 1),  # seq run 4: 3/4, remaining 1, could reach 4
            _make_tb_result(0, 1),  # seq run 5: 3/5 < 4
        ])
        monkeypatch.setattr("evaluate._run_tb", mock)
        _mock_cleanup(monkeypatch)

        result = _run_filter_tier(
            task_dir=str(tmp_path), model="test-model",
            model_label="Test", n_runs=5, skip_threshold=4,
        )
        assert result["should_skip"] is False
        assert result["passes"] == 3
        assert result["total"] == 5
        assert result["early_stopped"] is False
        assert len(mock.calls) == 3

    def test_threshold_exactly_met(self, tmp_path, monkeypatch):
        """Passes exactly reach skip_threshold → should_skip."""
        mock = _MockRunTb([
            _make_tb_result(2, 3),
            _make_tb_result(1, 1),
            _make_tb_result(1, 1),
        ])
        monkeypatch.setattr("evaluate._run_tb", mock)
        _mock_cleanup(monkeypatch)

        result = _run_filter_tier(
            task_dir=str(tmp_path), model="test-model",
            model_label="Test", n_runs=5, skip_threshold=4,
        )
        assert result["should_skip"] is True
        assert result["passes"] == 4

    def test_small_n_runs_no_sequential(self, tmp_path, monkeypatch):
        """n_runs <= 3 means only the parallel batch, no sequential phase."""
        mock = _MockRunTb([_make_tb_result(2, 3)])
        monkeypatch.setattr("evaluate._run_tb", mock)
        _mock_cleanup(monkeypatch)

        result = _run_filter_tier(
            task_dir=str(tmp_path), model="test-model",
            model_label="Test", n_runs=3, skip_threshold=3,
        )
        assert result["should_skip"] is False
        assert result["total"] == 3
        assert len(mock.calls) == 1


# ── evaluate_task orchestration tests ─────────────────────────────────────────

class TestEvaluateTask:
    """Tests for the full tiered evaluation pipeline."""

    def _mock_filter_tier(self, monkeypatch, haiku_result=None, sonnet_result=None):
        """Mock _run_filter_tier to return preconfigured results per model label."""
        results = {}
        if haiku_result:
            results["Haiku"] = haiku_result
        if sonnet_result:
            results["Sonnet"] = sonnet_result

        def fake_filter_tier(task_dir, model, model_label, n_runs, skip_threshold, **kw):
            return results.get(model_label, {
                "model": model, "model_label": model_label,
                "passes": 0, "total": n_runs, "skip_threshold": skip_threshold,
                "should_skip": False, "early_stopped": False, "results": [],
            })

        monkeypatch.setattr("evaluate._run_filter_tier", fake_filter_tier)

    def _make_filter_result(self, model_label, passes, total, skip_threshold, should_skip):
        return {
            "model": "test-model", "model_label": model_label,
            "passes": passes, "total": total,
            "skip_threshold": skip_threshold, "should_skip": should_skip,
            "early_stopped": False, "results": [],
        }

    def test_haiku_filters_too_easy(self, tmp_path, monkeypatch):
        """Haiku 5/5 → too_easy, never reaches Sonnet or Opus."""
        _mock_cleanup(monkeypatch)
        self._mock_filter_tier(monkeypatch,
            haiku_result=self._make_filter_result("Haiku", 5, 5, 4, True),
        )

        result = evaluate_task(
            str(tmp_path), skip_haiku=False, skip_sonnet=False,
        )
        assert result["classification"] == "too_easy"
        assert result["filtered_at"] == "haiku"
        assert "haiku" in result["tier_results"]
        assert "sonnet" not in result["tier_results"]
        assert "opus" not in result["tier_results"]

    def test_sonnet_filters_too_easy(self, tmp_path, monkeypatch):
        """Haiku 1/5, Sonnet 4/5 → too_easy at Sonnet, never reaches Opus."""
        _mock_cleanup(monkeypatch)
        self._mock_filter_tier(monkeypatch,
            haiku_result=self._make_filter_result("Haiku", 1, 5, 4, False),
            sonnet_result=self._make_filter_result("Sonnet", 4, 5, 4, True),
        )

        result = evaluate_task(
            str(tmp_path), skip_haiku=False, skip_sonnet=False,
        )
        assert result["classification"] == "too_easy"
        assert result["filtered_at"] == "sonnet"
        assert "haiku" in result["tier_results"]
        assert "sonnet" in result["tier_results"]
        assert "opus" not in result["tier_results"]

    def test_reaches_opus_learnable(self, tmp_path, monkeypatch):
        """Sonnet 2/5 → proceed to Opus. Opus 2/3 batch → learnable (early stop)."""
        _mock_cleanup(monkeypatch)
        self._mock_filter_tier(monkeypatch,
            sonnet_result=self._make_filter_result("Sonnet", 2, 5, 4, False),
        )
        # Opus batch: 2/3 passes, remaining=2, max possible=4 → can't exceed LEARNABLE_MAX(3)
        # with passes=2, remaining=2, passes+remaining=4 > LEARNABLE_MAX → undecided
        # Actually: 2 passes, remaining 2 → passes(2) + remaining(2) = 4 > 3 → can't confirm
        # Need to think about _can_stop:
        #   passes >= LEARNABLE_MIN(1) and passes + remaining <= LEARNABLE_MAX(3)
        #   2 >= 1 ✓ but 2 + 2 = 4 > 3 → not learnable yet
        # So we need sequential runs. Let's make it 2/3 batch then 0/1 seq:
        #   passes=2, remaining=1 → 2+1=3 <= 3 → learnable!
        mock = _MockRunTb([
            _make_tb_result(2, 3),  # Opus parallel batch: 2/3
            _make_tb_result(0, 1),  # Opus sequential: 2/4, remaining=1, 2+1=3 <=3 → learnable
        ])
        monkeypatch.setattr("evaluate._run_tb", mock)

        result = evaluate_task(str(tmp_path), skip_haiku=True)
        assert result["classification"] == "learnable"
        assert result["filtered_at"] is None
        assert result["passes"] == 2
        assert "opus" in result["tier_results"]

    def test_reaches_opus_too_hard(self, tmp_path, monkeypatch):
        """Sonnet 0/5 → Opus 0/3 batch, 0/1 seq, 0/1 seq → 0/5 → too_hard."""
        _mock_cleanup(monkeypatch)
        self._mock_filter_tier(monkeypatch,
            sonnet_result=self._make_filter_result("Sonnet", 0, 5, 4, False),
        )
        # _can_stop(0, 2) → 0+2=2 >= 1 → not too_hard yet
        # _can_stop(0, 1) → 0+1=1 >= 1 → not too_hard yet
        # _can_stop(0, 0) → 0+0=0 < 1 → too_hard
        mock = _MockRunTb([
            _make_tb_result(0, 3),  # batch: 0/3
            _make_tb_result(0, 1),  # seq: 0/4
            _make_tb_result(0, 1),  # seq: 0/5 → too_hard
        ])
        monkeypatch.setattr("evaluate._run_tb", mock)

        result = evaluate_task(str(tmp_path), skip_haiku=True)
        assert result["classification"] == "too_hard"
        assert result["passes"] == 0
        assert result["total"] == 5

    def test_reaches_opus_too_easy(self, tmp_path, monkeypatch):
        """Sonnet 3/5 → proceed. Opus 3/3 batch + 1/1 seq → 4/4 > LEARNABLE_MAX → too_easy."""
        _mock_cleanup(monkeypatch)
        self._mock_filter_tier(monkeypatch,
            sonnet_result=self._make_filter_result("Sonnet", 3, 5, 4, False),
        )
        # _can_stop: passes > LEARNABLE_MAX(3) is strictly greater
        # 3/3 batch → 3 > 3 is False → undecided
        # seq pass → 4/4, 4 > 3 → too_easy
        mock = _MockRunTb([
            _make_tb_result(3, 3),
            _make_tb_result(1, 1),
        ])
        monkeypatch.setattr("evaluate._run_tb", mock)

        result = evaluate_task(str(tmp_path), skip_haiku=True)
        assert result["classification"] == "too_easy"
        assert result["filtered_at"] is None

    def test_skip_filters_goes_straight_to_opus(self, tmp_path, monkeypatch):
        """skip_filters=True bypasses Haiku and Sonnet."""
        _mock_cleanup(monkeypatch)
        mock = _MockRunTb([_make_tb_result(2, 3)])  # 2/3 → learnable (2+2<=3? no, undecided)
        # 2/3, remaining 2 → undecided. Need more:
        # Let's do 1/3 batch → 1+2=3 <=3 and 1>=1 → learnable
        mock = _MockRunTb([_make_tb_result(1, 3)])
        monkeypatch.setattr("evaluate._run_tb", mock)

        result = evaluate_task(str(tmp_path), skip_filters=True)
        assert result["classification"] == "learnable"
        assert "haiku" not in result["tier_results"]
        assert "sonnet" not in result["tier_results"]
        assert result["passes"] == 1

    def test_haiku_skipped_by_default(self, tmp_path, monkeypatch):
        """skip_haiku defaults to True — Haiku tier should not run."""
        _mock_cleanup(monkeypatch)
        filter_calls = []

        original_filter = _run_filter_tier

        def tracking_filter(task_dir, model, model_label, n_runs, skip_threshold, **kw):
            filter_calls.append(model_label)
            return self._make_filter_result(model_label, 0, n_runs, skip_threshold, False)

        monkeypatch.setattr("evaluate._run_filter_tier", tracking_filter)
        mock = _MockRunTb([_make_tb_result(0, 3)])
        monkeypatch.setattr("evaluate._run_tb", mock)

        result = evaluate_task(str(tmp_path))  # default skip_haiku=True
        assert "Haiku" not in filter_calls
        assert "Sonnet" in filter_calls

    def test_opus_sequential_phase_runs_to_completion(self, tmp_path, monkeypatch):
        """Opus remains uncertain through sequential phase, classifies at end."""
        _mock_cleanup(monkeypatch)
        self._mock_filter_tier(monkeypatch,
            sonnet_result=self._make_filter_result("Sonnet", 2, 5, 4, False),
        )
        # batch 2/3 → remaining 2, 2+2=4 > LEARNABLE_MAX(3) → undecided
        # seq: pass → 3/4, remaining 1, 3+1=4 > 3 → undecided
        # seq: fail → 3/5 → LEARNABLE_MIN(1) <= 3 <= LEARNABLE_MAX(3) → learnable
        mock = _MockRunTb([
            _make_tb_result(2, 3),
            _make_tb_result(1, 1),
            _make_tb_result(0, 1),
        ])
        monkeypatch.setattr("evaluate._run_tb", mock)

        result = evaluate_task(str(tmp_path), skip_haiku=True, n_trials=5)
        assert result["classification"] == "learnable"
        assert result["passes"] == 3
        assert result["total"] == 5


class TestBuildResult:
    def test_learnable_with_pass_rate(self):
        result = _build_result(
            task_dir="/tmp/test-task",
            classification="learnable",
            filtered_at=None,
            tier_results={},
            opus_passes=2,
            opus_total=5,
        )
        assert result["classification"] == "learnable"
        assert result["pass_rate"] == 0.4
        assert result["task_name"] == "test-task"
        assert result["filtered_at"] is None

    def test_too_easy_filtered_at_sonnet(self):
        result = _build_result(
            task_dir="/tmp/easy-task",
            classification="too_easy",
            filtered_at="sonnet",
            tier_results={"sonnet": {
                "model_label": "Sonnet", "passes": 4, "total": 5, "should_skip": True,
            }},
        )
        assert result["classification"] == "too_easy"
        assert result["filtered_at"] == "sonnet"
        assert result["pass_rate"] is None  # no Opus data
        assert result["tier_results"]["sonnet"]["model"] == "Sonnet"

    def test_zero_opus_total(self):
        result = _build_result(
            task_dir="/tmp/t",
            classification="too_easy",
            filtered_at="haiku",
            tier_results={},
            opus_passes=0,
            opus_total=0,
        )
        assert result["pass_rate"] is None
