"""Unit tests for configuration loading and validation."""

import pytest
from pathlib import Path
from voicefi.config import VoiceFiConfig, load_config, save_config


def test_default_config_values():
    config = VoiceFiConfig()
    assert config.version == 1
    assert config.tier == "community"
    assert config.tts.provider == "edge_tts"
    assert config.stt.provider == "whisper_local"
    assert config.antigravity.auto_listen is True
    assert config.antigravity.read_summary_aloud is True
    assert config.antigravity.max_spoken_words == 60
    assert config.vad.barge_in == "auto"
    assert config.telemetry is True
    assert "Mail Sent.aiff" in config.audio_cues.sent_chime
    assert "Mail Sent.aiff" in config.audio_cues.done_chime
    assert config.global_hotkey.focus_and_talk_hotkey == "<ctrl>+r"
    assert config.global_hotkey.dictate_hotkey == "<ctrl>+t"
    assert config.global_hotkey.new_conversation_hotkey == "<cmd>+<shift>+n"
    assert config.hud.enabled is True
    assert config.hud.persistent is True
    assert config.hud.auto_send is True
    assert config.hud.show_live_transcript is True


def test_custom_config_save_load(tmp_path: Path):
    custom_yaml = tmp_path / "config.yaml"
    cfg = VoiceFiConfig(
        tier="pro",
        license_key="PRO-1234-5678",
    )
    cfg.tts.voice = "Alex"
    cfg.antigravity.max_spoken_words = 40

    save_config(cfg, custom_yaml)
    assert custom_yaml.is_file()

    loaded = load_config(str(custom_yaml))
    assert loaded.tier == "pro"
    assert loaded.license_key == "PRO-1234-5678"
    assert loaded.tts.voice == "Alex"
    assert loaded.antigravity.max_spoken_words == 40
