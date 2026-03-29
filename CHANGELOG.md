# Changelog

## [Unreleased]

### Config: model and pipeline constants (`generator/config.py`)
- **Generator model**: Switched from Haiku to **Sonnet** (`claude-sonnet-4.5`) for higher-quality task generation.
- **Evaluation model**: Added **Opus** (`claude-opus-4`) as the target agent model. Tasks are calibrated so Opus passes 1-3 out of 5 runs.
- **Pre-filter model**: Kept **Haiku** (`claude-3.5-haiku`) as a cheap pre-filter to screen out trivially easy tasks before expensive Opus evaluation.
- Added pipeline constants: learnable range (1-3/5), eval trials (5), task categories for diversity.
- **Design decision**: Three-model architecture (Sonnet generates, Haiku filters, Opus evaluates) balances quality and cost. Haiku pre-filter saves ~$2-10 per batch by catching easy tasks before running 5 Opus trials.

### Docker-based functional validator (`validator/docker_validate.py`)
- **New module**: Standalone Docker-based validator that verifies task correctness end-to-end.
- Three-phase validation: (1) build Docker image, (2) run tests without solution — must fail, (3) run solution.sh then tests — must pass.
- **Design decision**: Uses `subprocess` + Docker CLI rather than the `docker` Python SDK for simplicity and fewer failure modes. The SDK is listed as a dependency for downstream consumers but the validator itself shells out to `docker build` and `docker run`.
- **Design decision**: Tests and solution.sh are bind-mounted read-only into the container rather than baked into the image. This lets us test the same image in both solved/unsolved states without rebuilding.
- **Design decision**: Automatic image cleanup after validation to avoid disk bloat. `--no-cleanup` flag available for debugging.
- Supports `--json` output for programmatic consumption by the pipeline.
- Configurable timeouts for both build (default 300s) and test execution (default 120s).
- Shell wrapper at `scripts/docker-validate.sh` for CLI usage.

### Core generator (`generator/generate.py`)
- Loads all 6 example tasks as few-shot context for Sonnet.
- Structured JSON output format with fallback extraction for robustness.
- Difficulty calibration in system prompt: targets 3-5 interacting bugs, subtle issues, multi-file understanding — designed so Opus solves ~40-60% of the time.
- Tracks token usage and timing for cost reporting.
- Python 3.9 compatible (`from __future__ import annotations`).

### Evaluation pipeline (`generator/evaluate.py`)
- Wraps the `tb` CLI to run terminus-1 agent against generated tasks.
- Two-stage evaluation: Haiku pre-filter (1 run, cheap) → Opus full evaluation (5 runs).
- Classifies tasks: learnable (1-3/5), too_easy (4-5/5), too_hard (0/5).
- Parses trial results from run output directories.

### End-to-end pipeline (`generator/pipeline.py`)
- Orchestrates: generate → structural validate → functional validate → evaluate.
- Functional validation: builds Docker image, verifies tests fail before solution and pass after.
- Early exit at each stage to avoid wasting compute on broken tasks.

### Batch generation (`generator/batch.py`)
- 15 diverse topic templates spanning debugging, data-processing, build systems, devops.
- Aggregate metrics: generation rate, validation rate, learnable rate, cost, time.
- Per-task results table and JSON report output.
- CLI flags: `--skip-eval`, `--skip-functional`, `--n-tasks N`.
