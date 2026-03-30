import sys
import os
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, '/app')

from fixture_manager import DatabaseFixture, FileFixture, CacheFixture


def test_database_fixture_basic_setup_teardown():
    """Test that DatabaseFixture properly sets up and tears down."""
    db = DatabaseFixture()
    
    connection = db.setup()
    assert connection is not None
    assert db.db_path is not None
    assert os.path.exists(db.db_path)
    
    db.teardown()
    assert db.connection is None
    # Temp directory should be cleaned up
    if db.temp_dir:
        assert not os.path.exists(db.temp_dir)


def test_database_fixture_external_path_no_cleanup():
    """Test that DatabaseFixture doesn't delete externally provided paths."""
    # Create external temp directory
    external_dir = tempfile.mkdtemp()
    external_db = os.path.join(external_dir, 'external.db')
    
    try:
        db = DatabaseFixture(db_path=external_db)
        db.setup()
        
        assert os.path.exists(external_db)
        
        db.teardown()
        
        # External directory should still exist
        assert os.path.exists(external_dir), "DatabaseFixture should not delete externally provided paths"
    finally:
        # Clean up external directory
        if os.path.exists(external_dir):
            shutil.rmtree(external_dir)


def test_database_fixture_prevents_double_setup():
    """Test that DatabaseFixture tracks setup state."""
    db = DatabaseFixture()
    
    first_connection = db.setup()
    first_path = db.db_path
    
    # Second setup should not create new resources
    second_connection = db.setup()
    
    assert db._setup_called
    assert first_path == db.db_path
    
    db.teardown()


def test_file_fixture_basic_operations():
    """Test that FileFixture creates and cleans up files."""
    content = "test content"
    file_fix = FileFixture(content=content, filename="test.txt")
    
    file_path = file_fix.setup()
    assert os.path.exists(file_path)
    assert file_fix.read() == content
    
    file_fix.teardown()
    assert not os.path.exists(file_path)


def test_file_fixture_idempotent_teardown():
    """Test that FileFixture teardown can be called multiple times safely."""
    file_fix = FileFixture(content="test")
    
    file_path = file_fix.setup()
    assert os.path.exists(file_path)
    
    # First teardown
    file_fix.teardown()
    assert file_fix.file_path is None
    
    # Second teardown should not crash
    file_fix.teardown()
    assert file_fix.file_path is None


def test_file_fixture_read_after_teardown():
    """Test that FileFixture read returns None after teardown."""
    file_fix = FileFixture(content="test")
    file_fix.setup()
    
    assert file_fix.read() == "test"
    
    file_fix.teardown()
    result = file_fix.read()
    
    assert result is None, "Read after teardown should return None"


def test_cache_fixture_singleton_pattern():
    """Test that CacheFixture implements singleton pattern."""
    # Reset singleton for test isolation
    CacheFixture._instance = None
    CacheFixture._initialized = False
    
    cache1 = CacheFixture()
    cache2 = CacheFixture()
    
    assert cache1 is cache2, "CacheFixture should be a singleton"


def test_cache_fixture_session_scope():
    """Test that CacheFixture maintains data across instances."""
    # Reset singleton
    CacheFixture._instance = None
    CacheFixture._initialized = False
    
    cache1 = CacheFixture()
    cache1.setup()
    cache1.set('key1', 'value1')
    
    cache2 = CacheFixture()
    assert cache2.get('key1') == 'value1', "Cache should persist across instances"
    
    cache1.teardown()


def test_cache_fixture_reset_after_teardown():
    """Test that CacheFixture properly resets after teardown."""
    # Reset singleton
    CacheFixture._instance = None
    CacheFixture._initialized = False
    
    cache1 = CacheFixture()
    cache1.setup()
    cache1.set('key1', 'value1')
    
    cache1.teardown()
    
    # After teardown, cache should be empty
    assert cache1.get('key1') is None, "Cache should be cleared after teardown"
    
    # New instance after teardown should be fresh
    CacheFixture._instance = None
    CacheFixture._initialized = False
    cache2 = CacheFixture()
    cache2.setup()
    
    assert cache2.get('key1') is None, "New cache instance should be empty"


def test_database_fixture_teardown_state():
    """Test that DatabaseFixture properly tracks teardown state."""
    db = DatabaseFixture()
    db.setup()
    
    assert db._setup_called
    assert not db._teardown_called
    
    db.teardown()
    
    assert db._teardown_called
