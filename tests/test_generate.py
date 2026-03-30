"""Tests for generator/generate.py (_parse_response, _load_examples) and config.py (_slugify)."""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from config import _slugify, _SLUG_MAX_LEN, _SLUG_HASH_LEN
from generate import (
    SYSTEM_PROMPT, SYSTEM_PROMPT_B, HINT_RULES, _format_prompt,
    _build_user_prompt, _parse_response, _load_examples,
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
    """Tests for _format_prompt with hint style placeholders."""

    def test_all_hint_styles_format_without_error(self):
        for variant, template in [("A", SYSTEM_PROMPT), ("B", SYSTEM_PROMPT_B)]:
            for style in HINT_RULES:
                result = _format_prompt(template, hint_style=style, variant=variant)
                assert isinstance(result, str)
                assert len(result) > 100

    def test_hint_style_changes_output(self):
        none_result = _format_prompt(SYSTEM_PROMPT, "none")
        soft_result = _format_prompt(SYSTEM_PROMPT, "soft")
        full_result = _format_prompt(SYSTEM_PROMPT, "full")
        assert none_result != soft_result
        assert soft_result != full_result

    def test_no_unresolved_placeholders(self):
        for style in HINT_RULES:
            result = _format_prompt(SYSTEM_PROMPT, style)
            assert "{instruction_hint_rule}" not in result
            result_b = _format_prompt(SYSTEM_PROMPT_B, style)
            assert "{instruction_hint_rule_short}" not in result_b


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
# _load_examples -- three-way classification
# ---------------------------------------------------------------------------

class TestLoadExamples:
    """Test example loading with the three-way classification logic."""

    def _make_task_dir(self, parent, name, content="hello"):
        """Create a minimal task directory with one file."""
        d = os.path.join(str(parent), name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "task.yaml"), "w") as f:
            f.write(content)

    def test_positive_examples(self, monkeypatch, tmp_path):
        """Normal examples (not too-easy, not too-hard) appear as positive."""
        examples_dir = tmp_path / "examples"
        examples_dir.mkdir()
        self._make_task_dir(examples_dir, "good-task")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "opus-nope"))
        monkeypatch.setattr("generate.TOO_EASY_EXAMPLES", set())
        monkeypatch.setattr("generate.TOO_HARD_EXAMPLES", set())

        result = _load_examples()
        assert "GOOD EXAMPLES" in result
        assert "good-task" in result
        assert "TOO-EASY" not in result

    def test_too_easy_in_negative_section(self, monkeypatch, tmp_path):
        """TOO_EASY_EXAMPLES items appear in the negative (TOO-EASY) section."""
        examples_dir = tmp_path / "examples"
        examples_dir.mkdir()
        self._make_task_dir(examples_dir, "trivial-task")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "opus-nope"))
        monkeypatch.setattr("generate.TOO_EASY_EXAMPLES", {"trivial-task"})
        monkeypatch.setattr("generate.TOO_HARD_EXAMPLES", set())

        result = _load_examples()
        assert "TOO-EASY EXAMPLES" in result
        assert "trivial-task" in result

    def test_too_hard_excluded_entirely(self, monkeypatch, tmp_path):
        """TOO_HARD_EXAMPLES items do not appear anywhere in the output."""
        examples_dir = tmp_path / "examples"
        examples_dir.mkdir()
        self._make_task_dir(examples_dir, "impossible-task")
        self._make_task_dir(examples_dir, "normal-task")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "opus-nope"))
        monkeypatch.setattr("generate.TOO_EASY_EXAMPLES", set())
        monkeypatch.setattr("generate.TOO_HARD_EXAMPLES", {"impossible-task"})

        result = _load_examples()
        assert "impossible-task" not in result
        assert "normal-task" in result

    def test_opus_examples_as_positive(self, monkeypatch, tmp_path):
        """Opus-generated examples from examples-opus/ are included as positive."""
        examples_dir = tmp_path / "examples"
        examples_dir.mkdir()
        opus_dir = tmp_path / "examples-opus"
        opus_dir.mkdir()
        self._make_task_dir(opus_dir, "opus-generated-task")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(opus_dir))
        monkeypatch.setattr("generate.TOO_EASY_EXAMPLES", set())
        monkeypatch.setattr("generate.TOO_HARD_EXAMPLES", set())

        result = _load_examples()
        assert "GOOD EXAMPLES" in result
        assert "opus-generated-task" in result

    def test_three_way_combined(self, monkeypatch, tmp_path):
        """All three classifications work together in a single call."""
        examples_dir = tmp_path / "examples"
        examples_dir.mkdir()
        self._make_task_dir(examples_dir, "normal-a")
        self._make_task_dir(examples_dir, "easy-one")
        self._make_task_dir(examples_dir, "hard-one")

        opus_dir = tmp_path / "examples-opus"
        opus_dir.mkdir()
        self._make_task_dir(opus_dir, "opus-b")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(opus_dir))
        monkeypatch.setattr("generate.TOO_EASY_EXAMPLES", {"easy-one"})
        monkeypatch.setattr("generate.TOO_HARD_EXAMPLES", {"hard-one"})

        result = _load_examples()
        assert "normal-a" in result
        assert "easy-one" in result        # in negative section
        assert "hard-one" not in result     # excluded
        assert "opus-b" in result           # positive
        assert "TOO-EASY EXAMPLES" in result
        assert "GOOD EXAMPLES" in result

    def test_no_examples_dirs(self, monkeypatch, tmp_path):
        """Returns empty string when no examples directories exist."""
        monkeypatch.setattr("generate.EXAMPLES_DIR", str(tmp_path / "nope1"))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope2"))
        monkeypatch.setattr("generate.SONNET_EXAMPLES_DIR", str(tmp_path / "nope3"))
        monkeypatch.setattr("generate.TOO_EASY_EXAMPLES", set())
        monkeypatch.setattr("generate.TOO_HARD_EXAMPLES", set())

        result = _load_examples()
        assert result == ""

    def test_files_in_examples_dir_ignored(self, monkeypatch, tmp_path):
        """Plain files (not dirs) in the examples directory are skipped."""
        examples_dir = tmp_path / "examples"
        examples_dir.mkdir()
        (examples_dir / "README.md").write_text("ignore me")
        self._make_task_dir(examples_dir, "real-task")

        monkeypatch.setattr("generate.EXAMPLES_DIR", str(examples_dir))
        monkeypatch.setattr("generate.OPUS_EXAMPLES_DIR", str(tmp_path / "nope"))
        monkeypatch.setattr("generate.TOO_EASY_EXAMPLES", set())
        monkeypatch.setattr("generate.TOO_HARD_EXAMPLES", set())

        result = _load_examples()
        assert "README" not in result
        assert "real-task" in result


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
