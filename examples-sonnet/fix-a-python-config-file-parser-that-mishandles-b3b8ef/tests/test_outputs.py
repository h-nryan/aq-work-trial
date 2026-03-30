import subprocess
import sys
from pathlib import Path

# Import the config parser for direct testing
sys.path.insert(0, '/app')
from config_parser import ConfigParser


def test_parse_full_config():
    """Test parsing a config file with all values specified."""
    parser = ConfigParser('/tmp/configs/full.conf')
    config = parser.parse()
    
    assert parser.get('host') == 'example.com', "Should parse host correctly"
    assert parser.get_int('port') == 9000, "Should parse port as integer"
    assert parser.get_bool('debug') == True, "Should parse debug as boolean"
    assert parser.get_int('timeout') == 60, "Should parse timeout as integer"
    assert parser.get_int('max_connections') == 200, "Should parse max_connections as integer"


def test_parse_partial_config_with_defaults():
    """Test that missing values use defaults from the defaults dictionary."""
    parser = ConfigParser('/tmp/configs/partial.conf')
    config = parser.parse()
    
    assert parser.get('host') == 'api.example.com', "Should use parsed host"
    assert parser.get_int('port') == 3000, "Should use parsed port"
    # These should come from defaults since not in config file
    assert parser.get_bool('debug') == False, "Should use default debug value"
    assert parser.get_int('timeout') == 30, "Should use default timeout value"
    assert parser.get_int('max_connections') == 100, "Should use default max_connections"


def test_type_coercion_integers():
    """Test that integer values are properly coerced from strings."""
    parser = ConfigParser('/tmp/configs/types.conf')
    config = parser.parse()
    
    port = parser.get_int('port')
    assert isinstance(port, int), f"Port should be int, got {type(port)}"
    assert port == 8888, f"Port should be 8888, got {port}"
    
    timeout = parser.get_int('timeout')
    assert isinstance(timeout, int), f"Timeout should be int, got {type(timeout)}"
    assert timeout == 45, f"Timeout should be 45, got {timeout}"


def test_type_coercion_booleans():
    """Test that boolean values are properly coerced from strings."""
    parser = ConfigParser('/tmp/configs/types.conf')
    config = parser.parse()
    
    debug = parser.get_bool('debug')
    assert isinstance(debug, bool), f"Debug should be bool, got {type(debug)}"
    assert debug == False, f"Debug should be False, got {debug}"


def test_empty_config_uses_all_defaults():
    """Test that an empty config file returns all default values."""
    parser = ConfigParser('/tmp/configs/empty.conf')
    config = parser.parse()
    
    assert parser.get('host') == 'localhost', "Should use default host"
    assert parser.get_int('port') == 8080, "Should use default port"
    assert parser.get_bool('debug') == False, "Should use default debug"
    assert parser.get_int('timeout') == 30, "Should use default timeout"
    assert parser.get_int('max_connections') == 100, "Should use default max_connections"


def test_get_with_custom_default():
    """Test that get() method respects custom default parameter."""
    parser = ConfigParser('/tmp/configs/partial.conf')
    config = parser.parse()
    
    # Key that doesn't exist - should use provided default
    custom_value = parser.get('custom_key', 'custom_default')
    assert custom_value == 'custom_default', f"Should use custom default, got {custom_value}"
    
    # Integer with custom default
    custom_int = parser.get_int('missing_int', 999)
    assert custom_int == 999, f"Should use custom int default, got {custom_int}"


def test_cli_output_format():
    """Test that CLI output shows all configuration values correctly."""
    result = subprocess.run(
        ['python3', '/app/config_parser.py', '/tmp/configs/full.conf'],
        capture_output=True,
        text=True
    )
    
    assert result.returncode == 0, "CLI should exit successfully"
    output = result.stdout
    
    assert 'example.com' in output, "Output should contain host value"
    assert '9000' in output, "Output should contain port value"
    assert 'true' in output.lower() or 'True' in output, "Output should show debug as true"
    assert '60' in output, "Output should contain timeout value"
    assert '200' in output, "Output should contain max_connections value"
