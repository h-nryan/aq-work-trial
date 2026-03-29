"""
Docker-based functional validator for generated tasks.

Validates that:
1. The Docker image builds successfully
2. Tests FAIL on an unsolved container (no solution applied)
3. Tests PASS after solution.sh is applied

This ensures generated tasks are functionally correct — the task is genuinely
broken, and the reference solution actually fixes it.
"""

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml


def _docker_available() -> bool:
    """Check if Docker daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _build_image(task_dir: Path, tag: str, timeout: int = 300) -> dict:
    """Build Docker image from the task's Dockerfile.

    Returns dict with 'success' bool and 'error' string if failed.
    """
    try:
        result = subprocess.run(
            ["docker", "build", "-t", tag, "."],
            cwd=str(task_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return {
                "success": False,
                "error": f"Docker build failed (exit {result.returncode}):\n{result.stderr[-2000:]}",
            }
        return {"success": True, "error": None}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Docker build timed out after {timeout}s"}


def _run_tests_in_container(
    tag: str,
    task_dir: Path,
    apply_solution: bool,
    timeout: int = 120,
) -> dict:
    """Run tests inside a container, optionally applying solution.sh first.

    The container mounts run-tests.sh and tests/ from the task directory,
    then executes them. If apply_solution is True, solution.sh runs first.

    Returns dict with 'exit_code', 'stdout', 'stderr', 'timed_out'.
    """
    tests_dir = task_dir / "tests"
    run_tests = task_dir / "run-tests.sh"
    solution = task_dir / "solution.sh"

    # Build the command to run inside the container.
    # We copy run-tests.sh and tests/ into the container's workdir,
    # then optionally run solution.sh before running the tests.
    if apply_solution:
        shell_cmd = (
            "cp /mnt/solution.sh . && chmod +x solution.sh && bash solution.sh && "
            "export TEST_DIR=/mnt/tests && bash /mnt/run-tests.sh"
        )
    else:
        shell_cmd = "export TEST_DIR=/mnt/tests && bash /mnt/run-tests.sh"

    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{run_tests.resolve()}:/mnt/run-tests.sh:ro",
        "-v", f"{tests_dir.resolve()}:/mnt/tests:ro",
    ]

    if apply_solution and solution.exists():
        docker_cmd.extend(["-v", f"{solution.resolve()}:/mnt/solution.sh:ro"])

    docker_cmd.extend([tag, "bash", "-c", shell_cmd])

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Container timed out after {timeout}s",
            "timed_out": True,
        }


def _cleanup_image(tag: str) -> None:
    """Remove the Docker image to avoid clutter."""
    subprocess.run(
        ["docker", "rmi", "-f", tag],
        capture_output=True,
        timeout=30,
    )


def docker_validate(
    task_dir: str,
    build_timeout: int = 300,
    test_timeout: int = 120,
    cleanup: bool = True,
) -> dict:
    """Run full Docker-based functional validation on a task.

    Args:
        task_dir: Path to the task directory.
        build_timeout: Max seconds for Docker build.
        test_timeout: Max seconds for each test run.
        cleanup: Whether to remove the Docker image after validation.

    Returns:
        dict with:
            passed: bool — True only if all checks pass
            image_builds: bool
            tests_fail_without_solution: bool
            tests_pass_with_solution: bool
            issues: list of strings describing failures
            details: dict with stdout/stderr from each phase
    """
    task_path = Path(task_dir).resolve()
    issues = []
    details = {}

    # Pre-flight checks
    if not task_path.is_dir():
        return {
            "passed": False,
            "image_builds": False,
            "tests_fail_without_solution": False,
            "tests_pass_with_solution": False,
            "issues": [f"Task directory not found: {task_dir}"],
            "details": {},
        }

    required = ["Dockerfile", "run-tests.sh", "solution.sh", "tests"]
    for name in required:
        p = task_path / name
        if not p.exists():
            issues.append(f"Missing required path: {name}")
    if issues:
        return {
            "passed": False,
            "image_builds": False,
            "tests_fail_without_solution": False,
            "tests_pass_with_solution": False,
            "issues": issues,
            "details": {},
        }

    if not _docker_available():
        return {
            "passed": False,
            "image_builds": False,
            "tests_fail_without_solution": False,
            "tests_pass_with_solution": False,
            "issues": ["Docker is not available. Ensure Docker Desktop is running."],
            "details": {},
        }

    # Generate a unique tag for this validation run
    task_name = task_path.name
    tag = f"tbench-validate-{task_name}:{int(time.time())}"

    image_builds = False
    tests_fail_without_solution = False
    tests_pass_with_solution = False

    try:
        # Phase 1: Build the Docker image
        print(f"[1/3] Building Docker image for '{task_name}'...")
        build_result = _build_image(task_path, tag, timeout=build_timeout)
        details["build"] = build_result

        if not build_result["success"]:
            issues.append(f"Docker image build failed: {build_result['error']}")
            return {
                "passed": False,
                "image_builds": False,
                "tests_fail_without_solution": False,
                "tests_pass_with_solution": False,
                "issues": issues,
                "details": details,
            }

        image_builds = True
        print("    Image built successfully.")

        # Phase 2: Tests must FAIL without solution
        print("[2/3] Running tests WITHOUT solution (expecting failure)...")
        no_solution = _run_tests_in_container(
            tag, task_path, apply_solution=False, timeout=test_timeout,
        )
        details["without_solution"] = {
            "exit_code": no_solution["exit_code"],
            "timed_out": no_solution["timed_out"],
            "stdout_tail": no_solution["stdout"][-2000:] if no_solution["stdout"] else "",
            "stderr_tail": no_solution["stderr"][-2000:] if no_solution["stderr"] else "",
        }

        if no_solution["timed_out"]:
            issues.append("Tests timed out without solution applied.")
        elif no_solution["exit_code"] == 0:
            issues.append(
                "Tests PASSED without solution — task is broken (tests should fail on unsolved container)."
            )
        else:
            tests_fail_without_solution = True
            print("    Tests correctly fail without solution.")

        # Phase 3: Tests must PASS with solution
        print("[3/3] Running tests WITH solution (expecting pass)...")
        with_solution = _run_tests_in_container(
            tag, task_path, apply_solution=True, timeout=test_timeout,
        )
        details["with_solution"] = {
            "exit_code": with_solution["exit_code"],
            "timed_out": with_solution["timed_out"],
            "stdout_tail": with_solution["stdout"][-2000:] if with_solution["stdout"] else "",
            "stderr_tail": with_solution["stderr"][-2000:] if with_solution["stderr"] else "",
        }

        if with_solution["timed_out"]:
            issues.append("Tests timed out with solution applied.")
        elif with_solution["exit_code"] != 0:
            issues.append(
                f"Tests FAILED with solution applied (exit {with_solution['exit_code']}) — "
                "solution.sh does not fix the task."
            )
        else:
            tests_pass_with_solution = True
            print("    Tests correctly pass with solution.")

    finally:
        if cleanup:
            _cleanup_image(tag)

    passed = image_builds and tests_fail_without_solution and tests_pass_with_solution

    return {
        "passed": passed,
        "image_builds": image_builds,
        "tests_fail_without_solution": tests_fail_without_solution,
        "tests_pass_with_solution": tests_pass_with_solution,
        "issues": issues,
        "details": details,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Docker-based functional validation for Terminal Bench tasks."
    )
    parser.add_argument("task_dir", help="Path to the task directory")
    parser.add_argument(
        "--build-timeout", type=int, default=300,
        help="Docker build timeout in seconds (default: 300)",
    )
    parser.add_argument(
        "--test-timeout", type=int, default=120,
        help="Test execution timeout in seconds (default: 120)",
    )
    parser.add_argument(
        "--no-cleanup", action="store_true",
        help="Keep the Docker image after validation",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    result = docker_validate(
        task_dir=args.task_dir,
        build_timeout=args.build_timeout,
        test_timeout=args.test_timeout,
        cleanup=not args.no_cleanup,
    )

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print()
        if result["passed"]:
            print("PASSED: All functional checks passed.")
        else:
            print("FAILED:")
            for issue in result["issues"]:
                print(f"  - {issue}")

        print()
        print(f"  Image builds:                 {'yes' if result['image_builds'] else 'NO'}")
        print(f"  Tests fail without solution:  {'yes' if result['tests_fail_without_solution'] else 'NO'}")
        print(f"  Tests pass with solution:     {'yes' if result['tests_pass_with_solution'] else 'NO'}")

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
