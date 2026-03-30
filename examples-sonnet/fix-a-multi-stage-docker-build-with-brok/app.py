#!/usr/bin/env python3
import sys
import json

def process_data(input_file):
    """Process JSON data and compute statistics."""
    total = 0
    count = 0
    
    # BUG 1: Using json.load instead of reading line-by-line JSONL
    # This will fail on JSONL format (multiple JSON objects)
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    # BUG 2: Assuming data is a single object, but should iterate lines
    for record in data:
        if 'value' in record:
            # BUG 3: Not converting to float, will fail on string numbers
            total += record['value']
            count += 1
    
    if count == 0:
        return {'average': 0, 'total': 0, 'count': 0}
    
    average = total / count
    
    return {
        'average': average,
        'total': total,
        'count': count
    }

def main():
    if len(sys.argv) != 3:
        print("Usage: python app.py <input.jsonl> <output.json>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    try:
        result = process_data(input_file)
        
        with open(output_file, 'w') as f:
            json.dump(result, f)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
