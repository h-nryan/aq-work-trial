# Changelog

## Overview

A pipeline that generates Terminal Bench coding tasks calibrated for Claude Opus to solve 1-3 out of 5 attempts (the "learnable" range).

**Architecture**: Three-model design — **Sonnet generates** tasks, **Haiku + Sonnet pre-filter** cheaply catches too-easy tasks, **Opus evaluates** ground truth difficulty. A solution-first two-phase generation strategy ensures functional correctness (write working code first, then introduce bugs). The pipeline validates structurally and functionally in Docker before spending on expensive Opus evaluation.

**Stretch goals implemented**: A (cost-efficient evaluation), B (difficulty tuning), C (diversity analysis), D (human-likeness comparison).

**Current state**: 23 learnable tasks in examples-sonnet/, 2 Opus-generated exemplars, 1 hand-crafted exemplar (26 total). Batch 22 achieved 75% learnable rate (9/12) — best batch yet — with 5 of those via difficulty adjustment (first confirmed adjustment→learnable conversions). Pipeline validates structurally and functionally in Docker with solution-first generation, then evaluates with tiered Opus eval with early stopping.

---

## [Unreleased]

### Dashboard: Cost Summary, Funnel, Trends, and Diversity

**Batch cost summary** (`dashboard.py`) — Three cost cards below the existing count cards: Generation cost (Sonnet API tokens from all generate/retry/adjustment stages), Opus eval cost (from agent token counts in trial data), and Cost per learnable task. Pricing constants: Sonnet 4.5 at $3/$15 per MTok in/out; Opus 4 at $15/$75 per MTok in/out.

**Pipeline funnel visualization** (`dashboard.py`) — Removed. The funnel was added and subsequently removed as the visual did not render well.

**Per-task cost in detail view** (`dashboard.py`) — Cost breakdown added to every task expander: generation tokens + cost, Opus eval tokens + cost, and total.

**All-batch trend charts** (`dashboard.py`) — Inside the "All-time metrics" expander: learnable yield % per batch (bar chart) and cost per learnable per batch (bar chart), computed from token data in the incremental JSONL files.

**Category diversity chart** (`dashboard.py`) — Inside "All-time metrics": bar chart of `_meta.yaml` category distribution across tasks in the current batch, showing coverage across the 6 task categories.

### Example Budget Increase

**Doubled example token budget from 20K to 40K** (`generate.py`) — Increases few-shot examples from 5 to 9 (covering all 6 categories). More examples give Sonnet better calibration for bug difficulty and solution alignment. Motivated by batch 24 functional failures: curl wrapper (bugs too weak — tests pass without solution) and DNS resolver (Phase 1/2 mismatch — solution doesn't fix bugs). Both failure modes suggest Sonnet needs more reference material for correct bug/test/solution structure. Cost impact negligible (~$0.02/generation) vs Opus eval savings.

**Validated with retest on 3 previously-failing topics** — Ran generation-only (no eval) on the 3 topics that failed functional validation in batch 24 with 5 examples: backup rotation (0% pass rate across batches 22-24), curl wrapper (tests pass without solution), DNS resolver (solution doesn't fix bugs). With 9 examples, all 3 passed functional validation (backup rotation on attempt 3, curl wrapper on attempt 2, DNS resolver on attempt 3). The backup rotation topic had never passed functional validation in any prior batch — this is a direct improvement from more examples giving Sonnet better structural patterns for test/solution alignment.

### Use per-phase httpx timeout on generation API calls

**Replace blunt total timeout with `httpx.Timeout`** (`generate.py`) — The previous `timeout=120` was a total-request timeout that would cut off a slow-but-progressing generation (large outputs can take >60s to stream). Replaced with `httpx.Timeout(connect=10, read=30, write=10, pool=5)`: the `read=30` fires only if **no bytes arrive for 30 seconds**, so a legitimate slow response keeps streaming while a truly stalled connection (e.g. OpenRouter holding a TCP socket open with no data while waiting for Anthropic capacity) is detected and retried. The existing `_api_call_with_retry` loop handles `openai.APITimeoutError` via the general `except Exception` branch.

### Lower max_tokens to avoid OpenRouter token-rate-limit 402s

**Reduce max_tokens across all generate.py API calls** — OpenRouter enforces a per-model token-rate-limit bucket. With `max_tokens=32000`, each request consumed a large chunk of the bucket even when actual output was ~4,700 tokens (generation) or ~400-500 tokens (repairs/adjustments). This caused 402 errors mid-batch as the bucket depleted, manifesting as `"can only afford N"` with N decreasing across successive requests.

| Call | Old | New | Typical actual |
|---|---|---|---|
| Phase 1 generation | 32000 | 8192 | ~4700 |
| Phase 2 bug intro | 32000 | 8192 | ~500 |
| Phase 2 phase | 16000 | 8192 | ~500 |
| Repair | 32000 | 4096 | ~400–500 |
| Adjust difficulty | 16000 | 4096 | ~400–500 |

8192 gives 74% headroom over observed peak usage. 4096 gives 8× headroom for repairs which have never exceeded ~500 tokens.

### Fix Early Adjustment: Full Re-eval After Code Change

**Restart full eval after early adjustment** (`pipeline.py`) — The early adjustment path (0/3 Opus + low test rate → adjust → resume) was carrying forward the 0/3 prior results and running only 2 more trials on the *adjusted* code. This mixed pre- and post-adjustment results — the 0/3 was from the old code, the 2 remaining from the new code. Fixed: after a successful early adjustment, the loop simply continues to `evaluate_task` which runs a fresh full eval. Removed the `run_opus_eval` resume path and its unused import.

**Confirmed no saved tasks affected** — Early adjustment was committed at 14:17. All saved learnable tasks came from batch 22 (10:41 AM) or earlier, which used the old full-eval code path.

### Skip Sonnet Filter After Too-Hard Adjustment

**Skip Sonnet on re-eval after too_hard adjustment** (`pipeline.py`) — If a task was classified as too_hard by Opus (0-1/5 passes), the difficulty adjustment makes it easier. Re-evaluating through the Sonnet filter (5 runs) before Opus is wasteful — a task that was too hard for Opus can't be too easy for Sonnet. Now sets `skip_sonnet=True` on the `evaluate_task` call after a too_hard adjustment, going straight to Opus. Saves ~5 minutes per too_hard adjustment round. Does not apply to too_easy adjustments (which need Sonnet to verify the task is no longer trivial).

### Same-Topic Example Priority in Prompt Selection

**Prioritize same-topic examples** (`generate.py`) — `select_examples` now accepts `target_topic` and guarantees that if an existing learnable example matches the current topic, it's included first (Phase 0, before category diversity). This ensures Sonnet sees "here's what worked for this exact topic before" when regenerating a topic that already has a learnable example. Previously, the setup.py topic failed functional validation in batch 27 despite having a learnable example from batch 22 — because the scoring algorithm ranked other build-systems examples higher by token efficiency.

**No duplicate selection**: Phase 0 selection is tracked in `selected_dirs`, so the same example isn't picked again in Phase 1 (category diversity) or Phase 2 (fill remaining budget).

### Content-Based Task Dedup

**Content-based dedup for auto-promotion** (`pipeline.py`) — Previously, `_auto_promote` only checked if the exact dirname already existed in `examples-sonnet/`. This missed duplicates with different dir names (e.g., `debug-broken-webhook-receiver` vs `debug-a-broken-webhook-receiver-with-incorrect-1f481f` were byte-identical). Now hashes all source files (excluding infrastructure like Dockerfile, solution.sh, _meta.yaml) and compares against existing examples. Same topic with different code is correctly allowed — only identical content is rejected.

**Why content-based, not topic-based**: Analysis of 5 same-topic pairs showed 4 have genuinely different implementations (14-36% Jaccard similarity, different line counts, different code structure). Only 1 pair was truly identical (webhook receiver, 100% Jaccard). Topic-based dedup would incorrectly reject diverse implementations of the same topic.

**Fixed _meta.yaml missing `topic` field** (`pipeline.py`) — `_write_task_meta` was writing classification, pass_rate, etc. but never the topic string. This made it impossible to identify which prompt bank topic a task came from. Backfilled all 20 existing `_meta.yaml` files.

**Validation test**: Added `test_no_duplicate_content_in_examples_sonnet` which hashes all tasks and fails if any two are byte-identical. Runs as part of the test suite to catch future duplicates.

### Dashboard: Durable Eval Tier Scores

**Persist Sonnet filter scores in `_status.json`** (`evaluate.py`) — Sonnet filter run artifacts get cleaned up after parsing, so the dashboard couldn't show Sonnet scores for tasks that had already moved to Opus. Added `_write_eval_status()` which writes `eval_tiers.sonnet.{passes, total, filtered}` to `_status.json` after the filter completes. The dashboard reads this as the primary source, falling back to live `runs/` dir (filtered by batch start timestamp to prevent cross-batch collisions).

**Write `_status.json` at every pipeline exit point** (`pipeline.py`) — Previously, several early returns (structural validation failure, retry generation failure, functional validation failure, infrastructure error, adjustment failure, adjustment rounds exhausted) did not update `_status.json`. Killed batches would leave tasks showing stale "evaluating" or "functional" status. Now every exit path writes the final status before returning.

### Dashboard: Fix Sonnet/Opus Cell Rendering Inconsistencies

**Remove broken `runs/` fallback from main row SONNET and OPUS cells** (`dashboard.py`) — Both cells had a `runs/` directory fallback that was doubly broken: (1) it read stale dirs from previous pipeline runs, and (2) the `results.json` path was wrong — it looked for `runs/{run_id}/results.json` but the actual structure is `runs/{run_id}/{task_id}/{trial_dir}/results.json`. This caused "..." to appear for completed tasks whenever a stale `runs/` dir existed.

Fixed behavior:
- **Completed tasks with stages data**: show `passes/total` (unchanged)
- **Completed tasks without stages data** (older pipeline format): show `—` instead of misleading `...`
- **In-progress evaluating tasks**: show `...` (no stages written yet — genuinely pending)
- **eval_skipped tasks**: show `skip` (unchanged)
- Also eliminated duplicate `eval_stages` lookup between Sonnet and Opus rendering blocks.

**Fix stale docstring in `evaluate.py`** — module header said "Sonnet × 3 runs" but constant is `SONNET_FILTER_RUNS = 5`.

### Dashboard: Fix Spurious Eval Rows Before Any Trials Complete

**Remove stale `runs/` fallback and fix batch-dict accumulation** (`dashboard.py`) — Two bugs caused "unknown_agent_errors 0/0" to appear before any evaluation had run:

1. **Batch-level dicts appended as trial dicts**: when `trials: []` was empty, the `else` branch appended the batch dict itself (wrong schema) into `all_trials`, producing rows with spurious `failure_mode` values and 0/0 test counts.
2. **Stale `runs/` directory fallback**: the fallback scanned `runs/eval-{dirname}-*` directories, which persisted from previous pipeline runs with different timestamps, causing stale trial data from prior batches to appear on current tasks.

Both the `else: all_trials.append(batch)` branch and the entire `runs/` fallback block are removed. The eval section guard is tightened to `has_real_eval = bool(all_trials) or (eval_data.get("total") or 0) > 0`, so the block only renders when at least one real trial has completed.

### Dashboard: Expandable Task Details

**Expandable task cards** (`dashboard.py`) — Each task row now has a "Details" expander showing:
- **Stage timeline**: current stage, last updated timestamp
- **Functional validation**: per-attempt results with pass/fail, execution times (build, test_without, test_with), error messages, and expandable test output excerpts
- **Opus evaluation**: per-trial results showing tests passed/total, agent duration, token usage, failure mode, and expandable per-test pass/fail breakdown
- **Difficulty adjustments**: round number, trigger reason, and expandable raw adjustment response
- **Task files**: list of generated files

This surfaces retry counts, per-stage durations, and debug output that were previously only visible via CLI or manual file inspection.

### Code Quality

**Fix `_run_tb` timeout scaling for concurrent runs** (`evaluate.py`) — The subprocess timeout was set to `timeout_sec * n_attempts` (e.g. 5 × 900s = 75 min for 5 trials). But `tb run` executes trials with `--n-concurrent min(n,4)`, so actual wall time is `ceil(n / concurrent) × timeout_sec` (e.g. 2 waves × 900s = 30 min for 5 trials). The old formula was 2-5× too large, masking genuinely hung runs — a stuck agent could block a task slot for 45-75 min instead of 15-30 min. Fixed with `math.ceil(n_attempts / min(n_attempts, 4)) * timeout_sec`. Also promoted the hardcoded `max_tb_retries = 1` local variable to a module-level constant `_MAX_TB_RETRIES`.

**Remove dead `previous_json` variable in `regenerate_task`** (`generate.py`) — `previous_json = json.dumps(...)` was computed from all task files on every repair call but never referenced; the actual prompt uses `context_json` built from the targeted subset of files. Silent JSON serialization waste on every retry.

**Move inline imports to module level** (`pipeline.py`) — Four imports were scattered inside function bodies: `import json` in `_write_adjustment_snapshot` (already at module level — pure redundancy), `from evaluate import run_opus_eval as _run_opus_resume` in `run_pipeline` (already imported at module level as `run_opus_eval`), and `from evaluate import _run_tb` + `from config import SONNET_FILTER_MODEL` inside the too_easy adjustment branch. All moved to module-level imports. The redundant re-import alias is removed; callers now use `run_opus_eval` directly.

**Extract `_strip_fences` helper** (`generate.py`) — The markdown fence-stripping logic (strip ` ```json ` wrappers from LLM responses) was copy-pasted identically in `_parse_response` and `adjust_difficulty`. Extracted into a shared `_strip_fences(text: str) -> str` helper. Both call sites simplified to a single line. The helper comment explains why regex can't be used (JSON content may itself contain triple backticks).

**Use `yaml.dump` in `_write_task_meta`** (`pipeline.py`) — `_meta.yaml` was written with hand-rolled f-string writes. If any value (particularly `category`) contained a YAML special character (`:`, `#`, `"`, etc.) the output would be silently malformed and fail to parse. Replaced with `yaml.dump(..., sort_keys=True)` which handles all edge cases. `yaml` (pyyaml) was already a declared generator dependency; added module-level import to `pipeline.py`.

**Document `SONNET_SKIP_THRESHOLD=3` tradeoff** (`config.py`) — The threshold was lowered from 4 to 3 (skip if Sonnet passes ≥ 3/5). The single-line comment didn't capture the full reasoning. Expanded to explain: Opus reliably outperforms Sonnet, so a task Sonnet solves 3/5 is expected to land at 4-5/5 for Opus (too easy). The accepted false-positive risk — a Sonnet-3/5 task that Opus would also solve exactly 3/5 — is low in practice and cheaper than running Opus on likely-too-easy tasks.

**Document `regenerate_task` always uses full prompt** (`generate.py`) — Added a comment clarifying that repairs always use `SYSTEM_PROMPT` (Variant A, full constraints) regardless of how the task was originally generated. This is intentional: targeted repair needs the full constraint set to fix specific structural/functional issues.

### Sonnet Filter / Adjustment Fix

**Pass filter scores through to adjustment** (`evaluate.py`) — When the Sonnet filter flagged a task as too_easy (3/5), the eval result returned `passes=None, pass_rate=None` (since Opus never ran). The pipeline converted this to 0%, so the adjustment prompt was told "too_easy with 0% pass rate" — contradictory and unhelpful. Now `_build_result` passes the filtering model's actual scores (e.g., 3/5 = 60%) as the pass/total, giving the adjustment prompt accurate context.

**Unified adjustment loop** (`pipeline.py`) — The too_easy adjustment path had a separate "Sonnet quick-check" (3 runs, threshold 3) that duplicated the Sonnet filter logic with different parameters. Removed the quick-check entirely. After adjustment, the loop simply continues and calls `evaluate_task` which runs the standard Sonnet filter (5 runs, threshold 3). One code path, one threshold, no divergence. Also removed unused `_run_tb` and `SONNET_FILTER_MODEL` imports from pipeline.py.

### Early Adjustment with Test-Level Granularity

**Early adjustment after 0/3 parallel batch** (`evaluate.py`, `pipeline.py`) — Major refactor of the evaluation + adjustment loop. Previously, the pipeline ran all 5 Opus trials before adjusting difficulty, wasting 2 expensive Opus runs on clearly-too-hard tasks. Now, after the initial 3-parallel Opus batch:

1. If 0/3 passes AND average test pass rate < 30%, the task is "clearly too hard" — adjust difficulty immediately before running the remaining 2 trials
2. If 0/3 passes but test pass rate >= 30%, the task is "close" — let it play out (Opus is fixing most tests, just not all)
3. After early adjustment, resume Opus eval with only the remaining 2 runs, carrying forward the 0/3 prior results

**Test-level difficulty signal** (`evaluate.py`) — New `_extract_test_stats()` function aggregates per-test pass/fail data from `parser_results` across all trials. Returns average test pass rate (0.0-1.0), enabling granular difficulty assessment. A task where Opus fixes 5/7 tests consistently (71% test rate) but never fully solves is fundamentally different from one where Opus fixes 0/7 tests (0% test rate) — the former needs a small nudge, the latter needs aggressive adjustment.

**Refactored Opus evaluation** (`evaluate.py`) — Extracted `run_opus_eval()` as a reusable function that supports resuming from prior results. This enables the early-adjustment pattern: run 3 trials → adjust → resume with 2 more trials passing in the prior 3 as context. Also extracted `_can_stop()` for early-stop classification logic.

**Refactored adjustment logic** (`pipeline.py`) — Extracted `_try_adjustment()` helper that handles snapshot creation, adjustment call, functional re-validation, and snapshot restoration on failure. Eliminates duplication between early adjustment, normal too_hard adjustment, and too_easy adjustment paths.

### Retry and Error Handling Hardening

Comprehensive audit of all error paths in the pipeline. Previously, several failure modes would silently abandon a task with no retry. Now every error path either retries with context or logs diagnostics.

**Generation exception handling** (`pipeline.py`) — If `generate_task_solution_first()` throws an exception (API timeout, network error), `_status.json` is now updated to show the failure instead of staying at "generating" forever. Previously the exception propagated to batch.py's catch block but `_status.json` was never updated, making the task appear permanently stuck in the UI.

**Docker build retries** (`docker_validate.py`) — `_build_image()` now retries up to 2 times on transient failures (connection refused, daemon not running, DNS resolution, I/O timeout). Previously a single Docker daemon hiccup would fail the entire validation with no retry.

**tb run retries** (`evaluate.py`) — `_run_tb()` now retries once on transient subprocess failures (connection refused, daemon not running, resource temporarily unavailable) and on timeouts. Previously a single timeout meant 0 passes and too_hard classification, even if the failure was transient.

**Incremental write durability** (`batch.py`) — JSONL appends now call `f.flush()` + `os.fsync()` to ensure data hits disk before the thread continues. Prevents data loss if the batch process crashes between write and OS flush.

**Silent exception logging** (`pipeline.py`) — `_write_status()` now logs a warning to stderr instead of silently swallowing file I/O errors. Disk-full or permission-denied errors are no longer invisible.

**Phase 2 file guard** (`generate.py`) — After Phase 2 returns buggy files, the merge step now validates that Phase 2 only modified known source files from Phase 1. Unknown files and infrastructure/test modifications are logged and ignored, preventing Phase 2 from corrupting test data or introducing files the solution doesn't cover.

### Known Limitation: Phase 1 test-data mismatches

Batch 23 root cause analysis revealed that 2/3 functional validation failures were caused by Phase 1 generating test expectations that don't match test data (e.g., CSV with 7 "completed" records but test asserts 6). The solution and buggy code are both correct relative to Phase 1 — but Phase 1 itself has an internal inconsistency. The ideal fix is running tests against the working code in Phase 1 *before* proceeding to Phase 2, which would catch mismatches immediately. **Tradeoff**: this doubles Docker build cost per generation attempt (one build for Phase 1 validation + one for functional validation after Phase 2). Currently mitigated by the existing retry loop — functional validation catches the mismatch and regenerates from scratch, at the cost of wasted API calls for Phase 1 + Phase 2. If functional validation failure rates remain high, the Phase 1 pre-check may be worth the Docker cost.

### Sonnet Filter Calibration

**Lowered SONNET_SKIP_THRESHOLD from 4 to 3** (`config.py`) — Cross-batch analysis shows Opus consistently scores >= Sonnet on the same tasks. A task Sonnet solves 3/5 is almost certainly too easy for Opus (likely 4-5/5). The one learnable case with Sonnet data (Docker build) had Sonnet 2/4, Opus 1/3 — Opus scored lower, confirming Sonnet is a conservative proxy. Threshold of 3 catches too_easy tasks earlier, enabling cheaper adjustment via Sonnet quick-check instead of burning Opus eval budget.

**Re-enabled Sonnet filtering for batch 25** — Batches 22-24 used `--skip-filters` to speed up eval, sending all tasks directly to Opus. This saved wall-clock time but wasted Opus budget on potentially-too-easy tasks. Sonnet filtering adds ~5 minutes per task (5 Sonnet runs) but each Sonnet run costs ~1/10th of an Opus run. If Sonnet catches even 1 too-easy task per batch, the 5 Sonnet runs ($0.15) save 5 Opus runs ($1.50) — a 10x return. The tradeoff is longer wall-clock time for cheaper total cost.

### Prompt Cleanup

**Removed prompt variant B** (`generate.py`, `pipeline.py`, `batch.py`) — Variant A (verbose constraints with data-driven structural rules) has been used exclusively in all successful batches (including batch 22's 75% learnable rate). Variant B (trimmed, example-driven) was tested once in batch 5 but never adopted. Removed SYSTEM_PROMPT_B, PHASE2_PROMPT_B, the variant-B user prompt path, and the `--prompt-variant` CLI flag to reduce dead code. Variant A is now the only generation prompt.

### Difficulty Adjustment Testing

**Direct test of severity-based adjustment on batch 22 too_hard tasks** — Wrote `test_adjust_difficulty.py` to test `adjust_difficulty()` in isolation on the "fix-a-python-unit-test-suite-where-fixtures-have-411353" task (too_hard, 0% pass rate). Results: Sonnet picked `simplify_bug` operation, applied 4/6 edits successfully (2 failed on string matching — one exact match not found in test file, one ambiguous match in solution.sh). Changes: added BUG comments near all 3 bugs in fixture_manager.py, added missing `setup()` call hint, expanded task.yaml with specific function names and symptoms for each bug. Functional validation passed (tests fail without solution, pass with solution). Duration: 38s, 11.5K tokens. Confirms the severity-based prompt (0-pass aggressive mode) produces valid, functional edits.

### Topic Pool

**Removed 8 "fundamentally too_hard" topic exclusions** (`prompts.py`) — Batch 22 proved that difficulty adjustment can convert too_hard topics to learnable: 5 of 9 learnable tasks in batch 22 were previously excluded topics that became learnable via surgical adjustment. Removed the 8 exclusions added in commit 5b42a68 (bash quoting, config parser, DNS resolver, SQLite migration, XML converter, backup rotation, CSV crash, monitoring script). These topics are now back in the selection pool, increasing pool size from ~20 to ~28.

### Difficulty Adjustment

**Surgical difficulty adjustment** (`generate.py`) — Replaced the full-regeneration approach in `adjust_difficulty()` with constrained surgical string-replacement edits. Previously, when a task was too_hard or too_easy, Sonnet would regenerate ALL task files from scratch — renaming functions, restructuring code, rewriting tests — which broke test/code alignment and created new failure modes (batch 17: 5/5 adjusted tasks still 0% after 2 rounds). Now Sonnet must pick exactly ONE operation from a constrained menu:
- **too_hard (0 tests passing)**: aggressive multi-edit — simplify hardest bug, add code comments near all bugs, improve instruction, remove a test. One surgical edit won't move a fundamentally-too-hard task.
- **too_hard (close)**: surgical single-operation — remove_bug, add_hints, or simplify_bug
- **too_easy**: add_bug, make_subtler, or remove_hints + cheap Sonnet x3 quick-check before re-running expensive Opus eval
- **First confirmed adjustment→learnable**: Batch 22 produced 2 learnable tasks via difficulty adjustment (CLI tool 33%, setup.py 33%) — both were initially too_hard

Each edit uses exact string replacement (`old` → `new`) applied to existing files — no file renames, no restructuring, no test rewrites. If an edit's `old` string isn't found verbatim, it fails explicitly and retries. Tests verified on 2 known too_hard tasks: bash quoting (removed `$(ls)` bug, kept quoting bugs) and XML converter (fixed inverted flattening, deleted its test) — both applied 5/5 edits cleanly in 18.5s with tests/Dockerfile/run-tests.sh untouched.

**Data-driven generation prompts** (`generate.py`) — Root-cause analysis of batch 17 too_hard vs learnable tasks revealed that task *structure* predicts Opus success better than topic domain. Updated all three generation prompts (SYSTEM_PROMPT, PHASE1_PROMPT, PHASE2_PROMPT) with data-driven structural guidance:
- **PHASE1 (test design)**: Tests must invoke the program directly via subprocess/import inside each test function. run-tests.sh must NOT pre-execute the program and cache output to /tmp files. Task instructions must describe requirements, not line-by-line diffs.
- **PHASE2 (bug design)**: Prefer "architectural" bugs (wrong algorithm, missing logic branch, wrong data structure) over "token-change" bugs (add a quote, change an operator). Each bug should break 1-2 tests, not all tests — enabling partial credit. Explicitly prohibit all-or-nothing designs.
- **SYSTEM_PROMPT**: Added "Structural Patterns for Learnability" section documenting 4 data-driven rules (partial credit, behavioral tests, requirement-based instructions, architectural bugs).
- Reverted 7 topic exclusions (bash quoting, config parser, DNS resolver, etc.) back into the pool — these topics should now generate learnable tasks with the improved structural guidance. Pool size: 28 topics (up from 21).
- Softened PHASE2 bug guidance per feedback: changed from "prefer architectural bugs / avoid token-change bugs" to "use a MIX of 1-2 simple bugs + 1-2 subtle bugs." Data showed learnable tasks actually had simple bugs (wrong operator, missing return) — pure architectural bugs risk being too_hard.

**Freestyle topic generation reverted** — Tested `--freestyle` mode (Sonnet picks its own topics) in batch 20. Results: worse functional pass rate (58% vs 75% with topic bank), poor diversity (5/12 tasks were "text processing CLI"), and concurrent launches couldn't dedup because `previous_topics` was empty for all threads. Topic bank approach retained — 28 topics remaining is sufficient.

### Reliability

**Crash-safe batch reports** (`batch.py`) — Batch runs now always produce a report file, even on crash (OOM, KeyboardInterrupt, credit exhaustion). Previously, if a batch died mid-execution, no report was written and the dashboard showed it as perpetually "active". Now the execution is wrapped in try/except with a finally-style report write that captures whatever results completed before the crash, tagged with `batch_status: "crashed"`. KeyboardInterrupt and SystemExit are re-raised after the report is saved.

**Metrics merge for incomplete batches** (`metrics.py`) — The metrics loader now merges incremental JSONL results into report files. When a batch has both a report and incremental file, any task with a null classification in the report is replaced by the real result from the incremental file if available. This fixes a bug where aborted batches with manually-created stub reports hid completed results (e.g., batch 5's learnable template engine task was invisible). Learnable count restored from 2 → 3.

**Difficulty adjustment snapshots** (`pipeline.py`) — Pre-adjustment task snapshots are now always preserved (as `.pre_adj{N}` directories) instead of being deleted on success. Each snapshot includes `_adj_snapshot.json` with the classification, pass rate, and per-trial results that triggered the adjustment. This enables before/after analysis of how adjust_difficulty changes tasks and whether those changes improve learnability.

**Prune exited Docker containers** (`evaluate.py`) — Added `_prune_exited_containers()` to `cleanup_stale_resources()`. The `tb` harness leaves stopped containers behind after each eval run; without pruning these accumulate (130+ in batch 11 alone). Now pruned automatically alongside stale container kills and network cleanup.

**Pre-built Docker base image for high concurrency** (`validator/Dockerfile.base`, `docker_validate.py`) — Batch 12 with `--n-concurrent 12` had 12/12 failures from Docker build timeouts (300s) caused by 12 tasks all running `apt-get update && apt-get install` simultaneously. Fix: pre-built `tbench-base:latest` image with all common deps (python3, gcc, cmake, tmux, uv, etc.). The validator auto-rewrites each task's Dockerfile from `FROM ubuntu:*`, `FROM python:*`, or `FROM debian:*` to `FROM tbench-base:latest`, stripping apt-get/pip install layers. Per-task builds drop from ~60-280s to ~0.4s, making concurrency of 12 feasible. Base image is built once on first use and cached. Batch 13 confirmed: 25/29 builds at 0.35-0.59s; the 4 slow ones (83-277s) were from `FROM python:3.11-slim` which the initial version didn't rewrite — now fixed.

**Richer test output in retry feedback** (`pipeline.py`) — Increased stdout included in retry feedback from 500→1500 chars. Previously, when a task failed functional validation ("Tests FAILED with solution applied"), the feedback to Sonnet truncated test output to 500 chars, often cutting off pytest's summary showing which tests failed and why. Now Sonnet sees the full `FAILED test_name - AssertionError: ...` lines, enabling more targeted solution fixes. The regenerate_task function already extracts failing test names and includes test source code — this ensures the actual error messages are also visible.

**Per-attempt functional validation logs** (`pipeline.py`) — Each functional validation attempt now saves a `validation_attempt_{N}.json` file in the task directory with the full result: pass/fail, issues list, phase results (tests_fail_without_solution, tests_pass_with_solution, solution_idempotent), execution times, and stdout/stderr tails. Previously validation failures were only printed to batch stdout, making it impossible to debug why specific tasks failed after the fact.

**Strip redundant apt-get/uv from run-tests.sh** (`docker_validate.py`, `Dockerfile.base`) — The base image rewrite (Dockerfile) fixed build-time timeouts, but run-tests.sh scripts also run `apt-get update && apt-get install` and `curl ... uv install`. With 12 tasks × 4 phases = 48 containers all running `apt-get update` simultaneously, every single task in batch 14 failed functional validation on attempt 1. New `_rewrite_run_tests_for_base()` strips apt-get, pip install, uv installer curl commands, and `source $HOME/.local/bin/env` from run-tests.sh since all these tools are pre-installed in the base image. Also added `ENV PATH="/root/.local/bin:${PATH}"` to Dockerfile.base so uv is on PATH in non-login shells (previously `bash /script.sh` couldn't find uv, causing exit 127 in all batch 16 tasks).

**Dashboard topic-to-directory matching fix** (`dashboard.py`) — Tasks with periods in their topic name (e.g., "setup.py") weren't matched to their directory because the slug comparison only stripped spaces and commas, not periods. The directory slug strips all non-alphanumeric chars, so "setup.py" → "setuppy" in the dir but "setup.p" in the dashboard's match string. Fix: use `re.sub(r"[^a-z0-9-]", "")` to strip all special chars consistently, and increased prefix from 20→30 chars for more reliable matching.

**Reduced validation timeouts** (`pipeline.py`) — Build timeout 300s→60s, test timeout 180s→120s. Data from batch 11 shows builds complete in <1s (with base image) and 99% of tests in 12-14s. The worst outlier (C linked list compilation) was 110s. Previous 180s timeout wasted minutes per task on tests that would never pass (e.g., tasks with server loops that hang forever).

**Fix UnboundLocalError on generation failure** (`pipeline.py`) — `task_dir` was referenced before assignment when generation failed, causing a crash that masked the real error.

**Cross-batch topic exclusion** (`prompts.py`) — Excluded topics that fail for infrastructure reasons (servers, concurrency, Node.js, Docker-in-Docker, etc.) and topics with 0% functional validation pass rate. Total exclusions: 26 topics, 28 remaining. Reverted 7 topic exclusions that were previously added as "fundamentally too hard" — root-cause analysis showed these fail due to task *structure* (all-or-nothing bugs, pre-computed output tests) not the topic domain. Fixed at the prompt level instead.

**Fix NoneType crash in eval result parsing** (`evaluate.py`) — `parser_results` can be `null` in trial data (not just missing), causing `'NoneType' object has no attribute 'values'` during result aggregation. Two batch 13 tasks (CMake, state machine) that passed functional validation and Opus eval were lost to this bug. Fixed with `or {}` guard.

### Generation

**Pre-batch prompt audit and refinements** (`generate.py`, `prompts.py`) — Systematic audit before committing to a $400-budget batch run:
- Fixed Phase 1 test count mismatch: was "6-10 test functions", now "5-7" matching the rest of the pipeline. This was likely producing too-hard tasks.
- Added Phase 1 guidance: source code <150 lines in a single file, modular structure to support clean bug injection
- Fixed `adjust_difficulty()` too_easy prompt: was telling Sonnet to "make symptoms misleading" and "point error messages to wrong location", directly contradicting the independently-discoverable principle. Now focuses on subtlety within discoverability bounds.
- Replaced `EXCLUDED_CATEGORIES` (blanket ban on 3 categories) with `EXCLUDED_TOPICS` (17 specific topics). Restores software-engineering and data-processing categories (both had learnable tasks) while pruning topics that violate pipeline constraints (server-based, concurrency, Node.js, Docker-in-Docker, /proc/systemd, infrastructure/packaging).

**Application-logic-only constraint** (`generate.py`, `prompts.py`) — Analysis of all 12 learnable tasks showed zero have bugs outside application logic, and all functional validation failures in batch 11 involved infrastructure/packaging bugs (pip install, CI/CD orchestration, environment scaffolding). Added Phase 1 prompt constraint: bugs must be in application logic only, tests must verify program behavior not infrastructure state. Excluded 2 more topics (`pyproject.toml` package build, CI/CD pipeline script) from the prompt bank.

**Metadata-driven example selection** (`generate.py`, `pipeline.py`) — Replaced hardcoded example classification with `_meta.yaml` metadata files on each example directory. New `select_examples()` function picks examples within a token budget (~20k tokens) using deterministic criteria:
- Category diversity: one example per category first, then fill by score
- Score = pass rate closeness to ideal (40-60%) + category match to target topic + token efficiency
- Too-hard examples excluded, at most 1 too-easy negative example included
- Pipeline auto-writes `_meta.yaml` for every evaluated task, enabling self-sustaining loop: generate → evaluate → feed best back as examples
- *Design decision*: Token budget (not example count) because examples vary 1k-6.5k tokens. Scoring by pass rate closeness ensures we show solidly learnable examples, not borderline ones.

**Solution-first is now the default** (`pipeline.py`, `batch.py`) — Non-solution-first consistently failed functional validation. Changed `solution_first=True` default, CLI flag is now `--no-solution-first`.

**Reduced retry budget** (`config.py`) — `MAX_SOLUTION_FIRST_RETRIES` reduced from 6 to 3. Retry data across 8 batches shows bimodal distribution: tasks either pass in 1-2 retries or max out at 6. Retries 4-6 are nearly pure waste (~$0.15/retry in Sonnet calls).

**Evaluate CLI: skip Haiku by default** (`evaluate.py`) — Fixed CLI to match function default (`skip_haiku=True`). Haiku tier was accidentally running on CLI invocations, wasting ~$0.20/task. Use `--include-haiku` to opt in.

**Solution-first strategy** (`generate.py`) — Phase 1 writes a complete working program with passing tests; Phase 2 introduces 3-5 interacting bugs into the source files. The working code becomes `solution.sh`. This inverts the original single-phase approach which asked the LLM to write broken code AND its fix simultaneously — that had ~20% functional validation pass rate. Solution-first separates two easy tasks (write correct code; introduce bugs) instead of one hard task.
- Phase 1 uses temperature 0.5 (correctness); Phase 2 uses 0.7 (creative bugs)
- Phase 2 requires majority of tests to fail, not all — some passing tests give the agent useful debugging signal
- Retry budget `MAX_SOLUTION_FIRST_RETRIES=3` (reduced from 6 — retries 4-6 rarely succeed)
- Source-only repair now includes test function code so the LLM can see what each test checks and introduce bugs that break those specific checks (previously guessed blindly)
- **Timeout-specific solution repair**: When solution.sh causes a hang (not just test failures), the repair prompt targets infinite loops, blocking I/O, and missing termination conditions instead of generic "fix all bugs."
- **Test-aware solution repair**: solution_only repair now includes failing test names and test function code, matching what source_only already had. Previously couldn't see which test was failing.
- **Timeout-specific solution repair**: When solution.sh causes a hang, repair prompt targets infinite loops, blocking I/O, and missing termination conditions instead of generic "fix all bugs."
- **Phase 2 diff validation**: Detects when Phase 2 returns files identical to Phase 1 (no bugs introduced), logging a warning to avoid wasting a Docker validation round.
- **write() crash fix**: `_write_task_files` coerces list content to string. LLMs occasionally return file content as a list of lines.
- **Phase 2 self-verification**: Prompt now requires the LLM to trace each test function against its buggy code and output a per-test verification ("test_X: WILL FAIL because..."). Forces chain-of-thought about test-to-bug mapping. Motivated by first Sonnet batch where 0/3 tasks passed functional validation because Phase 2 bugs didn't break tests.
- **Bug annotations in exemplars**: `_bugs.md` files in Opus exemplars explicitly describe each bug (what's wrong, why it's realistic, which tests it breaks). Loaded first in the few-shot context with a "BUG ANNOTATIONS" header so Sonnet learns the test-to-bug mapping pattern, not just what buggy code looks like.
- Usage: `python3.12 pipeline.py "topic" --solution-first`

**Few-shot example curation** (`generate.py`) — Three-way classification of reference examples:
- **Positive** (learnable): shown as "GOOD EXAMPLES — target this difficulty"
- **Negative** (too easy): shown as "TOO-EASY EXAMPLES — avoid this difficulty" (currently: `config-manifest-validator`)
- **Too hard**: excluded entirely — 4 of 6 hand-crafted examples are too hard (coordinate-transform, flask-api, log-rotation-analyzer, maven). All annotated with WHY they're too hard and patterns to avoid
- `examples-opus/` directory for Opus-generated exemplars that Sonnet can replicate cheaply at scale
- **Bug annotations** (`_bugs.md`): Every example now has a structured annotation describing each bug's subtlety level (LOW/MODERATE/HIGH), the test-to-bug mapping, and WHY the task falls in its difficulty category. Too-easy and too-hard examples include "patterns to avoid" sections that teach Sonnet the boundaries of good difficulty.
- *Design decision*: Subtlety ratings teach the QUALITY dimension of difficulty. Telling Sonnet "this is a HIGH subtlety bug because the wrong variable name looks correct at first glance" is more useful than "add 3-5 bugs."

**Prompt calibration** (`generate.py`) — Prompts recalibrated based on Sonnet→Opus correlation analysis (Sonnet 33% → Opus 0% pattern). Root cause: Sonnet generates bugs that are too clever — cascading failures, hidden cross-file bugs, 5+ interacting bugs. Key changes across SYSTEM_PROMPT, PHASE2_PROMPT, and user prompt:
- Cap at 3-4 bugs (was 3-5) — 5+ bugs consistently produces Opus 0/5
- Bugs must be independently discoverable from test output (was "interact with each other")
- Banned cascading bugs where Bug A must be fixed before Bug B can be diagnosed
- Single source file only (was "require reading the full codebase")
- Total source code under 150 lines — agent must read and understand in ~1 minute
- Clear test failures (wrong output, wrong type) — no undefined behavior or intermittent failures
- Target 10-20 minute human solve time (was 20-60 minutes)
- Per-difficulty hints (easy/medium/hard) were reverted earlier — every task should land in the learnable band regardless of topic.
- **Instruction quality (revised)**: Instructions should describe what the program does and expected behavior, but NOT hint at bug locations. Hints made tasks too easy (Sonnet solved 1/2 on variant B). The agent must read the code to find bugs — that's the difficulty source.
- **Test count cap**: 5-7 tests per task (was unbounded, Sonnet generated 9-11). Fewer tests with clearer pass/fail criteria give the agent margin for implementation differences — high test counts punish formatting mismatches rather than bug-finding ability.
- **Instruction hint style** (`--hint-style`): Three modes for task.yaml instruction hints — `none` (describe program only), `soft` (high-level area hint like "output formatting has issues"), `full` (specific area hints like "delimiter handling and header parsing"). Configurable per batch for A/B testing hint impact on difficulty.
- **JSON parse retry on repair**: `regenerate_task()` now retries up to 3 times when Sonnet returns invalid JSON, feeding back the parse error and asking for raw JSON only. Previously a single parse failure killed the entire retry chain.

**Prompt variant A/B testing** (`generate.py`, `pipeline.py`, `batch.py`) — Infrastructure for comparing verbose vs trimmed prompts. Variant A is the current full prompt (~35-40 constraints across SYSTEM_PROMPT, PHASE2_PROMPT, user prompt reminders). Variant B collapses the difficulty section to 3 core points ("match the examples"), removes redundant user-prompt reminders, and lets examples do the teaching instead of explicit rules. Hypothesis: Sonnet may internalize constraints better when not overloaded with rules that partly overlap the examples.
- `--prompt-variant B` flag on pipeline.py and batch.py
- Selects `SYSTEM_PROMPT_B`, `PHASE2_PROMPT_B`, and trimmed user prompt
- A/B comparison requires same seed/topics — use `--seed` flag in batch.py
- *Design decision*: Examples consume 80-95% of prompt tokens. If Sonnet already learns difficulty from examples, verbose constraint lists may cause attention dilution rather than reinforcement.

**Targeted repair** (`generate.py`, `pipeline.py`) — On validation failure, analyzes feedback to repair only broken files:
- "Tests FAILED with solution" → regenerate only `solution.sh`
- "Tests PASSED without solution" → regenerate only source files (with test code included so LLM knows what to break)
- "Docker build failed" → regenerate only Dockerfile (conflicting packages, wrong base image)
- Structural issues → full rebuild (rare)
- Difficulty adjustment focuses on bug **subtlety/discoverability** not quantity — making bugs more/less obvious rather than adding/removing them
- *Design decision*: Full-rebuild retries caused "whack-a-mole" — fixing one file broke others. Targeted repair cut retry cost ~80%.

**JSON parse robustness** (`generate.py`) — Handles markdown fences, embedded JSON, and triple-backtick content within JSON values.

### Validation

**Solution diff analysis** (`validator/validate.py`) — Pre-Docker calibration check that diffs buggy source files against solution.sh heredocs. Parses `cat > path << 'DELIM'` patterns to extract fixed file contents, then computes: files changed, change regions (hunks, proxy for bug count), total lines changed, and source LOC. Generates warnings for:
- Too many change regions (>8 hunks — likely too many bugs)
- Too few change regions (<2 hunks — likely too easy)
- Multi-file changes (>2 source files modified)
- Large diffs (>80 lines changed — too complex for 6-minute agent time limit)
- High source LOC (>200 lines)

**WORKDIR file layout check** (`validator/validate.py`) — Structural validation now fails if solution.sh writes files outside the Dockerfile's WORKDIR. Tasks with source files in system directories (e.g. `/etc/nginx/`) cause the agent to waste time navigating instead of debugging. Parses WORKDIR from Dockerfile and checks all heredoc/echo write targets in solution.sh. Both prompt variants updated to explicitly require all source files in WORKDIR.
- Validated against confirmed learnable tasks (csv-to-json: 5 hunks/24 LOC, C linked list: 5 hunks/125 LOC) and too-hard tasks (flask-api: 3 files/7 hunks, coordinate-transform: 8 hunks/51 lines changed). Thresholds calibrated so learnable tasks pass clean while too-hard tasks get flagged.

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
- **Backup/restore on adjustment failure**: Task files are backed up before each adjustment. If the adjusted version fails validation, the backup is restored and the original classification is preserved. Previously, failed adjustments destroyed working (but wrong-difficulty) tasks.
- *Design decision*: Full file replacement, not targeted repair — difficulty changes affect the relationship between source, tests, and solution.

### Post-Classification Analysis — Stretch Goal E

**Analysis module** (`analyze.py`) — Extracts features from classified tasks and identifies patterns that correlate with learnability. Feature extraction:
- **Bug type taxonomy**: Classifies diff hunks into categories (off_by_one, wrong_operator, wrong_variable, wrong_constant, missing_edge_case, missing_code, extra_code, logic_change) using heuristic pattern matching on the diff.
- **Test diagnostic quality**: AST-based analysis of test files — counts tests, assertion types (equality, membership, type_check), docstrings, descriptive names, average assertions per test.
- **Code structure**: Function/class count, max nesting depth, import count, LOC, language detection.
- **Instruction specificity**: Word count, mentions of files/functions/bugs, specificity score (low/medium/high).
- **Diff locality**: Spread ratio (0=clustered, 1=spread), gap distances between hunks.
- **Cross-group pattern analysis**: Compares averages across classification groups and generates actionable findings ("too-hard tasks average 8 bugs vs 3 for learnable").
- CLI: `python3.12 generator/analyze.py --learnable <dirs> --too-hard <dirs>` or `--batch-report <json>`

### Streamlit Dashboard (`dashboard.py`)

Live UI for monitoring and controlling the pipeline:
- **Overview**: Metric cards, pipeline funnel with progress bars, per-batch table
- **Learnable Tasks**: Inventory with Opus pass rates
- **Exemplar Browser**: Browse hand-crafted, Opus, and Sonnet examples with bug annotations
- **Live Status**: Running batch/eval processes, in-progress batch progress
- **Launch Batch**: UI controls for n_tasks, concurrency, seed, solution-first, prompt variant, hint style
- Active vs completed batch separation — running batches shown prominently with progress bars, completed collapsed
- Auto-refresh toggle for monitoring active runs
- Usage: `streamlit run dashboard.py`

### Pipeline Metrics — Part 3

**Metrics dashboard** (`metrics.py`) — Aggregates results across all batches:
- Pipeline funnel visualization (attempted → generated → structural → functional → evaluated → learnable)
- Per-batch breakdown table with functional/learnable/too-easy/too-hard counts
- Learnable task inventory with Opus pass rates
- Cost (generation tokens) and time totals
- HTML dashboard (`--html report.html`) with styled cards, funnel, and tables
- JSON export for programmatic consumption
- Current state: 9 batches, 36 tasks, 3 learnable (8% overall yield, 25% of evaluated)

### Diversity Analysis — Stretch Goal C

**Diversity module** (`diversity.py`) — Analyzes batch reports for:
- Category coverage (fraction of 6 categories present) and evenness (Shannon entropy)
- Language distribution
- Near-duplicate detection (Jaccard similarity on topic word sets, threshold 0.7)
- CLI: `python3.12 generator/diversity.py <batch-report.json>`

**Topic/prompt bank** (`prompts.py`) — 52 structured topics with category, difficulty, language metadata. Round-robin selection (`select_topics(diverse=True)`) maximizes coverage per batch. `EXCLUDED_CATEGORIES` filters out categories where Sonnet consistently fails to generate valid tasks: system-administration (0% functional pass rate), software-engineering (25%), and data-processing (33%). Remaining 26 topics across debugging, networking, and build-systems.

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
- **Targeted container kill on timeout**: When `_run_tb` hits `TimeoutExpired`, `_kill_containers_for_task(task_id)` immediately kills all containers matching the task — instead of relying on the age-based stale cleanup to catch them 20 minutes later. Root cause of persistent zombie containers: the `tb run` subprocess gets killed by the timeout, but its child Docker containers keep running with no parent to collect them.
- **atexit cleanup in batch runner**: `batch.py` registers an `atexit` handler that calls `cleanup_stale_resources(max_age_sec=60)` on exit. Catches orphaned containers when the batch process itself crashes, gets killed, or finishes normally — previously, zombies persisted until the next batch started.
- **Docker network cleanup**: `_cleanup_stale_networks()` removes orphaned Docker networks after containers are killed. `docker-compose` creates a network per task; if the container is killed without `docker-compose down`, the network leaks. Enough leaked networks exhaust Docker's address pool and block new runs. Safe: `docker network rm` only succeeds for networks with no connected containers.
- **Evaluation run cleanup**: `_run_tb` now removes run artifact directories after parsing results. All pass/fail data is captured in the return dict; the raw trial files under `runs/` were pure waste.
- **Docker build failures now retried**: Bad generated Dockerfiles (e.g., conflicting packages like `systemctl` vs `systemd`) are now retried with a `dockerfile_only` repair target that only sends the Dockerfile + error (not the full task). Only true environment errors (Docker not available, disk full, permission denied) skip retries.
- **Targeted repair context**: Dockerfile repairs send only the Dockerfile. Solution and source repairs send full task context (needed to understand file relationships).
- **API retry**: Exponential backoff (3 attempts, 5/10/20s) for transient OpenRouter failures. No retry on auth errors.
- **Phase 1/2 parse retry**: Both solution-first phases now retry the API call up to 3 times when the response is unparseable JSON, instead of failing immediately.

- **Trial data preservation**: `_parse_run_results` now captures agent timing (`agent_started_at/ended_at`), test pass counts (`tests_passed/total`), and token usage before cleanup deletes the raw files. Enables analysis of agent behavior on too-hard tasks without disabling cleanup.

### Code Quality

- `X | None` syntax throughout (not `Optional[X]`)
- Narrowed `except Exception` to specific types
- `_slugify` in dependency-free `config.py`; `batch_io.py` for resume helpers (no openai/pydantic chain)
- End-to-end integration test (`test_pipeline_e2e.py`) — 15 tests exercising the full `run_pipeline` flow (generate → structural → functional → evaluate) with mocked API/Docker. Covers happy path, solution-first strategy, generation failure, structural/functional retry, infrastructure error detection, difficulty adjustment loop, and regeneration failure.
- Generator unit tests (`test_generate.py`) — 26 new tests for `_parse_response` (JSON parsing edge cases, markdown fences, embedded backticks), `_load_examples` (three-way classification, opus examples), and `_slugify` (special chars, truncation, hash suffix).
- Evaluate tests (`test_evaluate.py`) — 32 tests covering stale resource cleanup, result parsing, filter tier early stopping, full evaluate_task orchestration (Haiku/Sonnet filtering, Opus classification, skip_filters, default skip_haiku), and _build_result.
- 302 tests across 14 modules (~5s, no Docker/API calls). Tests use `tmp_path` fixtures with synthetic tasks.

### Scripts

- **`generate-exemplar.sh`** — Generates a high-quality task using Opus (`--model anthropic/claude-opus-4 --solution-first`), validates structurally + functionally, and prints next-step commands for eval and promotion. Use this to build up `examples-opus/` before running Sonnet batches.
- **`promote-exemplar.sh`** — Copies a confirmed-learnable task to `examples-opus/`, strips pipeline artifacts, and commits. Takes `--opus-passes` and `--opus-total` for the commit message.

### Known Issues

- **Token tracking on timeout**: When the agent times out (`failure_mode=agent_timeout`), the harness returns 0 input/output tokens even though the agent may have made multiple LLM calls and partially fixed the task. The `AgentResult` partial result constructed on timeout doesn't pull token counts from the chat history. This means: (1) cost estimates are underreported for timed-out trials, (2) `resolved=True` with 0 tokens is valid — the agent fixed the code before timing out, and tests passed on the modified container.
- **4/7 tests pass on buggy webhook code**: The webhook receiver task has 4 tests passing without any fixes applied, meaning only 3 tests actually verify bug fixes. Tasks should aim for majority of tests failing on buggy code to properly measure agent capability.

- **Docker concurrency limit**: `--n-concurrent 12` caused all 12 tasks to fail functional validation — 36 simultaneous Docker containers triggered OOM kills (exit 137) and timeouts. Safe limit is `--n-concurrent 6` (18 containers peak). Batch 12 was a total loss; batch 13 reverts to 6 concurrent.
