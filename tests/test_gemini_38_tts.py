"""
Unit tests for Gemini 3.8 Flash TTS and multi-speaker dialogue integration in VoiceFi.
"""

import base64
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from voicefi.config import VoiceFiConfig, GeminiConfig
from voicefi.tts.gemini_tts import GeminiTTS
from voicefi.tts import get_tts_engine


def test_gemini_config_tts_models():
    """Verify GeminiConfig includes default TTS and Lite models."""
    cfg = VoiceFiConfig()
    assert cfg.gemini.tts_model == "gemini-3.8-flash-tts"
    assert cfg.gemini.tts_lite_model == "gemini-3.8-flash-lite-tts"
    assert cfg.gemini.live_model == "gemini-3.8-live"


def test_gemini_tts_initialization():
    """Verify GeminiTTS defaults to gemini-3.8-flash-tts and supports style."""
    tts = GeminiTTS(api_key="test_key", voice="puck", style="enthusiastic")
    assert tts.voice == "Puck"
    assert tts.model == "gemini-3.8-flash-tts"
    assert tts.style == "enthusiastic"


def test_get_tts_engine_gemini_providers():
    """Verify get_tts_engine correctly differentiates gemini, gemini_lite, and gemini_live."""
    cfg = VoiceFiConfig()
    cfg.gemini.api_key = "test_key"

    # Standard gemini provider -> gemini-3.8-flash-tts
    eng_flash = get_tts_engine(cfg, provider_override="gemini", voice_override="Puck")
    assert isinstance(eng_flash, GeminiTTS)
    assert eng_flash.model == "gemini-3.8-flash-tts"

    # gemini_lite provider -> gemini-3.8-flash-lite-tts
    eng_lite = get_tts_engine(cfg, provider_override="gemini_lite", voice_override="Charon")
    assert isinstance(eng_lite, GeminiTTS)
    assert eng_lite.model == "gemini-3.8-flash-lite-tts"

    # gemini_live provider -> gemini-3.8-live
    eng_live = get_tts_engine(cfg, provider_override="gemini_live", voice_override="Aoede")
    assert isinstance(eng_live, GeminiTTS)
    assert eng_live.model == "gemini-3.8-live"


def test_gemini_tts_single_speaker_style_payload():
    """Verify _generate_audio_bytes sends speech_metadata when style is provided."""
    tts = GeminiTTS(api_key="test_key", voice="Puck")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    dummy_wav = b"RIFF....WAVEfmt ...."
    b64_wav = base64.b64encode(dummy_wav).decode("utf-8")
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"inlineData": {"mimeType": "audio/wav", "data": b64_wav}}]
                }
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        audio = tts._generate_audio_bytes("Hello world!", style="excited and energetic")
        assert audio == dummy_wav

        call_args = mock_post.call_args
        assert call_args is not None
        body = call_args[1]["json"]
        parts = body["contents"][0]["parts"]
        assert len(parts) == 1
        assert parts[0]["text"] == "Hello world!"
        assert parts[0]["speech_metadata"] == {"style": "excited and energetic"}


def test_gemini_tts_multi_speaker_dialogue_payload():
    """Verify generate_dialogue_bytes constructs multi_speaker_voice_config and speech_metadata."""
    tts = GeminiTTS(api_key="test_key", voice="Puck")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    dummy_wav = b"RIFF....WAVEfmt ....DIALOGUE"
    b64_wav = base64.b64encode(dummy_wav).decode("utf-8")
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"inlineData": {"mimeType": "audio/wav", "data": b64_wav}}]
                }
            }
        ]
    }

    turns = [
        {"speaker": "Antigravity", "text": "What do you think of Gemini 3.8?", "style": "curious"},
        {"speaker": "Claude", "text": "The expressive control is outstanding.", "style": "scholarly"},
    ]
    speakers = {"Antigravity": "Puck", "Claude": "Charon"}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        audio = tts.generate_dialogue_bytes(turns, speakers=speakers)
        assert audio == dummy_wav

        call_args = mock_post.call_args
        assert call_args is not None
        body = call_args[1]["json"]

        # Verify multi_speaker_voice_config
        multi_config = body["generationConfig"]["speechConfig"]["multi_speaker_voice_config"]
        configs = multi_config["speaker_voice_configs"]
        assert len(configs) == 2
        assert configs[0]["speaker"] == "Antigravity"
        assert configs[0]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Puck"
        assert configs[1]["speaker"] == "Claude"
        assert configs[1]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Charon"

        # Verify parts and metadata
        parts = body["contents"][0]["parts"]
        assert len(parts) == 2
        assert parts[0]["text"] == "What do you think of Gemini 3.8?"
        assert parts[0]["speech_metadata"] == {"speaker": "Antigravity", "style": "curious"}
        assert parts[1]["text"] == "The expressive control is outstanding."
        assert parts[1]["speech_metadata"] == {"speaker": "Claude", "style": "scholarly"}


def test_synthesize_dialogue_to_file(tmp_path: Path):
    """Verify synthesize_dialogue_to_file writes audio bytes to output file."""
    tts = GeminiTTS(api_key="test_key", voice="Puck")
    dummy_wav = b"RIFF....WAVEfmt ....TEST_OUTPUT"

    with patch.object(tts, "generate_dialogue_bytes", return_value=dummy_wav):
        out_file = tmp_path / "test_dialogue.wav"
        success = tts.synthesize_dialogue_to_file(
            [{"speaker": "A", "text": "Hi"}],
            output_path=out_file
        )
        assert success is True
        assert out_file.exists()
        assert out_file.read_bytes() == dummy_wav
