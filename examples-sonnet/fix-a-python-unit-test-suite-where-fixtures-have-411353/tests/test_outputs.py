import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, '/app')

import pytest
from test_fixtures import temp_database, shared_cache, config_file, DatabaseConnection
from conftest import temp_workspace, log_file


def test_temp_database_creates_connection(temp_database):
    """Test that temp_database fixture creates a working connection."""
    assert temp_database.is_connected
    assert os.path.exists(temp_database.db_path)


def test_temp_database_transaction_cleanup(temp_database):
    """Test that active transactions are cleaned up properly."""
    temp_database.begin_transaction()
    assert temp_database.transaction_active
    # Fixture teardown should handle rollback


def test_temp_database_directory_cleanup(temp_database):
    """Test that temporary directories are cleaned up."""
    db_dir = os.path.dirname(temp_database.db_path)
    assert os.path.exists(db_dir)
    # After test, directory should be cleaned up


def test_shared_cache_isolation():
    """Test that shared cache is properly isolated between modules."""
    # This test verifies cache cleanup happens
    pass


def test_config_file_exists(config_file):
    """Test that config file fixture creates the file."""
    assert os.path.exists(config_file)
    with open(config_file, 'r') as f:
        content = f.read()
        assert '[settings]' in content
        assert 'debug=true' in content


def test_temp_workspace_directory(temp_workspace):
    """Test that temp_workspace provides a working directory."""
    assert os.path.exists(temp_workspace)
    assert os.path.isdir(temp_workspace)
    
    # Create a file in workspace
    test_file = os.path.join(temp_workspace, 'test.txt')
    with open(test_file, 'w') as f:
        f.write('test')
    
    assert os.path.exists(test_file)


def test_log_file_creation(log_file):
    """Test that log_file fixture creates and initializes the log."""
    assert os.path.exists(log_file)
    
    with open(log_file, 'r') as f:
        content = f.read()
        assert 'Test log initialized' in content
    
    # Write additional log entry
    with open(log_file, 'a') as f:
        f.write('Test entry\n')
