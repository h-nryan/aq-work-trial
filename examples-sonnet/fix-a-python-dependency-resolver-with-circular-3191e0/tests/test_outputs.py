import subprocess
import json
import pytest


def run_resolver(registry_file, requirements_file):
    """Run the resolver and return stdout, stderr, and return code."""
    result = subprocess.run(
        ['python3', '/app/resolver.py', 'resolve', registry_file, requirements_file],
        capture_output=True,
        text=True,
        timeout=5
    )
    return result.stdout, result.stderr, result.returncode


def test_simple_dependency_resolution():
    """Test that simple dependencies are resolved correctly."""
    stdout, stderr, returncode = run_resolver(
        '/tmp/test_data/simple_registry.json',
        '/tmp/test_data/simple_requirements.json'
    )
    
    assert returncode == 0, f"Resolver failed: {stderr}"
    result = json.loads(stdout)
    
    assert 'pkg-a' in result, "Should resolve pkg-a"
    assert 'pkg-b' in result, "Should resolve transitive dependency pkg-b"
    assert result['pkg-a'] == '1.0.0', "Should use correct version for pkg-a"
    assert result['pkg-b'] == '1.0.0', "Should use correct version for pkg-b"


def test_circular_dependency_detection():
    """Test that circular dependencies are detected and reported."""
    stdout, stderr, returncode = run_resolver(
        '/tmp/test_data/circular_registry.json',
        '/tmp/test_data/circular_requirements.json'
    )
    
    assert returncode != 0, "Should fail with non-zero exit code for circular dependencies"
    error_output = stdout + stderr
    assert 'circular' in error_output.lower(), "Error message should mention circular dependency"


def test_version_constraint_respected():
    """Test that version constraints are respected during resolution."""
    stdout, stderr, returncode = run_resolver(
        '/tmp/test_data/simple_registry.json',
        '/tmp/test_data/simple_requirements.json'
    )
    
    assert returncode == 0, f"Resolver failed: {stderr}"
    result = json.loads(stdout)
    
    # Should use version 1.0.0 as specified in requirements
    assert result['pkg-a'] == '1.0.0', "Should respect version constraint from requirements"
    assert result['pkg-b'] == '1.0.0', "Should use matching dependency version"


def test_no_infinite_loop_on_circular_deps():
    """Test that resolver doesn't hang on circular dependencies."""
    try:
        stdout, stderr, returncode = run_resolver(
            '/tmp/test_data/circular_registry.json',
            '/tmp/test_data/circular_requirements.json'
        )
        # Should complete (not timeout) and return error
        assert returncode != 0, "Should exit with error for circular dependencies"
    except subprocess.TimeoutExpired:
        pytest.fail("Resolver hung on circular dependencies (infinite loop)")


def test_transitive_dependencies():
    """Test that transitive dependencies are included in resolution."""
    stdout, stderr, returncode = run_resolver(
        '/tmp/test_data/simple_registry.json',
        '/tmp/test_data/simple_requirements.json'
    )
    
    assert returncode == 0, f"Resolver failed: {stderr}"
    result = json.loads(stdout)
    
    # pkg-a depends on pkg-b, both should be in result
    assert len(result) >= 2, "Should include both direct and transitive dependencies"
    assert 'pkg-a' in result and 'pkg-b' in result, "Should resolve all transitive deps"


def test_output_format():
    """Test that output is valid JSON with correct format."""
    stdout, stderr, returncode = run_resolver(
        '/tmp/test_data/simple_registry.json',
        '/tmp/test_data/simple_requirements.json'
    )
    
    assert returncode == 0, f"Resolver failed: {stderr}"
    
    # Should be valid JSON
    result = json.loads(stdout)
    assert isinstance(result, dict), "Output should be a JSON object"
    
    # Each key should be a package name, each value a version string
    for pkg, ver in result.items():
        assert isinstance(pkg, str), "Package names should be strings"
        assert isinstance(ver, str), "Versions should be strings"


def test_missing_package_error():
    """Test that missing packages produce appropriate errors."""
    # Create requirements for non-existent package
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump({"nonexistent-pkg": "1.0.0"}, f)
        missing_req_file = f.name
    
    try:
        stdout, stderr, returncode = run_resolver(
            '/tmp/test_data/simple_registry.json',
            missing_req_file
        )
        
        assert returncode != 0, "Should fail for missing package"
        error_output = stdout + stderr
        assert 'not found' in error_output.lower() or 'error' in error_output.lower(), \
            "Should report error for missing package"
    finally:
        import os
        os.unlink(missing_req_file)
