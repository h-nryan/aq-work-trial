"""
Basic structural validator — checks that a generated task directory has the right files and format.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


REQUIRED_FILES = ["task.yaml", "Dockerfile", "run-tests.sh"]
REQUIRED_YAML_FIELDS = ["instruction", "difficulty", "parser_name"]
VALID_DIFFICULTIES = {"easy", "medium", "hard"}


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

    passed = len(issues) == 0

    return {"passed": passed, "issues": issues}


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

    sys.exit(0 if result["passed"] else 1)
