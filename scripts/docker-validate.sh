#!/usr/bin/env bash
# Run the Docker-based functional validator on a generated task.
# This builds the Docker image, verifies tests fail without solution,
# and verifies tests pass with solution.
#
# Usage: bash scripts/docker-validate.sh <task_dir> [--json] [--no-cleanup]
# Example: bash scripts/docker-validate.sh output/fix-a-broken-python-script

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ $# -lt 1 ]; then
    echo "Usage: bash scripts/docker-validate.sh <task_dir> [--json] [--no-cleanup]"
    echo "Example: bash scripts/docker-validate.sh output/fix-a-broken-python-script"
    exit 1
fi

cd "$ROOT_DIR/validator"
python3.12 docker_validate.py "$@"
