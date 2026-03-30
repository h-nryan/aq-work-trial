import subprocess
import os
import re

def compile_program():
    """Compile the C program and return success status."""
    result = subprocess.run(['make', 'clean'], capture_output=True, text=True, cwd='/app')
    result = subprocess.run(['make'], capture_output=True, text=True, cwd='/app')
    return result.returncode == 0, result.stderr

def run_program(timeout=5):
    """Run the compiled program and return output."""
    result = subprocess.run(
        ['./list_program'],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd='/app'
    )
    return result.stdout, result.stderr, result.returncode

def run_valgrind(timeout=15):
    """Run the program under valgrind to check for memory errors."""
    result = subprocess.run(
        ['valgrind', '--leak-check=full', '--error-exitcode=1', '--errors-for-leak-kinds=definite', './list_program'],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd='/app'
    )
    return result.stdout + result.stderr, result.returncode

def test_program_compiles():
    """Test that the program compiles successfully."""
    success, stderr = compile_program()
    assert success, f"Program failed to compile: {stderr}"

def test_program_runs_without_crash():
    """Test that the program runs without crashing."""
    compile_program()
    try:
        stdout, stderr, returncode = run_program()
        assert returncode == 0, f"Program crashed with return code {returncode}\nStderr: {stderr}"
    except subprocess.TimeoutExpired:
        assert False, "Program timed out (likely infinite loop in reverse function)"

def test_append_operations():
    """Test that append operations produce correct output."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    assert "Testing append operations:" in stdout
    assert "10 -> 20 -> 30" in stdout, "Append operations should create list: 10 -> 20 -> 30"

def test_prepend_operation():
    """Test that prepend operation works correctly."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    assert "Testing prepend operation:" in stdout
    assert "5 -> 10 -> 20 -> 30" in stdout, "After prepend, list should be: 5 -> 10 -> 20 -> 30"

def test_list_length():
    """Test that get_length returns correct count."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    assert "List length: 4" in stdout, "List should have length 4 after prepend"

def test_find_operation():
    """Test that find_node locates correct value."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    assert "Found node with value: 20" in stdout, "Should find node with value 20"

def test_delete_operation():
    """Test that delete removes correct node."""
    compile_program()
    stdout, stderr, returncode = run_program()
    
    assert "Testing delete operation" in stdout
    # After deleting 5, list should be 10 -> 20 -> 30
    lines = stdout.split('\n')
    delete_section = False
    for i, line in enumerate(lines):
        if "Testing delete operation" in line:
            delete_section = True
        if delete_section and "10 -> 20 -> 30" in line:
            assert True
            return
    assert False, "After deleting 5, list should be: 10 -> 20 -> 30"

def test_reverse_operation():
    """Test that reverse operation works without hanging."""
    compile_program()
    try:
        stdout, stderr, returncode = run_program(timeout=5)
        assert "Testing reverse operation:" in stdout
        assert "30 -> 20 -> 10" in stdout, "After reverse, list should be: 30 -> 20 -> 10"
    except subprocess.TimeoutExpired:
        assert False, "Reverse operation caused infinite loop (missing current = next)"

def test_no_memory_leaks():
    """Test that the program has no memory leaks."""
    compile_program()
    try:
        valgrind_output, returncode = run_valgrind(timeout=20)
        
        # Check for memory leaks
        assert "definitely lost: 0 bytes in 0 blocks" in valgrind_output or \
               "All heap blocks were freed" in valgrind_output, \
               f"Memory leaks detected. Check delete_value for missing free()\n{valgrind_output}"
    except subprocess.TimeoutExpired:
        assert False, "Valgrind timed out (program likely has infinite loop)"

def test_no_use_after_free():
    """Test that there are no use-after-free errors."""
    compile_program()
    try:
        valgrind_output, returncode = run_valgrind(timeout=20)
        
        # Check for invalid reads/writes
        assert "Invalid read" not in valgrind_output, \
               f"Use-after-free detected. Check free_list for accessing freed memory\n{valgrind_output}"
        assert "Invalid write" not in valgrind_output, \
               f"Invalid write detected\n{valgrind_output}"
    except subprocess.TimeoutExpired:
        assert False, "Valgrind timed out"

def test_valgrind_clean():
    """Test that valgrind reports no errors."""
    compile_program()
    try:
        valgrind_output, returncode = run_valgrind(timeout=20)
        
        # Valgrind should exit with 0 if no errors
        assert returncode == 0, \
               f"Valgrind detected memory errors\n{valgrind_output}"
    except subprocess.TimeoutExpired:
        assert False, "Valgrind timed out"
