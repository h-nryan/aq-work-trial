import json
import subprocess
from pathlib import Path

def run_parser(input_file, output_file):
    """Run the date parser and return the result."""
    result = subprocess.run(
        ['python3', '/app/date_parser.py', input_file, output_file],
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr

def read_json_output(filepath):
    """Read and parse JSON output file."""
    with open(filepath, 'r') as f:
        return json.load(f)

def test_iso_format_parsing():
    """Test that ISO8601 format dates are parsed correctly."""
    returncode, stdout, stderr = run_parser(
        'sample_data/dates_iso.txt',
        '/tmp/output_iso.json'
    )
    
    assert returncode == 0, f"Parser failed: {stderr}"
    data = read_json_output('/tmp/output_iso.json')
    
    assert len(data) == 4, f"Expected 4 records, got {len(data)}"
    assert all('normalized' in record for record in data), "All records should have normalized field"

def test_us_format_parsing():
    """Test that US format (MM/DD/YYYY) dates are parsed correctly."""
    returncode, stdout, stderr = run_parser(
        'sample_data/dates_us.txt',
        '/tmp/output_us.json'
    )
    
    assert returncode == 0, f"Parser failed: {stderr}"
    data = read_json_output('/tmp/output_us.json')
    
    assert len(data) == 4, f"Expected 4 records, got {len(data)}"
    # Check that US format was parsed
    assert any('01/15/2024' in record['original'] for record in data), "Should parse US format dates"

def test_eu_format_parsing():
    """Test that EU format (DD/MM/YYYY) dates are parsed correctly."""
    returncode, stdout, stderr = run_parser(
        'sample_data/dates_eu.txt',
        '/tmp/output_eu.json'
    )
    
    assert returncode == 0, f"Parser failed: {stderr}"
    data = read_json_output('/tmp/output_eu.json')
    
    assert len(data) == 4, f"Expected 4 records, got {len(data)}"
    # Check that EU format was parsed
    assert any('15/01/2024' in record['original'] for record in data), "Should parse EU format dates"

def test_mixed_format_parsing():
    """Test that mixed date formats are handled correctly."""
    returncode, stdout, stderr = run_parser(
        'sample_data/dates_mixed.txt',
        '/tmp/output_mixed.json'
    )
    
    assert returncode == 0, f"Parser failed: {stderr}"
    data = read_json_output('/tmp/output_mixed.json')
    
    assert len(data) == 4, f"Expected 4 records, got {len(data)}"
    # Should handle both ISO and US formats
    originals = [record['original'] for record in data]
    assert '2024-01-15' in originals, "Should parse ISO format"
    assert '01/20/2024' in originals, "Should parse US format"

def test_timezone_normalization():
    """Test that timezone offsets are applied correctly to normalize to UTC."""
    returncode, stdout, stderr = run_parser(
        'sample_data/dates_iso.txt',
        '/tmp/output_tz.json'
    )
    
    assert returncode == 0, f"Parser failed: {stderr}"
    data = read_json_output('/tmp/output_tz.json')
    
    # All normalized dates should be in UTC (+0000)
    for record in data:
        assert '+0000' in record['normalized'], f"Normalized date should have +0000 timezone: {record['normalized']}"

def test_output_format():
    """Test that output is in correct ISO8601 format with timezone."""
    returncode, stdout, stderr = run_parser(
        'sample_data/dates_iso.txt',
        '/tmp/output_format.json'
    )
    
    assert returncode == 0, f"Parser failed: {stderr}"
    data = read_json_output('/tmp/output_format.json')
    
    for record in data:
        normalized = record['normalized']
        # Should be in format: YYYY-MM-DDTHH:MM:SS+0000
        assert 'T' in normalized, f"Should have 'T' separator: {normalized}"
        assert normalized.endswith('+0000'), f"Should end with +0000: {normalized}"
        assert len(normalized) == 24, f"Should be 24 characters long: {normalized}"


