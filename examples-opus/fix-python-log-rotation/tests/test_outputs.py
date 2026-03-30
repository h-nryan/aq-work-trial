import os
import json
import gzip
import subprocess
import tempfile
from pathlib import Path


def create_large_log(path, size_mb):
    """Create a log file of specified size in MB"""
    with open(path, 'w') as f:
        # Write ~1MB of data per iteration
        line = "2024-01-15 10:23:45 INFO " + "x" * 1000 + "\n"
        lines_per_mb = 1024  # ~1KB per line
        for _ in range(int(size_mb * lines_per_mb)):
            f.write(line)


def test_size_check_bug():
    """Test that the size check bug is fixed (KB vs bytes comparison)"""
    # Create test environment
    test_dir = Path("/tmp/test_rotation")
    test_dir.mkdir(exist_ok=True)
    
    log_file = test_dir / "test.log"
    config_file = test_dir / "config.json"
    
    # Create a 500KB file (should not trigger rotation with 1MB limit)
    create_large_log(log_file, 0.5)
    
    config = {
        "logs": {
            "test": {
                "path": str(log_file),
                "max_size": 1048576,  # 1MB in bytes
                "compress": False,
                "keep": 3
            }
        }
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f)
    
    # Run the fixed rotator
    result = subprocess.run(
        ["python3", "/app/log_rotator.py", str(config_file)],
        capture_output=True,
        text=True
    )
    
    # Should not rotate a 500KB file when limit is 1MB
    assert "skipped" in result.stdout, "Small file should not be rotated"
    assert log_file.exists(), "Original log file should still exist"


def test_compression_bug():
    """Test that compression works correctly (text vs binary mode bug)"""
    test_dir = Path("/tmp/test_compression")
    test_dir.mkdir(exist_ok=True)
    
    log_file = test_dir / "compress.log"
    config_file = test_dir / "config.json"
    
    # Create a 2MB file to trigger rotation
    create_large_log(log_file, 2)
    
    config = {
        "logs": {
            "compress_test": {
                "path": str(log_file),
                "max_size": 1048576,  # 1MB
                "compress": True,
                "keep": 3
            }
        }
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f)
    
    # Run rotator
    result = subprocess.run(
        ["python3", "/app/log_rotator.py", str(config_file)],
        capture_output=True,
        text=True
    )
    
    # Find the compressed file
    compressed_files = list(test_dir.glob("*.gz"))
    assert len(compressed_files) > 0, "Compressed file should be created"
    
    # Verify compression worked correctly
    compressed_file = compressed_files[0]
    try:
        with gzip.open(compressed_file, 'rt') as f:
            content = f.read()
            assert len(content) > 0, "Compressed file should contain data"
    except Exception as e:
        assert False, f"Failed to read compressed file: {e}"


def test_rotated_file_path_bug():
    """Test that rotated files are created in the correct directory"""
    test_dir = Path("/tmp/test_paths")
    test_dir.mkdir(exist_ok=True)
    log_dir = test_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / "app.log"
    config_file = test_dir / "config.json"
    
    create_large_log(log_file, 2)
    
    config = {
        "logs": {
            "path_test": {
                "path": str(log_file),
                "max_size": 1048576,
                "compress": False,
                "keep": 3
            }
        }
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f)
    
    # Run rotator
    subprocess.run(
        ["python3", "/app/log_rotator.py", str(config_file)],
        capture_output=True,
        text=True
    )
    
    # Check that rotated file is in the same directory as original
    rotated_files = [f for f in log_dir.iterdir() if f.name.startswith("app.log.") and not f.name.endswith(".gz")]
    assert len(rotated_files) > 0, "Rotated file should be in the logs directory"


def test_cleanup_compressed_files_bug():
    """Test that cleanup correctly handles compressed files"""
    test_dir = Path("/tmp/test_cleanup")
    test_dir.mkdir(exist_ok=True)
    
    log_file = test_dir / "cleanup.log"
    config_file = test_dir / "config.json"
    
    config = {
        "logs": {
            "cleanup_test": {
                "path": str(log_file),
                "max_size": 100,  # Very small to force multiple rotations
                "compress": True,
                "keep": 2
            }
        }
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f)
    
    # Create and rotate multiple times
    for i in range(5):
        with open(log_file, 'w') as f:
            f.write(f"Log entry {i}\n" * 20)
        
        subprocess.run(
            ["python3", "/app/log_rotator.py", str(config_file)],
            capture_output=True,
            text=True
        )
    
    # Count remaining files
    all_files = list(test_dir.glob("cleanup.log*"))
    compressed_files = list(test_dir.glob("*.gz"))
    
    # Should have: 1 current log + 2 kept rotated files (compressed)
    assert len(all_files) <= 3, f"Too many files kept: {len(all_files)}"
    assert len(compressed_files) <= 2, f"Too many compressed files: {len(compressed_files)}"


def test_uncompressed_file_removal_bug():
    """Test that uncompressed files are removed after compression"""
    test_dir = Path("/tmp/test_uncomp_removal")
    test_dir.mkdir(exist_ok=True)
    
    log_file = test_dir / "remove.log"
    config_file = test_dir / "config.json"
    
    create_large_log(log_file, 2)
    
    config = {
        "logs": {
            "remove_test": {
                "path": str(log_file),
                "max_size": 1048576,
                "compress": True,
                "keep": 3
            }
        }
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f)
    
    subprocess.run(
        ["python3", "/app/log_rotator.py", str(config_file)],
        capture_output=True,
        text=True
    )
    
    # Check that no uncompressed rotated files remain
    files = list(test_dir.iterdir())
    for f in files:
        if f.name.startswith("remove.log.") and not f.name.endswith(".gz"):
            assert False, f"Uncompressed rotated file still exists: {f.name}"


def test_sorting_by_time_bug():
    """Test that old files are cleaned up by modification time, not alphabetically"""
    test_dir = Path("/tmp/test_sorting")
    test_dir.mkdir(exist_ok=True)
    
    log_file = test_dir / "sort.log"
    config_file = test_dir / "config.json"
    
    # Create some old rotated files with different timestamps
    import time
    old_files = [
        test_dir / "sort.log.20240101_120000",
        test_dir / "sort.log.20240102_120000",
        test_dir / "sort.log.20240103_120000",
        test_dir / "sort.log.20240110_120000",  # Alphabetically later but should be kept
    ]
    
    for i, f in enumerate(old_files):
        f.write_text(f"Old log {i}")
        # Set modification time
        os.utime(f, (time.time() - (len(old_files) - i) * 86400, time.time() - (len(old_files) - i) * 86400))
    
    config = {
        "logs": {
            "sort_test": {
                "path": str(log_file),
                "max_size": 1,  # Force rotation
                "compress": False,
                "keep": 2
            }
        }
    }
    
    with open(config_file, 'w') as f:
        json.dump(config, f)
    
    # Create current log and rotate
    log_file.write_text("Current log")
    subprocess.run(
        ["python3", "/app/log_rotator.py", str(config_file)],
        capture_output=True,
        text=True
    )
    
    # The newest files should be kept
    remaining_files = [f for f in test_dir.glob("sort.log.*") if not f.name.endswith(".gz")]
    remaining_names = [f.name for f in remaining_files]
    
    # Should keep the most recent files by modification time
    assert "sort.log.20240110_120000" in remaining_names or len(remaining_files) <= 2, \
        "Cleanup should preserve newest files by modification time"


def test_multiple_logs_rotation():
    """Test that multiple logs can be rotated in one run"""
    test_dir = Path("/tmp/test_multiple")
    test_dir.mkdir(exist_ok=True)
    
    logs = {
        "app": test_dir / "app.log",
        "access": test_dir / "access.log",
        "error": test_dir / "error.log"
    }
    
    config_file = test_dir / "config.json"
    
    config = {"logs": {}}
    
    for name, path in logs.items():
        create_large_log(path, 2)
        config["logs"][name] = {
            "path": str(path),
            "max_size": 1048576,
            "compress": True,
            "keep": 3
        }
    
    with open(config_file, 'w') as f:
        json.dump(config, f)
    
    result = subprocess.run(
        ["python3", "/app/log_rotator.py", str(config_file)],
        capture_output=True,
        text=True
    )
    
    # All logs should be rotated
    for name in logs:
        assert f"{name}: rotated" in result.stdout, f"Log {name} should be rotated"
    
    # Check compressed files exist
    compressed_files = list(test_dir.glob("*.gz"))
    assert len(compressed_files) == 3, "All rotated logs should be compressed"
