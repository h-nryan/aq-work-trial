"""Tests for the topic/prompt bank."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from prompts import (
    PROMPT_BANK,
    TopicEntry,
    get_bank_stats,
    select_entries,
    select_topics,
)


class TestPromptBank:
    """Tests for the PROMPT_BANK data."""

    def test_bank_not_empty(self):
        assert len(PROMPT_BANK) > 0

    def test_all_entries_are_topic_entries(self):
        for entry in PROMPT_BANK:
            assert isinstance(entry, TopicEntry)

    def test_no_duplicate_topics(self):
        topics = [e.topic for e in PROMPT_BANK]
        assert len(topics) == len(set(topics)), "Duplicate topics found"

    def test_all_categories_covered(self):
        expected = {"debugging", "data-processing", "system-administration",
                    "software-engineering", "build-systems", "networking"}
        found = {e.category for e in PROMPT_BANK}
        assert expected == found, f"Missing categories: {expected - found}"

    def test_all_difficulties_covered(self):
        found = {e.difficulty for e in PROMPT_BANK}
        assert {"easy", "medium", "hard"} == found

    def test_each_category_has_multiple_entries(self):
        stats = get_bank_stats()
        for cat, count in stats["by_category"].items():
            assert count >= 3, f"Category '{cat}' has only {count} entries"

    def test_each_difficulty_has_multiple_entries(self):
        stats = get_bank_stats()
        for diff, count in stats["by_difficulty"].items():
            assert count >= 5, f"Difficulty '{diff}' has only {count} entries"

    def test_topic_strings_not_empty(self):
        for entry in PROMPT_BANK:
            assert len(entry.topic) > 10, f"Topic too short: {entry.topic}"

    def test_valid_difficulty_values(self):
        for entry in PROMPT_BANK:
            assert entry.difficulty in {"easy", "medium", "hard"}, \
                f"Invalid difficulty: {entry.difficulty}"

    def test_valid_category_values(self):
        valid = {"debugging", "data-processing", "system-administration",
                 "software-engineering", "build-systems", "networking"}
        for entry in PROMPT_BANK:
            assert entry.category in valid, f"Invalid category: {entry.category}"


class TestSelectTopics:
    """Tests for select_topics and select_entries."""

    def test_returns_requested_count(self):
        result = select_topics(n=5, seed=42)
        assert len(result) == 5

    def test_returns_strings(self):
        result = select_topics(n=3, seed=42)
        for t in result:
            assert isinstance(t, str)

    def test_filter_by_category(self):
        result = select_entries(n=5, category="debugging", seed=42)
        for entry in result:
            assert entry.category == "debugging"

    def test_filter_by_difficulty(self):
        result = select_entries(n=5, difficulty="hard", seed=42)
        for entry in result:
            assert entry.difficulty == "hard"

    def test_filter_by_language(self):
        result = select_entries(n=5, language="python", seed=42)
        for entry in result:
            assert entry.language == "python"

    def test_combined_filters(self):
        result = select_entries(n=10, category="debugging", difficulty="medium", seed=42)
        for entry in result:
            assert entry.category == "debugging"
            assert entry.difficulty == "medium"

    def test_empty_filter_returns_empty(self):
        result = select_topics(n=5, language="nonexistent", seed=42)
        assert result == []

    def test_diverse_covers_multiple_categories(self):
        result = select_entries(n=12, diverse=True, seed=42)
        categories = {e.category for e in result}
        assert len(categories) >= 4, f"Only {len(categories)} categories in diverse selection"

    def test_seed_reproducibility(self):
        r1 = select_topics(n=5, seed=123)
        r2 = select_topics(n=5, seed=123)
        assert r1 == r2

    def test_different_seeds_differ(self):
        r1 = select_topics(n=10, seed=1)
        r2 = select_topics(n=10, seed=2)
        assert r1 != r2

    def test_select_more_than_pool(self):
        result = select_topics(n=1000, difficulty="hard", seed=42)
        hard_count = sum(1 for e in PROMPT_BANK if e.difficulty == "hard")
        assert len(result) == hard_count


class TestGetBankStats:
    """Tests for get_bank_stats."""

    def test_total_matches_bank_length(self):
        stats = get_bank_stats()
        assert stats["total"] == len(PROMPT_BANK)

    def test_category_counts_sum_to_total(self):
        stats = get_bank_stats()
        assert sum(stats["by_category"].values()) == stats["total"]

    def test_difficulty_counts_sum_to_total(self):
        stats = get_bank_stats()
        assert sum(stats["by_difficulty"].values()) == stats["total"]

    def test_language_counts_sum_to_total(self):
        stats = get_bank_stats()
        assert sum(stats["by_language"].values()) == stats["total"]
