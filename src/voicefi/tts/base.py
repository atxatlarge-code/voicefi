import fcntl
import os
import re
import subprocess
import threading
import time
import json
import weakref
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Dict, Any

SPEECH_LOCK_FILE = Path(os.environ.get("VOICEFI_SPEECH_LOCK", "/tmp/voicefi_speech.lock"))
AGENT_SPEAKING_STATUS_FILE = Path(
    os.environ.get("VOICEFI_SPEAKING_STATUS", "/tmp/voicefi_speaking.status")
)
AUDIO_PLAYING_STATUS_FILE = Path(
    os.environ.get("VOICEFI_AUDIO_PLAYING_STATUS", "/tmp/voicefi_audio_playing.status")
)
HUD_STATE_STATUS_FILE = Path(
    os.environ.get("VOICEFI_HUD_STATE_STATUS", "/tmp/voicefi_hud_state.json")
)
RECENT_SPEECH_FILE = Path(
    os.environ.get("VOICEFI_RECENT_SPEECH", "/tmp/voicefi_recent_speech.json")
)
_THREAD_LOCK = threading.RLock()
_IN_PROCESS_SPEAKING = False
_IN_PROCESS_AUDIO_PLAYING = False
_ACTIVE_TTS_ENGINES: weakref.WeakSet = weakref.WeakSet()


class DuplicateSpeechSuppressed(Exception):
    """Raised when speech is suppressed because the exact text was recently spoken."""

    pass


def normalize_text_for_dedup(text: str) -> str:
    """Normalize text into lower-cased alphanumeric string for robust deduplication."""
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower()).strip()


def is_duplicate_speech(text: str, window_seconds: float = 60.0) -> bool:
    """
    Check if the exact text or near-identical text was spoken by any VoiceFi process
    within the last `window_seconds`.
    """
    if not text or not text.strip():
        return False
    norm = normalize_text_for_dedup(text)
    if not norm or len(norm) < 6:
        return False
    now = time.time()
    try:
        if RECENT_SPEECH_FILE.is_file():
            data = json.loads(RECENT_SPEECH_FILE.read_text())
            if isinstance(data, list):
                for item in data:
                    item_norm = item.get("norm", "")
                    ts = float(item.get("timestamp", 0))
                    if (now - ts) <= window_seconds:
                        if item_norm == norm:
                            return True
                        # Prefix match for long utterances (> 25 chars)
                        if len(norm) >= 25 and len(item_norm) >= 25:
                            if norm[:30] == item_norm[:30]:
                                return True
    except Exception:
        pass
    return False


def clear_recent_speech_history() -> None:
    """Clear recorded speech deduplication history."""
    try:
        RECENT_SPEECH_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def record_recent_speech(text: str) -> None:
    """Record speech text and timestamp into cross-process recent speech cache."""
    norm = normalize_text_for_dedup(text)
    if not norm:
        return
    now = time.time()
    try:
        entries = []
        if RECENT_SPEECH_FILE.is_file():
            try:
                entries = json.loads(RECENT_SPEECH_FILE.read_text())
                if not isinstance(entries, list):
                    entries = []
            except Exception:
                entries = []
        # Keep only entries within last 120s
        valid_entries = [e for e in entries if (now - float(e.get("timestamp", 0))) < 120.0]
        valid_entries.append({"norm": norm, "timestamp": now})
        if len(valid_entries) > 50:
            valid_entries = valid_entries[-50:]
        RECENT_SPEECH_FILE.write_text(json.dumps(valid_entries))
    except Exception:
        pass


def set_cross_process_hud_state(
    state: str,
    text: Optional[str] = None,
    agent_name: Optional[str] = None,
    persona_name: Optional[str] = None,
    user_name: Optional[str] = None,
    detail: Optional[str] = None,
    tool_action: Optional[str] = None,
    tag_text: Optional[str] = None,
    live_stream: bool = False,
    app_name: Optional[str] = None,
    conv_id: Optional[str] = None,
) -> None:
    """Set cross-process HUD lifecycle state for seamless multi-process dynamic island presentation."""
    try:
        if state == "idle":
            clear_cross_process_hud_state()
            return

        payload = {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "state": state,
            "text": text or "",
            "agent_name": agent_name or "Antigravity",
            "persona_name": persona_name or "",
            "user_name": user_name or "Jake",
            "detail": detail or "",
            "tool_action": tool_action or "",
            "tag_text": tag_text or "",
            "live_stream": live_stream,
            "app_name": app_name or "",
            "conv_id": conv_id or "",
        }
        HUD_STATE_STATUS_FILE.write_text(json.dumps(payload))
    except Exception:
        pass


def get_cross_process_hud_state() -> Optional[Dict[str, Any]]:
    """Retrieve active cross-process HUD state if a non-expired valid payload exists."""
    try:
        if HUD_STATE_STATUS_FILE.is_file():
            raw = HUD_STATE_STATUS_FILE.read_text().strip()
            if not raw:
                return None
            data = json.loads(raw)
            if isinstance(data, dict):
                pid = int(data.get("pid", 0))
                ts = float(data.get("timestamp", 0))
                if is_pid_alive(pid) and (time.time() - ts) < 60.0:
                    return data
                else:
                    HUD_STATE_STATUS_FILE.unlink(missing_ok=True)
                    return None
    except Exception:
        pass
    return None


def clear_cross_process_hud_state() -> None:
    """Clear active cross-process HUD state."""
    try:
        HUD_STATE_STATUS_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def set_agent_speaking(
    speaking: bool,
    text: Optional[str] = None,
    agent_name: Optional[str] = None,
    persona_name: Optional[str] = None,
    app_name: Optional[str] = None,
    conv_id: Optional[str] = None,
    workspace_path: Optional[str] = None,
) -> None:
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
            payload = {
                "pid": os.getpid(),
                "timestamp": time.time(),
                "text": text or "",
                "agent_name": agent_name or "VoiceFi",
                "persona_name": persona_name or "Viv",
                "app_name": app_name or "",
                "conv_id": conv_id or "",
                "workspace_path": workspace_path or "",
            }
            AGENT_SPEAKING_STATUS_FILE.write_text(json.dumps(payload))
            set_cross_process_hud_state(
                state="speaking",
                text=text or "",
                agent_name=agent_name or "VoiceFi",
                persona_name=persona_name or "Viv",
                app_name=app_name or "",
                conv_id=conv_id or "",
            )
        else:
            AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
            set_agent_audio_playing(False)
            clear_cross_process_hud_state()
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


def get_agent_speaking_info() -> Optional[Dict[str, Any]]:
    """
    Retrieve active cross-process speaking status payload if any agent is currently speaking.
    Handles JSON and legacy pid:timestamp formats.
    """
    global _IN_PROCESS_SPEAKING
    try:
        if AGENT_SPEAKING_STATUS_FILE.is_file():
            raw = AGENT_SPEAKING_STATUS_FILE.read_text().strip()
            if not raw:
                return None
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    pid = int(data.get("pid", 0))
                    ts = float(data.get("timestamp", 0))
                    if is_pid_alive(pid) and (time.time() - ts) < 45.0:
                        return data
                    else:
                        AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
                        return None
            except json.JSONDecodeError:
                parts = raw.split(":")
                if len(parts) == 2:
                    pid = int(parts[0])
                    ts = float(parts[1])
                    if is_pid_alive(pid) and (time.time() - ts) < 30.0:
                        return {
                            "pid": pid,
                            "timestamp": ts,
                            "text": "",
                            "agent_name": "VoiceFi",
                            "persona_name": "Viv",
                        }
                    else:
                        AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
                else:
                    ts = float(parts[0])
                    if (time.time() - ts) < 20.0:
                        return {
                            "pid": os.getpid(),
                            "timestamp": ts,
                            "text": "",
                            "agent_name": "VoiceFi",
                            "persona_name": "Viv",
                        }
                    else:
                        AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    if _IN_PROCESS_SPEAKING:
        return {
            "pid": os.getpid(),
            "timestamp": time.time(),
            "text": "",
            "agent_name": "VoiceFi",
            "persona_name": "Viv",
        }

    return None


def is_agent_speaking() -> bool:
    """
    Check if any AI agent or subagent is currently speaking aloud via TTS.
    Checks in-process state and verified active cross-process speaking status markers.
    """
    global _IN_PROCESS_SPEAKING
    if _IN_PROCESS_SPEAKING:
        return True
    return get_agent_speaking_info() is not None


_LAST_SYSTEM_AUDIO_CHECK = 0.0
_LAST_SYSTEM_AUDIO_STATE = False


def is_system_audio_playing() -> bool:
    """Check if any macOS speech playback process (afplay/say) or streaming audio output is currently producing audio."""
    global _LAST_SYSTEM_AUDIO_CHECK, _LAST_SYSTEM_AUDIO_STATE

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False

    try:
        from voicefi.audio.output_lock import is_audio_output_locked

        if is_audio_output_locked():
            return True
    except Exception:
        pass

    now = time.time()
    if (now - _LAST_SYSTEM_AUDIO_CHECK) < 0.75:
        return _LAST_SYSTEM_AUDIO_STATE

    _LAST_SYSTEM_AUDIO_CHECK = now
    try:
        res_af = subprocess.run(
            ["pgrep", "-x", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if res_af.returncode == 0:
            _LAST_SYSTEM_AUDIO_STATE = True
            return True
        res_say = subprocess.run(
            ["pgrep", "-x", "say"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        _LAST_SYSTEM_AUDIO_STATE = res_say.returncode == 0
        return _LAST_SYSTEM_AUDIO_STATE
    except Exception:
        _LAST_SYSTEM_AUDIO_STATE = False
        return False


def is_escape_key(key: Any) -> bool:
    """
    Universally check if a key event from pynput or Cocoa corresponds to the Escape key.
    Handles Key.esc, KeyCode(char='\\x1b'), KeyCode(vk=53), name='esc', raw ASCII, and string representations.
    """
    if key is None:
        return False

    # Fast path: macOS virtual key code 53 is Escape
    vk = getattr(key, "vk", None)
    if vk == 53:
        return True

    try:
        from pynput.keyboard import Key

        if key == Key.esc:
            return True
    except Exception:
        pass

    try:
        name = getattr(key, "name", None)
        if name in ("esc", "escape"):
            return True
        char = getattr(key, "char", None)
        if char in ("\x1b", "\033"):
            return True
        val = getattr(key, "value", None)
        if val in (53, "esc", "escape"):
            return True
        s = str(key)
        if s in ("Key.esc", "'\\x1b'", "'\\033'", "<53>", "53"):
            return True
    except Exception:
        pass
    return False


def is_tab_key(key: Any) -> bool:
    """
    Universally check if a key event from pynput or Cocoa corresponds to the Tab key.
    Handles Key.tab, KeyCode(char='\\t'), KeyCode(vk=48), name='tab', raw ASCII, and string representations.
    """
    if key is None:
        return False

    # Fast path: macOS virtual key code 48 is Tab
    vk = getattr(key, "vk", None)
    if vk == 48:
        return True

    try:
        from pynput.keyboard import Key

        if key == Key.tab:
            return True
    except Exception:
        pass

    try:
        name = getattr(key, "name", None)
        if name in ("tab",):
            return True
        char = getattr(key, "char", None)
        if char in ("\t",):
            return True
        val = getattr(key, "value", None)
        if val in (48, "tab"):
            return True
        s = str(key)
        if s in ("Key.tab", "'\\t'", "<48>", "48", "tab"):
            return True
    except Exception:
        pass
    return False


def focus_speaking_window(
    agent_name: Optional[str] = None,
    app_name: Optional[str] = None,
    conv_id: Optional[str] = None,
) -> bool:
    """
    Focus the active application window for the speaking agent or origin.
    Invoked when pressing Tab while speech is active.
    """
    try:
        from voicefi.integrations.injector import focus_speaking_agent_window

        return focus_speaking_agent_window(
            agent_name=agent_name, app_name=app_name, conv_id=conv_id
        )
    except Exception as e:
        print(f"[TTS] Notice focusing speaking window: {e}")
        return False


def is_speech_interrupted(turn_start_time: float = 0.0) -> bool:
    """
    Check if speech playback has been interrupted, stopped, or cancelled across any thread or process.
    """
    global _IN_PROCESS_SPEAKING
    stop_time = get_last_speech_stop_time()

    # If turn_start_time is provided: ONLY consider stops that occurred strictly AFTER this turn started!
    if turn_start_time > 0:
        return stop_time > turn_start_time

    # If no turn_start_time provided, check if recent stop occurred within last 1.5s
    now = time.time()
    if stop_time > 0 and (now - stop_time) < 1.5:
        return True

    return False




_LOCK_DEPTH = 0


@contextmanager
def escape_to_stop_speech(
    agent_name: Optional[str] = None,
    app_name: Optional[str] = None,
    conv_id: Optional[str] = None,
):
    """
    Spawns a lightweight global keyboard listener while speech is active.
    - Escape (Key.esc, vk=53, or char=\\x1b): immediately triggers stop_all_speech().
    - Tab (Key.tab, vk=48, or char=\\t): focuses the window/application of the speaking agent.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        yield
        return

    listener = None
    last_tab_time = [0.0]
    try:
        from pynput import keyboard

        def _on_press(key):
            try:
                if is_escape_key(key):
                    stop_all_speech()
                    try:
                        from voicefi.telemetry import capture_barge_in_event

                        capture_barge_in_event(device_type="keyboard_esc", is_full_duplex=False)
                    except Exception:
                        pass
                elif is_tab_key(key):
                    now = time.time()
                    if (now - last_tab_time[0]) >= 0.35:
                        last_tab_time[0] = now
                        focus_speaking_window(
                            agent_name=agent_name,
                            app_name=app_name,
                            conv_id=conv_id,
                        )
            except Exception:
                pass

        listener = keyboard.Listener(on_press=_on_press)
        listener.daemon = True
        listener.start()
    except Exception:
        pass

    try:
        yield
    finally:
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass


@contextmanager
def speech_turn_lock(
    text: Optional[str] = None,
    agent_name: Optional[str] = None,
    persona_name: Optional[str] = None,
    app_name: Optional[str] = None,
    conv_id: Optional[str] = None,
    workspace_path: Optional[str] = None,
):
    """
    Cross-process and cross-thread lock.
    Ensures that separate processes (IDE hooks, background subagents, CLI scripts)
    wait politely for the active speaker to finish instead of talking over each other.
    Supports re-entrant execution within the same thread/process.
    """
    global _LOCK_DEPTH
    from voicefi.audio.output_lock import exclusive_audio

    with _THREAD_LOCK:
        if _LOCK_DEPTH > 0:
            _LOCK_DEPTH += 1
            try:
                with escape_to_stop_speech(
                    agent_name=agent_name, app_name=app_name, conv_id=conv_id
                ):
                    yield
            finally:
                _LOCK_DEPTH -= 1
            return

        _LOCK_DEPTH += 1
        SPEECH_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = None
        try:
            lock_fd = open(SPEECH_LOCK_FILE, "a+")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            # Check if this exact speech was already delivered by another process while waiting for lock
            if text and is_duplicate_speech(text, window_seconds=6.0):
                print(
                    f'[TTS] 🛡️ Suppressed duplicate speech: "{text[:40]}..." (already spoken within 6.0s)'
                )
                raise DuplicateSpeechSuppressed(f"Duplicate speech: {text[:30]}")

            if text:
                record_recent_speech(text)

            speak_kwargs = {
                "text": text,
                "agent_name": agent_name,
                "persona_name": persona_name,
            }
            if app_name is not None:
                speak_kwargs["app_name"] = app_name
            if conv_id is not None:
                speak_kwargs["conv_id"] = conv_id
            if workspace_path is not None:
                speak_kwargs["workspace_path"] = workspace_path

            set_agent_speaking(True, **speak_kwargs)

            # If any previous audio is still playing out of speakers, wait until total silence
            max_wait = 150  # up to 15s
            while is_system_audio_playing() and max_wait > 0:
                time.sleep(0.1)
                max_wait -= 1

            lock_start_time = time.time()
            # Acquire physical audio output mutex across all OS processes
            owner_label = f"{agent_name or 'agent'}:{persona_name or 'tts'}"
            with exclusive_audio(timeout=30.0, owner=owner_label):
                # Brief pause for natural conversational handoff between agents
                if not os.environ.get("PYTEST_CURRENT_TEST"):
                    time.sleep(0.15)
                with escape_to_stop_speech(
                    agent_name=agent_name, app_name=app_name, conv_id=conv_id
                ):
                    yield
        finally:
            # If speech completed cleanly without interruption, record successful turn in BrevityLearner
            try:
                if text and 'lock_start_time' in locals() and not is_speech_interrupted(lock_start_time):
                    from voicefi.learning.brevity import BrevityLearner

                    word_cnt = len(text.split())
                    BrevityLearner.get_instance().record_turn(word_count=word_cnt, was_interrupted=False)
            except Exception:
                pass

            # Acoustic decay margin: allow room reverb / speaker decay to dissipate
            if not os.environ.get("PYTEST_CURRENT_TEST"):
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

    def __init__(self, *args, **kwargs):
        _ACTIVE_TTS_ENGINES.add(self)

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

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """
        Synthesize speech directly to an audio file without playing through speakers.
        Must be implemented by subclasses for silent testing and file synthesis.
        """
        return False

    async def synthesize_to_file(self, text: str, output_path: Path) -> bool:
        """
        Asynchronously synthesize speech directly to an audio file without playing.
        """


_LAST_SPEECH_STOP_FILE = Path("/tmp/voicefi_last_speech_stop.ts")


def record_speech_stopped() -> None:
    """Record timestamp when speech was interrupted/stopped."""
    try:
        _LAST_SPEECH_STOP_FILE.write_text(str(time.time()))
    except Exception:
        pass


def get_last_speech_stop_time() -> float:
    """Retrieve timestamp of the most recent speech stop event."""
    try:
        if _LAST_SPEECH_STOP_FILE.is_file():
            return float(_LAST_SPEECH_STOP_FILE.read_text().strip())
    except Exception:
        pass
    return 0.0


_STOPPING_ALL_SPEECH = False


def stop_all_speech(broadcast_web: bool = True) -> None:
    """
    Instantly stop any active speech synthesis and audio playback on macOS.
    Kills any running 'say' or 'afplay' processes, stops all registered TTS engines, and releases audio lock.
    """
    global _STOPPING_ALL_SPEECH
    if _STOPPING_ALL_SPEECH:
        return

    _STOPPING_ALL_SPEECH = True
    try:
        record_speech_stopped()
        set_agent_speaking(False)
        set_agent_audio_playing(False)
        try:
            from voicefi.audio.output_lock import force_release_audio_lock

            force_release_audio_lock()
        except Exception:
            pass
        try:
            AGENT_SPEAKING_STATUS_FILE.unlink(missing_ok=True)
            AUDIO_PLAYING_STATUS_FILE.unlink(missing_ok=True)
            HUD_STATE_STATUS_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        # Record interruption to BrevityLearner for recursive cognitive brevity adaptation
        try:
            from voicefi.learning.brevity import BrevityLearner

            BrevityLearner.get_instance().record_turn(word_count=0, was_interrupted=True)
        except Exception:
            pass

        for engine in list(_ACTIVE_TTS_ENGINES):
            try:
                engine.stop()
            except Exception:
                pass

        if not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                subprocess.run(
                    ["killall", "-9", "say"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

            try:
                subprocess.run(
                    ["killall", "-9", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
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
                UnifiedDynamicIslandHUD._instance.hide_speech()
        except Exception:
            pass

        # Notify companion server non-blockingly to broadcast stop to all connected web clients
        if broadcast_web and not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                import urllib.request

                req = urllib.request.Request(
                    "http://127.0.0.1:5141/api/stop", method="POST", data=b"{}"
                )
                req.add_header("Content-Type", "application/json")
                urllib.request.urlopen(req, timeout=0.08)
            except Exception:
                pass
    finally:
        _STOPPING_ALL_SPEECH = False
