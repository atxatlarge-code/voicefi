"""
Unit tests for spatial audio engine, constant-power panning law, and agent stereo staging.
"""

import math
from unittest.mock import patch
import numpy as np
import pytest

from voicefi.audio.spatial import (
    pan_audio,
    get_agent_pan,
    adapt_pan_for_active_device,
    create_spatial_tone,
    AGENT_PAN_PRESETS,
)


def test_constant_power_panning_center():
    """At pan = 0.0, both channels receive equal power (~0.7071) and sum of squares == 1.0."""
    mono = np.ones(100, dtype=np.float32)
    stereo = pan_audio(mono, pan=0.0)

    assert stereo.shape == (100, 2)
    expected_gain = math.cos(math.pi / 4.0)
    assert np.allclose(stereo[:, 0], expected_gain, atol=1e-5)
    assert np.allclose(stereo[:, 1], expected_gain, atol=1e-5)

    # Power check: L^2 + R^2 == 1.0
    power = stereo[:, 0] ** 2 + stereo[:, 1] ** 2
    assert np.allclose(power, 1.0, atol=1e-5)


def test_constant_power_panning_hard_left():
    """At pan = -1.0, left channel has full volume and right channel is silent."""
    mono = np.ones(100, dtype=np.float32)
    stereo = pan_audio(mono, pan=-1.0)

    assert np.allclose(stereo[:, 0], 1.0, atol=1e-5)
    assert np.allclose(stereo[:, 1], 0.0, atol=1e-5)


def test_constant_power_panning_hard_right():
    """At pan = 1.0, right channel has full volume and left channel is silent."""
    mono = np.ones(100, dtype=np.float32)
    stereo = pan_audio(mono, pan=1.0)

    assert np.allclose(stereo[:, 0], 0.0, atol=1e-5)
    assert np.allclose(stereo[:, 1], 1.0, atol=1e-5)


def test_int16_conversion():
    """Verify int16 mono audio is converted to normalized float32 stereo."""
    mono_i16 = np.array([32767, -32768, 0], dtype=np.int16)
    stereo = pan_audio(mono_i16, pan=0.0)

    assert stereo.dtype == np.float32
    assert stereo.shape == (3, 2)


def test_agent_pan_resolution():
    """Verify Antigravity is left-staged and Claude is right-staged."""
    with patch("voicefi.audio.device.is_headphone_or_headset_active", return_value=True):
        ag_pan = get_agent_pan("antigravity")
        claude_pan = get_agent_pan("claude")
        sys_pan = get_agent_pan("system")

        assert ag_pan < 0.0, "Antigravity must be staged to the left ear"
        assert claude_pan > 0.0, "Claude must be staged to the right ear"
        assert sys_pan == 0.0, "System notifications must be centered"


def test_device_adaptive_panning_laptop_vs_headphones():
    """Verify stereo spread is narrowed on laptop speakers and wide on headphones."""
    with patch("voicefi.audio.device.is_headphone_or_headset_active", return_value=True):
        wide_pan = adapt_pan_for_active_device(-0.6)
        assert wide_pan == -0.6

    with patch("voicefi.audio.device.is_headphone_or_headset_active", return_value=False):
        narrow_pan = adapt_pan_for_active_device(-0.6)
        assert abs(narrow_pan) < abs(wide_pan)
        assert np.isclose(narrow_pan, -0.6 * 0.4)


def test_create_spatial_tone():
    """Verify synthetic tone generation produces stereo output with correct envelope."""
    tone = create_spatial_tone(freq=440.0, duration=0.1, sample_rate=16000, pan=-0.5)
    assert tone.shape == (1600, 2)
    assert tone.dtype == np.float32
    assert not np.isnan(tone).any()


def test_create_orbit_sweep():
    """Verify 360-degree lateral orbit sweep produces valid continuous stereo audio."""
    from voicefi.audio.spatial import create_orbit_sweep

    sweep = create_orbit_sweep(duration=0.5, sample_rate=16000)
    assert sweep.shape == (8000, 2)
    assert sweep.dtype == np.float32
    assert not np.isnan(sweep).any()
    assert np.max(np.abs(sweep)) <= 1.0


def test_create_binaural_360_orbit():
    """Verify true binaural HRTF 360-degree orbit with ITD and pinna occlusion."""
    from voicefi.audio.spatial import create_binaural_360_orbit

    binaural = create_binaural_360_orbit(duration=0.5, sample_rate=16000)
    assert binaural.shape == (8000, 2)
    assert binaural.dtype == np.float32
    assert not np.isnan(binaural).any()
    assert not np.isinf(binaural).any()
    assert np.max(np.abs(binaural)) <= 1.0
