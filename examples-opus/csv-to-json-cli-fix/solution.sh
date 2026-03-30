#!/usr/bin/env bash
set -euo pipefail

cat > /app/csv_to_json.py << 'PY'
import os, sys, json, csv

def main():
    args = sys.argv[1:]
    pretty = False
    if args and args[0] == "--pretty":
        pretty = True
        args = args[1:]
    if len(args) != 1:
        print("usage: python csv_to_json.py [--pretty] <input.csv>")
        sys.exit(2)

    path = args[0]
    delim = os.environ.get("DELIM", ",")
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f, delimiter=delim)
        rows = list(reader)

    if not rows:
        print("[]")
        return

    header, *data_rows = rows
    out = [ { header[i]: row[i] if i < len(row) else "" for i in range(len(header)) } for row in data_rows ]

    if pretty:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(out, ensure_ascii=False, separators=(",",":")))
if __name__ == "__main__":
    main()
PY
chmod +x /app/csv_to_json.py
