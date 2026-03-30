import subprocess
import json
import time
import os
import signal
from threading import Thread

server_process = None

def setup_module(module):
    """Start test HTTP server before running tests."""
    global server_process
    server_process = subprocess.Popen(
        ['python3', '/tmp/test_server.py', '8080'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(2)

def teardown_module(module):
    """Stop test HTTP server after tests."""
    global server_process
    if server_process:
        server_process.terminate()
        server_process.wait(timeout=5)

def run_wrapper(args):
    """Run curl wrapper and return stdout, stderr, returncode."""
    result = subprocess.run(
        ['python3', '/app/curl_wrapper.py'] + args,
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode

def test_basic_get_request():
    """Test that basic GET request works."""
    stdout, stderr, returncode = run_wrapper(['http://localhost:8080/test'])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    data = json.loads(stdout)
    assert data['status'] == 'ok'
    assert data['method'] == 'GET'

def test_custom_header_formatting():
    """Test that custom headers are properly formatted and sent."""
    stdout, stderr, returncode = run_wrapper([
        '-H', 'X-Custom-Header: test-value',
        'http://localhost:8080/headers'
    ])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    data = json.loads(stdout)
    assert 'X-Custom-Header' in data, "Custom header not found in response"
    assert data['X-Custom-Header'] == 'test-value', f"Expected 'test-value', got {data.get('X-Custom-Header')}"

def test_multiple_headers():
    """Test that multiple headers are all properly sent."""
    stdout, stderr, returncode = run_wrapper([
        '-H', 'X-Header-One: value1',
        '-H', 'X-Header-Two: value2',
        'http://localhost:8080/headers'
    ])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    data = json.loads(stdout)
    assert 'X-Header-One' in data, "First header not found"
    assert 'X-Header-Two' in data, "Second header not found"
    assert data['X-Header-One'] == 'value1'
    assert data['X-Header-Two'] == 'value2'

def test_basic_authentication():
    """Test that Basic authentication header is properly formatted."""
    stdout, stderr, returncode = run_wrapper([
        '-u', 'testuser:testpass',
        'http://localhost:8080/headers'
    ])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    data = json.loads(stdout)
    assert 'Authorization' in data, "Authorization header not found"
    auth_header = data['Authorization']
    assert auth_header.startswith('Basic '), f"Expected 'Basic ' prefix, got {auth_header}"
    
    # Verify base64 encoding
    import base64
    encoded_part = auth_header.split(' ')[1]
    decoded = base64.b64decode(encoded_part).decode('utf-8')
    assert decoded == 'testuser:testpass', f"Expected 'testuser:testpass', got {decoded}"

def test_post_request_with_data():
    """Test that POST requests with data work correctly."""
    test_data = '{"key": "value"}'
    stdout, stderr, returncode = run_wrapper([
        '-X', 'POST',
        '-d', test_data,
        'http://localhost:8080/test'
    ])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    data = json.loads(stdout)
    assert data['method'] == 'POST'
    assert data['data'] == test_data

def test_exit_code_on_invalid_url():
    """Test that wrapper returns non-zero exit code for invalid URLs."""
    stdout, stderr, returncode = run_wrapper(['http://localhost:9999/nonexistent'])
    
    # curl should fail with non-zero exit code for connection refused
    assert returncode != 0, f"Expected non-zero exit code for invalid URL, got {returncode}"

def test_output_to_file():
    """Test that -o flag saves output to file."""
    output_file = '/tmp/test_output.json'
    
    # Clean up any existing file
    if os.path.exists(output_file):
        os.remove(output_file)
    
    stdout, stderr, returncode = run_wrapper([
        '-o', output_file,
        'http://localhost:8080/test'
    ])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    assert os.path.exists(output_file), "Output file was not created"
    
    with open(output_file, 'r') as f:
        data = json.load(f)
    
    assert data['status'] == 'ok'
    
    # Clean up
    os.remove(output_file)
