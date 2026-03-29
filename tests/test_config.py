"""Tests for config module — primarily _slugify."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "generator"))

from config import _slugify


class TestSlugify:
    def test_basic(self):
        assert _slugify("Fix a broken Python script") == "fix-a-broken-python-script"

    def test_slashes(self):
        assert _slugify("fix a/b issue") == "fix-ab-issue"

    def test_truncates_at_60(self):
        long = "a " * 50
        assert len(_slugify(long)) <= 60

    def test_truncation_at_word_boundary(self):
        # Truncated slug must not cut mid-word — prefix ends at a hyphen
        topic = "debug a c program with memory corruption in a linked list implementation"
        result = _slugify(topic)
        assert len(result) <= 60
        # The char before the 6-char hash suffix should be a hyphen
        assert result[-7] == "-"

    def test_truncation_no_collisions(self):
        # Two topics sharing a long prefix but differing at the end → different slugs
        a = _slugify("debug a c program with memory corruption in a linked list implementation")
        b = _slugify("debug a c program with memory corruption in a linked list insertion sort")
        assert a != b

    def test_short_topic_unchanged(self):
        # Topics under 60 chars get no hash suffix
        result = _slugify("fix a broken python script")
        assert result == "fix-a-broken-python-script"
        assert len(result) < 60

    def test_commas_stripped(self):
        result = _slugify("fix nested YAML, environment overrides, and defaults")
        assert "," not in result

    def test_consecutive_hyphens_collapsed(self):
        result = _slugify("fix  a--broken  script")
        assert "--" not in result

    def test_docker_tag_safe(self):
        result = _slugify("fix a/b, c++ (test) issue!")
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in result)

    def test_deterministic(self):
        topic = "fix a Python script"
        assert _slugify(topic) == _slugify(topic)
