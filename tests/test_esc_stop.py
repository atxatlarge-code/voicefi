"""
Unit tests for Escape key speech stopping and recording cancellation in VoiceFi.
"""

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


def test_mac_say_stop_requested():
    """Verify MacSayTTS aborts speech and avoids fallback if stop is requested."""
    tts = MacSayTTS(voice="Samantha", rate=200)

    with patch("voicefi.tts.mac_say.is_user_on_call", return_value=False):
        mock_proc = MagicMock()
        mock_proc.returncode = -9  # Killed by SIGKILL / stop()
        mock_proc.poll.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            def _stop_during_wait():
                tts.stop()
                return -9

            mock_proc.wait.side_effect = _stop_during_wait

            tts.speak("Hello world", block=True)

            # First call was the primary say command
            assert mock_popen.call_count == 1
            cmd_run = mock_popen.call_args_list[0][0][0]
            assert cmd_run[0] == "say"
            assert "-v" in cmd_run
            # Fallback should NOT have been called
            assert mock_popen.call_count == 1


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
                # Verify audio data was discarded
                assert np.all(audio_data == 0)
                temp_wav.unlink(missing_ok=True)


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
                temp_wav.unlink(missing_ok=True)

