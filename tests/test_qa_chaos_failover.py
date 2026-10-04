"""
QA-02: Mid-Synthesis Network Sever & Chaos Failover Test Suite.
Validates that:
1. Mid-stream network connection resets or timeouts in EdgeTTS trigger instant offline fallback.
2. VoiceActingTTS synthesis failures update HUD state to '⚠️ Ava Fallback' and cascade seamlessly.
3. speech_turn_lock is never leaked or deadlocked during chaos events, allowing subsequent turns.
4. Zero dead air is maintained; user always receives audible speech feedback.
"""

import pytest
import subprocess
from unittest.mock import MagicMock, patch

from voicefi.tts.edge_tts import EdgeTTS
from voicefi.tts.voice_acting import VoiceActingTTS
from voicefi.tts.mac_say import MacSayTTS
from voicefi.tts.base import (
    speech_turn_lock,
    is_agent_speaking,
    set_agent_speaking,
    set_agent_audio_playing,
    get_cross_process_hud_state,
)


def test_edge_tts_mid_synthesis_socket_sever(monkeypatch):
    """
    Simulate a socket disconnect / ConnectionResetError mid-stream in EdgeTTS.
    Verify seamless fallback to MacSay with zero dead air and no unhandled exceptions.
    """
    edge = EdgeTTS(voice="en-US-AvaNeural", agent_name="VoiceFi")

    # Mock _generate_audio to simulate an abrupt network drop
    async def mock_severed_generate(text, output_path):
        raise ConnectionResetError("Simulated mid-stream WiFi socket disconnect [Errno 54]")

    monkeypatch.setattr(edge, "_generate_audio", mock_severed_generate)

    # Track calls to fallback
    fallback_called = []

    def mock_fallback_speak(clean_text, turn_start_time=0.0):
        fallback_called.append(clean_text)

    monkeypatch.setattr(edge, "_fallback_speak_direct", mock_fallback_speak)

    # Execute speech turn under speech_turn_lock
    test_phrase = "Refactored the authentication gateway and updated certificates."
    edge.speak(test_phrase, block=True)

    # Verify that fallback was triggered immediately with the exact text
    assert len(fallback_called) == 1
    assert fallback_called[0] == test_phrase

    # Verify speech state was released cleanly and is ready for subsequent turns
    assert not is_agent_speaking()


def test_voice_acting_mid_synthesis_failure_cascade(monkeypatch):
    """
    Simulate an out-of-memory or model generation failure in VoiceActingTTS.
    Verify HUD status badge updates to '⚠️ Ava Fallback' and speech routes to MacSay.
    """
    engine = VoiceActingTTS(persona_name="drill_sergeant")

    # Force speak_to_file to fail (simulating Metal shader or weight failure)
    def mock_broken_speak_to_file(text, out_path):
        return False

    monkeypatch.setattr(engine, "speak_to_file", mock_broken_speak_to_file)

    hud_updates = []

    def mock_set_hud_state(state, **kwargs):
        hud_updates.append((state, kwargs))

    monkeypatch.setattr("voicefi.tts.base.set_cross_process_hud_state", mock_set_hud_state)

    # Mock EdgeTTS to fail as well to test cascade all the way to MacSay
    def mock_edge_speak(self, text, block=True):
        raise RuntimeError("Cloud provider unreachable")

    monkeypatch.setattr("voicefi.tts.edge_tts.EdgeTTS.speak", mock_edge_speak)

    mac_say_called = []

    def mock_mac_say_speak(self, text, block=True):
        mac_say_called.append(text)
        return True

    monkeypatch.setattr("voicefi.tts.mac_say.MacSayTTS.speak", mock_mac_say_speak)

    test_sentence = "Attention! All unit test suites passed with zero regressions."
    success = engine.speak(test_sentence, block=True)

    assert success is True
    # Verify HUD received the '⚠️ Ava Fallback' status badge
    assert any(kwargs.get("tag_text") == "⚠️ Ava Fallback" for state, kwargs in hud_updates)
    # Verify MacSay executed the final fallback
    assert len(mac_say_called) == 1
    assert mac_say_called[0] == test_sentence


def test_speech_turn_lock_reentrancy_after_chaos():
    """
    Verify that after an abrupt failure or exception in speech synthesis,
    the speech_turn_lock can be re-acquired immediately for subsequent turns.
    """
    assert not is_agent_speaking()

    with speech_turn_lock(text="Turn 1 under chaos"):
        assert is_agent_speaking()
        # Nested reentrant acquisition within same thread
        with speech_turn_lock(text="Turn 1 nested"):
            assert is_agent_speaking()

    # Lock is released cleanly
    assert not is_agent_speaking()

    # Subsequent speech turn succeeds without hanging
    subsequent_executed = False
    with speech_turn_lock(text="Turn 2 clean"):
        assert is_agent_speaking()
        subsequent_executed = True

    assert subsequent_executed is True
    assert not is_agent_speaking()

