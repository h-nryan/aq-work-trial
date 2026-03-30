#!/bin/bash
set -euo pipefail

# Fix all bugs in the migration script
cat > /app/migrate_db.py << 'EOF'
#!/usr/bin/env python3
import sqlite3
import sys
import os
from pathlib import Path

CURRENT_VERSION = 3

def get_db_version(conn):
    """Get current schema version from database."""
    try:
        cursor = conn.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0

def set_db_version(conn, version):
    """Set schema version in database."""
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'))", (version,))
    conn.commit()

def migrate_v0_to_v1(conn):
    """Initial schema: create users table."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()

def migrate_v1_to_v2(conn):
    """Add age column to users table."""
    conn.execute("ALTER TABLE users ADD COLUMN age INTEGER")
    conn.commit()

def migrate_v2_to_v3(conn):
    """Add status column with default value."""
    conn.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")
    conn.commit()

def apply_migrations(db_path):
    """Apply all pending migrations."""
    conn = sqlite3.connect(db_path)
    current_version = get_db_version(conn)
    
    migrations = [
        (1, migrate_v0_to_v1),
        (2, migrate_v1_to_v2),
        (3, migrate_v2_to_v3)
    ]
    
    for version, migrate_func in migrations:
        if current_version < version:
            print(f"Applying migration to version {version}...")
            migrate_func(conn)
            set_db_version(conn, version)
            print(f"Migration to version {version} complete")
    
    conn.close()
    print(f"Database is at version {CURRENT_VERSION}")

def verify_schema(db_path):
    """Verify database schema is correct."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("PRAGMA table_info(users)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    conn.close()
    return columns

def main():
    if len(sys.argv) != 2:
        print("Usage: migrate_db.py <database_path>")
        sys.exit(1)
    
    db_path = sys.argv[1]
    apply_migrations(db_path)
    
    columns = verify_schema(db_path)
    print(f"\nCurrent schema: {columns}")

if __name__ == "__main__":
    main()
EOF

chmod +x /app/migrate_db.py
