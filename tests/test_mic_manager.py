import argparse
from unittest.mock import patch, MagicMock
from voicefi.audio.device import (
    find_builtin_microphone_name,
    find_headset_microphone_name,
    pin_mac_microphone,
    set_headset_microphone,
    toggle_microphone_source,
    auto_pin_mac_microphone,
)
from voicefi.cli_commands.audio import cmd_mic


def test_find_builtin_microphone_name():
    with patch("voicefi.audio.device.list_audio_input_devices", return_value=["Pixel Buds Pro 2", "MacBook Pro Microphone"]):
        assert find_builtin_microphone_name() == "MacBook Pro Microphone"

    with patch("voicefi.audio.device.list_audio_input_devices", return_value=["External USB Mic"]):
        assert find_builtin_microphone_name() is None


def test_find_headset_microphone_name():
    with patch("voicefi.audio.device.list_audio_input_devices", return_value=["Jake's Pixel Buds Pro 2", "MacBook Pro Microphone"]):
        assert find_headset_microphone_name() == "Jake's Pixel Buds Pro 2"

    with patch("voicefi.audio.device.list_audio_input_devices", return_value=["MacBook Pro Microphone"]):
        assert find_headset_microphone_name() is None


def test_pin_mac_microphone_already_pinned():
    with patch("voicefi.audio.device.find_builtin_microphone_name", return_value="MacBook Pro Microphone"), \
         patch("voicefi.audio.device.get_current_input_device_name", return_value="MacBook Pro Microphone"):
        ok, msg = pin_mac_microphone()
        assert ok is True
        assert "Already pinned" in msg


def test_pin_mac_microphone_switches():
    with patch("voicefi.audio.device.find_builtin_microphone_name", return_value="MacBook Pro Microphone"), \
         patch("voicefi.audio.device.get_current_input_device_name", return_value="Pixel Buds Pro 2"), \
         patch("voicefi.audio.device.set_audio_input_device", return_value=True):
        ok, msg = pin_mac_microphone()
        assert ok is True
        assert "Locked input to MacBook Pro Microphone" in msg


def test_set_headset_microphone():
    with patch("voicefi.audio.device.find_headset_microphone_name", return_value="Pixel Buds Pro 2"), \
         patch("voicefi.audio.device.get_current_input_device_name", return_value="MacBook Pro Microphone"), \
         patch("voicefi.audio.device.set_audio_input_device", return_value=True):
        ok, msg = set_headset_microphone()
        assert ok is True
        assert "Switched input to Pixel Buds Pro 2 for roaming" in msg


def test_toggle_microphone_source():
    with patch("voicefi.audio.device.find_builtin_microphone_name", return_value="MacBook Pro Microphone"), \
         patch("voicefi.audio.device.find_headset_microphone_name", return_value="Pixel Buds Pro 2"), \
         patch("voicefi.audio.device.get_current_input_device_name", return_value="MacBook Pro Microphone"), \
         patch("voicefi.audio.device.set_audio_input_device", return_value=True):
        ok, msg = toggle_microphone_source()
        assert ok is True
        assert "roaming" in msg


def test_auto_pin_mac_microphone_triggered():
    with patch("voicefi.audio.device.is_headphone_or_headset_active", return_value=True), \
         patch("voicefi.audio.device.is_bluetooth_input_active", return_value=True), \
         patch("voicefi.audio.device.pin_mac_microphone", return_value=(True, "Locked")) as mock_pin:
        ok, msg = auto_pin_mac_microphone(force=False)
        assert ok is True
        assert mock_pin.called


def test_auto_pin_mac_microphone_not_needed():
    with patch("voicefi.audio.device.is_headphone_or_headset_active", return_value=True), \
         patch("voicefi.audio.device.is_bluetooth_input_active", return_value=False):
        ok, msg = auto_pin_mac_microphone(force=False)
        assert ok is False
        assert "Auto-pin not needed" in msg


def test_cmd_mic_cli_status(capsys):
    with patch("voicefi.audio.device.get_audio_device_profile", return_value={
        "default_output": "Pixel Buds Pro 2",
        "is_headphones_active": True,
        "is_bluetooth_input_active": False,
    }), \
         patch("voicefi.audio.device.get_current_input_device_name", return_value="MacBook Pro Microphone"), \
         patch("voicefi.audio.device.list_audio_input_devices", return_value=["Pixel Buds Pro 2", "MacBook Pro Microphone"]):
        code = cmd_mic(argparse.Namespace(action=None))
        assert code == 0
        captured = capsys.readouterr().out
        assert "VoiceFi Microphone & Audio Input Status" in captured
        assert "MacBook Pro Microphone" in captured
        assert "High-Fidelity Stereo" in captured
