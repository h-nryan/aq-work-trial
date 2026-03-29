"""Tests for the generator's prompt construction."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from generate import SYSTEM_PROMPT, _build_user_prompt


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

    def test_mentions_interacting_bugs(self):
        assert "3-5 distinct bugs" in SYSTEM_PROMPT

    def test_requires_all_files(self):
        assert "task.yaml" in SYSTEM_PROMPT
        assert "Dockerfile" in SYSTEM_PROMPT
        assert "run-tests.sh" in SYSTEM_PROMPT
        assert "solution.sh" in SYSTEM_PROMPT
        assert "test_outputs.py" in SYSTEM_PROMPT


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
