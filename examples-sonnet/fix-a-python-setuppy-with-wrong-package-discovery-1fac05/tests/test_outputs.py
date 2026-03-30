import subprocess
import json
import sys
import os

def run_processor(args):
    """Run the data processor with given arguments."""
    cmd = ['python3', '/app/src/processor.py'] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def test_basic_processing():
    """Test that the processor can read and aggregate data."""
    stdout, stderr, returncode = run_processor(['/tmp/test_data/transactions.csv'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    data = json.loads(stdout)
    
    assert isinstance(data, dict), "Output should be a JSON object"
    assert 'food' in data, "Should have food category"
    assert 'transport' in data, "Should have transport category"
    assert 'entertainment' in data, "Should have entertainment category"

def test_date_range_filtering():
    """Test that date range filtering works correctly with inclusive bounds."""
    stdout, stderr, returncode = run_processor([
        '/tmp/test_data/transactions.csv',
        '--start', '2024-01-17',
        '--end', '2024-01-22'
    ])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    data = json.loads(stdout)
    
    # Should include: 2024-01-17 (food 32.75), 2024-01-18 (entertainment 25.00),
    # 2024-01-20 (food 18.50), 2024-01-22 (transport 15.00)
    assert 'food' in data, "Should have food category in range"
    assert abs(data['food'] - 51.25) < 0.01, f"Food total should be 51.25, got {data['food']}"
    assert 'entertainment' in data, "Should have entertainment category"
    assert abs(data['entertainment'] - 25.00) < 0.01, "Entertainment should be 25.00"
    assert 'transport' in data, "Should have transport category"
    assert abs(data['transport'] - 15.00) < 0.01, "Transport should be 15.00"

def test_start_date_inclusive():
    """Test that start date is inclusive in filtering."""
    stdout, stderr, returncode = run_processor([
        '/tmp/test_data/transactions.csv',
        '--start', '2024-01-15',
        '--end', '2024-01-15'
    ])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    data = json.loads(stdout)
    
    # Should include 2024-01-15 (food 45.50)
    assert 'food' in data, "Should include start date transaction"
    assert abs(data['food'] - 45.50) < 0.01, f"Should include transaction from start date, got {data['food']}"

def test_json_output_sorted():
    """Test that JSON output has sorted keys for consistency."""
    stdout, stderr, returncode = run_processor(['/tmp/test_data/transactions.csv'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    
    # Parse and check that keys appear in sorted order in the string
    lines = stdout.strip().split('\n')
    keys_in_output = []
    for line in lines:
        if '":' in line:
            key = line.split('"')[1]
            keys_in_output.append(key)
    
    assert keys_in_output == sorted(keys_in_output), "JSON keys should be sorted alphabetically"



def test_end_date_filtering():
    """Test that end date filtering works correctly."""
    stdout, stderr, returncode = run_processor([
        '/tmp/test_data/transactions.csv',
        '--end', '2024-01-18'
    ])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    data = json.loads(stdout)
    
    # Should include up to and including 2024-01-18
    # 2024-01-15 (food 45.50), 2024-01-16 (transport 12.00),
    # 2024-01-17 (food 32.75), 2024-01-18 (entertainment 25.00)
    assert 'food' in data
    assert abs(data['food'] - 78.25) < 0.01, f"Food should be 78.25, got {data['food']}"
    assert 'transport' in data
    assert abs(data['transport'] - 12.00) < 0.01, "Transport should be 12.00"

def test_category_aggregation():
    """Test that amounts are correctly aggregated by category."""
    stdout, stderr, returncode = run_processor(['/tmp/test_data/transactions.csv'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    data = json.loads(stdout)
    
    # Total food: 45.50 + 32.75 + 18.50 + 55.25 = 152.00
    assert abs(data['food'] - 152.00) < 0.01, f"Food total incorrect: {data['food']}"
    
    # Total transport: 12.00 + 15.00 = 27.00
    assert abs(data['transport'] - 27.00) < 0.01, f"Transport total incorrect: {data['transport']}"
    
    # Total entertainment: 25.00 + 40.00 = 65.00
    assert abs(data['entertainment'] - 65.00) < 0.01, f"Entertainment total incorrect: {data['entertainment']}"
