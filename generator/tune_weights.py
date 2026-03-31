"""Auto-tune TOPIC_WEIGHTS based on historical batch results.

Reads all batch incremental JSONL files and computes per-topic success
rates. Outputs updated weights that can be pasted into prompts.py.

Weight formula:
  base = func_pass_rate * 0.5 + learnable_rate * 0.5
  weight = max(MIN_WEIGHT, base)

Topics with no data keep weight 1.0 (benefit of the doubt).
Topics with data get weights proportional to their success.

Usage:
  python generator/tune_weights.py [--apply]
"""

from __future__ import annotations

import json
import glob
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from prompts import PROMPT_BANK, TOPIC_WEIGHTS

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")

# Floor weight — no topic is ever fully excluded
MIN_WEIGHT = 0.05

# Minimum attempts before we adjust weight (avoid overreacting to 1 sample)
MIN_ATTEMPTS = 2


def compute_topic_stats() -> dict[str, dict]:
    """Aggregate per-topic stats from all batch JSONL files."""
    stats: dict[str, dict] = defaultdict(lambda: {
        "func_pass": 0, "func_fail": 0,
        "learnable": 0, "too_hard": 0, "too_easy": 0,
        "total_evals": 0,
    })

    for jsonl in sorted(glob.glob(os.path.join(OUTPUT_DIR, "*", "batch-*-incremental.jsonl"))):
        for line in open(jsonl):
            try:
                r = json.loads(line)
                topic = r.get("topic", "")
                if not topic:
                    continue
                cl = r.get("classification")
                status = r.get("status", "")
                func = r.get("stages", {}).get("functional", {}).get("passed")

                if func is True:
                    stats[topic]["func_pass"] += 1
                elif "functional" in status:
                    stats[topic]["func_fail"] += 1

                if cl == "learnable":
                    stats[topic]["learnable"] += 1
                    stats[topic]["total_evals"] += 1
                elif cl == "too_hard":
                    stats[topic]["too_hard"] += 1
                    stats[topic]["total_evals"] += 1
                elif cl == "too_easy":
                    stats[topic]["too_easy"] += 1
                    stats[topic]["total_evals"] += 1
            except (json.JSONDecodeError, KeyError):
                pass

    return dict(stats)


def compute_weights(stats: dict[str, dict]) -> dict[str, float]:
    """Compute weights from stats. Returns topic → weight mapping."""
    weights = {}

    for entry in PROMPT_BANK:
        topic = entry.topic
        s = stats.get(topic)

        if not s:
            # No data — keep current weight or default to 1.0
            weights[topic] = TOPIC_WEIGHTS.get(topic, 1.0)
            continue

        func_total = s["func_pass"] + s["func_fail"]
        func_rate = s["func_pass"] / func_total if func_total else 0.5

        eval_total = s["total_evals"]
        learn_rate = s["learnable"] / eval_total if eval_total else 0.0

        total_attempts = func_total + eval_total
        if total_attempts < MIN_ATTEMPTS:
            # Not enough data — blend with current weight
            current = TOPIC_WEIGHTS.get(topic, 1.0)
            weights[topic] = current
            continue

        # Weight = blend of functional pass rate and learnable rate
        # Func rate matters more early (can we even generate valid tasks?)
        # Learnable rate matters more once func validation works
        if func_rate > 0:
            raw = func_rate * 0.4 + learn_rate * 0.6
        else:
            raw = 0.0

        weights[topic] = round(max(MIN_WEIGHT, raw), 2)

    return weights


def main():
    apply = "--apply" in sys.argv

    stats = compute_topic_stats()
    new_weights = compute_weights(stats)

    # Show changes
    print("Topic weight analysis:")
    print(f"{'Topic':<60s} {'Old':>5s} {'New':>5s} {'Func':>8s} {'Learn':>8s}")
    print("-" * 95)

    changes = 0
    for entry in PROMPT_BANK:
        topic = entry.topic
        old_w = TOPIC_WEIGHTS.get(topic, 1.0)
        new_w = new_weights.get(topic, 1.0)
        s = stats.get(topic, {})

        func_total = s.get("func_pass", 0) + s.get("func_fail", 0)
        func_str = f"{s.get('func_pass', 0)}/{func_total}" if func_total else "—"
        eval_total = s.get("total_evals", 0)
        learn_str = f"{s.get('learnable', 0)}/{eval_total}" if eval_total else "—"

        changed = abs(old_w - new_w) > 0.05
        marker = " *" if changed else ""
        if changed:
            changes += 1

        print(f"  {topic[:58]:<58s} {old_w:>5.2f} {new_w:>5.2f} {func_str:>8s} {learn_str:>8s}{marker}")

    print(f"\n{changes} weight changes suggested.")

    if apply:
        # Write updated weights to prompts.py
        print("\nApplying weights to prompts.py...")
        prompts_path = os.path.join(os.path.dirname(__file__), "prompts.py")
        content = open(prompts_path).read()

        # Build new TOPIC_WEIGHTS dict string
        lines = ["TOPIC_WEIGHTS: dict[str, float] = {"]
        for entry in PROMPT_BANK:
            topic = entry.topic
            w = new_weights.get(topic, 1.0)
            if w != 1.0:
                lines.append(f'    "{topic}": {w},')
        lines.append("}")
        new_block = "\n".join(lines)

        # Replace existing TOPIC_WEIGHTS block
        import re
        pattern = r"TOPIC_WEIGHTS: dict\[str, float\] = \{[^}]*\}"
        if re.search(pattern, content, re.DOTALL):
            content = re.sub(pattern, new_block, content, flags=re.DOTALL)
            with open(prompts_path, "w") as f:
                f.write(content)
            print(f"Updated {changes} weights in prompts.py")
        else:
            print("ERROR: Could not find TOPIC_WEIGHTS block in prompts.py")
    else:
        print("\nRun with --apply to write changes to prompts.py")


if __name__ == "__main__":
    main()
