#!/bin/bash
set -euo pipefail

# Fix the processor.py to correct all bugs
cat > /app/src/processor.py << 'EOF'
#!/usr/bin/env python3
import sys
import json
import csv
from datetime import datetime

def load_data(filepath):
    """Load data from CSV file."""
    records = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records

def filter_by_date(records, start_date, end_date):
    """Filter records by date range."""
    filtered = []
    
    for record in records:
        try:
            record_date = datetime.strptime(record['date'], '%Y-%m-%d')
            
            if start_date:
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                if record_date < start_dt:
                    continue
            
            if end_date:
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                if record_date > end_dt:
                    continue
            
            filtered.append(record)
        except (ValueError, KeyError):
            continue
    
    return filtered

def aggregate_by_category(records):
    """Aggregate records by category."""
    aggregated = {}
    
    for record in records:
        category = record.get('category', 'unknown')
        amount = float(record.get('amount', 0))
        
        if category in aggregated:
            aggregated[category] += amount
        else:
            aggregated[category] = amount
    
    return aggregated

def format_output(data, output_format='json'):
    """Format output data."""
    return json.dumps(data, indent=2, sort_keys=True)

def main():
    if len(sys.argv) < 2:
        print("Usage: dataprocessor <input.csv> [--start DATE] [--end DATE] [--format FORMAT]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    start_date = None
    end_date = None
    output_format = 'json'
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--start' and i + 1 < len(sys.argv):
            start_date = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--end' and i + 1 < len(sys.argv):
            end_date = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--format' and i + 1 < len(sys.argv):
            output_format = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    
    try:
        records = load_data(input_file)
        filtered = filter_by_date(records, start_date, end_date)
        aggregated = aggregate_by_category(filtered)
        output = format_output(aggregated, output_format)
        print(output)
    except FileNotFoundError:
        print(f"Error: File '{input_file}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
EOF
