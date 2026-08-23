"""Unit tests for Push-to-Talk (PTT) and Real-Time Streaming STT & TTS."""

import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import pytest

from voicefi.config import VoiceFiConfig, VADConfig, TTSConfig, STTConfig
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.player import StreamingAudioPlayer
from voicefi.stt.base import BaseSTT, BaseStreamingSTT
from voicefi.stt.streaming_local import StreamingLocalSTT
from voicefi.stt import get_stt_engine
from voicefi.tts import get_tts_engine
from voicefi.tts.edge_tts import EdgeTTS


def test_config_ptt_and_streaming_defaults():
    config = VoiceFiConfig()
    assert config.vad.mode == "hybrid"
    assert config.vad.ptt_release_delay_ms == 150
    assert config.tts.streaming is True
    assert config.stt.streaming is False


def test_stt_factory_streaming_selection():
    cfg_stream = VoiceFiConfig()
    cfg_stream.stt.streaming = True
    stt_stream = get_stt_engine(cfg_stream)
    assert isinstance(stt_stream, StreamingLocalSTT)
    assert isinstance(stt_stream, BaseStreamingSTT)


def test_streaming_local_stt_chunks(monkeypatch):
    stt = StreamingLocalSTT(model_size="base.en")

    # Mock underlying transcribe
    mock_transcribe = MagicMock(return_value="hello streaming world")
    monkeypatch.setattr(stt.underlying, "transcribe", mock_transcribe)

    chunk = np.zeros(800, dtype=np.float32)

    # Feed 9 chunks -> should not trigger partial yet
    for _ in range(9):
        res = stt.feed_chunk(chunk)
        assert res is None

    # Feed 10th chunk -> triggers partial
    res10 = stt.feed_chunk(chunk)
    # Check finish_stream
    final_text = stt.finish_stream()
    assert final_text == "hello streaming world"
    assert len(stt.buffer) == 0


@patch("sounddevice.InputStream")
def test_recorder_push_to_talk(mock_stream_cls, tmp_path):
    # Mock audio stream read
    dummy_chunk = np.zeros(800, dtype=np.float32)
    mock_stream = MagicMock()
    mock_stream.read.return_value = (dummy_chunk.reshape(-1, 1), False)
    mock_stream_cls.return_value.__enter__.return_value = mock_stream

    recorder = AudioRecorder(sample_rate=16000)
    stop_ev = threading.Event()

    # Trigger stop immediately after starting
    def _trigger_stop():
        time.sleep(0.05)
        stop_ev.set()

    t = threading.Thread(target=_trigger_stop)
    t.start()

    audio, wav_path = recorder.record_push_to_talk(stop_event=stop_ev, ptt_release_delay_ms=50)
    t.join()

    assert wav_path.is_file()
    assert len(audio) > 0
    wav_path.unlink(missing_ok=True)


def test_streaming_audio_player():
    player = StreamingAudioPlayer(sample_rate=16000)
    assert not player.is_playing

    # Feed chunk without starting stream explicitly
    chunk = np.zeros(512, dtype=np.float32)
    player.feed(chunk)
    assert not player.audio_queue.empty()

    player.stop()
    assert not player.is_playing
    assert player.audio_queue.empty()


def test_edge_tts_streaming_flag():
    edge = EdgeTTS(voice="en-US-ChristopherNeural", streaming=True)
    assert edge.streaming is True
    assert edge.voice == "en-US-ChristopherNeural"
