#!/usr/bin/env python3.12
"""Test surgical adjustment + Opus evaluation on known too_hard tasks.

Copies pre_adj1 snapshots, applies surgical adjustment, validates,
then runs Opus×3 evaluation to see if tasks become learnable.
"""
import shutil
import sys
import os
import time
from pathlib import Path

# Tasks to test (all were too_hard 0/5 in batch 17)
TASKS = [
    {
        "source": "../output/sonnet-batch-17/fix-a-bash-script-with-quoting-errors-that-breaks-on-409544.pre_adj1",
        "topic": "fix a Bash script with quoting errors that breaks on filenames with spaces",
    },
    {
        "source": "../output/sonnet-batch-17/fix-a-python-xml-to-json-converter-with-namespace-20c497.pre_adj1",
        "topic": "fix a Python XML-to-JSON converter with namespace handling and attribute mapping",
    },
    {
        "source": "../output/sonnet-batch-17/fix-a-python-script-that-crashes-on-empty-input-when-0b782c.pre_adj1",
        "topic": "fix a Python script that crashes on empty input when reading a CSV file",
    },
]

OUTPUT_DIR = Path("../output/surgical-adjustment-test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_one(task_info: dict) -> dict:
    """Adjust one task and run functional validation + Opus eval."""
    source = Path(task_info["source"])
    topic = task_info["topic"]
    slug = source.name.split(".pre_adj")[0]  # strip .pre_adj1 suffix

    task_dir = OUTPUT_DIR / slug
    if task_dir.exists():
        shutil.rmtree(task_dir)
    shutil.copytree(source, task_dir)

    # Clean up snapshot artifacts
    for f in task_dir.glob("_*"):
        if f.is_file():
            f.unlink()
    for f in task_dir.glob("validation_attempt_*"):
        f.unlink()

    print(f"\n{'='*70}")
    print(f"TASK: {slug}")
    print(f"{'='*70}")

    # Step 1: Surgical adjustment
    print("\n[Step 1] Surgical difficulty adjustment...")
    from generate import adjust_difficulty
    adj_result = adjust_difficulty(
        topic=topic,
        task_dir=str(task_dir),
        classification="too_hard",
        pass_rate=0.0,
    )
    print(f"  Status: {adj_result['status']}")
    if adj_result["status"] != "success":
        return {"task": slug, "adj_status": adj_result["status"], "eval": None}

    # Step 2: Functional validation
    print("\n[Step 2] Functional validation...")
    sys.path.insert(0, str(Path(__file__).parent.parent / "validator"))
    from docker_validate import docker_validate
    func_result = docker_validate(str(task_dir))
    passed = func_result.get("passed", False)
    print(f"  Passed: {passed}")
    if not passed:
        issues = func_result.get("issues", [])
        for iss in issues:
            print(f"    - {iss}")
        details = func_result.get("details", {})
        for phase, info in details.items():
            if isinstance(info, dict) and info.get("stdout_tail"):
                print(f"  {phase} stdout tail: ...{info['stdout_tail'][-500:]}")
        return {"task": slug, "adj_status": "success", "func_passed": False,
                "issues": issues, "eval": None}

    # Step 3: Opus evaluation (3 trials, skip filters)
    print("\n[Step 3] Opus evaluation (3 trials)...")
    from evaluate import evaluate_task
    eval_result = evaluate_task(
        task_dir=str(task_dir),
        n_trials=3,
        skip_filters=True,
        output_path=str(OUTPUT_DIR / "runs"),
    )
    classification = eval_result.get("classification", "?")
    passes = eval_result.get("passes", 0)
    total = eval_result.get("total", 0)
    print(f"\n  RESULT: {passes}/{total} → {classification}")

    return {
        "task": slug,
        "adj_status": "success",
        "func_passed": True,
        "classification": classification,
        "passes": passes,
        "total": total,
    }


if __name__ == "__main__":
    start = time.time()
    results = []

    for task_info in TASKS:
        source = Path(task_info["source"])
        if not source.exists():
            print(f"SKIP: {source} not found")
            continue
        result = run_one(task_info)
        results.append(result)

    duration = time.time() - start

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        task = r["task"][:60]
        if r.get("eval") is None and not r.get("func_passed"):
            status = f"adj={r['adj_status']}, func=FAIL"
        elif r.get("classification"):
            status = f"{r['passes']}/{r['total']} → {r['classification']}"
        else:
            status = f"adj={r['adj_status']}"
        print(f"  {task:62s} {status}")

    print(f"\nTotal duration: {duration:.0f}s ({duration/60:.1f}min)")
