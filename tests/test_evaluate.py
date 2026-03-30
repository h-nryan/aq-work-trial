"""Tests for evaluate.py — stale resource cleanup and result parsing."""

from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from evaluate import (
    _cleanup_stale_containers,
    _cleanup_stale_tb_processes,
    _parse_run_results,
    cleanup_stale_resources,
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
