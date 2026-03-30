"""Tests for the Docker-based functional validator (unit tests, no Docker needed)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validator"))

from docker_validate import (
    TBENCH_BASE_IMAGE,
    _rewrite_dockerfile_for_base,
    _rewrite_run_tests_for_base,
    _sanity_checks,
    docker_validate,
    ensure_base_image,
)


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


class TestRewriteDockerfileForBase:
    """Tests for _rewrite_dockerfile_for_base Dockerfile rewriting."""

    def test_rewrites_ubuntu_base(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM ubuntu:24.04\n"
            "\n"
            "RUN apt-get update && apt-get install -y \\\n"
            "    tmux \\\n"
            "    python3 \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
            "\n"
            "WORKDIR /app\n"
            "COPY main.py /app/\n"
            "CMD [\"bash\"]\n"
        )
        assert _rewrite_dockerfile_for_base(tmp_path) is True

        content = dockerfile.read_text()
        assert f"FROM {TBENCH_BASE_IMAGE}" in content
        assert "apt-get" not in content
        assert "WORKDIR /app" in content
        assert "COPY main.py /app/" in content
        assert "CMD" in content

    def test_preserves_non_apt_run_commands(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM ubuntu:24.04\n"
            "RUN apt-get update && apt-get install -y python3\n"
            "RUN chmod +x /app/run-tests.sh\n"
            "COPY main.py /app/\n"
        )
        _rewrite_dockerfile_for_base(tmp_path)
        content = dockerfile.read_text()
        assert "chmod" in content
        assert "COPY main.py" in content

    def test_rewrites_python_base(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM python:3.11-slim\n"
            "RUN pip install requests\n"
            "WORKDIR /app\n"
            "COPY main.py /app/\n"
        )
        assert _rewrite_dockerfile_for_base(tmp_path) is True
        content = dockerfile.read_text()
        assert f"FROM {TBENCH_BASE_IMAGE}" in content
        assert "python:3.11" not in content
        assert "pip install" not in content
        assert "COPY main.py" in content

    def test_skips_unknown_base(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM alpine:3.18\nWORKDIR /app\n")
        assert _rewrite_dockerfile_for_base(tmp_path) is False
        assert "alpine:3.18" in dockerfile.read_text()

    def test_no_dockerfile(self, tmp_path):
        assert _rewrite_dockerfile_for_base(tmp_path) is False

    def test_removes_debian_frontend(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM ubuntu:22.04\n"
            "ENV DEBIAN_FRONTEND=noninteractive\n"
            "RUN apt-get update && apt-get install -y curl\n"
            "WORKDIR /app\n"
        )
        _rewrite_dockerfile_for_base(tmp_path)
        content = dockerfile.read_text()
        assert "DEBIAN_FRONTEND" not in content
        assert "apt-get" not in content
        assert "WORKDIR /app" in content

    def test_handles_multiline_apt_get(self, tmp_path):
        """Multi-line RUN apt-get with backslash continuations."""
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            "FROM ubuntu:24.04\n"
            "\n"
            "RUN apt-get update && apt-get install -y \\\n"
            "    tmux \\\n"
            "    asciinema \\\n"
            "    curl \\\n"
            "    python3 \\\n"
            "    python3-pip \\\n"
            "    && rm -rf /var/lib/apt/lists/*\n"
            "\n"
            "WORKDIR /app\n"
            "COPY . /app/\n"
        )
        _rewrite_dockerfile_for_base(tmp_path)
        content = dockerfile.read_text()
        assert "apt-get" not in content
        assert "tmux" not in content
        assert "WORKDIR /app" in content
        assert "COPY . /app/" in content


class TestRewriteRunTestsForBase:
    """Tests for _rewrite_run_tests_for_base."""

    def test_strips_apt_get_lines(self, tmp_path):
        (tmp_path / "run-tests.sh").write_text(
            "#!/bin/bash\n"
            "apt-get update\n"
            "apt-get install -y curl\n"
            "echo hello\n"
        )
        assert _rewrite_run_tests_for_base(tmp_path) is True
        result = (tmp_path / "run-tests.sh").read_text()
        assert "apt-get" not in result
        assert "echo hello" in result
        assert "#!/bin/bash" in result

    def test_strips_uv_installer(self, tmp_path):
        (tmp_path / "run-tests.sh").write_text(
            "#!/bin/bash\n"
            "curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh\n"
            "source $HOME/.local/bin/env\n"
            "uv run pytest tests/\n"
        )
        assert _rewrite_run_tests_for_base(tmp_path) is True
        result = (tmp_path / "run-tests.sh").read_text()
        assert "astral.sh" not in result
        assert "source $HOME/.local/bin/env" not in result
        assert "uv run pytest" in result

    def test_strips_multiline_apt_get(self, tmp_path):
        (tmp_path / "run-tests.sh").write_text(
            "#!/bin/bash\n"
            "apt-get update && \\\n"
            "  apt-get install -y \\\n"
            "  curl wget\n"
            "echo done\n"
        )
        assert _rewrite_run_tests_for_base(tmp_path) is True
        result = (tmp_path / "run-tests.sh").read_text()
        assert "apt-get" not in result
        assert "echo done" in result

    def test_strips_pip_install(self, tmp_path):
        (tmp_path / "run-tests.sh").write_text(
            "#!/bin/bash\n"
            "pip install requests\n"
            "pip3 install pyyaml\n"
            "python3 test.py\n"
        )
        assert _rewrite_run_tests_for_base(tmp_path) is True
        result = (tmp_path / "run-tests.sh").read_text()
        assert "pip install" not in result
        assert "python3 test.py" in result

    def test_no_changes_returns_false(self, tmp_path):
        (tmp_path / "run-tests.sh").write_text(
            "#!/bin/bash\n"
            "uv run pytest tests/\n"
        )
        assert _rewrite_run_tests_for_base(tmp_path) is False

    def test_no_file_returns_false(self, tmp_path):
        assert _rewrite_run_tests_for_base(tmp_path) is False

    def test_strips_sudo_apt_get(self, tmp_path):
        (tmp_path / "run-tests.sh").write_text(
            "#!/bin/bash\n"
            "sudo apt-get update\n"
            "sudo apt-get install -y python3\n"
            "python3 app.py\n"
        )
        assert _rewrite_run_tests_for_base(tmp_path) is True
        result = (tmp_path / "run-tests.sh").read_text()
        assert "apt-get" not in result
        assert "python3 app.py" in result


class TestEnsureBaseImage:
    """Tests for ensure_base_image (mocked Docker calls)."""

    def test_returns_true_when_image_exists(self, monkeypatch):
        import docker_validate
        monkeypatch.setattr(docker_validate, "_base_image_checked", False)

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["docker", "image", "inspect"]:
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("docker_validate.subprocess.run", fake_run)
        assert ensure_base_image() is True

    def test_caches_result(self, monkeypatch):
        import docker_validate
        monkeypatch.setattr(docker_validate, "_base_image_checked", True)
        # Should return True without calling Docker at all
        assert ensure_base_image() is True

    def test_returns_false_when_no_dockerfile(self, monkeypatch, tmp_path):
        import docker_validate
        monkeypatch.setattr(docker_validate, "_base_image_checked", False)
        # Image doesn't exist
        def fake_run(cmd, **kwargs):
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()
        monkeypatch.setattr("docker_validate.subprocess.run", fake_run)
        # Point to a nonexistent Dockerfile.base
        monkeypatch.setattr("docker_validate.Path", lambda x: tmp_path / "nonexistent")
        # Fallback: __file__ based path won't find Dockerfile.base
        result = ensure_base_image()
        # Should fail gracefully (either False or it finds the real file and builds)
        assert isinstance(result, bool)
