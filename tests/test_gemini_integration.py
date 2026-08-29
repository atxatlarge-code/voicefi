"""
Unit tests for Google Gemini Live & GenAI Intelligence integration in VoiceFi.
Validates config models, voice catalog resolution, intelligence fallback, and TTS provider.
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from voicefi.config import VoiceFiConfig, GeminiConfig, load_config
from voicefi.tts.catalog import find_persona, get_curated_personas
from voicefi.tts.gemini_tts import GeminiTTS
from voicefi.tts import get_tts_engine
from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.memo.synthesizer import MemoSynthesizer


def test_gemini_config_defaults():
    """Verify GeminiConfig has expected defaults and integrates into VoiceFiConfig."""
    cfg = VoiceFiConfig()
    assert hasattr(cfg, "gemini")
    assert cfg.gemini.enabled is True
    assert cfg.gemini.model == "gemini-2.5-flash"
    assert cfg.gemini.live_model == "gemini-2.0-flash-exp"
    assert cfg.gemini.live_voice == "Aoede"
    assert "gemini" in cfg.agents
    assert cfg.agents["gemini"].voice == "Aoede"
    assert cfg.agents["gemini"].provider == "gemini"


def test_gemini_curated_personas():
    """Verify Google Gemini neural voices exist in curated personas and can be resolved."""
    gemini_personas = get_curated_personas(provider="gemini")
    assert len(gemini_personas) >= 5

    voice_names = [p.name for p in gemini_personas]
    for expected in ["Aoede", "Puck", "Charon", "Kore", "Fenrir"]:
        assert expected in voice_names

    p = find_persona("Aoede")
    assert p is not None
    assert p.name == "Aoede"
    assert p.provider == "gemini"

    p_puck = find_persona("puck")
    assert p_puck is not None
    assert p_puck.name == "Puck"


def test_gemini_intelligence_offline_fallback():
    """Verify GeminiIntelligenceEngine gracefully handles missing API key."""
    cfg = VoiceFiConfig()
    cfg.gemini.api_key = ""
    with patch.dict("os.environ", {}, clear=True):
        engine = GeminiIntelligenceEngine(cfg)
        assert engine.is_available() is False
        assert engine.distill_spoken_soundbite("Long test text") is None
        assert engine.structure_voice_memo("Some ramble") is None
        assert engine.resolve_phonetic_code("auth", ["auth_middleware.py"]) is None


def test_gemini_intelligence_mock_distillation():
    """Verify GeminiIntelligenceEngine distill_spoken_soundbite parses responses properly."""
    cfg = VoiceFiConfig()
    cfg.gemini.api_key = "test_fake_key"
    engine = GeminiIntelligenceEngine(cfg)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "I refactored the auth module and all 14 tests pass."}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp):
        soundbite = engine.distill_spoken_soundbite("```python\ndef test(): pass\n```\nAll 14 tests pass.")
        assert soundbite == "I refactored the auth module and all 14 tests pass."


def test_gemini_tts_initialization_and_voices():
    """Verify GeminiTTS initializes properly and normalizes voice names."""
    tts = GeminiTTS(api_key="test_key", voice="puck")
    assert tts.voice == "Puck"

    tts_fenrir = GeminiTTS(api_key="test_key", voice="FENRIR")
    assert tts_fenrir.voice == "Fenrir"

    tts_unknown = GeminiTTS(api_key="test_key", voice="nonexistent")
    assert tts_unknown.voice == "Aoede"


def test_get_tts_engine_gemini():
    """Verify get_tts_engine returns GeminiTTS when provider is gemini."""
    cfg = VoiceFiConfig()
    cfg.tts.provider = "gemini"
    cfg.tts.voice = "Aoede"

    engine = get_tts_engine(cfg, agent_name="gemini")
    assert isinstance(engine, GeminiTTS)
    assert engine.voice == "Aoede"


def test_clean_markdown_for_speech_resilience():
    """Verify clean_markdown_for_speech runs reliably without crashing."""
    raw_markdown = "### Summary\n- Modified `src/main.py`\n- Passed 10 tests.\n\n```python\nprint('done')\n```"
    result = clean_markdown_for_speech(raw_markdown)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "```" not in result


def test_memo_synthesizer_structured():
    """Verify MemoSynthesizer can handle structured synthesis calls gracefully."""
    cfg = VoiceFiConfig()
    synth = MemoSynthesizer(cfg)
    # When no API key is present, should return None cleanly
    structured = synth.synthesize_structured("We should add a database caching layer.")
    assert structured is None
