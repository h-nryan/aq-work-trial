#!/bin/bash
set -euo pipefail

# Fix all bugs in the CSV processor
cat > /app/csv_processor.py << 'EOF'
#!/usr/bin/env python3
import sys
import csv
import json

def read_csv(filepath):
    """Read CSV file and return list of rows."""
    rows = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows

def filter_by_column(rows, column, value):
    """Filter rows where column equals value."""
    return [row for row in rows if row.get(column) == value]

def aggregate_sum(rows, column):
    """Calculate sum of numeric column."""
    total = 0.0
    for row in rows:
        try:
            total += float(row.get(column, 0))
        except (ValueError, TypeError):
            pass
    return total

def aggregate_count(rows, column):
    """Count occurrences of each unique value in column."""
    counts = {}
    for row in rows:
        value = row.get(column, '')
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts

def sort_by_column(rows, column, reverse=False):
    """Sort rows by column value."""
    return sorted(rows, key=lambda x: x.get(column, ''), reverse=reverse)

def output_json(data):
    """Output data as JSON."""
    print(json.dumps(data, indent=2))

def output_csv(rows, columns=None):
    """Output rows as CSV."""
    if not rows:
        return
    
    if columns is None:
        columns = list(rows[0].keys())
    
    writer = csv.DictWriter(sys.stdout, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)

def main():
    if len(sys.argv) < 2:
        print("Usage: csv_processor.py <file.csv> [--filter COLUMN VALUE] [--sum COLUMN] [--count COLUMN] [--sort COLUMN] [--reverse] [--json]")
        sys.exit(1)
    
    filepath = sys.argv[1]
    
    # Parse arguments
    filter_column = None
    filter_value = None
    sum_column = None
    count_column = None
    sort_column = None
    reverse = False
    output_format = 'csv'
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--filter' and i + 2 < len(sys.argv):
            filter_column = sys.argv[i + 1]
            filter_value = sys.argv[i + 2]
            i += 3
        elif sys.argv[i] == '--sum' and i + 1 < len(sys.argv):
            sum_column = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--count' and i + 1 < len(sys.argv):
            count_column = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--sort' and i + 1 < len(sys.argv):
            sort_column = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--reverse':
            reverse = True
            i += 1
        elif sys.argv[i] == '--json':
            output_format = 'json'
            i += 1
        else:
            i += 1
    
    # Read CSV
    rows = read_csv(filepath)
    
    # Apply operations
    if filter_column and filter_value:
        rows = filter_by_column(rows, filter_column, filter_value)
    
    if sort_column:
        rows = sort_by_column(rows, sort_column, reverse)
    
    if sum_column:
        result = aggregate_sum(rows, sum_column)
        print(result)
        return
    
    if count_column:
        result = aggregate_count(rows, count_column)
        output_json(result)
        return
    
    # Output results
    if output_format == 'json':
        output_json(rows)
    else:
        output_csv(rows)

if __name__ == '__main__':
    main()
EOF

chmod +x /app/csv_processor.py
