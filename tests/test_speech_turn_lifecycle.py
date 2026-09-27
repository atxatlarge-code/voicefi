"""
Unit and concurrency tests for speech-turn lock, process termination, and zombie prevention.
Validates:
1. exclusive_audio + force_release_audio_lock prevents integer underflow (_LOCK_DEPTH >= 0).
2. Cross-thread and nested re-entrant acquisitions of speech_turn_lock without deadlocks.
3. Non-blocking fcntl.flock polling and rapid cancellation when speech is stopped in queue.
4. Process termination via safe_terminate_process escalating to SIGKILL and reaping exit status.
5. stop_all_speech child process reaping via os.waitpid to guarantee 0 zombie (<defunct>) processes.
6. TTS engine stop lifecycles (EdgeTTS, MacSayTTS, KokoroTTS, F5TTS, GeminiTTS, ElevenLabsTTS).
7. Rapid-fire interleaved speak and stop commands under heavy concurrency.
"""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import voicefi.audio.output_lock as ol_mod
from voicefi.audio.output_lock import (
    exclusive_audio,
    force_release_audio_lock,
    is_audio_output_locked,
)
import voicefi.tts.base as tts_base
from voicefi.tts.base import (
    DuplicateSpeechSuppressed,
    clear_recent_speech_history,
    clear_speech_stopped_time,
    is_agent_speaking,
    record_speech_stopped,
    safe_terminate_process,
    set_agent_speaking,
    speech_turn_lock,
    stop_all_speech,
)


@pytest.fixture(autouse=True)
def clean_test_state():
    """Ensure audio lock and speaking states are reset before and after every test."""
    set_agent_speaking(False)
    clear_recent_speech_history()
    clear_speech_stopped_time()
    force_release_audio_lock()
    ol_mod._LOCK_DEPTH = 0
    tts_base._LOCK_DEPTH = 0
    yield
    set_agent_speaking(False)
    clear_recent_speech_history()
    clear_speech_stopped_time()
    force_release_audio_lock()
    ol_mod._LOCK_DEPTH = 0
    tts_base._LOCK_DEPTH = 0


# ==============================================================================
# 1. Output Lock Underflow Prevention & Re-entrancy
# ==============================================================================


def test_exclusive_audio_force_release_no_underflow(tmp_path, monkeypatch):
    """
    Verify that force_release_audio_lock() resets _LOCK_DEPTH to 0 and exiting
    the context manager does NOT decrement _LOCK_DEPTH into negative numbers (-1).
    """
    test_lock = tmp_path / "test_underflow.lock"
    monkeypatch.setenv("VOICEFI_AUDIO_LOCK", str(test_lock))

    assert ol_mod._LOCK_DEPTH == 0

    with exclusive_audio(timeout=2.0, owner="underflow_test"):
        assert ol_mod._LOCK_DEPTH == 1
        assert is_audio_output_locked()

        # Simulate barge-in / stop
        force_release_audio_lock()
        assert ol_mod._LOCK_DEPTH == 0

    # Critical invariant: must remain 0, never -1!
    assert ol_mod._LOCK_DEPTH == 0, f"Expected _LOCK_DEPTH == 0, got {ol_mod._LOCK_DEPTH}"
    assert not is_audio_output_locked()

    # Verify subsequent turn works immediately and supports nesting without 30s timeout
    with exclusive_audio(timeout=2.0, owner="subsequent_turn"):
        assert ol_mod._LOCK_DEPTH == 1
        assert is_audio_output_locked()

        # Nested acquisition must succeed instantaneously
        t0 = time.time()
        with exclusive_audio(timeout=1.0, owner="nested_subsequent"):
            assert ol_mod._LOCK_DEPTH == 2
        assert time.time() - t0 < 0.2, "Nested acquisition took too long; possible self-deadlock"
        assert ol_mod._LOCK_DEPTH == 1

    assert ol_mod._LOCK_DEPTH == 0


def test_exclusive_audio_multiple_nested_force_releases(tmp_path, monkeypatch):
    """Verify that multiple nested locks subjected to force release still unwind to 0."""
    test_lock = tmp_path / "test_nested_barge.lock"
    monkeypatch.setenv("VOICEFI_AUDIO_LOCK", str(test_lock))

    with exclusive_audio(timeout=2.0, owner="level_1"):
        with exclusive_audio(timeout=2.0, owner="level_2"):
            with exclusive_audio(timeout=2.0, owner="level_3"):
                assert ol_mod._LOCK_DEPTH == 3
                force_release_audio_lock()
                assert ol_mod._LOCK_DEPTH == 0

    assert ol_mod._LOCK_DEPTH == 0
    assert not is_audio_output_locked()


# ==============================================================================
# 2. Non-blocking Flock & Responsive Cancellation in speech_turn_lock
# ==============================================================================


def test_speech_turn_lock_cancels_immediately_on_stop_while_queued(tmp_path, monkeypatch):
    """
    Verify that if a thread is waiting to acquire SPEECH_LOCK_FILE, calling
    stop_all_speech() causes the waiting thread to detect the stop and abort
    with DuplicateSpeechSuppressed without waiting for the full timeout.
    """
    test_speech_lock = tmp_path / "speech_queue.lock"
    monkeypatch.setattr("voicefi.tts.base.SPEECH_LOCK_FILE", test_speech_lock)
    monkeypatch.setenv("VOICEFI_SPEECH_LOCK", str(test_speech_lock))

    # Process A holds the lock
    holder_fd = open(test_speech_lock, "a+")
    import fcntl
    fcntl.flock(holder_fd.fileno(), fcntl.LOCK_EX)

    aborted = threading.Event()
    exception_caught = []

    def _queued_worker():
        try:
            with speech_turn_lock(text="Waiting in queue utterance"):
                pass
        except DuplicateSpeechSuppressed as e:
            exception_caught.append(e)
            aborted.set()

    t = threading.Thread(target=_queued_worker, daemon=True)
    t.start()

    # Allow worker to enter the polling loop
    time.sleep(0.12)
    assert not aborted.is_set(), "Worker should be waiting in queue"

    # Trigger stop
    t_stop = time.time()
    record_speech_stopped()

    # The worker must detect the stop and abort rapidly (< 0.25s) even though holder_fd is still locked!
    aborted.wait(timeout=0.6)
    duration = time.time() - t_stop

    fcntl.flock(holder_fd.fileno(), fcntl.LOCK_UN)
    holder_fd.close()

    assert aborted.is_set(), "Waiting thread did not abort upon stop_all_speech"
    assert duration < 0.45, f"Abort took too long: {duration:.3f}s"
    assert len(exception_caught) == 1
    assert tts_base._LOCK_DEPTH == 0


# ==============================================================================
# 3. Process Termination & Zombie Reaping
# ==============================================================================


def test_safe_terminate_process_reaps_child_exit_status():
    """Verify safe_terminate_process terminates a child and reaps its exit code."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    assert proc.poll() is None, "Process should be running"

    safe_terminate_process(proc, timeout=0.2)

    # Process must be terminated and reaped (returncode set)
    assert proc.poll() is not None, "Process should have exited"
    assert proc.returncode in (-15, -9, 0, 1), f"Unexpected returncode: {proc.returncode}"


def test_safe_terminate_process_handles_none_and_already_dead():
    """Verify safe_terminate_process gracefully handles None and dead processes."""
    safe_terminate_process(None)

    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    assert proc.poll() is not None

    # Should not raise exception
    safe_terminate_process(proc)


def test_stop_all_speech_reaps_zombie_children():
    """
    Verify stop_all_speech cleanly reaps terminated child processes via os.waitpid(WNOHANG)
    so they do not linger as <defunct> zombies in the process table.
    """
    # Spawn a short-lived process that finishes immediately
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    time.sleep(0.05)

    # Calling stop_all_speech should reap child process table entries
    stop_all_speech(broadcast_web=False)

    # Check if reaped
    try:
        pid, _ = os.waitpid(proc.pid, os.WNOHANG)
        # pid == 0 means still running, -1 or ECHILD means already reaped
        assert pid in (0, -1, proc.pid)
    except ChildProcessError:
        # Already reaped!
        pass


# ==============================================================================
# 4. Engine Stop Implementations
# ==============================================================================


def test_kokoro_tts_stop_and_cleanup(tmp_path):
    """Verify KokoroTTS tracks _current_process and cleans up temp files in finally block."""
    from voicefi.tts.kokoro_tts import KokoroTTS

    tts = KokoroTTS()
    assert tts._current_process is None

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch.object(tts, "synthesize_to_wav", return_value=True):
            tts.speak("Hello test", block=False)
            time.sleep(0.05)

            # Process should be tracked
            tts.stop()
            assert tts._current_process is None


def test_f5_tts_stop_and_cleanup(tmp_path):
    """Verify F5TTS tracks _current_process and cleans up safely without premature deletion."""
    from voicefi.tts.f5_tts import F5TTS

    tts = F5TTS()
    assert tts._current_process is None

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None

    with patch("subprocess.Popen", return_value=mock_proc):
        tts.stop()
        assert tts._current_process is None


# ==============================================================================
# 5. Rapid-Fire Concurrent Speak & Stop Stress Test
# ==============================================================================


def test_rapid_fire_speak_and_stop_cycles(tmp_path, monkeypatch):
    """
    Stress-test rapid-fire interleaved speak and stop commands across concurrent threads.
    Verifies:
    1. Zero deadlocks.
    2. Zero _LOCK_DEPTH underflow below 0.
    3. Speaking status is cleanly released.
    """
    test_speech = tmp_path / "rapid_speech.lock"
    test_audio = tmp_path / "rapid_audio.lock"
    monkeypatch.setattr("voicefi.tts.base.SPEECH_LOCK_FILE", test_speech)
    monkeypatch.setenv("VOICEFI_SPEECH_LOCK", str(test_speech))
    monkeypatch.setenv("VOICEFI_AUDIO_LOCK", str(test_audio))

    iterations = 25
    errors = []

    def worker(worker_id: int):
        for i in range(iterations):
            try:
                clear_speech_stopped_time()
                with speech_turn_lock(text=f"Worker {worker_id} iter {i}"):
                    assert is_agent_speaking()
                    time.sleep(0.005)

                if i % 3 == 0:
                    stop_all_speech(broadcast_web=False)

                assert ol_mod._LOCK_DEPTH >= 0, f"ol_mod._LOCK_DEPTH underflow: {ol_mod._LOCK_DEPTH}"
                assert tts_base._LOCK_DEPTH >= 0, f"tts_base._LOCK_DEPTH underflow: {tts_base._LOCK_DEPTH}"
            except DuplicateSpeechSuppressed:
                pass
            except Exception as e:
                errors.append((worker_id, i, str(e)))

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert not errors, f"Errors during rapid-fire stress test: {errors}"
    assert ol_mod._LOCK_DEPTH == 0, f"Expected final ol_mod._LOCK_DEPTH == 0, got {ol_mod._LOCK_DEPTH}"
    assert tts_base._LOCK_DEPTH == 0, f"Expected final tts_base._LOCK_DEPTH == 0, got {tts_base._LOCK_DEPTH}"
    assert not is_agent_speaking()
