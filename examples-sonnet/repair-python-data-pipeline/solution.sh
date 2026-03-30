#!/bin/bash
set -euo pipefail

cat > /app/pipeline.py << 'EOF'
#!/usr/bin/env python3
import csv
import sys
import os

def transform_csv(input_path, output_path):
    """Transform CSV by filtering and enriching records."""
    records_written = 0
    
    with open(input_path, 'r', encoding='utf-8', newline='') as infile:
        reader = csv.DictReader(infile)
        
        with open(output_path, 'w', encoding='utf-8', newline='') as outfile:
            fieldnames = ['id', 'name', 'value', 'status', 'category']
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in reader:
                # FIX BUG 1: Convert empty values to 0 instead of skipping
                value_str = row.get('value', '').strip()
                if not value_str:
                    value = 0
                else:
                    # FIX BUG 2: Handle decimal strings by converting to float first
                    try:
                        value = int(float(value_str))
                    except ValueError:
                        continue
                
                # FIX BUG 3: Empty category strings should default to 'unknown'
                category = row.get('category', '').strip()
                if not category:
                    category = 'unknown'
                
                # Enrich record
                enriched = {
                    'id': row['id'],
                    'name': row['name'],
                    'value': value,
                    'status': 'active' if value > 0 else 'inactive',
                    'category': category
                }
                
                writer.writerow(enriched)
                records_written += 1
    
    return records_written

def main():
    if len(sys.argv) != 3:
        print("Usage: python pipeline.py <input.csv> <output.csv>", file=sys.stderr)
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    
    if not os.path.exists(input_path):
        print(f"Error: Input file '{input_path}' not found", file=sys.stderr)
        sys.exit(1)
    
    try:
        count = transform_csv(input_path, output_path)
        print(f"Processed {count} records", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
EOF

chmod +x /app/pipeline.py
