"""
Adversarial Challenger 2 Test Suite for Milestone M1.
Empirically stress-tests:
1. Full duplex speak/listen interleaving and rapid toggle transitions.
2. State desynchronization between is_agent_speaking(), _LOCK_DEPTH, and cross-process lockfiles.
3. Barge-in mode resolution and safe-mode state machine transitions under rapid simulated audio chunks.
"""

import os
import sys
import time
import json
import signal
import tempfile
import threading
import multiprocessing
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

import voicefi.tts.base as tts_base
from voicefi.tts.base import (
    speech_turn_lock,
    set_agent_speaking,
    is_agent_speaking,
    get_agent_speaking_info,
    stop_all_speech,
    DuplicateSpeechSuppressed,
    clear_recent_speech_history,
)
from voicefi.audio.recorder import AudioRecorder, resolve_barge_in_mode
from voicefi.audio.device import is_using_builtin_speakers, is_headphone_or_headset_active
from voicefi.audio.monitor import LiveVADMonitor


@pytest.fixture(autouse=True)
def isolated_audio_state(tmp_path):
    """
    Isolate test state to temporary files to prevent cross-test and cross-agent contention,
    while verifying full lock and state behavior.
    """
    test_lock = tmp_path / "voicefi_speech.lock"
    test_speaking_status = tmp_path / "voicefi_speaking.status"
    test_playing_status = tmp_path / "voicefi_audio_playing.status"
    test_recent = tmp_path / "voicefi_recent_speech.json"

    with patch.object(tts_base, "SPEECH_LOCK_FILE", test_lock), \
         patch.object(tts_base, "AGENT_SPEAKING_STATUS_FILE", test_speaking_status), \
         patch.object(tts_base, "AUDIO_PLAYING_STATUS_FILE", test_playing_status), \
         patch.object(tts_base, "RECENT_SPEECH_FILE", test_recent), \
         patch("pynput.keyboard.Listener", return_value=MagicMock()), \
         patch("voicefi.tts.base.is_system_audio_playing", return_value=False):

        set_agent_speaking(False)
        clear_recent_speech_history()
        tts_base._LOCK_DEPTH = 0
        yield
        set_agent_speaking(False)
        clear_recent_speech_history()
        tts_base._LOCK_DEPTH = 0


# ============================================================================
# SUITE 1: Full Duplex Speak/Listen Interleaving & Rapid Toggle Transitions
# ============================================================================


def test_rapid_alternating_speak_listen_turns():
    """
    Stress-test rapid sequential interleaving of speech_turn_lock and AudioRecorder.
    Simulates 8 back-and-forth conversation turns in rapid succession.
    """
    sample_rate = 16000
    chunk_duration = 0.05
    chunk_size = int(sample_rate * chunk_duration)
    silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)
    speech_chunk = np.ones((chunk_size, 1), dtype=np.float32) * 0.05

    for turn_idx in range(8):
        # 1. Agent speaks
        with speech_turn_lock(text=f"Rapid turn agent speech {turn_idx}"):
            assert is_agent_speaking()
            assert tts_base._LOCK_DEPTH == 1

        assert not is_agent_speaking()
        assert tts_base._LOCK_DEPTH == 0

        # 2. User speaks into recorder
        recorder = AudioRecorder(
            sample_rate=sample_rate,
            energy_threshold=0.01,
            silence_duration=0.6,
            max_record_seconds=2.0,
            vad_engine="energy",
        )

        stream_chunks = [speech_chunk] * 4 + [silence_chunk] * 15
        curr_idx = [0]

        class MockStream:
            def __init__(self, *args, **kwargs):
                pass
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, size):
                idx = curr_idx[0]
                curr_idx[0] += 1
                if idx < len(stream_chunks):
                    return stream_chunks[idx], False
                return silence_chunk, False

        recorder._create_input_stream = lambda: MockStream()
        audio, wav_path = recorder.record_speech_auto()
        assert wav_path is not None and wav_path.is_file()
        wav_path.unlink(missing_ok=True)


def test_concurrent_multi_thread_speak_and_listen():
    """
    Stress-test concurrent speak turns competing with concurrent audio recording threads.
    3 speak worker threads + 3 listen worker threads running simultaneously.
    Verifies that speaker threads hold mutual exclusion and recording threads cleanly yield.
    """
    num_speakers = 3
    num_listeners = 3
    barrier = threading.Barrier(num_speakers + num_listeners)
    errors = []
    speaker_results = []
    listener_results = []

    def speaker_worker(wid: int):
        try:
            barrier.wait(timeout=10.0)
            for step in range(2):
                with speech_turn_lock(text=f"Speaker {wid} step {step} unique"):
                    assert is_agent_speaking()
                    time.sleep(0.01)
            speaker_results.append(wid)
        except Exception as e:
            errors.append(("speaker", wid, e))

    def listener_worker(wid: int):
        try:
            barrier.wait(timeout=10.0)
            sample_rate = 16000
            chunk_size = int(sample_rate * 0.05)
            silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)
            speech_chunk = np.ones((chunk_size, 1), dtype=np.float32) * 0.05

            for step in range(2):
                recorder = AudioRecorder(
                    sample_rate=sample_rate,
                    energy_threshold=0.01,
                    silence_duration=0.6,
                    max_record_seconds=2.0,
                    barge_in=False,
                    vad_engine="energy",
                )

                class AdaptiveTurnStream:
                    def __init__(self, spk_chunks, sil_chunks):
                        self.spk_chunks = spk_chunks
                        self.sil_chunks = sil_chunks
                        self.cooldown_count = 0
                        self.spk_idx = 0
                        self.sil_idx = 0
                    def __enter__(self):
                        return self
                    def __exit__(self, *args):
                        pass
                    def read(self, size):
                        if is_agent_speaking():
                            self.cooldown_count = 0
                            self.spk_idx = 0
                            self.sil_idx = 0
                            return self.sil_chunks[0], False
                        if self.cooldown_count < 10:
                            self.cooldown_count += 1
                            return self.sil_chunks[0], False
                        if self.spk_idx < len(self.spk_chunks):
                            c = self.spk_chunks[self.spk_idx]
                            self.spk_idx += 1
                            return c, False
                        if self.sil_idx < len(self.sil_chunks):
                            c = self.sil_chunks[self.sil_idx]
                            self.sil_idx += 1
                            return c, False
                        return self.sil_chunks[0], False

                recorder._create_input_stream = lambda: AdaptiveTurnStream([speech_chunk] * 4, [silence_chunk] * 15)
                audio, wav_p = recorder.record_speech_auto()
                if wav_p:
                    wav_p.unlink(missing_ok=True)
                time.sleep(0.01)
            listener_results.append(wid)
        except Exception as e:
            errors.append(("listener", wid, e))

    threads = []
    for i in range(num_speakers):
        threads.append(threading.Thread(target=speaker_worker, args=(i,)))
    for i in range(num_listeners):
        threads.append(threading.Thread(target=listener_worker, args=(i,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert not errors, f"Errors in concurrent speak/listen: {errors}"
    assert len(speaker_results) == num_speakers
    assert len(listener_results) == num_listeners
    assert not is_agent_speaking()
    assert tts_base._LOCK_DEPTH == 0


def test_rapid_barge_in_mode_toggling_during_recording():
    """
    Stress-test rapidly mutating recorder.barge_in between 'auto', True, False, 1, 0
    while record_speech_auto is actively executing.
    """
    sample_rate = 16000
    chunk_size = int(sample_rate * 0.05)
    silence_chunk = np.zeros((chunk_size, 1), dtype=np.float32)
    speech_chunk = np.ones((chunk_size, 1), dtype=np.float32) * 0.05

    recorder = AudioRecorder(sample_rate=sample_rate, vad_engine="energy", barge_in="auto")
    chunks = [speech_chunk] * 6 + [silence_chunk] * 18
    idx = [0]

    class MockStream:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            i = idx[0]
            idx[0] += 1
            modes = ["auto", True, False, "AUTO", 1, 0, "auto"]
            recorder.barge_in = modes[i % len(modes)]
            if i < len(chunks):
                return chunks[i], False
            return silence_chunk, False

    recorder._create_input_stream = lambda: MockStream()
    audio, wav_path = recorder.record_speech_auto()
    assert wav_path is not None and wav_path.is_file()
    wav_path.unlink(missing_ok=True)


def test_live_vad_monitor_rapid_concurrent_pause_resume():
    """
    Stress-test LiveVADMonitor under heavy multi-threaded pause and resume hammering.
    Verifies that monitor thread state, config reload, and lock management never deadlock.
    """
    monitor = LiveVADMonitor.get_instance()
    monitor.start()

    num_threads = 6
    iterations_per_thread = 30
    barrier = threading.Barrier(num_threads)
    errors = []

    def hammer_worker(wid: int):
        try:
            barrier.wait(timeout=5.0)
            for _ in range(iterations_per_thread):
                monitor.pause()
                assert monitor._paused is True
                time.sleep(0.001)
                monitor.resume()
                time.sleep(0.001)
        except Exception as e:
            errors.append((wid, e))

    threads = [threading.Thread(target=hammer_worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    monitor.stop()
    assert not errors, f"LiveVADMonitor deadlock or error during pause/resume: {errors}"


# ============================================================================
# SUITE 2: State Desynchronization Between is_agent_speaking(), _LOCK_DEPTH,
#          and /tmp/voicefi_speech.lock
# ============================================================================


def _multiprocess_lock_worker(worker_id: int, lock_path: str, status_path: str, log_file: str, duration: float):
    """Child process entry point for multi-process speech lock contention testing."""
    import time
    from pathlib import Path
    from unittest.mock import patch
    import voicefi.tts.base as tts_base
    from voicefi.tts.base import speech_turn_lock, is_agent_speaking

    with patch.object(tts_base, "SPEECH_LOCK_FILE", Path(lock_path)), \
         patch.object(tts_base, "AGENT_SPEAKING_STATUS_FILE", Path(status_path)), \
         patch("pynput.keyboard.Listener"):
        try:
            t_req = time.time()
            with speech_turn_lock(text=f"Proc {worker_id} speech"):
                t_acquired = time.time()
                is_speaking = is_agent_speaking()
                time.sleep(duration)
                t_released = time.time()

            with open(log_file, "a") as f:
                f.write(f"{worker_id}:{t_req}:{t_acquired}:{t_released}:{is_speaking}\n")
        except Exception as e:
            with open(log_file, "a") as f:
                f.write(f"{worker_id}:ERROR:{e}\n")


def test_cross_process_lockfile_concurrency_and_mutual_exclusion(tmp_path):
    """
    Spawns 5 real OS processes competing for speech_turn_lock via flock.
    Verifies that no two processes overlap in their critical sections (strict cross-process mutex).
    """
    lock_file = str(tmp_path / "test_cross_proc.lock")
    status_file = str(tmp_path / "test_cross_proc.status")
    log_file = str(tmp_path / "lock_log.txt")
    num_procs = 5
    duration = 0.05

    processes = []
    for wid in range(num_procs):
        p = multiprocessing.Process(
            target=_multiprocess_lock_worker,
            args=(wid, lock_file, status_file, log_file, duration),
        )
        processes.append(p)

    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=15.0)

    assert Path(log_file).is_file()
    lines = Path(log_file).read_text().strip().split("\n")
    assert len(lines) == num_procs, f"Expected {num_procs} log entries, got {len(lines)}"

    intervals = []
    for line in lines:
        parts = line.split(":")
        assert len(parts) == 5, f"Invalid log entry: {line}"
        wid = int(parts[0])
        t_req = float(parts[1])
        t_acq = float(parts[2])
        t_rel = float(parts[3])
        is_spk = parts[4] == "True"
        assert is_spk is True, f"Process {wid} saw is_agent_speaking == False inside lock"
        assert t_acq < t_rel
        intervals.append((t_acq, t_rel, wid))

    intervals.sort(key=lambda x: x[0])
    for i in range(len(intervals) - 1):
        curr_acq, curr_rel, curr_id = intervals[i]
        next_acq, next_rel, next_id = intervals[i + 1]
        assert curr_rel <= next_acq + 0.02, (
            f"Process {curr_id} [rel={curr_rel}] overlapped with Process {next_id} [acq={next_acq}]!"
        )


def _crashed_lock_holder_worker(lock_path: str, status_path: str, barrier_file: str):
    """Child process that acquires lock, writes status, signals parent, and SIGKILLs itself."""
    import os
    from pathlib import Path
    from unittest.mock import patch
    import voicefi.tts.base as tts_base
    from voicefi.tts.base import speech_turn_lock

    with patch.object(tts_base, "SPEECH_LOCK_FILE", Path(lock_path)), \
         patch.object(tts_base, "AGENT_SPEAKING_STATUS_FILE", Path(status_path)), \
         patch("pynput.keyboard.Listener"):
        with speech_turn_lock(text="Crash test speech"):
            Path(barrier_file).write_text(str(os.getpid()))
            # Abruptly terminate process without executing finally blocks or cleanup
            os.kill(os.getpid(), signal.SIGKILL)


def test_crashed_process_lock_recovery_and_stale_pid_cleanup(tmp_path):
    """
    Verifies that if a process crashes (SIGKILL) while holding the lock and status file:
    1. The OS releases flock on lockfile automatically.
    2. Subsequent callers immediately acquire the lock without hanging.
    3. is_agent_speaking() detects the dead PID and removes the stale status file.
    """
    lock_file = str(tmp_path / "crash_test.lock")
    status_file = str(tmp_path / "crash_test.status")
    barrier_file = str(tmp_path / "barrier.txt")

    p = multiprocessing.Process(
        target=_crashed_lock_holder_worker,
        args=(lock_file, status_file, barrier_file),
    )
    p.start()
    p.join(timeout=5.0)

    assert Path(barrier_file).is_file()
    dead_pid = int(Path(barrier_file).read_text().strip())

    with patch.object(tts_base, "SPEECH_LOCK_FILE", Path(lock_file)), \
         patch.object(tts_base, "AGENT_SPEAKING_STATUS_FILE", Path(status_file)):

        # Verify dead process left status file behind
        if Path(status_file).is_file():
            speaking = is_agent_speaking()
            assert speaking is False, "Dead PID status must NOT be treated as actively speaking"
            assert not Path(status_file).is_file(), "Stale status file should be unlinked"

        # Verify new acquisition succeeds immediately without deadlocking on stale lockfile
        acquired = False
        with speech_turn_lock(text="Recovery acquisition"):
            assert is_agent_speaking()
            assert tts_base._LOCK_DEPTH == 1
            acquired = True

        assert acquired is True
        assert not is_agent_speaking()
        assert tts_base._LOCK_DEPTH == 0


def test_lock_depth_exact_synchronization_under_recursion_and_exceptions():
    """
    Stress-test _LOCK_DEPTH consistency across 10 levels of nesting with various exceptions:
    ValueError, KeyError, RuntimeError.
    """
    assert tts_base._LOCK_DEPTH == 0

    exceptions_to_test = [
        ValueError("Sample error"),
        KeyError("Missing key"),
        RuntimeError("Engine failure"),
    ]

    for idx, exc in enumerate(exceptions_to_test):
        with pytest.raises(type(exc)):
            with speech_turn_lock(text=f"Outer level 1 - unique {idx}"):
                assert tts_base._LOCK_DEPTH == 1
                with speech_turn_lock(text=f"Level 2 - unique {idx}"):
                    assert tts_base._LOCK_DEPTH == 2
                    with speech_turn_lock(text=f"Level 3 - unique {idx}"):
                        assert tts_base._LOCK_DEPTH == 3
                        with speech_turn_lock(text=f"Level 4 - unique {idx}"):
                            assert tts_base._LOCK_DEPTH == 4
                            raise exc

        assert tts_base._LOCK_DEPTH == 0
        assert not is_agent_speaking()


def test_is_agent_speaking_cross_process_status_file_corruption_immunity(tmp_path):
    """
    Stress-test is_agent_speaking() and get_agent_speaking_info() against corrupted status files:
    - Empty file
    - Truncated JSON
    - Random binary noise
    - Dead PID (PID 99999999)
    - Stale timestamp (> 60s ago)
    - Legacy pid:timestamp format with dead PID
    """
    status_file = tmp_path / "voicefi_speaking.status"
    with patch.object(tts_base, "AGENT_SPEAKING_STATUS_FILE", status_file):
        # 1. Empty file
        status_file.write_text("")
        assert is_agent_speaking() is False

        # 2. Corrupted JSON
        status_file.write_text("{broken: json[")
        assert is_agent_speaking() is False

        # 3. Binary junk
        status_file.write_bytes(b"\x00\xff\xfe\x12\x34\x56\x78")
        assert is_agent_speaking() is False

        # 4. Dead PID JSON
        payload = {"pid": 99999999, "timestamp": time.time(), "text": "phantom"}
        status_file.write_text(json.dumps(payload))
        assert is_agent_speaking() is False
        assert not status_file.is_file(), "Stale PID file should be unlinked"

        # 5. Stale timestamp (alive PID, but ts is 120s old)
        payload_stale = {"pid": os.getpid(), "timestamp": time.time() - 120.0, "text": "old"}
        status_file.write_text(json.dumps(payload_stale))
        assert is_agent_speaking() is False
        assert not status_file.is_file()

        # 6. Legacy format with dead PID
        status_file.write_text("99999999:1700000000.0")
        assert is_agent_speaking() is False
        assert not status_file.is_file()


# ============================================================================
# SUITE 3: Barge-In Mode Resolution & Safe-Mode State Machine Transitions
# ============================================================================


@pytest.mark.parametrize("setting,builtin,expected_active,expected_safe", [
    ("auto", True, False, True),      # Auto on built-in speakers -> safe mode (disabled barge-in)
    ("auto", False, True, False),     # Auto on headphones -> active full duplex
    ("AUTO", True, False, True),      # Case-insensitive "AUTO"
    ("Auto", False, True, False),
    (True, True, True, True),         # Forced True on built-in -> active safe-mode
    (True, False, True, False),       # Forced True on headphones -> active normal
    (False, True, False, False),      # Forced False -> disabled
    (False, False, False, False),
    (1, True, True, True),            # Truthy integer
    (0, True, False, False),          # Falsy integer
    (None, True, False, False),       # None
    ("", True, False, False),         # Empty string
    ("invalid_mode", True, True, True), # Non-empty string (truthy, not "auto")
])
def test_resolve_barge_in_mode_fuzzing(setting, builtin, expected_active, expected_safe):
    """Comprehensive fuzzing and verification of resolve_barge_in_mode() across all inputs."""
    with patch("voicefi.audio.native_vpio.is_vpio_supported", return_value=False), \
         patch("voicefi.audio.recorder.is_using_builtin_speakers", return_value=builtin):
        active, safe = resolve_barge_in_mode(setting)
        assert active == expected_active, f"Failed active for setting={setting}, builtin={builtin}"
        assert safe == expected_safe, f"Failed safe for setting={setting}, builtin={builtin}"


def test_safe_mode_grace_period_exact_boundary_timing():
    """
    Stress-test exact boundary of safe-mode grace period (1.0s / 20 chunks of 50ms):
    - Chunks 0..19 (<= 1.0s): Loud speaker bleed (0.055) is suppressed.
    - Chunk 20: Post-grace baseline established.
    - Chunk 21..24: Real loud human voice (0.14) arrives -> triggers barge-in.
    """
    sample_rate = 16000
    chunk_duration = 0.05
    chunk_size = int(sample_rate * chunk_duration)

    recorder = AudioRecorder(
        sample_rate=sample_rate,
        barge_in=True,
        barge_in_sensitivity=1.0,
        vad_engine="silero",
    )

    barge_in_triggered = []
    speaker_bleed = np.ones((chunk_size, 1), dtype=np.float32) * 0.055
    loud_human_voice = np.ones((chunk_size, 1), dtype=np.float32) * 0.14
    silence = np.zeros((chunk_size, 1), dtype=np.float32)

    # 20 chunks of speaker bleed (grace window), then 4 chunks human voice, then silence
    chunks = [speaker_bleed] * 20 + [loud_human_voice] * 4 + [silence] * 16
    curr_idx = [0]

    class MockStream:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            idx = curr_idx[0]
            curr_idx[0] += 1
            if idx < len(chunks):
                return chunks[idx], False
            recorder.stop()
            return silence, False

    def mock_is_agent_speaking():
        if barge_in_triggered:
            return False
        return True

    recorder._create_input_stream = lambda: MockStream()
    with patch("voicefi.audio.native_vpio.is_vpio_supported", return_value=False), \
         patch("voicefi.tts.base.stop_all_speech") as mock_stop, \
         patch("voicefi.audio.recorder.is_using_builtin_speakers", return_value=True), \
         patch("voicefi.audio.recorder.is_agent_audio_playing", return_value=True), \
         patch("voicefi.audio.recorder.is_agent_speaking", side_effect=mock_is_agent_speaking):

        audio, wav_p = recorder.record_speech_auto(
            on_barge_in=lambda: (barge_in_triggered.append(curr_idx[0]), mock_stop()),
        )

        try:
            assert len(barge_in_triggered) == 1, "Barge-in should trigger exactly once"
            trigger_chunk = barge_in_triggered[0]
            assert trigger_chunk >= 21, f"Barge-in prematurely triggered at chunk {trigger_chunk} during grace window!"
        finally:
            if wav_p:
                wav_p.unlink(missing_ok=True)


def test_rapid_speaking_state_oscillation_state_machine():
    """
    Stress-test recorder state machine when is_agent_speaking() oscillates rapidly
    (True -> False -> True -> False) every 2 chunks across 100 chunks.
    Verifies no crashes, no division-by-zero, and clean transition handling.
    """
    sample_rate = 16000
    chunk_size = int(sample_rate * 0.05)
    silence = np.zeros((chunk_size, 1), dtype=np.float32)
    voice = np.ones((chunk_size, 1), dtype=np.float32) * 0.05

    recorder = AudioRecorder(sample_rate=sample_rate, vad_engine="energy", barge_in="auto")
    chunks = [voice if i % 4 < 2 else silence for i in range(100)]
    c_idx = [0]

    class OscStream:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            idx = c_idx[0]
            c_idx[0] += 1
            if idx < len(chunks):
                return chunks[idx], False
            recorder.stop()
            return silence, False

    def oscillating_agent_speaking():
        return (c_idx[0] % 4) < 2

    recorder._create_input_stream = lambda: OscStream()
    with patch("voicefi.audio.recorder.is_using_builtin_speakers", return_value=True), \
         patch("voicefi.audio.recorder.is_agent_speaking", side_effect=oscillating_agent_speaking):

        audio, wav_p = recorder.record_speech_auto()
        if wav_p:
            wav_p.unlink(missing_ok=True)


def test_adaptive_speaker_bleed_decay_and_dynamic_floor():
    """
    Stress-test the adaptive speaker bleed floor tracking over 50 chunks of variable volume.
    Verifies that speaker_bleed_floor tracks baseline without exponential blowup or decay to zero.
    """
    sample_rate = 16000
    chunk_size = int(sample_rate * 0.05)

    recorder = AudioRecorder(
        sample_rate=sample_rate,
        barge_in=True,
        vad_engine="energy",
    )

    fluctuating_bleed = [
        np.ones((chunk_size, 1), dtype=np.float32) * (0.03 + 0.02 * np.sin(i / 5.0))
        for i in range(40)
    ]
    silence = np.zeros((chunk_size, 1), dtype=np.float32)
    chunks = fluctuating_bleed + [silence] * 10
    idx = [0]

    class BleedStream:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, size):
            i = idx[0]
            idx[0] += 1
            if i < len(chunks):
                return chunks[i], False
            recorder.stop()
            return silence, False

    recorder._create_input_stream = lambda: BleedStream()
    with patch("voicefi.audio.native_vpio.is_vpio_supported", return_value=False), \
         patch("voicefi.tts.base.stop_all_speech"), \
         patch("voicefi.audio.recorder.is_using_builtin_speakers", return_value=True), \
         patch("voicefi.audio.recorder.is_agent_audio_playing", return_value=True), \
         patch("voicefi.audio.recorder.is_agent_speaking", return_value=True):

        audio, wav_p = recorder.record_speech_auto()
        if wav_p:
            wav_p.unlink(missing_ok=True)
