# Work Trial: Task Generation Pipeline

## Context

Terminal Bench evaluates AI agents on coding tasks — an agent gets an instruction, works in a terminal, and tests verify whether it solved the problem. You've seen how this works from the take-home.

Now build the other side: **a pipeline that generates the tasks themselves.**

A generated task is only useful if it sits in the right difficulty band. Too easy and every model solves it. Too hard and none do. The sweet spot is a **learnable** task: when run 5 times with `terminus-1` using `anthropic/claude-haiku-4-5-20251001`, exactly **1 to 3 out of 5 runs pass all tests**. Your pipeline should produce tasks that consistently land in this range.

## What's Provided

- `generator/generate.py` — A task generator stub. Currently incomplete.
- `validator/validate.py` — A basic structural validator that checks whether files exist and task.yaml parses correctly.
- `examples/` — 6 reference tasks in the standard Terminal Bench format. Study these carefully.
- `terminal_bench/` — The Terminal Bench harness (source code). This is the framework that runs agents against tasks. Read the source to understand how it works — the CLI, the agents, the harness. The `pyproject.toml` lists all dependencies.
- `scripts/` — Helper scripts for generation and validation.

### Task Format

Each task directory contains:

```
task-name/
├── task.yaml           # Instruction, difficulty, timeouts, metadata
├── Dockerfile          # Container environment setup
├── run-tests.sh        # Runs pytest to verify the solution
├── solution.sh         # Deterministic reference solution
├── tests/
│   └── test_outputs.py # Pytest tests that verify the task was solved
└── [task-specific files]
```

Your generated tasks must follow this format exactly. Study the examples.

### What Makes a Good Task

A well-crafted task has:

- A clear, unambiguous instruction that describes what needs to be fixed or built
- Tests that **pass** when the task is correctly solved
- Tests that **fail** on an unsolved container (if the tests pass without anyone doing anything, the task is broken)
- A working reference solution (`solution.sh`) that makes all tests pass
- A Dockerfile that installs all necessary dependencies
- Appropriate difficulty — not trivially solvable, not impossibly hard

## Requirements

### Part 1: Generate Valid Tasks

Implement the generator and improve it so that generated tasks:

1. Pass the structural validator consistently
2. Are functionally correct: `solution.sh` passes all tests, and the task works end-to-end when run in a container

Verify by running the structural validator and by inspecting generated tasks against the examples.

### Part 2: Hit the Target Distribution

This is the core deliverable.

A task is **learnable** if, when run 5 times with `terminus-1` using `anthropic/claude-haiku-4-5-20251001`, exactly **1 to 3 runs pass all tests**. Tasks where 0 runs pass are too hard. Tasks where 4-5 runs pass are too easy.

Build a pipeline that produces learnable tasks. Your system should:

- Generate a task
- Evaluate it (run it against the agent)
- Report the pass distribution
- Only output tasks that land in the 1-3 out of 5 range

### Part 3: Pipeline Metrics

Generate a batch of tasks (aim for 10+). Report:

- How many pass structural validation
- How many are functionally correct
- How many land in the 1-3/5 learnable range
- Total cost and time

### Stretch Goals

If you keep going:

**A. Cost-efficient evaluation** — Running 5 agent attempts per task adds up. Design a strategy that reduces total evaluation cost while still reliably identifying learnable tasks.

**B. Difficulty tuning** — Given a task that's too easy or too hard, can your pipeline adjust it to land in the target band?

**C. Diversity analysis** — Analyze your generated tasks for category coverage, difficulty spread, and instruction uniqueness. How would you ensure your pipeline doesn't keep generating the same kind of task?

**D. Human-likeness** — Compare your generated tasks side-by-side with the hand-crafted examples in `examples/`. How close are they in terms of instruction clarity, test thoroughness, Dockerfile quality, and overall polish? Can your pipeline produce tasks that are indistinguishable from human-written ones?

## Setup

### Prerequisites

- Docker Desktop (running)
- Python 3.12+
- `uv` (recommended) or `pip`

### Install Terminal Bench

```bash
cd terminal_bench
uv pip install -e ".[dev]"
```

Or with pip:

```bash
cd terminal_bench
pip install -e ".[dev]"
```

Verify: `tb --help`

### Install Generator Dependencies

```bash
pip install -r generator/requirements.txt
pip install -r validator/requirements.txt
```

### Environment

```bash
export OPENROUTER_API_KEY="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"
```

### Running the Generator

```bash
bash scripts/generate.sh "fix a broken Python script"
```

### Running the Validator

```bash
bash scripts/validate.sh output/fix-a-broken-python-script
```

## Evaluation Criteria

In order of importance:

1. **Do your tasks hit the target distribution?** — What fraction of generated tasks are learnable (1-3 out of 5)?
2. **Pipeline design** — How did you decompose generation, validation, and evaluation?
3. **How do you know your tasks are good?** — What's your validation and evaluation strategy?
4. **Reliability and throughput** — Can you generate calibrated tasks consistently?
5. **Code quality** — Clean, readable, well-structured

Include:

- All source code
- `CHANGELOG.md` describing what you did, why, and any design tradeoffs
- Your git commit history (we read it)

