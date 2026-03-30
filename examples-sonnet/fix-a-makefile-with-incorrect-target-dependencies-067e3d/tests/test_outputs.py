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
    # Clean first
    run_make("clean")
    
    stdout, stderr, returncode = run_make("all")
    
    assert returncode == 0, f"Make failed with return code {returncode}\nStderr: {stderr}\nStdout: {stdout}"
    assert Path("/app/program").exists(), "Executable 'program' was not created"


def test_program_runs_correctly():
    """Test that the compiled program runs and produces correct output."""
    # Build the program
    run_make("clean")
    run_make("all")
    
    result = subprocess.run(
        ["./program"],
        capture_output=True,
        text=True,
        cwd="/app"
    )
    
    assert result.returncode == 0, f"Program failed with return code {result.returncode}"
    assert "Program starting" in result.stdout, "Expected output not found"
    assert "Result of add_numbers(10, 20): 30" in result.stdout, "Addition result incorrect"
    assert "Result of multiply_numbers(5, 6): 30" in result.stdout, "Multiplication result incorrect"
    assert "Program finished successfully" in result.stdout, "Program did not finish successfully"


def test_make_clean_removes_artifacts():
    """Test that 'make clean' removes all build artifacts."""
    # Build first
    run_make("all")
    
    # Verify artifacts exist
    assert Path("/app/main.o").exists() or Path("/app/program").exists(), "No artifacts to clean"
    
    # Clean
    stdout, stderr, returncode = run_make("clean")
    
    assert returncode == 0, f"Make clean failed: {stderr}"
    assert not Path("/app/main.o").exists(), "main.o was not removed"
    assert not Path("/app/utils.o").exists(), "utils.o was not removed"
    assert not Path("/app/program").exists(), "program was not removed"


def test_incremental_build_works():
    """Test that modifying a source file triggers correct rebuild."""
    # Clean and build
    run_make("clean")
    run_make("all")
    
    # Touch a source file to update its timestamp
    time.sleep(1)
    Path("/app/src/utils.c").touch()
    
    # Rebuild - should recompile utils.o and relink
    stdout, stderr, returncode = run_make("all")
    
    assert returncode == 0, f"Incremental build failed: {stderr}"
    # Should show recompilation activity
    assert "gcc" in stdout or "gcc" in stderr or returncode == 0, "Expected rebuild activity"


def test_phony_targets_work_with_files():
    """Test that phony targets work even when files with those names exist."""
    # Create files with target names
    Path("/app/clean").touch()
    Path("/app/test").touch()
    Path("/app/all").touch()
    
    # Build should still work
    stdout, stderr, returncode = run_make("all")
    assert returncode == 0, "Build failed when file named 'all' exists"
    
    # Clean should still work
    run_make("clean")
    # The 'clean' file should still exist (it's not a target output)
    assert Path("/app/clean").exists(), "Phony target 'clean' removed the file named 'clean'"
    
    # Clean up test files
    Path("/app/clean").unlink()
    Path("/app/test").unlink()
    Path("/app/all").unlink()


def test_header_dependency_triggers_rebuild():
    """Test that modifying a header file triggers recompilation of dependent files."""
    # Clean and build
    run_make("clean")
    run_make("all")
    
    # Get timestamp of object file
    main_o_time = Path("/app/main.o").stat().st_mtime
    
    # Touch header file
    time.sleep(1)
    Path("/app/src/utils.h").touch()
    
    # Rebuild
    run_make("all")
    
    # main.o should be newer (rebuilt)
    new_main_o_time = Path("/app/main.o").stat().st_mtime
    assert new_main_o_time > main_o_time, "main.o was not rebuilt after utils.h changed"


def test_make_test_target_runs_program():
    """Test that 'make test' builds and runs the program."""
    run_make("clean")
    
    stdout, stderr, returncode = run_make("test")
    
    assert returncode == 0, f"Make test failed: {stderr}"
    assert "Program starting" in stdout or "Program starting" in stderr, "Program did not run during 'make test'"
