#!/usr/bin/env bash
# Generate a single task from a topic string.
# Usage: bash scripts/generate.sh "fix a broken Python script"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ $# -lt 1 ]; then
    echo "Usage: bash scripts/generate.sh <topic>"
    echo "Example: bash scripts/generate.sh \"fix a broken Python script\""
    exit 1
fi

cd "$ROOT_DIR/generator"
python3.12 generate.py "$1"
