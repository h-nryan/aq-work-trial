import subprocess
import os

def run_cpp_program(input_data):
    """Compile and run the C++ matrix multiplication program with given input."""
    try:
        compile_result = subprocess.run([
            'g++', '-std=c++17', '-o', 'matrix_program', '/app/buggy.cpp'
        ], capture_output=True, text=True, timeout=30)
        if compile_result.returncode != 0:
            return f"Compilation failed: {compile_result.stderr}", 1

        process = subprocess.run(
            ['./matrix_program'],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=10
        )
        return process.stdout.strip(), process.returncode
    except subprocess.TimeoutExpired:
        return "Program timed out", 1
    except Exception as e:
        return f"Execution error: {str(e)}", 1

def test_exists_and_compiles():
    """Check that the C++ source file exists and compiles without errors."""
    assert os.path.exists('/app/buggy.cpp'), "C++ source file not found"
    result = subprocess.run([
        'g++', '-std=c++17', '-fsyntax-only', '/app/buggy.cpp'
    ], capture_output=True, text=True)
    assert result.returncode == 0, f"Syntax check failed: {result.stderr}"

def test_normal_multiplication():
    """Test standard 2x3 * 3x2 matrix multiplication."""
    input_data = "2 3\n3 2\n1 2 3\n4 5 6\n7 8\n9 10\n11 12"
    expected_output = "58 64\n139 154"
    output, returncode = run_cpp_program(input_data)
    assert returncode == 0
    assert output == expected_output

def test_invalid_dimensions():
    """Check behavior when matrix dimensions are incompatible for multiplication."""
    input_data = "2 3\n2 2\n1 2 3\n4 5 6\n7 8\n9 10"
    expected_output = "Matrix multiplication not possible"
    output, returncode = run_cpp_program(input_data)
    assert returncode == 0
    assert output == expected_output

def test_single_element():
    """Test multiplication of 1x1 matrices (scalar multiplication)."""
    input_data = "1 1\n1 1\n5\n-3"
    expected_output = "-15"
    output, returncode = run_cpp_program(input_data)
    assert returncode == 0
    assert output == expected_output

def test_negative_numbers():
    """Test multiplication with negative numbers to ensure correct arithmetic."""
    input_data = "2 2\n2 2\n1 -2\n-3 4\n5 6\n-7 8"
    expected_output = "19 -10\n-43 14"
    output, returncode = run_cpp_program(input_data)
    assert returncode == 0
    assert output == expected_output

def test_matrices_with_zeros():
    """Test matrices containing zeros to check correct summation in multiplication."""
    input_data = "3 2\n2 3\n1 0\n0 1\n1 1\n0 0 0\n0 0 0"
    expected_output = "0 0 0\n0 0 0\n0 0 0"
    output, returncode = run_cpp_program(input_data)
    assert returncode == 0
    assert output == expected_output

def test_larger_matrix():
    """Test multiplication of larger 3x3 matrices."""
    input_data = "3 3\n3 3\n1 2 3\n4 5 6\n7 8 9\n9 8 7\n6 5 4\n3 2 1"
    expected_output = "30 24 18\n84 69 54\n138 114 90"
    output, returncode = run_cpp_program(input_data)
    assert returncode == 0
    assert output == expected_output


def test_row_times_column():
    """Test multiplication of a 1x3 row matrix with a 3x1 column matrix (dot product)."""
    input_data = "1 3\n3 1\n1 2 3\n4\n5\n6"
    expected_output = "32"
    output, returncode = run_cpp_program(input_data)
    assert returncode == 0
    assert output == expected_output
