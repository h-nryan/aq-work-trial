# Changelog

## Overview

A pipeline that generates Terminal Bench coding tasks calibrated for Claude Opus to solve 1-3 out of 5 attempts (the "learnable" range).

**Architecture**: Three-model design — **Sonnet generates** tasks, **Haiku + Sonnet pre-filter** cheaply catches too-easy tasks, **Opus evaluates** ground truth difficulty. A solution-first two-phase generation strategy ensures functional correctness (write working code first, then introduce bugs). The pipeline validates structurally and functionally in Docker before spending on expensive Opus evaluation.

**Stretch goals implemented**: A (cost-efficient evaluation), B (difficulty tuning), C (diversity analysis), D (human-likeness comparison).

**Current state**: 175 tests across 10 test modules, ~3,400 lines of generator code across 9 modules. Evaluating hand-crafted examples against Opus to calibrate few-shot prompts before running production batches.

---

## [Unreleased]

### Generation

**Solution-first strategy** (`generate.py`) — Phase 1 writes a complete working program with passing tests; Phase 2 introduces 3-5 interacting bugs into the source files. The working code becomes `solution.sh`. This inverts the original single-phase approach which asked the LLM to write broken code AND its fix simultaneously — that had ~20% functional validation pass rate. Solution-first separates two easy tasks (write correct code; introduce bugs) instead of one hard task.
- Phase 1 uses temperature 0.5 (correctness); Phase 2 uses 0.7 (creative bugs)
- Phase 2 requires majority of tests to fail, not all — some passing tests give the agent useful debugging signal
- Higher retry budget (`MAX_SOLUTION_FIRST_RETRIES=6` vs default 2) since each targeted repair gets closer to passing
- Source-only repair now includes test function code so the LLM can see what each test checks and introduce bugs that break those specific checks (previously guessed blindly)
- **Phase 2 self-verification**: Prompt now requires the LLM to trace each test function against its buggy code and output a per-test verification ("test_X: WILL FAIL because..."). Forces chain-of-thought about test-to-bug mapping. Motivated by first Sonnet batch where 0/3 tasks passed functional validation because Phase 2 bugs didn't break tests.
- **Bug annotations in exemplars**: `_bugs.md` files in Opus exemplars explicitly describe each bug (what's wrong, why it's realistic, which tests it breaks). Loaded first in the few-shot context with a "BUG ANNOTATIONS" header so Sonnet learns the test-to-bug mapping pattern, not just what buggy code looks like.
- Usage: `python3.12 pipeline.py "topic" --solution-first`

**Few-shot example curation** (`generate.py`) — Three-way classification of reference examples:
- **Positive** (learnable): shown as "GOOD EXAMPLES — target this difficulty"
- **Negative** (too easy): shown as "TOO-EASY EXAMPLES — avoid this difficulty" (currently: `config-manifest-validator`)
- **Too hard**: excluded entirely — showing impossible tasks miscalibrates difficulty upward and wastes tokens
- `examples-opus/` directory for Opus-generated exemplars that Sonnet can replicate cheaply at scale
- *Design decision*: Negative examples are more informative than exclusion. Showing what "too easy" looks like helps calibrate the other boundary.

**Prompt calibration** (`generate.py`) — Single fixed system prompt targeting 3-5 interacting bugs, ~40-60% Opus solve rate. Per-difficulty hints (easy/medium/hard) were reverted — they worked against the pipeline's goal since every task should land in the learnable band regardless of topic.

**Targeted repair** (`generate.py`, `pipeline.py`) — On validation failure, analyzes feedback to repair only broken files:
- "Tests FAILED with solution" → regenerate only `solution.sh`
- "Tests PASSED without solution" → regenerate only source files
- Structural issues → full rebuild (rare)
- *Design decision*: Full-rebuild retries caused "whack-a-mole" — fixing one file broke others. Targeted repair cut retry cost ~80%.

**JSON parse robustness** (`generate.py`) — Handles markdown fences, embedded JSON, and triple-backtick content within JSON values.

### Validation

**Docker-based functional validator** (`validator/docker_validate.py`) — End-to-end correctness verification:
1. Pre-Docker sanity checks (instruction length, file sizes)
2. Docker image build + size check (fail > 2 GB, warn > 1 GB)
3. Tests FAIL without solution
4. Tests PASS with solution
5. Solution idempotency (re-run solution, re-run tests — catches irreversible state changes)
6. Test determinism (3x pass — catches flaky tests that waste Opus budget)
- `--skip-extended` for fast dev iteration; full 5-phase for production
- Execution time tracking per phase; warns if tests > 60s (multiplied by 5 Opus trials)
- *Design decision*: Bind-mount tests/solution read-only instead of baking into image — test same image in both states without rebuilding.

**Infrastructure error detection** (`pipeline.py`) — Distinguishes Docker build failures / timeouts (infrastructure) from content errors (tests pass without solution, solution doesn't fix). Infrastructure errors skip regeneration retries — re-generating code won't fix a broken Docker build.

**Harness compatibility** (`generate.py`) — Auto-injects `docker-compose.yaml` and requires `tmux asciinema` in every Dockerfile. Root cause of all early 0/5 results was infrastructure, not difficulty.

### Evaluation — Stretch Goal A

**Tiered evaluation** (`evaluate.py`) — Progressive filtering through cheaper models:
- **Tier 1: Haiku ×5** (~$0.05-0.25) — skip if ≥ 4/5 pass (definitely too easy for Opus)
- **Tier 2: Sonnet ×5** (~$0.30-1.00) — skip if ≥ 4/5 pass (very likely too easy for Opus)
- **Tier 3: Opus ×5** (~$2-5.00) — final classification: learnable (1-3/5), too_easy (4-5/5), too_hard (0/5)
- *Design decision*: Model capability ordering (Haiku < Sonnet < Opus) means if a weaker model finds it easy, a stronger one definitely will. Filter from the "too easy" side cheaply.

**Opus early stopping with hybrid parallelism** — First 3 Opus runs execute in parallel for speed. If classification is determined (e.g., 0/3 → too_hard, 3/3 → too_easy), stop. Otherwise run attempts 4-5 sequentially with early-stop checks. Saves ~$0.40-1.00 per skipped run; most tasks classify after 3 parallel runs.

**Haiku filter disabled by default** — Haiku scored 0/5 on every task tested, including the trivially easy config-manifest-validator (Opus 5/5, Sonnet 3/3). The terminus-1 agent with Haiku via OpenRouter is too weak to solve anything through the harness, making the tier pure overhead (5 API calls + 5 Docker runs returning 0/5). Now opt-in via `--include-haiku`. The evaluation pipeline goes Sonnet → Opus by default.

**Early stopping on all tiers** — The hybrid parallel+sequential early-stop strategy applies to Sonnet filter and Opus eval tiers (and Haiku if enabled). For filters, the decision is simpler (skip vs proceed): after 3 parallel runs, if passes + remaining < threshold → proceed immediately.

**`--solution-first` in batch CLI** — Batch runs now support `--solution-first` flag, passing it through to each `run_pipeline` call. Kept as a flag (not default) to allow A/B comparison of generation strategies on learnable yield.

**Sonnet filter tuning** — Increased from 3 runs / threshold 3 to 5 runs / threshold 4. A 70% true solve rate has 34% chance of 3/3 but only 17% chance of 4+/5, reducing false positives.

### Difficulty Tuning — Stretch Goal B

**Difficulty adjustment loop** (`generate.py`, `pipeline.py`) — After evaluation, if task is too_hard or too_easy, adjusts and re-evaluates (up to 2 rounds):
- **too_hard**: Remove 1-2 bugs, make remaining more discoverable
- **too_easy**: Add subtle interacting bugs, misleading symptoms
- Re-validates functionally after each adjustment before re-evaluating (validation is one Docker run vs. 5+ Opus agent runs)
- *Design decision*: Full file replacement, not targeted repair — difficulty changes affect the relationship between source, tests, and solution.

### Diversity Analysis — Stretch Goal C

**Diversity module** (`diversity.py`) — Analyzes batch reports for:
- Category coverage (fraction of 6 categories present) and evenness (Shannon entropy)
- Language distribution
- Near-duplicate detection (Jaccard similarity on topic word sets, threshold 0.7)
- CLI: `python3.12 generator/diversity.py <batch-report.json>`

**Topic/prompt bank** (`prompts.py`) — 52 structured topics with category, difficulty, language metadata. Round-robin selection (`select_topics(diverse=True)`) maximizes coverage per batch.

### Human-Likeness Comparison — Stretch Goal D

**Quality comparison** (`quality.py`) — Compares generated tasks against hand-crafted examples using structural metrics (instruction length, test count, file count, Dockerfile checks). Outlier detection flags tasks outside example range by > 50%.
- CLI: `python3.12 generator/quality.py <task_dir_or_output_dir>`

### Batch Infrastructure

**Batch runner** (`batch.py`) — Orchestrates generation, validation, and evaluation for multiple tasks:
- `--n-concurrent N` for parallel task execution (thread-safe incremental JSONL writes)
- `--resume [BATCH_ID_OR_PATH]` to pick up interrupted batches (meta file preserves original topic list)
- Pre-flight checks: API key, Docker daemon, `tb` CLI, output dir writable, disk space
- Pipeline funnel report with yield metric (learnable/attempted)
- Cost estimation from token counts (Sonnet, Haiku, Opus rates)
- Error categorization by failed stage (generation, structural, functional, evaluation)
- `--seed` for reproducible prompt bank selection

**Crash safety** — Incremental JSONL appends (not full-array rewrites) preserve completed results. `threading.Lock` prevents byte-interleaving under concurrent writes. Worker count capped to `min(n_concurrent, remaining)`.

### Harness Fixes

The `tb` harness was non-functional out of the box — all early evaluation results were infrastructure failures. Fixes required to get the first successful agent run:
- Created missing prompt templates (`terminus.txt`, `timeout.txt`, `formatted-response.txt`)
- Implemented missing `add_anthropic_caching()`, `AsciinemaHandler`, `get-asciinema-timestamp.sh`
- Added `docker-compose.yaml` and `tmux asciinema` to all 6 example Dockerfiles
- JSON extraction fallback in `terminus_1.py` for OpenRouter responses
- Auto-prefix `openrouter/` on model names for litellm routing

### Bug Fixes

- **Slug generation**: Commas in topics produced invalid Docker tags. Fixed with character stripping + word-boundary truncation + SHA-256 hash suffix for collision safety.
- **config-manifest-validator example**: Instruction said "manifest.txt" but tests checked "hello.txt" — appeared impossibly hard when it was actually a bug in the example.
- **Timeout as valid failure**: Docker validator now accepts test timeout without solution as a valid failure mode (buggy code may hang due to infinite loops, deadlocks, or memory corruption). Previously blocked promotion of tasks like the C linked list exemplar where buggy code hangs but solution runs cleanly.
- **Evaluation path resolution**: `evaluate.py` resolved paths relative to cwd instead of repo root.
- **Stale resource cleanup**: `cleanup_stale_resources()` runs before each `_run_tb` call, killing both Docker containers and orphaned processes older than 20 minutes. The `tb` harness has a 6-minute agent timeout but doesn't always clean up containers or its own process tree when it fires. Three layers of cleanup: (1) stale Docker containers, (2) stale `tb run` processes stuck on dead containers, (3) orphaned parent evaluator processes (`python -c "from evaluate import..."`) waiting on dead children.
- **Evaluation run cleanup**: `_run_tb` now removes run artifact directories after parsing results. All pass/fail data is captured in the return dict; the raw trial files under `runs/` were pure waste.
- **API retry**: Exponential backoff (3 attempts, 5/10/20s) for transient OpenRouter failures. No retry on auth errors.

### Code Quality

- `X | None` syntax throughout (not `Optional[X]`)
- Narrowed `except Exception` to specific types
- `_slugify` in dependency-free `config.py`; `batch_io.py` for resume helpers (no openai/pydantic chain)
- End-to-end integration test (`test_pipeline_e2e.py`) — 15 tests exercising the full `run_pipeline` flow (generate → structural → functional → evaluate) with mocked API/Docker. Covers happy path, solution-first strategy, generation failure, structural/functional retry, infrastructure error detection, difficulty adjustment loop, and regeneration failure.
- Generator unit tests (`test_generate.py`) — 26 new tests for `_parse_response` (JSON parsing edge cases, markdown fences, embedded backticks), `_load_examples` (three-way classification, opus examples), and `_slugify` (special chars, truncation, hash suffix).
- 216 tests across 12 modules (~4s, no Docker/API calls). Tests use `tmp_path` fixtures with synthetic tasks.

### Scripts

- **`generate-exemplar.sh`** — Generates a high-quality task using Opus (`--model anthropic/claude-opus-4 --solution-first`), validates structurally + functionally, and prints next-step commands for eval and promotion. Use this to build up `examples-opus/` before running Sonnet batches.
- **`promote-exemplar.sh`** — Copies a confirmed-learnable task to `examples-opus/`, strips pipeline artifacts, and commits. Takes `--opus-passes` and `--opus-total` for the commit message.
