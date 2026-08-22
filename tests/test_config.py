"""Unit tests for configuration loading and validation."""

import pytest
from pathlib import Path
from voicegency.config import VoicegencyConfig, load_config, save_config


def test_default_config_values():
    config = VoicegencyConfig()
    assert config.version == 1
    assert config.tier == "community"
    assert config.tts.provider == "mac_say"
    assert config.stt.provider == "whisper_local"
    assert config.antigravity.auto_listen is True
    assert config.antigravity.read_summary_aloud is True
    assert "Mail Sent.aiff" in config.audio_cues.sent_chime
    assert "Mail Sent.aiff" in config.audio_cues.done_chime
    assert config.global_hotkey.focus_and_talk_hotkey == "<ctrl>+r"
    assert config.global_hotkey.dictate_hotkey == "<ctrl>+t"


def test_custom_config_save_load(tmp_path: Path):
    custom_yaml = tmp_path / "config.yaml"
    cfg = VoicegencyConfig(
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
