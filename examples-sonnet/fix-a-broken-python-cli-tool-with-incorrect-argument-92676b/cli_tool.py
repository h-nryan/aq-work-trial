#!/usr/bin/env python3
import sys
import os

def main():
    """Simple CLI tool with broken argument parsing and missing help text."""
    args = sys.argv[1:]
    
    # BUG 1: No comprehensive help text - just shows minimal usage
    if not args:
        print("Error: No command specified")
        sys.exit(1)
    
    # BUG 1 continued: Help flag shows minimal text, not comprehensive
    if args[0] in ['--help', '-h']:
        print("Usage: cli_tool.py <command>")
        sys.exit(0)
    
    command = args[0]
    
    # BUG 2: Incorrect argument parsing - doesn't handle flags with values
    options = {}
    i = 1
    while i < len(args):
        if args[i].startswith('--'):
            key = args[i][2:]
            # BUG 2: Always sets to True, doesn't check for value in next arg
            options[key] = True
            i += 1
        else:
            i += 1
    
    # BUG 3: No command-specific help handling
    if command == 'process':
        # BUG 2 effect: options['input'] is True, not the actual filename
        input_file = options.get('input', '')
        output_file = options.get('output', '')
        
        if not input_file:
            print("Error: --input required")
            sys.exit(1)
        
        print(f"Processing {input_file}")
        if output_file:
            print(f"Output: {output_file}")
    
    elif command == 'analyze':
        # BUG 2 effect: options['file'] is True
        file_path = options.get('file', '')
        verbose = options.get('verbose', False)
        
        if not file_path:
            print("Error: --file required")
            sys.exit(1)
        
        print(f"Analyzing {file_path}")
        if verbose:
            print("Verbose mode enabled")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == '__main__':
    main()
