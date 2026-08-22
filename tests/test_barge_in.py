"""
Tests for Active Barge-In and VAD Cancellation.
Verifies immediate killing of audio output and seamless voice capture when user speaks during agent turns.
"""

import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from voicegency.config import VoicegencyConfig, load_config
from voicegency.audio.recorder import AudioRecorder
from voicegency.tts.base import (
    set_agent_speaking,
    is_agent_speaking,
    stop_all_speech,
    speech_turn_lock,
)
from voicegency.integrations.watcher import TranscriptWatcher
from voicegency.integrations.antigravity import handle_antigravity_stop_hook


def test_vad_config_barge_in_defaults():
    """Verify VADConfig has barge_in enabled by default with 1.0 sensitivity."""
    cfg = VoicegencyConfig()
    assert cfg.vad.barge_in is True
    assert cfg.vad.barge_in_sensitivity == 1.0


def test_audio_recorder_barge_in_triggers_and_preserves_audio():
    """
    Simulate microphone input where agent starts speaking, and user interrupts mid-sentence.
    Verify:
    1. on_barge_in is triggered.
    2. stop_all_speech is called.
    3. User speech frames (including onset buffer) are captured and saved to output WAV.
    """
    sample_rate = 16000
    chunk_duration = 0.05
    chunk_size = int(sample_rate * chunk_duration)

    recorder = AudioRecorder(
        sample_rate=sample_rate,
        energy_threshold=0.005,
        silence_duration=0.6,
        max_record_seconds=10.0,
        barge_in=True,
        barge_in_sensitivity=1.0,
    )

    barge_in_events = []
    speech_starts = []

    def on_barge():
        barge_in_events.append(True)

    def on_start():
        speech_starts.append(True)

    silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)
    # Loud human voice chunk that exceeds the barge-in threshold
    loud_speech_chunk = np.ones((chunk_size, 1), dtype=np.float32) * 0.06

    # Timeline of chunks:
    # 0-3: Silence while agent is speaking
    # 4-7: User interrupts (loud speech while agent is still speaking) -> triggers Barge-In!
    # 8-12: User continues speaking
    # 13-28: Silence -> VAD natural pause cutoff
    chunks = (
        [silence_chunk] * 4 +
        [loud_speech_chunk] * 4 +
        [loud_speech_chunk] * 5 +
        [silence_chunk] * 16
    )

    speaking_states = [True] * 30
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
        # Once stop_all_speech is called by barge-in, agent speaking becomes False
        if barge_in_events:
            return False
        idx = min(current_idx[0], len(speaking_states) - 1)
        return speaking_states[idx]

    with patch("sounddevice.InputStream", side_effect=MockStream), \
         patch("voicegency.tts.base.stop_all_speech") as mock_stop_speech, \
         patch("voicegency.audio.recorder.is_agent_speaking", side_effect=mock_is_agent_speaking):

        def wrapped_barge_in():
            on_barge()
            mock_stop_speech()

        audio_data, wav_path = recorder.record_speech_auto(
            on_speech_start=on_start,
            on_barge_in=wrapped_barge_in,
        )

        try:
            assert wav_path.is_file()
            assert len(barge_in_events) > 0, "Barge-in callback must be called when user speaks during agent speech"
            assert mock_stop_speech.called, "stop_all_speech must be called on barge-in"
            assert len(speech_starts) > 0, "Speech start must be notified"
            
            # Verify audio frames were captured
            total_duration = len(audio_data) / sample_rate
            assert total_duration > 0.4, f"Captured audio should include user speech (got {total_duration}s)"
        finally:
            wav_path.unlink(missing_ok=True)


def test_audio_recorder_barge_in_disabled_maintains_pause():
    """Verify that when barge_in=False, incoming audio is paused/discarded during agent speech."""
    sample_rate = 16000
    chunk_duration = 0.05
    chunk_size = int(sample_rate * chunk_duration)

    recorder = AudioRecorder(
        sample_rate=sample_rate,
        energy_threshold=0.005,
        silence_duration=0.6,
        max_record_seconds=5.0,
        barge_in=False,
    )

    barge_in_events = []
    silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)
    loud_speech_chunk = np.ones((chunk_size, 1), dtype=np.float32) * 0.06

    chunks = (
        [loud_speech_chunk] * 4 +
        [silence_chunk] * 15
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

    with patch("sounddevice.InputStream", side_effect=MockStream), \
         patch("voicegency.tts.base.stop_all_speech") as mock_stop_speech, \
         patch("voicegency.audio.recorder.is_agent_speaking", return_value=True):

        # Stop recorder after a few iterations to prevent timeout hang
        timer = threading.Timer(0.3, recorder.stop)
        timer.start()

        audio_data, wav_path = recorder.record_speech_auto(
            on_barge_in=lambda: barge_in_events.append(True),
        )

        try:
            assert len(barge_in_events) == 0, "Barge-in must not trigger when disabled"
            assert not mock_stop_speech.called
        finally:
            wav_path.unlink(missing_ok=True)


def test_ptt_barge_in_instant_speech_stop():
    """Verify that triggering PTT mode immediately stops agent speech if barge_in is True."""
    sample_rate = 16000
    chunk_duration = 0.05
    chunk_size = int(sample_rate * chunk_duration)

    recorder = AudioRecorder(
        sample_rate=sample_rate,
        barge_in=True,
    )

    silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)
    stop_event = threading.Event()

    class MockStream:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            stop_event.set()
            return silence_chunk, False

    with patch("sounddevice.InputStream", side_effect=MockStream), \
         patch("voicegency.tts.base.stop_all_speech") as mock_stop_speech, \
         patch("voicegency.audio.recorder.is_agent_speaking", return_value=True):

        audio_data, wav_path = recorder.record_push_to_talk(stop_event=stop_event)
        try:
            assert mock_stop_speech.called, "Triggering PTT while agent is speaking must immediately call stop_all_speech"
        finally:
            wav_path.unlink(missing_ok=True)


def test_transcript_watcher_turn_ready_with_barge_in(tmp_path):
    """Verify TranscriptWatcher coordinates TTS in background and auto-listen with barge-in."""
    cfg = VoicegencyConfig()
    cfg.vad.barge_in = True
    cfg.antigravity.read_summary_aloud = True
    cfg.antigravity.auto_listen = True
    cfg.antigravity.show_speech_popup = False
    cfg.audio_cues.enabled = False

    states = []
    watcher = TranscriptWatcher(config=cfg, on_state_change=lambda s: states.append(s))

    fake_wav = tmp_path / "test.wav"
    fake_wav.write_bytes(b"RIFF....WAVE")

    mock_tts = MagicMock()
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "Yes deploy it now"

    with patch("voicegency.integrations.watcher.load_config", return_value=cfg), \
         patch("voicegency.integrations.watcher.claim_turn", return_value=True), \
         patch("voicegency.integrations.watcher.is_system_audio_playing", return_value=False), \
         patch("voicegency.integrations.watcher.play_chime"), \
         patch("voicegency.integrations.watcher.get_tts_engine", return_value=mock_tts), \
         patch("voicegency.integrations.watcher.get_stt_engine", return_value=mock_stt), \
         patch("voicegency.integrations.watcher.send_message_to_antigravity") as mock_send, \
         patch.object(AudioRecorder, "record_speech_auto", return_value=(np.zeros(16000), fake_wav)):

        watcher._handle_turn_ready("Finished running migrations. Ready to deploy?", is_active=True)

        assert "speaking" in states
        assert mock_stt.transcribe.called
        assert mock_send.called
        mock_send.assert_called_with(conv_id=None, text="Yes deploy it now")


def test_antigravity_stop_hook_with_barge_in(tmp_path):
    """Verify handle_antigravity_stop_hook runs barge-in enabled recording loop."""
    cfg = VoicegencyConfig()
    cfg.vad.barge_in = True
    cfg.antigravity.read_summary_aloud = True
    cfg.antigravity.auto_listen = True
    cfg.antigravity.show_speech_popup = False
    cfg.audio_cues.enabled = False

    fake_wav = tmp_path / "test_hook.wav"
    fake_wav.write_bytes(b"RIFF....WAVE")

    mock_tts = MagicMock()
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "Approve PR"

    with patch("voicegency.integrations.antigravity.load_config", return_value=cfg), \
         patch("voicegency.integrations.antigravity.claim_turn", return_value=True), \
         patch("voicegency.integrations.antigravity.play_chime"), \
         patch("voicegency.integrations.antigravity.extract_latest_agent_summary", return_value=("Ready to merge?", "antigravity")), \
         patch("voicegency.integrations.antigravity.get_tts_engine", return_value=mock_tts), \
         patch("voicegency.integrations.antigravity.get_stt_engine", return_value=mock_stt), \
         patch("voicegency.integrations.antigravity.inject_text_to_active_app") as mock_inject, \
         patch("voicegency.integrations.antigravity.AudioRecorder.record_speech_auto", return_value=(np.zeros(16000), fake_wav)):

        handle_antigravity_stop_hook({"conversationId": "test-conv-123"}, config=cfg)

        assert mock_stt.transcribe.called
        assert mock_inject.called
        mock_inject.assert_called_with("Approve PR", submit_enter=True, target_antigravity=True)


def test_tray_app_barge_in_toggle():
    """Verify VoicegencyTrayApp barge-in menu item toggles configuration and saves."""
    from voicegency.ui.tray import VoicegencyTrayApp

    with patch("voicegency.integrations.watcher.TranscriptWatcher"), \
         patch("voicegency.ui.hub.ConversationHubWindow.get_instance"), \
         patch("voicegency.ui.dictation_hud.DictationHUD.get_instance"), \
         patch("voicegency.ui.tray.VoicegencyTrayApp._start_global_hotkey_listener"), \
         patch("voicegency.ui.tray.save_config") as mock_save, \
         patch("rumps.Timer"):

        app = VoicegencyTrayApp()
        assert app.barge_in_item.state == 1

        # Toggle barge-in
        app.toggle_barge_in(app.barge_in_item)
        assert app.config.vad.barge_in is False
        assert app.barge_in_item.state == 0
        assert mock_save.called

        # Toggle back
        app.toggle_barge_in(app.barge_in_item)
        assert app.config.vad.barge_in is True
        assert app.barge_in_item.state == 1
