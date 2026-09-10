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


def test_recorder_config_defaults():
    """Verify AudioRecorder pulls VAD defaults from config if not specified."""
    recorder = AudioRecorder()
    assert recorder.vad is not None
    assert recorder.vad_engine in ("auto", "silero")
    assert recorder.speech_threshold > 0.0


def test_wakeword_listener_pause_all_and_resume_all():
    """Verify WakeWordListener tracking and bulk pause/resume."""
    from voicefi.audio.wakeword import WakeWordListener

    listener = WakeWordListener()
    assert listener in WakeWordListener._ACTIVE_INSTANCES
    assert listener._paused is False

    WakeWordListener.pause_all()
    assert listener._paused is True
    assert listener._current_state == "paused"

    WakeWordListener.resume_all()
    assert listener._paused is False
    assert listener._current_state == "listening"

    listener.stop()
    assert listener not in WakeWordListener._ACTIVE_INSTANCES


def test_silence_gate_speech_preservation():
    """Verify speech chunk at normal speaking volume (~0.012 RMS) is not suppressed."""
    vad = VoiceActivityDetector(engine="auto", speech_threshold=0.35, energy_threshold=0.005)

    # Synthesize sine wave at ~0.012 RMS (amplitude ~ 0.017)
    t = np.linspace(0, 0.05, 800, endpoint=False)
    speech_chunk = (0.017 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    for _ in range(3):
        res = vad.process(speech_chunk)

    # Energy should be ~0.012
    assert 0.010 <= res["energy"] <= 0.015
    # Running noise floor should not spike to absorb the speech chunk
    assert vad.running_noise_floor <= 0.008


def test_whisper_transcribe_none_safety():
    """Verify WhisperLocalSTT safely returns empty string when passed None or empty input."""
    from voicefi.stt.whisper_local import WhisperLocalSTT

    stt = WhisperLocalSTT()
    assert stt.transcribe(None) == ""
    assert stt.transcribe(np.zeros(0, dtype=np.float32)) == ""
    assert stt.transcribe(Path("/tmp/non_existent_file_12345.wav")) == ""


def test_record_speech_auto_manual_stop_preserves_audio():
    """Verify record_speech_auto does not discard audio when trigger_stop is set manually."""
    import threading
    from voicefi.audio.recorder import AudioRecorder

    rec = AudioRecorder(vad_engine="energy", energy_threshold=0.001)
    stop_evt = threading.Event()

    # Mock _create_input_stream to return 10 chunks of synthetic speech then set stop_evt
    chunk = (0.05 * np.ones(800, dtype=np.float32))

    class MockStream:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            self.calls += 1
            if self.calls >= 5:
                stop_evt.set()
            return chunk.reshape(-1, 1), False

    with patch.object(rec, "_create_input_stream", return_value=MockStream()):
        audio_data, temp_wav = rec.record_speech_auto(stop_event=stop_evt)
        try:
            assert temp_wav is not None
            assert temp_wav.is_file()
            assert len(audio_data) > 0
        finally:
            if temp_wav and temp_wav.is_file():
                temp_wav.unlink(missing_ok=True)


def test_call_detection_guards_antigravity_and_claude():
    """Verify that active call detection suppresses both speech and microphone auto-listening."""
    from unittest.mock import patch
    from voicefi.integrations.claude import handle_claude_stop_hook
    from voicefi.integrations.antigravity import handle_antigravity_stop_hook

    with patch("voicefi.audio.meeting_detection.is_user_on_call", return_value=True):
        # Claude hook should return early with on_call status
        res_claude = handle_claude_stop_hook({"message": "Hello from Claude"})
        assert res_claude.get("status") == "on_call"

        # Antigravity hook should return empty dict early without recording
        res_agy = handle_antigravity_stop_hook({"conversation_id": "test-123"})
        assert res_agy == {}



