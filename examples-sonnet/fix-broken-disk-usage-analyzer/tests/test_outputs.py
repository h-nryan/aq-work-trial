import json
import os
import subprocess
from pathlib import Path


def read_json(path):
    """Read and parse JSON from file path."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def run_analyzer(directory, *args):
    """Run the disk analyzer and return output."""
    cmd = ['python3', '/app/disk_analyzer.py', directory] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def test_basic_analysis_runs():
    """Test that the analyzer runs without crashing."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk')
    assert returncode == 0, f"Analyzer crashed: {stderr}"
    assert len(stdout) > 0, "No output produced"


def test_json_output_valid():
    """Test that JSON output is valid and contains required fields."""
    data = read_json('/tmp/output_json.json')
    
    assert isinstance(data, list), "JSON output should be a list"
    assert len(data) > 0, "JSON output should not be empty"
    
    for item in data:
        assert 'path' in item, "Each item should have 'path' field"
        assert 'size' in item, "Each item should have 'size' field"
        assert 'depth' in item, "Each item should have 'depth' field"
        assert isinstance(item['size'], (int, float)), "Size should be numeric"
        assert isinstance(item['depth'], int), "Depth should be integer"


def test_size_calculations_accurate():
    """Test that file sizes are calculated correctly."""
    data = read_json('/tmp/output_json.json')
    
    # Find the medium.dat file (10 KB = 10240 bytes)
    medium_file = [item for item in data if 'medium.dat' in item['path']]
    assert len(medium_file) > 0, "medium.dat not found in results"
    
    # Size should be approximately 10240 bytes (10 KB)
    size = medium_file[0]['size']
    assert 10200 <= size <= 10300, f"medium.dat size {size} not close to 10240 bytes"


def test_max_depth_respected():
    """Test that max-depth parameter limits traversal depth."""
    data = read_json('/tmp/output_depth2.json')
    
    # With max-depth 2, we should have:
    # depth 0: /tmp/test_disk
    # depth 1: /tmp/test_disk/subdir1, /tmp/test_disk/subdir4, etc.
    # depth 2: /tmp/test_disk/subdir1/subdir2, etc.
    # But NOT depth 3 or deeper
    
    max_depth_found = max(item['depth'] for item in data)
    assert max_depth_found <= 2, f"Found depth {max_depth_found}, but max-depth was 2"
    
    # Should have some depth 2 items
    depth_2_items = [item for item in data if item['depth'] == 2]
    assert len(depth_2_items) > 0, "Should have some depth 2 items"


def test_max_depth_one_limits_correctly():
    """Test that max-depth 1 only shows root and direct children."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk', '--json', '--max-depth', '1')
    assert returncode == 0, "Analyzer should run successfully"
    
    data = json.loads(stdout)
    max_depth_found = max(item['depth'] for item in data)
    assert max_depth_found <= 1, f"With max-depth 1, found depth {max_depth_found}"
    
    # Should NOT have nested.txt or deep.txt (they're at depth 2)
    nested_files = [item for item in data if 'nested.txt' in item['path'] or 'deep.txt' in item['path']]
    assert len(nested_files) == 0, "Should not traverse beyond depth 1"


def test_human_readable_format():
    """Test that human-readable output formats sizes correctly."""
    with open('/tmp/output_default.txt', 'r') as f:
        output = f.read()
    
    # Should contain size units
    assert any(unit in output for unit in ['B', 'KB', 'MB']), "Output should contain size units"
    
    # Should contain file paths
    assert '/tmp/test_disk' in output, "Output should contain analyzed directory"
    
    # Lines should be formatted with size and path
    lines = [line for line in output.strip().split('\n') if line]
    assert len(lines) > 0, "Should have output lines"


def test_recursive_traversal_complete():
    """Test that all files in the tree are found."""
    data = read_json('/tmp/output_json.json')
    
    # Should find all created files
    paths = [item['path'] for item in data]
    
    # Check for key files at different depths
    assert any('small.txt' in p for p in paths), "Should find small.txt"
    assert any('medium.dat' in p for p in paths), "Should find medium.dat"
    assert any('large.dat' in p for p in paths), "Should find large.dat"
    assert any('nested.txt' in p for p in paths), "Should find nested.txt at depth 2"
    assert any('deep.txt' in p for p in paths), "Should find deep.txt at depth 2"


def test_symlinks_handled_correctly():
    """Test that symlinks don't cause double-counting."""
    data = read_json('/tmp/output_json.json')
    
    # Find symlink and its target
    symlink_items = [item for item in data if 'symlink.txt' in item['path']]
    small_items = [item for item in data if item['path'].endswith('small.txt') and 'symlink' not in item['path']]
    
    assert len(symlink_items) > 0, "Should find symlink.txt"
    assert len(small_items) > 0, "Should find small.txt"
    
    # Symlink size should be small (size of link itself, not target)
    symlink_size = symlink_items[0]['size']
    assert symlink_size < 100, f"Symlink size {symlink_size} seems too large (should be link size, not target)"


def test_directory_sizes_include_contents():
    """Test that directory sizes include all contents recursively."""
    data = read_json('/tmp/output_json.json')
    
    # Find the root directory
    root_item = [item for item in data if item['path'] == '/tmp/test_disk'][0]
    
    # Root size should be sum of all file sizes (approximately)
    # Should be at least 100KB (large.dat) + 10KB (medium.dat)
    assert root_item['size'] > 110000, f"Root directory size {root_item['size']} seems too small"


def test_depth_zero_means_root_only():
    """Test that max-depth 0 only shows the root directory."""
    stdout, stderr, returncode = run_analyzer('/tmp/test_disk', '--json', '--max-depth', '0')
    assert returncode == 0, "Analyzer should run successfully"
    
    data = json.loads(stdout)
    
    # Should only have depth 0 items
    assert all(item['depth'] == 0 for item in data), "With max-depth 0, should only have root"
    assert len(data) == 1, "With max-depth 0, should only have one item (root)"
