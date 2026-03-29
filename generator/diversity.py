"""
Diversity analysis for generated task batches (Stretch Goal C).

Analyzes a batch report JSON to assess:
- Category coverage vs. the defined TASK_CATEGORIES
- Language/technology distribution
- Difficulty spread
- Topic uniqueness (detects near-duplicate topics)
- Instruction length distribution (proxy for task complexity)

Can be run standalone on a batch report file or imported for programmatic use.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(__file__))
from config import TASK_CATEGORIES


def _load_batch_report(report_path: str) -> dict:
    """Load a batch report JSON file."""
    with open(report_path) as f:
        return json.load(f)


def _extract_task_metadata(results: list) -> list[dict]:
    """Extract category, difficulty, and instruction from pipeline results.

    Each result has a task_dir; we read task.yaml from there if it exists.
    Falls back to parsing the topic string for basic metadata.
    """
    tasks = []
    for r in results:
        task_dir = r.get("task_dir")
        topic = r.get("topic", "")
        meta = {"topic": topic, "status": r.get("status", "unknown")}

        # Try to read task.yaml for ground truth
        if task_dir:
            yaml_path = Path(task_dir) / "task.yaml"
            if yaml_path.exists():
                try:
                    with open(yaml_path) as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        meta["category"] = data.get("category", "unknown")
                        meta["difficulty"] = data.get("difficulty", "unknown")
                        meta["instruction"] = data.get("instruction", "")
                        meta["tags"] = data.get("tags", [])
                except (yaml.YAMLError, OSError):
                    pass  # task.yaml unreadable — fall back to topic inference

        # Infer language from topic if not in yaml
        if "language" not in meta:
            meta["language"] = _infer_language(topic)

        tasks.append(meta)

    return tasks


def _infer_language(topic: str) -> str:
    """Best-effort language inference from a topic string."""
    topic_lower = topic.lower()
    patterns = [
        ("python", "python"),
        ("bash", "bash"), ("shell", "bash"),
        ("node", "nodejs"), ("javascript", "nodejs"),
        ("go ", "go"), ("golang", "go"),
        ("rust", "rust"),
        ("c++", "cpp"), ("cpp", "cpp"),
        (" c ", "c"), ("c program", "c"),
        ("java", "java"),
        ("makefile", "make"), ("cmake", "cmake"),
        ("docker", "docker"),
        ("nginx", "nginx"),
        ("typescript", "typescript"),
    ]
    for pattern, lang in patterns:
        if pattern in topic_lower:
            return lang
    return "unknown"


def _word_set(text: str) -> set[str]:
    """Extract normalized word set from a string for similarity comparison."""
    return set(re.findall(r"[a-z]+", text.lower()))


def _jaccard_similarity(a: set, b: set) -> float:
    """Compute Jaccard similarity between two sets."""
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def analyze_diversity(
    results: list,
    similarity_threshold: float = 0.7,
) -> dict:
    """Analyze diversity of a batch of generated tasks.

    Args:
        results: List of pipeline result dicts (from batch report).
        similarity_threshold: Jaccard similarity above which two topics
            are flagged as near-duplicates.

    Returns:
        dict with coverage, distribution, and uniqueness analysis.
    """
    tasks = _extract_task_metadata(results)
    successful = [t for t in tasks if t["status"] not in ("generation_failed", "error")]

    # Category coverage
    categories_found = Counter(t.get("category", "unknown") for t in successful)
    categories_expected = set(TASK_CATEGORIES)
    categories_missing = categories_expected - set(categories_found.keys())

    # Difficulty distribution
    difficulties = Counter(t.get("difficulty", "unknown") for t in successful)

    # Language distribution
    languages = Counter(t.get("language", "unknown") for t in successful)

    # Instruction length stats
    instruction_lengths = [
        len(t.get("instruction", "")) for t in successful if t.get("instruction")
    ]
    length_stats = {}
    if instruction_lengths:
        length_stats = {
            "min": min(instruction_lengths),
            "max": max(instruction_lengths),
            "mean": round(sum(instruction_lengths) / len(instruction_lengths)),
            "median": sorted(instruction_lengths)[len(instruction_lengths) // 2],
        }

    # Topic uniqueness: find near-duplicate pairs
    near_duplicates = []
    topic_words = [(t["topic"], _word_set(t["topic"])) for t in successful]
    for i in range(len(topic_words)):
        for j in range(i + 1, len(topic_words)):
            sim = _jaccard_similarity(topic_words[i][1], topic_words[j][1])
            if sim >= similarity_threshold:
                near_duplicates.append({
                    "topic_a": topic_words[i][0],
                    "topic_b": topic_words[j][0],
                    "similarity": round(sim, 3),
                })

    # Coverage score: how well do we cover the expected categories?
    # 1.0 = all categories present, 0.0 = none
    coverage_score = (
        len(categories_expected & set(categories_found.keys())) / len(categories_expected)
        if categories_expected else 1.0
    )

    # Evenness score: how evenly distributed are categories?
    # Uses normalized entropy. 1.0 = perfectly even, 0.0 = all one category.
    evenness_score = _normalized_entropy(list(categories_found.values()))

    return {
        "total_tasks": len(tasks),
        "successful_tasks": len(successful),
        "category_coverage": {
            "found": dict(categories_found),
            "missing": sorted(categories_missing),
            "coverage_score": round(coverage_score, 3),
            "evenness_score": round(evenness_score, 3),
        },
        "difficulty_distribution": dict(difficulties),
        "language_distribution": dict(languages),
        "instruction_length_stats": length_stats,
        "topic_uniqueness": {
            "unique_topics": len(successful) - len(near_duplicates),
            "near_duplicate_pairs": near_duplicates,
        },
    }


def _normalized_entropy(counts: list[int]) -> float:
    """Compute normalized Shannon entropy of a distribution.

    Returns 0.0 for a single-element distribution, 1.0 for perfectly uniform.
    """
    import math

    total = sum(counts)
    if total == 0 or len(counts) <= 1:
        return 0.0

    probs = [c / total for c in counts if c > 0]
    entropy = -sum(p * math.log2(p) for p in probs)
    max_entropy = math.log2(len(probs))

    return entropy / max_entropy if max_entropy > 0 else 0.0


def print_diversity_report(analysis: dict) -> None:
    """Print a human-readable diversity report."""
    print(f"\n{'#'*60}")
    print("DIVERSITY ANALYSIS")
    print(f"{'#'*60}")

    cc = analysis["category_coverage"]
    print(f"\n--- Category Coverage (score: {cc['coverage_score']:.0%}, evenness: {cc['evenness_score']:.0%}) ---")
    for cat, count in sorted(cc["found"].items(), key=lambda x: -x[1]):
        bar = "#" * count
        print(f"  {cat:<25} {count:>3}  {bar}")
    if cc["missing"]:
        print(f"  Missing: {', '.join(cc['missing'])}")

    dd = analysis["difficulty_distribution"]
    print(f"\n--- Difficulty Distribution ---")
    for diff in ["easy", "medium", "hard"]:
        count = dd.get(diff, 0)
        bar = "#" * count
        print(f"  {diff:<10} {count:>3}  {bar}")
    for diff, count in dd.items():
        if diff not in ("easy", "medium", "hard"):
            print(f"  {diff:<10} {count:>3}")

    ld = analysis["language_distribution"]
    print(f"\n--- Language Distribution ---")
    for lang, count in sorted(ld.items(), key=lambda x: -x[1]):
        bar = "#" * count
        print(f"  {lang:<15} {count:>3}  {bar}")

    ls = analysis["instruction_length_stats"]
    if ls:
        print(f"\n--- Instruction Length ---")
        print(f"  Min: {ls['min']}  Max: {ls['max']}  Mean: {ls['mean']}  Median: {ls['median']}")

    tu = analysis["topic_uniqueness"]
    print(f"\n--- Topic Uniqueness ---")
    print(f"  Total: {analysis['successful_tasks']}  Near-duplicates: {len(tu['near_duplicate_pairs'])}")
    for dup in tu["near_duplicate_pairs"]:
        print(f"  [{dup['similarity']:.0%}] \"{dup['topic_a'][:40]}\" ~ \"{dup['topic_b'][:40]}\"")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diversity.py <batch-report.json>")
        print("       python diversity.py <output-dir>  (finds latest report)")
        sys.exit(1)

    path = sys.argv[1]

    # If given a directory, find the latest batch report
    if os.path.isdir(path):
        reports = sorted(Path(path).glob("batch-*-report.json"))
        if not reports:
            print(f"No batch reports found in {path}")
            sys.exit(1)
        path = str(reports[-1])
        print(f"Using latest report: {path}")

    report = _load_batch_report(path)
    analysis = analyze_diversity(report["results"])
    print_diversity_report(analysis)

    # Also save as JSON
    json_out = path.replace("-report.json", "-diversity.json")
    with open(json_out, "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"\nDiversity analysis saved to: {json_out}")
