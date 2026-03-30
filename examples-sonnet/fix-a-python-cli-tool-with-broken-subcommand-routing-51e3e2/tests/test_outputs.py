import subprocess
import sys
import json

def run_cli(args):
    """Run the CLI tool with given arguments and return result."""
    result = subprocess.run(
        ['python3', '/app/cli_tool.py'] + args,
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode

def test_status_command_text_format():
    """Test that status command outputs text format by default."""
    stdout, stderr, returncode = run_cli(['status'])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    assert 'Status:' in stdout, "Output should contain 'Status:'"
    assert 'Uptime:' in stdout, "Output should contain 'Uptime:'"
    assert 'running' in stdout, "Status should show 'running'"

def test_status_command_json_format():
    """Test that status command supports JSON output format."""
    stdout, stderr, returncode = run_cli(['status', '--format', 'json'])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    data = json.loads(stdout)
    assert 'status' in data, "JSON should contain 'status' key"
    assert 'uptime' in data, "JSON should contain 'uptime' key"
    assert data['status'] == 'running', "Status should be 'running'"

def test_config_command_list_all():
    """Test that config command lists all configuration without arguments."""
    stdout, stderr, returncode = run_cli(['config'])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    assert 'host=' in stdout, "Output should contain 'host=' config"
    assert 'port=' in stdout, "Output should contain 'port=' config"
    assert 'debug=' in stdout, "Output should contain 'debug=' config"

def test_config_command_get_specific_key():
    """Test that config command can retrieve specific configuration key."""
    stdout, stderr, returncode = run_cli(['config', '--get', 'host'])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    assert 'host=localhost' in stdout, "Output should show host=localhost"

def test_config_command_invalid_key():
    """Test that config command handles invalid keys correctly."""
    stdout, stderr, returncode = run_cli(['config', '--get', 'invalid_key'])
    
    assert returncode == 1, f"Expected exit code 1 for invalid key, got {returncode}"
    assert 'not found' in stderr or 'not found' in stdout, "Should report key not found"

def test_list_command_default():
    """Test that list command outputs items in simple format by default."""
    stdout, stderr, returncode = run_cli(['list'])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    lines = stdout.strip().split('\n')
    assert len(lines) == 3, "Should list 3 items"
    assert 'item1' in stdout, "Should contain item1"
    assert 'item2' in stdout, "Should contain item2"
    assert 'item3' in stdout, "Should contain item3"

def test_list_command_verbose():
    """Test that list command supports verbose output with --verbose flag."""
    stdout, stderr, returncode = run_cli(['list', '--verbose'])
    
    assert returncode == 0, f"Expected exit code 0, got {returncode}"
    assert '1.' in stdout, "Verbose output should include numbering"
    assert 'active' in stdout, "Verbose output should show status"
    assert 'item1' in stdout and 'item2' in stdout, "Should list all items"



def test_missing_required_argument():
    """Test that missing required arguments are handled correctly."""
    stdout, stderr, returncode = run_cli(['config', '--get'])
    
    assert returncode == 2, f"Expected exit code 2 for missing argument, got {returncode}"
    assert 'requires' in stderr or 'requires' in stdout, "Should indicate missing required argument"
