"""
Unit tests for Granular Zero-PII CLI telemetry in VoiceFi.
Validates PostHog instrumentation properties, voice_interaction events, crash hashes, and strict zero-PII guarantees.
"""

import argparse
import json
import os
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from voicefi.cli import extract_cli_metadata, cmd_hook
from voicefi.telemetry import (
    sanitize_telemetry_data,
    get_telemetry_id,
    get_machine_id,
    is_telemetry_enabled,
    capture_voice_interaction,
    compute_traceback_hash,
    capture_event,
    set_active_command,
)


def test_extract_cli_metadata_universal_properties():
    """Verify standard command, subcommand, agent, voice, args, and flags extraction."""
    parser_args = argparse.Namespace(
        command="voice",
        voice_action="set",
        agent="antigravity",
        voice="Ava (Premium)",
        provider="apple_speech",
        quiet=True,
        dev=True,
    )
    props = extract_cli_metadata(parser_args)
    assert props["command"] == "voice"
    assert props["subcommand"] == "set"
    assert props["agent"] == "antigravity"
    assert props["voice"] == "Ava (Premium)"
    assert props["provider"] == "apple_speech"
    assert props["$is_server"] is True
    assert "--quiet" in props["args"]
    assert "--dev" in props["args"]
    assert "--quiet" in props["flags"]
    assert "--dev" in props["flags"]


def test_extract_cli_metadata_hud_properties():
    """Verify HUD actions, state enums, and boolean flags."""
    parser_args = argparse.Namespace(
        command="hud",
        hud_action="show",
        state="speaking",
        text="This should not be in props",
    )
    props = extract_cli_metadata(parser_args)
    assert props["command"] == "hud"
    assert props["subcommand"] == "show"
    assert props["hud_state"] == "speaking"
    assert "text" not in props


def test_extract_cli_metadata_zero_pii_guarantee():
    """Verify that user prompts, memo recordings, and raw text are never extracted."""
    parser_args = argparse.Namespace(
        command="speak",
        text=["Deploy", "to", "production", "server", "at", "192.168.1.1"],
        agent="claude",
        voice="Viv",
        prompt="Secret user prompt that must not leak",
        files=["/Users/alice/SecretProject/data.csv"],
    )
    props = extract_cli_metadata(parser_args)
    assert props["command"] == "speak"
    assert props["agent"] == "claude"
    assert props["voice"] == "Viv"
    assert "text" not in props
    assert "prompt" not in props
    assert "files" not in props


def test_sanitize_telemetry_data_drops_user_content_and_keys():
    """Verify sanitize_telemetry_data redacts paths, keys, and drops content fields."""
    raw_event = {
        "command": "hook",
        "subcommand": "Stop",
        "hook_agent": "antigravity",
        "sk_secret_key": "sk-1234567890abcdef1234567890",
        "prompt": "Fix the authentication vulnerability in auth.py",
        "raw_text": "Sensitive developer stream",
        "user_path": "/Users/john_doe/Projects/VoiceFi/test.py",
    }
    sanitized = sanitize_telemetry_data(raw_event)
    assert "sk_secret_key" not in sanitized
    assert "prompt" not in sanitized
    assert "raw_text" not in sanitized
    assert sanitized["command"] == "hook"
    assert sanitized["subcommand"] == "Stop"
    assert sanitized["hook_agent"] == "antigravity"
    assert sanitized["user_path"] == "~/Projects/VoiceFi/test.py"


def test_get_telemetry_id_persists(tmp_path):
    """Verify get_telemetry_id persists to ~/.voicefi/telemetry.json and reuses UUID."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    with patch("pathlib.Path.home", return_value=fake_home):
        tid1 = get_telemetry_id()
        assert tid1 is not None
        assert len(tid1) >= 32

        telemetry_file = fake_home / ".voicefi" / "telemetry.json"
        assert telemetry_file.is_file()
        stored = json.loads(telemetry_file.read_text())
        assert stored["id"] == tid1

        # Second call returns identical ID
        tid2 = get_telemetry_id()
        assert tid2 == tid1
        assert get_machine_id() == tid1


def test_telemetry_opt_out(monkeypatch):
    """Verify telemetry kill switch and opt-out environment variables."""
    monkeypatch.setenv("VOICEFI_TELEMETRY", "false")
    assert is_telemetry_enabled() is False

    monkeypatch.setenv("VOICEFI_TELEMETRY", "0")
    assert is_telemetry_enabled() is False

    monkeypatch.delenv("VOICEFI_TELEMETRY", raising=False)
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    assert is_telemetry_enabled() is False

    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    assert is_telemetry_enabled() is True


def test_capture_voice_interaction():
    """Verify capture_voice_interaction formats and dispatches zero-PII payload."""
    with patch("voicefi.telemetry.capture_event") as mock_capture:
        capture_voice_interaction(
            trigger="hook",
            duration_ms=450,
            success=True,
            agent="antigravity",
            voice="Ava (Premium)",
            provider="mac_say",
            chars_count=85,
            is_barge_in=True,
        )
        assert mock_capture.called
        event_name, props = mock_capture.call_args[0]
        assert event_name == "voice_interaction"
        assert props["trigger"] == "hook"
        assert props["duration_ms"] == 450
        assert props["success"] is True
        assert props["agent"] == "antigravity"
        assert props["voice"] == "Ava (Premium)"
        assert props["provider"] == "mac_say"
        assert props["chars_count"] == 85
        assert props["is_barge_in"] is True
        assert props["$is_server"] is True


def test_compute_traceback_hash():
    """Verify deterministic traceback hash computation."""
    tb = "Traceback (most recent call last):\n  File 'test.py', line 10, in <module>\nValueError: Test error"
    h1 = compute_traceback_hash(tb)
    h2 = compute_traceback_hash(tb)
    assert len(h1) == 16
    assert h1 == h2
    assert compute_traceback_hash("") == "empty"


def test_cmd_hook_telemetry_enrichment_server_forward():
    """Verify cmd_hook attaches ipc_forwarded=True when server handles the hook."""
    args = argparse.Namespace(
        command="hook",
        config=None,
        agent="antigravity",
    )
    with patch("voicefi.integrations.server_client.forward_hook_to_server") as mock_forward:
        mock_forward.return_value = {"status": "handled"}
        with patch("sys.stdin.isatty", return_value=True):
            cmd_hook(args)
            assert hasattr(args, "_telemetry_extra")
            assert args._telemetry_extra["hook_agent"] == "antigravity"
            assert args._telemetry_extra["ipc_forwarded"] is True


def test_cmd_hook_telemetry_enrichment_standalone():
    """Verify cmd_hook attaches ipc_forwarded=False when falling back to standalone."""
    args = argparse.Namespace(
        command="hook",
        config=None,
        agent="claude",
    )
    with patch("voicefi.integrations.server_client.forward_hook_to_server", return_value=None):
        with patch("voicefi.integrations.claude.handle_claude_stop_hook", return_value={}) as mock_claude:
            with patch("sys.stdin.isatty", return_value=True):
                cmd_hook(args)
                assert hasattr(args, "_telemetry_extra")
                assert args._telemetry_extra["hook_agent"] == "claude"
                assert args._telemetry_extra["ipc_forwarded"] is False
                assert mock_claude.called

