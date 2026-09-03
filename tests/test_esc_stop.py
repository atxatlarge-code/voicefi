"""
Unit tests for Escape key speech stopping and recording cancellation in VoiceFi.
"""

import os
import threading
import time
from unittest.mock import patch, MagicMock
import pytest
import numpy as np

from voicefi.tts.base import speech_turn_lock, stop_all_speech, is_agent_speaking, set_agent_speaking
from voicefi.tts.mac_say import MacSayTTS
from voicefi.audio.recorder import AudioRecorder


def test_esc_key_triggers_stop_all_speech():
    """Verify speech_turn_lock sets and clears speaking status cleanly."""
    with patch("voicefi.tts.base.set_agent_speaking") as mock_set_speaking:
        with speech_turn_lock(text="Hello world", agent_name="Antigravity", persona_name="Christopher"):
            mock_set_speaking.assert_called_with(True, text="Hello world", agent_name="Antigravity", persona_name="Christopher")
        mock_set_speaking.assert_called_with(False)


def test_mac_say_stop_requested(tmp_path):
    """Verify MacSayTTS aborts speech and avoids fallback if stop is requested."""
    tts = MacSayTTS(voice="Samantha", rate=200)

    with patch("voicefi.tts.mac_say.is_user_on_call", return_value=False):
        mock_proc = MagicMock()
        mock_proc.returncode = -9  # Killed by SIGKILL / stop()
        mock_proc.poll.return_value = None

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
                def _stop_during_wait():
                    tts.stop()
                    return -9

                mock_proc.wait.side_effect = _stop_during_wait

                with patch("pathlib.Path.stat") as mock_stat, patch("pathlib.Path.is_file", return_value=True):
                    mock_stat.return_value = MagicMock(st_size=1024)
                    tts.speak("Hello world", block=True)
                afplay_calls = [c for c in mock_popen.call_args_list if c[0][0][0] == "afplay"]
                assert len(afplay_calls) == 1


def test_audio_recorder_esc_cancels_recording():
    """Verify that pressing Esc during record_speech_auto stops recording and discards audio."""
    recorder = AudioRecorder(sample_rate=16000)

    with patch("voicefi.tts.base.stop_all_speech") as mock_stop:
        with patch("pynput.keyboard.Listener") as mock_listener_cls:
            mock_listener_inst = MagicMock()
            mock_listener_cls.return_value = mock_listener_inst

            # Mock sounddevice stream to yield 1 chunk then stop
            dummy_chunk = np.zeros((800, 1), dtype=np.float32)

            with patch("sounddevice.InputStream") as mock_input_stream:
                mock_stream_inst = MagicMock()
                mock_stream_inst.__enter__.return_value = mock_stream_inst

                def stream_read(size):
                    # Trigger the Esc callback on first read
                    _, kwargs = mock_listener_cls.call_args
                    on_press_cb = kwargs.get("on_press")
                    from pynput.keyboard import Key
                    on_press_cb(Key.esc)
                    return dummy_chunk, False

                mock_stream_inst.read.side_effect = stream_read
                mock_input_stream.return_value = mock_stream_inst

                audio_data, temp_wav = recorder.record_speech_auto()

                # Verify stop_all_speech called
                mock_stop.assert_called_once()
                # Verify audio data was discarded and temp_wav is None
                assert np.all(audio_data == 0)
                assert temp_wav is None


def test_audio_recorder_space_does_not_cancel_recording():
    """Verify that pressing Spacebar does NOT stop or cancel recording in AudioRecorder."""
    recorder = AudioRecorder(sample_rate=16000)

    with patch("voicefi.tts.base.stop_all_speech") as mock_stop:
        with patch("pynput.keyboard.Listener") as mock_listener_cls:
            mock_listener_inst = MagicMock()
            mock_listener_cls.return_value = mock_listener_inst

            dummy_chunk = np.zeros((800, 1), dtype=np.float32)

            with patch("sounddevice.InputStream") as mock_input_stream:
                mock_stream_inst = MagicMock()
                mock_stream_inst.__enter__.return_value = mock_stream_inst

                def stream_read(size):
                    _, kwargs = mock_listener_cls.call_args
                    on_press_cb = kwargs.get("on_press")
                    from pynput.keyboard import Key
                    # Simulate user typing Space bar
                    on_press_cb(Key.space)
                    # Set stop_event manually to finish the test cleanly
                    recorder.stop_event.set()
                    return dummy_chunk, False

                mock_stream_inst.read.side_effect = stream_read
                mock_input_stream.return_value = mock_stream_inst

                audio_data, temp_wav = recorder.record_speech_auto()

                # Space should NOT call stop_all_speech or cancel
                mock_stop.assert_not_called()
                if temp_wav:
                    temp_wav.unlink(missing_ok=True)


def test_audio_recorder_esc_while_agent_speaking_stops_speech_and_cancels_recording():
    """Verify that pressing Esc while agent is speaking stops speech and cancels recording."""
    recorder = AudioRecorder(sample_rate=16000)

    with patch("voicefi.tts.base.stop_all_speech") as mock_stop, \
         patch("voicefi.tts.base.is_agent_speaking", return_value=True), \
         patch("pynput.keyboard.Listener") as mock_listener_cls:

        mock_listener_inst = MagicMock()
        mock_listener_cls.return_value = mock_listener_inst

        dummy_chunk = np.ones((800, 1), dtype=np.float32) * 0.05

        with patch("sounddevice.InputStream") as mock_input_stream:
            mock_stream_inst = MagicMock()
            mock_stream_inst.__enter__.return_value = mock_stream_inst

            def stream_read(size):
                _, kwargs = mock_listener_cls.call_args
                on_press_cb = kwargs.get("on_press")
                from pynput.keyboard import Key
                # Press Esc while agent is speaking
                on_press_cb(Key.esc)
                # Ensure stop_event is set to immediately terminate recording
                assert recorder.stop_event.is_set()
                return dummy_chunk, False

            mock_stream_inst.read.side_effect = stream_read
            mock_input_stream.return_value = mock_stream_inst

            audio_data, temp_wav = recorder.record_speech_auto()

            # stop_all_speech called to stop the agent's voice
            mock_stop.assert_called_once()
            assert temp_wav is None
            assert np.all(audio_data == 0)


def test_tray_handle_escape_press_when_speaking_with_auto_listen():
    """Verify tray app handle_escape_press stops speech and resets to idle without triggering mic."""
    from voicefi.ui.tray import VoiceFiTrayApp
    from voicefi.config import VoiceFiConfig

    app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
    app.config = VoiceFiConfig()
    app.config.antigravity.auto_listen = True
    app.watcher = MagicMock()
    app.watcher._is_handling_turn = False
    app.speech_hud = MagicMock()
    app._listen_lock = threading.Lock()
    app._current_status = "speaking"
    app.active_recorder = None

    with patch("voicefi.ui.tray.is_agent_speaking", return_value=True), \
         patch("voicefi.ui.tray.stop_all_speech") as mock_stop, \
         patch.object(app, "trigger_talk_to_antigravity") as mock_talk:

        app.handle_escape_press()

        mock_stop.assert_called_once()
        app.speech_hud.hide.assert_called_once()
        mock_talk.assert_not_called()
        assert app._current_status == "idle"


def test_tray_handle_escape_press_when_speaking_without_auto_listen():
    """Verify tray app handle_escape_press stops speech and resets to idle when auto_listen is OFF."""
    from voicefi.ui.tray import VoiceFiTrayApp
    from voicefi.config import VoiceFiConfig

    app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
    app.config = VoiceFiConfig()
    app.config.antigravity.auto_listen = False
    app.watcher = MagicMock()
    app.speech_hud = MagicMock()
    app._listen_lock = threading.Lock()
    app._current_status = "speaking"
    app.active_recorder = None

    with patch("voicefi.ui.tray.is_agent_speaking", return_value=True), \
         patch("voicefi.ui.tray.stop_all_speech") as mock_stop, \
         patch.object(app, "trigger_talk_to_antigravity") as mock_talk:

        app.handle_escape_press()

        mock_stop.assert_called_once()
        app.speech_hud.hide.assert_called_once()
        app.watcher.interrupt.assert_called_once()
        mock_talk.assert_not_called()
        assert app._current_status == "idle"


def test_escape_to_stop_speech_triggers_stop_all_speech():
    """Verify escape_to_stop_speech listener intercepts Esc key and triggers stop_all_speech."""
    from voicefi.tts.base import escape_to_stop_speech
    from pynput.keyboard import Key

    with patch("voicefi.tts.base.stop_all_speech") as mock_stop:
        with patch("pynput.keyboard.Listener") as mock_listener_cls:
            mock_inst = MagicMock()
            mock_listener_cls.return_value = mock_inst

            # Temporarily clear PYTEST_CURRENT_TEST to test the listener logic
            with patch.dict("os.environ", {}, clear=False):
                if "PYTEST_CURRENT_TEST" in os.environ:
                    del os.environ["PYTEST_CURRENT_TEST"]
                with escape_to_stop_speech():
                    # Extract callback passed to pynput.keyboard.Listener
                    _, kwargs = mock_listener_cls.call_args
                    on_press_cb = kwargs.get("on_press")
                    assert on_press_cb is not None
                    # Press Esc
                    on_press_cb(Key.esc)
                    mock_stop.assert_called_once()


def test_ensure_daemon_running_auto_spawns():
    """Verify ensure_daemon_running spawns background tray daemon when port is free."""
    from voicefi.integrations.daemon_client import ensure_daemon_running
    from voicefi.config import VoiceFiConfig

    cfg = VoiceFiConfig()

    with patch("voicefi.integrations.daemon_client.is_daemon_running", side_effect=[False, False, True]), \
         patch("subprocess.Popen") as mock_popen:
        res = ensure_daemon_running(cfg, timeout=0.5)
        assert res is True
        mock_popen.assert_called_once()


def test_forward_hook_to_daemon_does_not_autospawn_when_offline():
    """Verify forward_hook_to_daemon returns None and does not spawn processes if daemon is killed."""
    from voicefi.integrations.daemon_client import forward_hook_to_daemon
    from voicefi.config import VoiceFiConfig

    cfg = VoiceFiConfig()

    with patch("voicefi.integrations.daemon_client.is_daemon_running", return_value=False), \
         patch("subprocess.Popen") as mock_popen:
        res = forward_hook_to_daemon({"agent": "antigravity"}, cfg)
        assert res is None
        mock_popen.assert_not_called()


def test_is_escape_key_all_representations():
    """Verify is_escape_key identifies all macOS and pynput representations of Escape."""
    from voicefi.tts.base import is_escape_key
    from pynput.keyboard import Key, KeyCode

    # Direct Key.esc
    assert is_escape_key(Key.esc) is True

    # KeyCode with vk=53 (macOS hardware virtual key code for Esc)
    vk_esc = KeyCode.from_vk(53)
    assert is_escape_key(vk_esc) is True

    # KeyCode with ASCII escape char (\x1b)
    char_esc = KeyCode.from_char("\x1b")
    assert is_escape_key(char_esc) is True

    # Mock KeyCode with name='esc'
    named_esc = MagicMock()
    named_esc.name = "esc"
    named_esc.vk = None
    named_esc.char = None
    assert is_escape_key(named_esc) is True

    # Non-escape keys should return False
    assert is_escape_key(Key.space) is False
    assert is_escape_key(Key.enter) is False
    assert is_escape_key(KeyCode.from_char("a")) is False
    assert is_escape_key(None) is False


def test_is_speech_interrupted():
    """Verify is_speech_interrupted accurately detects stops across time and state."""
    from voicefi.tts.base import (
        is_speech_interrupted,
        set_agent_speaking,
        record_speech_stopped,
        AGENT_SPEAKING_STATUS_FILE,
    )

    # 1. When active speaking with no stop event -> False
    set_agent_speaking(True, text="Active test turn")
    turn_start = time.time()
    time.sleep(0.01)
    assert is_speech_interrupted(turn_start) is False

    # 2. When stop is recorded after turn start -> True
    record_speech_stopped()
    assert is_speech_interrupted(turn_start) is True

    # Cleanup
    set_agent_speaking(False)


def test_mac_say_registers_in_active_tts_engines():
    """Verify MacSayTTS registers in _ACTIVE_TTS_ENGINES and responds to stop_all_speech."""
    from voicefi.tts.mac_say import MacSayTTS
    from voicefi.tts.base import _ACTIVE_TTS_ENGINES

    tts = MacSayTTS(voice="Samantha", rate=200)
    assert tts in _ACTIVE_TTS_ENGINES

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    tts._current_process = mock_proc

    tts.stop()
    assert tts._stop_requested is True
    mock_proc.terminate.assert_called_once()


def test_f5_tts_registers_in_active_tts_engines():
    """Verify F5TTS registers in _ACTIVE_TTS_ENGINES and responds to stop."""
    from voicefi.tts.f5_tts import F5TTS
    from voicefi.tts.base import _ACTIVE_TTS_ENGINES

    tts = F5TTS(model_name="F5TTS_v1_Base")
    assert tts in _ACTIVE_TTS_ENGINES

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    tts._current_process = mock_proc

    tts.stop()
    assert tts._stop_requested is True
    mock_proc.terminate.assert_called_once()


def test_edge_tts_no_fallback_on_interruption():
    """Verify EdgeTTS does not trigger fallback speech when interrupted by Esc."""
    from voicefi.tts.edge_tts import EdgeTTS

    tts = EdgeTTS(voice="en-US-AvaNeural")

    with patch.object(tts, "_fallback_speak_direct") as mock_fallback, \
         patch("voicefi.tts.base.is_speech_interrupted", return_value=True), \
         patch("voicefi.tts.edge_tts.is_user_on_call", return_value=False):
        tts.speak("Sentence one. Sentence two.", block=True)
        mock_fallback.assert_not_called()




