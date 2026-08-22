import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from voicegency.tts.base import (
    set_agent_speaking,
    is_agent_speaking,
    is_system_audio_playing,
    speech_turn_lock,
    stop_all_speech,
    AGENT_SPEAKING_STATUS_FILE,
)
from voicegency.audio.recorder import AudioRecorder
from voicegency.ui.dictation_hud import DictationHUD
from voicegency.config import VoicegencyConfig


def test_agent_speaking_flag_lifecycle(tmp_path):
    """Test setting and clearing in-process and cross-process agent speaking flags."""
    # Ensure clean initial state
    set_agent_speaking(False)
    assert not is_agent_speaking()

    # Set speaking active
    set_agent_speaking(True)
    assert is_agent_speaking()
    assert AGENT_SPEAKING_STATUS_FILE.is_file()

    # Clear speaking
    set_agent_speaking(False)
    assert not is_agent_speaking()
    assert not AGENT_SPEAKING_STATUS_FILE.is_file()


def test_speech_turn_lock_sets_and_clears_speaking_state():
    """Verify that entering and exiting speech_turn_lock updates speaking state."""
    set_agent_speaking(False)
    assert not is_agent_speaking()

    with speech_turn_lock():
        assert is_agent_speaking()

    assert not is_agent_speaking()


def test_stop_all_speech_clears_speaking_state():
    """Verify stop_all_speech resets speaking status and cleans up marker file."""
    set_agent_speaking(True)
    assert is_agent_speaking()

    stop_all_speech()
    assert not is_agent_speaking()


def test_audio_recorder_pauses_during_agent_speech_and_discards_audio():
    """
    Simulate microphone stream where an agent starts speaking mid-recording.
    Verify:
    1. on_pause_change(True) is triggered.
    2. Audio frames during agent speech are not saved to the output.
    3. on_pause_change(False) is triggered when agent stops.
    4. User speech after agent stops is captured.
    """
    sample_rate = 16000
    chunk_duration = 0.05
    chunk_size = int(sample_rate * chunk_duration)

    recorder = AudioRecorder(
        sample_rate=sample_rate,
        energy_threshold=0.01,
        silence_duration=0.6,
        max_record_seconds=10.0,
    )

    pause_events = []
    speech_starts = []

    def on_pause(paused: bool):
        pause_events.append(paused)

    def on_start():
        speech_starts.append(True)

    # Simulated audio chunks:
    # Phase 1: 4 chunks of silence
    # Phase 2: Agent starts speaking -> 6 chunks of loud speech (while is_agent_speaking is True)
    # Phase 3: Agent finishes -> 6 cooldown chunks
    # Phase 4: User speaks -> 6 chunks of loud speech (is_agent_speaking is False)
    # Phase 5: 14 chunks of silence -> VAD triggers completion
    silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)
    loud_chunk = np.ones((chunk_size, 1), dtype=np.float32) * 0.05

    chunks = (
        [silence_chunk] * 4 +       # silence
        [loud_chunk] * 6 +          # agent speaking
        [silence_chunk] * 6 +       # cooldown & gap
        [loud_chunk] * 6 +          # user speaking
        [silence_chunk] * 16        # user silence -> end
    )

    # Simulated is_agent_speaking() returns True for Phase 2 (chunks 4 to 9)
    speaking_states = (
        [False] * 4 +
        [True] * 6 +
        [False] * 50
    )

    current_idx = [0]

    class MockStream:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            idx = current_idx[0]
            current_idx[0] += 1
            if idx < len(chunks):
                return chunks[idx], False
            return silence_chunk, False

    def mock_is_agent_speaking():
        idx = min(current_idx[0], len(speaking_states) - 1)
        return speaking_states[idx]

    with patch("sounddevice.InputStream", side_effect=MockStream), \
         patch("voicegency.audio.recorder.is_agent_speaking", side_effect=mock_is_agent_speaking):
        
        audio_data, wav_path = recorder.record_speech_auto(
            on_speech_start=on_start,
            on_pause_change=on_pause,
        )

        try:
            assert wav_path.is_file()
            # Verify pause and resume were notified
            assert True in pause_events, "Should have triggered on_pause_change(True)"
            assert False in pause_events, "Should have triggered on_pause_change(False)"

            # Verify speech start was triggered for user speech
            assert len(speech_starts) > 0, "Should have detected user speech start"

            # Verify that total captured audio is substantially shorter than all 38 chunks
            # because the 6 agent chunks were discarded!
            total_duration = len(audio_data) / sample_rate
            # 4 silence + 6 user + ~14 silence = ~24 chunks (~1.2s) vs 38 total chunks (1.9s)
            assert total_duration < 1.7, f"Audio should not include agent speech (got {total_duration}s)"
        finally:
            wav_path.unlink(missing_ok=True)


def test_dictation_hud_show_paused():
    """Verify DictationHUD.show_paused updates UI label and text."""
    hud = DictationHUD.get_instance()
    hud.show_paused("⏸️ Agent Speaking (Paused)...")
    assert hud._label.stringValue() == "⏸️ Agent Speaking (Paused)..."

    hud.show_listening()
    assert "Listening" in hud._label.stringValue()
    hud.hide()


def test_tray_status_map_includes_paused():
    """Verify VoicegencyTrayApp status map displays appropriate paused icon and text."""
    from voicegency.ui.tray import VoicegencyTrayApp

    # Mock rumps to instantiate tray app
    with patch("voicegency.integrations.watcher.TranscriptWatcher"), \
         patch("voicegency.ui.hub.ConversationHubWindow.get_instance"), \
         patch("voicegency.ui.tray.VoicegencyTrayApp._start_global_hotkey_listener"), \
         patch("rumps.Timer"):
        app = VoicegencyTrayApp()
        
        # Test speaking state
        app._current_status = "speaking"
        app._update_status_ui(None)
        assert "Speaking" in app.title

        # Test listening state
        app._current_status = "listening"
        app._update_status_ui(None)
        assert "Listening" in app.title

        # Test paused agent speaking state
        app._current_status = "paused_agent_speaking"
        app._update_status_ui(None)
        assert "⏸️" in app.title
        assert "Agent Speaking" in app.title

        # Test generic paused state
        app._current_status = "paused"
        app._update_status_ui(None)
        assert "⏸️" in app.title
