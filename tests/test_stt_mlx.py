"""
Unit tests for Apple Silicon MLXWhisperSTT provider and STT factory routing.
"""

import pytest
import numpy as np
from voicefi.config import VoiceFiConfig
from voicefi.stt import get_stt_engine, MLXWhisperSTT


class TestMLXWhisperSTT:
    def test_factory_returns_mlx_whisper_when_configured(self):
        cfg = VoiceFiConfig()
        cfg.stt.provider = "mlx_whisper"
        engine = get_stt_engine(cfg)
        assert isinstance(engine, MLXWhisperSTT)
        assert engine.model_name == "mlx-community/whisper-large-v3-turbo"

    def test_empty_audio_handling(self):
        engine = MLXWhisperSTT()
        assert engine.transcribe(None) == ""
        assert engine.transcribe(np.array([], dtype=np.float32)) == ""

    def test_filter_hallucinations(self):
        assert MLXWhisperSTT.filter_hallucinations("Thank you.") == ""
        assert MLXWhisperSTT.filter_hallucinations("[BLANK_AUDIO]") == ""
        assert MLXWhisperSTT.filter_hallucinations("Please subscribe") == ""
        assert MLXWhisperSTT.filter_hallucinations("This is actual developer speech.") == "This is actual developer speech."

    def test_factory_auto_provider_resolves_mlx(self):
        cfg = VoiceFiConfig()
        cfg.stt.provider = "auto"
        engine = get_stt_engine(cfg)
        # On macOS ARM64 with mlx-whisper installed, auto selects MLXWhisperSTT
        import platform
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            assert isinstance(engine, MLXWhisperSTT)

    def test_transcribe_with_mocked_mlx_engine(self, monkeypatch):
        class MockMLXWhisper:
            @staticmethod
            def transcribe(audio_path, **kwargs):
                return {"text": "Refactor the kubernetes pod deployment."}

        monkeypatch.setattr("voicefi.stt.mlx_whisper.mlx_whisper", MockMLXWhisper, raising=False)
        engine = MLXWhisperSTT()
        # Mock sys.modules['mlx_whisper']
        import sys
        monkeypatch.setitem(sys.modules, "mlx_whisper", MockMLXWhisper)

        audio = np.zeros(16000, dtype=np.float32)
        result = engine.transcribe(audio)
        assert "kubernetes" in result.lower()
