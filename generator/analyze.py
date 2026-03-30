"""
Post-classification task analysis — extracts features from tasks and identifies
patterns that correlate with learnability.

Analyzes: bug types (from diff), test diagnostic quality, code structure,
instruction specificity, diff locality, and language. Groups by classification
to surface actionable patterns for prompt tuning.

Usage:
    # Analyze all tasks in a directory (reads classification from batch reports)
    python3.12 generator/analyze.py output/sonnet-batch-3/

    # Analyze specific tasks with explicit classifications
    python3.12 generator/analyze.py --learnable examples-opus/debug-c-linked-list-memory-corruption \
        --too-hard examples/broken-flask-api

    # Analyze from a batch report
    python3.12 generator/analyze.py --batch-report output/sonnet-batch-3/batch-*-report.json
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validator"))
from validate import _parse_solution_files, analyze_solution_diff


# ── Bug type classification from diff hunks ──────────────────────────────────

def _classify_hunk(removed_lines: list[str], added_lines: list[str]) -> str:
    """Classify a diff hunk into a bug type category."""
    removed = "\n".join(removed_lines).strip()
    added = "\n".join(added_lines).strip()

    if not removed and added:
        return "missing_code"
    if removed and not added:
        return "extra_code"

    # Single-line changes — most classifiable
    if len(removed_lines) == 1 and len(added_lines) == 1:
        r, a = removed_lines[0].strip(), added_lines[0].strip()
        return _classify_single_line_change(r, a)

    # Multi-line: check if it's mostly the same with small changes
    if abs(len(removed_lines) - len(added_lines)) <= 1:
        types = []
        for rl, al in zip(removed_lines, added_lines):
            types.append(_classify_single_line_change(rl.strip(), al.strip()))
        # Return the most common non-"other" type
        non_other = [t for t in types if t != "logic_change"]
        if non_other:
            return max(set(non_other), key=non_other.count)

    return "logic_change"


def _classify_single_line_change(removed: str, added: str) -> str:
    """Classify a single-line diff into a bug type."""
    # Off-by-one: < vs <=, > vs >=, +1/-1, range boundary
    if re.search(r"[<>]=?", removed) and re.search(r"[<>]=?", added):
        r_ops = set(re.findall(r"[<>]=?", removed))
        a_ops = set(re.findall(r"[<>]=?", added))
        if r_ops != a_ops:
            return "off_by_one"

    # Check for +1/-1 differences (literal numbers or added/removed offsets)
    r_nums = re.findall(r"[-+]?\d+", removed)
    a_nums = re.findall(r"[-+]?\d+", added)
    if r_nums and a_nums and len(r_nums) == len(a_nums):
        diffs = [abs(int(a) - int(r)) for r, a in zip(r_nums, a_nums) if r != a]
        if diffs and all(d <= 1 for d in diffs):
            return "off_by_one"
    # Also catch n vs n-1, n vs n+1, i vs i-1 patterns
    if re.search(r"\w+\s*[-+]\s*1", added) and not re.search(r"\w+\s*[-+]\s*1", removed):
        return "off_by_one"
    if re.search(r"\w+\s*[-+]\s*1", removed) and not re.search(r"\w+\s*[-+]\s*1", added):
        return "off_by_one"

    # Wrong operator: +/-, *//, and/or, ==/!=
    ops_pattern = r"[\+\-\*\/\%]|==|!=|<=|>=|<<|>>|\band\b|\bor\b|\bnot\b"
    r_ops = re.findall(ops_pattern, removed)
    a_ops = re.findall(ops_pattern, added)
    if r_ops != a_ops and _lines_similar(removed, added, threshold=0.5):
        return "wrong_operator"

    # Wrong variable: single identifier swap in otherwise identical line
    r_ids = re.findall(r"\b[a-zA-Z_]\w*\b", removed)
    a_ids = re.findall(r"\b[a-zA-Z_]\w*\b", added)
    if len(r_ids) == len(a_ids):
        id_diffs = sum(1 for r, a in zip(r_ids, a_ids) if r != a)
        if id_diffs == 1:
            return "wrong_variable"
        if id_diffs == 2 and _lines_similar(removed, added, threshold=0.85):
            return "swapped_arguments"

    # Bad constant/default: literal value change
    r_strs = re.findall(r"['\"][^'\"]*['\"]", removed)
    a_strs = re.findall(r"['\"][^'\"]*['\"]", added)
    if r_strs != a_strs and _lines_similar(removed, added, threshold=0.4):
        return "wrong_constant"

    if r_nums != a_nums and _lines_similar(removed, added, threshold=0.4):
        return "wrong_constant"

    # Missing edge case: added conditional/check
    if any(kw in added and kw not in removed for kw in
           ["if ", "elif ", "else:", "try:", "except", "not ", "is None"]):
        return "missing_edge_case"

    return "logic_change"


def _lines_similar(a: str, b: str, threshold: float = 0.7) -> bool:
    """Check if two lines are structurally similar (Jaccard on tokens)."""
    a_tokens = set(re.findall(r"\S+", a))
    b_tokens = set(re.findall(r"\S+", b))
    if not a_tokens or not b_tokens:
        return False
    intersection = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    return (intersection / union) >= threshold


def extract_bug_types(task_dir: str) -> list[dict]:
    """Extract and classify bugs from the solution diff.

    Returns a list of dicts with: type, removed_lines, added_lines, filename.
    """
    task_path = Path(task_dir)
    solution_path = task_path / "solution.sh"
    if not solution_path.exists():
        return []

    solution_files = _parse_solution_files(solution_path.read_text())
    if not solution_files:
        return []

    import difflib
    bugs: list[dict] = []
    infra = {"Dockerfile", "docker-compose.yaml", "run-tests.sh", "task.yaml"}

    for filename, fixed_content in solution_files.items():
        if filename in infra or filename.startswith("test_"):
            continue

        buggy_path = _find_source_file(task_path, filename)
        if buggy_path is None:
            continue

        buggy_lines = buggy_path.read_text().splitlines(keepends=True)
        fixed_lines = fixed_content.splitlines(keepends=True)

        diff = list(difflib.unified_diff(buggy_lines, fixed_lines, n=0))

        # Parse hunks
        current_removed: list[str] = []
        current_added: list[str] = []

        def flush_hunk():
            if current_removed or current_added:
                bug_type = _classify_hunk(current_removed, current_added)
                bugs.append({
                    "type": bug_type,
                    "filename": filename,
                    "removed": [l.rstrip("\n") for l in current_removed],
                    "added": [l.rstrip("\n") for l in current_added],
                })

        for line in diff:
            if line.startswith("@@"):
                flush_hunk()
                current_removed = []
                current_added = []
            elif line.startswith("-") and not line.startswith("---"):
                current_removed.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                current_added.append(line[1:])

        flush_hunk()

    return bugs


# ── Test diagnostic quality ──────────────────────────────────────────────────

def analyze_tests(task_dir: str) -> dict:
    """Analyze test file quality and diagnostic potential.

    Returns dict with: test_count, has_docstrings, assertion_types,
    uses_subprocess, descriptive_names, avg_assertions_per_test.
    """
    task_path = Path(task_dir)
    tests_dir = task_path / "tests"
    if not tests_dir.is_dir():
        return {"test_count": 0}

    test_files = list(tests_dir.glob("*.py"))
    if not test_files:
        return {"test_count": 0}

    total_tests = 0
    total_assertions = 0
    has_docstrings = 0
    descriptive_names = 0
    assertion_types: dict[str, int] = {}
    uses_subprocess = False

    for tf in test_files:
        content = tf.read_text()
        if "subprocess" in content:
            uses_subprocess = True

        # Parse test functions
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                total_tests += 1

                # Check for docstring
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    has_docstrings += 1

                # Descriptive name (more than just test_1, test_foo)
                name_words = node.name.replace("test_", "").split("_")
                if len(name_words) >= 2:
                    descriptive_names += 1

                # Count and classify assertions
                test_assertions = 0
                for child in ast.walk(node):
                    if isinstance(child, ast.Assert):
                        test_assertions += 1
                        atype = _classify_assertion(child)
                        assertion_types[atype] = assertion_types.get(atype, 0) + 1
                    elif (isinstance(child, ast.Call)
                          and isinstance(child.func, ast.Attribute)
                          and child.func.attr.startswith("assert")):
                        test_assertions += 1
                        assertion_types[child.func.attr] = assertion_types.get(
                            child.func.attr, 0) + 1

                total_assertions += test_assertions

    return {
        "test_count": total_tests,
        "has_docstrings": has_docstrings,
        "descriptive_names": descriptive_names,
        "avg_assertions_per_test": round(total_assertions / max(total_tests, 1), 1),
        "assertion_types": assertion_types,
        "uses_subprocess": uses_subprocess,
    }


def _classify_assertion(node: ast.Assert) -> str:
    """Classify an assert statement by what it checks."""
    test = node.test
    if isinstance(test, ast.Compare):
        if any(isinstance(op, (ast.Eq, ast.NotEq)) for op in test.ops):
            return "equality"
        if any(isinstance(op, (ast.In, ast.NotIn)) for op in test.ops):
            return "membership"
        return "comparison"
    if isinstance(test, ast.Call):
        if isinstance(test.func, ast.Name):
            if test.func.id == "isinstance":
                return "type_check"
        return "function_call"
    if isinstance(test, ast.BoolOp):
        return "compound"
    return "boolean"


# ── Code structure metrics ───────────────────────────────────────────────────

def analyze_code_structure(task_dir: str) -> dict:
    """Analyze source code structure (Python files only for AST parsing).

    Returns: function_count, class_count, max_nesting, import_count,
    total_loc, language, source_files.
    """
    task_path = Path(task_dir)
    infra = {"Dockerfile", "docker-compose.yaml", "run-tests.sh", "task.yaml",
             "solution.sh", "docker-compose.yml", "requirements.txt"}

    source_files: list[dict] = []
    total_loc = 0
    total_functions = 0
    total_classes = 0
    max_nesting = 0
    import_count = 0
    language = "unknown"

    for f in task_path.iterdir():
        if not f.is_file() or f.name in infra or f.name.startswith("."):
            continue
        if f.suffix in (".py", ".c", ".h", ".go", ".js", ".ts", ".sh", ".bash",
                        ".rb", ".rs", ".java"):
            if "test" in f.name.lower():
                continue

            content = f.read_text(errors="replace")
            loc = len([l for l in content.splitlines() if l.strip()])
            total_loc += loc

            lang = _detect_language(f.suffix)
            if language == "unknown":
                language = lang

            file_info = {"name": f.name, "loc": loc, "language": lang}

            # Python-specific AST analysis
            if f.suffix == ".py":
                try:
                    tree = ast.parse(content)
                    funcs = sum(1 for n in ast.walk(tree)
                                if isinstance(n, ast.FunctionDef))
                    classes = sum(1 for n in ast.walk(tree)
                                 if isinstance(n, ast.ClassDef))
                    imports = sum(1 for n in ast.walk(tree)
                                 if isinstance(n, (ast.Import, ast.ImportFrom)))
                    nesting = _max_nesting_depth(tree)
                    total_functions += funcs
                    total_classes += classes
                    import_count += imports
                    max_nesting = max(max_nesting, nesting)
                    file_info.update({
                        "functions": funcs, "classes": classes,
                        "imports": imports, "max_nesting": nesting,
                    })
                except SyntaxError:
                    pass

            source_files.append(file_info)

    # Also check subdirectories (but not tests/)
    for subdir in task_path.iterdir():
        if subdir.is_dir() and subdir.name not in ("tests", "inputs", "__pycache__",
                                                     "test_files", ".git"):
            for f in subdir.rglob("*"):
                if f.is_file() and f.suffix in (".py", ".c", ".h", ".go", ".js",
                                                  ".sh", ".bash"):
                    if "test" in f.name.lower():
                        continue
                    content = f.read_text(errors="replace")
                    loc = len([l for l in content.splitlines() if l.strip()])
                    total_loc += loc
                    source_files.append({
                        "name": str(f.relative_to(task_path)),
                        "loc": loc,
                        "language": _detect_language(f.suffix),
                    })

    return {
        "source_files": source_files,
        "source_file_count": len(source_files),
        "total_loc": total_loc,
        "function_count": total_functions,
        "class_count": total_classes,
        "max_nesting": max_nesting,
        "import_count": import_count,
        "language": language,
    }


def _detect_language(suffix: str) -> str:
    return {
        ".py": "python", ".c": "c", ".h": "c", ".go": "go",
        ".js": "javascript", ".ts": "typescript", ".sh": "bash",
        ".bash": "bash", ".rb": "ruby", ".rs": "rust", ".java": "java",
    }.get(suffix, "unknown")


def _max_nesting_depth(tree: ast.AST, depth: int = 0) -> int:
    """Calculate maximum nesting depth of control flow in an AST."""
    max_depth = depth
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With,
                             ast.Try, ast.FunctionDef, ast.ClassDef)):
            max_depth = max(max_depth, _max_nesting_depth(node, depth + 1))
        else:
            max_depth = max(max_depth, _max_nesting_depth(node, depth))
    return max_depth


# ── Instruction analysis ─────────────────────────────────────────────────────

def analyze_instruction(task_dir: str) -> dict:
    """Analyze the task instruction for length and specificity.

    Returns: word_count, char_count, mentions_files, mentions_functions,
    mentions_bugs, specificity (low/medium/high).
    """
    import yaml as _yaml

    task_path = Path(task_dir) / "task.yaml"
    if not task_path.exists():
        return {"word_count": 0, "specificity": "unknown"}

    try:
        with open(task_path) as f:
            data = _yaml.safe_load(f)
    except Exception:
        return {"word_count": 0, "specificity": "unknown"}

    instruction = data.get("instruction", "")
    words = instruction.split()
    word_count = len(words)

    # Check for specific references
    mentions_files = bool(re.search(r"\.\w{1,4}\b", instruction))  # file extensions
    mentions_functions = bool(re.search(r"\w+\(\)", instruction))  # function()
    mentions_bugs = bool(re.search(
        r"\b(bug|error|fix|wrong|incorrect|broken|issue)\b", instruction, re.I))
    mentions_specific_behavior = bool(re.search(
        r"\b(should|must|expected|returns?|outputs?)\b", instruction, re.I))

    specificity_score = sum([
        mentions_files, mentions_functions,
        mentions_specific_behavior, word_count > 50,
    ])
    specificity = "low" if specificity_score <= 1 else (
        "high" if specificity_score >= 3 else "medium")

    return {
        "word_count": word_count,
        "char_count": len(instruction),
        "mentions_files": mentions_files,
        "mentions_functions": mentions_functions,
        "mentions_bugs": mentions_bugs,
        "mentions_specific_behavior": mentions_specific_behavior,
        "specificity": specificity,
    }


# ── Diff locality ────────────────────────────────────────────────────────────

def analyze_diff_locality(task_dir: str) -> dict:
    """Analyze how spread out or clustered the bugs are within source files.

    Returns: spread_ratio (0=clustered, 1=evenly spread), max_gap_lines,
    avg_gap_lines.
    """
    task_path = Path(task_dir)
    solution_path = task_path / "solution.sh"
    if not solution_path.exists():
        return {}

    solution_files = _parse_solution_files(solution_path.read_text())
    if not solution_files:
        return {}

    import difflib
    infra = {"Dockerfile", "docker-compose.yaml", "run-tests.sh", "task.yaml"}

    all_hunk_positions: list[int] = []
    total_lines = 0

    for filename, fixed_content in solution_files.items():
        if filename in infra or filename.startswith("test_"):
            continue

        buggy_path = _find_source_file(task_path, filename)
        if buggy_path is None:
            continue

        buggy_lines = buggy_path.read_text().splitlines(keepends=True)
        fixed_lines = fixed_content.splitlines(keepends=True)
        total_lines = max(total_lines, len(buggy_lines))

        diff = list(difflib.unified_diff(buggy_lines, fixed_lines, n=0))
        for line in diff:
            if line.startswith("@@"):
                # Parse hunk header: @@ -start,count +start,count @@
                match = re.search(r"@@ -(\d+)", line)
                if match:
                    all_hunk_positions.append(int(match.group(1)))

    if len(all_hunk_positions) < 2:
        return {"spread_ratio": 0.0, "max_gap_lines": 0, "avg_gap_lines": 0}

    all_hunk_positions.sort()
    gaps = [all_hunk_positions[i+1] - all_hunk_positions[i]
            for i in range(len(all_hunk_positions) - 1)]

    # spread_ratio: how much of the file is covered between first and last bug
    span = all_hunk_positions[-1] - all_hunk_positions[0]
    spread_ratio = round(span / max(total_lines, 1), 2)

    return {
        "spread_ratio": spread_ratio,
        "max_gap_lines": max(gaps) if gaps else 0,
        "avg_gap_lines": round(sum(gaps) / len(gaps), 1) if gaps else 0,
    }


# ── Full task analysis ───────────────────────────────────────────────────────

def analyze_task(task_dir: str) -> dict:
    """Run all analyses on a single task directory.

    Returns a dict with all extracted features.
    """
    diff = analyze_solution_diff(task_dir)
    bugs = extract_bug_types(task_dir)
    tests = analyze_tests(task_dir)
    structure = analyze_code_structure(task_dir)
    instruction = analyze_instruction(task_dir)
    locality = analyze_diff_locality(task_dir)

    bug_type_counts: dict[str, int] = {}
    for b in bugs:
        bug_type_counts[b["type"]] = bug_type_counts.get(b["type"], 0) + 1

    return {
        "task_dir": task_dir,
        "task_name": Path(task_dir).name,
        "diff": {k: v for k, v in diff.items() if k != "warnings"},
        "diff_warnings": diff.get("warnings", []),
        "bugs": bugs,
        "bug_type_summary": bug_type_counts,
        "bug_count": len(bugs),
        "tests": tests,
        "structure": structure,
        "instruction": instruction,
        "locality": locality,
    }


# ── Cross-classification pattern analysis ────────────────────────────────────

def analyze_patterns(
    classified_tasks: dict[str, list[dict]],
) -> dict:
    """Analyze patterns across classification groups.

    Args:
        classified_tasks: mapping of classification -> list of analysis dicts

    Returns summary with per-group averages and notable differences.
    """
    patterns: dict[str, dict] = {}

    for classification, tasks in classified_tasks.items():
        if not tasks:
            continue

        n = len(tasks)
        avg = lambda vals: round(sum(vals) / len(vals), 1) if vals else 0

        bug_counts = [t["bug_count"] for t in tasks]
        locs = [t["structure"]["total_loc"] for t in tasks]
        file_counts = [t.get("diff", {}).get("files_changed", 0) for t in tasks]
        test_counts = [t["tests"].get("test_count", 0) for t in tasks]
        hunks = [t.get("diff", {}).get("total_hunks", 0) for t in tasks]
        lines_changed = [t.get("diff", {}).get("total_lines_changed", 0) for t in tasks]
        spread_ratios = [t["locality"].get("spread_ratio", 0) for t in tasks
                         if t["locality"]]
        word_counts = [t["instruction"].get("word_count", 0) for t in tasks]

        # Aggregate bug types across tasks
        all_bug_types: dict[str, int] = {}
        for t in tasks:
            for btype, count in t["bug_type_summary"].items():
                all_bug_types[btype] = all_bug_types.get(btype, 0) + count

        # Languages
        languages = [t["structure"]["language"] for t in tasks]
        lang_counts: dict[str, int] = {}
        for lang in languages:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

        patterns[classification] = {
            "count": n,
            "avg_bug_count": avg(bug_counts),
            "avg_loc": avg(locs),
            "avg_files_changed": avg(file_counts),
            "avg_test_count": avg(test_counts),
            "avg_hunks": avg(hunks),
            "avg_lines_changed": avg(lines_changed),
            "avg_spread_ratio": avg(spread_ratios),
            "avg_instruction_words": avg(word_counts),
            "bug_type_distribution": all_bug_types,
            "languages": lang_counts,
        }

    # Generate findings
    findings: list[str] = []
    if "learnable" in patterns and "too_hard" in patterns:
        l, h = patterns["learnable"], patterns["too_hard"]
        if h["avg_bug_count"] > l["avg_bug_count"] + 1:
            findings.append(
                f"Too-hard tasks average {h['avg_bug_count']} bugs vs "
                f"{l['avg_bug_count']} for learnable — reduce bug count"
            )
        if h["avg_loc"] > l["avg_loc"] * 1.3:
            findings.append(
                f"Too-hard tasks average {h['avg_loc']} LOC vs "
                f"{l['avg_loc']} for learnable — reduce code size"
            )
        if h["avg_files_changed"] > l["avg_files_changed"] + 0.5:
            findings.append(
                f"Too-hard tasks change {h['avg_files_changed']} files vs "
                f"{l['avg_files_changed']} for learnable — keep bugs in fewer files"
            )
        if h["avg_lines_changed"] > l["avg_lines_changed"] * 1.5:
            findings.append(
                f"Too-hard solutions change {h['avg_lines_changed']} lines vs "
                f"{l['avg_lines_changed']} for learnable — simpler fixes needed"
            )

        # Bug type differences
        l_types = l["bug_type_distribution"]
        h_types = h["bug_type_distribution"]
        l_total = max(sum(l_types.values()), 1)
        h_total = max(sum(h_types.values()), 1)
        for btype in set(list(l_types.keys()) + list(h_types.keys())):
            l_pct = l_types.get(btype, 0) / l_total
            h_pct = h_types.get(btype, 0) / h_total
            if h_pct > l_pct + 0.15:
                findings.append(
                    f"'{btype}' bugs are {h_pct:.0%} of too-hard vs "
                    f"{l_pct:.0%} of learnable — this bug type may be too difficult"
                )
            elif l_pct > h_pct + 0.15:
                findings.append(
                    f"'{btype}' bugs are {l_pct:.0%} of learnable vs "
                    f"{h_pct:.0%} of too-hard — this bug type works well"
                )

    if "learnable" in patterns and "too_easy" in patterns:
        l, e = patterns["learnable"], patterns["too_easy"]
        if e["avg_bug_count"] < l["avg_bug_count"] - 1:
            findings.append(
                f"Too-easy tasks average {e['avg_bug_count']} bugs vs "
                f"{l['avg_bug_count']} for learnable — need more bugs"
            )

    return {
        "per_group": patterns,
        "findings": findings,
    }


def _find_source_file(task_path: Path, filename: str) -> Path | None:
    """Find a source file in the task directory."""
    candidate = task_path / filename
    if candidate.exists():
        return candidate
    for path in task_path.rglob(filename):
        if "tests" not in path.parts and path.is_file():
            return path
    return None


# ── CLI ──────────────────────────────────────────────────────────────────────

def _print_task_summary(analysis: dict, classification: str | None = None) -> None:
    """Print a human-readable summary of a single task analysis."""
    name = analysis["task_name"]
    cls_label = f" [{classification}]" if classification else ""
    print(f"\n{'=' * 60}")
    print(f"  {name}{cls_label}")
    print(f"{'=' * 60}")

    s = analysis["structure"]
    d = analysis.get("diff", {})
    t = analysis["tests"]
    inst = analysis["instruction"]
    loc = analysis["locality"]

    print(f"  Language: {s['language']}  |  LOC: {s['total_loc']}  |  "
          f"Files: {s['source_file_count']}  |  Functions: {s['function_count']}")
    print(f"  Tests: {t.get('test_count', 0)}  |  "
          f"Avg assertions/test: {t.get('avg_assertions_per_test', 0)}  |  "
          f"Descriptive names: {t.get('descriptive_names', 0)}/{t.get('test_count', 0)}")
    print(f"  Instruction: {inst.get('word_count', 0)} words  |  "
          f"Specificity: {inst.get('specificity', '?')}")

    if d:
        print(f"  Diff: {d.get('files_changed', 0)} file(s), "
              f"{d.get('total_hunks', 0)} hunks, "
              f"{d.get('total_lines_changed', 0)} lines changed")
    if loc:
        print(f"  Locality: spread={loc.get('spread_ratio', 0):.2f}  "
              f"avg_gap={loc.get('avg_gap_lines', 0)} lines")

    if analysis["bug_type_summary"]:
        types_str = ", ".join(f"{k}: {v}" for k, v in
                              sorted(analysis["bug_type_summary"].items(),
                                     key=lambda x: -x[1]))
        print(f"  Bug types: {types_str}")

    if analysis["diff_warnings"]:
        for w in analysis["diff_warnings"]:
            print(f"  ⚠ {w}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze classified tasks to find learnability patterns.",
    )
    parser.add_argument(
        "task_dirs", nargs="*",
        help="Task directories to analyze (classification inferred or unknown)",
    )
    parser.add_argument(
        "--learnable", nargs="*", default=[],
        help="Task directories classified as learnable",
    )
    parser.add_argument(
        "--too-hard", nargs="*", default=[],
        help="Task directories classified as too_hard",
    )
    parser.add_argument(
        "--too-easy", nargs="*", default=[],
        help="Task directories classified as too_easy",
    )
    parser.add_argument(
        "--batch-report",
        help="Path to a batch report JSON (reads classifications from it)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw JSON instead of human-readable summary",
    )

    args = parser.parse_args()

    classified: dict[str, list[dict]] = {
        "learnable": [], "too_hard": [], "too_easy": [], "unclassified": [],
    }

    # Load from batch report
    if args.batch_report:
        with open(args.batch_report) as f:
            report = json.load(f)
        for result in report.get("results", []):
            task_dir = result.get("task_dir")
            cls = result.get("classification") or "unclassified"
            if task_dir and Path(task_dir).is_dir():
                analysis = analyze_task(task_dir)
                classified.setdefault(cls, []).append(analysis)
                if not args.json:
                    _print_task_summary(analysis, cls)

    # Load from explicit classification flags
    for task_dir in args.learnable:
        analysis = analyze_task(task_dir)
        classified["learnable"].append(analysis)
        if not args.json:
            _print_task_summary(analysis, "learnable")

    for task_dir in args.too_hard:
        analysis = analyze_task(task_dir)
        classified["too_hard"].append(analysis)
        if not args.json:
            _print_task_summary(analysis, "too_hard")

    for task_dir in args.too_easy:
        analysis = analyze_task(task_dir)
        classified["too_easy"].append(analysis)
        if not args.json:
            _print_task_summary(analysis, "too_easy")

    # Load unclassified
    for task_dir in (args.task_dirs or []):
        analysis = analyze_task(task_dir)
        classified["unclassified"].append(analysis)
        if not args.json:
            _print_task_summary(analysis, None)

    # Cross-group analysis (only if we have classified tasks)
    has_classified = any(
        classified[k] for k in ("learnable", "too_hard", "too_easy")
    )
    if has_classified:
        # Remove empty groups
        classified = {k: v for k, v in classified.items() if v}
        patterns = analyze_patterns(classified)

        if args.json:
            print(json.dumps({"tasks": classified, "patterns": patterns}, indent=2,
                             default=str))
        else:
            print(f"\n{'=' * 60}")
            print("  CROSS-GROUP ANALYSIS")
            print(f"{'=' * 60}")

            for group, stats in patterns["per_group"].items():
                print(f"\n  [{group}] ({stats['count']} tasks)")
                print(f"    Avg bugs: {stats['avg_bug_count']}  |  "
                      f"Avg LOC: {stats['avg_loc']}  |  "
                      f"Avg files: {stats['avg_files_changed']}")
                print(f"    Avg hunks: {stats['avg_hunks']}  |  "
                      f"Avg lines changed: {stats['avg_lines_changed']}")
                print(f"    Avg spread: {stats['avg_spread_ratio']}  |  "
                      f"Avg instruction: {stats['avg_instruction_words']} words")
                if stats["bug_type_distribution"]:
                    total = sum(stats["bug_type_distribution"].values())
                    types_str = ", ".join(
                        f"{k}: {v}/{total} ({v/total:.0%})"
                        for k, v in sorted(
                            stats["bug_type_distribution"].items(),
                            key=lambda x: -x[1])
                    )
                    print(f"    Bug types: {types_str}")

            if patterns["findings"]:
                print(f"\n  FINDINGS:")
                for i, finding in enumerate(patterns["findings"], 1):
                    print(f"    {i}. {finding}")
    elif args.json:
        all_analyses = []
        for group_tasks in classified.values():
            all_analyses.extend(group_tasks)
        print(json.dumps(all_analyses, indent=2, default=str))


if __name__ == "__main__":
    main()
