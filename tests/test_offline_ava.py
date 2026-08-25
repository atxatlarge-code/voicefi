"""
Unit tests for Apple Ava (Premium) 0ms offline speech detection, setup, and CLI commands.
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

from voicefi.config import VoiceFiConfig, AgentVoiceProfile
from voicefi.tts.offline import (
    is_voice_installed,
    list_installed_neural_voices,
    open_spoken_content_settings,
    configure_offline_voice,
    run_download_ava_workflow,
)
from voicefi.tts.catalog import find_persona, get_curated_personas


MOCK_SAY_OUTPUT_WITH_AVA = """Albert              en_US    # Hello! My name is Albert.
Alex                en_US    # Hello! My name is Alex.
Ava (Premium)       en_US    # Hello! My name is Ava.
Lee (Premium)       en_AU    # Hello! My name is Lee.
Nathan (Enhanced)   en_US    # Hello! My name is Nathan.
Samantha            en_US    # Hello! My name is Samantha.
"""

MOCK_SAY_OUTPUT_WITHOUT_AVA = """Albert              en_US    # Hello! My name is Albert.
Alex                en_US    # Hello! My name is Alex.
Nathan (Enhanced)   en_US    # Hello! My name is Nathan.
Samantha            en_US    # Hello! My name is Samantha.
"""


def test_is_voice_installed_positive():
    """Verify detection when Ava (Premium) is present in say output."""
    with patch("subprocess.check_output", return_value=MOCK_SAY_OUTPUT_WITH_AVA):
        installed, name = is_voice_installed("Ava")
        assert installed is True
        assert name == "Ava (Premium)"

        installed_exact, name_exact = is_voice_installed("Ava (Premium)")
        assert installed_exact is True
        assert name_exact == "Ava (Premium)"


def test_is_voice_installed_negative():
    """Verify is_voice_installed returns False when voice is not in say output."""
    with patch("subprocess.check_output", return_value=MOCK_SAY_OUTPUT_WITHOUT_AVA):
        installed, name = is_voice_installed("Ava")
        assert installed is False
        assert name is None


def test_list_installed_neural_voices():
    """Verify listing of Premium and Enhanced voices."""
    with patch("subprocess.check_output", return_value=MOCK_SAY_OUTPUT_WITH_AVA):
        voices = list_installed_neural_voices()
        assert len(voices) == 3
        voice_ids = [v["id"] for v in voices]
        assert "Ava (Premium)" in voice_ids
        assert "Lee (Premium)" in voice_ids
        assert "Nathan (Enhanced)" in voice_ids


def test_open_spoken_content_settings():
    """Verify opening Spoken Content settings triggers system open."""
    with patch("subprocess.run") as mock_run:
        res = open_spoken_content_settings()
        assert res is True
        mock_run.assert_any_call(
            ["open", "x-apple.systempreferences:com.apple.preference.universalaccess?SpokenContent"],
            check=True,
            stdout=-3,
            stderr=-3,
            timeout=5,
        )


def test_configure_offline_voice(tmp_path):
    """Verify configure_offline_voice updates config and agents correctly."""
    cfg = VoiceFiConfig()
    cfg.agents["antigravity"] = AgentVoiceProfile(voice="Christopher", provider="edge_tts")
    
    with patch("voicefi.tts.offline.save_config") as mock_save:
        res = configure_offline_voice("Ava (Premium)", config=cfg, speak_confirmation=False)
        assert res["success"] is True
        assert cfg.tts.provider == "mac_say"
        assert cfg.tts.voice == "Ava (Premium)"
        assert cfg.agents["antigravity"].provider == "mac_say"
        assert cfg.agents["antigravity"].voice == "Ava (Premium)"
        mock_save.assert_called_once_with(cfg)


def test_run_download_ava_workflow_already_installed():
    """When Ava is already installed, workflow completes immediately."""
    with patch("subprocess.check_output", return_value=MOCK_SAY_OUTPUT_WITH_AVA):
        with patch("voicefi.tts.offline.save_config"):
            res = run_download_ava_workflow(auto_poll=False, silent=True)
            assert res["success"] is True
            assert res["provider"] == "mac_say"
            assert res["voice"] == "Ava (Premium)"


def test_run_download_ava_workflow_check_only():
    """Verify --check mode returns status without mutating config."""
    with patch("subprocess.check_output", return_value=MOCK_SAY_OUTPUT_WITH_AVA):
        res = run_download_ava_workflow(check_only=True, silent=True)
        assert res["installed"] is True
        assert res["voice"] == "Ava (Premium)"

    with patch("subprocess.check_output", return_value=MOCK_SAY_OUTPUT_WITHOUT_AVA):
        res_no = run_download_ava_workflow(check_only=True, silent=True)
        assert res_no["installed"] is False


def test_catalog_find_persona_ava_premium():
    """Verify catalog recognizes Ava (Premium) and Ava (Enhanced) personas."""
    persona = find_persona("Ava (Premium)")
    assert persona is not None
    assert persona.name == "Ava"
    assert persona.provider == "mac_say"

    persona_enh = find_persona("Ava (Enhanced)")
    assert persona_enh is not None
    assert persona_enh.provider == "mac_say"


def test_cli_download_ava_parsers():
    """Verify CLI parser accepts download-ava subcommands and options."""
    from voicefi.cli import main
    import argparse

    # Test top-level download-ava command invocation
    with patch("voicefi.cli.cmd_download_ava") as mock_cmd:
        with patch("sys.argv", ["vifi", "download-ava", "--check"]):
            from voicefi.cli import main
            main()
            mock_cmd.assert_called_once()
            args = mock_cmd.call_args[0][0]
            assert args.check is True

    # Test voice download-ava subcommand
    with patch("voicefi.cli.cmd_download_ava") as mock_cmd2:
        with patch("sys.argv", ["vifi", "voice", "download-ava", "--no-wait"]):
            from voicefi.cli import main
            main()
            mock_cmd2.assert_called_once()
            args2 = mock_cmd2.call_args[0][0]
            assert args2.no_wait is True
