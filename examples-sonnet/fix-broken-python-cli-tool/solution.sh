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
        description='CLI tool for data conversion and validation',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Convert command
    convert_parser = subparsers.add_parser('convert', help='Convert data files')
    convert_parser.add_argument('--input', required=True, help='Input file path')
    convert_parser.add_argument('--output', required=True, help='Output file path')
    convert_parser.add_argument('--format', default='json', help='Output format (default: json)')
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate data files')
    validate_parser.add_argument('--file', required=True, help='File to validate')
    validate_parser.add_argument('--strict', action='store_true', help='Enable strict validation')
    
    return parser

def process_convert(args):
    """Convert data with given options"""
    print(f"Converting {args.input} to {args.format}")
    print(f"Output: {args.output}")
    return True

def process_validate(args):
    """Validate data file"""
    print(f"Validating {args.file}")
    if args.strict:
        print("Strict mode enabled")
    return True

def main():
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == 'convert':
        success = process_convert(args)
    elif args.command == 'validate':
        success = process_validate(args)
    else:
        print(f"Unknown command: {args.command}")
        sys.exit(1)
    
    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main()
EOF

chmod +x /app/cli_tool.py
