"""
Basic structural validator — checks that a generated task directory has the right files and format.

Includes solution diff analysis that compares buggy source files against the
solution to produce calibration warnings (bug count, LOC, file count).
"""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

import yaml


REQUIRED_FILES = ["task.yaml", "Dockerfile", "run-tests.sh"]
REQUIRED_YAML_FIELDS = ["instruction", "difficulty", "parser_name"]
VALID_DIFFICULTIES = {"easy", "medium", "hard"}

# Files that are infrastructure, not source code — excluded from diff analysis
INFRA_FILES = {"Dockerfile", "docker-compose.yaml", "run-tests.sh", "task.yaml"}


def _parse_solution_files(solution_sh: str) -> dict[str, str]:
    """Extract file contents from a solution.sh script.

    Parses patterns:
    1. Heredoc:  cat > /app/foo.py << 'EOF' ... EOF
    2. Echo:     echo "content" > /app/foo.txt
    3. Flags sed/perl patches as unparseable (returns empty for those files)

    Returns dict mapping filename (basename) to content.
    """
    files: dict[str, str] = {}

    # Pattern 1: heredoc — cat > <path> << '<DELIM>'
    heredoc_pattern = re.compile(
        r"""cat\s+>+\s+(\S+)\s+<<\s*['"]?(\w+)['"]?""",
    )

    # Pattern 2: echo — echo "content" > <path> (single-line file writes)
    echo_pattern = re.compile(
        r"""echo\s+["']([^"']*)["']\s+>\s+(\S+)""",
    )

    lines = solution_sh.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        line = lines[i]

        # Try heredoc first
        match = heredoc_pattern.search(line)
        if match:
            filepath = match.group(1)
            delimiter = match.group(2)
            content_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].rstrip("\n") != delimiter:
                content_lines.append(lines[i])
                i += 1
            # Skip shell variable paths like "$REPORT" or "\"$REPORT\""
            clean_path = filepath.strip('"').strip("'")
            if not clean_path.startswith("$"):
                filename = clean_path.split("/")[-1] if "/" in clean_path else clean_path
                files[filename] = "".join(content_lines)
            i += 1
            continue

        # Try echo pattern (single-line writes)
        match = echo_pattern.search(line)
        if match and ">>" not in line:  # skip appends
            content = match.group(1)
            filepath = match.group(2)
            if not filepath.startswith("$"):
                filename = filepath.split("/")[-1] if "/" in filepath else filepath
                files[filename] = content + "\n"
            i += 1
            continue

        i += 1

    return files


def analyze_solution_diff(task_dir: str) -> dict:
    """Analyze the diff between buggy source files and solution.sh output.

    Returns a dict with:
        - files_changed: number of source files modified by solution
        - total_hunks: number of distinct change regions (proxy for bug count)
        - total_lines_changed: total added + removed lines
        - source_loc: total lines in buggy source files
        - warnings: list of calibration warnings
        - file_details: per-file breakdown
    """
    task_path = Path(task_dir)
    solution_path = task_path / "solution.sh"
    warnings: list[str] = []

    if not solution_path.exists():
        return {"warnings": ["solution.sh not found — skipping diff analysis"]}

    solution_files = _parse_solution_files(solution_path.read_text())
    if not solution_files:
        return {"warnings": ["Could not parse any heredoc files from solution.sh"]}

    files_changed = 0
    total_hunks = 0
    total_lines_added = 0
    total_lines_removed = 0
    source_loc = 0
    file_details: list[dict] = []

    for filename, fixed_content in solution_files.items():
        # Skip infrastructure files
        if filename in INFRA_FILES:
            continue
        # Skip test files (filename is always a basename from _parse_solution_files)
        if filename.startswith("test_"):
            continue

        buggy_path = _find_source_file(task_path, filename)
        if buggy_path is None:
            warnings.append(f"Solution modifies {filename} but file not found in task")
            continue

        buggy_content = buggy_path.read_text()
        source_loc += len(buggy_content.splitlines())

        if buggy_content == fixed_content:
            continue

        files_changed += 1
        buggy_lines = buggy_content.splitlines(keepends=True)
        fixed_lines = fixed_content.splitlines(keepends=True)

        # Count hunks and changed lines
        diff = list(difflib.unified_diff(buggy_lines, fixed_lines, n=0))
        hunks = sum(1 for line in diff if line.startswith("@@"))
        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

        total_hunks += hunks
        total_lines_added += added
        total_lines_removed += removed

        file_details.append({
            "filename": filename,
            "hunks": hunks,
            "lines_added": added,
            "lines_removed": removed,
        })

    # Generate calibration warnings
    if files_changed == 0:
        warnings.append("Solution changes no source files — may be misconfigured")
    elif files_changed > 2:
        warnings.append(
            f"Solution modifies {files_changed} source files — "
            "multi-file tasks are harder for agents"
        )

    if total_hunks < 2:
        warnings.append(
            f"Only {total_hunks} change region(s) — task may be too easy (single bug)"
        )
    elif total_hunks > 8:
        warnings.append(
            f"{total_hunks} change regions — likely too many bugs (target 3-4)"
        )

    total_changed = total_lines_added + total_lines_removed
    if total_changed > 80:
        warnings.append(
            f"Solution changes {total_changed} lines — large diffs suggest "
            "task is too complex for 6-minute time limit"
        )

    if source_loc > 200:
        warnings.append(
            f"Buggy source is {source_loc} LOC — agents must read and understand "
            "quickly; consider keeping under 150 lines"
        )

    return {
        "files_changed": files_changed,
        "total_hunks": total_hunks,
        "total_lines_changed": total_lines_added + total_lines_removed,
        "source_loc": source_loc,
        "warnings": warnings,
        "file_details": file_details,
    }


def _find_source_file(task_path: Path, filename: str) -> Path | None:
    """Find a source file in the task directory, checking common locations."""
    # Direct match in task root
    candidate = task_path / filename
    if candidate.exists():
        return candidate

    # Search subdirectories (but not tests/)
    for path in task_path.rglob(filename):
        if "tests" not in path.parts and path.is_file():
            return path

    return None


def validate_task(task_dir: str) -> dict:
    """Validate that a task directory has the correct structure.

    Args:
        task_dir: Path to the generated task directory.

    Returns:
        dict with passed (bool) and issues (list of strings).
    """
    task_path = Path(task_dir)
    issues = []

    if not task_path.is_dir():
        return {"passed": False, "issues": [f"Directory does not exist: {task_dir}"]}

    # Check required files
    for filename in REQUIRED_FILES:
        if not (task_path / filename).exists():
            issues.append(f"Missing required file: {filename}")

    # Check tests directory has at least one .py file
    tests_dir = task_path / "tests"
    if not tests_dir.is_dir():
        issues.append("Missing tests/ directory")
    else:
        py_files = list(tests_dir.glob("*.py"))
        if not py_files:
            issues.append("No .py test files in tests/ directory")

    # Validate task.yaml if it exists
    task_yaml_path = task_path / "task.yaml"
    if task_yaml_path.exists():
        try:
            with open(task_yaml_path) as f:
                task_data = yaml.safe_load(f)

            if not isinstance(task_data, dict):
                issues.append("task.yaml does not parse to a dict")
            else:
                for field in REQUIRED_YAML_FIELDS:
                    if field not in task_data:
                        issues.append(f"task.yaml missing required field: {field}")

                difficulty = task_data.get("difficulty", "")
                if difficulty not in VALID_DIFFICULTIES:
                    issues.append(
                        f"task.yaml difficulty '{difficulty}' not in {VALID_DIFFICULTIES}"
                    )
        except yaml.YAMLError as e:
            issues.append(f"task.yaml parse error: {e}")

    # Check Dockerfile has a FROM statement
    dockerfile_path = task_path / "Dockerfile"
    if dockerfile_path.exists():
        content = dockerfile_path.read_text()
        if "FROM" not in content:
            issues.append("Dockerfile missing FROM statement")

    # Check solution.sh doesn't write files outside WORKDIR
    # Tasks with files in system dirs (e.g. /etc/nginx/) are too hard because
    # the agent wastes time navigating instead of debugging.
    solution_path = task_path / "solution.sh"
    if solution_path.exists() and dockerfile_path.exists():
        workdir = "/app"  # default
        for line in dockerfile_path.read_text().splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("WORKDIR"):
                parts = stripped.split(None, 1)
                if len(parts) == 2:
                    workdir = parts[1].strip()

        # Extract full paths from heredoc and echo write targets
        write_path_re = re.compile(
            r"""cat\s+>+\s+(\S+)\s+<<|echo\s+["'][^"']*["']\s+>\s+(\S+)"""
        )
        for match in write_path_re.finditer(solution_path.read_text()):
            raw_path = (match.group(1) or match.group(2)).strip("'\"")
            if raw_path.startswith("$"):
                continue
            if raw_path.startswith("/") and not raw_path.startswith(workdir):
                issues.append(
                    f"solution.sh writes to '{raw_path}' outside WORKDIR ({workdir}) "
                    f"— source files must be in WORKDIR for agent navigability"
                )

    # Solution diff analysis — calibration warnings (don't block validation)
    diff_analysis = analyze_solution_diff(task_dir)
    warnings = diff_analysis.get("warnings", [])

    passed = len(issues) == 0

    result = {"passed": passed, "issues": issues}
    if warnings:
        result["diff_warnings"] = warnings
    if "total_hunks" in diff_analysis:
        result["diff_analysis"] = {
            k: v for k, v in diff_analysis.items() if k != "warnings"
        }
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate.py <task_dir>")
        sys.exit(1)

    result = validate_task(sys.argv[1])

    if result["passed"]:
        print("PASSED: All structural checks passed.")
    else:
        print("FAILED:")
        for issue in result["issues"]:
            print(f"  - {issue}")

    if result.get("diff_warnings"):
        print("\nDiff analysis warnings:")
        for w in result["diff_warnings"]:
            print(f"  ⚠ {w}")

    if result.get("diff_analysis"):
        da = result["diff_analysis"]
        print(
            f"\nDiff analysis: {da.get('files_changed', 0)} file(s) changed, "
            f"{da.get('total_hunks', 0)} change region(s), "
            f"{da.get('total_lines_changed', 0)} lines changed, "
            f"{da.get('source_loc', 0)} LOC in buggy source"
        )

    sys.exit(0 if result["passed"] else 1)
