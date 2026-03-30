#!/usr/bin/env bash
# Generate a high-quality task with Opus, validate it, and prepare for promotion.
#
# Usage:
#   bash scripts/generate-exemplar.sh <topic> [--skip-functional] [--output-dir <dir>]
#
# Examples:
#   bash scripts/generate-exemplar.sh "fix a broken Python CSV parser"
#   bash scripts/generate-exemplar.sh "debug a Node.js async race condition" --skip-functional
#   bash scripts/generate-exemplar.sh "repair a flaky pytest fixture" --output-dir /tmp/tasks
#
# What it does:
#   1. Generates a task using Opus (solution-first, skip-eval)
#   2. Runs structural validation
#   3. Optionally runs functional validation in Docker (skip with --skip-functional)
#   4. Prints next-step instructions (Opus eval, then promote)
#
# This script does NOT run Opus evaluation or promote the task — those are
# separate steps. This script generates and validates only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Parse args ────────────────────────────────────────────────────────────────
TOPIC=""
SKIP_FUNCTIONAL=false
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-functional) SKIP_FUNCTIONAL=true; shift ;;
        --output-dir)      OUTPUT_DIR="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        -*)
            echo "Error: unknown option '$1'" >&2
            echo "Run with --help for usage." >&2
            exit 1
            ;;
        *)
            if [[ -z "$TOPIC" ]]; then
                TOPIC="$1"
            else
                echo "Error: unexpected argument '$1'" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$TOPIC" ]]; then
    echo "Usage: bash scripts/generate-exemplar.sh <topic> [--skip-functional] [--output-dir <dir>]"
    exit 1
fi

# ── Step 1: Generate with Opus ───────────────────────────────────────────────
echo "=== Generate Exemplar ==="
echo "  Topic: $TOPIC"
echo "  Model: anthropic/claude-opus-4"
echo ""

PIPELINE_CMD=(
    python3.12 "$ROOT_DIR/generator/pipeline.py" "$TOPIC"
    --model anthropic/claude-opus-4
    --solution-first
    --skip-eval
)

if [[ -n "$OUTPUT_DIR" ]]; then
    echo "  Output: $OUTPUT_DIR (custom)"
    echo ""
    # The pipeline writes to output/ by default; we'll move it after
fi

echo "[1/3] Generating task with Opus..."
echo "  Running: ${PIPELINE_CMD[*]}"
echo ""

PIPELINE_OUTPUT=$("${PIPELINE_CMD[@]}" 2>&1) || {
    echo "FAILED: Pipeline exited with an error." >&2
    echo "" >&2
    echo "$PIPELINE_OUTPUT" >&2
    exit 1
}

echo "$PIPELINE_OUTPUT"
echo ""

# Extract the task directory from the pipeline JSON output
TASK_DIR=$(echo "$PIPELINE_OUTPUT" | python3.12 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if line.startswith('{'):
        try:
            data = json.loads(line + sys.stdin.read())
            print(data.get('task_dir', ''))
        except:
            pass
        break
" 2>/dev/null)

if [[ -z "$TASK_DIR" || ! -d "$TASK_DIR" ]]; then
    # Fallback: try to find it from the last JSON blob in output
    TASK_DIR=$(echo "$PIPELINE_OUTPUT" | python3.12 -c "
import sys, json
text = sys.stdin.read()
# Find the last JSON object in the output
import re
matches = re.findall(r'\{[^{}]*\}', text, re.DOTALL)
for m in reversed(matches):
    try:
        data = json.loads(m)
        if 'task_dir' in data:
            print(data['task_dir'])
            break
    except:
        continue
" 2>/dev/null)
fi

if [[ -z "$TASK_DIR" || ! -d "$TASK_DIR" ]]; then
    echo "Error: Could not determine task directory from pipeline output." >&2
    echo "Check the output above for details." >&2
    exit 1
fi

# If --output-dir was given, move the task there
if [[ -n "$OUTPUT_DIR" ]]; then
    TASK_NAME="$(basename "$TASK_DIR")"
    mkdir -p "$OUTPUT_DIR"
    NEW_TASK_DIR="$OUTPUT_DIR/$TASK_NAME"
    mv "$TASK_DIR" "$NEW_TASK_DIR"
    TASK_DIR="$NEW_TASK_DIR"
    echo "  Moved to: $TASK_DIR"
fi

echo ""
echo "  Task directory: $TASK_DIR"
echo ""

# ── Step 2: Structural validation ───────────────────────────────────────────
echo "[2/3] Structural validation..."
if ! python3.12 "$ROOT_DIR/validator/validate.py" "$TASK_DIR"; then
    echo ""
    echo "FAILED: Task does not pass structural validation." >&2
    echo "  You may need to manually fix the task in: $TASK_DIR" >&2
    exit 1
fi
echo "  PASSED"

# ── Step 3: Functional validation ───────────────────────────────────────────
if [[ "$SKIP_FUNCTIONAL" == "true" ]]; then
    echo "[3/3] Functional validation... SKIPPED (--skip-functional)"
else
    echo "[3/3] Functional validation (Docker)..."
    if ! python3.12 "$ROOT_DIR/validator/docker_validate.py" "$TASK_DIR" --skip-extended; then
        echo ""
        echo "FAILED: Task does not pass functional validation." >&2
        echo "Use --skip-functional to bypass if Docker is unavailable."
        exit 1
    fi
    echo "  PASSED"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "=== Generation Complete ==="
echo "  Task directory: $TASK_DIR"
echo ""
echo "Next steps:"
echo "  1. Run Opus evaluation to check learnability:"
echo "     python3.12 evaluator/evaluate.py $TASK_DIR --model anthropic/claude-opus-4 --trials 5"
echo ""
echo "  2. If Opus passes 2-4 out of 5, promote to examples-opus/:"
echo "     bash scripts/promote-exemplar.sh $TASK_DIR --opus-passes <N> --opus-total 5"
echo ""
