import sys
import json
# naive: assumes comma delimiter, no header, outputs list-of-lists

def main():
    if len(sys.argv) != 2 or sys.argv[1].startswith("-"):
        print("usage: python csv_to_json.py <input.csv>")
        sys.exit(2)

    path = sys.argv[1]
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")  # BUG: hard-coded delimiter
            rows.append(parts)

    # BUG: ignores header; emits lists instead of dicts; no pretty option
    print(json.dumps(rows))

if __name__ == "__main__":
    main()
