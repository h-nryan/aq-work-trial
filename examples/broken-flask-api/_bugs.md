# This task is TOO HARD (Opus 0/5, Sonnet 0/3)
# DO NOT generate tasks at this difficulty level.

## Why it's too hard:
- Server-based task requires starting Flask and waiting for it to be ready
- Multiple interacting issues: dependency (Flask not installed), syntax errors,
  data format bugs, AND routing logic bugs
- Tests use HTTP requests — timing-sensitive, can fail due to server startup race
- Agent must fix requirements.txt, data/users.json, AND app.py — three different
  file types with different bug patterns

## What makes a task too hard (AVOID these patterns):
- Server-based tasks (timing-dependent, hard to validate)
- Tasks requiring fixes across 3+ different file types/languages
- Dependency installation issues combined with code bugs
- Tests that depend on network requests or service readiness
