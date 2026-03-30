import subprocess
import os
import time

def compile_program():
    """Compile the C program and return success status."""
    result = subprocess.run(['make', 'clean'], capture_output=True, text=True)
    result = subprocess.run(['make'], capture_output=True, text=True)
    return result.returncode == 0

def run_program():
    """Run the compiled program and return output."""
    result = subprocess.run(['./linkedlist_program'], capture_output=True, text=True, timeout=10)
    return result.stdout, result.stderr, result.returncode

def run_valgrind():
    """Run the program under valgrind to check for memory errors."""
    result = subprocess.run(
        ['valgrind', '--leak-check=full', '--error-exitcode=1', './linkedlist_program'],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout + result.stderr, result.returncode

def test_program_compiles():
    """Test that the program compiles successfully."""
    assert compile_program(), "Program failed to compile"

def test_program_runs_without_crash():
    """Test that the program runs without crashing."""
    compile_program()
    stdout, stderr, returncode = run_program()
    assert returncode == 0, f"Program crashed with return code {returncode}"

def test_basic_operations_output():
    """Test that basic linked list operations produce expected output."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    # Check for key operations in output
    assert "Inserting elements..." in stdout
    assert "List after insertions:" in stdout
    assert "20 -> 10 -> 30 -> 40 -> NULL" in stdout
    assert "Deleting 20..." in stdout
    assert "List after deletion:" in stdout
    assert "10 -> 30 -> 40 -> NULL" in stdout

def test_middle_element_found():
    """Test that finding middle element works correctly."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    assert "Middle element:" in stdout
    # After deletion, list is 10 -> 30 -> 40, middle should be 30
    assert "Middle element: 30" in stdout

def test_reverse_operation():
    """Test that list reversal works correctly."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    assert "Reversing list..." in stdout
    assert "List after reversal:" in stdout
    # After reversal of 10 -> 30 -> 40, should be 40 -> 30 -> 10
    assert "40 -> 30 -> 10 -> NULL" in stdout

def test_cycle_detection():
    """Test that cycle detection works correctly."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    assert "Checking for cycle:" in stdout
    assert "Checking for cycle: No" in stdout

def test_no_memory_leaks():
    """Test that the program has no memory leaks when run with valgrind."""
    compile_program()
    valgrind_output, returncode = run_valgrind()
    
    # Check for memory leak summary
    assert "All heap blocks were freed -- no leaks are possible" in valgrind_output or \
           "definitely lost: 0 bytes in 0 blocks" in valgrind_output, \
           "Memory leaks detected"

def test_no_memory_errors():
    """Test that the program has no memory corruption errors."""
    compile_program()
    valgrind_output, returncode = run_valgrind()
    
    # Valgrind should exit with 0 if no errors
    assert returncode == 0, "Valgrind detected memory errors"
    
    # Check for common memory errors
    assert "Invalid read" not in valgrind_output, "Invalid memory read detected"
    assert "Invalid write" not in valgrind_output, "Invalid memory write detected"
    assert "Conditional jump or move depends on uninitialised value" not in valgrind_output, \
           "Use of uninitialized memory detected"

def test_source_files_exist():
    """Test that all required source files exist."""
    assert os.path.exists('/app/linkedlist.c'), "linkedlist.c not found"
    assert os.path.exists('/app/linkedlist.h'), "linkedlist.h not found"
    assert os.path.exists('/app/main.c'), "main.c not found"
    assert os.path.exists('/app/Makefile'), "Makefile not found"