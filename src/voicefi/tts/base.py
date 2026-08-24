import fcntl
import os
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

SPEECH_LOCK_FILE = Path("/tmp/voicefi_speech.lock")
AGENT_SPEAKING_STATUS_FILE = Path("/tmp/voicefi_speaking.status")
AUDIO_PLAYING_STATUS_FILE = Path("/tmp/voicefi_audio_playing.status")
_THREAD_LOCK = threading.Lock()
_IN_PROCESS_SPEAKING = False
_IN_PROCESS_AUDIO_PLAYING = False


def set_agent_speaking(speaking: bool, text: Optional[str] = None) -> None:
    """Set in-process and cross-process indicator that an AI agent is speaking aloud."""
    global _IN_PROCESS_SPEAKING
    _IN_PROCESS_SPEAKING = speaking
    if text and speaking:
        try:
            from voicefi.audio.echo_canceller import record_agent_spoken
            record_agent_spoken(text)
        except Exception:
            pass
    try:
        if speaking:
            AGENT_SPEAKING_STATUS_FILE.write_text(f"{os.getpid()}:{time.time()}")
        else:
            AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
            set_agent_audio_playing(False)
    except Exception:
        pass


def set_agent_audio_playing(playing: bool) -> None:
    """Set indicator that physical sound is actively streaming out of the speakers."""
    global _IN_PROCESS_AUDIO_PLAYING
    _IN_PROCESS_AUDIO_PLAYING = playing
    try:
        if playing:
            AUDIO_PLAYING_STATUS_FILE.write_text(f"{os.getpid()}:{time.time()}")
        else:
            AUDIO_PLAYING_STATUS_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def is_agent_audio_playing() -> bool:
    """Check if audio playback is physically outputting sound right now."""
    global _IN_PROCESS_AUDIO_PLAYING
    if _IN_PROCESS_AUDIO_PLAYING:
        return True

    try:
        if AUDIO_PLAYING_STATUS_FILE.is_file():
            content = AUDIO_PLAYING_STATUS_FILE.read_text().strip()
            if content:
                parts = content.split(":")
                if len(parts) == 2:
                    pid = int(parts[0])
                    ts = float(parts[1])
                    if is_pid_alive(pid) and (time.time() - ts) < 25.0:
                        return True
                    else:
                        AUDIO_PLAYING_STATUS_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    return is_system_audio_playing()


def is_pid_alive(pid: int) -> bool:
    """Check if process with given PID is currently active."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_agent_speaking() -> bool:
    """
    Check if any AI agent or subagent is currently speaking aloud via TTS.
    Checks in-process state and verified active cross-process speaking status markers.
    """
    global _IN_PROCESS_SPEAKING
    if _IN_PROCESS_SPEAKING:
        return True

    try:
        if AGENT_SPEAKING_STATUS_FILE.is_file():
            content = AGENT_SPEAKING_STATUS_FILE.read_text().strip()
            if content:
                parts = content.split(":")
                if len(parts) == 2:
                    pid = int(parts[0])
                    ts = float(parts[1])
                    if is_pid_alive(pid) and (time.time() - ts) < 25.0:
                        return True
                    else:
                        AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
                else:
                    ts = float(parts[0])
                    if (time.time() - ts) < 20.0:
                        return True
                    else:
                        AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    return False


def is_system_audio_playing() -> bool:
    """Check if any macOS speech playback process (afplay or say) is currently producing audio."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False

    try:
        res_af = subprocess.run(["pgrep", "-x", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res_af.returncode == 0:
            return True
        res_say = subprocess.run(["pgrep", "-x", "say"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res_say.returncode == 0
    except Exception:
        return False


_LOCK_DEPTH = 0


@contextmanager
def speech_turn_lock():
    """
    Cross-process and cross-thread lock.
    Ensures that separate processes (IDE hooks, background subagents, CLI scripts)
    wait politely for the active speaker to finish instead of talking over each other.
    Supports re-entrant execution within the same thread/process.
    """
    global _LOCK_DEPTH
    with _THREAD_LOCK:
        if _LOCK_DEPTH > 0:
            _LOCK_DEPTH += 1
            try:
                yield
            finally:
                _LOCK_DEPTH -= 1
            return

        _LOCK_DEPTH += 1
        SPEECH_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = None
        esc_listener = None
        try:
            # Active Esc key listener to cancel speech playback on Escape press
            try:
                from pynput import keyboard
                def _on_key(key):
                    vk = getattr(key, 'vk', None)
                    if key == keyboard.Key.esc or vk == 53:
                        stop_all_speech()
                esc_listener = keyboard.Listener(on_press=_on_key)
                esc_listener.daemon = True
                esc_listener.start()
            except Exception:
                esc_listener = None

            lock_fd = open(SPEECH_LOCK_FILE, "a+")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            set_agent_speaking(True)
            
            # If any previous audio is still playing out of speakers, wait until total silence
            max_wait = 150  # up to 15s
            while is_system_audio_playing() and max_wait > 0:
                time.sleep(0.1)
                max_wait -= 1

            # Brief pause for natural conversational handoff between agents
            time.sleep(0.15)
            yield
        finally:
            if esc_listener is not None:
                try:
                    esc_listener.stop()
                except Exception:
                    pass
            # Acoustic decay margin: allow room reverb / speaker decay to dissipate
            time.sleep(0.25)
            set_agent_speaking(False)
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    lock_fd.close()
                except Exception:
                    pass
            _LOCK_DEPTH -= 1



# Legacy alias
SPEECH_LOCK = _THREAD_LOCK


class BaseTTS(ABC):
    """Abstract interface for all TTS engines."""

    @abstractmethod
    def speak(self, text: str, block: bool = True) -> None:
        """
        Synthesize and speak the provided text aloud.
        
        Args:
            text: Text to speak.
            block: Whether to wait for audio playback to complete before returning.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Interrupt any ongoing speech playback."""
        pass

    def stream_speak(self, text: str, block: bool = True) -> None:
        """
        Stream and speak audio with minimal time-to-first-byte latency.
        Defaults to standard speak if streaming not implemented by subclass.
        """
        self.speak(text, block=block)


def stop_all_speech() -> None:
    """
    Instantly stop any active speech synthesis and audio playback on macOS.
    Kills any running 'say' or 'afplay' processes and dismisses HUDs.
    """
    set_agent_speaking(False)
    set_agent_audio_playing(False)
    try:
        AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
        AUDIO_PLAYING_STATUS_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        subprocess.run(["killall", "say"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    try:
        subprocess.run(["killall", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    try:
        from voicefi.ui.speech_hud import AgentSpeechHUD
        if AgentSpeechHUD._instance:
            AgentSpeechHUD._instance.hide()
    except Exception:
        pass

    try:
        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
        if UnifiedDynamicIslandHUD._instance:
            UnifiedDynamicIslandHUD._instance.hide()
    except Exception:
        pass
