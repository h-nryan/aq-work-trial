#!/usr/bin/env python3
import pytest
import tempfile
import os
import shutil
from pathlib import Path


class DatabaseConnection:
    """Simulates a database connection for testing."""
    
    def __init__(self, db_path):
        self.db_path = db_path
        self.is_connected = False
        self.transaction_active = False
    
    def connect(self):
        """Establish database connection."""
        if not os.path.exists(self.db_path):
            Path(self.db_path).touch()
        self.is_connected = True
        return self
    
    def disconnect(self):
        """Close database connection."""
        self.is_connected = False
        self.transaction_active = False
    
    def begin_transaction(self):
        """Start a database transaction."""
        if not self.is_connected:
            raise RuntimeError("Not connected to database")
        self.transaction_active = True
    
    def commit(self):
        """Commit the current transaction."""
        if not self.transaction_active:
            raise RuntimeError("No active transaction")
        self.transaction_active = False
    
    def rollback(self):
        """Rollback the current transaction."""
        if not self.transaction_active:
            raise RuntimeError("No active transaction")
        self.transaction_active = False


@pytest.fixture(scope="function")
def temp_database():
    """Fixture that provides a temporary database connection."""
    # BUG 1: Missing temp directory creation - db_path will be invalid
    db_path = os.path.join("/tmp", "test.db")
    
    db = DatabaseConnection(db_path)
    db.connect()
    
    yield db
    
    # BUG 2: Disconnects before rolling back transaction (wrong order)
    db.disconnect()
    if db.transaction_active:
        db.rollback()


@pytest.fixture(scope="module")
def shared_cache():
    """Module-scoped fixture for shared cache."""
    cache = {"data": []}
    yield cache
    cache.clear()


@pytest.fixture(scope="session")
def config_file():
    """Session-scoped fixture for configuration file."""
    temp_dir = tempfile.mkdtemp()
    config_path = os.path.join(temp_dir, "config.ini")
    
    # BUG 3: Wrong delimiter - uses colon instead of equals
    with open(config_path, 'w') as f:
        f.write("[settings]\n")
        f.write("debug:true\n")
    
    yield config_path
    
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
