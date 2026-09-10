"""Unit tests for TTS and STT factory and fallbacks."""

from voicefi.config import VoiceFiConfig
from voicefi.tts import get_tts_engine, MacSayTTS, EdgeTTS
from voicefi.stt import get_stt_engine, WhisperLocalSTT, GroqSTT


def test_tts_factory_selection():
    cfg_say = VoiceFiConfig()
    cfg_say.tts.provider = "mac_say"
    engine_say = get_tts_engine(cfg_say)
    assert isinstance(engine_say, MacSayTTS)

    cfg_edge = VoiceFiConfig()
    cfg_edge.tts.provider = "edge_tts"
    engine_edge = get_tts_engine(cfg_edge)
    assert isinstance(engine_edge, EdgeTTS)


def test_stt_factory_selection():
    cfg_whisper = VoiceFiConfig()
    cfg_whisper.stt.provider = "whisper_local"
    stt_whisper = get_stt_engine(cfg_whisper)
    assert isinstance(stt_whisper, WhisperLocalSTT)

    cfg_groq = VoiceFiConfig()
    cfg_groq.stt.provider = "groq"
    cfg_groq.stt.groq_api_key = "gsk_dummy123"
    stt_groq = get_stt_engine(cfg_groq)
    assert isinstance(stt_groq, GroqSTT)


def test_whisper_local_anti_repetition_params():
    """Verify that WhisperLocalSTT passes anti-repetition parameters to faster-whisper."""
    from unittest.mock import MagicMock
    import numpy as np

    stt = WhisperLocalSTT(model_size="base.en")
    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "Hello world"
    mock_model.transcribe.return_value = ([mock_segment], None)
    stt._model = mock_model

    dummy_audio = np.zeros(16000, dtype=np.float32)
    result = stt.transcribe(dummy_audio)

    assert result.strip().lower() == "hello world"
    mock_model.transcribe.assert_called_once()
    _, kwargs = mock_model.transcribe.call_args
    assert kwargs.get("condition_on_previous_text") is False
    assert kwargs.get("repetition_penalty") == 1.15
    assert kwargs.get("no_repeat_ngram_size") == 3
    assert kwargs.get("vad_parameters") == {"min_silence_duration_ms": 500}


def test_whisper_local_hallucination_filter():
    """Verify that filter_hallucinations catches Whisper silence artifacts and preserves developer speech."""
    # Suppressed hallucinations
    assert WhisperLocalSTT.filter_hallucinations("[BLANK_AUDIO]") == ""
    assert WhisperLocalSTT.filter_hallucinations("[applause]") == ""
    assert WhisperLocalSTT.filter_hallucinations("(silence)") == ""
    assert WhisperLocalSTT.filter_hallucinations("Thank you.") == ""
    assert WhisperLocalSTT.filter_hallucinations("Thanks for watching!") == ""
    assert WhisperLocalSTT.filter_hallucinations("Please subscribe.") == ""
    assert WhisperLocalSTT.filter_hallucinations("you") == ""
    assert WhisperLocalSTT.filter_hallucinations("...") == ""
    assert WhisperLocalSTT.filter_hallucinations("Subtitles by Amara.org") == ""

    # Preserved real speech
    assert WhisperLocalSTT.filter_hallucinations("Thank you for fixing the bug") == "Thank you for fixing the bug"
    assert WhisperLocalSTT.filter_hallucinations("Run the test suite now") == "Run the test suite now"
    assert WhisperLocalSTT.filter_hallucinations("git checkout -b feature") == "git checkout -b feature"


