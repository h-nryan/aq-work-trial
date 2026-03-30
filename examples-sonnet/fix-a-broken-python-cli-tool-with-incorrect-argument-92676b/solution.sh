#!/bin/bash
set -euo pipefail

# Fix the broken CLI tool with proper argument parsing and help text
cat > /app/cli_tool.py << 'EOF'
#!/usr/bin/env python3
import sys
import argparse

def create_parser():
    """Create argument parser with proper help text"""
    parser = argparse.ArgumentParser(
        description='CLI tool for file processing and analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Process command
    process_parser = subparsers.add_parser('process', help='Process input files')
    process_parser.add_argument('--input', required=True, help='Input file path')
    process_parser.add_argument('--output', help='Output file path')
    
    # Analyze command
    analyze_parser = subparsers.add_parser('analyze', help='Analyze data files')
    analyze_parser.add_argument('--file', required=True, help='File to analyze')
    analyze_parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    
    return parser

def process_command(args):
    """Handle process command"""
    print(f"Processing {args.input}")
    if args.output:
        print(f"Output: {args.output}")
    return True

def analyze_command(args):
    """Handle analyze command"""
    print(f"Analyzing {args.file}")
    if args.verbose:
        print("Verbose mode enabled")
    return True

def main():
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == 'process':
        success = process_command(args)
    elif args.command == 'analyze':
        success = analyze_command(args)
    else:
        print(f"Unknown command: {args.command}")
        sys.exit(1)
    
    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main()
EOF

chmod +x /app/cli_tool.py
