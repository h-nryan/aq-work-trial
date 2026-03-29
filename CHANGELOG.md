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
- **Integrated with `docker_validate.py`**: Pipeline's functional validation now delegates to the standalone Docker validator instead of maintaining its own 100-line inline implementation. Gets sanity checks, image size limits, and timing data for free. Uses `--skip-extended` for speed in the pipeline; full idempotency/determinism checks available via `scripts/docker-validate.sh`.
- **Design decision**: Single source of truth for Docker validation logic. The pipeline was duplicating bind-mount logic, WORKDIR detection, and build/test commands. Centralizing in `docker_validate.py` means bug fixes and enhancements (like the sanity checks) apply everywhere.
- Early exit at each stage to avoid wasting compute on broken tasks.

### Diversity analysis (`generator/diversity.py`) — Stretch Goal C
- Analyzes batch reports for category coverage, language distribution, difficulty spread, instruction complexity, and topic uniqueness.
- **Coverage score**: Fraction of TASK_CATEGORIES present in the batch. Measures breadth.
- **Evenness score**: Normalized Shannon entropy of category distribution. 1.0 = perfectly uniform, low values indicate clustering in a few categories.
- **Near-duplicate detection**: Jaccard similarity on word sets between topic strings. Configurable threshold (default 0.7). Catches the generator producing semantically identical tasks with slightly different phrasing.
- **Design decision**: Language is inferred from topic strings rather than requiring it in task.yaml. The generator doesn't always set a language field, so pattern matching on the topic ("Python", "Bash", "C++") is more reliable than depending on generated metadata.
- CLI: `python generator/diversity.py <batch-report.json>` or pass a directory to auto-find the latest report. Saves a companion `-diversity.json` file.

### Topic/prompt bank (`generator/prompts.py`)
- **52 structured topics** with metadata: category, difficulty, language.
- Covers all 6 task categories evenly (8-10 topics each).
- Difficulty distribution: 27% easy, 50% medium, 23% hard — the easy/hard tails matter for calibrating where the learnable boundary sits.
- 11 languages/technologies: Python, Bash, C, C++, Node.js, Go, Java, Make, CMake, Docker, Nginx.
- **Design decision**: Each topic is a `TopicEntry` dataclass rather than a plain string. Structured metadata enables filtering by category/difficulty/language without parsing topic text.
- **Design decision**: `select_topics(diverse=True)` uses round-robin across categories to maximize coverage per batch, preventing the generator from clustering in one domain.
- `get_bank_stats()` for inspecting bank composition.

### Generation prompt (`generator/generate.py`)
- **Reverted per-difficulty prompt hints** — all tasks now use a single fixed system prompt targeting the 1-3/5 learnable range. Per-difficulty hints (easy/medium/hard) were counterproductive because they worked against the pipeline's goal: every task should land in the learnable band regardless of topic. The tiered evaluation (Haiku→Sonnet→Opus) handles difficulty calibration, not the generation prompt.
- **Design decision**: Prompt bank difficulty metadata is retained for topic selection and diversity reporting, but is NOT passed to the generator. The generator always targets "3-5 interacting bugs, ~40-60% solve rate."

### Batch runner + metrics (`generator/batch.py`)
- Now uses prompt bank (`select_topics()`) instead of hardcoded DEFAULT_TOPICS list.
- **Incremental saves**: Each task result is appended to a JSONL file as it completes. If the batch crashes mid-run (network error, Docker timeout, OOM), completed results are preserved. The incremental file is cleaned up after the final JSON report is written.
- **Design decision**: JSONL (one JSON object per line) for incremental saves rather than repeatedly rewriting a full JSON array. Append-only is crash-safe — a partial write only loses the last line, not the whole file.
- **Cost estimation**: Computes approximate USD costs from token counts using per-model rates (Sonnet input/output, Haiku input/output, Opus input/output). Reports generation cost, evaluation cost, total, and cost-per-learnable-task. Rates are hardcoded from OpenRouter pricing — not perfectly accurate but good enough for budget planning.
- **Design decision**: Cost estimation is best-effort from token counts rather than from OpenRouter billing APIs. Token counts are already in the pipeline results, so no additional API calls needed. Rates may drift over time but the relative cost structure (Haiku << Sonnet << Opus) is stable.
- **Pipeline funnel report**: Shows drop-off at each stage with percentages (attempted → generated → structural pass → functional pass → evaluated → learnable). Makes bottlenecks immediately visible — e.g., if 80% fail functional validation, focus on improving the generator's Dockerfile/solution quality rather than tuning evaluation.
- **Yield metric**: learnable/attempted ratio — the single number that matters for pipeline efficiency.
- **CLI overhaul**: Replaced manual `sys.argv` parsing with `argparse`. Added `--output-dir` (was in the function signature but not wired to CLI), `--seed` (for reproducible prompt bank selection). All flags have help descriptions.

### Retry with feedback (`generator/generate.py`, `generator/pipeline.py`)
- When structural or functional validation fails, the pipeline feeds the specific errors back to Sonnet and asks it to fix the task (up to `max_retries` attempts, default 2).
- **Targeted repair** (improved): Instead of regenerating all files on retry, the system now analyzes the feedback to repair only the broken files:
  - "Tests FAILED with solution" → only regenerate `solution.sh` (~10k tokens vs 50k for full rebuild)
  - "Tests PASSED without solution" → only regenerate source files (keep tests/solution intact)
  - Structural issues → full rebuild (rare)
- **Design decision**: The original full-rebuild approach caused "whack-a-mole" — fixing solution.sh would introduce new bugs in other files. Targeted repair preserves working files and only touches what's broken. Cut retry cost by ~80% and improved fix success rate.
- **Design decision**: Lower temperature (0.3) for targeted repairs vs. 0.7 for initial generation. Corrections need precision.
- Feedback includes test stdout/stderr excerpts so the LLM can see exactly which tests failed and why.
- Retry results tracked in `stages` dict (as `retry_1`, `retry_2`) for cost accounting.

### JSON parse robustness (`generator/generate.py`)
- Fixed markdown fence stripping: the regex used non-greedy `.*?` matching, which broke when JSON content contained triple backticks (e.g. code blocks in task.yaml instructions). Replaced with line-based fence stripping.
- Strengthened "no fences" instruction in the system prompt, but the robust parser is the real fix since models don't always comply.

### Difficulty adjustment loop (`generator/generate.py`, `generator/pipeline.py`) — Stretch Goal B
- After evaluation classifies a task as `too_hard` (0/5 Opus passes) or `too_easy` (4-5/5), the pipeline adjusts difficulty and re-evaluates (up to 2 rounds).
- **too_hard**: Instructs the LLM to remove 1-2 bugs, make remaining bugs more discoverable, reduce file interactions — while keeping the core challenge.
- **too_easy**: Instructs the LLM to add subtle interacting bugs, misleading symptoms, edge cases — without making it impossible.
- **Design decision**: Full file replacement on difficulty adjustment (not targeted repair). Unlike solution fixes where only solution.sh is broken, difficulty changes affect the relationship between source files, tests, and solution — all three need to stay consistent.
- **Design decision**: Re-validates functionally after each adjustment before re-evaluating. An adjustment that breaks tests wastes expensive Opus eval budget. Validation is cheap (one Docker run) vs. evaluation (5+ agent runs).
- Motivated by exemplar generation results: 2/2 tasks that passed functional validation were classified as too_hard (Opus 0/5). The generator consistently overshoots difficulty when targeting "3-5 interacting bugs."

### Code quality cleanup
- Added `from __future__ import annotations` to all modules for Python 3.9 compatibility.
- Removed unused imports across 6 files (Path, Optional, tempfile, unused config constants).
- Narrowed broad `except Exception` to specific exception types for debuggability.
- Consistent use of `X | None` syntax over `Optional[X]` across all modules.

### Terminal Bench harness fixes
- **Critical**: The `tb` harness was completely non-functional — all previous evaluation results (0/5 across all tasks) were caused by infrastructure failures, not task difficulty. Every fix below was necessary to get the first successful agent run.
- **Missing prompt templates**: Created `terminus.txt` (agent system prompt), `timeout.txt` (command timeout notification), and `formatted-response.txt` (JSON schema fallback for models without native `response_format`). Reconstructed from source code context — the templates reference `{instruction}`, `{response_schema}`, `{terminal_state}`, `{history}` placeholders used in `terminus_1.py`.
- **Missing `add_anthropic_caching()`**: Function was called in `lite_llm.py` but never defined. Added implementation that injects `cache_control` headers on system/user messages for Anthropic models.
- **Missing `AsciinemaHandler`**: Class was used in `harness.py` but never defined. Added implementation that merges agent markers into asciinema v2 recordings.
- **Missing `get-asciinema-timestamp.sh`**: Script expected by `tmux_session.py` to extract timestamps from recordings. Created with Python-based JSON parser.
- **docker-compose.yaml for all examples**: The harness uses `docker compose`, not raw `docker build`. Added standardized compose files to all 6 examples with env-var-driven container/image names.
- **tmux + asciinema in Dockerfiles**: The harness requires both tools inside the container for terminal session management and recording. Added to all 6 example Dockerfiles.
- **JSON extraction fallback**: Added brace-extraction fallback to `terminus_1.py` for models that return JSON embedded in free text (common via OpenRouter routing).
- **OpenRouter model routing**: Models must use `openrouter/` prefix (e.g., `openrouter/anthropic/claude-3.5-haiku`) for litellm to route through OpenRouter instead of calling Anthropic directly.

### Bug fixes
- **Slug generation**: Topic strings with commas (e.g., "nested YAML, environment overrides") produced directory names containing commas, which are invalid Docker tags. Docker build failed with "invalid reference format". Fixed by stripping all non-alphanumeric/hyphen characters from slugs. Discovered during Opus exemplar generation — wasted 2 retry attempts before identifying the root cause was in our tooling, not the generated task.
- **API retry**: OpenRouter occasionally returns malformed JSON responses (network interruption, server error). Added `_api_call_with_retry()` with exponential backoff (3 attempts, 5s/10s/20s). Does not retry on auth errors (4xx).

### Test suites (`tests/`)
- **97 tests** covering prompts, structural validator, Docker validator sanity checks, generator prompt construction, batch metrics/cost estimation, and diversity analysis.
- All tests are fast (~0.6s) and deterministic — no Docker or API calls needed.
- **Design decision**: Tests use `tmp_path` fixtures with synthetic task directories rather than the real examples, so they stay fast and don't depend on example task state.
- Batch tests verify funnel counts, cost math, token aggregation, and edge cases (zero denominators, error statuses, generation failures).
