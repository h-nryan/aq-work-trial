#!/usr/bin/env bash
# Promote a task to examples-opus/ after confirming it's in the learnable range.
#
# Usage:
#   bash scripts/promote-exemplar.sh <task_dir> [--opus-passes N] [--opus-total N] [--skip-functional]
#
# Examples:
#   bash scripts/promote-exemplar.sh examples/csv-to-json-cli-fix --opus-passes 2 --opus-total 5
#   bash scripts/promote-exemplar.sh output/fix-a-broken-python-log-rotation-script-with-05bfc9
#
# What it does:
#   1. Validates the task structurally
#   2. Optionally validates functionally in Docker (skip with --skip-functional)
#   3. Copies to examples-opus/<task-name>/
#   4. Stages and commits
#
# The --opus-passes and --opus-total flags are for the commit message only.
# The script does NOT run Opus evaluation — that's expensive and should be done
# separately. This script is for after you already know the result.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
DEST_DIR="$ROOT_DIR/examples-opus"

# ── Parse args ────────────────────────────────────────────────────────────────
TASK_DIR=""
OPUS_PASSES=""
OPUS_TOTAL=""
SKIP_FUNCTIONAL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --opus-passes) OPUS_PASSES="$2"; shift 2 ;;
        --opus-total)  OPUS_TOTAL="$2";  shift 2 ;;
        --skip-functional) SKIP_FUNCTIONAL=true; shift ;;
        -h|--help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            if [[ -z "$TASK_DIR" ]]; then
                TASK_DIR="$1"
            else
                echo "Error: unexpected argument '$1'" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [[ -z "$TASK_DIR" ]]; then
    echo "Usage: bash scripts/promote-exemplar.sh <task_dir> [--opus-passes N] [--opus-total N] [--skip-functional]"
    exit 1
fi

# Resolve to absolute path
TASK_DIR_ORIG="$TASK_DIR"
TASK_DIR="$(cd "$TASK_DIR" 2>/dev/null && pwd)" || {
    echo "Error: task directory does not exist: $TASK_DIR_ORIG" >&2
    exit 1
}

TASK_NAME="$(basename "$TASK_DIR")"
TARGET="$DEST_DIR/$TASK_NAME"

echo "=== Promote Exemplar ==="
echo "  Source: $TASK_DIR"
echo "  Target: $TARGET"
if [[ -n "$OPUS_PASSES" && -n "$OPUS_TOTAL" ]]; then
    echo "  Opus:   $OPUS_PASSES/$OPUS_TOTAL"
fi
echo ""

# ── Check for duplicates ─────────────────────────────────────────────────────
if [[ -d "$TARGET" ]]; then
    echo "Error: $TARGET already exists. Remove it first if you want to replace." >&2
    exit 1
fi

# ── Structural validation ────────────────────────────────────────────────────
echo "[1/3] Structural validation..."
if ! python3.12 "$ROOT_DIR/validator/validate.py" "$TASK_DIR"; then
    echo ""
    echo "FAILED: Task does not pass structural validation." >&2
    exit 1
fi
echo "  PASSED"

# ── Functional validation ────────────────────────────────────────────────────
if [[ "$SKIP_FUNCTIONAL" == "true" ]]; then
    echo "[2/3] Functional validation... SKIPPED (--skip-functional)"
else
    echo "[2/3] Functional validation (Docker)..."
    if ! python3.12 "$ROOT_DIR/validator/docker_validate.py" "$TASK_DIR" --skip-extended; then
        echo ""
        echo "FAILED: Task does not pass functional validation." >&2
        echo "Use --skip-functional to bypass (e.g., if Docker images are still cached from eval)."
        exit 1
    fi
    echo "  PASSED"
fi

# ── Copy to examples-opus/ ───────────────────────────────────────────────────
echo "[3/3] Copying to examples-opus/$TASK_NAME/..."
mkdir -p "$DEST_DIR"
cp -r "$TASK_DIR" "$TARGET"

# Remove any internal pipeline artifacts
rm -f "$TARGET"/_raw_response.txt "$TARGET"/_phase1_raw.txt "$TARGET"/_phase2_raw.txt \
      "$TARGET"/_retry_raw_response.txt "$TARGET"/_adjust_raw_response.txt
echo "  Done"

# ── Git commit ───────────────────────────────────────────────────────────────
echo ""
echo "Staging and committing..."

cd "$ROOT_DIR"
git add "examples-opus/$TASK_NAME/"

# Build commit message
COMMIT_MSG="Promote $TASK_NAME to examples-opus"
if [[ -n "$OPUS_PASSES" && -n "$OPUS_TOTAL" ]]; then
    COMMIT_MSG="$COMMIT_MSG (Opus $OPUS_PASSES/$OPUS_TOTAL — learnable)"
fi

git commit -m "$COMMIT_MSG"

echo ""
echo "=== Done ==="
echo "  Promoted: examples-opus/$TASK_NAME/"
echo "  Commit:   $(git log --oneline -1)"
echo ""
echo "The generator will now include this task as a positive few-shot example."
