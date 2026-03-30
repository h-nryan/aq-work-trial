import json
import csv
import os
import subprocess
from pathlib import Path

def read_json(path):
    """Read and parse JSON from file path."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def read_csv_file(path):
    """Read CSV file and return records."""
    records = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records

def test_basic_transformation():
    """Test that basic CSV records are transformed correctly."""
    data = read_json('/tmp/test_data/output1.json')
    
    assert isinstance(data, list), "Output should be a list"
    assert len(data) == 3, f"Expected 3 records, got {len(data)}"
    
    # Check first record structure
    assert 'id' in data[0], "Record should have 'id' field"
    assert 'name' in data[0], "Record should have 'name' field"
    assert 'value' in data[0], "Record should have 'value' field"
    assert 'status' in data[0], "Record should have 'status' field"
    
    # Check values are transformed correctly
    assert data[0]['name'] == 'Alice', "Name should be preserved"
    assert data[0]['value'] == 100.0, "Value should be converted to float"

def test_zero_value_handling():
    """Test that records with zero values are handled correctly."""
    data = read_json('/tmp/test_data/output2.json')
    
    # Should include records with value 0 after fixing the >= bug
    assert len(data) == 2, f"Expected 2 records (including zero), got {len(data)}"
    
    # Check that zero value record exists
    zero_records = [r for r in data if r['value'] == 0.0]
    assert len(zero_records) == 1, "Should include record with value 0"

def test_no_filter_mode():
    """Test that --no-filter flag preserves all records."""
    data = read_json('/tmp/test_data/output3.json')
    
    # With --no-filter, all records should be present
    assert len(data) == 4, f"Expected 4 records with --no-filter, got {len(data)}"
    
    # Check that zero value record is included
    zero_records = [r for r in data if r['value'] == 0.0]
    assert len(zero_records) == 1, "Should include zero value record with --no-filter"

def test_csv_output_format():
    """Test that CSV output format works correctly."""
    assert os.path.exists('/tmp/test_data/output4.csv'), "CSV output file should exist"
    
    records = read_csv_file('/tmp/test_data/output4.csv')
    assert len(records) == 3, f"Expected 3 records in CSV output, got {len(records)}"
    
    # Check that values are present
    assert records[0]['name'] == 'Alice', "CSV should preserve names"
    assert float(records[0]['value']) == 100.0, "CSV should have correct values"

def test_empty_input_handling():
    """Test that empty CSV input is handled gracefully."""
    data = read_json('/tmp/test_data/output5.json')
    
    assert isinstance(data, list), "Output should be a list"
    assert len(data) == 0, f"Empty input should produce empty output, got {len(data)} records"

def test_all_records_processed():
    """Test that no records are silently dropped during transformation."""
    # Run pipeline on input with known record count
    result = subprocess.run(
        ['python3', '/app/pipeline.py', '/tmp/test_data/input1.csv', '/tmp/test_output_test.json'],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "Pipeline should complete successfully"
    
    data = read_json('/tmp/test_output_test.json')
    # All 3 records should be present (all have value > 0)
    assert len(data) == 3, f"Expected all 3 records to be processed, got {len(data)}"

def test_value_type_conversion():
    """Test that string values are converted to float correctly."""
    data = read_json('/tmp/test_data/output3.json')
    
    # Check that all values are floats, not strings
    for record in data:
        assert isinstance(record['value'], (int, float)), f"Value should be numeric, got {type(record['value'])}"
    
    # Check specific float values
    item1 = [r for r in data if r['name'] == 'Item1'][0]
    assert item1['value'] == 25.5, f"Expected 25.5, got {item1['value']}"
