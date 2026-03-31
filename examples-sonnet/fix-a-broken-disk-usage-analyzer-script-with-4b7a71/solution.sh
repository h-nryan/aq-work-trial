#!/bin/bash

# Solution: restore the working versions of all source files
cat > disk_usage.py << 'SOLUTION_EOF'
#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path


def get_file_size(path):
    """Get the size of a file, handling symlinks correctly."""
    try:
        # BUG 1: Using os.path.getsize() which follows symlinks
        # Should use os.lstat() to get the link size itself
        return os.path.getsize(path)
    except (OSError, PermissionError):
        return 0


def calculate_directory_size(path, follow_symlinks=False):
    """Calculate total size of directory and its contents."""
    total_size = 0
    
    try:
        # BUG 2: Not checking if path is a symlink before recursing
        # This can cause infinite loops with circular symlinks
        if os.path.isdir(path):
            # Get directory entry size
            total_size += get_file_size(path)
            
            # Recurse into subdirectories
            for entry in os.listdir(path):
                entry_path = os.path.join(path, entry)
                total_size += calculate_directory_size(entry_path, follow_symlinks)
        else:
            total_size = get_file_size(path)
    except (PermissionError, OSError):
        pass
    
    return total_size


def traverse_directory(root_path, max_depth=None, current_depth=0):
    """Traverse directory tree and collect size information."""
    results = []
    
    try:
        # Add current path
        size = calculate_directory_size(root_path)
        results.append({
            'path': root_path,
            'size': size,
            'depth': current_depth
        })
        
        # BUG 3: Wrong depth comparison - uses > instead of >=
        # This allows one extra level of recursion
        if os.path.isdir(root_path) and (max_depth is None or current_depth > max_depth):
            for entry in os.listdir(root_path):
                entry_path = os.path.join(root_path, entry)
                child_results = traverse_directory(entry_path, max_depth, current_depth + 1)
                results.extend(child_results)
    except (PermissionError, OSError):
        pass
    
    return results


def format_size(size_bytes):
    """Format size in human-readable format."""
    # BUG 4: Using integer division which loses precision
    # Should use float division for accurate formatting
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes = size_bytes // 1024
    return f"{size_bytes:.2f} PB"


def main():
    if len(sys.argv) < 2:
        print("Usage: disk_usage.py <directory> [--json] [--max-depth N]")
        sys.exit(1)
    
    directory = sys.argv[1]
    output_json = '--json' in sys.argv
    max_depth = None
    
    # Parse max-depth argument
    if '--max-depth' in sys.argv:
        idx = sys.argv.index('--max-depth')
        if idx + 1 < len(sys.argv):
            try:
                max_depth = int(sys.argv[idx + 1])
            except ValueError:
                print("Error: max-depth must be an integer")
                sys.exit(1)
    
    if not os.path.exists(directory):
        print(f"Error: Directory '{directory}' does not exist")
        sys.exit(1)
    
    results = traverse_directory(directory, max_depth)
    
    if output_json:
        print(json.dumps(results, indent=2))
    else:
        # Sort by size descending
        for item in sorted(results, key=lambda x: x['size'], reverse=True):
            print(f"{format_size(item['size']):>12} {item['path']}")


if __name__ == '__main__':
    main()

SOLUTION_EOF

cat > requirements.txt << 'SOLUTION_EOF'
# No runtime dependencies required
# The disk_usage.py script uses only Python standard library modules
# Test dependencies are handled by run-tests.sh using uv with pinned versions:
# - pytest==8.4.1

SOLUTION_EOF

cat > solution.sh << 'SOLUTION_EOF'
#!/bin/bash
set -euo pipefail

# Fix all bugs in disk_usage.py
cat > /app/disk_usage.py << 'EOF'
#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path


def get_file_size(path):
    """Get the size of a file, handling symlinks correctly."""
    try:
        # FIX BUG 1: Use os.lstat() to not follow symlinks
        stat_info = os.lstat(path)
        return stat_info.st_size
    except (OSError, PermissionError):
        return 0


def calculate_directory_size(path, follow_symlinks=False):
    """Calculate total size of directory and its contents."""
    total_size = 0
    
    try:
        # FIX BUG 2: Check for symlinks to avoid infinite loops
        if os.path.islink(path) and not follow_symlinks:
            return get_file_size(path)
        
        if os.path.isdir(path):
            # Get directory entry size
            total_size += get_file_size(path)
            
            # Recurse into subdirectories
            for entry in os.listdir(path):
                entry_path = os.path.join(path, entry)
                total_size += calculate_directory_size(entry_path, follow_symlinks)
        else:
            total_size = get_file_size(path)
    except (PermissionError, OSError):
        pass
    
    return total_size


def traverse_directory(root_path, max_depth=None, current_depth=0):
    """Traverse directory tree and collect size information."""
    results = []
    
    try:
        # Add current path
        size = calculate_directory_size(root_path)
        results.append({
            'path': root_path,
            'size': size,
            'depth': current_depth
        })
        
        # FIX BUG 3: Use >= for correct depth limiting
        if os.path.isdir(root_path) and not os.path.islink(root_path):
            if max_depth is None or current_depth < max_depth:
                for entry in os.listdir(root_path):
                    entry_path = os.path.join(root_path, entry)
                    child_results = traverse_directory(entry_path, max_depth, current_depth + 1)
                    results.extend(child_results)
    except (PermissionError, OSError):
        pass
    
    return results


def format_size(size_bytes):
    """Format size in human-readable format."""
    # FIX BUG 4: Use float division for accurate formatting
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size = size / 1024.0
    return f"{size:.2f} PB"


def main():
    if len(sys.argv) < 2:
        print("Usage: disk_usage.py <directory> [--json] [--max-depth N]")
        sys.exit(1)
    
    directory = sys.argv[1]
    output_json = '--json' in sys.argv
    max_depth = None
    
    # Parse max-depth argument
    if '--max-depth' in sys.argv:
        idx = sys.argv.index('--max-depth')
        if idx + 1 < len(sys.argv):
            try:
                max_depth = int(sys.argv[idx + 1])
            except ValueError:
                print("Error: max-depth must be an integer")
                sys.exit(1)
    
    if not os.path.exists(directory):
        print(f"Error: Directory '{directory}' does not exist")
        sys.exit(1)
    
    results = traverse_directory(directory, max_depth)
    
    if output_json:
        print(json.dumps(results, indent=2))
    else:
        # Sort by size descending
        for item in sorted(results, key=lambda x: x['size'], reverse=True):
            print(f"{format_size(item['size']):>12} {item['path']}")


if __name__ == '__main__':
    main()
EOF

chmod +x /app/disk_usage.py

SOLUTION_EOF
