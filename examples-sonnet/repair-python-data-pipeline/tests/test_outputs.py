import csv
import os
from pathlib import Path

def read_csv_records(filepath):
    """Read CSV file and return list of records."""
    with open(filepath, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        return list(reader)

def test_basic_transformation():
    """Test that basic CSV transformation works correctly."""
    records = read_csv_records('/tmp/output1.csv')
    
    assert len(records) == 3, f"Expected 3 records, got {len(records)}"
    
    # Check first record
    assert records[0]['id'] == '1'
    assert records[0]['name'] == 'Alice'
    assert records[0]['value'] == '100'
    assert records[0]['status'] == 'active'
    assert records[0]['category'] == 'premium'

def test_decimal_values_handled():
    """Test that decimal string values like '42.0' are converted correctly."""
    records = read_csv_records('/tmp/output2.csv')
    
    # Should have all 3 records including the one with 42.0
    assert len(records) == 3, f"Expected 3 records (decimal values should not be dropped), got {len(records)}"
    
    # Find the record with value 42
    david_record = next((r for r in records if r['name'] == 'David'), None)
    assert david_record is not None, "Record for David with value 42.0 should be present"
    assert david_record['value'] == '42', f"Expected value '42', got {david_record['value']}"

def test_empty_values_converted_to_zero():
    """Test that empty value fields are converted to 0 instead of being dropped."""
    records = read_csv_records('/tmp/output3.csv')
    
    # Should have all 3 records including Grace with empty value
    assert len(records) == 3, f"Expected 3 records (empty value should not be dropped), got {len(records)}"
    
    # Find Grace's record
    grace_record = next((r for r in records if r['name'] == 'Grace'), None)
    assert grace_record is not None, "Record for Grace with empty value should be present"
    assert grace_record['value'] == '0', f"Empty value should be converted to 0, got {grace_record['value']}"
    assert grace_record['status'] == 'inactive', "Record with value 0 should have status 'inactive'"

def test_missing_category_defaults():
    """Test that missing category field defaults to 'unknown'."""
    records = read_csv_records('/tmp/output3.csv')
    
    # Find Iris's record (has empty category)
    iris_record = next((r for r in records if r['name'] == 'Iris'), None)
    assert iris_record is not None, "Record for Iris should be present"
    assert iris_record['category'] == 'unknown', f"Empty category should default to 'unknown', got '{iris_record['category']}'"

def test_all_records_written():
    """Test that no records are silently dropped during transformation."""
    records = read_csv_records('/tmp/output4.csv')
    
    # input4.csv has 5 records, all should be written
    assert len(records) == 5, f"Expected 5 records, got {len(records)} - records are being dropped"
    
    # Verify all names are present
    names = [r['name'] for r in records]
    expected_names = ['Jack', 'Kate', 'Liam', 'Mia', 'Noah']
    for name in expected_names:
        assert name in names, f"Record for {name} was dropped"
