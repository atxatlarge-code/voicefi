"""
Unit tests for Native macOS Apple Hardware VoiceProcessingIO (VPIO) Audio Stream and AEC.
"""

from unittest.mock import MagicMock, patch
import pytest
import numpy as np

from voicefi.audio.native_vpio import (
    is_vpio_supported,
    NativeVoiceProcessingStream,
)
from voicefi.audio.echo_canceller import (
    is_hardware_aec_active,
    get_echo_cancellation_info,
    is_acoustic_echo,
)
from voicefi.audio.recorder import AudioRecorder, resolve_barge_in_mode
from voicefi.audio.device import get_audio_device_profile


def test_is_vpio_supported():
    """Verify is_vpio_supported runs without error and returns a boolean."""
    supported = is_vpio_supported()
    assert isinstance(supported, bool)


def test_echo_canceller_hardware_aec():
    """Verify echo canceller reports hardware AEC support and diagnostic profile."""
    active = is_hardware_aec_active()
    assert isinstance(active, bool)

    info = get_echo_cancellation_info()
    assert "hardware_aec_supported" in info
    assert "hardware_aec_backend" in info
    assert "active_isolation_mode" in info


def test_audio_device_profile_includes_aec():
    """Verify get_audio_device_profile includes hardware AEC attributes."""
    profile = get_audio_device_profile()
    assert "hardware_aec_supported" in profile
    assert "hardware_aec_backend" in profile


def test_resolve_barge_in_mode_with_vpio():
    """Verify resolve_barge_in_mode pauses mic on built-in laptop speakers to keep playback loud & unmuted."""
    with patch("voicefi.audio.recorder.is_using_builtin_speakers", return_value=True):
        is_active, is_safe = resolve_barge_in_mode("auto")
        assert is_active is False
        assert is_safe is True

    with patch("voicefi.audio.recorder.is_using_builtin_speakers", return_value=False):
        is_active, is_safe = resolve_barge_in_mode("auto")
        assert is_active is True
        assert is_safe is False


def test_audio_recorder_stream_factory():
    """Verify AudioRecorder._create_input_stream uses sounddevice InputStream."""
    rec = AudioRecorder(sample_rate=16000)

    with patch("sounddevice.InputStream") as mock_sd_stream:
        stream = rec._create_input_stream()
        assert mock_sd_stream.called


def test_native_vpio_stream_mock_lifecycle():
    """Verify NativeVoiceProcessingStream mock lifecycle and reading."""
    stream = NativeVoiceProcessingStream(target_sample_rate=16000)
    assert stream.target_sample_rate == 16000
    assert not stream._is_running

    # Test reading when not running produces zero array
    chunk, overflowed = stream.read(800)
    assert len(chunk) == 800
    assert not overflowed
    assert np.all(chunk == 0)


@pytest.mark.skipif(not is_vpio_supported(), reason="Requires macOS hardware VoiceProcessingIO")
def test_native_vpio_live_stream_capture():
    """Live integration test: capture a real buffer using Apple VoiceProcessingIO."""
    stream = NativeVoiceProcessingStream(target_sample_rate=16000, buffer_size=1024)
    with stream:
        assert stream._is_running
        chunk, overflowed = stream.read(800, timeout=0.6)
        assert len(chunk) == 800
        assert isinstance(chunk, np.ndarray)
        assert chunk.dtype == np.float32

    assert not stream._is_running
