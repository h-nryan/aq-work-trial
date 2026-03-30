#!/bin/bash
set -euo pipefail

# Fix all bugs in curl_wrapper.py
cat > /app/curl_wrapper.py << 'EOF'
#!/usr/bin/env python3
import sys
import subprocess
import json
import os

def parse_args():
    """Parse command line arguments for curl wrapper."""
    if len(sys.argv) < 2:
        print("Usage: curl_wrapper.py <url> [options]")
        sys.exit(1)
    
    url = sys.argv[1]
    options = sys.argv[2:]
    return url, options

def build_curl_command(url, options):
    """Build curl command with proper headers and authentication."""
    cmd = ['curl', '-s']
    
    # FIX BUG 1: Correct header format with colon separator
    content_type = os.environ.get('CONTENT_TYPE', 'application/json')
    cmd.extend(['-H', f'Content-Type: {content_type}'])
    
    # Using Bearer token authentication (correct)
    api_key = os.environ.get('API_KEY', '')
    if api_key:
        cmd.extend(['-H', f'Authorization: Bearer {api_key}'])
    
    # Handle custom headers from environment (correct)
    custom_header = os.environ.get('CUSTOM_HEADER', '')
    if custom_header:
        cmd.extend(['-H', custom_header])
    
    # Add user-provided options
    cmd.extend(options)
    cmd.append(url)
    
    return cmd

def execute_curl(cmd):
    """Execute curl command and return response."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        return '', 'Request timed out', 1

def format_response(stdout, stderr, returncode):
    """Format response as JSON."""
    response = {
        'status': 'success' if returncode == 0 else 'error',
        'returncode': returncode,
        'output': stdout,
        'error': stderr
    }
    return json.dumps(response, indent=2)

def main():
    url, options = parse_args()
    
    # FIX BUG 2: Check for correct flag name --raw
    raw_mode = '--raw' in options
    if raw_mode:
        options = [opt for opt in options if opt != '--raw']
    
    cmd = build_curl_command(url, options)
    stdout, stderr, returncode = execute_curl(cmd)
    
    if raw_mode:
        print(stdout, end='')
    else:
        output = format_response(stdout, stderr, returncode)
        print(output)

if __name__ == '__main__':
    main()
EOF

chmod +x /app/curl_wrapper.py
