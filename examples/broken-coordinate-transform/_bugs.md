# This task is TOO HARD (Opus 0/5, Sonnet 0/3)
# DO NOT generate tasks at this difficulty level.

## Why it's too hard:
- C++ matrix multiplication with multiple interacting bugs
- Requires understanding matrix math AND C++ memory management simultaneously
- Bugs span input parsing, dimension validation, multiplication logic, and output
- Error messages are misleading — incorrect dimension check passes invalid inputs
- The agent must trace through the entire program with sample inputs to verify

## What makes a task too hard (AVOID these patterns):
- Bugs that require domain expertise (matrix math, protocol specs, algorithm theory)
- Multiple bugs that form long dependency chains (fix A to see B, fix B to see C)
- Symptoms that appear in a completely different location than the root cause
- Tasks requiring reasoning about memory layout or undefined behavior
- Bugs that only manifest with specific numerical inputs (not obvious test cases)
- Single-file programs where every function has at least one bug
