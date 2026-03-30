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

# Create test log files
mkdir -p /tmp/test_logs

# Test log file with various levels and timestamps
cat > /tmp/test_logs/app.log << 'EOF'
2024-01-15 10:30:45 [INFO] Application started
2024-01-15 10:31:12 [DEBUG] Loading configuration
2024-01-15 10:31:15 [INFO] Configuration loaded successfully
2024-01-15 10:32:00 [WARNING] High memory usage detected
2024-01-15 10:32:30 [ERROR] Database connection failed
2024-01-15 10:33:00 [ERROR] Retry attempt 1 failed
2024-01-15 10:33:30 [INFO] Database connection restored
2024-01-15 10:34:00 [DEBUG] Processing request
2024-01-15 10:35:00 [INFO] Request completed successfully
2024-01-15 10:36:00 [WARNING] Cache miss for key: user_123
EOF

# Run the parser with different options and save outputs
python3 /app/log_parser.py /tmp/test_logs/app.log > /tmp/output_all.txt
python3 /app/log_parser.py /tmp/test_logs/app.log --level ERROR > /tmp/output_errors.txt
python3 /app/log_parser.py /tmp/test_logs/app.log --start "2024-01-15 10:32:00" --end "2024-01-15 10:34:00" > /tmp/output_timerange.txt
python3 /app/log_parser.py /tmp/test_logs/app.log --stats > /tmp/output_stats.json
python3 /app/log_parser.py /tmp/test_logs/app.log --json > /tmp/output_json.json
python3 /app/log_parser.py /tmp/test_logs/app.log --level WARNING --json > /tmp/output_warnings.json

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
