#!/bin/bash
# Extract the latest timestamp from an asciinema recording file.
# Usage: get-asciinema-timestamp.sh <recording_file>
#
# Asciinema v2 format: first line is header JSON, subsequent lines are
# [timestamp, event_type, data] arrays. We want the last timestamp.

RECORDING_FILE="$1"

if [ -z "$RECORDING_FILE" ] || [ ! -f "$RECORDING_FILE" ]; then
    echo "0.0"
    exit 0
fi

# Get the last event line's timestamp
tail -1 "$RECORDING_FILE" | python3 -c "
import sys, json
try:
    line = sys.stdin.readline().strip()
    if line:
        event = json.loads(line)
        print(event[0])
    else:
        print('0.0')
except:
    print('0.0')
"
