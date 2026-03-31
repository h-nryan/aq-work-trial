"""
Topic/prompt bank for diverse task generation.

Each prompt is structured with:
- A descriptive topic string (passed to the generator)
- Category (maps to TASK_CATEGORIES in config.py)
- Target difficulty
- Primary language/technology

The bank is designed to cover:
- All 6 task categories evenly
- Multiple languages (Python, Bash, C/C++, Node.js, Go, Rust, Java)
- All 3 difficulty levels with a 25/50/25 distribution
- Varied bug types (logic, syntax, config, concurrency, data handling)
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class TopicEntry:
    topic: str
    category: str
    difficulty: str
    language: str


PROMPT_BANK: list[TopicEntry] = [
    # =========================================================================
    # DEBUGGING (finding and fixing bugs in existing code)
    # =========================================================================

    # Easy
    TopicEntry(
        topic="fix a Python script that crashes on empty input when reading a CSV file",
        category="debugging", difficulty="easy", language="python",
    ),
    TopicEntry(
        topic="fix a Bash script with quoting errors that breaks on filenames with spaces",
        category="debugging", difficulty="easy", language="bash",
    ),
    TopicEntry(
        topic="fix a Node.js script that fails to parse JSON due to encoding issues",
        category="debugging", difficulty="easy", language="nodejs",
    ),

    # Medium
    TopicEntry(
        topic="fix a Python async web scraper with rate limiting and connection pool bugs",
        category="debugging", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="debug a C program with memory corruption in a linked list implementation",
        category="debugging", difficulty="medium", language="c",
    ),
    TopicEntry(
        topic="fix a broken Python Flask API with dependency, routing, and data format bugs",
        category="debugging", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="debug a Go HTTP server with race conditions in shared state access",
        category="debugging", difficulty="medium", language="go",
    ),
    TopicEntry(
        topic="fix a Python unit test suite where fixtures have scoping and teardown bugs",
        category="debugging", difficulty="medium", language="python",
    ),

    # Hard
    TopicEntry(
        topic="debug a multi-threaded Python producer-consumer with deadlocks and data loss",
        category="debugging", difficulty="hard", language="python",
    ),
    TopicEntry(
        topic="fix a C++ program with undefined behavior from iterator invalidation and buffer overflows",
        category="debugging", difficulty="hard", language="cpp",
    ),

    # =========================================================================
    # DATA PROCESSING (ETL, parsing, transformation)
    # =========================================================================

    # Easy
    TopicEntry(
        topic="fix a Python script that incorrectly converts CSV to JSON due to header parsing bugs",
        category="data-processing", difficulty="easy", language="python",
    ),
    TopicEntry(
        topic="fix a Bash script that fails to count and summarize log file entries correctly",
        category="data-processing", difficulty="easy", language="bash",
    ),
    TopicEntry(
        topic="fix a Python script that mangles Unicode text during file encoding conversion",
        category="data-processing", difficulty="easy", language="python",
    ),

    # Medium
    TopicEntry(
        topic="repair a Python data pipeline that silently drops records during CSV transformation",
        category="data-processing", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="fix a Python XML-to-JSON converter with namespace handling and attribute mapping bugs",
        category="data-processing", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="fix a Bash pipeline that corrupts binary data when processing mixed text/binary streams",
        category="data-processing", difficulty="medium", language="bash",
    ),
    TopicEntry(
        topic="fix a Python SQLite migration script with schema versioning and data type bugs",
        category="data-processing", difficulty="medium", language="python",
    ),

    # Hard
    TopicEntry(
        topic="fix a Python streaming JSON parser that loses events under backpressure with malformed input",
        category="data-processing", difficulty="hard", language="python",
    ),
    TopicEntry(
        topic="repair a multi-stage data pipeline with inconsistent date parsing across timezones and locales",
        category="data-processing", difficulty="hard", language="python",
    ),

    # =========================================================================
    # SYSTEM ADMINISTRATION (services, configs, monitoring)
    # =========================================================================

    # Easy
    TopicEntry(
        topic="fix a broken crontab setup script that has syntax errors and wrong time specifications",
        category="system-administration", difficulty="easy", language="bash",
    ),
    TopicEntry(
        topic="fix a Bash script that incorrectly parses /proc filesystem stats for CPU monitoring",
        category="system-administration", difficulty="easy", language="bash",
    ),

    # Medium
    TopicEntry(
        topic="fix a broken log rotation system with incorrect size checks, permissions, and compression",
        category="system-administration", difficulty="medium", language="bash",
    ),
    TopicEntry(
        topic="repair a shell script that manages systemd services with incorrect status parsing",
        category="system-administration", difficulty="medium", language="bash",
    ),
    TopicEntry(
        topic="fix a Python monitoring script with broken metrics collection, alerting thresholds, and stale data",
        category="system-administration", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="fix a broken disk usage analyzer script with incorrect recursive traversal and size calculations",
        category="system-administration", difficulty="medium", language="bash",
    ),

    # Hard
    TopicEntry(
        topic="fix a process supervisor script with broken signal handling, zombie reaping, and restart logic",
        category="system-administration", difficulty="hard", language="bash",
    ),
    TopicEntry(
        topic="debug a broken backup rotation script with race conditions in concurrent rsync and retention policy bugs",
        category="system-administration", difficulty="hard", language="bash",
    ),

    # =========================================================================
    # SOFTWARE ENGINEERING (design patterns, architecture, tooling)
    # =========================================================================

    # Easy
    TopicEntry(
        topic="fix a Python config file parser that mishandles default values and type coercion",
        category="software-engineering", difficulty="easy", language="python",
    ),
    TopicEntry(
        topic="fix a broken Python CLI tool with incorrect argument parsing and missing help text",
        category="software-engineering", difficulty="easy", language="python",
    ),

    # Medium
    TopicEntry(
        topic="fix a Python CLI tool with broken subcommand routing, output formatting, and exit codes",
        category="software-engineering", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="fix a broken Python plugin system with incorrect module loading and hook registration",
        category="software-engineering", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="fix a Python config parser that mishandles nested YAML, environment overrides, and defaults",
        category="software-engineering", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="repair a Python state machine implementation with incorrect transition validation and event handling",
        category="software-engineering", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="fix a broken Python template engine with incorrect variable substitution and escaping",
        category="software-engineering", difficulty="medium", language="python",
    ),

    # Hard
    TopicEntry(
        topic="fix a Python dependency resolver with circular dependency detection and version conflict bugs",
        category="software-engineering", difficulty="hard", language="python",
    ),
    TopicEntry(
        topic="debug a broken Python ORM layer with incorrect query generation, lazy loading, and transaction handling",
        category="software-engineering", difficulty="hard", language="python",
    ),

    # =========================================================================
    # BUILD SYSTEMS (compilation, linking, packaging)
    # =========================================================================

    # Easy
    TopicEntry(
        topic="fix a Makefile with incorrect target dependencies and missing phony declarations",
        category="build-systems", difficulty="easy", language="make",
    ),
    TopicEntry(
        topic="fix a Python setup.py with wrong package discovery and missing dependencies",
        category="build-systems", difficulty="easy", language="python",
    ),

    # Medium
    TopicEntry(
        topic="fix a broken Makefile for a multi-target C project with linking and include path errors",
        category="build-systems", difficulty="medium", language="make",
    ),
    TopicEntry(
        topic="fix broken Maven POM files with dependency conflicts, incorrect plugin configs, and wrong artifact versions",
        category="build-systems", difficulty="medium", language="java",
    ),
    TopicEntry(
        topic="fix a broken CMake project with incorrect library linking, missing find_package, and install rules",
        category="build-systems", difficulty="medium", language="cmake",
    ),
    TopicEntry(
        topic="repair a broken Python package build with incorrect pyproject.toml, missing entry points, and version bugs",
        category="build-systems", difficulty="medium", language="python",
    ),

    # Hard
    TopicEntry(
        topic="fix a multi-stage Docker build with broken layer caching, wrong build args, and missing runtime deps",
        category="build-systems", difficulty="hard", language="docker",
    ),
    TopicEntry(
        topic="debug a broken CI/CD pipeline script with incorrect artifact handling, test parallelization, and caching bugs",
        category="build-systems", difficulty="hard", language="bash",
    ),

    # =========================================================================
    # NETWORKING (protocols, servers, configuration)
    # =========================================================================

    # Easy
    TopicEntry(
        topic="fix a Python socket client that drops messages due to incorrect buffer handling",
        category="networking", difficulty="easy", language="python",
    ),
    TopicEntry(
        topic="fix a broken curl wrapper script with incorrect header and authentication handling",
        category="networking", difficulty="easy", language="bash",
    ),

    # Medium
    TopicEntry(
        topic="fix a broken Nginx reverse proxy config with upstream routing, header forwarding, and SSL issues",
        category="networking", difficulty="medium", language="nginx",
    ),
    TopicEntry(
        topic="fix a broken Python HTTP client with retry logic, timeout handling, and redirect bugs",
        category="networking", difficulty="medium", language="python",
    ),
    TopicEntry(
        topic="debug a broken Docker Compose setup with incorrect networking, port mapping, and service dependencies",
        category="networking", difficulty="medium", language="docker",
    ),
    TopicEntry(
        topic="fix a Python DNS resolver script with incorrect record type handling and cache expiry bugs",
        category="networking", difficulty="medium", language="python",
    ),

    # Hard
    TopicEntry(
        topic="fix a Python TCP proxy with broken connection pooling, half-close handling, and backpressure bugs",
        category="networking", difficulty="hard", language="python",
    ),
    TopicEntry(
        topic="debug a broken webhook receiver with incorrect signature verification, replay protection, and retry handling",
        category="networking", difficulty="hard", language="python",
    ),
]


# Kept for backward compat — empty set, all topics use weighted sampling now
EXCLUDED_TOPICS: set[str] = set()

# Static weight overrides for topics with known issues.
# Weight 1.0 = normal, 0.1 = very unlikely to be selected, 0.0 = never selected.
# Topics not listed default to 1.0.
# These weights reflect structural constraints (Docker-in-Docker, /proc, etc.)
# and historical performance. Updated based on retest results.
TOPIC_WEIGHTS: dict[str, float] = {
    "fix a Python script that crashes on empty input when reading a CSV file": 0.73,
    "fix a Bash script with quoting errors that breaks on filenames with spaces": 0.05,
    "fix a Node.js script that fails to parse JSON due to encoding issues": 0.6,
    "fix a Python async web scraper with rate limiting and connection pool bugs": 0.1,
    "debug a C program with memory corruption in a linked list implementation": 0.1,
    "fix a broken Python Flask API with dependency, routing, and data format bugs": 0.6,
    "debug a Go HTTP server with race conditions in shared state access": 0.1,
    "fix a Python unit test suite where fixtures have scoping and teardown bugs": 0.73,
    "debug a multi-threaded Python producer-consumer with deadlocks and data loss": 0.1,
    "fix a C++ program with undefined behavior from iterator invalidation and buffer overflows": 0.1,
    "fix a Bash script that fails to count and summarize log file entries correctly": 0.2,
    "fix a Bash pipeline that corrupts binary data when processing mixed text/binary streams": 0.2,
    "fix a Python SQLite migration script with schema versioning and data type bugs": 0.57,
    "fix a Python streaming JSON parser that loses events under backpressure with malformed input": 0.1,
    "fix a Bash script that incorrectly parses /proc filesystem stats for CPU monitoring": 0.2,
    "repair a shell script that manages systemd services with incorrect status parsing": 0.5,
    "fix a broken disk usage analyzer script with incorrect recursive traversal and size calculations": 0.8,
    "fix a process supervisor script with broken signal handling, zombie reaping, and restart logic": 0.1,
    "debug a broken backup rotation script with race conditions in concurrent rsync and retention policy bugs": 0.05,
    "fix a broken Python CLI tool with incorrect argument parsing and missing help text": 0.4,
    "repair a Python state machine implementation with incorrect transition validation and event handling": 0.2,
    "debug a broken Python ORM layer with incorrect query generation, lazy loading, and transaction handling": 0.5,
    "fix a Python setup.py with wrong package discovery and missing dependencies": 0.05,
    "fix a broken Makefile for a multi-target C project with linking and include path errors": 0.8,
    "fix broken Maven POM files with dependency conflicts, incorrect plugin configs, and wrong artifact versions": 0.6,
    "fix a broken CMake project with incorrect library linking, missing find_package, and install rules": 0.2,
    "repair a broken Python package build with incorrect pyproject.toml, missing entry points, and version bugs": 0.3,
    "fix a multi-stage Docker build with broken layer caching, wrong build args, and missing runtime deps": 0.05,
    "debug a broken CI/CD pipeline script with incorrect artifact handling, test parallelization, and caching bugs": 0.5,
    "fix a Python socket client that drops messages due to incorrect buffer handling": 0.2,
    "fix a broken curl wrapper script with incorrect header and authentication handling": 0.05,
    "fix a broken Nginx reverse proxy config with upstream routing, header forwarding, and SSL issues": 0.05,
    "fix a broken Python HTTP client with retry logic, timeout handling, and redirect bugs": 0.05,
    "debug a broken Docker Compose setup with incorrect networking, port mapping, and service dependencies": 0.01,
    "fix a Python DNS resolver script with incorrect record type handling and cache expiry bugs": 0.8,
    "fix a Python TCP proxy with broken connection pooling, half-close handling, and backpressure bugs": 0.1,
    "debug a broken webhook receiver with incorrect signature verification, replay protection, and retry handling": 0.4,
}


def select_entries(
    n: int = 10,
    category: str | None = None,
    difficulty: str | None = None,
    language: str | None = None,
    diverse: bool = True,
    seed: int | None = None,
) -> list[TopicEntry]:
    """Select topic entries from the prompt bank (with full metadata).

    Args:
        n: Number of entries to return.
        category: Filter to a specific category.
        difficulty: Filter to a specific difficulty level.
        language: Filter to a specific language.
        diverse: If True, maximize category/difficulty diversity via round-robin.
        seed: Random seed for reproducibility.

    Returns:
        List of TopicEntry objects.
    """
    rng = random.Random(seed)

    pool = list(PROMPT_BANK)  # all topics eligible, weighted by historical performance

    if category:
        pool = [t for t in pool if t.category == category]
    if difficulty:
        pool = [t for t in pool if t.difficulty == difficulty]
    if language:
        pool = [t for t in pool if t.language == language]

    if not pool:
        return []

    def _weight(t: TopicEntry) -> float:
        return TOPIC_WEIGHTS.get(t.topic, 1.0)

    if not diverse or n >= len(pool):
        # Weighted sample without replacement
        selected: list[TopicEntry] = []
        remaining = list(pool)
        for _ in range(min(n, len(remaining))):
            weights = [_weight(t) for t in remaining]
            total_w = sum(weights)
            if total_w == 0:
                break
            chosen = rng.choices(remaining, weights=weights, k=1)[0]
            selected.append(chosen)
            remaining.remove(chosen)
        return selected

    # Round-robin across categories for diversity, weighted within each category
    by_category: dict[str, list[TopicEntry]] = {}
    for t in pool:
        by_category.setdefault(t.category, []).append(t)
    # Sort within each category by weight (highest first) with random tiebreaking
    for entries in by_category.values():
        entries.sort(key=lambda t: (-_weight(t), rng.random()))

    selected = []
    categories = list(by_category.keys())
    rng.shuffle(categories)
    idx = {cat: 0 for cat in categories}

    while len(selected) < n:
        added = False
        for cat in categories:
            if len(selected) >= n:
                break
            entries = by_category[cat]
            # Find next unselected entry, sampling by weight
            remaining_in_cat = entries[idx[cat]:]
            if not remaining_in_cat:
                continue
            weights = [_weight(t) for t in remaining_in_cat]
            total_w = sum(weights)
            if total_w == 0:
                idx[cat] = len(entries)
                continue
            chosen = rng.choices(remaining_in_cat, weights=weights, k=1)[0]
            selected.append(chosen)
            # Move past chosen (and anything before it)
            chosen_idx = entries.index(chosen)
            entries.pop(chosen_idx)
            added = True
        if not added:
            break

    return selected


def select_topics(
    n: int = 10,
    category: str | None = None,
    difficulty: str | None = None,
    language: str | None = None,
    diverse: bool = True,
    seed: int | None = None,
) -> list[str]:
    """Select topic strings from the prompt bank.

    Convenience wrapper around select_entries() that returns just the topic strings.
    """
    entries = select_entries(
        n=n, category=category, difficulty=difficulty,
        language=language, diverse=diverse, seed=seed,
    )
    return [e.topic for e in entries]


def get_category_for_topic(topic: str) -> str | None:
    """Look up a topic's category from the prompt bank. Returns None if not found."""
    for entry in PROMPT_BANK:
        if entry.topic == topic:
            return entry.category
    return None


def get_bank_stats() -> dict:
    """Return summary statistics about the prompt bank."""
    stats: dict = {
        "total": len(PROMPT_BANK),
        "by_category": {},
        "by_difficulty": {},
        "by_language": {},
    }
    for t in PROMPT_BANK:
        stats["by_category"][t.category] = stats["by_category"].get(t.category, 0) + 1
        stats["by_difficulty"][t.difficulty] = stats["by_difficulty"].get(t.difficulty, 0) + 1
        stats["by_language"][t.language] = stats["by_language"].get(t.language, 0) + 1
    return stats
