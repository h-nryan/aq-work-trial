#!/bin/bash
set -euo pipefail

# Fix all bugs in the test fixture files
cat > /app/test_fixtures.py << 'EOF'
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
    # FIX BUG 1: Create temp directory properly
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    
    db = DatabaseConnection(db_path)
    db.connect()
    
    yield db
    
    # FIX BUG 2: Rollback transaction BEFORE disconnect
    if db.transaction_active:
        db.rollback()
    db.disconnect()
    
    # Clean up temp directory
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)


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
    
    # FIX BUG 3: Use equals sign instead of colon
    with open(config_path, 'w') as f:
        f.write("[settings]\n")
        f.write("debug=true\n")
    
    yield config_path
    
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
EOF

cat > /app/conftest.py << 'EOF'
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
    
    # FIX BUG 4: Yield BEFORE cleanup
    yield log_path
    
    # Cleanup happens after yield
    if os.path.exists(log_path):
        os.remove(log_path)
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
EOF
