import json
import os
import subprocess
from pathlib import Path


def run_analyzer(directory, *args):
    """Run the disk usage analyzer and return output."""
    cmd = ['python3', '/app/disk_usage.py', directory] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.stdout, result.stderr, result.returncode


def test_script_runs_without_crash():
    """Test that the analyzer runs without crashing."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk')
    assert returncode == 0, f"Script crashed: {stderr}"
    assert len(stdout) > 0, "No output produced"


def test_json_output_valid():
    """Test that JSON output is valid and well-formed."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk', '--json')
    assert returncode == 0, f"Script failed: {stderr}"
    
    data = json.loads(stdout)
    assert isinstance(data, list), "JSON output should be a list"
    assert len(data) > 0, "JSON output should not be empty"
    
    for item in data:
        assert 'path' in item, "Each item should have 'path' field"
        assert 'size' in item, "Each item should have 'size' field"
        assert 'depth' in item, "Each item should have 'depth' field"


def test_size_calculations():
    """Test that file sizes are calculated correctly."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk', '--json')
    data = json.loads(stdout)
    
    # Find medium.dat (5 KB = 5120 bytes)
    medium_file = [item for item in data if 'medium.dat' in item['path']]
    assert len(medium_file) > 0, "medium.dat not found"
    
    size = medium_file[0]['size']
    assert 5100 <= size <= 5200, f"medium.dat size {size} not close to 5120 bytes"


def test_max_depth_limiting():
    """Test that max-depth parameter limits traversal correctly."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk', '--json', '--max-depth', '1')
    assert returncode == 0, "Script should run successfully"
    
    data = json.loads(stdout)
    max_depth = max(item['depth'] for item in data)
    assert max_depth <= 1, f"With max-depth 1, found depth {max_depth}"
    
    # Should NOT find deep.txt (at depth 3)
    deep_files = [item for item in data if 'deep.txt' in item['path']]
    assert len(deep_files) == 0, "Should not traverse beyond depth 1"


def test_max_depth_zero():
    """Test that max-depth 0 only shows root directory."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk', '--json', '--max-depth', '0')
    assert returncode == 0, "Script should run successfully"
    
    data = json.loads(stdout)
    assert all(item['depth'] == 0 for item in data), "With max-depth 0, should only have root"
    assert len(data) == 1, "With max-depth 0, should only have one item"


def test_symlink_handling():
    """Test that symlinks don't cause infinite loops or double-counting."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk', '--json')
    assert returncode == 0, "Script should handle symlinks"
    
    data = json.loads(stdout)
    symlink_items = [item for item in data if 'symlink.txt' in item['path']]
    assert len(symlink_items) > 0, "Should find symlink.txt"
    
    # Symlink size should be small (size of link itself)
    symlink_size = symlink_items[0]['size']
    assert symlink_size < 100, f"Symlink size {symlink_size} too large (should be link size)"


def test_human_readable_format():
    """Test that human-readable output formats sizes correctly."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk')
    assert returncode == 0, "Script should run successfully"
    
    # Should contain size units
    assert any(unit in stdout for unit in ['B', 'KB', 'MB']), "Output should contain size units"
    assert '/tmp/test_disk' in stdout, "Output should contain paths"


def test_recursive_traversal():
    """Test that all files in the tree are found."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk', '--json')
    data = json.loads(stdout)
    
    paths = [item['path'] for item in data]
    
    # Should find files at various depths
    assert any('small.txt' in p for p in paths), "Should find small.txt"
    assert any('large.dat' in p for p in paths), "Should find large.dat"
    assert any('nested.txt' in p for p in paths), "Should find nested.txt"
    assert any('deep.txt' in p for p in paths), "Should find deep.txt at depth 3"



