#!/usr/bin/env python3
import pytest
import tempfile
import os
import shutil


@pytest.fixture(scope="function")
def temp_workspace():
    """Provides a temporary workspace directory."""
    workspace = tempfile.mkdtemp()
    yield workspace
    if os.path.exists(workspace):
        shutil.rmtree(workspace)


@pytest.fixture(scope="function")
def log_file():
    """Provides a temporary log file."""
    temp_dir = tempfile.mkdtemp()
    log_path = os.path.join(temp_dir, "test.log")
    
    with open(log_path, 'w') as f:
        f.write("Test log initialized\n")
    
    # BUG 4: Cleanup happens before yield - file deleted before test runs
    if os.path.exists(log_path):
        os.remove(log_path)
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    
    yield log_path
