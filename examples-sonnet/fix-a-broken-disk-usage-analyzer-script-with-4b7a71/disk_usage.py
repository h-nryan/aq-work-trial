#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path


def get_file_size(path):
    try:
        # BUG: Should use os.lstat() instead of os.path.getsize() to avoid following symlinks
        return os.path.getsize(path)
    except (OSError, PermissionError):
        return 0


def calculate_directory_size(path, follow_symlinks=False):
    total_size = 0
    
    try:
        # BUG: Missing check for symlinks before recursing - should check os.path.islink(path)
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
    results = []
    
    try:
        size = calculate_directory_size(root_path)
        results.append({
            'path': root_path,
            'size': size,
            'depth': current_depth
        })
        
        # BUG: Wrong comparison operator - should use < instead of >= for max_depth check
        if os.path.isdir(root_path) and (max_depth is None or current_depth >= max_depth):
            for entry in os.listdir(root_path):
                entry_path = os.path.join(root_path, entry)
                child_results = traverse_directory(entry_path, max_depth, current_depth + 1)
                results.extend(child_results)
    except (PermissionError, OSError):
        pass
    
    return results


def format_size(size_bytes):
    # BUG: Using integer division (//) instead of float division (/) loses precision
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
