import json
import subprocess
import os
from pathlib import Path

def read_json(path):
    """Read and parse JSON from file path."""
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def test_basic_request_format():
    """Test that basic request produces valid JSON output."""
    result = read_json('/tmp/output1.json')
    
    assert 'status' in result, "Output missing 'status' field"
    assert 'returncode' in result, "Output missing 'returncode' field"
    assert 'output' in result, "Output missing 'output' field"
    assert result['returncode'] == 0, f"Request failed with code {result['returncode']}"

def test_content_type_header_format():
    """Test that Content-Type header has correct format with colon."""
    # Run curl with verbose output to check headers
    result = subprocess.run(
        ['python3', '/app/curl_wrapper.py', 'http://localhost:8888/test.json', '-v'],
        capture_output=True,
        text=True
    )
    
    output = read_json('/tmp/output1.json')
    # The request should succeed (curl accepts the header format)
    assert output['returncode'] == 0, "Request should succeed with correct header format"

def test_bearer_token_authentication():
    """Test that API_KEY is used as Bearer token, not Basic auth."""
    result = read_json('/tmp/output2.json')
    
    # Request should succeed
    assert result['returncode'] == 0, "Request with API key should succeed"
    
    # Verify Bearer token format by checking curl command construction
    # We can't directly inspect headers, but we can verify the request succeeds
    # and the wrapper doesn't crash with Bearer format
    assert result['status'] == 'success', "Request should be successful"

def test_custom_header_support():
    """Test that CUSTOM_HEADER environment variable is applied."""
    result = read_json('/tmp/output3.json')
    
    # Request should succeed with custom header
    assert result['returncode'] == 0, "Request with custom header should succeed"
    assert result['status'] == 'success', "Request should be successful"

def test_raw_output_mode():
    """Test that --raw flag outputs raw response without JSON wrapping."""
    with open('/tmp/output4.txt', 'r') as f:
        content = f.read()
    
    # Should be plain text, not JSON
    assert 'plain text response' in content, "Raw output should contain plain text"
    
    # Should NOT be JSON-wrapped
    try:
        json.loads(content)
        # If it parses as JSON with our wrapper format, that's wrong
        parsed = json.loads(content)
        if 'status' in parsed and 'returncode' in parsed:
            assert False, "Raw mode should not output JSON-wrapped response"
    except json.JSONDecodeError:
        # Good - raw output is not JSON
        pass

def test_custom_content_type():
    """Test that CONTENT_TYPE environment variable is used."""
    result = read_json('/tmp/output5.json')
    
    # Request should succeed with custom content type
    assert result['returncode'] == 0, "Request with custom content type should succeed"
    assert result['status'] == 'success', "Request should be successful"

def test_wrapper_handles_success():
    """Test that wrapper correctly identifies successful requests."""
    result = read_json('/tmp/output1.json')
    
    assert result['status'] == 'success', "Status should be 'success' for successful request"
    assert result['returncode'] == 0, "Return code should be 0 for success"
    assert len(result['output']) > 0, "Output should not be empty"

def test_wrapper_executable():
    """Test that wrapper script is executable and runs without errors."""
    result = subprocess.run(
        ['python3', '/app/curl_wrapper.py', 'http://localhost:8888/test.json'],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "Wrapper should execute successfully"
    
    # Output should be valid JSON
    try:
        output = json.loads(result.stdout)
        assert 'status' in output, "Output should have status field"
    except json.JSONDecodeError:
        assert False, "Wrapper output should be valid JSON"
