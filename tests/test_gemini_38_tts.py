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


def test_clean_character_statement_deduplication():
    """Verify clean_character_statement prevents repetition of the first sentence."""
    from voicefi.tts.gemini_tts import clean_character_statement

    first_sentence = "All unit tests have passed successfully."

    # Case 1: Model repeats first sentence verbatim before statement
    raw_repeated = "All unit tests have passed successfully. [bark] Outstanding work cadet!"
    cleaned = clean_character_statement(raw_repeated, first_sentence=first_sentence)
    assert cleaned == "[bark] Outstanding work cadet!"

    # Case 2: Model wraps reaction in XML tags
    raw_xml = "<reaction>[chuckle] Not too shabby for a human.</reaction>"
    cleaned = clean_character_statement(raw_xml, first_sentence=first_sentence)
    assert cleaned == "[chuckle] Not too shabby for a human."

    # Case 3: Model outputs Sentence 1 and Sentence 2 prefixes
    raw_prefix = "Sentence 1: All unit tests have passed.\nSentence 2: [bark] Drop and give me twenty!"
    cleaned = clean_character_statement(raw_prefix, first_sentence="All unit tests have passed.")
    assert cleaned == "[bark] Drop and give me twenty!"

    # Case 4: Model outputs quotes
    raw_quotes = '"[sigh] Finally done with the refactor."'
    cleaned = clean_character_statement(raw_quotes, first_sentence=first_sentence)
    assert cleaned == "[sigh] Finally done with the refactor."

    # Case 5: Normalizes [sighs] to [sigh]
    raw_sighs = "[sighs] Another bug bites the dust."
    cleaned = clean_character_statement(raw_sighs, first_sentence=first_sentence)
    assert cleaned == "[sigh] Another bug bites the dust."

    # Case 6: Model leaves <reaction> tag unclosed
    raw_unclosed = "<reaction>Looks like another cold case closed in this town"
    cleaned = clean_character_statement(raw_unclosed, first_sentence=first_sentence)
    assert cleaned == "Looks like another cold case closed in this town."

    # Case 7: Model omits terminal punctuation
    raw_nopunct = "Not too bad for a rookie"
    cleaned = clean_character_statement(raw_nopunct, first_sentence=first_sentence)
    assert cleaned == "Not too bad for a rookie."


def test_character_prompt_template_customization():
    """Verify custom character prompt templates format accurately."""
    from voicefi.tts.gemini_tts import DEFAULT_CHARACTER_PROMPT_TEMPLATE

    formatted_default = DEFAULT_CHARACTER_PROMPT_TEMPLATE.format(
        character_persona="Drill Sergeant",
        first_sentence="Build succeeded.",
        context="Full pytest suite completed.",
    )
    assert "Drill Sergeant" in formatted_default
    assert "Build succeeded." in formatted_default
    assert "<reaction>...</reaction>" in formatted_default

    custom_tmpl = "Role: {character_persona}\nContext: {context}\nPrev: {first_sentence}\nSay reaction in tags:"
    formatted_custom = custom_tmpl.format(
        character_persona="Shakespearean",
        first_sentence="Build succeeded.",
        context="All green.",
    )
    assert "Role: Shakespearean" in formatted_custom
    assert "Prev: Build succeeded." in formatted_custom


def test_truncate_or_summarize_sentence():
    """Verify long sentences are cut off cleanly at natural clause or word boundaries."""
    from voicefi.tts.gemini_tts import truncate_or_summarize_sentence

    # Short sentence is unchanged
    short_s = "I have fixed the issue."
    assert truncate_or_summarize_sentence(short_s, max_words=18) == short_s

    # Long sentence with a natural comma clause break
    long_s_comma = (
        "I have updated the test configuration files, refactored all nineteen integration tests "
        "to use the new mock server, and verified that everything compiles without errors."
    )
    res_comma = truncate_or_summarize_sentence(long_s_comma, max_words=18)
    assert res_comma == "I have updated the test configuration files."

    # Long sentence with an em-dash break
    long_s_dash = (
        "All integration tests passed with zero errors — the background worker pool is now "
        "completely stable and ready for deployment."
    )
    res_dash = truncate_or_summarize_sentence(long_s_dash, max_words=18)
    assert res_dash == "All integration tests passed with zero errors."

    # Long sentence with no punctuation breaks cuts off cleanly at word limit with trailing connectors removed
    long_s_runon = (
        "The background deployment job finished packaging all microservice containers and pushed the "
        "updated container images to the internal enterprise cloud repository for"
    )
    res_runon = truncate_or_summarize_sentence(long_s_runon, max_words=15)
    assert len(res_runon.split()) <= 15
    assert res_runon.endswith(".")
    assert not res_runon.lower().endswith("for.")


def test_extract_first_sentence_long_sentence_handling():
    """Verify extract_first_sentence cuts off long first sentences cleanly."""
    from voicefi.tts.gemini_tts import extract_first_sentence

    text = (
        "We have completed the full database schema migration, indexed eleven slow query patterns, "
        "and validated that the API endpoints respond within ten milliseconds. Next steps include..."
    )
    result = extract_first_sentence(text, max_words=12)
    assert len(result.split()) <= 12
    assert result.endswith(".")
    assert result == "We have completed the full database schema migration."


def test_clean_markdown_for_speech_full_read_vs_standard():
    """Verify full_read=True preserves the entire response while full_read=False filters/truncates."""
    from voicefi.integrations.antigravity import clean_markdown_for_speech

    multi_sentence_text = (
        "You ask a 70B cloud model to fix a bug. It refactors half your repo, introduces three "
        "new design patterns, and bills you $4.00. You ask a 1.5B local model to fix a bug. "
        "It doesn't fix the code—it hands you a clipboard and asks you to hold its juice."
    )

    # 1. Standard mode: filtered and truncated to 1-2 sentences / target_max_words
    res_standard = clean_markdown_for_speech(multi_sentence_text, max_words=20, full_read=False)
    assert "clipboard" not in res_standard
    assert "You ask a 70B" in res_standard

    # 2. Live API mode: full_read=True preserves ALL sentences and punchlines verbatim!
    res_live = clean_markdown_for_speech(multi_sentence_text, max_words=20, full_read=True)
    assert "You ask a 70B cloud model to fix a bug" in res_live
    assert "bills you \\$4.00" in res_live or "bills you $4.00" in res_live
    assert "hands you a clipboard and asks you to hold its juice" in res_live


def test_live_turn_origin_lifecycle():
    """Verify set_live_turn_origin, peek_live_turn_origin, and pop_live_turn_origin."""
    from voicefi.integrations.turn_lock import (
        set_live_turn_origin,
        peek_live_turn_origin,
        pop_live_turn_origin,
    )

    cid = "test-conv-live-1234"
    assert peek_live_turn_origin(cid) is False

    set_live_turn_origin(cid)
    assert peek_live_turn_origin(cid) is True
    assert peek_live_turn_origin(cid) is True  # Non-destructive

    assert pop_live_turn_origin(cid) is True   # Consumes marker
    assert peek_live_turn_origin(cid) is False # Now cleared


