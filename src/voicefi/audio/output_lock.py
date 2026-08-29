"""
Cross-process mutual exclusion mutex for physical audio output devices.
Guarantees that independent OS processes (Antigravity hooks, Claude Code hooks,
subagents, CLI scripts) never play audio simultaneously over CoreAudio.
"""

import fcntl
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

AUDIO_LOCK_FILE = Path(os.environ.get("VOICEFI_AUDIO_LOCK", "/tmp/voicefi_audio_output.lock"))
_IN_PROCESS_LOCK = threading.RLock()
_LOCK_DEPTH = 0
_CURRENT_LOCK_FD: Optional[int] = None
_CURRENT_LOCK_FILE_OBJ = None


@contextmanager
def exclusive_audio(timeout: float = 30.0, owner: str = ""):
    """
    Acquire cross-process mutual exclusion lock on physical audio output.
    Blocks until previous speaker finishes or timeout expires.
    Guarantees in-process locks are not held during playback so barge-in/Escape can interrupt instantly.
    """
    global _LOCK_DEPTH, _CURRENT_LOCK_FD, _CURRENT_LOCK_FILE_OBJ

    pid = os.getpid()
    owner_str = owner or f"pid_{pid}"

    with _IN_PROCESS_LOCK:
        if _LOCK_DEPTH > 0:
            _LOCK_DEPTH += 1
            is_nested = True
        else:
            _LOCK_DEPTH += 1
            is_nested = False

    if is_nested:
        try:
            yield
        finally:
            with _IN_PROCESS_LOCK:
                _LOCK_DEPTH -= 1
        return

    AUDIO_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = None
    lock_file_obj = None
    start_time = time.time()
    acquired = False

    try:
        lock_file_obj = open(AUDIO_LOCK_FILE, "a+")
        lock_fd = lock_file_obj.fileno()
        with _IN_PROCESS_LOCK:
            _CURRENT_LOCK_FD = lock_fd
            _CURRENT_LOCK_FILE_OBJ = lock_file_obj

        # Non-blocking poll loop with timeout to avoid hard deadlock
        while time.time() - start_time < timeout:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, IOError):
                time.sleep(0.05)

        if not acquired:
            print(
                f"[AudioLock] ⚠️ Timeout ({timeout:.1f}s) waiting for audio output mutex (owner={owner_str}). Proceeding.",
                file=sys.stderr,
            )

        # Record diagnostics
        try:
            lock_file_obj.seek(0)
            lock_file_obj.truncate()
            lock_file_obj.write(f"owner={owner_str} pid={pid} acquired_at={time.time()}\n")
            lock_file_obj.flush()
        except Exception:
            pass

        yield
    finally:
        with _IN_PROCESS_LOCK:
            if _CURRENT_LOCK_FD == lock_fd:
                _CURRENT_LOCK_FD = None
            if _CURRENT_LOCK_FILE_OBJ == lock_file_obj:
                _CURRENT_LOCK_FILE_OBJ = None
            _LOCK_DEPTH -= 1

        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                lock_file_obj.close()
            except Exception:
                pass


def is_audio_output_locked() -> bool:
    """
    Check if another process currently holds the audio output lock.
    Returns True if locked by someone else, False if free.
    """
    with _IN_PROCESS_LOCK:
        if _LOCK_DEPTH > 0:
            return True

    if not AUDIO_LOCK_FILE.exists():
        return False

    try:
        with open(AUDIO_LOCK_FILE, "a+") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                return False
            except (BlockingIOError, IOError):
                return True
    except Exception:
        return False


def force_release_audio_lock():
    """Emergency force release of the audio mutex (used during barge-in/stop)."""
    global _LOCK_DEPTH, _CURRENT_LOCK_FD, _CURRENT_LOCK_FILE_OBJ
    with _IN_PROCESS_LOCK:
        if _CURRENT_LOCK_FD is not None:
            try:
                fcntl.flock(_CURRENT_LOCK_FD, fcntl.LOCK_UN)
            except Exception:
                pass
            _CURRENT_LOCK_FD = None
        if _CURRENT_LOCK_FILE_OBJ is not None:
            try:
                _CURRENT_LOCK_FILE_OBJ.close()
            except Exception:
                pass
            _CURRENT_LOCK_FILE_OBJ = None
        _LOCK_DEPTH = 0
