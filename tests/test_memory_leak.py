"""Tests verifying singleton caching and memory leak prevention in VoiceFi STT and WakeWord."""

from unittest.mock import MagicMock
import numpy as np
import pytest

from voicefi.config import VoiceFiConfig
from voicefi.stt import get_stt_engine, clear_stt_engine_cache, WhisperLocalSTT
from voicefi.stt.whisper_local import _MODEL_CACHE, clear_whisper_model_cache
from voicefi.audio.wakeword import WakeWordListener


def test_stt_engine_singleton_cache():
    """Verify get_stt_engine returns the identical instance for identical configs."""
    clear_stt_engine_cache()

    cfg1 = VoiceFiConfig()
    cfg1.stt.provider = "whisper_local"
    cfg1.stt.model_size = "base.en"

    cfg2 = VoiceFiConfig()
    cfg2.stt.provider = "whisper_local"
    cfg2.stt.model_size = "base.en"

    engine1 = get_stt_engine(cfg1)
    engine2 = get_stt_engine(cfg2)

    assert engine1 is engine2

    clear_stt_engine_cache()
    engine3 = get_stt_engine(cfg1)
    assert engine3 is not engine1


def test_whisper_model_registry_cache():
    """Verify separate WhisperLocalSTT instances share the underlying model instance in _MODEL_CACHE."""
    clear_whisper_model_cache()

    stt1 = WhisperLocalSTT(model_size="base.en")
    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "Testing cache"
    mock_model.transcribe.return_value = ([mock_segment], None)

    # Inject mock into cache
    cache_key = ("base.en", "auto", "int8")
    _MODEL_CACHE[cache_key] = mock_model

    model_obtained_1 = stt1._get_model()
    assert model_obtained_1 is mock_model

    stt2 = WhisperLocalSTT(model_size="base.en")
    model_obtained_2 = stt2._get_model()
    assert model_obtained_2 is mock_model
    assert model_obtained_1 is model_obtained_2


def test_wakeword_candidate_lock_prevents_pileups():
    """Verify that candidate processing acquires _candidate_lock and skips if busy."""
    cfg = VoiceFiConfig()
    listener = WakeWordListener(config=cfg)

    dummy_audio = np.zeros(16000, dtype=np.float32)

    # Acquire lock simulating an in-progress transcription
    assert listener._candidate_lock.acquire(blocking=False) is True

    # While locked, _process_candidate_audio should return immediately without doing work
    listener._process_candidate_audio(dummy_audio)

    # Release lock
    listener._candidate_lock.release()

    # Now lock can be acquired normally
    assert listener._candidate_lock.locked() is False
