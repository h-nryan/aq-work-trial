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

def test_help_flag_shows_commands():
    """Test that --help flag displays available commands"""
    stdout, stderr, returncode = run_cli(['--help'])
    
    assert returncode == 0, "--help should exit with code 0"
    output = stdout + stderr
    assert 'process' in output.lower(), "Help should mention 'process' command"
    assert 'analyze' in output.lower(), "Help should mention 'analyze' command"
    assert len(output) > 100, "Help text should be comprehensive"

def test_short_help_flag_works():
    """Test that -h flag displays help information"""
    stdout, stderr, returncode = run_cli(['-h'])
    
    assert returncode == 0, "-h should exit with code 0"
    output = stdout + stderr
    assert len(output) > 50, "Help text should be substantial"

def test_process_command_with_args():
    """Test that process command works with required arguments"""
    stdout, stderr, returncode = run_cli(['process', '--input', 'test.txt', '--output', 'out.txt'])
    
    assert returncode == 0, "Process command should succeed with required args"
    assert 'test.txt' in stdout, "Output should mention input file"
    assert 'out.txt' in stdout, "Output should mention output file"

def test_process_command_missing_input():
    """Test that process command fails without required --input argument"""
    stdout, stderr, returncode = run_cli(['process', '--output', 'out.txt'])
    
    assert returncode != 0, "Process should fail without --input"
    output = stdout + stderr
    assert 'required' in output.lower() or 'input' in output.lower(), "Error should mention required argument"

def test_analyze_command_works():
    """Test that analyze command works correctly"""
    stdout, stderr, returncode = run_cli(['analyze', '--file', 'data.txt'])
    
    assert returncode == 0, "Analyze command should succeed"
    assert 'data.txt' in stdout, "Output should mention file being analyzed"

def test_verbose_flag_handling():
    """Test that boolean flags like --verbose work correctly"""
    stdout, stderr, returncode = run_cli(['analyze', '--file', 'data.txt', '--verbose'])
    
    assert returncode == 0, "Analyze with --verbose should succeed"
    assert 'verbose' in stdout.lower(), "Output should indicate verbose mode"

def test_command_specific_help():
    """Test that commands have their own help text"""
    stdout, stderr, returncode = run_cli(['process', '--help'])
    
    assert returncode == 0, "Command help should exit with code 0"
    output = stdout + stderr
    assert 'input' in output.lower(), "Process help should mention --input"
    assert 'output' in output.lower(), "Process help should mention --output"
