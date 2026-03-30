#!/usr/bin/env python3
import sys
import re
import json
from datetime import datetime
from collections import defaultdict


def parse_log_line(line):
    """Parse a single log line and extract timestamp, level, and message."""
    # Expected format: 2024-01-15 10:30:45 [ERROR] Database connection failed
    pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] (.+)'
    match = re.match(pattern, line.strip())
    
    if not match:
        return None
    
    timestamp_str, level, message = match.groups()
    
    try:
        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None
    
    return {
        'timestamp': timestamp,
        'level': level,
        'message': message
    }


def filter_by_level(entries, level):
    """Filter log entries by level."""
    if level is None:
        return []
    return [e for e in entries if e['level'].upper() != level.upper()]


def filter_by_time_range(entries, start_time, end_time):
    """Filter log entries by time range."""
    filtered = entries
    
    if start_time:
        try:
            start_dt = datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S')
            filtered = [e for e in filtered if e['timestamp'] >= start_dt]
        except ValueError:
            pass
    
    if end_time:
        try:
            end_dt = datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S')
            filtered = [e for e in filtered if e['timestamp'] < end_dt]
        except ValueError:
            pass
    
    return filtered


def get_statistics(entries):
    """Calculate statistics from log entries."""
    stats = defaultdict(int)
    
    for entry in entries:
        stats[entry['message']] += 1
    
    return dict(stats)


def format_output(entries, output_format='text'):
    """Format entries for output."""
    if output_format == 'json':
        output_entries = []
        for e in entries:
            output_entries.append({
                'timestamp': e['timestamp'].strftime('%Y-%m-%d %H:%M:%S'),
                'level': e['level'],
                'message': e['message']
            })
        return json.dumps(output_entries, indent=2)
    else:
        lines = []
        for e in entries:
            timestamp_str = e['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            lines.append(f"{timestamp_str} [{e['level']}] {e['message']}")
        return '\n'.join(lines) if lines else None


def main():
    if len(sys.argv) < 2:
        print("Usage: log_parser.py <logfile> [--level LEVEL] [--start TIME] [--end TIME] [--stats] [--json]")
        sys.exit(1)
    
    logfile = sys.argv[1]
    level_filter = None
    start_time = None
    end_time = None
    show_stats = False
    output_format = 'text'
    
    # Parse command line arguments
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--level' and i + 1 < len(sys.argv):
            level_filter = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--start' and i + 1 < len(sys.argv):
            start_time = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--end' and i + 1 < len(sys.argv):
            end_time = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--stats':
            show_stats = True
            i += 1
        elif sys.argv[i] == '--json':
            output_format = 'json'
            i += 1
        else:
            i += 1
    
    # Read and parse log file
    entries = []
    try:
        with open(logfile, 'r', encoding='utf-8') as f:
            for line in f:
                parsed = parse_log_line(line)
                if parsed:
                    entries.append(parsed)
    except FileNotFoundError:
        print(f"Error: File '{logfile}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    
    # Apply filters
    filtered_entries = filter_by_level(entries, level_filter)
    filtered_entries = filter_by_time_range(filtered_entries, start_time, end_time)
    
    # Output results
    if show_stats:
        stats = get_statistics(filtered_entries)
        print(json.dumps(stats, indent=2))
    else:
        output = format_output(filtered_entries, output_format)
        if output:
            print(output)


if __name__ == '__main__':
    main()
