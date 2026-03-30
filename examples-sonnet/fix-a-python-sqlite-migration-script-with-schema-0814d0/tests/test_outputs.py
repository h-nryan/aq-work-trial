import subprocess
import sqlite3
import os
import tempfile
from pathlib import Path

def run_migration(db_path):
    """Run the migration script on a database."""
    result = subprocess.run(
        ['python3', '/app/migrate_db.py', db_path],
        capture_output=True,
        text=True,
        timeout=10
    )
    return result.stdout, result.stderr, result.returncode

def get_schema(db_path):
    """Get the schema information for the users table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("PRAGMA table_info(users)")
    columns = {row[1]: {'type': row[2], 'notnull': row[3], 'dflt_value': row[4]} for row in cursor.fetchall()}
    conn.close()
    return columns

def get_version(db_path):
    """Get current schema version."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        version = row[0] if row else 0
    except sqlite3.OperationalError:
        version = 0
    conn.close()
    return version

def test_migration_creates_users_table():
    """Test that migration creates the users table with initial columns."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        stdout, stderr, returncode = run_migration(db_path)
        assert returncode == 0, f"Migration failed: {stderr}"
        
        schema = get_schema(db_path)
        assert 'id' in schema, "users table should have id column"
        assert 'username' in schema, "users table should have username column"
        assert 'email' in schema, "users table should have email column"
        assert 'created_at' in schema, "users table should have created_at column"
    finally:
        os.unlink(db_path)

def test_migration_adds_age_column_with_correct_type():
    """Test that age column is added with INTEGER type, not TEXT."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        stdout, stderr, returncode = run_migration(db_path)
        assert returncode == 0, f"Migration failed: {stderr}"
        
        schema = get_schema(db_path)
        assert 'age' in schema, "users table should have age column"
        assert schema['age']['type'] == 'INTEGER', f"age column should be INTEGER, not {schema['age']['type']}"
    finally:
        os.unlink(db_path)

def test_migration_reaches_version_3():
    """Test that all migrations are applied and version reaches 3."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        stdout, stderr, returncode = run_migration(db_path)
        assert returncode == 0, f"Migration failed: {stderr}"
        
        version = get_version(db_path)
        assert version == 3, f"Expected version 3, got {version}"
        
        # Check that all migrations were mentioned in output
        assert 'version 1' in stdout.lower(), "Should apply migration to version 1"
        assert 'version 2' in stdout.lower(), "Should apply migration to version 2"
        assert 'version 3' in stdout.lower(), "Should apply migration to version 3"
    finally:
        os.unlink(db_path)

def test_all_columns_present_with_correct_types():
    """Test that final schema has all expected columns with correct types."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        stdout, stderr, returncode = run_migration(db_path)
        assert returncode == 0, f"Migration failed: {stderr}"
        
        schema = get_schema(db_path)
        
        # Check all columns exist
        expected_columns = ['id', 'username', 'email', 'created_at', 'age', 'status']
        for col in expected_columns:
            assert col in schema, f"Missing column: {col}"
        
        # Check specific types
        assert schema['age']['type'] == 'INTEGER', "age should be INTEGER"
        assert schema['status']['type'] == 'TEXT', "status should be TEXT"
    finally:
        os.unlink(db_path)

def test_schema_version_table_exists():
    """Test that schema_version table is created and tracks versions."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    try:
        stdout, stderr, returncode = run_migration(db_path)
        assert returncode == 0, f"Migration failed: {stderr}"
        
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        result = cursor.fetchone()
        conn.close()
        
        assert result is not None, "schema_version table should exist"
    finally:
        os.unlink(db_path)
