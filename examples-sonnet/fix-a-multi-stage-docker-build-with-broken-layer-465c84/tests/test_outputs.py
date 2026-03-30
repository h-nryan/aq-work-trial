import json
import subprocess
import os
from pathlib import Path


def read_file(path):
    """Read file contents."""
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def read_json(path):
    """Read and parse JSON from file."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def run_parser(logfile, *args):
    """Run the log parser with given arguments."""
    cmd = ['python3', '/app/log_parser.py', logfile] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def test_basic_parsing():
    """Test that all log lines are parsed and output correctly."""
    output = read_file('/tmp/output_all.txt')
    lines = [line for line in output.strip().split('\n') if line]
    
    assert len(lines) == 10, f"Expected 10 log lines, got {len(lines)}"
    assert '[INFO]' in output, "Should contain INFO logs"
    assert '[ERROR]' in output, "Should contain ERROR logs"
    assert '[WARNING]' in output, "Should contain WARNING logs"
    assert '[DEBUG]' in output, "Should contain DEBUG logs"


def test_level_filtering():
    """Test that --level flag filters logs correctly."""
    output = read_file('/tmp/output_errors.txt')
    lines = [line for line in output.strip().split('\n') if line]
    
    assert len(lines) == 2, f"Expected 2 ERROR lines, got {len(lines)}"
    assert all('[ERROR]' in line for line in lines), "All lines should be ERROR level"
    assert 'Database connection failed' in output, "Should contain specific error message"
    assert 'Retry attempt 1 failed' in output, "Should contain retry error message"


def test_time_range_filtering():
    """Test that --start and --end flags filter by time range."""
    output = read_file('/tmp/output_timerange.txt')
    lines = [line for line in output.strip().split('\n') if line]
    
    # Time range: 2024-01-15 10:32:00 to 10:34:00
    # Should include: 10:32:00, 10:32:30, 10:33:00, 10:33:30, 10:34:00
    assert len(lines) == 5, f"Expected 5 lines in time range, got {len(lines)}"
    
    # Check that times are within range
    for line in lines:
        assert '10:32:' in line or '10:33:' in line or '10:34:00' in line, \
            f"Line outside time range: {line}"
    
    # Should NOT include 10:31 or 10:35
    assert '10:31:' not in output, "Should not include times before start"
    assert '10:35:' not in output, "Should not include times after end"


def test_statistics_generation():
    """Test that --stats flag generates correct statistics."""
    stats = read_json('/tmp/output_stats.json')
    
    assert isinstance(stats, dict), "Stats should be a dictionary"
    assert 'INFO' in stats, "Stats should include INFO count"
    assert 'ERROR' in stats, "Stats should include ERROR count"
    assert 'WARNING' in stats, "Stats should include WARNING count"
    assert 'DEBUG' in stats, "Stats should include DEBUG count"
    
    assert stats['INFO'] == 4, f"Expected 4 INFO logs, got {stats['INFO']}"
    assert stats['ERROR'] == 2, f"Expected 2 ERROR logs, got {stats['ERROR']}"
    assert stats['WARNING'] == 2, f"Expected 2 WARNING logs, got {stats['WARNING']}"
    assert stats['DEBUG'] == 2, f"Expected 2 DEBUG logs, got {stats['DEBUG']}"


def test_json_output_format():
    """Test that --json flag produces valid JSON output."""
    data = read_json('/tmp/output_json.json')
    
    assert isinstance(data, list), "JSON output should be a list"
    assert len(data) == 10, f"Expected 10 entries, got {len(data)}"
    
    for entry in data:
        assert 'timestamp' in entry, "Each entry should have timestamp"
        assert 'level' in entry, "Each entry should have level"
        assert 'message' in entry, "Each entry should have message"
        
        # Verify timestamp format
        assert len(entry['timestamp']) == 19, "Timestamp should be YYYY-MM-DD HH:MM:SS format"
        assert entry['level'] in ['INFO', 'DEBUG', 'WARNING', 'ERROR'], \
            f"Invalid level: {entry['level']}"


def test_combined_filters():
    """Test that multiple filters can be combined."""
    data = read_json('/tmp/output_warnings.json')
    
    assert isinstance(data, list), "Should be JSON list"
    assert len(data) == 2, f"Expected 2 WARNING entries, got {len(data)}"
    
    for entry in data:
        assert entry['level'] == 'WARNING', "All entries should be WARNING level"


def test_timestamp_preservation():
    """Test that timestamps are preserved correctly in output."""
    output = read_file('/tmp/output_all.txt')
    
    # Check that original timestamps are preserved
    assert '2024-01-15 10:30:45' in output, "Should preserve exact timestamp"
    assert '2024-01-15 10:32:30' in output, "Should preserve exact timestamp"
    assert '2024-01-15 10:36:00' in output, "Should preserve exact timestamp"


def test_case_insensitive_level_filter():
    """Test that level filtering is case-insensitive."""
    stdout, stderr, returncode = run_parser('/tmp/test_logs/app.log', '--level', 'error')
    
    assert returncode == 0, "Parser should run successfully"
    lines = [line for line in stdout.strip().split('\n') if line]
    assert len(lines) == 2, "Should filter ERROR logs regardless of case"
    assert all('[ERROR]' in line for line in lines), "All lines should be ERROR level"
