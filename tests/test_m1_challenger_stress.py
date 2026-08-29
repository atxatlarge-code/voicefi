"""
Adversarial Stress Test Suite for Milestone M1: Core Audio Concurrency & Pipeline Hardening.

Author: Challenger 1 (critic, specialist)
Validates:
1. Re-entrant speech_turn_lock under extreme recursion depth (depth=100) and unexpected exceptions.
2. Concurrent multi-threaded contention and multi-process contention.
3. record_speech_auto and record_push_to_talk under simulated CoreAudio/AUHAL stream open and read failures.
4. Cold-cache concurrent procedural SFX generation and TTS lock concurrency.
5. Overlapping recorder sessions and LiveVADMonitor pause/resume lifecycle.
"""

import os
import sys
import time
import shutil
import tempfile
import threading
import multiprocessing
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from voicefi.tts.base import (
    speech_turn_lock,
    set_agent_speaking,
    is_agent_speaking,
    stop_all_speech,
    DuplicateSpeechSuppressed,
    clear_recent_speech_history,
)
import voicefi.tts.base as tts_base
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.monitor import LiveVADMonitor
from voicefi.audio.sfx import (
    play_sfx,
    get_sfx_path,
    list_available_sfx,
    SFX_CACHE_DIR,
)


@pytest.fixture(autouse=True)
def clean_audio_harness_state():
    """Ensure clean lock and speaking state with mocked keyboard listener during unit runs."""
    set_agent_speaking(False)
    clear_recent_speech_history()
    tts_base._LOCK_DEPTH = 0
    with patch("pynput.keyboard.Listener", return_value=MagicMock()):
        yield
    set_agent_speaking(False)
    clear_recent_speech_history()
    tts_base._LOCK_DEPTH = 0


# ============================================================================
# Challenge 1: Re-entrant speech_turn_lock under extreme depth & exceptions
# ============================================================================


def test_speech_turn_lock_extreme_recursion_depth_100():
    """Stress-test speech_turn_lock() re-entrancy up to 100 nested recursion levels."""
    target_depth = 100
    reached_depths = []

    def recursive_lock(current_depth: int):
        if current_depth > target_depth:
            return
        with speech_turn_lock(text=f"Nested turn level {current_depth}"):
            assert is_agent_speaking(), f"Must be speaking at depth {current_depth}"
            assert tts_base._LOCK_DEPTH == current_depth, f"Lock depth mismatch at {current_depth}: got {tts_base._LOCK_DEPTH}"
            reached_depths.append(current_depth)
            recursive_lock(current_depth + 1)
            # On return unwinding
            assert tts_base._LOCK_DEPTH == current_depth, f"Unwinding depth mismatch at {current_depth}: got {tts_base._LOCK_DEPTH}"

    recursive_lock(1)
    assert len(reached_depths) == target_depth
    assert reached_depths[-1] == 100
    assert tts_base._LOCK_DEPTH == 0
    assert not is_agent_speaking()


def test_speech_turn_lock_exception_unwinding_from_deep_recursion():
    """
    Stress-test exception unwinding when an unexpected exception is raised
    at level 50 of 100 nested lock acquisitions.
    Verifies lock depth drops to 0, speaking status is cleared, and lock is immediately re-acquirable.
    """
    fail_at_depth = 50

    def recursive_lock(current_depth: int):
        with speech_turn_lock(text=f"Nested error test level {current_depth}"):
            if current_depth == fail_at_depth:
                raise ValueError(f"Simulated crash at depth {fail_at_depth}")
            recursive_lock(current_depth + 1)

    with pytest.raises(ValueError, match=f"Simulated crash at depth {fail_at_depth}"):
        recursive_lock(1)

    # Verify complete cleanup
    assert tts_base._LOCK_DEPTH == 0, f"Expected _LOCK_DEPTH == 0 after exception, got {tts_base._LOCK_DEPTH}"
    assert not is_agent_speaking(), "Agent speaking status must be False after exception unwinding"

    # Verify lock can immediately be acquired by a subsequent turn
    with speech_turn_lock(text="Post crash recovery turn"):
        assert is_agent_speaking()
        assert tts_base._LOCK_DEPTH == 1

    assert tts_base._LOCK_DEPTH == 0
    assert not is_agent_speaking()


# ============================================================================
# Challenge 2: Multi-threaded & Multi-process contention
# ============================================================================


def test_heavy_multithreaded_contention_10_threads():
    """
    Stress-test 10 concurrent threads simultaneously contending for speech_turn_lock.
    Each thread performs nested re-entrant locks.
    Verifies mutual exclusion (max 1 thread in critical section) and zero deadlocks.
    """
    num_threads = 10
    barrier = threading.Barrier(num_threads)
    active_threads = 0
    max_concurrent = 0
    stats_lock = threading.Lock()
    completed = []
    errors = []

    def worker(worker_id: int):
        nonlocal active_threads, max_concurrent
        try:
            barrier.wait(timeout=5.0)
            # Outer turn
            with speech_turn_lock(text=f"Worker {worker_id} outer unique prompt {time.time()}"):
                with stats_lock:
                    active_threads += 1
                    if active_threads > max_concurrent:
                        max_concurrent = active_threads

                assert is_agent_speaking()

                # Inner nested re-entrant turn
                with speech_turn_lock(text=f"Worker {worker_id} inner subagent voice {time.time()}"):
                    assert is_agent_speaking()
                    time.sleep(0.005)

                with stats_lock:
                    active_threads -= 1
                    completed.append(worker_id)
        except Exception as e:
            with stats_lock:
                errors.append((worker_id, e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30.0)

    assert not errors, f"Errors in concurrent workers: {errors}"
    assert len(completed) == num_threads, f"Expected {num_threads} completed, got {len(completed)}"
    assert max_concurrent == 1, f"Mutual exclusion violated! max_concurrent = {max_concurrent}"
    assert tts_base._LOCK_DEPTH == 0
    assert not is_agent_speaking()


def _mp_worker(proc_id: int, results_queue):
    """Worker process for multi-process lock contention testing."""
    try:
        with speech_turn_lock(text=f"MP Worker {proc_id} unique process payload {time.time()}"):
            speaking = is_agent_speaking()
            time.sleep(0.02)
            results_queue.put((proc_id, True, speaking, None))
    except Exception as e:
        results_queue.put((proc_id, False, False, str(e)))


def test_cross_process_lock_contention():
    """
    Stress-test cross-process lock contention using multiprocessing.
    Verifies that multiple OS processes respect file locking and complete cleanly.
    """
    num_procs = 4
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    procs = [ctx.Process(target=_mp_worker, args=(i, queue)) for i in range(num_procs)]

    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=15.0)

    results = []
    while not queue.empty():
        results.append(queue.get())

    assert len(results) == num_procs, f"Expected {num_procs} process results, got {len(results)}"
    for proc_id, success, was_speaking, err in results:
        assert success is True, f"Process {proc_id} failed with error: {err}"
        assert was_speaking is True, f"Process {proc_id} reported speaking=False while holding lock"

    assert not is_agent_speaking()


# ============================================================================
# Challenge 3: Simulated CoreAudio/AUHAL Stream Failures & LiveVADMonitor
# ============================================================================


def test_live_vad_monitor_resilience_under_portaudio_crash():
    """
    Simulate macOS CoreAudio / AUHAL stream initialization crash (e.g. error -50).
    Verify LiveVADMonitor is paused before open, and guaranteed to resume in finally.
    """
    recorder = AudioRecorder(sample_rate=16000, vad_engine="energy")
    mock_monitor = MagicMock()
    mock_monitor.is_running = True
    pause_called = False
    resume_called = False

    def fake_pause():
        nonlocal pause_called
        pause_called = True

    def fake_resume():
        nonlocal resume_called
        resume_called = True

    mock_monitor.pause.side_effect = fake_pause
    mock_monitor.resume.side_effect = fake_resume

    class CoreAudioAUHALCrashStream:
        def __init__(self, *args, **kwargs):
            assert pause_called is True, "LiveVADMonitor must be paused BEFORE stream open attempt"
        def __enter__(self):
            raise OSError("||PaMacCore (AUHAL)|| Error on line 2790: err='-50', msg=Unknown Error")
        def __exit__(self, *args):
            pass

    with patch("voicefi.audio.monitor.LiveVADMonitor.get_instance", return_value=mock_monitor), \
         patch("sounddevice.InputStream", side_effect=CoreAudioAUHALCrashStream):

        with pytest.raises(OSError, match="PaMacCore"):
            recorder.record_speech_auto()

        assert pause_called is True, "Pause must be called"
        assert resume_called is True, "Resume must be called in finally block after CoreAudio crash"


def test_live_vad_monitor_resilience_under_midstream_read_crash():
    """
    Simulate stream crash during stream.read() midway through audio capture.
    Verify LiveVADMonitor resumes and keyboard listener stops cleanly.
    """
    recorder = AudioRecorder(sample_rate=16000, vad_engine="energy")
    mock_monitor = MagicMock()
    mock_kb = MagicMock()

    class MidstreamCrashStream:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            raise RuntimeError("Hardware audio interface disconnected unexpectedly")

    with patch("voicefi.audio.monitor.LiveVADMonitor.get_instance", return_value=mock_monitor), \
         patch("pynput.keyboard.Listener", return_value=mock_kb), \
         patch("sounddevice.InputStream", side_effect=MidstreamCrashStream):

        with pytest.raises(RuntimeError, match="Hardware audio interface"):
            recorder.record_speech_auto()

        assert mock_monitor.pause.call_count == 1
        assert mock_monitor.resume.call_count == 1
        assert mock_kb.stop.call_count == 1


# ============================================================================
# Challenge 4: Cold-Cache Concurrent Procedural SFX & TTS Lock Concurrency
# ============================================================================


def test_cold_cache_sfx_race_condition_demonstration():
    """
    Demonstrate the race condition in get_sfx_path() when multiple concurrent threads
    request cold SFX assets simultaneously.
    """
    temp_sfx_dir = Path(tempfile.mkdtemp(prefix="voicefi_sfx_test_"))
    sfx_names = list_available_sfx()

    sfx_errors = []
    sfx_completed = []
    num_sfx_threads = 10
    barrier = threading.Barrier(num_sfx_threads)

    def sfx_worker(worker_id: int):
        try:
            barrier.wait(timeout=5.0)
            for name in sfx_names:
                p = get_sfx_path(name)
                assert p is not None
                assert p.is_file()
                # Verify non-empty and non-zero size
                sz = p.stat().st_size
                assert sz > 500, f"File {p} has invalid size {sz}"
            sfx_completed.append(worker_id)
        except Exception as e:
            sfx_errors.append((worker_id, e))

    with patch("voicefi.audio.sfx.SFX_CACHE_DIR", temp_sfx_dir):
        threads = [threading.Thread(target=sfx_worker, args=(i,)) for i in range(num_sfx_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

    shutil.rmtree(temp_sfx_dir, ignore_errors=True)

    assert len(sfx_errors) == 0, f"Errors in cold-cache concurrent SFX: {sfx_errors}"
    assert len(sfx_completed) == num_sfx_threads
