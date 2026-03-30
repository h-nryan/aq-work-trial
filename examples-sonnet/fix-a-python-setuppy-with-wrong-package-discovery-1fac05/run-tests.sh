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

cat > /tmp/test_data/transactions.csv << 'EOF'
date,category,amount,description
2024-01-15,food,45.50,Grocery shopping
2024-01-16,transport,12.00,Bus fare
2024-01-17,food,32.75,Restaurant
2024-01-18,entertainment,25.00,Movie tickets
2024-01-20,food,18.50,Coffee shop
2024-01-22,transport,15.00,Taxi
2024-01-25,entertainment,40.00,Concert
2024-01-28,food,55.25,Dinner
EOF

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
