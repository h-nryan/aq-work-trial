import json
import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path

def run_monitor(metrics_file, *args):
    """Run the monitor script with given arguments."""
    cmd = ['python3', '/app/monitor.py', metrics_file] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode

def create_test_metrics(filename, metrics_data):
    """Create a test metrics file."""
    with open(filename, 'w') as f:
        for timestamp, name, value in metrics_data:
            f.write(f"{timestamp},{name},{value}\n")

def test_basic_metrics_collection():
    """Test that metrics are collected and parsed correctly."""
    test_file = '/tmp/test_basic.csv'
    now = datetime.now().isoformat()
    create_test_metrics(test_file, [
        (now, 'cpu_usage', 50.0),
        (now, 'memory_usage', 70.0)
    ])
    
    stdout, stderr, returncode = run_monitor(test_file, '--stats')
    assert returncode == 0, f"Script failed: {stderr}"
    
    stats = json.loads(stdout)
    assert 'cpu_usage' in stats, "Should collect cpu_usage metric"
    assert 'memory_usage' in stats, "Should collect memory_usage metric"
    assert stats['cpu_usage']['count'] == 1
    assert stats['memory_usage']['count'] == 1



def test_threshold_alerting():
    """Test that alerts are generated when thresholds are exceeded."""
    test_file = '/tmp/test_threshold.csv'
    now = datetime.now().isoformat()
    
    create_test_metrics(test_file, [
        (now, 'cpu_usage', 95.0),
        (now, 'memory_usage', 70.0)
    ])
    
    thresholds = json.dumps({'cpu_usage': 90, 'memory_usage': 80})
    stdout, stderr, returncode = run_monitor(test_file, '--thresholds', thresholds)
    assert returncode == 0, f"Script failed: {stderr}"
    
    result = json.loads(stdout)
    alerts = result['alerts']
    assert len(alerts) == 1, "Should generate one alert for cpu_usage"
    assert alerts[0]['metric'] == 'cpu_usage'
    assert alerts[0]['value'] == 95.0

def test_threshold_boundary():
    """Test that alerts are NOT generated when value equals threshold."""
    test_file = '/tmp/test_boundary.csv'
    now = datetime.now().isoformat()
    
    create_test_metrics(test_file, [
        (now, 'cpu_usage', 90.0)
    ])
    
    thresholds = json.dumps({'cpu_usage': 90})
    stdout, stderr, returncode = run_monitor(test_file, '--thresholds', thresholds)
    assert returncode == 0, f"Script failed: {stderr}"
    
    result = json.loads(stdout)
    alerts = result['alerts']
    assert len(alerts) == 0, "Should NOT alert when value equals threshold"

def test_statistics_calculation():
    """Test that statistics are calculated correctly."""
    test_file = '/tmp/test_stats.csv'
    now = datetime.now().isoformat()
    
    create_test_metrics(test_file, [
        (now, 'cpu_usage', 50.0),
        (now, 'cpu_usage', 70.0),
        (now, 'cpu_usage', 90.0),
        (now, 'memory_usage', 60.0)
    ])
    
    stdout, stderr, returncode = run_monitor(test_file, '--stats')
    assert returncode == 0, f"Script failed: {stderr}"
    
    stats = json.loads(stdout)
    assert stats['cpu_usage']['count'] == 3
    assert stats['cpu_usage']['min'] == 50.0
    assert stats['cpu_usage']['max'] == 90.0
    assert abs(stats['cpu_usage']['avg'] - 70.0) < 0.1, "Average should be 70.0"
    assert stats['memory_usage']['count'] == 1

def test_no_alerts_when_under_threshold():
    """Test that no alerts are generated when all metrics are under threshold."""
    test_file = '/tmp/test_no_alerts.csv'
    now = datetime.now().isoformat()
    
    create_test_metrics(test_file, [
        (now, 'cpu_usage', 50.0),
        (now, 'memory_usage', 60.0)
    ])
    
    thresholds = json.dumps({'cpu_usage': 90, 'memory_usage': 80})
    stdout, stderr, returncode = run_monitor(test_file, '--thresholds', thresholds)
    assert returncode == 0, f"Script failed: {stderr}"
    
    result = json.loads(stdout)
    alerts = result['alerts']
    assert len(alerts) == 0, "Should not generate alerts when under threshold"
