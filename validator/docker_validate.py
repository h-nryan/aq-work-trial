"""
Docker-based functional validator for generated tasks.

Validates that:
1. The Docker image builds successfully
2. Tests FAIL on an unsolved container (no solution applied)
3. Tests PASS after solution.sh is applied
4. Solution is idempotent (re-running solution + tests still passes)
5. Tests are deterministic (3 total passing runs required)

Also performs sanity checks on instruction length, file sizes,
and Docker image size, and tracks execution timing per phase.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import yaml


def _log(msg: str) -> None:
    """Print progress messages to stderr so they don't corrupt --json output."""
    print(msg, file=sys.stderr)


TBENCH_BASE_IMAGE = "tbench-base:latest"
_base_image_checked = False


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


def ensure_base_image() -> bool:
    """Ensure the tbench-base Docker image exists, building it if needed.

    The base image pre-installs common dependencies (python3, gcc, tmux, uv, etc.)
    so per-task builds only need to COPY files — reducing build time from ~60s to ~2s.
    This makes high concurrency (12+ tasks) feasible.

    Returns True if the image is available, False on failure.
    """
    global _base_image_checked
    if _base_image_checked:
        return True

    # Check if image already exists
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", TBENCH_BASE_IMAGE],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            _base_image_checked = True
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

    # Build from Dockerfile.base
    base_dockerfile = Path(__file__).parent / "Dockerfile.base"
    if not base_dockerfile.exists():
        _log(f"WARNING: {base_dockerfile} not found, cannot build base image")
        return False

    _log("Building tbench-base image (one-time setup)...")
    try:
        result = subprocess.run(
            ["docker", "build", "-t", TBENCH_BASE_IMAGE, "-f", str(base_dockerfile), "."],
            cwd=str(base_dockerfile.parent.parent),  # project root
            capture_output=True, text=True,
            timeout=600,
        )
        if result.returncode == 0:
            _base_image_checked = True
            _log("tbench-base image built successfully")
            return True
        else:
            _log(f"WARNING: Failed to build tbench-base: {result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        _log("WARNING: tbench-base build timed out")
        return False


def _rewrite_dockerfile_for_base(task_dir: Path) -> bool:
    """Rewrite a task's Dockerfile to use tbench-base instead of ubuntu.

    Replaces the FROM + apt-get layer with FROM tbench-base, keeping all
    COPY/WORKDIR/RUN/CMD instructions. Returns True if rewritten.
    """
    dockerfile = task_dir / "Dockerfile"
    if not dockerfile.exists():
        return False

    content = dockerfile.read_text()

    # Rewrite any standard base image (ubuntu, python, debian) to use our pre-built base
    rewritable_bases = ("FROM ubuntu:", "FROM python:", "FROM debian:")
    if not any(
        any(stripped.startswith(base) for base in rewritable_bases)
        for stripped in (line.strip() for line in content.splitlines())
    ):
        return False

    lines = content.splitlines()
    new_lines = []
    skip_apt = False

    for line in lines:
        stripped = line.strip()

        # Replace any rewritable base with our base
        if any(stripped.startswith(base) for base in rewritable_bases):
            new_lines.append(f"FROM {TBENCH_BASE_IMAGE}")
            continue

        # Skip apt-get and pip install lines (already in base image)
        if stripped.startswith("RUN apt-get") or stripped.startswith("RUN pip"):
            # Only enter multi-line skip if this line has a continuation
            skip_apt = stripped.endswith("\\")
            continue
        if skip_apt:
            # Multi-line RUN: skip continuation lines (ending with \)
            if stripped.endswith("\\"):
                continue
            else:
                # Last line of the multi-line RUN
                skip_apt = False
                continue

        # Skip DEBIAN_FRONTEND (already in base)
        if "DEBIAN_FRONTEND" in stripped:
            continue

        new_lines.append(line)

    # Remove leading blank lines after FROM
    while len(new_lines) > 1 and new_lines[1].strip() == "":
        new_lines.pop(1)

    dockerfile.write_text("\n".join(new_lines) + "\n")
    return True


def _rewrite_run_tests_for_base(task_dir: Path) -> bool:
    """Strip redundant apt-get/pip/uv-install lines from run-tests.sh.

    When using the tbench-base image, curl, uv, python3, pip, gcc, cmake etc.
    are already installed. The generated run-tests.sh scripts often start with
    ``apt-get update && apt-get install -y curl`` followed by a uv install,
    which are slow and cause timeouts under concurrency. This strips those
    lines (and their continuations) so tests start instantly.

    Returns True if the file was modified.
    """
    run_tests = task_dir / "run-tests.sh"
    if not run_tests.exists():
        return False

    content = run_tests.read_text()

    lines = content.splitlines()
    new_lines = []
    skip_continuation = False

    for line in lines:
        stripped = line.strip()

        # Skip continuation lines from a previous multi-line command
        if skip_continuation:
            if stripped.endswith("\\"):
                continue
            else:
                skip_continuation = False
                continue

        # Skip apt-get install/update lines (already in base image)
        if stripped.startswith("apt-get ") or stripped.startswith("sudo apt-get "):
            skip_continuation = stripped.endswith("\\")
            continue

        # Skip curl-based uv installer (uv already in base image)
        if "astral.sh/uv" in stripped or "curl -LsSf" in stripped and "uv" in stripped:
            skip_continuation = stripped.endswith("\\")
            continue

        # Skip pip install lines (deps in base image)
        if stripped.startswith("pip install") or stripped.startswith("pip3 install"):
            skip_continuation = stripped.endswith("\\")
            continue

        # Skip 'source $HOME/.local/bin/env' (uv env setup, not needed with base)
        if stripped == "source $HOME/.local/bin/env":
            continue

        new_lines.append(line)

    new_content = "\n".join(new_lines) + "\n"
    if new_content != content:
        run_tests.write_text(new_content)
        return True
    return False


def _build_image(task_dir: Path, tag: str, timeout: int = 300, max_retries: int = 2) -> dict:
    """Build Docker image from the task's Dockerfile.

    Returns dict with 'success' bool and 'error' string if failed.
    Retries on transient failures (timeouts, daemon errors).
    """
    last_error = None
    for attempt in range(1 + max_retries):
        try:
            result = subprocess.run(
                ["docker", "build", "-t", tag, "."],
                cwd=str(task_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                error_msg = result.stderr[-2000:]
                # Transient Docker daemon errors → retry
                transient = any(s in error_msg.lower() for s in [
                    "connection refused", "daemon is not running", "temporary failure",
                    "could not resolve", "i/o timeout",
                ])
                if transient and attempt < max_retries:
                    import time as _time
                    _time.sleep(2 ** attempt)
                    continue
                return {
                    "success": False,
                    "error": f"Docker build failed (exit {result.returncode}):\n{error_msg}",
                }
            return {"success": True, "error": None}
        except subprocess.TimeoutExpired:
            last_error = f"Docker build timed out after {timeout}s"
            if attempt < max_retries:
                continue
    return {"success": False, "error": last_error or "Docker build failed after retries"}


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


def _run_solution_and_tests_in_container(
    tag: str,
    task_dir: Path,
    timeout: int = 120,
) -> dict:
    """Run solution.sh then tests in a container. For idempotency testing,
    this runs solution.sh twice before running tests.

    Returns dict with 'exit_code', 'stdout', 'stderr', 'timed_out'.
    """
    tests_dir = task_dir / "tests"
    run_tests = task_dir / "run-tests.sh"
    solution = task_dir / "solution.sh"

    # Run solution twice then test — catches solutions that break on re-run
    shell_cmd = (
        "cp /mnt/solution.sh . && chmod +x solution.sh && "
        "bash solution.sh && bash solution.sh && "
        "export TEST_DIR=/mnt/tests && bash /mnt/run-tests.sh"
    )

    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{run_tests.resolve()}:/mnt/run-tests.sh:ro",
        "-v", f"{tests_dir.resolve()}:/mnt/tests:ro",
        "-v", f"{solution.resolve()}:/mnt/solution.sh:ro",
        tag, "bash", "-c", shell_cmd,
    ]

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


def _get_image_size_mb(tag: str) -> float | None:
    """Get Docker image size in MB using docker image inspect."""
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", tag, "--format", "{{.Size}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            size_bytes = int(result.stdout.strip())
            return round(size_bytes / (1024 * 1024), 1)
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _sanity_checks(task_path: Path) -> list[str]:
    """Run pre-Docker sanity checks on task files.

    Returns a list of issue strings (empty if all checks pass).
    """
    issues = []

    # Check instruction length in task.yaml
    task_yaml = task_path / "task.yaml"
    if task_yaml.exists():
        try:
            with open(task_yaml) as f:
                task_data = yaml.safe_load(f)
            instruction = task_data.get("instruction", "")
            if len(instruction) < 50:
                issues.append(
                    f"task.yaml instruction is too short ({len(instruction)} chars, minimum 50)."
                )
        except Exception as e:
            issues.append(f"Failed to parse task.yaml: {e}")
    else:
        issues.append("task.yaml not found (needed for instruction sanity check).")

    # Check solution.sh size
    solution = task_path / "solution.sh"
    if solution.exists():
        size = solution.stat().st_size
        if size < 10:
            issues.append(
                f"solution.sh is too small ({size} bytes, minimum 10) — likely empty or trivial."
            )
    # Missing solution.sh is caught by the required-files check upstream.

    # Check run-tests.sh size
    run_tests = task_path / "run-tests.sh"
    if run_tests.exists():
        size = run_tests.stat().st_size
        if size < 10:
            issues.append(
                f"run-tests.sh is too small ({size} bytes, minimum 10) — likely empty or trivial."
            )

    return issues


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
    skip_extended: bool = False,
) -> dict:
    """Run full Docker-based functional validation on a task.

    Args:
        task_dir: Path to the task directory.
        build_timeout: Max seconds for Docker build.
        test_timeout: Max seconds for each test run.
        cleanup: Whether to remove the Docker image after validation.
        skip_extended: Skip idempotency and determinism checks (quick mode).

    Returns:
        dict with:
            passed: bool — True only if all critical checks pass
            image_builds: bool
            tests_fail_without_solution: bool
            tests_pass_with_solution: bool
            solution_idempotent: bool or None (if skipped)
            tests_deterministic: bool or None (if skipped)
            image_size_mb: float or None
            execution_times: dict of phase -> seconds
            issues: list of strings describing failures
            warnings: list of non-fatal warnings
            details: dict with stdout/stderr from each phase
    """
    task_path = Path(task_dir).resolve()
    issues = []
    warnings = []
    details = {}
    execution_times = {}

    # Default result structure
    result_template = {
        "passed": False,
        "image_builds": False,
        "tests_fail_without_solution": False,
        "tests_pass_with_solution": False,
        "solution_idempotent": None,
        "tests_deterministic": None,
        "image_size_mb": None,
        "execution_times": execution_times,
        "issues": issues,
        "warnings": warnings,
        "details": details,
    }

    # Pre-flight checks
    if not task_path.is_dir():
        issues.append(f"Task directory not found: {task_dir}")
        return result_template

    required = ["Dockerfile", "run-tests.sh", "solution.sh", "tests"]
    for name in required:
        p = task_path / name
        if not p.exists():
            issues.append(f"Missing required path: {name}")
    if issues:
        return result_template

    # Sanity checks (before Docker phases)
    sanity_issues = _sanity_checks(task_path)
    if sanity_issues:
        issues.extend(sanity_issues)
        return result_template

    if not _docker_available():
        issues.append("Docker is not available. Ensure Docker Desktop is running.")
        return result_template

    # Generate a unique tag for this validation run
    task_name = task_path.name
    tag = f"tbench-validate-{task_name}:{int(time.time())}"

    total_phases = 3 if skip_extended else 5

    image_builds = False
    tests_fail_without_solution = False
    tests_pass_with_solution = False
    solution_idempotent = None
    tests_deterministic = None

    try:
        # Rewrite Dockerfile to use tbench-base if available (speeds up builds)
        if ensure_base_image():
            _rewrite_dockerfile_for_base(task_path)
            _rewrite_run_tests_for_base(task_path)

        # Phase 1: Build the Docker image
        _log(f"[1/{total_phases}] Building Docker image for '{task_name}'...")
        t0 = time.monotonic()
        build_result = _build_image(task_path, tag, timeout=build_timeout)
        execution_times["build"] = round(time.monotonic() - t0, 2)
        details["build"] = build_result

        if not build_result["success"]:
            issues.append(f"Docker image build failed: {build_result['error']}")
            return result_template

        image_builds = True
        result_template["image_builds"] = True
        _log(f"    Image built successfully. ({execution_times['build']}s)")

        # Dockerfile hygiene: check image size
        image_size = _get_image_size_mb(tag)
        result_template["image_size_mb"] = image_size
        if image_size is not None:
            if image_size > 2048:
                issues.append(
                    f"Docker image is too large ({image_size} MB, maximum 2048 MB)."
                )
                return result_template
            elif image_size > 1024:
                warnings.append(
                    f"Docker image is large ({image_size} MB). Consider optimizing to stay under 1 GB."
                )

        # Phase 2: Tests must FAIL without solution
        _log(f"[2/{total_phases}] Running tests WITHOUT solution (expecting failure)...")
        t0 = time.monotonic()
        no_solution = _run_tests_in_container(
            tag, task_path, apply_solution=False, timeout=test_timeout,
        )
        execution_times["test_without_solution"] = round(time.monotonic() - t0, 2)
        details["without_solution"] = {
            "exit_code": no_solution["exit_code"],
            "timed_out": no_solution["timed_out"],
            "stdout_tail": no_solution["stdout"][-2000:] if no_solution["stdout"] else "",
            "stderr_tail": no_solution["stderr"][-2000:] if no_solution["stderr"] else "",
        }

        if no_solution["timed_out"]:
            # Timeout counts as a valid failure — buggy code may hang due to
            # infinite loops, deadlocks, or memory corruption.
            tests_fail_without_solution = True
            result_template["tests_fail_without_solution"] = True
            _log(f"    Tests timed out without solution (valid failure). ({execution_times['test_without_solution']}s)")
        elif no_solution["exit_code"] == 0:
            issues.append(
                "Tests PASSED without solution — task is broken (tests should fail on unsolved container)."
            )
        else:
            tests_fail_without_solution = True
            result_template["tests_fail_without_solution"] = True
            _log(f"    Tests correctly fail without solution. ({execution_times['test_without_solution']}s)")

        # Phase 3: Tests must PASS with solution
        _log(f"[3/{total_phases}] Running tests WITH solution (expecting pass)...")
        t0 = time.monotonic()
        with_solution = _run_tests_in_container(
            tag, task_path, apply_solution=True, timeout=test_timeout,
        )
        execution_times["test_with_solution"] = round(time.monotonic() - t0, 2)
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
            result_template["tests_pass_with_solution"] = True
            _log(f"    Tests correctly pass with solution. ({execution_times['test_with_solution']}s)")

            if execution_times["test_with_solution"] > 60:
                warnings.append(
                    f"Test execution with solution took {execution_times['test_with_solution']}s "
                    "(over 60s). This will be expensive during batch evaluation."
                )

        # Extended checks (only if basic checks passed and not skipped)
        if not skip_extended and tests_pass_with_solution:
            # Phase 4: Solution idempotency
            _log(f"[4/{total_phases}] Checking solution idempotency (re-running solution + tests)...")
            t0 = time.monotonic()
            idempotency_result = _run_solution_and_tests_in_container(
                tag, task_path, timeout=test_timeout,
            )
            execution_times["idempotency"] = round(time.monotonic() - t0, 2)
            details["idempotency"] = {
                "exit_code": idempotency_result["exit_code"],
                "timed_out": idempotency_result["timed_out"],
                "stdout_tail": idempotency_result["stdout"][-2000:] if idempotency_result["stdout"] else "",
                "stderr_tail": idempotency_result["stderr"][-2000:] if idempotency_result["stderr"] else "",
            }

            if idempotency_result["timed_out"]:
                issues.append("Idempotency check timed out.")
                solution_idempotent = False
            elif idempotency_result["exit_code"] != 0:
                issues.append(
                    "Solution is NOT idempotent — tests fail after running solution.sh a second time."
                )
                solution_idempotent = False
            else:
                solution_idempotent = True
                _log(f"    Solution is idempotent. ({execution_times['idempotency']}s)")

            result_template["solution_idempotent"] = solution_idempotent

            # Phase 5: Test determinism (2 additional runs, 3 total with phase 3)
            _log(f"[5/{total_phases}] Checking test determinism (2 additional runs)...")
            determinism_pass_count = 0
            t0 = time.monotonic()
            for i in range(2):
                det_result = _run_tests_in_container(
                    tag, task_path, apply_solution=True, timeout=test_timeout,
                )
                if det_result["exit_code"] == 0 and not det_result["timed_out"]:
                    determinism_pass_count += 1

            execution_times["determinism"] = round(time.monotonic() - t0, 2)

            if determinism_pass_count == 2:
                tests_deterministic = True
                _log(f"    Tests are deterministic (3/3 runs passed). ({execution_times['determinism']}s)")
            else:
                tests_deterministic = False
                total_passed = 1 + determinism_pass_count  # 1 from phase 3
                issues.append(
                    f"Tests are NOT deterministic — only {total_passed}/3 runs passed."
                )

            result_template["tests_deterministic"] = tests_deterministic

    finally:
        if cleanup:
            _cleanup_image(tag)

    # passed requires all critical checks. Image size warning is non-critical.
    passed = image_builds and tests_fail_without_solution and tests_pass_with_solution
    if not skip_extended:
        passed = passed and (solution_idempotent is True) and (tests_deterministic is True)

    result_template["passed"] = passed
    return result_template


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
        "--skip-extended", action="store_true",
        help="Skip idempotency and determinism checks (quick validation)",
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
        skip_extended=args.skip_extended,
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

        if result["warnings"]:
            print()
            print("WARNINGS:")
            for warning in result["warnings"]:
                print(f"  - {warning}")

        print()
        print(f"  Image builds:                 {'yes' if result['image_builds'] else 'NO'}")
        print(f"  Tests fail without solution:  {'yes' if result['tests_fail_without_solution'] else 'NO'}")
        print(f"  Tests pass with solution:     {'yes' if result['tests_pass_with_solution'] else 'NO'}")

        if result["solution_idempotent"] is not None:
            print(f"  Solution idempotent:          {'yes' if result['solution_idempotent'] else 'NO'}")
        if result["tests_deterministic"] is not None:
            print(f"  Tests deterministic:          {'yes' if result['tests_deterministic'] else 'NO'}")

        if result["image_size_mb"] is not None:
            print(f"  Image size:                   {result['image_size_mb']} MB")

        if result["execution_times"]:
            print()
            print("  Execution times:")
            for phase, seconds in result["execution_times"].items():
                print(f"    {phase}: {seconds}s")

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
