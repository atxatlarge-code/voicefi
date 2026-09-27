"""
Tests for Taras Stanin Beatbox & Vocal Synthesizer (voicefi.audio.beatbox_synth).
"""

import tempfile
import wave
from pathlib import Path
import numpy as np
import pytest

from voicefi.audio.beatbox_synth import (
    synth_beatbox_kick,
    synth_beatbox_snare,
    synth_beatbox_hihat,
    synth_laser_zap,
    synth_throat_bass,
    synth_tongue_roll,
    synth_taras_guitar_note,
    synth_taras_guitar_riff,
    generate_taras_beatbox_routine,
    save_beatbox_wav,
    play_beatbox,
    SAMPLE_RATE,
)


def test_synth_beatbox_drums():
    kick = synth_beatbox_kick(dur=0.30)
    snare = synth_beatbox_snare(dur=0.25)
    hihat_closed = synth_beatbox_hihat(dur=0.05, open_hat=False)
    hihat_open = synth_beatbox_hihat(dur=0.15, open_hat=True)

    for item, name in [
        (kick, "kick"),
        (snare, "snare"),
        (hihat_closed, "hihat_closed"),
        (hihat_open, "hihat_open"),
    ]:
        assert isinstance(item, np.ndarray)
        assert len(item) > 0
        assert np.max(np.abs(item)) <= 1.0, f"{name} exceeded amplitude limit"


def test_synth_special_fx():
    laser = synth_laser_zap(dur=0.08)
    throat_bass = synth_throat_bass(freq=55.0, dur=0.5, wobble_rate=3.0)
    tongue_roll = synth_tongue_roll(dur=0.3)

    assert len(laser) == int(SAMPLE_RATE * 0.08)
    assert len(throat_bass) == int(SAMPLE_RATE * 0.5)
    assert len(tongue_roll) == int(SAMPLE_RATE * 0.3)

    for item in [laser, throat_bass, tongue_roll]:
        assert np.max(np.abs(item)) <= 1.0


def test_synth_taras_guitar():
    # Single note
    note = synth_taras_guitar_note(freq=164.81, dur=0.3)
    assert len(note) == int(SAMPLE_RATE * 0.3)
    assert np.max(np.abs(note)) <= 1.0

    # Riffs
    riff_rock = synth_taras_guitar_riff(riff_style="rock", bpm=100.0)
    riff_nirvana = synth_taras_guitar_riff(riff_style="nirvana", bpm=110.0)
    riff_solo = synth_taras_guitar_riff(riff_style="solo", bpm=95.0)

    assert len(riff_rock) > SAMPLE_RATE
    assert len(riff_nirvana) > SAMPLE_RATE
    assert len(riff_solo) > SAMPLE_RATE


def test_generate_taras_beatbox_routine():
    routine = generate_taras_beatbox_routine(bars=2, bpm=95.0, include_guitar=True)
    expected_duration = (60.0 / 95.0) * 4.0 * 2  # 2 bars
    expected_samples = int(expected_duration * SAMPLE_RATE)

    assert abs(len(routine) - expected_samples) <= 1
    assert np.max(np.abs(routine)) <= 1.0


def test_save_beatbox_wav():
    kick = synth_beatbox_kick(0.2)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        saved_path = save_beatbox_wav(kick, tmp_path)
        assert saved_path.is_file()
        assert saved_path.stat().st_size > 500

        with wave.open(str(saved_path), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == SAMPLE_RATE
            assert wf.getnframes() == len(kick)
    finally:
        if tmp_path.is_file():
            tmp_path.unlink()


def test_play_beatbox_testing_mode(monkeypatch):
    monkeypatch.setenv("VOICEFI_TESTING", "1")
    assert play_beatbox(preset="routine", block=False) is True
    assert play_beatbox(preset="guitar", block=False) is True
    assert play_beatbox(preset="laser", block=False) is True
    assert play_beatbox(preset="throat_bass", block=False) is True
    assert play_beatbox(preset="drums", block=False) is True
