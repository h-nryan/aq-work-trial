# This task is TOO HARD (Opus 0/5, Sonnet 0/5) — pending final confirmation
# DO NOT generate tasks at this difficulty level.

## Why it's too hard:
- Requires deep Maven/Java expertise (POM files, manifest classpath, assembly plugin)
- Multi-module project with parent POM + 3 submodules
- Bugs span build configuration (XML), not just code — Maven POM syntax is verbose
  and easy to get wrong even for experienced Java developers
- Runtime classpath issues are notoriously hard to debug (NoClassDefFoundError
  gives no hint about which POM setting is wrong)
- Agent must understand Maven lifecycle, dependency resolution, and JAR packaging

## What makes a task too hard (AVOID these patterns):
- Build system configuration bugs (POM, Gradle, CMake) — config languages are
  harder than code languages for agents to reason about
- Multi-module projects where the bug is in the wiring between modules
- Runtime-only failures (code compiles but fails at runtime with opaque errors)
- Tasks requiring tool-specific expertise (Maven assembly plugin, classpath manifest)
