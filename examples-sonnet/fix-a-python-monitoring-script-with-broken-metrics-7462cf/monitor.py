#!/usr/bin/env python3
import sys
import json
import time
from datetime import datetime, timedelta

def collect_metrics(source_file):
    """Collect metrics from a data source file."""
    metrics = []
    try:
        with open(source_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(',')
                if len(parts) >= 3:
                    timestamp = parts[0]
                    metric_name = parts[1]
                    try:
                        value = float(parts[2])
                        metrics.append({
                            'timestamp': timestamp,
                            'name': metric_name,
                            'value': value
                        })
                    except ValueError:
                        continue
    except FileNotFoundError:
        print(f"Error: File {source_file} not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading metrics: {e}")
        sys.exit(1)
    
    return metrics

def filter_stale_metrics(metrics, max_age_seconds=300):
    """Filter out metrics older than max_age_seconds."""
    current_time = datetime.now()
    fresh_metrics = []
    
    for metric in metrics:
        try:
            metric_time = datetime.fromisoformat(metric['timestamp'])
            age = (current_time - metric_time).total_seconds()
            if age <= max_age_seconds:
                fresh_metrics.append(metric)
        except ValueError:
            continue
    
    return fresh_metrics

def check_thresholds(metrics, thresholds):
    """Check if metrics exceed defined thresholds."""
    alerts = []
    
    for metric in metrics:
        metric_name = metric['name']
        value = metric['value']
        
        if metric_name in thresholds:
            threshold = thresholds[metric_name]
            if value >= threshold:
                alerts.append({
                    'metric': metric_name,
                    'value': value,
                    'threshold': threshold,
                    'timestamp': metric['timestamp']
                })
    
    return alerts

def calculate_statistics(metrics):
    """Calculate statistics for collected metrics."""
    stats = {}
    
    for metric in metrics:
        name = metric['name']
        value = metric['value']
        
        if name not in stats:
            stats[name] = {
                'count': 0,
                'sum': 0,
                'min': value,
                'max': value,
                'values': []
            }
        
        stats[name]['count'] += 1
        stats[name]['sum'] += value
        stats[name]['min'] = min(stats[name]['min'], value)
        stats[name]['max'] = max(stats[name]['max'], value)
        stats[name]['values'].append(value)
    
    for name in stats:
        if stats[name]['count'] > 0:
            stats[name]['avg'] = stats[name]['sum'] / stats[name]['count']
        del stats[name]['values']
        del stats[name]['sum']
    
    return stats

def main():
    if len(sys.argv) < 2:
        print("Usage: monitor.py <metrics_file> [--thresholds THRESHOLDS_JSON] [--max-age SECONDS] [--stats]")
        sys.exit(1)
    
    metrics_file = sys.argv[1]
    thresholds = {}
    max_age = 300
    show_stats = False
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--thresholds' and i + 1 < len(sys.argv):
            try:
                thresholds = json.loads(sys.argv[i + 1])
            except json.JSONDecodeError:
                print("Error: Invalid JSON for thresholds")
                sys.exit(1)
            i += 2
        elif sys.argv[i] == '--max-age' and i + 1 < len(sys.argv):
            try:
                max_age = int(sys.argv[i + 1])
            except ValueError:
                print("Error: Invalid max-age value")
                sys.exit(1)
            i += 2
        elif sys.argv[i] == '--stats':
            show_stats = True
            i += 1
        else:
            i += 1
    
    metrics = collect_metrics(metrics_file)
    fresh_metrics = filter_stale_metrics(metrics, max_age)
    
    if show_stats:
        stats = calculate_statistics(fresh_metrics)
        print(json.dumps(stats, indent=2))
    else:
        alerts = check_thresholds(fresh_metrics, thresholds)
        if alerts:
            print(json.dumps({'alerts': alerts}, indent=2))
        else:
            print(json.dumps({'alerts': []}, indent=2))

if __name__ == '__main__':
    main()
