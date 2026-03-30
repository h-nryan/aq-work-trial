#!/usr/bin/env python3
import csv
import sys
import json

def read_csv(input_file):
    """Read CSV file and return records."""
    records = []
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    return records

def transform_record(record):
    """Transform a single record."""
    # BUG 1: Missing return statement - causes all records to be None
    transformed = {
        'id': record.get('id', ''),
        'name': record.get('name', ''),
        'value': float(record.get('value', 0)),
        'status': record.get('status', 'unknown')
    }
    # Missing: return transformed

def filter_records(records):
    """Filter out invalid records."""
    valid = []
    for record in records:
        # BUG 2: Wrong comparison operator - uses > instead of >=
        # This incorrectly drops records with value exactly 0
        if record.get('value', 0) > 0:
            valid.append(record)
    return valid

def write_output(records, output_file, format_type='json'):
    """Write records to output file."""
    if format_type == 'json':
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(records, f, indent=2)
    elif format_type == 'csv':
        if not records:
            return
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=records[0].keys())
            writer.writeheader()
            writer.writerows(records)

def process_pipeline(input_file, output_file, format_type='json', skip_filter=False):
    """Main pipeline processing function."""
    # Read input
    records = read_csv(input_file)
    
    # Transform records
    transformed = []
    for record in records:
        result = transform_record(record)
        # BUG 3: Doesn't check if result is None before appending
        transformed.append(result)
    
    # Filter records
    if not skip_filter:
        # BUG 4: Wrong variable name - uses 'records' instead of 'transformed'
        filtered = filter_records(records)
    else:
        filtered = transformed
    
    # Write output
    write_output(filtered, output_file, format_type)
    
    return len(filtered)

def main():
    if len(sys.argv) < 3:
        print("Usage: pipeline.py <input.csv> <output.json> [--format json|csv] [--no-filter]")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    format_type = 'json'
    skip_filter = False
    
    if '--format' in sys.argv:
        idx = sys.argv.index('--format')
        if idx + 1 < len(sys.argv):
            format_type = sys.argv[idx + 1]
    
    if '--no-filter' in sys.argv:
        skip_filter = True
    
    count = process_pipeline(input_file, output_file, format_type, skip_filter)
    print(f"Processed {count} records")

if __name__ == '__main__':
    main()
