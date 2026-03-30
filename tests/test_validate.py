"""Tests for the structural validator."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validator"))

from validate import _parse_solution_files, analyze_solution_diff, validate_task


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

    def test_diff_warnings_included_in_result(self, good_task):
        """validate_task includes diff analysis warnings when present."""
        # solution.sh has no heredocs, so we get a warning
        result = validate_task(str(good_task))
        assert result["passed"] is True
        assert "diff_warnings" in result

    def test_solution_outside_workdir_fails(self, good_task):
        """solution.sh writing to paths outside WORKDIR should fail."""
        (good_task / "Dockerfile").write_text("FROM ubuntu:24.04\nWORKDIR /app\n")
        (good_task / "solution.sh").write_text(
            "#!/bin/bash\ncat > /etc/nginx/nginx.conf << 'EOF'\nserver {}\nEOF\n"
        )
        result = validate_task(str(good_task))
        assert result["passed"] is False
        assert any("outside WORKDIR" in i for i in result["issues"])

    def test_solution_inside_workdir_passes(self, good_task):
        """solution.sh writing to paths inside WORKDIR should pass."""
        (good_task / "Dockerfile").write_text("FROM ubuntu:24.04\nWORKDIR /app\n")
        (good_task / "solution.sh").write_text(
            "#!/bin/bash\ncat > /app/main.py << 'EOF'\nprint('hi')\nEOF\n"
        )
        result = validate_task(str(good_task))
        assert result["passed"] is True

    def test_solution_relative_path_ok(self, good_task):
        """Relative paths in solution.sh are fine (resolved within WORKDIR)."""
        (good_task / "solution.sh").write_text(
            "#!/bin/bash\ncat > main.py << 'EOF'\nprint('hi')\nEOF\n"
        )
        result = validate_task(str(good_task))
        assert result["passed"] is True

    def test_solution_custom_workdir(self, good_task):
        """Check uses actual WORKDIR from Dockerfile, not hardcoded /app."""
        (good_task / "Dockerfile").write_text("FROM ubuntu:24.04\nWORKDIR /opt/project\n")
        (good_task / "solution.sh").write_text(
            "#!/bin/bash\ncat > /opt/project/fix.py << 'EOF'\npass\nEOF\n"
        )
        result = validate_task(str(good_task))
        assert result["passed"] is True


class TestParseSolutionFiles:
    def test_basic_heredoc(self):
        script = """#!/bin/bash
cat > /app/main.py << 'EOF'
def hello():
    return "world"
EOF
"""
        files = _parse_solution_files(script)
        assert "main.py" in files
        assert 'return "world"' in files["main.py"]

    def test_multiple_files(self):
        script = """#!/bin/bash
cat > /app/foo.py << 'EOF'
x = 1
EOF
cat > /app/bar.py << 'PY'
y = 2
PY
"""
        files = _parse_solution_files(script)
        assert len(files) == 2
        assert "foo.py" in files
        assert "bar.py" in files

    def test_no_heredocs(self):
        script = "#!/bin/bash\necho hello\nsed -i 's/foo/bar/' file.txt\n"
        files = _parse_solution_files(script)
        assert files == {}

    def test_unquoted_delimiter(self):
        script = """cat > /app/main.py << EOF
print("hi")
EOF
"""
        files = _parse_solution_files(script)
        assert "main.py" in files

    def test_nested_path(self):
        script = """cat > /app/src/utils/helper.py << 'EOF'
pass
EOF
"""
        files = _parse_solution_files(script)
        assert "helper.py" in files

    def test_echo_pattern(self):
        script = '#!/bin/bash\necho "Hello, world!" > /app/hello.txt\n'
        files = _parse_solution_files(script)
        assert "hello.txt" in files
        assert files["hello.txt"] == "Hello, world!\n"

    def test_skips_shell_variable_paths(self):
        script = 'cat > "$REPORT" << \'EOF\'\nsome content\nEOF\n'
        files = _parse_solution_files(script)
        assert len(files) == 0

    def test_echo_append_ignored(self):
        """echo >> (append) should not be captured as a file write."""
        script = '#!/bin/bash\necho "line" >> /app/output.txt\n'
        files = _parse_solution_files(script)
        assert len(files) == 0


class TestAnalyzeSolutionDiff:
    def _make_task(self, tmp_path, buggy_content, fixed_content, filename="main.py"):
        """Create a minimal task with buggy source and solution.sh."""
        (tmp_path / "task.yaml").write_text(yaml.dump({
            "instruction": "Fix it", "difficulty": "medium", "parser_name": "pytest",
        }))
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:24.04\n")
        (tmp_path / "run-tests.sh").write_text("pytest\n")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_outputs.py").write_text("def test_pass(): pass\n")

        (tmp_path / filename).write_text(buggy_content)
        (tmp_path / "solution.sh").write_text(
            f"#!/bin/bash\ncat > /app/{filename} << 'EOF'\n{fixed_content}EOF\n"
        )
        return tmp_path

    def test_counts_hunks_correctly(self, tmp_path):
        buggy = "def add(a, b):\n    return a - b\n\ndef mul(a, b):\n    return a + b\n"
        fixed = "def add(a, b):\n    return a + b\n\ndef mul(a, b):\n    return a * b\n"
        task = self._make_task(tmp_path, buggy, fixed)
        result = analyze_solution_diff(str(task))
        assert result["files_changed"] == 1
        assert result["total_hunks"] == 2
        assert result["total_lines_changed"] == 4  # 2 removed + 2 added

    def test_warns_too_many_hunks(self, tmp_path):
        # 10 bugs = 10 hunks (every other line in 20 lines)
        buggy = "\n".join(f"line_{i} = {i}" for i in range(20))
        fixed = "\n".join(
            f"line_{i} = {i * 10}" if i % 2 == 0 else f"line_{i} = {i}"
            for i in range(20)
        )
        task = self._make_task(tmp_path, buggy, fixed)
        result = analyze_solution_diff(str(task))
        assert any("too many bugs" in w for w in result["warnings"])

    def test_warns_too_few_hunks(self, tmp_path):
        buggy = "x = 1\ny = 2\n"
        fixed = "x = 1\ny = 3\n"
        task = self._make_task(tmp_path, buggy, fixed)
        result = analyze_solution_diff(str(task))
        assert result["total_hunks"] == 1
        assert any("too easy" in w for w in result["warnings"])

    def test_warns_multi_file(self, tmp_path):
        (tmp_path / "task.yaml").write_text(yaml.dump({
            "instruction": "Fix it", "difficulty": "medium", "parser_name": "pytest",
        }))
        (tmp_path / "Dockerfile").write_text("FROM ubuntu:24.04\n")
        (tmp_path / "run-tests.sh").write_text("pytest\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_outputs.py").write_text("pass\n")

        # 3 buggy files
        for name in ["a.py", "b.py", "c.py"]:
            (tmp_path / name).write_text(f"x = 0  # bug in {name}\n")

        solution = "#!/bin/bash\n"
        for name in ["a.py", "b.py", "c.py"]:
            solution += f"cat > /app/{name} << 'EOF'\nx = 1  # fixed in {name}\nEOF\n"
        (tmp_path / "solution.sh").write_text(solution)

        result = analyze_solution_diff(str(tmp_path))
        assert result["files_changed"] == 3
        assert any("multi-file" in w for w in result["warnings"])

    def test_warns_high_loc(self, tmp_path):
        buggy = "\n".join(f"line_{i} = {i}" for i in range(250))
        fixed = buggy.replace("line_5 = 5", "line_5 = 50")
        task = self._make_task(tmp_path, buggy, fixed)
        result = analyze_solution_diff(str(task))
        assert result["source_loc"] == 250
        assert any("LOC" in w for w in result["warnings"])

    def test_warns_large_diff(self, tmp_path):
        buggy = "\n".join(f"x{i} = {i}" for i in range(50))
        # Replace most lines
        fixed = "\n".join(f"x{i} = {i * 100}" for i in range(50))
        task = self._make_task(tmp_path, buggy, fixed)
        result = analyze_solution_diff(str(task))
        assert any("lines" in w and "complex" in w for w in result["warnings"])

    def test_no_solution_file(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        result = analyze_solution_diff(str(tmp_path))
        assert any("not found" in w for w in result["warnings"])

    def test_skips_infra_files(self, tmp_path):
        """Solution rewriting Dockerfile/run-tests.sh shouldn't count as source changes."""
        buggy = "x = 1\n"
        fixed = "x = 2\n"
        task = self._make_task(tmp_path, buggy, fixed)
        # Add Dockerfile heredoc to solution
        solution = (tmp_path / "solution.sh").read_text()
        solution += "cat > /app/Dockerfile << 'EOF'\nFROM python:3.12\nEOF\n"
        (tmp_path / "solution.sh").write_text(solution)

        result = analyze_solution_diff(str(task))
        assert result["files_changed"] == 1  # only main.py, not Dockerfile
