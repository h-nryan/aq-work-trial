#!/bin/bash
set -euo pipefail

# Fix the buggy app.py to handle JSONL format correctly
cat > /app/app.py << 'EOF'
#!/usr/bin/env python3
import sys
import json

def process_data(input_file):
    """Process JSON data and compute statistics."""
    total = 0.0
    count = 0
    
    # FIX Bug 1: Read JSONL format (one JSON object per line)
    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            record = json.loads(line)
            
            if 'value' in record:
                # FIX Bug 3: Convert to float to handle both int and string numbers
                value = float(record['value'])
                total += value
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
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
EOF

chmod +x /app/app.py
