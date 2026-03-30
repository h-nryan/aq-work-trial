#!/bin/bash
set -euo pipefail

# Fix the buggy disk_analyzer.py
cat > /app/disk_analyzer.py << 'EOF'
#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path


def get_size(path):
    """Get size of a file or directory."""
    total = 0
    
    # FIX BUG 1: Use os.lstat() to handle symlinks and get actual file size
    try:
        stat_info = os.lstat(path)
        if os.path.islink(path):
            # For symlinks, return the size of the link itself
            return stat_info.st_size
        elif os.path.isfile(path):
            return stat_info.st_size
        elif os.path.isdir(path):
            total = stat_info.st_size  # Directory entry size
            # Recursively add contents
            try:
                for entry in os.listdir(path):
                    entry_path = os.path.join(path, entry)
                    total += get_size(entry_path)
            except PermissionError:
                pass
    except (OSError, PermissionError):
        return 0
    
    return total


def analyze_directory(root_path, max_depth=None):
    """Analyze disk usage of a directory tree."""
    results = []
    
    def traverse(path, depth=0):
        try:
            size = get_size(path)
            
            results.append({
                'path': str(path),
                'size': size,
                'depth': depth
            })
            
            # FIX BUG 2: Check max_depth BEFORE recursing (use < not >=)
            if os.path.isdir(path) and not os.path.islink(path):
                if max_depth is None or depth < max_depth:
                    try:
                        for entry in os.listdir(path):
                            entry_path = os.path.join(path, entry)
                            traverse(entry_path, depth + 1)
                    except PermissionError:
                        pass
        
        except (PermissionError, OSError):
            # Silently skip inaccessible paths
            pass
    
    traverse(root_path)
    return results


def format_size(size_bytes):
    """Format size in human-readable format."""
    # FIX BUG 3: Use float division for accurate results
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size = size / 1024.0
    return f"{size:.2f} PB"


def main():
    if len(sys.argv) < 2:
        print("Usage: disk_analyzer.py <directory> [--json] [--max-depth N]")
        sys.exit(1)
    
    directory = sys.argv[1]
    output_json = '--json' in sys.argv
    max_depth = None
    
    # Parse max-depth argument
    if '--max-depth' in sys.argv:
        idx = sys.argv.index('--max-depth')
        if idx + 1 < len(sys.argv):
            max_depth = int(sys.argv[idx + 1])
    
    if not os.path.exists(directory):
        print(f"Error: Directory '{directory}' does not exist")
        sys.exit(1)
    
    results = analyze_directory(directory, max_depth)
    
    if output_json:
        print(json.dumps(results, indent=2))
    else:
        for item in sorted(results, key=lambda x: x['size'], reverse=True):
            print(f"{format_size(item['size']):>12} {item['path']}")


if __name__ == '__main__':
    main()
EOF

chmod +x /app/disk_analyzer.py
