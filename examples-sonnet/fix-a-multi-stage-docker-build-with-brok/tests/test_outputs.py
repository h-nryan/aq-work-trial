import json
import subprocess
import os
from pathlib import Path


def read_json(path):
    """Read and parse JSON from file path."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def test_basic_jsonl_processing():
    """Test that basic JSONL with integer values is processed correctly."""
    result = read_json('/tmp/test_data/output1.json')
    
    assert 'average' in result, "Output missing 'average' field"
    assert 'total' in result, "Output missing 'total' field"
    assert 'count' in result, "Output missing 'count' field"
    
    assert result['count'] == 3, f"Expected count=3, got {result['count']}"
    assert result['total'] == 60.0, f"Expected total=60.0, got {result['total']}"
    assert result['average'] == 20.0, f"Expected average=20.0, got {result['average']}"


def test_string_number_conversion():
    """Test that string numbers are converted to floats correctly."""
    result = read_json('/tmp/test_data/output2.json')
    
    assert result['count'] == 2, f"Expected count=2, got {result['count']}"
    assert result['total'] == 41.0, f"Expected total=41.0, got {result['total']}"
    assert result['average'] == 20.5, f"Expected average=20.5, got {result['average']}"


def test_unicode_preservation():
    """Test that unicode characters are preserved in processing."""
    # The output should be valid JSON and the script should not crash on unicode
    result = read_json('/tmp/test_data/output3.json')
    
    assert result['count'] == 3, f"Expected count=3, got {result['count']}"
    assert result['total'] == 600.0, f"Expected total=600.0, got {result['total']}"
    assert result['average'] == 200.0, f"Expected average=200.0, got {result['average']}"


def test_missing_value_fields():
    """Test that records without 'value' field are skipped correctly."""
    result = read_json('/tmp/test_data/output4.json')
    
    # Only one record has a value field (value=50)
    assert result['count'] == 1, f"Expected count=1, got {result['count']}"
    assert result['total'] == 50.0, f"Expected total=50.0, got {result['total']}"
    assert result['average'] == 50.0, f"Expected average=50.0, got {result['average']}"


def test_output_is_valid_json():
    """Test that all output files are valid JSON."""
    for i in range(1, 5):
        output_file = f'/tmp/test_data/output{i}.json'
        assert os.path.exists(output_file), f"Output file {output_file} does not exist"
        
        try:
            with open(output_file, 'r') as f:
                json.load(f)
        except json.JSONDecodeError as e:
            assert False, f"Output file {output_file} is not valid JSON: {e}"


def test_script_handles_jsonl_format():
    """Test that the script correctly reads JSONL format (multiple JSON objects)."""
    # Create a test JSONL file
    test_input = '/tmp/test_jsonl_format.jsonl'
    test_output = '/tmp/test_jsonl_format.json'
    
    with open(test_input, 'w') as f:
        f.write('{"value": 5}\n')
        f.write('{"value": 10}\n')
        f.write('{"value": 15}\n')
    
    result = subprocess.run(
        ['python3', '/app/app.py', test_input, test_output],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    
    output = read_json(test_output)
    assert output['count'] == 3, "Failed to read all JSONL records"
    assert output['total'] == 30.0, "Incorrect total from JSONL"
    assert output['average'] == 10.0, "Incorrect average from JSONL"


def test_float_division_not_integer():
    """Test that division produces float results, not integer division."""
    # Create test with values that would show integer division bug
    test_input = '/tmp/test_division.jsonl'
    test_output = '/tmp/test_division.json'
    
    with open(test_input, 'w') as f:
        f.write('{"value": 5}\n')
        f.write('{"value": 4}\n')
    
    subprocess.run(
        ['python3', '/app/app.py', test_input, test_output],
        capture_output=True,
        text=True
    )
    
    output = read_json(test_output)
    # 5 + 4 = 9, 9 / 2 = 4.5 (not 4 with integer division)
    assert output['average'] == 4.5, f"Expected 4.5, got {output['average']} - integer division bug"


def test_empty_input_handling():
    """Test that empty input produces correct zero statistics."""
    test_input = '/tmp/test_empty.jsonl'
    test_output = '/tmp/test_empty.json'
    
    # Create empty file
    Path(test_input).touch()
    
    result = subprocess.run(
        ['python3', '/app/app.py', test_input, test_output],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "Script should handle empty input"
    
    output = read_json(test_output)
    assert output['count'] == 0, "Empty input should have count=0"
    assert output['total'] == 0, "Empty input should have total=0"
    assert output['average'] == 0, "Empty input should have average=0"


def test_mixed_numeric_types():
    """Test that both integer and float values are handled correctly."""
    test_input = '/tmp/test_mixed.jsonl'
    test_output = '/tmp/test_mixed.json'
    
    with open(test_input, 'w') as f:
        f.write('{"value": 10}\n')      # int
        f.write('{"value": 15.5}\n')    # float
        f.write('{"value": "20"}\n')   # string int
        f.write('{"value": "25.5"}\n') # string float
    
    subprocess.run(
        ['python3', '/app/app.py', test_input, test_output],
        capture_output=True,
        text=True
    )
    
    output = read_json(test_output)
    assert output['count'] == 4, "Should process all numeric types"
    assert output['total'] == 71.0, f"Expected total=71.0, got {output['total']}"
    assert output['average'] == 17.75, f"Expected average=17.75, got {output['average']}"
