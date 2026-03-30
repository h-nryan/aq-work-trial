#!/bin/bash
set -euo pipefail

cat > /app/cli_tool.py << 'EOF'
#!/usr/bin/env python3
import sys
import json

def handle_status(args):
    """Handle status subcommand."""
    if '--format' in args:
        idx = args.index('--format')
        if idx + 1 < len(args):
            fmt = args[idx + 1]
        else:
            fmt = 'text'
    else:
        fmt = 'text'
    
    status_data = {'status': 'running', 'uptime': 3600}
    
    if fmt == 'json':
        print(json.dumps(status_data))
    else:
        print(f"Status: {status_data['status']}")
        print(f"Uptime: {status_data['uptime']}s")
    return 0

def handle_config(args):
    """Handle config subcommand."""
    if '--get' in args:
        idx = args.index('--get')
        if idx + 1 < len(args):
            key = args[idx + 1]
        else:
            print("Error: --get requires a key", file=sys.stderr)
            return 2
    else:
        key = None
    
    config = {'host': 'localhost', 'port': 8080, 'debug': False}
    
    if key:
        if key in config:
            print(f"{key}={config[key]}")
        else:
            print(f"Error: key '{key}' not found", file=sys.stderr)
            return 1
    else:
        for k, v in config.items():
            print(f"{k}={v}")
    return 0

def handle_list(args):
    """Handle list subcommand."""
    if '--verbose' in args:
        verbose = True
    else:
        verbose = False
    
    items = ['item1', 'item2', 'item3']
    
    if verbose:
        for i, item in enumerate(items, 1):
            print(f"{i}. {item} (active)")
    else:
        for item in items:
            print(item)
    return 0

def main():
    if len(sys.argv) < 2:
        print("Usage: cli_tool.py <command> [options]", file=sys.stderr)
        return 1
    
    command = sys.argv[1]
    args = sys.argv[2:]
    
    if command == 'status':
        return handle_status(args)
    elif command == 'config':
        return handle_config(args)
    elif command == 'list':
        return handle_list(args)
    else:
        print(f"Error: unknown command '{command}'", file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
EOF

chmod +x /app/cli_tool.py
