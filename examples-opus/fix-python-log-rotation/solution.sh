#!/bin/bash

# Fix all bugs in the log rotator script
cat > log_rotator.py << 'SOLUTION_EOF'
#!/usr/bin/env python3
import os
import json
import gzip
import shutil
from datetime import datetime
from pathlib import Path

class LogRotator:
    def __init__(self, config_file):
        with open(config_file, 'r') as f:
            self.config = json.load(f)
    
    def get_file_size(self, filepath):
        """Get file size in bytes"""
        # FIX: Return size in bytes, not KB
        return os.path.getsize(filepath)
    
    def should_rotate(self, log_file, config):
        """Check if log file needs rotation"""
        if not os.path.exists(log_file):
            return False
        
        size = self.get_file_size(log_file)
        max_size = config.get('max_size', 1048576)  # Default 1MB
        
        # Now comparing bytes to bytes correctly
        return size > max_size
    
    def compress_file(self, source, dest):
        """Compress file using gzip"""
        # FIX: Open source in binary mode
        with open(source, 'rb') as f_in:
            with gzip.open(dest, 'wb') as f_out:
                # Now writing bytes to bytes file
                f_out.write(f_in.read())
    
    def rotate_log(self, log_file, config):
        """Rotate a single log file"""
        if not self.should_rotate(log_file, config):
            return False
        
        # Generate rotated filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = os.path.basename(log_file)
        log_dir = os.path.dirname(log_file)
        
        # FIX: Include directory in rotated path
        rotated_name = os.path.join(log_dir, f"{base_name}.{timestamp}")
        
        # Move current log to rotated name
        shutil.move(log_file, rotated_name)
        
        # Create new empty log file
        Path(log_file).touch()
        
        # Compress if enabled
        if config.get('compress', False):
            compressed_name = f"{rotated_name}.gz"
            self.compress_file(rotated_name, compressed_name)
            # FIX: Remove uncompressed file after compression
            os.remove(rotated_name)
        
        # Clean old logs
        self.cleanup_old_logs(log_file, config)
        
        return True
    
    def cleanup_old_logs(self, log_file, config):
        """Remove old rotated logs based on retention policy"""
        keep_count = config.get('keep', 5)
        log_dir = os.path.dirname(log_file)
        base_name = os.path.basename(log_file)
        
        rotated_files = []
        for f in os.listdir(log_dir or '.'):
            # FIX: Better pattern matching for both compressed and uncompressed files
            if f.startswith(base_name + '.') and f != base_name:
                full_path = os.path.join(log_dir or '.', f)
                rotated_files.append(full_path)
        
        # FIX: Sort by modification time (oldest first)
        rotated_files.sort(key=lambda x: os.path.getmtime(x))
        
        # Remove oldest files
        while len(rotated_files) > keep_count:
            old_file = rotated_files.pop(0)
            # FIX: Using full path for removal
            os.remove(old_file)
    
    def run(self):
        """Run log rotation for all configured logs"""
        results = {}
        
        for log_name, log_config in self.config['logs'].items():
            log_file = log_config['path']
            
            try:
                rotated = self.rotate_log(log_file, log_config)
                results[log_name] = {
                    'status': 'rotated' if rotated else 'skipped',
                    'file': log_file
                }
            except Exception as e:
                results[log_name] = {
                    'status': 'error',
                    'file': log_file,
                    'error': str(e)
                }
        
        return results

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python log_rotator.py <config.json>")
        sys.exit(1)
    
    rotator = LogRotator(sys.argv[1])
    results = rotator.run()
    
    # Print results
    for log_name, result in results.items():
        print(f"{log_name}: {result['status']}")
        if 'error' in result:
            print(f"  Error: {result['error']}")
SOLUTION_EOF
