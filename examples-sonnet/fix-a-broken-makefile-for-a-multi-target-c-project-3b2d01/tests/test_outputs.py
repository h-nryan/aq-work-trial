import subprocess
import os
import time
from pathlib import Path


def run_make(target="all", cwd="/app"):
    """Run make with specified target and return result."""
    result = subprocess.run(
        ["make", target],
        capture_output=True,
        text=True,
        cwd=cwd
    )
    return result.stdout, result.stderr, result.returncode


def test_makefile_builds_successfully():
    """Test that the Makefile can build the program without errors."""
    run_make("clean")
    
    stdout, stderr, returncode = run_make("all")
    
    assert returncode == 0, f"Make failed with return code {returncode}\nStderr: {stderr}\nStdout: {stdout}"
    assert Path("/app/bin/app").exists(), "Executable 'bin/app' was not created"


def test_program_runs_correctly():
    """Test that the compiled program runs and produces correct output."""
    run_make("clean")
    run_make("all")
    
    result = subprocess.run(
        ["./bin/app"],
        capture_output=True,
        text=True,
        cwd="/app"
    )
    
    assert result.returncode == 0, f"Program failed with return code {result.returncode}"
    assert "Starting application" in result.stdout, "Expected startup message not found"
    assert "Parsing input" in result.stdout, "Parser output not found"
    assert "Average:" in result.stdout, "Average calculation output not found"
    assert "Sum:" in result.stdout, "Sum calculation output not found"
    assert "Application finished successfully" in result.stdout, "Program did not finish successfully"


def test_make_clean_removes_artifacts():
    """Test that 'make clean' removes all build artifacts."""
    run_make("all")
    
    assert Path("/app/obj").exists() or Path("/app/bin").exists(), "No artifacts to clean"
    
    stdout, stderr, returncode = run_make("clean")
    
    assert returncode == 0, f"Make clean failed: {stderr}"
    assert not Path("/app/obj").exists(), "obj directory was not removed"
    assert not Path("/app/bin").exists(), "bin directory was not removed"


def test_phony_targets_work_with_files():
    """Test that phony targets work even when files with those names exist."""
    Path("/app/clean").touch()
    Path("/app/test").touch()
    Path("/app/all").touch()
    
    stdout, stderr, returncode = run_make("all")
    assert returncode == 0, "Build failed when file named 'all' exists"
    
    run_make("clean")
    assert Path("/app/clean").exists(), "Phony target 'clean' removed the file named 'clean'"
    
    Path("/app/clean").unlink()
    Path("/app/test").unlink()
    Path("/app/all").unlink()


def test_make_test_target_runs_program():
    """Test that 'make test' builds and runs the program."""
    run_make("clean")
    
    stdout, stderr, returncode = run_make("test")
    
    assert returncode == 0, f"Make test failed: {stderr}"
    output = stdout + stderr
    assert "Starting application" in output, "Program did not run during 'make test'"


def test_math_library_linking():
    """Test that the math library is properly linked."""
    run_make("clean")
    stdout, stderr, returncode = run_make("all")
    
    assert returncode == 0, f"Build failed, possibly due to missing -lm flag: {stderr}"
    
    result = subprocess.run(
        ["./bin/app"],
        capture_output=True,
        text=True,
        cwd="/app"
    )
    
    assert result.returncode == 0, "Program failed to run, possibly due to missing math library"
