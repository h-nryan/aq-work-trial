# This is a template test file. Each of these functions will be called
# by the test harness to evaluate the final state of the terminal

import os
import re
import csv
import json
import pytest

def test_analysis_report_exists():
    """Test that analysis report was generated"""
    assert os.path.exists('analysis_report.txt'), "analysis_report.txt not found"

def test_analysis_report_content():
    """Test that analysis report contains required sections"""
    with open('analysis_report.txt', 'r') as f:
        content = f.read()
    
    required_sections = [
        'LOG ROTATION ANALYSIS REPORT',
        'SYSTEM OVERVIEW',
        'LOG FILE ANALYSIS', 
        'SUMMARY',
        'RECOMMENDATIONS'
    ]
    
    for section in required_sections:
        assert section in content, f"Missing required section: {section}"
    
    assert 'Total log size:' in content, "Missing total log size calculation"
    assert 'Estimated total savings:' in content, "Missing savings calculation"
    assert 'MB' in content, "Missing size units"

def test_rotation_summary_csv():
    """Test that CSV file was generated with correct structure"""
    assert os.path.exists('rotation_summary.csv'), "rotation_summary.csv not found"
    
    with open('rotation_summary.csv', 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        expected_columns = [
            'log_path',
            'current_size_mb', 
            'days_since_rotation',
            'recommended_schedule',
            'estimated_savings_mb'
        ]
        
        assert header == expected_columns, f"CSV header mismatch. Expected: {expected_columns}, Got: {header}"
        
        rows = list(reader)
        assert len(rows) > 0, "CSV file has no data rows"
        
        first_row = rows[0]
        assert len(first_row) == 5, f"Row should have 5 columns, got {len(first_row)}"
        
        try:
            float(first_row[1])  
            int(first_row[2])    
            float(first_row[4])  
        except ValueError as e:
            pytest.fail(f"Numeric validation failed: {e}")

def test_optimized_logrotate_config():
    """Test that optimized logrotate config was generated"""
    assert os.path.exists('optimized_logrotate.conf'), "optimized_logrotate.conf not found"
    
    with open('optimized_logrotate.conf', 'r') as f:
        content = f.read()
    
    assert 'rotate' in content, "Missing rotation count directive"
    assert 'compress' in content, "Missing compression directive"
    assert '{' in content and '}' in content, "Missing logrotate block structure"
    
    log_files = ['/var/log/samples/app.log', '/var/log/samples/system.log', 
                 '/var/log/samples/access.log', '/var/log/samples/error.log']
    
    found_configs = 0
    for log_file in log_files:
        if log_file in content:
            found_configs += 1
    
    assert found_configs >= 2, f"Should configure at least 2 log files, found {found_configs}"

def test_savings_calculation():
    """Test that savings calculations are reasonable"""
    with open('analysis_report.txt', 'r') as f:
        content = f.read()
    
    savings_match = re.search(r'Potential space reduction: ([\d.]+)%', content)
    assert savings_match, "Savings percentage not found in report"
    
    savings_percent = float(savings_match.group(1))
    assert 0 <= savings_percent <= 100, f"Invalid savings percentage: {savings_percent}%"
    assert savings_percent >= 10, f"Savings should be at least 10%, got {savings_percent}%"

def test_issue_identification():
    """Test that issues are properly identified and categorized"""
    with open('analysis_report.txt', 'r') as f:
        content = f.read()
    
    severity_levels = ['HIGH', 'MEDIUM', 'LOW']
    found_issues = False
    
    for level in severity_levels:
        if f'ISSUE ({level})' in content:
            found_issues = True
            break
    
    assert found_issues, "No issues identified in log analysis"
    
    issue_indicators = [
        'Large file',
        'rotation',
        'size',
        'days'
    ]
    
    found_indicators = sum(1 for indicator in issue_indicators if indicator.lower() in content.lower())
    assert found_indicators >= 2, "Insufficient issue analysis depth"

def test_recommendations_quality():
    """Test that recommendations are actionable and specific"""
    with open('analysis_report.txt', 'r') as f:
        content = f.read()
    
    recommendations_section = content.split('RECOMMENDATIONS:')[1] if 'RECOMMENDATIONS:' in content else ""
    assert recommendations_section, "No recommendations section found"
    
    actionable_terms = [
        'daily', 'weekly', 'monthly',  
        'compression', 'compress',      
        'retention', 'rotate',          
        'monitor', 'disk'              
    ]
    
    found_terms = sum(1 for term in actionable_terms 
                     if term.lower() in recommendations_section.lower())
    assert found_terms >= 3, f"Recommendations lack specificity, found {found_terms} actionable terms"
