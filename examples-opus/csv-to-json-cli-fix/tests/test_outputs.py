import json
import subprocess
import os
from pathlib import Path

def read_json(p):
    """Read and parse JSON from file path."""
    txt = Path(p).read_text(encoding="utf-8")
    return json.loads(txt)

def test_commas_records_as_objects():
    """
    Test that CSV with comma delimiter produces JSON array of objects 
    with header keys mapped to row values.
    """
    data = read_json("/tmp/out_commas.json")
    assert isinstance(data, list) and len(data) == 2
    assert data[0] == {"name":"Asha","age":"29","city":"Mumbai"}
    assert data[1] == {"name":"Rohit","age":"34","city":"Delhi"}

def test_default_delimiter_is_comma():
    """
    Test that when DELIM environment variable is not set, 
    the script defaults to comma delimiter.
    """
    # Ensure DELIM is not set
    env = os.environ.copy()
    env.pop('DELIM', None)
    
    # Run script and capture stdout
    result = subprocess.run(
        ['python', 'csv_to_json.py', 'inputs/sample_commas.csv'],
        capture_output=True, text=True, env=env
    )
    
    # Verify it successfully parsed comma-delimited file
    data = json.loads(result.stdout)
    assert isinstance(data, list) and len(data) == 2
    assert data[0] == {"name":"Asha","age":"29","city":"Mumbai"}

def test_utf8_stdout_encoding():
    """
    Test that the script writes valid UTF-8 JSON to stdout.
    """
    result = subprocess.run(
        ['python', 'csv_to_json.py', 'inputs/sample_commas.csv'],
        capture_output=True, text=True, encoding='utf-8'
    )
    
    # Should not raise encoding errors and produce valid JSON
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    
    # Verify stdout bytes are valid UTF-8
    stdout_bytes = result.stdout.encode('utf-8')
    decoded = stdout_bytes.decode('utf-8')
    assert decoded == result.stdout

def test_semicolons_with_env_delim():
    """
    Test that DELIM environment variable controls the delimiter used for parsing.
    """
    data = read_json("/tmp/out_semicolons.json")
    assert data[0]["name"] == "Meera" and data[0]["city"] == "Bengaluru"
    assert data[1]["name"] == "Arjun" and data[1]["age"] == "31"

def test_pretty_flag_changes_format_only():
    """
    Test that --pretty flag produces indented JSON without changing data content.
    """
    # Ensure it's valid JSON and same structure as compact output
    pretty = read_json("/tmp/out_pretty.json")
    compact = read_json("/tmp/out_commas.json")
    assert pretty == compact, "--pretty must not change data content"
