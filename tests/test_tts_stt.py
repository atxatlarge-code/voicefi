"""Unit tests for TTS and STT factory and fallbacks."""

from talk2me.config import Talk2MeConfig
from talk2me.tts import get_tts_engine, MacSayTTS, EdgeTTS
from talk2me.stt import get_stt_engine, WhisperLocalSTT, GroqSTT


def test_tts_factory_selection():
    cfg_say = Talk2MeConfig()
    cfg_say.tts.provider = "mac_say"
    engine_say = get_tts_engine(cfg_say)
    assert isinstance(engine_say, MacSayTTS)

    cfg_edge = Talk2MeConfig()
    cfg_edge.tts.provider = "edge_tts"
    engine_edge = get_tts_engine(cfg_edge)
    assert isinstance(engine_edge, EdgeTTS)


def test_stt_factory_selection():
    cfg_whisper = Talk2MeConfig()
    cfg_whisper.stt.provider = "whisper_local"
    stt_whisper = get_stt_engine(cfg_whisper)
    assert isinstance(stt_whisper, WhisperLocalSTT)

    cfg_groq = Talk2MeConfig()
    cfg_groq.stt.provider = "groq"
    cfg_groq.stt.groq_api_key = "gsk_dummy123"
    stt_groq = get_stt_engine(cfg_groq)
    assert isinstance(stt_groq, GroqSTT)
