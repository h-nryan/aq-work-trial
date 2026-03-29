import subprocess
import json
from pathlib import Path


def test_server_is_running():
    """Test that the Flask server is running and accessible"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "http://localhost:3000/users"],
            capture_output=True, text=True, timeout=5
        )
        status_code = int(result.stdout.strip())
        assert status_code == 200, f"Server not responding, got status {status_code}"
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError) as e:
        assert False, f"Server is not running or not accessible: {e}"


def test_users_endpoint_returns_json():
    """Test that /users endpoint returns valid JSON"""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:3000/users"],
            capture_output=True, text=True, timeout=5
        )
        assert result.returncode == 0, "curl command failed"

        users = json.loads(result.stdout)
        assert isinstance(users, list), "Response should be a list of users"
        assert len(users) > 0, "Should return at least one user"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        assert False, f"Cannot connect to server: {e}"
    except json.JSONDecodeError:
        assert False, "Response is not valid JSON"


def test_users_endpoint_has_correct_structure():
    """Test that users have the expected structure"""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:3000/users"],
            capture_output=True, text=True, timeout=5
        )
        users = json.loads(result.stdout)

        assert len(users) >= 4, "Should have at least 4 users from the data file"

        for user in users:
            assert "id" in user, "Each user should have an id field"
            assert "name" in user, "Each user should have a name field"
            assert "email" in user, "Each user should have an email field"
            assert "role" in user, "Each user should have a role field"
            assert isinstance(user["id"], int), "User id should be an integer"
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        assert False, f"Cannot connect to server or parse response: {e}"


def test_user_by_id_endpoint_valid_id():
    """Test that /users/<id> endpoint returns correct user for valid ID"""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:3000/users/1"],
            capture_output=True, text=True, timeout=5
        )
        assert result.returncode == 0, "curl command failed"

        user = json.loads(result.stdout)
        assert user["id"] == 1, "Should return user with ID 1"
        assert "name" in user, "User should have a name field"
        assert "email" in user, "User should have an email field"
        assert "role" in user, "User should have a role field"
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        assert False, f"Cannot connect to server or parse response: {e}"


def test_user_by_id_endpoint_invalid_id():
    """Test that /users/<id> endpoint returns 404 for invalid ID"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-w", "%{http_code}", "http://localhost:3000/users/999"],
            capture_output=True, text=True, timeout=5
        )

        # Extract status code (last 3 characters) and response body
        output = result.stdout
        status_code = int(output[-3:])
        response_body = output[:-3]

        assert status_code == 404, f"Expected 404 for invalid user ID, got {status_code}"

        error_response = json.loads(response_body)
        assert "error" in error_response, "Error response should contain an error field"
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        assert False, f"Cannot connect to server or parse response: {e}"



def test_requirements_file_exists():
    """Test that requirements.txt file exists and has Flask dependency"""
    requirements_path = Path("/app/requirements.txt")
    assert requirements_path.exists(), "requirements.txt file should exist"

    content = requirements_path.read_text()
    assert "flask" in content.lower(), "requirements.txt should contain Flask dependency"


def test_app_file_exists():
    """Test that app.py file exists and is valid Python"""
    app_path = Path("/app/app.py")
    assert app_path.exists(), "app.py file should exist"

    # Test syntax by trying to parse the file
    try:
        result = subprocess.run(
            ["python3", "-m", "py_compile", "app.py"],
            capture_output=True, text=True, timeout=5, cwd="/app"
        )
        assert result.returncode == 0, f"app.py has syntax errors: {result.stderr}"
    except subprocess.TimeoutExpired:
        assert False, "Python syntax check timed out"


def test_server_handles_multiple_requests():
    """Test that server can handle multiple requests successfully"""
    try:
        for i in range(3):
            result = subprocess.run(
                ["curl", "-s", "-w", "%{http_code}", "http://localhost:3000/users"],
                capture_output=True, text=True, timeout=5
            )

            # Extract status code and response
            output = result.stdout
            status_code = int(output[-3:])
            response_body = output[:-3]

            assert status_code == 200, f"Request {i+1} failed with status {status_code}"

            users = json.loads(response_body)
            assert len(users) >= 4, f"Request {i+1} returned insufficient users"
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        assert False, f"Server failed to handle multiple requests: {e}"


def test_data_file_valid_json():
    """Test that data/users.json is valid JSON with correct structure"""
    data_path = Path("/app/data/users.json")
    assert data_path.exists(), "data/users.json file should exist"

    try:
        with open(data_path, 'r') as file:
            users = json.load(file)

        assert isinstance(users, list), "users.json should contain a list"
        assert len(users) >= 4, "users.json should contain at least 4 users"

        for user in users:
            assert isinstance(user, dict), "Each user should be a dictionary"
            assert "id" in user and isinstance(user["id"], int), "Each user should have an integer id"
            assert "name" in user and isinstance(user["name"], str), "Each user should have a string name"
            assert "email" in user and isinstance(user["email"], str), "Each user should have a string email"
            assert "role" in user and isinstance(user["role"], str), "Each user should have a string role"

    except json.JSONDecodeError as e:
        assert False, f"data/users.json is not valid JSON: {e}"