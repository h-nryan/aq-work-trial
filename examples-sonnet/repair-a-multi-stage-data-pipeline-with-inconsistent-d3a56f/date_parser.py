#!/usr/bin/env python3
import sys
import json
from datetime import datetime
import os

def parse_date(date_str, timezone=None, locale=None):
    """Parse date string with timezone and locale support."""
    # FIXME: Only handles ISO8601 format - need to support US (MM/DD/YYYY) and EU (DD/MM/YYYY) formats too
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None
    
    # FIXME: Wrong variable name - should use 'timezone' not 'tz_offset'
    if timezone:
        # Parse timezone offset and adjust datetime
        sign = 1 if tz_offset[0] == '+' else -1
        hours = int(tz_offset[1:3])
        minutes = int(tz_offset[3:5])
    
    return dt

def normalize_dates(input_file, output_file, target_timezone=None):
    """Read dates from input, normalize them, write to output."""
    results = []
    
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split('|')
            if len(parts) < 2:
                continue
            
            date_str = parts[0].strip()
            timezone = parts[1].strip() if len(parts) > 1 else None
            locale = parts[2].strip() if len(parts) > 2 else None
            
            parsed = parse_date(date_str, timezone, locale)
            
            # Skip None returns gracefully
            if parsed is None:
                continue
            
            if parsed:
                # FIXME: Missing timezone in output format - should be '%Y-%m-%dT%H:%M:%S+0000'
                results.append({
                    'original': date_str,
                    'normalized': parsed.strftime('%Y-%m-%d'),
                    'timezone': timezone
                })
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    
    return len(results)

def main():
    if len(sys.argv) < 3:
        print("Usage: date_parser.py <input_file> <output_file> [--target-tz TIMEZONE]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    target_tz = None
    
    # Parse optional timezone argument
    if len(sys.argv) > 3 and sys.argv[3] == '--target-tz':
        target_tz = sys.argv[4] if len(sys.argv) > 4 else None
    
    if not os.path.exists(input_file):
        print(f"Error: Input file '{input_file}' not found")
        sys.exit(1)
    
    count = normalize_dates(input_file, output_file, target_tz)
    print(f"Processed {count} dates")

if __name__ == '__main__':
    main()
