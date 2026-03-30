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

# Create test fixtures
mkdir -p /tmp/test_data

# Simple registry with no circular deps
cat > /tmp/test_data/simple_registry.json << 'EOF'
{
  "pkg-a": {
    "1.0.0": {"pkg-b": "1.0.0"},
    "2.0.0": {"pkg-b": "2.0.0"}
  },
  "pkg-b": {
    "1.0.0": {},
    "2.0.0": {}
  }
}
EOF

cat > /tmp/test_data/simple_requirements.json << 'EOF'
{
  "pkg-a": "1.0.0"
}
EOF

# Registry with circular dependencies
cat > /tmp/test_data/circular_registry.json << 'EOF'
{
  "pkg-x": {
    "1.0.0": {"pkg-y": "1.0.0"}
  },
  "pkg-y": {
    "1.0.0": {"pkg-x": "1.0.0"}
  }
}
EOF

cat > /tmp/test_data/circular_requirements.json << 'EOF'
{
  "pkg-x": "1.0.0"
}
EOF

# Registry with version conflicts
cat > /tmp/test_data/conflict_registry.json << 'EOF'
{
  "app": {
    "1.0.0": {"lib-a": "1.0.0", "lib-b": "1.0.0"}
  },
  "lib-a": {
    "1.0.0": {"common": "1.0.0"}
  },
  "lib-b": {
    "1.0.0": {"common": "2.0.0"}
  },
  "common": {
    "1.0.0": {},
    "2.0.0": {}
  }
}
EOF

cat > /tmp/test_data/conflict_requirements.json << 'EOF'
{
  "app": "1.0.0"
}
EOF

# Run pytest
uv run pytest $TEST_DIR/test_outputs.py -rA
