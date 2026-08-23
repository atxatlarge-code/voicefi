"""Unit tests for VoiceFi audio feedback chimes and sound effects."""

import os
from unittest.mock import patch
from voicefi.audio.chimes import (
    SYSTEM_SOUNDS,
    DEFAULT_SENT_SOUND,
    get_default_sent_sound,
    play_chime,
)


def test_system_sounds_keys():
    assert "start" in SYSTEM_SOUNDS
    assert "sent" in SYSTEM_SOUNDS
    assert "done" in SYSTEM_SOUNDS
    assert "mail_sent" in SYSTEM_SOUNDS
    assert "swoosh" in SYSTEM_SOUNDS
    assert "error" in SYSTEM_SOUNDS
    assert "alert" in SYSTEM_SOUNDS


def test_default_sent_sound():
    sound_path = get_default_sent_sound()
    assert os.path.exists(sound_path)
    assert DEFAULT_SENT_SOUND == sound_path


@patch("subprocess.run")
def test_play_chime_blocking(mock_run):
    play_chime("sent", block=True)
    assert mock_run.called
    args = mock_run.call_args[0][0]
    assert args[0] == "afplay"
    assert args[1] == DEFAULT_SENT_SOUND


@patch("subprocess.run")
def test_play_chime_custom_path(mock_run):
    play_chime("/System/Library/Sounds/Tink.aiff", block=True)
    assert mock_run.called
    args = mock_run.call_args[0][0]
    assert args[0] == "afplay"
    assert args[1] == "/System/Library/Sounds/Tink.aiff"
