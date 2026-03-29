"""Tests for the quality comparison module."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from quality import (
    _compute_stats,
    _count_lines,
    _count_test_functions,
    analyze_task,
    compare,
)


class TestCountLines:
    def test_counts_lines(self, tmp_path):
        f = tmp_path / "test.sh"
        f.write_text("line1\nline2\nline3\n")
        assert _count_lines(f) == 3

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.sh"
        f.write_text("")
        assert _count_lines(f) == 0

    def test_missing_file(self, tmp_path):
        assert _count_lines(tmp_path / "nonexistent.sh") is None


class TestCountTestFunctions:
    def test_finds_test_functions(self, tmp_path):
        f = tmp_path / "test_outputs.py"
        f.write_text(
            "def test_one():\n    pass\n\n"
            "def test_two():\n    pass\n\n"
            "def helper():\n    pass\n"
        )
        assert _count_test_functions(f) == 2

    def test_indented_test_functions(self, tmp_path):
        f = tmp_path / "test_outputs.py"
        f.write_text(
            "class TestFoo:\n"
            "    def test_one(self):\n        pass\n\n"
            "    def test_two(self):\n        pass\n"
        )
        assert _count_test_functions(f) == 2

    def test_no_tests(self, tmp_path):
        f = tmp_path / "test_outputs.py"
        f.write_text("def helper():\n    pass\n")
        assert _count_test_functions(f) == 0

    def test_missing_file(self, tmp_path):
        assert _count_test_functions(tmp_path / "nope.py") is None


class TestComputeStats:
    def test_basic_stats(self):
        s = _compute_stats([1, 2, 3, 4, 5])
        assert s["min"] == 1
        assert s["max"] == 5
        assert s["mean"] == 3.0
        assert s["median"] == 3.0
        assert s["count"] == 5

    def test_single_value(self):
        s = _compute_stats([42])
        assert s["min"] == 42
        assert s["max"] == 42
        assert s["mean"] == 42.0
        assert s["count"] == 1

    def test_empty(self):
        s = _compute_stats([])
        assert s["count"] == 0
        assert s["mean"] is None


class TestAnalyzeTask:
    def _make_task(self, tmp_path, instruction="Fix the bug", solution_lines=5,
                   test_code=None, extra_files=None, dockerfile_content=None):
        """Create a minimal valid task directory."""
        import yaml

        task_dir = tmp_path / "test-task"
        task_dir.mkdir()

        # task.yaml
        (task_dir / "task.yaml").write_text(yaml.dump({
            "instruction": instruction,
            "difficulty": "medium",
            "parser_name": "pytest",
        }))

        # solution.sh
        (task_dir / "solution.sh").write_text("\n".join(["#!/bin/bash"] + ["echo fix"] * solution_lines) + "\n")

        # Dockerfile
        df_content = dockerfile_content or "FROM python:3.11\nRUN apt-get update && apt-get install -y tmux asciinema\n"
        (task_dir / "Dockerfile").write_text(df_content)

        # docker-compose.yaml
        (task_dir / "docker-compose.yaml").write_text("services:\n  client:\n    build: .\n")

        # run-tests.sh
        (task_dir / "run-tests.sh").write_text("#!/bin/bash\npytest\n")

        # tests/
        tests_dir = task_dir / "tests"
        tests_dir.mkdir()
        if test_code is None:
            test_code = "def test_one():\n    pass\n\ndef test_two():\n    pass\n"
        (tests_dir / "test_outputs.py").write_text(test_code)

        # Extra source files
        if extra_files:
            for name, content in extra_files.items():
                p = task_dir / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)

        return task_dir

    def test_basic_task(self, tmp_path):
        task_dir = self._make_task(tmp_path)
        m = analyze_task(str(task_dir))
        assert m is not None
        assert m["task_name"] == "test-task"
        assert m["instruction_length"] > 0
        assert m["solution_lines"] > 0
        assert m["test_lines"] == 5
        assert m["test_count"] == 2
        assert m["has_dockerfile"] is True
        assert m["has_docker_compose"] is True
        assert m["dockerfile_installs_tmux"] is True

    def test_no_task_yaml(self, tmp_path):
        task_dir = tmp_path / "empty"
        task_dir.mkdir()
        assert analyze_task(str(task_dir)) is None

    def test_source_file_count(self, tmp_path):
        task_dir = self._make_task(tmp_path, extra_files={
            "app.py": "print('hello')",
            "lib/utils.py": "def util(): pass",
        })
        m = analyze_task(str(task_dir))
        assert m["source_file_count"] == 2

    def test_dockerfile_without_tmux(self, tmp_path):
        task_dir = self._make_task(
            tmp_path,
            dockerfile_content="FROM python:3.11\nRUN pip install pytest\n",
        )
        m = analyze_task(str(task_dir))
        assert m["dockerfile_installs_tmux"] is False

    def test_instruction_length(self, tmp_path):
        long_instruction = "Fix the broken parser. " * 20
        task_dir = self._make_task(tmp_path, instruction=long_instruction)
        m = analyze_task(str(task_dir))
        assert m["instruction_length"] == len(long_instruction)


class TestCompare:
    def test_basic_comparison(self):
        examples = [
            {"task_name": "ex1", "instruction_length": 1000, "solution_lines": 50,
             "test_lines": 100, "test_count": 10, "file_count": 8, "source_file_count": 3,
             "has_dockerfile": True, "has_docker_compose": True, "dockerfile_installs_tmux": True},
            {"task_name": "ex2", "instruction_length": 1500, "solution_lines": 80,
             "test_lines": 150, "test_count": 15, "file_count": 10, "source_file_count": 5,
             "has_dockerfile": True, "has_docker_compose": True, "dockerfile_installs_tmux": True},
        ]
        generated = [
            {"task_name": "gen1", "instruction_length": 800, "solution_lines": 40,
             "test_lines": 90, "test_count": 8, "file_count": 7, "source_file_count": 2,
             "has_dockerfile": True, "has_docker_compose": True, "dockerfile_installs_tmux": True},
        ]
        c = compare(examples, generated)
        assert "instruction_length" in c
        assert c["instruction_length"]["examples"]["count"] == 2
        assert c["instruction_length"]["generated"]["count"] == 1
        assert c["instruction_length"]["delta_mean"] is not None

    def test_outlier_detection(self):
        examples = [
            {"task_name": "ex1", "instruction_length": 1000, "solution_lines": 50,
             "test_lines": 100, "test_count": 10, "file_count": 8, "source_file_count": 3,
             "has_dockerfile": True, "has_docker_compose": True, "dockerfile_installs_tmux": True},
        ]
        generated = [
            {"task_name": "gen1", "instruction_length": 50, "solution_lines": 2,
             "test_lines": 5, "test_count": 1, "file_count": 3, "source_file_count": 0,
             "has_dockerfile": True, "has_docker_compose": False, "dockerfile_installs_tmux": False},
        ]
        c = compare(examples, generated)
        assert len(c["outliers"]) > 0

    def test_empty_generated(self):
        examples = [
            {"task_name": "ex1", "instruction_length": 1000, "solution_lines": 50,
             "test_lines": 100, "test_count": 10, "file_count": 8, "source_file_count": 3,
             "has_dockerfile": True, "has_docker_compose": True, "dockerfile_installs_tmux": True},
        ]
        c = compare(examples, [])
        assert c["instruction_length"]["generated"]["count"] == 0

    def test_boolean_checks(self):
        examples = []
        generated = [
            {"task_name": "gen1", "instruction_length": 500, "solution_lines": 20,
             "test_lines": 50, "test_count": 5, "file_count": 6, "source_file_count": 1,
             "has_dockerfile": True, "has_docker_compose": True, "dockerfile_installs_tmux": False},
            {"task_name": "gen2", "instruction_length": 600, "solution_lines": 25,
             "test_lines": 60, "test_count": 6, "file_count": 7, "source_file_count": 2,
             "has_dockerfile": True, "has_docker_compose": True, "dockerfile_installs_tmux": True},
        ]
        c = compare(examples, generated)
        assert c["dockerfile_installs_tmux"]["generated_true"] == 1
        assert c["dockerfile_installs_tmux"]["generated_total"] == 2
        assert c["dockerfile_installs_tmux"]["generated_pct"] == 50.0
