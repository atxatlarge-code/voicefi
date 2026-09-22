"""
Unit and concurrency tests for VoiceFi audio concurrency, re-entrancy, and pipeline lifecycle.
Verifies:
1. Nested re-entrant acquisitions of speech_turn_lock.
2. Rapid concurrent speak turn requests across multiple threads.
3. Pausing and resuming of LiveVADMonitor during auto speech recording (and PTT).
4. SFX concurrent playback alongside speech locks.
5. Error unwinding and mutual exclusion guarantees.
"""

import time
import threading
import tempfile
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
    clear_speech_stopped_time,
    get_agent_speaking_info,
)
import voicefi.tts.base as tts_base
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.monitor import LiveVADMonitor
from voicefi.audio.sfx import (
    play_sfx,
    get_sfx_path,
    list_available_sfx,
    strip_inline_sfx_tags,
)


@pytest.fixture(autouse=True)
def clean_audio_state():
    """Ensure all audio and speaking lock states are clean before and after each test."""
    set_agent_speaking(False)
    clear_recent_speech_history()
    clear_speech_stopped_time()
    tts_base._LOCK_DEPTH = 0
    with patch("pynput.keyboard.Listener", return_value=MagicMock()):
        yield
    set_agent_speaking(False)
    clear_recent_speech_history()
    clear_speech_stopped_time()
    tts_base._LOCK_DEPTH = 0


# ============================================================================
# 1. Nested Re-entrant Acquisitions of speech_turn_lock
# ============================================================================


def test_speech_turn_lock_nested_reentrancy():
    """
    Verify that speech_turn_lock supports re-entrant calls within the same thread.
    With threading.RLock, nested with speech_turn_lock() calls must NOT deadlock.
    """
    assert not is_agent_speaking()
    assert tts_base._LOCK_DEPTH == 0

    with speech_turn_lock(text="Outer turn 1"):
        assert is_agent_speaking()
        assert tts_base._LOCK_DEPTH == 1

        # Level 2 nesting
        with speech_turn_lock(text="Inner turn 2"):
            assert is_agent_speaking()
            assert tts_base._LOCK_DEPTH == 2

            # Level 3 nesting
            with speech_turn_lock(text="Deep inner turn 3"):
                assert is_agent_speaking()
                assert tts_base._LOCK_DEPTH == 3

            assert is_agent_speaking()
            assert tts_base._LOCK_DEPTH == 2

        assert is_agent_speaking()
        assert tts_base._LOCK_DEPTH == 1

    assert not is_agent_speaking()
    assert tts_base._LOCK_DEPTH == 0


def test_speech_turn_lock_nested_exception_unwinding():
    """Verify that exceptions raised inside nested locks cleanly unwind _LOCK_DEPTH."""
    assert tts_base._LOCK_DEPTH == 0

    with pytest.raises(RuntimeError, match="Inner test failure"):
        with speech_turn_lock(text="Outer lock for error test"):
            assert tts_base._LOCK_DEPTH == 1
            with speech_turn_lock(text="Inner lock for error test"):
                assert tts_base._LOCK_DEPTH == 2
                raise RuntimeError("Inner test failure")

    assert tts_base._LOCK_DEPTH == 0
    assert not is_agent_speaking()


# ============================================================================
# 2. Rapid Concurrent Speak Turn Requests Across Multiple Threads
# ============================================================================


def test_rapid_concurrent_speak_turn_requests():
    """
    Verify that multiple threads concurrently competing for speech_turn_lock
    maintain strict mutual exclusion (at most 1 thread in the critical section)
    and all complete without deadlock or state corruption.
    """
    num_threads = 8
    barrier = threading.Barrier(num_threads)
    active_count = 0
    max_concurrent = 0
    lock_stats = threading.Lock()
    completed_threads = []
    errors = []

    def worker(worker_id: int):
        nonlocal active_count, max_concurrent
        try:
            # Wait for all threads to be ready for maximum contention
            barrier.wait(timeout=5.0)
            
            with speech_turn_lock(text=f"Worker speech {worker_id} - unique text"):
                with lock_stats:
                    active_count += 1
                    if active_count > max_concurrent:
                        max_concurrent = active_count

                # Critical section: simulate short speech work
                assert is_agent_speaking(), f"Worker {worker_id}: agent speaking should be True"
                time.sleep(0.02)

                with lock_stats:
                    active_count -= 1
                    completed_threads.append(worker_id)
        except Exception as e:
            with lock_stats:
                errors.append((worker_id, e))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert not errors, f"Errors occurred in concurrent workers: {errors}"
    assert len(completed_threads) == num_threads, f"Expected {num_threads} threads, completed: {len(completed_threads)}"
    assert max_concurrent == 1, f"Expected strict mutual exclusion (max 1), got {max_concurrent}"
    assert not is_agent_speaking()
    assert tts_base._LOCK_DEPTH == 0


def test_multithreaded_nested_reentrant_concurrency():
    """
    Verify that concurrent threads each executing nested re-entrant locks
    maintain both per-thread re-entrancy and cross-thread mutual exclusion.
    """
    num_threads = 6
    barrier = threading.Barrier(num_threads)
    max_concurrent = 0
    active_count = 0
    lock_stats = threading.Lock()
    completed = []

    def worker(worker_id: int):
        nonlocal active_count, max_concurrent
        barrier.wait(timeout=5.0)
        with speech_turn_lock(text=f"Thread {worker_id} outer unique utterance"):
            with lock_stats:
                active_count += 1
                if active_count > max_concurrent:
                    max_concurrent = active_count

            # Nested re-entrant acquisition in same thread
            with speech_turn_lock(text=f"Thread {worker_id} inner unique utterance"):
                time.sleep(0.01)

            with lock_stats:
                active_count -= 1
                completed.append(worker_id)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(completed) == num_threads
    assert max_concurrent == 1
    assert not is_agent_speaking()
    assert tts_base._LOCK_DEPTH == 0


# ============================================================================
# 3. Pausing and Resuming LiveVADMonitor During Recording
# ============================================================================


def test_live_vad_monitor_pause_and_resume_during_auto_recording():
    """
    Verify that record_speech_auto() pauses LiveVADMonitor upon entering
    and resumes it in finally block upon completion.
    """
    sample_rate = 16000
    recorder = AudioRecorder(
        sample_rate=sample_rate,
        energy_threshold=0.01,
        silence_duration=0.6,
        max_record_seconds=5.0,
        vad_engine="energy",
    )

    mock_monitor = MagicMock()
    mock_monitor.pause = MagicMock()
    mock_monitor.resume = MagicMock()

    chunk_duration = 0.05
    chunk_size = int(sample_rate * chunk_duration)
    silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)
    loud_chunk = np.ones((chunk_size, 1), dtype=np.float32) * 0.08

    chunks = (
        [loud_chunk] * 4 +     # speech start
        [silence_chunk] * 15   # natural silence -> end
    )
    current_idx = [0]

    class MockStream:
        def __init__(self, *args, **kwargs):
            # Assert that pause was called BEFORE InputStream was created / opened!
            assert mock_monitor.pause.called, "LiveVADMonitor.pause() must be called BEFORE creating input stream"
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

    with patch("voicefi.audio.monitor.LiveVADMonitor.get_instance", return_value=mock_monitor), \
         patch("sounddevice.InputStream", side_effect=MockStream):

        audio, wav_path = recorder.record_speech_auto()

        assert mock_monitor.pause.call_count == 1, "Expected exactly 1 pause call"
        assert mock_monitor.resume.call_count == 1, "Expected exactly 1 resume call in finally"
        if wav_path:
            wav_path.unlink(missing_ok=True)


def test_live_vad_monitor_resumed_on_stream_exception():
    """
    Verify that if an exception occurs during InputStream initialization or reading,
    LiveVADMonitor is STILL cleanly resumed in the finally block.
    """
    recorder = AudioRecorder(sample_rate=16000, vad_engine="energy")
    mock_monitor = MagicMock()

    class FailingStream:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            raise RuntimeError("PortAudio AUHAL Device contention error simulated")
        def __exit__(self, *args):
            pass

    with patch("voicefi.audio.monitor.LiveVADMonitor.get_instance", return_value=mock_monitor), \
         patch("sounddevice.InputStream", side_effect=FailingStream):

        with pytest.raises(RuntimeError, match="PortAudio AUHAL"):
            recorder.record_speech_auto()

        # Verify pause and resume were both invoked
        assert mock_monitor.pause.call_count == 1
        assert mock_monitor.resume.call_count == 1, "LiveVADMonitor must be resumed even on stream crash"


def test_live_vad_monitor_pause_and_resume_ptt():
    """Verify that record_push_to_talk() also pauses and resumes LiveVADMonitor."""
    sample_rate = 16000
    recorder = AudioRecorder(sample_rate=sample_rate, vad_engine="energy")
    mock_monitor = MagicMock()

    stop_evt = threading.Event()
    chunk_size = int(sample_rate * 0.05)
    silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)

    class PTTMockStream:
        def __init__(self, *args, **kwargs):
            assert mock_monitor.pause.called
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            stop_evt.set()
            return silence_chunk, False

    with patch("voicefi.audio.monitor.LiveVADMonitor.get_instance", return_value=mock_monitor), \
         patch("sounddevice.InputStream", side_effect=PTTMockStream):

        audio, wav_path = recorder.record_push_to_talk(stop_event=stop_evt)
        assert mock_monitor.pause.call_count == 1
        assert mock_monitor.resume.call_count == 1
        if wav_path:
            wav_path.unlink(missing_ok=True)


# ============================================================================
# 4. SFX Concurrent Playback Alongside Speech Locks
# ============================================================================


def test_sfx_generation_and_playback_concurrency():
    """
    Verify that synthetic sound effects (rimshot, honk, applause, sad_trombone, boing, crickets)
    can be generated and played concurrently alongside active speech locks without deadlocks.
    """
    sfx_names = list_available_sfx()
    assert "drum_smash" in sfx_names
    assert "honk" in sfx_names
    assert "applause" in sfx_names
    assert "sad_trombone" in sfx_names
    assert "boing" in sfx_names
    assert "crickets" in sfx_names

    sfx_errors = []
    speech_completed = []

    def sfx_worker():
        try:
            with patch("subprocess.run") as mock_afplay:
                for _ in range(5):
                    for name in sfx_names:
                        # Verify path generation works cleanly and produces valid file
                        p = get_sfx_path(name)
                        assert p is not None and p.is_file() and p.stat().st_size > 0
                        # Test non-blocking play_sfx with subprocess mock
                        res = play_sfx(name, block=False)
                        assert res is True
                    time.sleep(0.01)
        except Exception as e:
            sfx_errors.append(e)

    def speech_worker(worker_id: int):
        try:
            for step in range(3):
                with speech_turn_lock(text=f"Concurrent speech {worker_id}-{step}"):
                    assert is_agent_speaking()
                    time.sleep(0.01)
            speech_completed.append(worker_id)
        except Exception as e:
            sfx_errors.append(e)

    sfx_thread = threading.Thread(target=sfx_worker)
    speech_threads = [threading.Thread(target=speech_worker, args=(i,)) for i in range(4)]

    sfx_thread.start()
    for st in speech_threads:
        st.start()

    sfx_thread.join(timeout=10.0)
    for st in speech_threads:
        st.join(timeout=10.0)

    assert not sfx_errors, f"SFX / Speech concurrency errors: {sfx_errors}"
    assert len(speech_completed) == 4
    assert not is_agent_speaking()


def test_strip_inline_sfx_tags():
    """Verify inline SFX tags are stripped cleanly without corrupting speech text."""
    text = "Great job on the release! [sfx:applause] That was fast. [honk] [rimshot]"
    cleaned = strip_inline_sfx_tags(text)
    assert cleaned == "Great job on the release! That was fast."

    text_no_sfx = "Normal sentence without sound effects."
    assert strip_inline_sfx_tags(text_no_sfx) == text_no_sfx


# ============================================================================
# 5. Duplicate Speech Suppression Under Locks
# ============================================================================


def test_duplicate_speech_suppression_resets_lock_cleanly():
    """
    Verify that if duplicate speech is suppressed within speech_turn_lock,
    it raises DuplicateSpeechSuppressed and unwinds the lock cleanly.
    """
    sample_text = "This is a unique utterance for suppression testing."

    # First acquisition should succeed
    with speech_turn_lock(text=sample_text):
        assert is_agent_speaking()

    assert not is_agent_speaking()
    assert tts_base._LOCK_DEPTH == 0

    # Immediate second acquisition with identical text within 6.0s must raise DuplicateSpeechSuppressed
    with pytest.raises(DuplicateSpeechSuppressed):
        with speech_turn_lock(text=sample_text):
            pass

    # Verify lock and speaking status are completely clean after suppression exception
    assert not is_agent_speaking()
    assert tts_base._LOCK_DEPTH == 0


# ============================================================================
# 6. Microphone Recording Lifecycle & Turn Coordination
# ============================================================================


def test_mic_recording_status_lifecycle():
    """Verify set_mic_recording, get_mic_recording_info, and is_mic_recording_active."""
    from voicefi.tts.base import (
        set_mic_recording,
        get_mic_recording_info,
        is_mic_recording_active,
    )

    try:
        set_mic_recording(False)
        assert not is_mic_recording_active()
        assert get_mic_recording_info() is None

        set_mic_recording(True, state="listening", conv_id="conv-123", agent_name="Viv")
        assert is_mic_recording_active()
        info = get_mic_recording_info()
        assert info is not None
        assert info["state"] == "listening"
        assert info["conv_id"] == "conv-123"
        assert info["agent_name"] == "Viv"

        # Update to hearing
        set_mic_recording(True, state="hearing", conv_id="conv-123", agent_name="Viv")
        info = get_mic_recording_info()
        assert info is not None
        assert info["state"] == "hearing"

        set_mic_recording(False)
        assert not is_mic_recording_active()
        assert get_mic_recording_info() is None
    finally:
        set_mic_recording(False)


def test_speech_turn_lock_waits_for_active_mic_recording():
    """Verify speech_turn_lock waits politely while another conversation's mic is active."""
    from voicefi.tts.base import (
        set_mic_recording,
        speech_turn_lock,
    )

    try:
        # Simulate active recording in another conversation
        set_mic_recording(True, state="hearing", conv_id="conv-other")

        lock_entered = [False]

        def _try_speak():
            with speech_turn_lock(text="Turn waiting for mic", conv_id="conv-current"):
                lock_entered[0] = True

        t = threading.Thread(target=_try_speak, daemon=True)
        t.start()

        # Speech should be waiting because mic is active in conv-other
        time.sleep(0.3)
        assert not lock_entered[0]

        # Release the microphone
        set_mic_recording(False)

        # Thread should now acquire lock and enter
        t.join(timeout=2.0)
        assert lock_entered[0]
    finally:
        set_mic_recording(False)


def test_speech_turn_lock_barge_in_same_conv_does_not_block():
    """Verify speech_turn_lock does not self-deadlock when mic recording is from the same process & conv_id."""
    from voicefi.tts.base import (
        set_mic_recording,
        speech_turn_lock,
    )

    try:
        # Simulate barge-in where same conv_id and process is recording
        set_mic_recording(True, state="listening", conv_id="conv-barge-in")

        entered = False
        with speech_turn_lock(text="Barge-in speech turn", conv_id="conv-barge-in"):
            entered = True

        assert entered
    finally:
        set_mic_recording(False)


def test_queued_speech_turn_cancelled_on_stop_all_speech():
    """
    Verify that if Turn A is actively speaking and Turn B is waiting in queue,
    calling stop_all_speech() cancels Turn A AND causes Turn B to be suppressed
    without speaking upon acquiring the lock.
    """
    from voicefi.tts.base import record_speech_stopped

    turn_a_started = threading.Event()
    turn_b_attempted = threading.Event()
    turn_b_suppressed = [False]
    turn_b_spoke = [False]

    def _turn_a():
        with speech_turn_lock(text="Guy speaking for Turn A", persona_name="Guy"):
            turn_a_started.set()
            # Wait until Turn B has enqueued and stop_all_speech has been called
            time.sleep(0.35)

    def _turn_b():
        # Ensure Turn A has already acquired lock
        turn_a_started.wait(timeout=2.0)
        time.sleep(0.05)  # Let Turn A establish ownership
        turn_b_attempted.set()
        try:
            with speech_turn_lock(text="Viv speaking for Turn B", persona_name="Viv"):
                turn_b_spoke[0] = True
        except DuplicateSpeechSuppressed:
            turn_b_suppressed[0] = True

    t_a = threading.Thread(target=_turn_a, daemon=True)
    t_b = threading.Thread(target=_turn_b, daemon=True)

    t_a.start()
    turn_a_started.wait(timeout=2.0)
    t_b.start()
    turn_b_attempted.wait(timeout=2.0)
    time.sleep(0.08)  # Let Turn B enter flock wait queue

    # User presses Esc / stop_all_speech() is triggered
    record_speech_stopped()

    t_a.join(timeout=3.0)
    t_b.join(timeout=3.0)

    # Turn B must have been suppressed and must NOT have spoken!
    assert turn_b_suppressed[0], "Expected Turn B to be suppressed by queue stop guard"
    assert not turn_b_spoke[0], "Turn B should never have spoken"


def test_sequential_turns_distinct_personas_hud_state():
    """
    Verify that sequential turns with different personas (e.g. Guy, then Viv)
    cleanly update persona_name in get_agent_speaking_info() in exact order.
    """
    first_persona = None
    second_persona = None

    with speech_turn_lock(text="First turn by Guy", persona_name="Guy", conv_id="conv-guy"):
        info_1 = get_agent_speaking_info()
        assert info_1 is not None
        first_persona = info_1.get("persona_name")

    # After Turn 1 completes, speaking info is cleared
    assert get_agent_speaking_info() is None

    with speech_turn_lock(text="Second turn by Viv", persona_name="Viv", conv_id="conv-viv"):
        info_2 = get_agent_speaking_info()
        assert info_2 is not None
        second_persona = info_2.get("persona_name")

    assert first_persona == "Guy"
    assert second_persona == "Viv"
    assert get_agent_speaking_info() is None

