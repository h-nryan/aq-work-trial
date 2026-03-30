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

# Create test data files
mkdir -p /tmp/test_data

# Create metrics file with various timestamps
cat > /tmp/test_data/metrics.csv << 'EOF'
2024-01-15T10:00:00,cpu_usage,45.5
2024-01-15T10:01:00,memory_usage,78.2
2024-01-15T10:02:00,cpu_usage,92.3
2024-01-15T10:03:00,disk_usage,65.0
2024-01-15T10:04:00,memory_usage,85.7
2024-01-15T10:05:00,cpu_usage,55.1
2024-01-15T10:06:00,network_throughput,120.5
EOF

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
