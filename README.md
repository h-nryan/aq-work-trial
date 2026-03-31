# Task Generation Pipeline for Terminal Bench

A pipeline that generates coding tasks calibrated for **Claude Opus** to solve **1-3 out of 5 attempts** (the "learnable" range). Tasks are self-contained Docker environments verified by pytest.

## Architecture

```
Sonnet (generate) --> Structural Validator --> Docker Functional Validator --> Haiku x5 (pre-filter) --> Sonnet x5 (pre-filter) --> Opus x5 (ground truth)
```

**Three-model design**: Sonnet generates tasks using a solution-first two-phase strategy. Haiku and Sonnet act as cheap pre-filters that catch trivially easy tasks before spending on expensive Opus evaluation. Tasks that survive the filter chain are evaluated by Opus x5 — the ground truth for difficulty calibration.

**Solution-first generation**: Phase 1 writes a complete working program with tests. Phase 2 introduces 3-5 interacting bugs. The working code becomes `solution.sh`. This inverts the naive approach (write broken code + fix simultaneously) and dramatically improves functional validation pass rates.

## Quick Start

### Prerequisites

- Docker Desktop (running)
- Python 3.12+
- `uv` (recommended) or `pip`

### Install

```bash
# Terminal Bench harness
cd terminal_bench && uv pip install -e ".[dev]" && cd ..

# Generator + validator deps
pip install -r generator/requirements.txt
pip install -r validator/requirements.txt
```

Verify: `tb --help`

### Environment

```bash
export OPENROUTER_API_KEY="sk-or-v1-..."
```

### Run a Single Task

```bash
# Generate + validate + evaluate one task
python3.12 generator/pipeline.py "fix a broken Python script" --solution-first

# Generate only (skip Docker validation and evaluation)
python3.12 generator/pipeline.py "fix a broken Python script" --skip-functional --skip-eval
```

### Run a Batch

```bash
# Generate 10 tasks, 3 concurrently
python3.12 generator/batch.py --n-tasks 10 --n-concurrent 3

# Resume an interrupted batch
python3.12 generator/batch.py --resume

# Filter by category/difficulty
python3.12 generator/batch.py --n-tasks 5 --category debugging --difficulty medium
```

### Validate an Existing Task

```bash
# Structural validation only
python3.12 validator/validate.py output/fix-a-broken-python-script

# Full Docker functional validation (idempotency + determinism)
python3.12 validator/docker_validate.py output/fix-a-broken-python-script
```

### Analysis Tools

```bash
# Quality comparison against hand-crafted examples
python3.12 generator/quality.py output/

# Diversity analysis of a batch report
python3.12 generator/diversity.py output/batch-*-report.json
```

### Dashboard

```bash
streamlit run dashboard.py
```

Live monitoring UI showing per-task pipeline progress, stage timelines, Opus eval scores, cost breakdowns, all-time yield trends, and diversity/quality panels (Stretch Goals C and D).

### Tests

```bash
python3.12 -m pytest tests/ -q  # 446 tests, ~11s, no Docker/API calls
```

## Project Structure

```
generator/
  generate.py      # Task generation (single-phase + solution-first two-phase)
  pipeline.py      # Orchestrator: generate -> validate -> evaluate
  evaluate.py      # Tiered evaluation: Haiku -> Sonnet -> Opus
  batch.py         # Batch runner with concurrency, resume, pre-flight checks
  batch_io.py      # Lightweight I/O helpers for batch resume
  config.py        # Models, thresholds, paths, slug generation
  prompts.py       # 52 topics with weighted sampling, category/difficulty/language metadata
  tune_weights.py  # Auto-tune topic weights from historical batch data
  quality.py       # Structural comparison against hand-crafted examples (Stretch Goal D)
  diversity.py     # Category coverage, language distribution, duplicate detection (Stretch Goal C)
  analyze.py       # Bug taxonomy, test quality, code structure, instruction specificity
  metrics.py       # Aggregate statistics across batches for dashboard and reporting (HTML + JSON)
  test_surgical_eval.py  # Standalone test of adjust_difficulty on real tasks
validator/
  validate.py      # Structural validation (file existence, YAML parsing, diff analysis)
  docker_validate.py  # Docker functional validation (5-phase)
dashboard.py       # Streamlit live monitoring dashboard
examples/          # 6 hand-crafted reference tasks (1 learnable, 4 too-hard, 1 too-easy)
examples-opus/     # 2 Opus-generated exemplars for few-shot context
examples-sonnet/   # 20 auto-promoted learnable tasks (content-deduplicated)
tests/             # 446+ tests across 15 modules (~11s, no Docker/API calls)
```

## Task Format

Each task directory contains:

```
task-name/
  task.yaml           # Instruction, difficulty, timeouts, metadata
  Dockerfile          # Container environment (must include tmux + asciinema)
  docker-compose.yaml # Required by tb harness
  run-tests.sh        # Installs uv + pytest, runs tests
  solution.sh         # Deterministic reference solution (heredoc file writes)
  tests/
    test_outputs.py   # Pytest tests: fail unsolved, pass after solution.sh
  [source files]      # The buggy/incomplete code the agent must fix
```

## Pipeline Stages

1. **Generate**: Sonnet creates a task via solution-first strategy (or single-phase fallback)
2. **Structural validation**: Files exist, task.yaml parses, required fields present
3. **Functional validation**: Docker build, tests fail without solution, tests pass with solution, idempotency, determinism
4. **Retry with targeted repair**: On validation failure, regenerates only the broken files (not a full rebuild)
5. **Dedup check**: Hash + Jaccard similarity against existing examples (threshold 0.7). Duplicates retry with diversity feedback.
6. **Tiered evaluation**: Sonnet x5 pre-filter (threshold 3/5) -> Opus x5 ground truth (with early stopping)
7. **Difficulty adjustment**: If too_hard or too_easy, surgical edits + full re-evaluation (up to 2 rounds, with overshoot context)

## Design Decisions

See `CHANGELOG.md` for detailed rationale and data behind every decision.

### Generation

- **Solution-first two-phase generation**: Phase 1 writes a complete working program with tests. Phase 2 introduces 3-4 bugs. This inverts the naive approach (write broken code + fix simultaneously) and dramatically improves functional validation pass rates — the solution is guaranteed correct because it was written first.
- **9 few-shot examples (40K token budget)**: Doubled from 5 to 9 examples covering all 6 categories. Directly improved functional validation: 3 previously-impossible topics (backup rotation, curl wrapper, DNS resolver) all passed after the increase. The extra ~$0.02/generation cost is negligible vs Opus eval savings.
- **Same-topic example exclusion**: Including a same-topic example in the prompt caused Sonnet to copy it verbatim (batch 27: 5/11 tasks were byte-identical). Now excludes matching-topic examples, forcing diverse implementations.
- **Content-based dedup before eval**: After functional validation, hashes source files and checks Jaccard similarity (threshold 0.7) against existing examples. Duplicates trigger regeneration with diversity feedback; if retries exhausted, skips eval to save Opus budget.

### Evaluation

- **100% certainty on learnable classification**: All 5 Opus runs are required — no shortcuts. 0/3 doesn't preclude 1/5 (learnable). Early adjustment after 0/3 was implemented then removed after batch 27 showed it caused premature too_hard classification.
- **Sonnet filter (threshold 3/5)**: If Sonnet solves ≥3/5, skip Opus (too easy). Cross-batch data shows Opus ≥ Sonnet consistently, so Sonnet 3/5 ≈ Opus 4-5/5. Saves ~$5/task. False positive risk (Sonnet 3/5 but Opus only 3/5) accepted — cost savings outweigh rare borderline cases.
- **Skip Sonnet after too_hard adjustment**: A task too hard for Opus can't be too easy for Sonnet. Saves 5 Sonnet runs per too_hard adjustment round.
- **2 adjustment rounds retained**: Data shows 6/17 (35%) of second-round adjustments produced learnable tasks. Both rounds pull their weight.
- **Overshoot context**: When a task oscillates (too_hard → too_easy or vice versa), the adjustment prompt includes the full history so Sonnet can find the middle ground.

### Topic Selection

- **Weighted sampling (not binary exclusions)**: All 52 topics eligible with weights 0.01-1.0 based on historical functional validation and learnable rates. Previously 26 were hard-excluded; retest showed 7/12 now pass functional validation with improved generation.
- **Auto-tuning**: `tune_weights.py` computes optimal weights from all batch JSONL data. Formula: `max(0.05, func_rate * 0.4 + learn_rate * 0.6)`. Batch runner auto-detects weight drift and prompts to apply.

### Reliability

- **Every pipeline exit writes `_status.json`**: Generation exceptions, structural/functional failures, adjustment failures, adjustment exhaustion — all write final status. No more tasks stuck showing "evaluating" after a killed batch.
- **`eval_phase` state machine**: Pipeline writes the current phase (`sonnet`, `opus`, `adjusting`) to `_status.json` at each tier transition. Dashboard reads this single authoritative field instead of inferring from stale data.
- **Docker build retries (2x)**, **tb run retries (1x)**: Transient infrastructure failures don't kill tasks.
- **Actual API token tracking**: Harness accumulates `response.usage` from each litellm call instead of recounting from message history. Fixes ~50% of trials reporting null tokens (timed-out agents had no messages).

### Results

- **20 unique learnable tasks** in `examples-sonnet/` (content-deduplicated)
- **Best batch: 8/12 learnable** (batch 27) — 67% yield
- **100% functional validation** achieved (batch 27) — first ever with improved examples
- **446 tests** across 15 modules (~11s, no Docker/API calls)
