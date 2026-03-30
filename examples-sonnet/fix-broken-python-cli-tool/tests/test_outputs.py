import subprocess
import sys

def run_cli(args):
    """Run the CLI tool with given arguments and return result"""
    result = subprocess.run(
        ['python3', '/app/cli_tool.py'] + args,
        capture_output=True,
        text=True
    )
    return result.stdout, result.stderr, result.returncode

def test_help_flag_works():
    """Test that --help flag displays help information"""
    stdout, stderr, returncode = run_cli(['--help'])
    
    assert returncode == 0, "--help should exit with code 0"
    assert 'convert' in stdout.lower() or 'convert' in stderr.lower(), "Help should mention 'convert' command"
    assert 'validate' in stdout.lower() or 'validate' in stderr.lower(), "Help should mention 'validate' command"

def test_short_help_flag_works():
    """Test that -h flag displays help information"""
    stdout, stderr, returncode = run_cli(['-h'])
    
    assert returncode == 0, "-h should exit with code 0"
    assert len(stdout) > 50 or len(stderr) > 50, "Help text should be substantial"

def test_convert_command_with_required_args():
    """Test that convert command works with required arguments"""
    stdout, stderr, returncode = run_cli(['convert', '--input', 'test.txt', '--output', 'out.txt'])
    
    assert returncode == 0, "Convert command should succeed with required args"
    assert 'test.txt' in stdout, "Output should mention input file"
    assert 'out.txt' in stdout, "Output should mention output file"

def test_convert_command_missing_required_arg():
    """Test that convert command fails without required arguments"""
    stdout, stderr, returncode = run_cli(['convert', '--input', 'test.txt'])
    
    assert returncode != 0, "Convert should fail without --output"
    assert 'required' in stderr.lower() or 'required' in stdout.lower(), "Error should mention required argument"

def test_validate_command_works():
    """Test that validate command works correctly"""
    stdout, stderr, returncode = run_cli(['validate', '--file', 'data.txt'])
    
    assert returncode == 0, "Validate command should succeed"
    assert 'data.txt' in stdout, "Output should mention file being validated"

def test_boolean_flag_handling():
    """Test that boolean flags like --strict work correctly"""
    stdout, stderr, returncode = run_cli(['validate', '--file', 'data.txt', '--strict'])
    
    assert returncode == 0, "Validate with --strict should succeed"
    assert 'strict' in stdout.lower(), "Output should indicate strict mode"

def test_subcommand_help():
    """Test that subcommands have their own help text"""
    stdout, stderr, returncode = run_cli(['convert', '--help'])
    
    assert returncode == 0, "Subcommand help should exit with code 0"
    assert 'input' in stdout.lower() or 'input' in stderr.lower(), "Convert help should mention --input"
    assert 'output' in stdout.lower() or 'output' in stderr.lower(), "Convert help should mention --output"
