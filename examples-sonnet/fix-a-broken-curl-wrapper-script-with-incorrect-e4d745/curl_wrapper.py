#!/usr/bin/env python3
import sys
import subprocess
import json
import os

def parse_args():
    """Parse command line arguments for curl wrapper."""
    args = sys.argv[1:]
    
    url = None
    headers = []
    method = "POST"  # BUG 4: Wrong default method - should be GET
    data = None
    auth = None
    output_file = None
    
    i = 0
    while i < len(args):
        arg = args[i]
        
        if arg == "-H" or arg == "--header":
            if i + 1 < len(args):
                headers.append(args[i + 1])
                i += 2
            else:
                i += 1
        elif arg == "-X" or arg == "--request":
            if i + 1 < len(args):
                method = args[i + 1]
                i += 2
            else:
                i += 1
        elif arg == "-d" or arg == "--data":
            if i + 1 < len(args):
                data = args[i + 1]
                i += 2
            else:
                i += 1
        elif arg == "-u" or arg == "--user":
            if i + 1 < len(args):
                auth = args[i + 1]
                i += 2
            else:
                i += 1
        elif arg == "-o" or arg == "--output":
            if i + 1 < len(args):
                output_file = args[i + 1]
                i += 2
            else:
                i += 1
        elif not arg.startswith("-"):
            url = arg
            i += 1
        else:
            i += 1
    
    return url, headers, method, data, auth, output_file

def build_curl_command(url, headers, method, data, auth):
    """Build curl command with proper header and auth handling."""
    cmd = ["curl", "-s"]
    
    # BUG 1: Headers not properly formatted - missing -H flag for each header
    for header in headers:
        cmd.append(header)
    
    if method != "GET":
        cmd.extend(["-X", method])
    
    if data:
        cmd.extend(["-d", data])
    
    # BUG 2: Auth header constructed incorrectly - should use Basic auth format
    if auth:
        cmd.extend(["-H", f"Authorization: {auth}"])
    
    cmd.append(url)
    
    return cmd

def execute_request(url, headers, method, data, auth, output_file):
    """Execute the curl request."""
    if not url:
        print("Error: URL required", file=sys.stderr)
        return 1
    
    cmd = build_curl_command(url, headers, method, data, auth)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(result.stdout)
        else:
            print(result.stdout)
        
        # BUG 3: Not returning curl's exit code - always returns 0
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

def main():
    url, headers, method, data, auth, output_file = parse_args()
    exit_code = execute_request(url, headers, method, data, auth, output_file)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
