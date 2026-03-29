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
- **Solution idempotency check**: After tests pass with solution, re-runs solution.sh a second time and re-runs tests. This catches fragile solutions that modify state irreversibly (e.g., appending duplicate config lines, creating files that already exist without guards). Idempotency is critical because during evaluation the agent environment may apply partial fixes before finding the full solution.
- **Test determinism check**: Runs tests with solution applied 3 times total. All 3 must pass. This catches flaky tests (race conditions, timing-dependent assertions, random port allocation) that would produce unreliable difficulty scores and waste expensive Opus evaluation runs.
- **Pre-Docker sanity checks**: Validates task.yaml instruction is at least 50 characters, solution.sh is at least 10 bytes, and run-tests.sh is at least 10 bytes. These catch degenerate tasks early before spending time on Docker builds. Runs before any Docker operations for fast feedback.
- **Dockerfile hygiene**: After build, inspects image size via `docker image inspect`. Fails if over 2 GB (would make batch eval infeasible), warns if over 1 GB. Large images slow down container startup and waste disk across hundreds of evaluation runs.
- **Execution time tracking**: Records wall-clock time for each phase (build, test-without-solution, test-with-solution, idempotency, determinism). Warns if test execution with solution exceeds 60 seconds, since this cost multiplies by 5 Opus trials per task. Times are included in the result dict and CLI output.
- **`--skip-extended` flag**: Skips idempotency and determinism checks for quick validation during development. The full 5-phase check runs by default and is recommended before submitting tasks to the evaluation pipeline.

### Core generator (`generator/generate.py`)
- Loads all 6 example tasks as few-shot context for Sonnet.
- Structured JSON output format with fallback extraction for robustness.
- Difficulty calibration in system prompt: targets 3-5 interacting bugs, subtle issues, multi-file understanding — designed so Opus solves ~40-60% of the time.
- Tracks token usage and timing for cost reporting.
- Python 3.9 compatible (`from __future__ import annotations`).

### Tiered evaluation pipeline (`generator/evaluate.py`)
- **Tier 1: Haiku x5** (~$0.05-0.25/task) — cheapest filter. Skip if >= 4/5 pass (definitely too easy for Opus).
- **Tier 2: Sonnet x3** (~$0.30-1.00/task) — closer Opus proxy. Skip if 3/3 pass (probably too easy for Opus).
- **Tier 3: Opus x5** (~$2-5/task) — final calibration. Classify as learnable (1-3/5), too_easy (4-5/5), or too_hard (0/5).
- **Design decision**: Model capability ordering (Haiku < Sonnet < Opus) means if a weaker model finds it easy, a stronger one definitely will. We filter from the "too easy" side cheaply, only spending Opus budget on tasks with real uncertainty.
- **Design decision**: Single-run Haiku was too noisy — a single binary signal can't distinguish "always passes" from "passes 60%". 5 runs gives a distribution. Thresholds are configurable for later tuning once we see empirical correlations.

### End-to-end pipeline (`generator/pipeline.py`)
- Orchestrates: generate → structural validate → functional validate → tiered evaluate.
- Functional validation: builds Docker image, verifies tests fail before solution and pass after.
- Early exit at each stage to avoid wasting compute on broken tasks.

### Topic/prompt bank (`generator/prompts.py`)
- **52 structured topics** with metadata: category, difficulty, language.
- Covers all 6 task categories evenly (8-10 topics each).
- Difficulty distribution: 27% easy, 50% medium, 23% hard — the easy/hard tails matter for calibrating where the learnable boundary sits.
- 11 languages/technologies: Python, Bash, C, C++, Node.js, Go, Java, Make, CMake, Docker, Nginx.
- **Design decision**: Each topic is a `TopicEntry` dataclass rather than a plain string. Structured metadata enables filtering by category/difficulty/language without parsing topic text.
- **Design decision**: `select_topics(diverse=True)` uses round-robin across categories to maximize coverage per batch, preventing the generator from clustering in one domain.
- `get_bank_stats()` for inspecting bank composition.

### Batch generation (`generator/batch.py`)
- Now uses prompt bank (`select_topics()`) instead of hardcoded DEFAULT_TOPICS list.
- Aggregate metrics: generation rate, validation rate, learnable rate, cost, time.
- Per-task results table and JSON report output.
- CLI flags: `--skip-eval`, `--skip-functional`, `--skip-filters`, `--n-tasks N`, `--category`, `--difficulty`, `--language`.
