"""
Unit tests for Granular Zero-PII CLI telemetry in VoiceFi.
Validates PostHog instrumentation properties and verifies strict zero-PII guarantees.
"""

import argparse
import json
import pytest
from unittest.mock import patch, MagicMock

from voicefi.cli import extract_cli_metadata, cmd_hook
from voicefi.telemetry import sanitize_telemetry_data


def test_extract_cli_metadata_universal_properties():
    """Verify standard command, subcommand, agent, voice, and flags extraction."""
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


def test_cmd_hook_telemetry_enrichment_daemon_forward():
    """Verify cmd_hook attaches ipc_forwarded=True when daemon handles the hook."""
    args = argparse.Namespace(
        command="hook",
        config=None,
        agent="antigravity",
    )
    with patch("voicefi.integrations.daemon_client.forward_hook_to_daemon") as mock_forward:
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
    with patch("voicefi.integrations.daemon_client.forward_hook_to_daemon", return_value=None):
        with patch("voicefi.integrations.claude.handle_claude_stop_hook", return_value={}) as mock_claude:
            with patch("sys.stdin.isatty", return_value=True):
                cmd_hook(args)
                assert hasattr(args, "_telemetry_extra")
                assert args._telemetry_extra["hook_agent"] == "claude"
                assert args._telemetry_extra["ipc_forwarded"] is False
                assert mock_claude.called
