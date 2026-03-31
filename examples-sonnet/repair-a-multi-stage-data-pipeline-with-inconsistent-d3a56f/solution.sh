#!/bin/bash
set -euo pipefail

cat > /app/date_parser.py << 'EOF'
#!/usr/bin/env python3
import sys
import json
from datetime import datetime, timedelta
import os

def parse_date(date_str, timezone=None, locale=None):
    """Parse date string with timezone and locale support."""
    dt = None
    
    # FIX BUG 1: Support multiple date formats
    formats = [
        '%Y-%m-%d',      # ISO8601
        '%m/%d/%Y',      # US format
        '%d/%m/%Y',      # EU format
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    
    if dt is None:
        return None
    
    # FIX BUG 2: Use correct variable name 'timezone' and apply offset
    if timezone:
        try:
            # Parse timezone like '+0530' or '-0800'
            sign = 1 if timezone[0] == '+' else -1
            hours = int(timezone[1:3])
            minutes = int(timezone[3:5])
            offset = timedelta(hours=sign*hours, minutes=sign*minutes)
            # Adjust datetime by subtracting offset to get UTC
            dt = dt - offset
        except (ValueError, IndexError):
            pass
    
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
            
            # Skip invalid dates gracefully
            if parsed is None:
                continue
            
            # FIX BUG 3: Output in ISO8601 format with timezone
            results.append({
                'original': date_str,
                'normalized': parsed.strftime('%Y-%m-%dT%H:%M:%S+0000'),
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
EOF

chmod +x /app/date_parser.py
