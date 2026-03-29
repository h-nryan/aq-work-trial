from pathlib import Path
import os


def test_hello_file_exists():
    """Test that hello.txt file exists in the current directory."""
    hello_path = Path("/app/hello.txt")

    assert hello_path.exists(), f"File {hello_path} does not exist"


def test_hello_file_content():
    """Test that hello.txt contains exactly 'Hello, world!' followed by a newline."""
    hello_path = Path("/app/hello.txt")

    assert hello_path.read_text().strip() == "Hello, world!", (
        f"Expected 'Hello, world!' but got '{hello_path.read_text().strip()}'"
    )


def test_hello_file_is_file():
    """Test that hello.txt is a file and not a directory."""
    hello_path = Path("/app/hello.txt")

    assert hello_path.is_file(), f"{hello_path} is not a file"


def test_hello_file_size():
    """Test that hello.txt has the expected size."""
    hello_path = Path("/app/hello.txt")

    # "Hello, world!\n" is 14 bytes
    assert hello_path.stat().st_size > 0, f"{hello_path} is empty"


def test_hello_file_permissions():
    """Test that hello.txt has read permissions."""
    hello_path = Path("/app/hello.txt")

    assert os.access(hello_path, os.R_OK), f"{hello_path} is not readable"


def test_hello_file_encoding():
    """Test that hello.txt can be read as text."""
    hello_path = Path("/app/hello.txt")

    try:
        content = hello_path.read_text(encoding='utf-8')
        assert isinstance(content, str), f"{hello_path} content is not text"
    except UnicodeDecodeError:
        assert False, f"{hello_path} is not properly encoded"


def test_hello_file_exact_content():
    """Test that hello.txt contains exactly 'Hello, world!' with proper formatting."""
    hello_path = Path("/app/hello.txt")

    content = hello_path.read_text()
    # Should contain the exact string
    assert "Hello, world!" in content, f"{hello_path} does not contain 'Hello, world!'"
    # Should not contain extra characters at the beginning
    assert content.startswith("Hello, world!"), f"{hello_path} does not start with 'Hello, world!'"