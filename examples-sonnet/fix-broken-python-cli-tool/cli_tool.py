#!/usr/bin/env python3
import sys
import argparse

def parse_arguments():
    """Parse command line arguments with incorrect parsing logic"""
    # BUG 1: Manual argument parsing instead of using argparse properly
    # This causes issues with help text and flag handling
    args = sys.argv[1:]
    
    if not args:
        print("Error: No arguments provided")
        sys.exit(1)
    
    # BUG 2: Minimal help text implementation - doesn't show commands
    if args[0] == "--help" or args[0] == "-h":
        print("Usage: cli_tool.py <command> [options]")
        sys.exit(0)
    
    command = args[0]
    options = {}
    
    # BUG 3: Incorrect flag parsing - doesn't handle values after flags
    # Treats all flags as boolean True instead of capturing their values
    i = 1
    while i < len(args):
        if args[i].startswith("--"):
            flag = args[i][2:]
            options[flag] = True  # BUG: should check if next arg is value and capture it
            i += 1
        else:
            i += 1
    
    return command, options

def process_convert(options):
    """Convert data with given options"""
    # BUG 4: Only checks input, doesn't validate that output is provided
    input_file = options.get("input", "")
    output_file = options.get("output", "")
    format_type = options.get("format", "json")
    
    if not input_file:
        print("Error: --input required")
        return False
    
    # BUG: Since options['input'] = True (not the actual filename),
    # this will print "Converting True to json" instead of actual filename
    print(f"Converting {input_file} to {format_type}")
    return True

def process_validate(options):
    """Validate data file"""
    file_path = options.get("file", "")
    
    if not file_path:
        print("Error: --file required")
        return False
    
    # BUG: options['file'] = True, so prints "Validating True"
    print(f"Validating {file_path}")
    # BUG: doesn't check or use 'strict' option even if provided
    return True

def main():
    command, options = parse_arguments()
    
    if command == "convert":
        success = process_convert(options)
    elif command == "validate":
        success = process_validate(options)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
