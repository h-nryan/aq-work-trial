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

### Tests

```bash
python3.12 -m pytest tests/ -q  # 175 tests, ~2s, no Docker/API calls
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
  prompts.py       # 52 structured topics with category/difficulty/language
  quality.py       # Structural comparison against hand-crafted examples
  diversity.py     # Category coverage, language distribution, duplicate detection
validator/
  validate.py      # Structural validation (file existence, YAML parsing)
  docker_validate.py  # Docker functional validation (5-phase)
examples/          # 6 hand-crafted reference tasks
tests/             # 175 tests across 10 modules
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
5. **Tiered evaluation**: Haiku x5 pre-filter -> Sonnet x5 pre-filter -> Opus x5 ground truth
6. **Difficulty adjustment**: If too_hard (0/5) or too_easy (4-5/5), adjusts and re-evaluates (up to 2 rounds)

## Design Decisions

See `CHANGELOG.md` for detailed rationale on every design decision. Key choices:

- **Opus as target model** (not Haiku): Tasks calibrated for Opus are more valuable — they test the frontier of agent capability. Haiku and Sonnet serve as cheap pre-filters, not evaluation targets.
- **Solution-first generation**: Writing correct code then introducing bugs is two easy tasks. Writing broken code and its fix simultaneously is one hard task. The former has much higher validation pass rates.
- **Tiered evaluation**: Model capability ordering (Haiku < Sonnet < Opus) means if a weaker model finds it easy, Opus definitely will. Filter from the "too easy" side cheaply.
- **Infrastructure error detection**: Docker failures skip regeneration retries — re-generating code won't fix a broken Docker build.
- **Crash-safe batch resume**: JSONL incremental writes + meta file preserving the original topic list. Interrupted batches pick up where they left off.
