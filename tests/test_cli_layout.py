"""
Unit tests for CLI layout, error formatting, and fuzzy typo suggestions in VoiceFi.
"""

import io
import sys
import pytest
from unittest.mock import patch

from voicefi.cli_format import (
    find_closest_matches,
    render_categorized_help,
    render_error_box,
    resolve_prog_name,
    VoiceFiArgumentParser,
)


def test_find_closest_matches_exact():
    choices = ["hook", "speak", "onboarding", "voice", "troubleshoot"]
    assert find_closest_matches("onboarding", choices) == ["onboarding"]
    assert find_closest_matches("ONBOARDING", choices) == ["onboarding"]


def test_find_closest_matches_prefix_and_substring():
    choices = ["hook", "speak", "onboarding", "voice", "troubleshoot", "list"]
    assert find_closest_matches("onboard", choices) == ["onboarding"]
    assert find_closest_matches("trouble", choices) == ["troubleshoot"]
    assert find_closest_matches("lis", choices) == ["list"]


def test_find_closest_matches_fuzzy_typos():
    choices = ["hook", "speak", "onboarding", "voice", "troubleshoot", "download-ava", "hearing-test"]
    # Typo onbaoarding -> onboarding
    matches = find_closest_matches("onbaoarding", choices)
    assert len(matches) >= 1
    assert matches[0] == "onboarding"

    # Typo speek -> speak
    matches_speak = find_closest_matches("speek", choices)
    assert "speak" in matches_speak


def test_render_categorized_help():
    help_text = render_categorized_help(prog="vifi")
    assert "VoiceFi" in help_text
    assert "Usage: vifi <command>" in help_text
    assert "Agent & Integration" in help_text
    assert "Voice & Personas" in help_text
    assert "Interface & Controls" in help_text
    assert "Memory & Knowledge" in help_text
    assert "Diagnostics & Audio" in help_text
    assert "Management" in help_text
    assert "--version" in help_text
    assert "Quick Examples" in help_text


def test_render_error_box():
    box = render_error_box("Unknown command", "'onbaoarding'", suggestions=["onboarding"], prog="vifi")
    assert "Unknown command: 'onbaoarding'" in box
    assert "Did you mean?" in box
    assert "vifi onboarding" in box
    assert "Run vifi --help" in box


def test_parser_typo_error_output():
    parser = VoiceFiArgumentParser(prog="vifi")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.add_parser("onboarding")
    subparsers.add_parser("speak")
    subparsers.add_parser("troubleshoot")

    stderr_capture = io.StringIO()
    with patch("sys.stderr", stderr_capture):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["onbaoarding"])
        assert exc.value.code == 2

    output = stderr_capture.getvalue()
    assert "Unknown command: 'onbaoarding'" in output
    assert "Did you mean?" in output
    assert "vifi onboarding" in output


def test_parser_flag_typo_error_output():
    parser = VoiceFiArgumentParser(prog="vifi")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--config", type=str)

    stderr_capture = io.StringIO()
    with patch("sys.stderr", stderr_capture):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--verison"])
        assert exc.value.code == 2

    output = stderr_capture.getvalue()
    assert "Unrecognized argument: --verison" in output
    assert "Did you mean?" in output
    assert "--version" in output


def test_parser_subaction_typo_error_output():
    parser = VoiceFiArgumentParser(prog="vifi")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    voice_p = subparsers.add_parser("voice")
    voice_sub = voice_p.add_subparsers(dest="voice_action", metavar="<action>")
    voice_sub.add_parser("list")
    voice_sub.add_parser("test")

    stderr_capture = io.StringIO()
    with patch("sys.stderr", stderr_capture):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["voice", "lis"])
        assert exc.value.code == 2

    output = stderr_capture.getvalue()
    assert "Unknown action: 'lis'" in output
    assert "Did you mean?" in output
    assert "vifi voice list" in output


def test_resolve_prog_name():
    with patch.object(sys, "argv", ["/opt/homebrew/bin/vifi", "speak"]):
        assert resolve_prog_name() == "vifi"
    with patch.object(sys, "argv", ["/usr/local/bin/voicefi", "listen"]):
        assert resolve_prog_name() == "voicefi"
