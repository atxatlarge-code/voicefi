"""
Unit tests for vifi doctor CLI and self-healing diagnostics.
"""

import argparse
import pytest
from unittest.mock import patch, MagicMock

from voicefi.cli_commands.doctor import (
    check_python_environment,
    check_package_dependencies,
    check_audio_devices,
    check_port_availability,
    check_privacy_and_airgap,
    run_diagnostics,
    cmd_doctor,
)


def test_check_python_environment():
    res = check_python_environment()
    assert res["category"] == "Environment"
    assert res["status"] in ("pass", "warn")
    assert "version" in res


def test_check_package_dependencies():
    res = check_package_dependencies()
    assert isinstance(res, list)
    assert len(res) >= 2
    names = [r["name"] for r in res]
    assert any("Tokenizers" in n for n in names)


def test_check_audio_devices():
    with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
        mock_devs.return_value = (
            {"name": "Studio Mic"},
            {"name": "Studio Monitors", "default_samplerate": 48000.0},
        )
        res = check_audio_devices()
        assert res["status"] == "pass"
        assert res["output_samplerate"] == 48000.0
        assert "Studio Monitors" in res["details"]
        assert res["audio_input_lock_recommended"] is False


def test_check_audio_devices_bluetooth_input_lock_warning():
    with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
        mock_devs.return_value = (
            {"name": "Pixel Buds Pro 2"},
            {"name": "Pixel Buds Pro 2", "default_samplerate": 44100.0},
        )
        res = check_audio_devices()
        assert res["status"] == "warn"
        assert res["audio_input_lock_recommended"] is True
        assert "Audio Input Device Lock" in res["details"]
        assert "MacBook Pro Microphone" in res["details"]


def test_check_port_availability():
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0  # Port is open/listening
        mock_sock_cls.return_value = mock_sock

        res = check_port_availability()
        assert len(res) == 2
        assert res[0]["is_running"] is True


def test_check_privacy_and_airgap(monkeypatch):
    # Online mode
    monkeypatch.delenv("VOICEFI_OFFLINE", raising=False)
    monkeypatch.delenv("VOICEFI_AIRGAP", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setenv("VOICEFI_TELEMETRY", "1")

    res_online = check_privacy_and_airgap()
    assert res_online["is_offline_mode"] is False

    # Offline mode
    monkeypatch.setenv("VOICEFI_OFFLINE", "1")
    res_offline = check_privacy_and_airgap()
    assert res_offline["is_offline_mode"] is True
    assert "Air-Gap Active" in res_offline["details"]


def test_cmd_doctor_cli(monkeypatch, capsys):
    args = argparse.Namespace(json=False, fix=False)
    ret = cmd_doctor(args)
    assert ret in (0, 1)
    captured = capsys.readouterr().out
    assert "VoiceFi Doctor" in captured

    args_json = argparse.Namespace(json=True, fix=False)
    ret_json = cmd_doctor(args_json)
    assert ret_json in (0, 1)
