"""
Tests for Turn Completion Readout formats, TurnSessionMemory persistent store,
and active listening spoken escalation ("tell me everything").
"""

import pytest
from voicefi.config import VoiceFiConfig, TTSConfig
from voicefi.integrations.turn_memory import TurnSessionMemory
from voicefi.integrations.active_listening import (
    ActiveListeningEngine,
    SpokenIntentCategory,
)
from voicefi.integrations.antigravity import append_character_quip
from voicefi.audio.chimes import AVAILABLE_TURN_CHIMES, play_turn_complete_chime


def test_turn_complete_config_defaults():
    cfg = VoiceFiConfig()
    assert cfg.tts.turn_complete_format == "first_sentence"
    assert cfg.tts.turn_complete_chime == "Glass"
    assert cfg.tts.character_quip_instruction is None


def test_turn_session_memory_lifecycle():
    mem = TurnSessionMemory.get_instance()
    mem.clear()

    rec = mem.record_turn(
        conv_id="test_conv_123",
        full_text="Refactored the auth module. All 18 unit tests passed with zero regressions. You are ready to deploy to staging.",
        spoken_text="Refactored the auth module.",
        agent_name="antigravity",
        format_used="first_sentence",
    )

    assert rec.conv_id == "test_conv_123"
    assert rec.agent_name == "antigravity"
    assert "All 18 unit tests passed" in rec.full_text
    assert rec.spoken_text == "Refactored the auth module."

    latest = mem.get_latest_turn("test_conv_123")
    assert latest is not None
    assert latest.conv_id == "test_conv_123"

    # Global latest check
    latest_global = mem.get_latest_turn()
    assert latest_global is not None
    assert latest_global.conv_id == "test_conv_123"

    # Full readout text retrieval
    full_text = mem.get_full_readout_text("test_conv_123")
    assert "ready to deploy to staging" in full_text

    # Clear
    mem.clear("test_conv_123")
    assert mem.get_latest_turn("test_conv_123") is None


def test_expand_readout_spoken_intents():
    phrases = [
        "tell me everything",
        "read it to me fully",
        "read it fully",
        "read the whole thing",
        "read all",
        "give me the full report",
        "give me the full story",
        "what else",
        "please tell me everything",
    ]
    for p in phrases:
        assert ActiveListeningEngine.is_expand_readout(p), f"Failed to match: {p}"
        res = ActiveListeningEngine.evaluate(p)
        assert res.category == SpokenIntentCategory.EXPAND_READOUT, f"Failed for {p}: {res.category}"
        assert res.is_actionable is True


def test_append_character_quip_heuristics():
    quip_viv = append_character_quip("Task complete.", active_agent="Viv")
    assert "Task complete." in quip_viv
    assert "All clean" in quip_viv

    quip_ricky = append_character_quip("Database updated", active_agent="Ricky Bobby")
    assert "Database updated." in quip_ricky
    assert "Shake and bake" in quip_ricky

    quip_custom = append_character_quip("Files committed.", active_agent="UnknownAgent")
    assert "Files committed." in quip_custom
    assert len(quip_custom) > len("Files committed.")


def test_available_turn_chimes():
    assert "Glass" in AVAILABLE_TURN_CHIMES
    assert "Hero" in AVAILABLE_TURN_CHIMES
    assert "Ping" in AVAILABLE_TURN_CHIMES
    assert "Pop" in AVAILABLE_TURN_CHIMES
    assert "Tink" in AVAILABLE_TURN_CHIMES

    # Ensure play_turn_complete_chime doesn't crash in test/headless mode
    play_turn_complete_chime("Glass", block=False)
    play_turn_complete_chime("NonExistentChime", block=False)
