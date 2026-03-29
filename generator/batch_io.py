"""
Lightweight batch I/O helpers — no external dependencies.

Extracted from batch.py so they can be imported by tests without pulling
in the openai / pydantic chain that batch.py requires at module level.
"""

from __future__ import annotations

import json
import os


def save_meta(meta_path: str, batch_id: str, topics: list, seed: int | None) -> None:
    """Persist batch metadata so a crashed run can be fully resumed."""
    with open(meta_path, "w") as f:
        json.dump({"batch_id": batch_id, "topics": topics, "seed": seed}, f, indent=2)


def load_meta(meta_path: str) -> dict | None:
    """Load batch metadata; returns None if file is missing."""
    if not os.path.exists(meta_path):
        return None
    with open(meta_path) as f:
        return json.load(f)


def load_incremental(incremental_path: str) -> tuple[list[dict], set[str]]:
    """Load completed results from an incremental JSONL file.

    Returns (results_list, completed_topics_set).
    Silently skips malformed lines so a partial final write doesn't block resume.
    """
    results: list[dict] = []
    completed: set[str] = set()
    if not os.path.exists(incremental_path):
        return results, completed
    with open(incremental_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                result = json.loads(line)
                results.append(result)
                if topic := result.get("topic"):
                    completed.add(topic)
            except json.JSONDecodeError:
                pass  # partial write on last line — ignore
    return results, completed


def resolve_resume(
    resume_from: str, batch_output_dir: str
) -> tuple[str, str, str]:
    """Resolve a resume target to (batch_id, meta_path, incremental_path).

    resume_from may be:
      - "auto"          → pick the most recently modified incomplete batch
      - a batch ID      → e.g. "20240101-120000"
      - a file path     → path to a *-incremental.jsonl or *-meta.json file
    """
    if resume_from == "auto":
        candidates = sorted(
            (
                p for p in os.listdir(batch_output_dir)
                if p.endswith("-incremental.jsonl")
            ),
            key=lambda p: os.path.getmtime(os.path.join(batch_output_dir, p)),
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(
                f"No incomplete batches found in {batch_output_dir}"
            )
        resume_from = (
            candidates[0]
            .removeprefix("batch-")
            .removesuffix("-incremental.jsonl")
        )

    # Normalise file paths to a batch ID
    if os.path.isfile(resume_from):
        base = os.path.basename(resume_from)
        resolved_dir = os.path.dirname(os.path.abspath(resume_from))
        for suffix in ("-incremental.jsonl", "-meta.json"):
            if base.endswith(suffix):
                resume_from = base.removeprefix("batch-").removesuffix(suffix)
                batch_output_dir = resolved_dir
                break

    batch_id = resume_from
    meta_path = os.path.join(batch_output_dir, f"batch-{batch_id}-meta.json")
    incremental_path = os.path.join(
        batch_output_dir, f"batch-{batch_id}-incremental.jsonl"
    )

    if not os.path.exists(incremental_path) and not os.path.exists(meta_path):
        raise FileNotFoundError(
            f"No resume files found for batch '{batch_id}' in {batch_output_dir}"
        )

    return batch_id, meta_path, incremental_path
