import subprocess
import json
import csv
from io import StringIO

def run_processor(args):
    """Run the CSV processor with given arguments."""
    cmd = ['python3', '/app/csv_processor.py'] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def parse_csv_output(output):
    """Parse CSV output into list of dictionaries."""
    reader = csv.DictReader(StringIO(output))
    return list(reader)

def test_basic_csv_reading():
    """Test that the processor can read and output CSV data."""
    stdout, stderr, returncode = run_processor(['/app/sample_data.csv'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    rows = parse_csv_output(stdout)
    assert len(rows) == 7, f"Expected 7 rows, got {len(rows)}"
    assert 'name' in rows[0], "Output should contain 'name' column"
    assert 'department' in rows[0], "Output should contain 'department' column"

def test_filter_by_department():
    """Test that filtering by department returns correct rows."""
    stdout, stderr, returncode = run_processor(['/app/sample_data.csv', '--filter', 'department', 'Engineering'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    rows = parse_csv_output(stdout)
    assert len(rows) == 3, f"Expected 3 Engineering employees, got {len(rows)}"
    
    for row in rows:
        assert row['department'] == 'Engineering', f"Found non-Engineering employee: {row['name']}"
    
    names = [row['name'] for row in rows]
    assert 'Alice' in names, "Alice should be in Engineering"
    assert 'Bob' in names, "Bob should be in Engineering"
    assert 'Diana' in names, "Diana should be in Engineering"

def test_sum_salary_with_decimals():
    """Test that sum operation preserves decimal precision."""
    stdout, stderr, returncode = run_processor(['/app/sample_data.csv', '--sum', 'salary'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    total = float(stdout.strip())
    
    # Expected: 75000.50 + 65000.00 + 70000.75 + 68000.25 + 72000.00 + 60000.50 + 62000.00 = 472002.00
    expected = 472002.00
    assert abs(total - expected) < 0.01, f"Expected {expected}, got {total}"

def test_sum_filtered_salaries():
    """Test sum operation on filtered data."""
    stdout, stderr, returncode = run_processor(['/app/sample_data.csv', '--filter', 'department', 'Engineering', '--sum', 'salary'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    total = float(stdout.strip())
    
    # Expected: 75000.50 + 65000.00 + 68000.25 = 208000.75
    expected = 208000.75
    assert abs(total - expected) < 0.01, f"Expected {expected} for Engineering salaries, got {total}"



def test_sort_ascending():
    """Test that sorting works in ascending order."""
    stdout, stderr, returncode = run_processor(['/app/sample_data.csv', '--sort', 'age'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    rows = parse_csv_output(stdout)
    
    ages = [int(row['age']) for row in rows]
    assert ages == sorted(ages), f"Ages not sorted ascending: {ages}"
    assert ages[0] == 25, f"Youngest should be 25, got {ages[0]}"
    assert ages[-1] == 35, f"Oldest should be 35, got {ages[-1]}"

def test_sort_descending():
    """Test that sorting with --reverse flag works in descending order."""
    stdout, stderr, returncode = run_processor(['/app/sample_data.csv', '--sort', 'age', '--reverse'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    rows = parse_csv_output(stdout)
    
    ages = [int(row['age']) for row in rows]
    assert ages == sorted(ages, reverse=True), f"Ages not sorted descending: {ages}"
    assert ages[0] == 35, f"First should be 35, got {ages[0]}"
    assert ages[-1] == 25, f"Last should be 25, got {ages[-1]}"

def test_json_output_format():
    """Test that --json flag produces valid JSON output."""
    stdout, stderr, returncode = run_processor(['/app/sample_data.csv', '--json'])
    
    assert returncode == 0, f"Processor failed: {stderr}"
    data = json.loads(stdout)
    
    assert isinstance(data, list), "JSON output should be a list"
    assert len(data) == 7, f"Expected 7 records, got {len(data)}"
    assert 'name' in data[0], "JSON records should have 'name' field"
    assert 'salary' in data[0], "JSON records should have 'salary' field"
