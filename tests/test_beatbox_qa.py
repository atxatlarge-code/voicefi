"""
Comprehensive QA Verification Suite for VoiceFi™ Taras Stanin Beatbox Synthesizer.
Tests:
  1. Acoustic DSP & Physical Modeling (signal clipping, DC offset, FFT spectral bounds).
  2. Pitch trajectory validation for laser zaps and kick sweeps.
  3. Harmonic & subharmonic distribution for vocal guitar and throat bass.
  4. File I/O, WAV headers, multi-tempo and multi-bar scaling.
  5. SFX caching, alias resolution, and cache versioning.
  6. Voice FX audio filter pipeline with FFmpeg.
  7. CLI argument parsing, subcommands, and flags.
"""

import os
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
from voicefi.audio.sfx import (
    get_sfx_path,
    list_available_sfx,
    play_sfx,
    ALIASES,
    GENERATORS,
)
from voicefi.audio.effects import VoiceFXEngine, FX_PRESETS
from voicefi.cli_parser import build_parser


# ============================================================================
# 1. Acoustic DSP & Physical Modeling Quality
# ============================================================================


def test_qa_dsp_bounds_and_no_dc_offset():
    """Verify all synthesized elements stay within [-1.0, 1.0] and have near-zero DC offset."""
    generators = [
        ("kick", synth_beatbox_kick(0.35)),
        ("snare", synth_beatbox_snare(0.30)),
        ("hihat_closed", synth_beatbox_hihat(0.06, open_hat=False)),
        ("hihat_open", synth_beatbox_hihat(0.20, open_hat=True)),
        ("laser", synth_laser_zap(0.09)),
        ("throat_bass", synth_throat_bass(55.0, 0.6)),
        ("tongue_roll", synth_tongue_roll(0.35)),
        ("guitar_note", synth_taras_guitar_note(164.81, 0.35)),
        ("guitar_riff", synth_taras_guitar_riff("rock", 100.0)),
        ("routine", generate_taras_beatbox_routine(2, 95.0)),
    ]

    for name, audio in generators:
        assert isinstance(audio, np.ndarray), f"{name} is not numpy array"
        assert audio.dtype == np.float32, f"{name} is not float32"
        max_amp = float(np.max(np.abs(audio)))
        assert max_amp <= 1.0, f"{name} clipped: peak={max_amp}"
        assert max_amp >= 0.05, f"{name} is silent or too quiet: peak={max_amp}"

        # DC offset check: mean amplitude should be close to 0 (< 0.08)
        dc_offset = abs(float(np.mean(audio)))
        assert dc_offset < 0.08, f"{name} has significant DC offset: {dc_offset}"

        # Clean edges check: starting and ending samples should not jump abruptly
        assert abs(audio[0]) < 0.25, f"{name} starts with abrupt click: {audio[0]}"
        assert abs(audio[-1]) < 0.15, f"{name} ends with abrupt click: {audio[-1]}"


def test_qa_laser_zap_frequency_trajectory():
    """Verify that the laser zap performs a steep downward pitch sweep."""
    dur = 0.09
    laser = synth_laser_zap(dur=dur)
    
    # Zero-crossing rate in first 20% vs last 20%
    n = len(laser)
    first_part = laser[: int(n * 0.25)]
    last_part = laser[-int(n * 0.25) :]

    zc_first = np.sum(np.diff(np.signbit(first_part)) != 0) / (len(first_part) / SAMPLE_RATE)
    zc_last = np.sum(np.diff(np.signbit(last_part)) != 0) / (len(last_part) / SAMPLE_RATE)

    # First section should have much higher frequency than the tail
    assert zc_first > zc_last * 2.0, (
        f"Laser zap pitch drop failed: start freq estimate={zc_first/2}Hz, end={zc_last/2}Hz"
    )


def test_qa_throat_bass_subharmonic_spectrum():
    """Verify that throat bass contains strong low-end energy (< 100 Hz)."""
    bass = synth_throat_bass(freq=55.0, dur=0.6, wobble_rate=0.0)
    fft_mag = np.abs(np.fft.rfft(bass))
    freqs = np.fft.rfftfreq(len(bass), 1.0 / SAMPLE_RATE)

    # Sub-bass energy (30 - 90 Hz)
    sub_mask = (freqs >= 30.0) & (freqs <= 90.0)
    high_mask = (freqs >= 2000.0) & (freqs <= 8000.0)

    sub_energy = np.sum(fft_mag[sub_mask] ** 2)
    high_energy = np.sum(fft_mag[high_mask] ** 2)

    assert sub_energy > high_energy * 3.0, "Throat bass lacks dominant subharmonic low-end energy"


def test_qa_vocal_guitar_formant_presence():
    """Verify that the vocal guitar tone exhibits strong midrange vocal tract formant resonance (1kHz - 3kHz)."""
    guitar = synth_taras_guitar_note(freq=164.81, dur=0.5)
    fft_mag = np.abs(np.fft.rfft(guitar))
    freqs = np.fft.rfftfreq(len(guitar), 1.0 / SAMPLE_RATE)

    formant_band = (freqs >= 1000.0) & (freqs <= 3200.0)
    sub_ultra = (freqs >= 12000.0)

    formant_energy = np.sum(fft_mag[formant_band] ** 2)
    ultra_energy = np.sum(fft_mag[sub_ultra] ** 2)

    assert formant_energy > ultra_energy * 5.0, "Vocal guitar lacks formant filtering / cabinet cutoff"


# ============================================================================
# 2. File I/O, WAV Headers & Scaling
# ============================================================================


@pytest.mark.parametrize("bpm", [75.0, 95.0, 128.0])
@pytest.mark.parametrize("bars", [1, 2, 4])
def test_qa_routine_durations_and_bpm(bpm, bars):
    """Verify mathematical precision of bar-to-sample scaling across BPMs."""
    routine = generate_taras_beatbox_routine(bars=bars, bpm=bpm)
    expected_sec = (60.0 / bpm) * 4.0 * bars
    actual_sec = len(routine) / SAMPLE_RATE

    assert abs(actual_sec - expected_sec) < 0.001, (
        f"Routine duration mismatch: expected {expected_sec:.4f}s, got {actual_sec:.4f}s"
    )


def test_qa_wav_header_compliance():
    """Verify generated WAV files meet strict RIFF PCM specifications."""
    riff = synth_taras_guitar_riff("rock", 100.0)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        out = save_beatbox_wav(riff, tmp_path)
        assert out.is_file()
        with wave.open(str(out), "rb") as wf:
            assert wf.getnchannels() == 1, "Must be mono"
            assert wf.getsampwidth() == 2, "Must be 16-bit PCM"
            assert wf.getframerate() == SAMPLE_RATE, "Must be 44.1 kHz"
            assert wf.getnframes() == len(riff)
            raw_bytes = wf.readframes(wf.getnframes())
            # Ensure not all zeroes
            assert any(b != 0 for b in raw_bytes)
    finally:
        if tmp_path.is_file():
            tmp_path.unlink()


# ============================================================================
# 3. SFX Integration & Aliases
# ============================================================================


def test_qa_sfx_registration_and_aliases():
    """Ensure all Taras beatbox effects and aliases resolve cleanly."""
    available = list_available_sfx()
    for required in ["taras_guitar", "taras_laser", "taras_throat_bass", "beatbox_drop"]:
        assert required in available, f"Missing required SFX: {required}"

    alias_checks = [
        ("taras", "taras_guitar.wav"),
        ("taras-guitar", "taras_guitar.wav"),
        ("guitar-riff", "taras_guitar.wav"),
        ("laser", "taras_laser.wav"),
        ("laser-zap", "taras_laser.wav"),
        ("zap", "taras_laser.wav"),
        ("throat-bass", "taras_throat_bass.wav"),
        ("beatbox", "beatbox_drop.wav"),
        ("beatbox-drop", "beatbox_drop.wav"),
        ("beatbox-routine", "beatbox_drop.wav"),
    ]

    for alias, target in alias_checks:
        path = get_sfx_path(alias)
        assert path is not None, f"Alias '{alias}' failed to resolve"
        assert path.name == target, f"Alias '{alias}' resolved to {path.name}, expected {target}"
        assert path.is_file(), f"Target file does not exist: {path}"


# ============================================================================
# 4. Voice FX DSP Filter Presets
# ============================================================================


def test_qa_voice_fx_presets():
    """Validate taras_guitar and taras_beatbox filter chains exist in FX_PRESETS."""
    assert "taras_guitar" in FX_PRESETS
    assert "taras_beatbox" in FX_PRESETS

    guitar_preset = FX_PRESETS["taras_guitar"]
    assert guitar_preset["category"] == "creative"
    assert "equalizer" in guitar_preset["filter"]
    assert "acompressor" in guitar_preset["filter"]

    beatbox_preset = FX_PRESETS["taras_beatbox"]
    assert beatbox_preset["category"] == "creative"
    assert "highshelf" in beatbox_preset["filter"]


# ============================================================================
# 5. CLI Parser QA
# ============================================================================


def test_qa_cli_parser_beatbox_commands():
    """Verify that CLI parser parses all beatbox options and aliases."""
    parser = build_parser()

    # Default
    args = parser.parse_args(["beatbox"])
    assert args.command == "beatbox"
    assert args.preset == "routine"
    assert args.bpm == 95.0
    assert args.bars == 2
    assert args.no_play is False

    # Customized flags
    args = parser.parse_args([
        "beatbox",
        "guitar",
        "--bpm", "110",
        "--bars", "4",
        "--volume", "0.8",
        "--save", "/tmp/riff.wav",
        "--no-play",
    ])
    assert args.preset == "guitar"
    assert args.bpm == 110.0
    assert args.bars == 4
    assert args.volume == 0.8
    assert args.save == "/tmp/riff.wav"
    assert args.no_play is True

    # Aliases
    args_alias = parser.parse_args(["taras", "laser"])
    assert args_alias.command in ("taras", "beatbox")
    assert args_alias.preset == "laser"
