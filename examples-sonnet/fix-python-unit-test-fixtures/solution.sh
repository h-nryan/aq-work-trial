#!/bin/bash

# Solution: restore the working versions of all source files
cat > fixture_manager.py << 'SOLUTION_EOF'
#!/usr/bin/env python3
import os
import tempfile
import shutil
from pathlib import Path


class DatabaseFixture:
    """Manages database test fixtures with proper setup and teardown."""
    
    def __init__(self, db_path=None):
        self.db_path = db_path
        self.temp_dir = None
        self.connection = None
        self._setup_called = False
        self._teardown_called = False
    
    def setup(self):
        """Initialize database fixture."""
        if not self.db_path:
            self.temp_dir = tempfile.mkdtemp()
            self.db_path = os.path.join(self.temp_dir, 'test.db')
        
        # Create database file
        Path(self.db_path).touch()
        self.connection = f"connected_to_{self.db_path}"
        self._setup_called = True
        return self.connection
    
    def teardown(self):
        """Clean up database fixture."""
        self.connection = None
        
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            self.temp_dir = None
        
        self._teardown_called = True


class FileFixture:
    """Manages file test fixtures with proper scoping."""
    
    def __init__(self, content="", filename="test.txt"):
        self.content = content
        self.filename = filename
        self.file_path = None
        self.temp_dir = None
    
    def setup(self):
        """Create test file."""
        self.temp_dir = tempfile.mkdtemp()
        self.file_path = os.path.join(self.temp_dir, self.filename)
        
        with open(self.file_path, 'w') as f:
            f.write(self.content)
        
        return self.file_path
    
    def teardown(self):
        """Clean up test file."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            self.temp_dir = None
        self.file_path = None
    
    def read(self):
        """Read current file content."""
        if not self.file_path or not os.path.exists(self.file_path):
            return None
        
        with open(self.file_path, 'r') as f:
            return f.read()


class CacheFixture:
    """Manages cache test fixtures with session scope."""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not CacheFixture._initialized:
            self.cache = {}
            self.temp_dir = None
            CacheFixture._initialized = True
    
    def setup(self):
        """Initialize cache."""
        if not self.temp_dir:
            self.temp_dir = tempfile.mkdtemp()
        return self.cache
    
    def teardown(self):
        """Clean up cache."""
        self.cache.clear()
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            self.temp_dir = None
    
    def set(self, key, value):
        """Set cache value."""
        self.cache[key] = value
    
    def get(self, key):
        """Get cache value."""
        return self.cache.get(key)

SOLUTION_EOF

cat > requirements.txt << 'SOLUTION_EOF'
# No runtime dependencies required
# The fixture_manager.py uses only Python standard library modules
# Test dependencies are handled by run-tests.sh using uv with pinned versions:
# - pytest==8.4.1

SOLUTION_EOF
