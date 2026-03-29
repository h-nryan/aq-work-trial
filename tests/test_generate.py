"""Tests for the generator's difficulty calibration and prompt construction."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from generate import DIFFICULTY_GUIDANCE, _build_system_prompt, _build_user_prompt


class TestDifficultyGuidance:
    """Tests for difficulty-calibrated prompt generation."""

    def test_all_difficulties_have_guidance(self):
        assert "easy" in DIFFICULTY_GUIDANCE
        assert "medium" in DIFFICULTY_GUIDANCE
        assert "hard" in DIFFICULTY_GUIDANCE

    def test_easy_guidance_mentions_high_solve_rate(self):
        assert "80-90%" in DIFFICULTY_GUIDANCE["easy"]

    def test_medium_guidance_mentions_moderate_solve_rate(self):
        assert "40-60%" in DIFFICULTY_GUIDANCE["medium"]

    def test_hard_guidance_mentions_low_solve_rate(self):
        assert "10-30%" in DIFFICULTY_GUIDANCE["hard"]

    def test_easy_fewer_bugs(self):
        assert "1-2" in DIFFICULTY_GUIDANCE["easy"]

    def test_hard_more_bugs(self):
        assert "5-7" in DIFFICULTY_GUIDANCE["hard"]


class TestBuildSystemPrompt:
    """Tests for _build_system_prompt."""

    def test_contains_critical_rules(self):
        prompt = _build_system_prompt("medium")
        assert "CRITICAL RULES" in prompt

    def test_contains_output_format(self):
        prompt = _build_system_prompt("medium")
        assert "OUTPUT FORMAT" in prompt

    def test_easy_prompt_uses_easy_guidance(self):
        prompt = _build_system_prompt("easy")
        assert "80-90%" in prompt
        assert "1-2 clear bugs" in prompt

    def test_hard_prompt_uses_hard_guidance(self):
        prompt = _build_system_prompt("hard")
        assert "10-30%" in prompt
        assert "dependency chain" in prompt

    def test_unknown_difficulty_falls_back_to_medium(self):
        prompt = _build_system_prompt("unknown")
        assert "40-60%" in prompt


class TestBuildUserPrompt:
    """Tests for _build_user_prompt."""

    def test_contains_topic(self):
        prompt = _build_user_prompt("fix a broken script", "medium")
        assert "fix a broken script" in prompt

    def test_contains_difficulty_level(self):
        prompt = _build_user_prompt("fix a bug", "hard")
        assert "DIFFICULTY LEVEL: HARD" in prompt

    def test_instructs_yaml_difficulty(self):
        prompt = _build_user_prompt("fix a bug", "easy")
        assert 'difficulty: "easy"' in prompt
