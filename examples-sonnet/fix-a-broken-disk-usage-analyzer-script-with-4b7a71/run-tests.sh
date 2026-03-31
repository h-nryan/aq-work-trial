#!/bin/bash

# Install curl

# Install uv


# Check if we're in a valid working directory
if [ "$PWD" = "/" ]; then
    echo "Error: No working directory set. Please set a WORKDIR in your Dockerfile before running this script."
    exit 1
fi

uv init
uv add pytest==8.4.1

# Create test directory structure
mkdir -p /tmp/test_disk/dir1/dir2/dir3
mkdir -p /tmp/test_disk/dir1/dir4
mkdir -p /tmp/test_disk/dir5

# Create test files with known sizes
echo "small" > /tmp/test_disk/small.txt
dd if=/dev/zero of=/tmp/test_disk/medium.dat bs=1024 count=5 2>/dev/null
dd if=/dev/zero of=/tmp/test_disk/dir1/large.dat bs=1024 count=50 2>/dev/null
echo "nested" > /tmp/test_disk/dir1/dir2/nested.txt
echo "deep" > /tmp/test_disk/dir1/dir2/dir3/deep.txt

# Create symlink
ln -s /tmp/test_disk/small.txt /tmp/test_disk/symlink.txt

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
