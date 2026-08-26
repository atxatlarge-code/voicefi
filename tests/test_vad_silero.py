"""
Unit and integration tests for Silero VAD (Voice Activity Detection) in VoiceFi.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

from voicefi.config import VoiceFiConfig, VADConfig
from voicefi.audio.vad import (
    SileroVAD,
    VoiceActivityDetector,
    find_silero_vad_model,
)
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.ambient import AmbientAudioStream


def test_vad_config_defaults():
    """Verify default VAD config includes silero engine and speech threshold."""
    cfg = VADConfig()
    assert cfg.engine in ("silero", "auto")
    assert cfg.speech_threshold == 0.5
    assert cfg.sample_rate == 16000


def test_find_silero_vad_model():
    """Verify discovery of bundled or faster-whisper silero_vad_v6.onnx model."""
    model_path = find_silero_vad_model()
    assert model_path is not None
    assert model_path.exists()
    assert model_path.stat().st_size > 100_000


def test_silero_vad_inference_streaming():
    """Verify SileroVAD runs inference on 16kHz audio chunks and tracks recurrent state."""
    vad = SileroVAD(sample_rate=16000, threshold=0.5)
    assert vad.is_available is True

    # 1. Test silent chunk (50ms = 800 samples)
    silence = np.zeros(800, dtype=np.float32)
    is_speech, prob = vad.process_chunk(silence)
    assert isinstance(is_speech, (bool, np.bool_))
    assert isinstance(prob, float)
    assert prob < 0.2
    assert is_speech is False

    # 2. Test noisy chunk
    noise = np.random.randn(800).astype(np.float32) * 0.005
    is_speech_noise, prob_noise = vad.process_chunk(noise)
    assert prob_noise < 0.4
    assert is_speech_noise is False

    # 3. Test reset clears state
    vad.reset()
    assert np.all(vad._h == 0.0)
    assert np.all(vad._c == 0.0)
    assert np.all(vad._context == 0.0)


def test_voice_activity_detector_modes():
    """Verify VoiceActivityDetector handles 'silero', 'energy', and 'auto' modes."""
    # Auto mode -> selects silero if model found
    vad_auto = VoiceActivityDetector(engine="auto")
    assert vad_auto.active_engine == "silero"

    # Energy mode -> forces energy engine
    vad_energy = VoiceActivityDetector(engine="energy")
    assert vad_energy.active_engine == "energy"

    # Test processing in silero mode
    chunk = np.zeros(800, dtype=np.float32)
    res_silero = vad_auto.process(chunk)
    assert res_silero["engine"] == "silero"
    assert "confidence" in res_silero
    assert "energy" in res_silero
    assert "is_speech" in res_silero

    # Test processing in energy mode
    res_energy = vad_energy.process(chunk)
    assert res_energy["engine"] == "energy"
    assert res_energy["is_speech"] is False


def test_silero_vad_fallback_on_missing_model():
    """Verify graceful fallback to energy VAD when ONNX model is missing."""
    with patch("voicefi.audio.vad.find_silero_vad_model", return_value=None):
        vad = VoiceActivityDetector(engine="auto")
        assert vad.active_engine == "energy"

        chunk = np.random.randn(800).astype(np.float32) * 0.05
        res = vad.process(chunk)
        assert res["engine"] == "energy"
        assert "is_speech" in res


def test_vad_benchmark():
    """Verify VAD benchmark measures microsecond latency."""
    vad = VoiceActivityDetector(engine="silero")
    bench = vad.benchmark(num_frames=20)
    assert bench["available"] is True
    assert bench["engine"] == "silero"
    assert bench["avg_latency_ms"] < 2.0  # Should be ~0.1ms on modern hardware
    assert bench["throughput_frames_per_sec"] > 500


def test_recorder_initializes_with_vad():
    """Verify AudioRecorder initializes with VoiceActivityDetector."""
    recorder = AudioRecorder(vad_engine="silero", speech_threshold=0.5)
    assert recorder.vad is not None
    assert recorder.vad.active_engine == "silero"


def test_ambient_stream_initializes_with_vad():
    """Verify AmbientAudioStream initializes with VoiceActivityDetector."""
    stream = AmbientAudioStream(vad_engine="silero", speech_threshold=0.5)
    assert stream.vad is not None
    assert stream.vad.active_engine == "silero"
