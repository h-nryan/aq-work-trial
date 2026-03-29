#!/usr/bin/env bash
# Run the structural validator on a generated task.
# Usage: bash scripts/validate.sh output/my-task

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ $# -lt 1 ]; then
    echo "Usage: bash scripts/validate.sh <task_dir>"
    echo "Example: bash scripts/validate.sh output/fix-a-broken-python-script"
    exit 1
fi

cd "$ROOT_DIR/validator"
python validate.py "$1"
