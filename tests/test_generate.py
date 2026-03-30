"""Tests for generator/generate.py (_parse_response, select_examples) and config.py (_slugify)."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from config import _slugify, _SLUG_MAX_LEN, _SLUG_HASH_LEN
from generate import (
    SYSTEM_PROMPT, SYSTEM_PROMPT_B, INSTRUCTION_RULE, _format_prompt,
    _build_user_prompt, _parse_response, select_examples, _score_example,
)


# ---------------------------------------------------------------------------
# Existing tests (system prompt + user prompt)
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    """Tests for the system prompt."""

    def test_contains_critical_rules(self):
        assert "CRITICAL RULES" in SYSTEM_PROMPT

    def test_contains_output_format(self):
        assert "OUTPUT FORMAT" in SYSTEM_PROMPT

    def test_targets_learnable_range(self):
        assert "1-3 out of 5" in SYSTEM_PROMPT

    def test_mentions_solve_rate(self):
        assert "40-60%" in SYSTEM_PROMPT

    def test_mentions_independently_discoverable_bugs(self):
        assert "3-4 bugs" in SYSTEM_PROMPT
        assert "independently discoverable" in SYSTEM_PROMPT

    def test_requires_all_files(self):
        assert "task.yaml" in SYSTEM_PROMPT
        assert "Dockerfile" in SYSTEM_PROMPT
        assert "run-tests.sh" in SYSTEM_PROMPT
        assert "solution.sh" in SYSTEM_PROMPT
        assert "test_outputs.py" in SYSTEM_PROMPT


class TestFormatPrompt:
    """Tests for _format_prompt with instruction rule placeholders."""

    def test_format_prompt_produces_valid_string(self):
        for variant, template in [("A", SYSTEM_PROMPT), ("B", SYSTEM_PROMPT_B)]:
            result = _format_prompt(template, variant=variant)
            assert isinstance(result, str)
            assert len(result) > 100

    def test_no_unresolved_placeholders(self):
        result = _format_prompt(SYSTEM_PROMPT)
        assert "{instruction_hint_rule}" not in result
        result_b = _format_prompt(SYSTEM_PROMPT_B)
        assert "{instruction_hint_rule_short}" not in result_b

    def test_instruction_rule_present(self):
        result = _format_prompt(SYSTEM_PROMPT)
        assert "file path" in result.lower() or "task.yaml" in result.lower()


class TestBuildUserPrompt:
    """Tests for _build_user_prompt."""

    def test_contains_topic(self):
        prompt = _build_user_prompt("fix a broken script")
        assert "fix a broken script" in prompt

    def test_contains_examples_section(self):
        prompt = _build_user_prompt("fix a bug")
        assert "reference examples" in prompt

    def test_reminds_about_tests(self):
        prompt = _build_user_prompt("fix a bug")
        assert "Tests must fail before solution and pass after" in prompt


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    """Test JSON parsing with various edge cases."""

    def test_clean_json(self):
        """Clean JSON object with 'files' key parses correctly."""
        payload = {"files": {"main.py": "print('hello')", "test.py": "assert True"}}
        result = _parse_response(json.dumps(payload))
        assert result == payload["files"]

    def test_json_in_markdown_fences(self):
        """JSON wrapped in ```json ... ``` is extracted."""
        payload = {"files": {"app.py": "x = 1"}}
        text = f"```json\n{json.dumps(payload)}\n```"
        result = _parse_response(text)
        assert result == payload["files"]

    def test_json_in_plain_fences(self):
        """JSON wrapped in ``` ... ``` (no language tag) is extracted."""
        payload = {"files": {"a.sh": "echo hi"}}
        text = f"```\n{json.dumps(payload)}\n```"
        result = _parse_response(text)
        assert result == payload["files"]

    def test_json_with_embedded_triple_backticks(self):
        """JSON whose string values contain triple backticks parses correctly.

        This simulates a task.yaml instruction field that contains markdown code fences.
        """
        instruction = "Fix the bug:\n```python\nprint('hi')\n```\nThen run tests."
        payload = {"files": {"task.yaml": instruction, "main.py": "pass"}}
        raw_json = json.dumps(payload)
        # Wrap in markdown fences -- the content itself has ``` inside
        text = f"```json\n{raw_json}\n```"
        result = _parse_response(text)
        assert result == payload["files"]
        assert "```python" in result["task.yaml"]

    def test_json_with_surrounding_text(self):
        """JSON embedded in surrounding explanation text is extracted via brace matching."""
        payload = {"files": {"x.py": "1+1"}}
        text = f"Here is the task:\n{json.dumps(payload)}\nHope that helps!"
        result = _parse_response(text)
        assert result == payload["files"]

    def test_invalid_json_raises(self):
        """Completely invalid text raises ValueError."""
        with pytest.raises(ValueError, match="Could not parse JSON"):
            _parse_response("this is not json at all")

    def test_missing_files_key_raises(self):
        """Valid JSON without 'files' key raises ValueError."""
        with pytest.raises(ValueError, match="missing 'files' key"):
            _parse_response(json.dumps({"tasks": {}}))

    def test_empty_files(self):
        """Empty files dict is valid (edge case)."""
        result = _parse_response(json.dumps({"files": {}}))
        assert result == {}

    def test_whitespace_around_json(self):
        """Leading/trailing whitespace is stripped before parsing."""
        payload = {"files": {"f.txt": "data"}}
        text = f"   \n\n  {json.dumps(payload)}  \n\n  "
        result = _parse_response(text)
        assert result == payload["files"]


# ---------------------------------------------------------------------------
# select_examples -- metadata-driven example selection
# ---------------------------------------------------------------------------

class TestSelectExamples:
    """Test metadata-driven example selection."""

    def _make_example(self, parent, name, classification="learnable",
                      pass_rate=0.4, category="debugging", tokens=3000):
        """Create a minimal example directory with _meta.yaml."""
        d = parent / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "task.yaml").write_text(f"instruction: test\ndifficulty: medium\n")
        (d / "_meta.yaml").write_text(
            f"classification: {classification}\n"
            f"opus_pass_rate: {pass_rate}\n"
            f"opus_passes: {int(pass_rate * 5)}\n"
            f"opus_total: 5\n"
            f"category: {category}\n"
            f"approx_tokens: {tokens}\n"
            f"source: test\n"
        )

    def test_learnable_examples_selected(self, monkeypatch, tmp_path):
        """Learnable examples appear as positive."""
        examples_dir = tmp_path / "examples"
        self._make_example(examples_dir, "good-task")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope1"))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(tmp_path / "nope2"))

        result = select_examples()
        assert "GOOD EXAMPLES" in result
        assert "good-task" in result

    def test_too_easy_in_negative_section(self, monkeypatch, tmp_path):
        """Too-easy examples appear in negative section."""
        examples_dir = tmp_path / "examples"
        self._make_example(examples_dir, "trivial-task", classification="too_easy",
                          pass_rate=1.0, tokens=1000)

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope1"))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(tmp_path / "nope2"))

        result = select_examples()
        assert "TOO-EASY EXAMPLES" in result
        assert "trivial-task" in result

    def test_too_hard_excluded(self, monkeypatch, tmp_path):
        """Too-hard examples are excluded entirely."""
        examples_dir = tmp_path / "examples"
        self._make_example(examples_dir, "hard-task", classification="too_hard", pass_rate=0.0)
        self._make_example(examples_dir, "good-task")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope1"))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(tmp_path / "nope2"))

        result = select_examples()
        assert "hard-task" not in result
        assert "good-task" in result

    def test_no_meta_skipped(self, monkeypatch, tmp_path):
        """Examples without _meta.yaml are skipped."""
        examples_dir = tmp_path / "examples"
        d = examples_dir / "no-meta"
        d.mkdir(parents=True)
        (d / "task.yaml").write_text("instruction: test\n")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope1"))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(tmp_path / "nope2"))

        result = select_examples()
        assert result == ""

    def test_token_budget_respected(self, monkeypatch, tmp_path):
        """Token budget limits how many examples are included."""
        examples_dir = tmp_path / "examples"
        self._make_example(examples_dir, "big-a", tokens=8000, category="debugging")
        self._make_example(examples_dir, "big-b", tokens=8000, category="networking")
        self._make_example(examples_dir, "big-c", tokens=8000, category="build-systems")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope1"))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(tmp_path / "nope2"))

        result = select_examples(token_budget=15000)
        # Only 2 of 3 should fit in 15k budget (8k each)
        count = sum(1 for name in ["big-a", "big-b", "big-c"] if name in result)
        assert count <= 2

    def test_category_diversity(self, monkeypatch, tmp_path):
        """Examples from different categories are preferred."""
        examples_dir = tmp_path / "examples"
        self._make_example(examples_dir, "debug-1", category="debugging", tokens=2000)
        self._make_example(examples_dir, "debug-2", category="debugging", tokens=2000)
        self._make_example(examples_dir, "net-1", category="networking", tokens=2000)

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope1"))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(tmp_path / "nope2"))

        result = select_examples(token_budget=5000)
        # Should pick one from each category before doubling up
        assert "net-1" in result
        assert "debug-1" in result or "debug-2" in result

    def test_no_examples_dirs(self, monkeypatch, tmp_path):
        """Returns empty string when no examples directories exist."""
        monkeypatch.setattr("generate.EXAMPLES_DIR", str(tmp_path / "nope1"))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope2"))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(tmp_path / "nope3"))

        result = select_examples()
        assert result == ""

    def test_across_all_dirs(self, monkeypatch, tmp_path):
        """Examples from all three directories are considered."""
        ex_dir = tmp_path / "examples"
        opus_dir = tmp_path / "opus"
        sonnet_dir = tmp_path / "sonnet"
        self._make_example(ex_dir, "hand-a", category="debugging")
        self._make_example(opus_dir, "opus-b", category="networking")
        self._make_example(sonnet_dir, "sonnet-c", category="build-systems")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(ex_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(opus_dir))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(sonnet_dir))

        result = select_examples()
        assert "hand-a" in result
        assert "opus-b" in result
        assert "sonnet-c" in result


class TestScoreExample:
    """Test the example scoring function."""

    def test_ideal_pass_rate_scores_highest(self):
        """Pass rate of 0.5 (ideal) scores higher than 0.2 (borderline)."""
        ideal = _score_example({"opus_pass_rate": 0.5, "approx_tokens": 3000}, None)
        borderline = _score_example({"opus_pass_rate": 0.2, "approx_tokens": 3000}, None)
        assert ideal > borderline

    def test_category_match_bonus(self):
        """Matching category gets a score bonus."""
        match = _score_example({"opus_pass_rate": 0.4, "category": "debugging", "approx_tokens": 3000}, "debugging")
        no_match = _score_example({"opus_pass_rate": 0.4, "category": "networking", "approx_tokens": 3000}, "debugging")
        assert match > no_match

    def test_smaller_examples_preferred(self):
        """Smaller examples get slight preference."""
        small = _score_example({"opus_pass_rate": 0.4, "approx_tokens": 2000}, None)
        large = _score_example({"opus_pass_rate": 0.4, "approx_tokens": 7000}, None)
        assert small > large


# ---------------------------------------------------------------------------
# _slugify (from config.py)
# ---------------------------------------------------------------------------

class TestSlugify:
    """Test slug generation edge cases."""

    def test_normal_topic(self):
        """Simple topic becomes lowercase hyphenated slug."""
        assert _slugify("Fix Broken Parser") == "fix-broken-parser"

    def test_special_chars_removed(self):
        """Commas, parens, and other non-alphanumeric chars are stripped."""
        assert _slugify("Fix (broken) parser, v2!") == "fix-broken-parser-v2"

    def test_consecutive_hyphens_collapsed(self):
        """Multiple hyphens are collapsed into one."""
        assert _slugify("fix - - broken") == "fix-broken"

    def test_leading_trailing_hyphens_stripped(self):
        """Hyphens at edges are removed."""
        assert _slugify(" -fix it- ") == "fix-it"

    def test_short_topic_no_hash(self):
        """Short slug is returned as-is without hash suffix."""
        slug = _slugify("short")
        assert slug == "short"
        assert len(slug) <= _SLUG_MAX_LEN

    def test_long_topic_truncated_with_hash(self):
        """Very long topic is truncated and gets a hash suffix."""
        long_topic = "fix the incredibly broken multi-threaded async event loop in the distributed microservice architecture framework"
        slug = _slugify(long_topic)
        assert len(slug) <= _SLUG_MAX_LEN
        # Hash suffix is present (6 hex chars after last hyphen)
        assert "-" in slug

    def test_long_topic_uniqueness(self):
        """Two long topics sharing a prefix but differing later produce different slugs."""
        prefix = "a " * 40  # well over 60 chars
        slug1 = _slugify(prefix + "alpha")
        slug2 = _slugify(prefix + "beta")
        assert slug1 != slug2

    def test_empty_string(self):
        """Empty string produces an empty slug."""
        assert _slugify("") == ""

    def test_all_special_chars(self):
        """A topic made entirely of special characters produces empty slug."""
        assert _slugify("!@#$%^&*()") == ""

    def test_numerics_preserved(self):
        """Digits are kept in the slug."""
        assert _slugify("Python 3.12 fix") == "python-312-fix"
