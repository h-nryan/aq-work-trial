#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path


def get_size(path):
    """Get size of a file or directory."""
    total = 0
    
    # BUG 1: Using os.path.getsize() which raises IsADirectoryError on directories
    # Should use os.lstat() or check type first
    if os.path.isfile(path):
        total = os.path.getsize(path)  # This follows symlinks incorrectly
    elif os.path.isdir(path):
        total = os.path.getsize(path)  # BUG: This will raise IsADirectoryError!
        for entry in os.listdir(path):
            entry_path = os.path.join(path, entry)
            total += get_size(entry_path)
    
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
            
            if os.path.isdir(path):
                for entry in os.listdir(path):
                    entry_path = os.path.join(path, entry)
                    # BUG 2: Wrong comparison - uses >= instead of <
                    # This means max_depth=1 allows depth 0,1,2 instead of just 0,1
                    if max_depth is None or depth >= max_depth:
                        traverse(entry_path, depth + 1)
        
        except (PermissionError, OSError):
            # Silently skip inaccessible paths
            pass
    
    traverse(root_path)
    return results


def format_size(size_bytes):
    """Format size in human-readable format."""
    # BUG 3: Using integer division (//) instead of float division (/)
    # This causes incorrect rounding for values like 10240 bytes
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes = size_bytes // 1024  # BUG: Should be / not //
    return f"{size_bytes:.2f} PB"


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
