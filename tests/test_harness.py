"""Tests for Terminal Bench harness helpers: caching, AsciinemaHandler, templates."""

from __future__ import annotations

import json
import os
import stat
import sys

import pytest

# Match the sys.path pattern used by other test files in this repo.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "terminal_bench", "terminal_bench"),
)

from llms.lite_llm import add_anthropic_caching
from harness.harness import AsciinemaHandler
from agents.terminus_1 import CommandBatchResponse

# Root of the terminal_bench package tree (for file-existence checks).
_TB_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "terminal_bench", "terminal_bench"
)
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


# ---------------------------------------------------------------------------
# add_anthropic_caching
# ---------------------------------------------------------------------------

class TestAddAnthropicCaching:
    """Tests for the add_anthropic_caching helper."""

    def test_adds_cache_control_for_anthropic_model(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = add_anthropic_caching(messages, "anthropic/claude-3-sonnet")
        # First message should have its content wrapped with cache_control
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_adds_cache_control_for_claude_model(self):
        messages = [
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "Hi"},
        ]
        result = add_anthropic_caching(messages, "claude-3-opus-20240229")
        assert isinstance(result[0]["content"], list)
        assert result[0]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_last_user_message_cached(self):
        messages = [
            {"role": "system", "content": "Sys"},
            {"role": "assistant", "content": "Ok"},
            {"role": "user", "content": "Follow-up"},
        ]
        result = add_anthropic_caching(messages, "anthropic/claude-3-sonnet")
        # Last message is role=user so it should be wrapped too
        assert isinstance(result[-1]["content"], list)
        assert result[-1]["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_passthrough_for_non_anthropic_model(self):
        messages = [
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "Hello"},
        ]
        result = add_anthropic_caching(messages, "gpt-4")
        # Should be returned unchanged
        assert result == messages

    def test_empty_message_list(self):
        result = add_anthropic_caching([], "anthropic/claude-3-sonnet")
        assert result == []

    def test_does_not_mutate_original(self):
        messages = [{"role": "system", "content": "Sys"}]
        _ = add_anthropic_caching(messages, "anthropic/claude-3-sonnet")
        # Original should still have a plain string content
        assert isinstance(messages[0]["content"], str)

    def test_handles_dict_content(self):
        messages = [
            {
                "role": "system",
                "content": [{"type": "text", "text": "Already structured"}],
            },
        ]
        # Should not crash; dict/list content won't match `isinstance(content, str)`
        result = add_anthropic_caching(messages, "anthropic/claude-3-sonnet")
        # Content was not a plain string, so it should remain a list (not double-wrapped)
        assert isinstance(result[0]["content"], list)


# ---------------------------------------------------------------------------
# AsciinemaHandler.merge_markers
# ---------------------------------------------------------------------------

class TestAsciinemaHandler:
    """Tests for the AsciinemaHandler.merge_markers method."""

    @staticmethod
    def _make_recording(tmp_path, events=None):
        """Create a minimal asciinema v2 recording file."""
        rec = tmp_path / "recording.cast"
        header = json.dumps({"version": 2, "width": 80, "height": 24})
        if events is None:
            events = [
                json.dumps([0.5, "o", "$ "]),
                json.dumps([1.0, "o", "hello\r\n"]),
                json.dumps([2.0, "o", "$ "]),
            ]
        rec.write_text(header + "\n" + "\n".join(events) + "\n")
        return rec

    def test_merge_markers_inserts_and_sorts(self, tmp_path):
        rec = self._make_recording(tmp_path)
        markers = [(0.75, "marker-A"), (1.5, "marker-B")]
        handler = AsciinemaHandler(markers, rec)
        handler.merge_markers()

        lines = rec.read_text().splitlines()
        # Header is still first
        assert json.loads(lines[0])["version"] == 2
        # Markers should be present
        events = [json.loads(l) for l in lines[1:]]
        marker_events = [e for e in events if e[1] == "m"]
        assert len(marker_events) == 2
        # All events should be sorted by timestamp
        timestamps = [e[0] for e in events]
        assert timestamps == sorted(timestamps)

    def test_merge_markers_empty_markers_is_noop(self, tmp_path):
        rec = self._make_recording(tmp_path)
        original = rec.read_text()
        handler = AsciinemaHandler([], rec)
        handler.merge_markers()
        assert rec.read_text() == original

    def test_merge_markers_nonexistent_file(self, tmp_path):
        fake_path = tmp_path / "does_not_exist.cast"
        handler = AsciinemaHandler([(1.0, "hi")], fake_path)
        # Should not raise
        handler.merge_markers()

    def test_merge_markers_empty_file(self, tmp_path):
        rec = tmp_path / "empty.cast"
        rec.write_text("")
        handler = AsciinemaHandler([(1.0, "hi")], rec)
        # Should not raise
        handler.merge_markers()


# ---------------------------------------------------------------------------
# CommandBatchResponse (Pydantic model / JSON extraction)
# ---------------------------------------------------------------------------

class TestCommandBatchResponse:
    """Tests for CommandBatchResponse parsing and validation."""

    _VALID_PAYLOAD = {
        "state_analysis": "Terminal is at prompt.",
        "explanation": "Run ls to list files.",
        "commands": [
            {"keystrokes": "ls", "is_blocking": True, "timeout_sec": 5.0}
        ],
        "is_task_complete": False,
    }

    def test_valid_json_parses(self):
        obj = CommandBatchResponse.model_validate_json(json.dumps(self._VALID_PAYLOAD))
        assert obj.state_analysis == "Terminal is at prompt."
        assert len(obj.commands) == 1
        assert obj.commands[0].keystrokes == "ls"
        assert obj.is_task_complete is False

    def test_embedded_json_extraction(self):
        """Simulate the fallback logic in _handle_llm_interaction."""
        freetext = (
            "Here's my response:\n"
            + json.dumps(self._VALID_PAYLOAD)
            + "\nHope that helps!"
        )
        # Direct parse should fail
        with pytest.raises(Exception):
            CommandBatchResponse.model_validate_json(freetext)
        # Fallback extraction
        brace_start = freetext.index("{")
        brace_end = freetext.rindex("}") + 1
        json_str = freetext[brace_start:brace_end]
        obj = CommandBatchResponse.model_validate_json(json_str)
        assert obj.explanation == "Run ls to list files."

    def test_extra_fields_rejected(self):
        payload = {**self._VALID_PAYLOAD, "extra_field": "bad"}
        with pytest.raises(Exception):
            CommandBatchResponse.model_validate_json(json.dumps(payload))

    def test_missing_required_field_rejected(self):
        incomplete = {
            "state_analysis": "ok",
            "explanation": "ok",
            # missing commands and is_task_complete
        }
        with pytest.raises(Exception):
            CommandBatchResponse.model_validate_json(json.dumps(incomplete))


# ---------------------------------------------------------------------------
# File existence checks
# ---------------------------------------------------------------------------

class TestFileExistence:
    """Verify that key repo files exist."""

    def test_get_asciinema_timestamp_script_exists_and_executable(self):
        script = os.path.join(_TB_ROOT, "terminal", "get-asciinema-timestamp.sh")
        assert os.path.isfile(script), f"Script not found: {script}"
        assert os.access(script, os.X_OK), f"Script is not executable: {script}"

    @pytest.mark.parametrize(
        "relpath",
        [
            "agents/prompt-templates/terminus.txt",
            "agents/prompt-templates/timeout.txt",
            "llms/prompt-templates/formatted-response.txt",
        ],
    )
    def test_prompt_template_exists(self, relpath):
        full = os.path.join(_TB_ROOT, relpath)
        assert os.path.isfile(full), f"Template not found: {full}"

    @pytest.mark.parametrize(
        "example_dir",
        [
            "broken-coordinate-transform",
            "broken-flask-api",
            "config-manifest-validator",
            "csv-to-json-cli-fix",
            "fix-maven-artifact-dependencies",
            "log-rotation-analyzer",
        ],
    )
    def test_example_docker_compose_exists(self, example_dir):
        path = os.path.join(_REPO_ROOT, "examples", example_dir, "docker-compose.yaml")
        assert os.path.isfile(path), f"docker-compose.yaml not found: {path}"
