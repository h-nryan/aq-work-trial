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

# Create test config files
mkdir -p /tmp/configs

# Config with all values specified
cat > /tmp/configs/full.conf << 'EOF'
host=example.com
port=9000
debug=true
timeout=60
max_connections=200
EOF

# Config with some values missing (should use defaults)
cat > /tmp/configs/partial.conf << 'EOF'
host=api.example.com
port=3000
EOF

# Config with type coercion needed
cat > /tmp/configs/types.conf << 'EOF'
port=8888
debug=false
timeout=45
EOF

# Empty config (should use all defaults)
touch /tmp/configs/empty.conf

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
