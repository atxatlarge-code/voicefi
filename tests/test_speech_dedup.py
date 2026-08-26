"""
Tests for VoiceFi Turn Identity, TTS Deduplication, and Self-Echo Suppression.
"""

import time
import pytest
from pathlib import Path
from voicefi.integrations.conversations import claim_turn, get_claimed_turn_origin
from voicefi.tts.base import (
    speech_turn_lock,
    is_duplicate_speech,
    record_recent_speech,
    DuplicateSpeechSuppressed,
    RECENT_SPEECH_FILE,
)
from voicefi.audio.echo_canceller import record_agent_spoken, is_acoustic_echo, clear_agent_spoken_history


def test_claim_turn_with_step_index(tmp_path, monkeypatch):
    turn_file = tmp_path / "active_turns.json"
    lock_file = tmp_path / "active_turns.lock"
    monkeypatch.setattr("voicefi.integrations.conversations.Path", lambda p: turn_file if "active_turns.json" in str(p) else (lock_file if "active_turns.lock" in str(p) else Path(p)))

    # First claim for step 10 succeeds
    res1 = claim_turn("conv-abc", "conv-abc:Summary of first turn", step_index=10)
    assert res1 is True

    # Second claim for same conv and same step 10 fails (even if text is slightly different)
    res2 = claim_turn("conv-abc", "conv-abc:Slightly different summary text", step_index=10)
    assert res2 is False

    # Claim for step 11 succeeds
    res3 = claim_turn("conv-abc", "conv-abc:Summary of step eleven", step_index=11)
    assert res3 is True

    # Origin retrieval works with step_index
    origin = get_claimed_turn_origin("conv-abc", "conv-abc:Summary of step eleven", step_index=11)
    assert origin == "desktop"


def test_speech_turn_lock_deduplication(tmp_path, monkeypatch):
    recent_file = tmp_path / "recent_speech.json"
    speech_lock = tmp_path / "speech.lock"
    monkeypatch.setattr("voicefi.tts.base.RECENT_SPEECH_FILE", recent_file)
    monkeypatch.setattr("voicefi.tts.base.SPEECH_LOCK_FILE", speech_lock)
    monkeypatch.setattr("voicefi.tts.base.is_system_audio_playing", lambda: False)

    sample_text = "Refactored the authentication controller and verified all tests."

    # First speech execution passes
    executed = False
    with speech_turn_lock(text=sample_text, agent_name="Antigravity", persona_name="Viv"):
        executed = True
    assert executed is True
    assert is_duplicate_speech(sample_text, window_seconds=6.0) is True

    # Immediate second speech attempt with same text raises DuplicateSpeechSuppressed
    with pytest.raises(DuplicateSpeechSuppressed):
        with speech_turn_lock(text=sample_text, agent_name="Antigravity", persona_name="Viv"):
            pytest.fail("Second speech execution should have been suppressed!")

    # Different text passes
    executed_diff = False
    with speech_turn_lock(text="Here is a completely different update for the user.", agent_name="Antigravity"):
        executed_diff = True
    assert executed_diff is True


def test_acoustic_echo_suppression(tmp_path, monkeypatch):
    last_spoken = tmp_path / "last_spoken.json"
    monkeypatch.setattr("voicefi.audio.echo_canceller.LAST_SPOKEN_FILE", last_spoken)
    clear_agent_spoken_history()

    agent_phrase = "Would you like me to stage this on Railway or ship straightaway?"
    record_agent_spoken(agent_phrase)

    # Exact echo from microphone
    assert is_acoustic_echo(agent_phrase) is True

    # Partial / fuzzy microphone pickup of the phrase
    assert is_acoustic_echo("stage this on Railway or ship straightaway") is True
    assert is_acoustic_echo("Railway or ship straightaway?") is True

    # Completely different user voice prompt is NOT echo
    assert is_acoustic_echo("Please run the full test suite in verbose mode.") is False
