"""
Unit tests for feedback submission, diagnostics collection, and CLI feedback commands.
"""

from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest
from voicefi.feedback import (
    submit_feedback,
    list_feedback,
    collect_system_diagnostics,
)
from voicefi.cli import cmd_feedback


def test_collect_system_diagnostics():
    """Test gathering environment diagnostics."""
    diag = collect_system_diagnostics()
    assert "voicefi_version" in diag
    assert "os_platform" in diag
    assert "python_version" in diag
    assert "tts_provider" in diag


def test_submit_and_list_feedback(tmp_path):
    """Test submitting feedback and verifying persistence."""
    with patch("voicefi.feedback.get_feedback_dir", return_value=tmp_path / "feedback"), \
         patch("voicefi.feedback.Path.home", return_value=tmp_path), \
         patch("voicefi.telemetry.capture_event") as mock_capture:
        
        record = submit_feedback(
            title="Audio sample rate mismatch",
            details="Recorded audio is slightly pitched up on external mic.",
            category="voice_quality",
            agent_id="antigravity",
        )

        assert record["title"] == "Audio sample rate mismatch"
        assert record["category"] == "voice_quality"
        assert record["agent_id"] == "antigravity"
        assert "diagnostics" in record

        items = list_feedback(limit=5)
        assert len(items) >= 1
        assert items[0]["id"] == record["id"]


def test_submit_feedback_validation():
    """Test empty title validation."""
    with pytest.raises(ValueError):
        submit_feedback(title="")


def test_cmd_feedback_cli(capsys, tmp_path):
    """Test CLI feedback submission and listing."""
    with patch("voicefi.feedback.get_feedback_dir", return_value=tmp_path / "feedback"), \
         patch("voicefi.feedback.Path.home", return_value=tmp_path), \
         patch("voicefi.telemetry.capture_event") as mock_capture:

        # Test submit
        args_submit = MagicMock()
        args_submit.feedback_action = "submit"
        args_submit.title = ["Microphone", "energy", "too", "sensitive"]
        args_submit.details = "Triggered voice capture on fan noise."
        args_submit.category = "bug"
        args_submit.agent_id = "test_agent"
        args_submit.no_diagnostics = False

        cmd_feedback(args_submit)
        captured = capsys.readouterr()
        assert "Feedback logged successfully" in captured.out

        # Test list
        args_list = MagicMock()
        args_list.feedback_action = "list"
        args_list.limit = 5

        cmd_feedback(args_list)
        captured_list = capsys.readouterr()
        assert "Recent Feedback Items" in captured_list.out
        assert "Microphone energy too sensitive" in captured_list.out


def test_telemetry_sanitization():
    """Verify telemetry path and token sanitization eliminates PII."""
    from voicefi.telemetry import sanitize_telemetry_data

    sample = {
        "path": "/Users/developer/Projects/myapp/main.py",
        "error": "Failed at /Users/developer/.voicefi/config.yaml with sk-1234567890abcdef123456",
        "nested": [
            "/Users/developer/Library/Application Support/voicefi",
            {"secret_key": "super_secret", "normal_metric": 42}
        ]
    }

    sanitized = sanitize_telemetry_data(sample)
    assert "/Users/developer" not in sanitized["path"]
    assert "~" in sanitized["path"]
    assert "sk-1234567890abcdef123456" not in sanitized["error"]
    assert "[REDACTED_API_KEY]" in sanitized["error"]
    assert "secret_key" not in sanitized["nested"][1]
    assert sanitized["nested"][1]["normal_metric"] == 42


def test_telemetry_opt_out():
    """Verify DO_NOT_TRACK and VOICEFI_TELEMETRY environment flags disable telemetry."""
    from voicefi.telemetry import is_telemetry_enabled
    import os

    with patch.dict(os.environ, {"DO_NOT_TRACK": "1"}):
        assert is_telemetry_enabled() is False

    with patch.dict(os.environ, {"VOICEFI_TELEMETRY": "0", "DO_NOT_TRACK": ""}):
        assert is_telemetry_enabled() is False
