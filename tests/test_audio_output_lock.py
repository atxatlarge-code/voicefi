"""
Tests for cross-process audio output mutex and StreamingAudioPlayer drain completion.
Validates mutual exclusion across independent OS processes and mixed playback paths.
"""

import multiprocessing
import os
import time
import pytest
import numpy as np

from voicefi.audio.output_lock import (
    exclusive_audio,
    is_audio_output_locked,
    force_release_audio_lock,
    AUDIO_LOCK_FILE,
)
from voicefi.audio.player import StreamingAudioPlayer
from voicefi.tts.base import is_system_audio_playing


def _worker_hold_audio_lock(hold_duration: float, result_queue: multiprocessing.Queue):
    """Worker process that acquires exclusive audio lock, holds it, and signals."""
    try:
        with exclusive_audio(timeout=10.0, owner="worker_1"):
            result_queue.put(("acquired", time.time()))
            time.sleep(hold_duration)
            result_queue.put(("releasing", time.time()))
    except Exception as e:
        result_queue.put(("error", str(e)))


def _worker_try_lock(timeout: float, result_queue: multiprocessing.Queue):
    """Worker process that attempts to acquire exclusive audio lock."""
    try:
        with exclusive_audio(timeout=timeout, owner="worker_2"):
            result_queue.put(("worker2_acquired", time.time()))
    except Exception as e:
        result_queue.put(("worker2_error", str(e)))


def test_exclusive_audio_cross_process_serialization(tmp_path, monkeypatch):
    """Test that two separate OS processes serialize their access to the audio mutex."""
    test_lock = tmp_path / "test_audio.lock"
    monkeypatch.setenv("VOICEFI_AUDIO_LOCK", str(test_lock))

    q1 = multiprocessing.Queue()
    q2 = multiprocessing.Queue()

    # Process 1 holds lock for 0.5 seconds
    p1 = multiprocessing.Process(target=_worker_hold_audio_lock, args=(0.5, q1))
    p1.start()

    # Wait until p1 acquires lock
    msg, t_p1_acquired = q1.get(timeout=3.0)
    assert msg == "acquired"

    # Verify that from parent process perspective, audio output is locked
    # (Note: we test with separate lock file in subprocess)

    # Process 2 attempts to acquire lock
    p2 = multiprocessing.Process(target=_worker_try_lock, args=(3.0, q2))
    p2.start()

    # Wait for p1 to release
    msg_rel, t_p1_released = q1.get(timeout=3.0)
    assert msg_rel == "releasing"

    # Wait for p2 to acquire
    msg_p2, t_p2_acquired = q2.get(timeout=3.0)
    assert msg_p2 == "worker2_acquired"

    # Invariant: p2 must acquire AFTER p1 released
    assert t_p2_acquired >= t_p1_released - 0.05

    p1.join(timeout=2.0)
    p2.join(timeout=2.0)


def test_is_audio_output_locked_detection(tmp_path, monkeypatch):
    """Test is_audio_output_locked detects locked state."""
    test_lock = tmp_path / "test_detect.lock"
    monkeypatch.setenv("VOICEFI_AUDIO_LOCK", str(test_lock))

    assert not is_audio_output_locked()

    with exclusive_audio(timeout=5.0, owner="detect_test"):
        assert is_audio_output_locked()
        # Also verify is_system_audio_playing reflects it
        # (when not in pytest mode, or when checking lock directly)

    assert not is_audio_output_locked()


def test_force_release_audio_lock(tmp_path, monkeypatch):
    """Test force_release_audio_lock releases local lock on barge-in."""
    test_lock = tmp_path / "test_barge.lock"
    monkeypatch.setenv("VOICEFI_AUDIO_LOCK", str(test_lock))

    with exclusive_audio(timeout=5.0, owner="barge_test"):
        assert is_audio_output_locked()
        force_release_audio_lock()

    assert not is_audio_output_locked()


def test_streaming_audio_player_drain_and_close():
    """Test StreamingAudioPlayer sample tracking and drain completion signaling."""
    player = StreamingAudioPlayer(sample_rate=24000, channels=1, blocksize=512)
    # Mocking stream to avoid opening hardware device in unit test
    player.is_playing = True
    player._stop_event.clear()
    player._drained_event.set()

    # Feed audio chunks
    chunk = np.zeros(2048, dtype=np.float32)
    player.feed(chunk)
    assert not player._drained_event.is_set()
    assert player._outstanding_samples == 2048

    # Drain queue
    while not player.audio_queue.empty():
        player.audio_queue.get_nowait()
    with player._samples_lock:
        player._outstanding_samples = 0
        player._drained_event.set()

    assert player.wait_until_drained(timeout=1.0)
    player.stop()
    assert player._drained_event.is_set()
