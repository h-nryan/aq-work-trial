# This task is TOO HARD (Opus 0/5, Sonnet 0/5)
# DO NOT generate tasks at this difficulty level.

## Why it's too hard:
- Task requires CREATING a tool from scratch, not fixing existing code
- Broad, underspecified requirements (analyze patterns, generate recommendations)
- Multiple file system operations needed (traverse /var/log/samples/, parse
  various log formats, compute statistics)
- The "bugs" are missing functionality, not broken existing code
- Agent must understand log rotation conventions (logrotate, date-stamped
  files, .gz compression) as domain knowledge

## What makes a task too hard (AVOID these patterns):
- "Create from scratch" tasks instead of "fix existing code"
- Requirements that need domain expertise (sysadmin conventions, protocol specs)
- Underspecified output format (what exactly should the "structured report" contain?)
- Tasks where the instruction is essentially the entire specification
- No existing code to serve as scaffolding — agent starts from zero
