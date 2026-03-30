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

# Create test input files
mkdir -p /tmp/test_data

# Test 1: Basic CSV with valid records
cat > /tmp/test_data/input1.csv << 'EOF'
id,name,value,status
1,Alice,100,active
2,Bob,200,active
3,Charlie,150,inactive
EOF

# Test 2: CSV with zero values
cat > /tmp/test_data/input2.csv << 'EOF'
id,name,value,status
1,Zero,0,active
2,Positive,50,active
EOF

# Test 3: CSV with mixed values
cat > /tmp/test_data/input3.csv << 'EOF'
id,name,value,status
1,Item1,25.5,active
2,Item2,0,active
3,Item3,75.25,inactive
4,Item4,100,active
EOF

# Test 4: Empty CSV
cat > /tmp/test_data/input4.csv << 'EOF'
id,name,value,status
EOF

# Run the pipeline with different configurations
python3 /app/pipeline.py /tmp/test_data/input1.csv /tmp/test_data/output1.json
python3 /app/pipeline.py /tmp/test_data/input2.csv /tmp/test_data/output2.json
python3 /app/pipeline.py /tmp/test_data/input3.csv /tmp/test_data/output3.json --no-filter
python3 /app/pipeline.py /tmp/test_data/input1.csv /tmp/test_data/output4.csv --format csv
python3 /app/pipeline.py /tmp/test_data/input4.csv /tmp/test_data/output5.json

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
