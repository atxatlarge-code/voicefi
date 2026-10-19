"""
Audio hardware device detection and acoustic profiling.
Identifies built-in MacBook speakers vs. headphones/AirPods to prevent acoustic feedback loops.
"""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List, Callable, Set

_LIVE_ROUTE_CACHE: Dict[str, Any] = {
    "ts": 0.0,
    "in_name": None,
    "out_name": None,
}
_LIVE_ROUTE_LOCK = threading.Lock()

# Process-wide mutex serializing PortAudio InputStream lifecycle (Pa_OpenStream / Pa_StopStream / Pa_CloseStream)
# to prevent macOS CoreAudio AUHAL recursive_mutex vs HALB_Mutex AB-BA deadlocks across threads.
PORTAUDIO_STREAM_LOCK = threading.Lock()


def _query_live_macos_route(ttl_s: float = 1.0) -> Tuple[Optional[str], Optional[str]]:
    """Query live macOS input/output device names via SwitchAudioSource with a short TTL cache."""
    now = time.monotonic()
    with _LIVE_ROUTE_LOCK:
        if (now - _LIVE_ROUTE_CACHE["ts"]) < ttl_s and (
            _LIVE_ROUTE_CACHE["in_name"] or _LIVE_ROUTE_CACHE["out_name"]
        ):
            return _LIVE_ROUTE_CACHE["in_name"], _LIVE_ROUTE_CACHE["out_name"]

    sw = None
    for cand in (
        "SwitchAudioSource",
        "/opt/homebrew/bin/SwitchAudioSource",
        "/usr/local/bin/SwitchAudioSource",
    ):
        if shutil.which(cand) or os.path.exists(cand):
            sw = cand
            break

    if not sw:
        return None, None

    in_name: Optional[str] = None
    out_name: Optional[str] = None
    try:
        r_out = subprocess.run(
            [sw, "-c", "-t", "output"], capture_output=True, text=True, timeout=1.0
        )
        if r_out.returncode == 0 and r_out.stdout.strip():
            out_name = r_out.stdout.strip()
        r_in = subprocess.run(
            [sw, "-c", "-t", "input"], capture_output=True, text=True, timeout=1.0
        )
        if r_in.returncode == 0 and r_in.stdout.strip():
            in_name = r_in.stdout.strip()
    except Exception:
        pass

    with _LIVE_ROUTE_LOCK:
        _LIVE_ROUTE_CACHE["ts"] = now
        if in_name:
            _LIVE_ROUTE_CACHE["in_name"] = in_name
        if out_name:
            _LIVE_ROUTE_CACHE["out_name"] = out_name
    return in_name, out_name


def get_default_audio_devices() -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Retrieve default (input_device, output_device) metadata.
    Overlays live macOS CoreAudio route (via SwitchAudioSource) onto sounddevice
    so hot-swapping between Headphones/AirPods and MacBook Speakers is detected immediately.
    """
    is_mock_or_test = (
        os.getenv("VOICEFI_MOCK_AUDIO") == "1"
        or os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("VOICEFI_TESTING") == "1"
        or bool(os.getenv("PYTEST_CURRENT_TEST"))
    )
    in_dev: Optional[Dict[str, Any]] = None
    out_dev: Optional[Dict[str, Any]] = None

    try:
        import sounddevice as sd

        devices = sd.query_devices()
        in_idx, out_idx = sd.default.device

        in_dev = (
            dict(devices[in_idx])
            if (in_idx is not None and 0 <= in_idx < len(devices))
            else None
        )
        out_dev = (
            dict(devices[out_idx])
            if (out_idx is not None and 0 <= out_idx < len(devices))
            else None
        )
    except Exception:
        pass

    if not is_mock_or_test:
        live_in, live_out = _query_live_macos_route(ttl_s=1.0)
        if live_in:
            if in_dev is None:
                in_dev = {"name": live_in, "max_input_channels": 1, "max_output_channels": 0}
            else:
                in_dev["name"] = live_in
        if live_out:
            if out_dev is None:
                out_dev = {"name": live_out, "max_input_channels": 0, "max_output_channels": 2}
            else:
                out_dev["name"] = live_out

    if (in_dev is None and out_dev is None) and is_mock_or_test:
        return (
            {"name": "Built-in Mic", "max_input_channels": 1, "max_output_channels": 0},
            {"name": "Built-in Output", "max_input_channels": 0, "max_output_channels": 2},
        )
    return in_dev, out_dev


def is_using_builtin_speakers() -> bool:
    """
    Check if the active audio output device is the Mac's built-in laptop speakers.
    When true, acoustic coupling into the built-in mic is high, requiring safe barge-in gating.
    """
    try:
        _, out_dev = get_default_audio_devices()
        if not out_dev:
            return False

        out_name = str(out_dev.get("name", "")).lower()

        # Check for headphone/external overrides first
        headphone_markers = (
            "headphone",
            "headset",
            "airpod",
            "buds",
            "ear",
            "bluetooth",
            "wireless",
            "external",
            "dongle",
            "dac",
        )
        if any(marker in out_name for marker in headphone_markers):
            return False

        # Check for built-in laptop speaker markers
        speaker_markers = ("speaker", "built-in output", "internal", "macbook", "imac", "mac mini")
        return any(marker in out_name for marker in speaker_markers)
    except Exception:
        return False


def is_headphone_or_headset_active() -> bool:
    """
    Check if headphones, AirPods, or an external headset are active.
    When true, there is zero acoustic bleed from speakers into mic, so active barge-in is 100% safe.
    """
    try:
        _, out_dev = get_default_audio_devices()
        if not out_dev:
            return False

        out_name = str(out_dev.get("name", "")).lower()
        headphone_markers = (
            "headphone",
            "headset",
            "airpod",
            "buds",
            "ear",
            "bluetooth",
            "wireless",
            "in-ear",
            "iem",
        )
        if any(marker in out_name for marker in headphone_markers):
            return True

        # Check for external speaker/monitor markers that are definitely NOT headphones
        external_speaker_markers = (
            "display",
            "monitor",
            "tv",
            "hdmi",
            "soundbar",
            "speaker",
            "studio display",
        )
        if any(marker in out_name for marker in external_speaker_markers):
            return False

        # If it's built-in laptop speakers, definitely not headphones
        if is_using_builtin_speakers():
            return False

        # Do not assume unknown external devices/monitors/DACs are headphones
        return False
    except Exception:
        return False


def is_bluetooth_input_active() -> bool:
    """
    Check if the current default audio input device is a Bluetooth headset or earbuds.
    When true, macOS CoreAudio switches the Bluetooth profile from high-fidelity A2DP stereo
    to low-fidelity SCO/HFP mono to service the microphone channel.
    """
    try:
        in_dev, _ = get_default_audio_devices()
        if not in_dev:
            return False

        in_name = str(in_dev.get("name", "")).lower()
        headphone_markers = (
            "headphone",
            "headset",
            "airpod",
            "buds",
            "ear",
            "bluetooth",
            "wireless",
            "in-ear",
            "iem",
        )
        return any(marker in in_name for marker in headphone_markers)
    except Exception:
        return False


def get_audio_device_profile() -> Dict[str, Any]:
    """Return a comprehensive hardware acoustic profile for diagnostics and telemetry."""
    in_dev, out_dev = get_default_audio_devices()
    builtin_spk = is_using_builtin_speakers()
    headphones = is_headphone_or_headset_active()
    bt_input = is_bluetooth_input_active()
    lock_recommended = headphones and bt_input
    try:
        from voicefi.audio.native_vpio import is_vpio_supported

        hardware_aec = is_vpio_supported()
    except Exception:
        hardware_aec = False

    return {
        "default_input": in_dev.get("name") if in_dev else "None",
        "default_output": out_dev.get("name") if out_dev else "None",
        "is_builtin_speakers": builtin_spk,
        "is_headphones_active": headphones,
        "is_bluetooth_input_active": bt_input,
        "audio_input_lock_recommended": lock_recommended,
        "audio_input_lock_tip": (
            "Keep input on MacBook Pro Microphone in System Settings → Sound → Input to lock earbuds in high-fidelity stereo."
            if lock_recommended
            else ""
        ),
        "hardware_aec_supported": hardware_aec,
        "hardware_aec_backend": "Apple AUVoiceProcessing (VoiceProcessingIO)"
        if hardware_aec
        else "None",
        "acoustic_safe_mode_recommended": builtin_spk and not headphones and not hardware_aec,
    }


def _find_audio_switcher_bin() -> Optional[str]:
    """Locate SwitchAudioSource binary on macOS."""
    candidates = [
        "SwitchAudioSource",
        "/opt/homebrew/bin/SwitchAudioSource",
        "/usr/local/bin/SwitchAudioSource",
    ]
    for cand in candidates:
        if shutil.which(cand) or os.path.exists(cand):
            return cand
    return None


def list_audio_input_devices() -> List[str]:
    """List all available audio input device names."""
    sw = _find_audio_switcher_bin()
    if sw:
        try:
            res = subprocess.run(
                [sw, "-a", "-t", "input"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        except Exception:
            pass

    # Fallback to sounddevice
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        names = []
        for d in devices:
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name")
                if name and name not in names:
                    names.append(name)
        return names
    except Exception:
        return []


def get_current_input_device_name() -> str:
    """Get the currently selected default audio input device name."""
    sw = _find_audio_switcher_bin()
    if sw:
        try:
            res = subprocess.run(
                [sw, "-c", "-t", "input"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
    in_dev, _ = get_default_audio_devices()
    return in_dev.get("name", "Unknown") if in_dev else "Unknown"


def set_audio_input_device(device_name: str) -> bool:
    """Set the system audio input device by name via SwitchAudioSource."""
    sw = _find_audio_switcher_bin()
    if not sw:
        return False
    try:
        res = subprocess.run(
            [sw, "-s", device_name, "-t", "input"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return res.returncode == 0
    except Exception:
        return False


def find_builtin_microphone_name() -> Optional[str]:
    """Find the Mac built-in microphone device name if available."""
    inputs = list_audio_input_devices()
    builtin_markers = ("macbook", "built-in microphone", "internal microphone", "built-in mic")
    for name in inputs:
        low = name.lower()
        if any(marker in low for marker in builtin_markers):
            return name
    return None


def find_headset_microphone_name() -> Optional[str]:
    """Find connected Bluetooth headset/earbuds microphone name if available."""
    inputs = list_audio_input_devices()
    headphone_markers = (
        "buds",
        "airpod",
        "headphone",
        "headset",
        "bluetooth",
        "wireless",
        "in-ear",
        "iem",
    )
    for name in inputs:
        low = name.lower()
        if any(marker in low for marker in headphone_markers):
            return name
    return None


def pin_mac_microphone() -> Tuple[bool, str]:
    """
    Lock/switch input to the Mac built-in microphone.
    Preserves connected Bluetooth earbuds in high-fidelity A2DP stereo.
    """
    mac_mic = find_builtin_microphone_name()
    if not mac_mic:
        return False, "Built-in Mac microphone not found in input devices."

    current = get_current_input_device_name()
    if current.lower() == mac_mic.lower():
        return True, f"Already pinned to {mac_mic}."

    ok = set_audio_input_device(mac_mic)
    if ok:
        return True, f"Locked input to {mac_mic} (earbuds preserved in high-fidelity stereo)."
    return False, f"Failed to switch input to {mac_mic}."


def set_headset_microphone() -> Tuple[bool, str]:
    """Switch input to connected Bluetooth earbuds/headset for roaming."""
    headset_mic = find_headset_microphone_name()
    if not headset_mic:
        return False, "No Bluetooth headset or earbuds microphone detected."

    current = get_current_input_device_name()
    if current.lower() == headset_mic.lower():
        return True, f"Already set to {headset_mic}."

    ok = set_audio_input_device(headset_mic)
    if ok:
        return True, f"Switched input to {headset_mic} for roaming (earbuds in headset mode)."
    return False, f"Failed to switch input to {headset_mic}."


def toggle_microphone_source() -> Tuple[bool, str]:
    """Toggle input between Mac built-in microphone and Bluetooth headset."""
    current = get_current_input_device_name()
    mac_mic = find_builtin_microphone_name()
    headset_mic = find_headset_microphone_name()

    if mac_mic and current.lower() == mac_mic.lower():
        if headset_mic:
            return set_headset_microphone()
        return False, "No headset microphone available to switch to."
    else:
        if mac_mic:
            return pin_mac_microphone()
        return False, "Built-in Mac microphone not found."


def auto_pin_mac_microphone(force: bool = False) -> Tuple[bool, str]:
    """
    Automatically pin to Mac microphone if headphones/earbuds are active and
    macOS has hijacked input to the earbuds.
    """
    if not force:
        headphones = is_headphone_or_headset_active()
        bt_input = is_bluetooth_input_active()
        if not (headphones and bt_input):
            return False, "Auto-pin not needed (earbuds are not capturing input)."
    return pin_mac_microphone()


class AudioRouteWatcher:
    """
    Background macOS Audio Route Watcher.
    Detects hot-swaps between Headphones/AirPods and Built-in Laptop Speakers,
    refreshes PortAudio when idle, auto-pins the Mac built-in microphone when
    Bluetooth headphones connect, and invokes callbacks to update Barge-In Auto mode.
    """

    def __init__(
        self,
        on_route_change: Optional[Callable[[str, str, bool, bool], None]] = None,
        interval_s: float = 1.2,
    ) -> None:
        self.on_route_change = on_route_change
        self.interval_s = max(0.5, float(interval_s))
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_output_name: str = ""
        self.last_input_name: str = ""

    def start(self) -> None:
        if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("VOICEFI_TESTING") == "1":
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop, daemon=True, name="AudioRouteWatcher"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _watch_loop(self) -> None:
        try:
            in_dev, out_dev = get_default_audio_devices()
            self.last_input_name = str(in_dev.get("name", "")) if in_dev else ""
            self.last_output_name = str(out_dev.get("name", "")) if out_dev else ""
        except Exception:
            pass

        while not self._stop_event.is_set():
            time.sleep(self.interval_s)
            if self._stop_event.is_set():
                break
            try:
                live_in, live_out = _query_live_macos_route(ttl_s=0.0)
                cur_out = live_out or self.last_output_name
                cur_in = live_in or self.last_input_name

                if cur_out and cur_out != self.last_output_name:
                    prev_out = self.last_output_name
                    self.last_output_name = cur_out
                    self.last_input_name = cur_in

                    builtin_spk = is_using_builtin_speakers()
                    headphones = is_headphone_or_headset_active()
                    mode_desc = (
                        "🎧 Headphones (Full-Duplex Barge-In ACTIVE)"
                        if headphones
                        else (
                            "🔇 Laptop Speakers (Acoustic Safe Mode • Barge-In Paused)"
                            if builtin_spk
                            else "🔊 External Audio"
                        )
                    )
                    print(
                        f"[AudioRouteWatcher] 🔄 Speaker route changed: '{prev_out or 'Init'}' -> '{cur_out}' ({mode_desc})",
                        flush=True,
                    )

                    # If headphones connected, auto-pin Mac built-in mic to preserve A2DP stereo
                    if headphones:
                        try:
                            auto_pin_mac_microphone()
                        except Exception:
                            pass

                    # Refresh PortAudio device table only when no mic recording or background stream is active
                    try:
                        from voicefi.tts.base import is_mic_recording_active

                        if not is_mic_recording_active() and PORTAUDIO_STREAM_LOCK.acquire(blocking=False):
                            try:
                                import sounddevice as sd

                                if hasattr(sd, "_terminate") and hasattr(sd, "_initialize"):
                                    sd._terminate()
                                    sd._initialize()
                            finally:
                                PORTAUDIO_STREAM_LOCK.release()
                    except Exception:
                        pass

                    if self.on_route_change:
                        try:
                            self.on_route_change(prev_out, cur_out, builtin_spk, headphones)
                        except Exception:
                            pass
            except Exception:
                pass


class _AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", ctypes.c_uint32),
        ("mScope", ctypes.c_uint32),
        ("mElement", ctypes.c_uint32),
    ]


_COREAUDIO_LIB = None
_LIBSYSTEM_LIB = None
_EXT_MIC_LOCK = threading.Lock()
_LAST_EXT_MIC_CHECK_TIME = 0.0
_CACHED_EXT_MIC_INFO: Optional[Dict[str, Any]] = None
_PID_APP_CACHE: Dict[int, Tuple[float, str, bool]] = {}

# Known non-dictation virtual audio routers and system daemons that do not represent user speech recording
_IGNORED_EXTERNAL_MIC_DAEMONS = (
    "coreaudiod",
    "backgroundmusic",
    "loopback",
    "loopbackd",
    "audiohijack",
    "soundsource",
    "eqmac",
    "krisp",
)


_LAST_VIFI_PIDS_CHECK_TIME = 0.0
_CACHED_VIFI_PIDS: Set[int] = set()


def reset_external_mic_detection_state() -> None:
    """Reset cached external microphone detection state (useful for tests)."""
    global _LAST_EXT_MIC_CHECK_TIME, _CACHED_EXT_MIC_INFO, _LAST_VIFI_PIDS_CHECK_TIME
    with _EXT_MIC_LOCK:
        _LAST_EXT_MIC_CHECK_TIME = 0.0
        _CACHED_EXT_MIC_INFO = None
        _LAST_VIFI_PIDS_CHECK_TIME = 0.0
        _CACHED_VIFI_PIDS.clear()
        _PID_APP_CACHE.clear()


def _get_known_voicefi_pids() -> Set[int]:
    """Return set of PIDs belonging to active VoiceFi processes (cached for 1.0s)."""
    global _LAST_VIFI_PIDS_CHECK_TIME, _CACHED_VIFI_PIDS
    now_mono = time.monotonic()
    with _EXT_MIC_LOCK:
        if _CACHED_VIFI_PIDS and (now_mono - _LAST_VIFI_PIDS_CHECK_TIME) < 1.0:
            return set(_CACHED_VIFI_PIDS)

    pids: Set[int] = {os.getpid(), os.getppid()}
    for pid_path in ("/tmp/voicefi.pid", "/tmp/voicefi_tray.pid"):
        try:
            p = Path(pid_path)
            if p.is_file():
                raw = p.read_text().strip()
                if raw.isdigit():
                    pids.add(int(raw))
        except Exception:
            pass
    for json_path in (
        "/tmp/voicefi_hud_owner.json",
        os.environ.get("VOICEFI_RECORDING_STATUS", "/tmp/voicefi_recording.status"),
        os.environ.get("VOICEFI_SPEAKING_STATUS", "/tmp/voicefi_speaking.status"),
    ):
        try:
            p = Path(json_path)
            if p.is_file():
                raw = p.read_text().strip()
                if raw:
                    if raw.startswith("{"):
                        data = json.loads(raw)
                        if isinstance(data, dict) and data.get("pid"):
                            pids.add(int(data["pid"]))
                    elif ":" in raw:
                        first = raw.split(":", 1)[0]
                        if first.isdigit():
                            pids.add(int(first))
        except Exception:
            pass

    with _EXT_MIC_LOCK:
        _CACHED_VIFI_PIDS = set(pids)
        _LAST_VIFI_PIDS_CHECK_TIME = now_mono
    return pids


def _get_pid_executable_path(pid: int) -> str:
    """Return full executable path for a process ID via libSystem proc_pidpath."""
    try:
        global _LIBSYSTEM_LIB
        if _LIBSYSTEM_LIB is None:
            _LIBSYSTEM_LIB = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        buf = ctypes.create_string_buffer(4096)
        res = _LIBSYSTEM_LIB.proc_pidpath(ctypes.c_int32(pid), buf, ctypes.c_uint32(4096))
        if res > 0:
            return buf.value.decode("utf-8", errors="ignore")
    except Exception:
        pass
    return ""


def _resolve_external_mic_pid(pid: int) -> Tuple[str, bool]:
    """
    Resolve (app_name, should_ignore) for a process ID that has an active CoreAudio input stream.
    Returns should_ignore=True for VoiceFi's own processes and passive virtual audio daemons.
    """
    if pid <= 0:
        return "VoiceFi", True

    now = time.monotonic()
    with _EXT_MIC_LOCK:
        cached = _PID_APP_CACHE.get(pid)
        if cached and (now - cached[0]) < 30.0:
            return cached[1], cached[2]

    if pid in _get_known_voicefi_pids():
        with _EXT_MIC_LOCK:
            _PID_APP_CACHE[pid] = (now, "VoiceFi", True)
        return "VoiceFi", True

    exe_path = _get_pid_executable_path(pid)
    bin_name = os.path.basename(exe_path) if exe_path else ""
    bin_lower = bin_name.lower()
    exe_lower = exe_path.lower()

    if "voicefi" in exe_lower or bin_lower == "vifi":
        with _EXT_MIC_LOCK:
            _PID_APP_CACHE[pid] = (now, "VoiceFi", True)
        return "VoiceFi", True

    if any(d in bin_lower for d in _IGNORED_EXTERNAL_MIC_DAEMONS):
        with _EXT_MIC_LOCK:
            _PID_APP_CACHE[pid] = (now, bin_name or "AudioDaemon", True)
        return bin_name or "AudioDaemon", True

    if bin_lower.startswith("python") or not exe_path:
        try:
            proc = subprocess.run(
                ["ps", "-p", str(pid), "-o", "args="],
                capture_output=True,
                text=True,
                timeout=0.15,
            )
            args_str = (proc.stdout or "").strip()
            args_lower = args_str.lower()
            if (
                "voicefi" in args_lower
                or "/vifi" in args_lower
                or args_lower.startswith("vifi ")
                or "pytest" in args_lower
            ):
                with _EXT_MIC_LOCK:
                    _PID_APP_CACHE[pid] = (now, "VoiceFi", True)
                return "VoiceFi", True
        except Exception:
            pass

    app_name = bin_name or f"PID {pid}"
    if ".app/" in exe_path:
        # Extract outermost .app bundle name (e.g. /Applications/Antigravity.app/... -> Antigravity)
        for part in exe_path.split("/"):
            if part.endswith(".app"):
                app_name = part[:-4]
                break
    elif bin_lower in ("corespeechd", "speechrecognitiond", "dictationim", "assistantd"):
        app_name = "macOS Dictation"

    with _EXT_MIC_LOCK:
        _PID_APP_CACHE[pid] = (now, app_name, False)
    return app_name, False


def get_external_mic_recording_info(
    use_cache: bool = True, ttl_s: float = 0.20
) -> Optional[Dict[str, Any]]:
    """
    Detect if an external application (such as Antigravity's built-in voice recording,
    macOS Dictation, Cursor, or browser voice input) currently has an active microphone
    input stream via macOS CoreAudio process objects (kAudioHardwarePropertyProcessObjectList).
    Excludes VoiceFi's own processes (which are tracked via MIC_RECORDING_STATUS_FILE).
    """
    global _COREAUDIO_LIB, _LAST_EXT_MIC_CHECK_TIME, _CACHED_EXT_MIC_INFO

    mock_ext = os.getenv("MOCK_EXTERNAL_MIC")
    if mock_ext is not None:
        if mock_ext.strip().lower() in ("", "0", "false", "no", "off", "none"):
            return None
        app_label = "Antigravity" if mock_ext == "1" else mock_ext
        return {
            "pid": 99999,
            "timestamp": time.time(),
            "state": "external_recording",
            "conv_id": "",
            "agent_name": app_label,
            "app_name": app_label,
            "source": "external_mic",
            "detail": f"{app_label} (native microphone)",
        }

    if sys.platform != "darwin":
        return None

    if (
        os.getenv("VOICEFI_MOCK_AUDIO") == "1"
        or os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("VOICEFI_TESTING") == "1"
        or os.getenv("PYTEST_CURRENT_TEST")
    ):
        return None

    now_mono = time.monotonic()
    with _EXT_MIC_LOCK:
        if use_cache and (now_mono - _LAST_EXT_MIC_CHECK_TIME) < ttl_s:
            return _CACHED_EXT_MIC_INFO

    detected_info: Optional[Dict[str, Any]] = None
    try:
        if _COREAUDIO_LIB is None:
            _COREAUDIO_LIB = ctypes.CDLL(
                "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
            )

        # kAudioHardwarePropertyProcessObjectList = 'prs#' (0x70727323)
        # kAudioObjectPropertyScopeGlobal = 'glob' (0x676C6F62)
        # kAudioObjectPropertyElementMain = 0
        addr_list = _AudioObjectPropertyAddress(0x70727323, 0x676C6F62, 0)
        size = ctypes.c_uint32(0)
        status = _COREAUDIO_LIB.AudioObjectGetPropertyDataSize(
            ctypes.c_uint32(1),
            ctypes.byref(addr_list),
            ctypes.c_uint32(0),
            None,
            ctypes.byref(size),
        )
        if status == 0 and size.value > 0:
            count = size.value // 4
            objs = (ctypes.c_uint32 * count)()
            status = _COREAUDIO_LIB.AudioObjectGetPropertyData(
                ctypes.c_uint32(1),
                ctypes.byref(addr_list),
                ctypes.c_uint32(0),
                None,
                ctypes.byref(size),
                objs,
            )
            if status == 0:
                # kAudioProcessPropertyIsRunningInput = 'piri' (0x70697269)
                # kAudioProcessPropertyPID = 'ppid' (0x70706964)
                addr_piri = _AudioObjectPropertyAddress(0x70697269, 0x676C6F62, 0)
                addr_ppid = _AudioObjectPropertyAddress(0x70706964, 0x676C6F62, 0)
                known_vifi_pids: Optional[Set[int]] = None

                for i in range(count):
                    obj_id = objs[i]
                    piri_val = ctypes.c_uint32(0)
                    piri_sz = ctypes.c_uint32(4)
                    st_piri = _COREAUDIO_LIB.AudioObjectGetPropertyData(
                        ctypes.c_uint32(obj_id),
                        ctypes.byref(addr_piri),
                        ctypes.c_uint32(0),
                        None,
                        ctypes.byref(piri_sz),
                        ctypes.byref(piri_val),
                    )
                    if st_piri != 0 or piri_val.value == 0:
                        continue

                    pid_val = ctypes.c_int32(0)
                    pid_sz = ctypes.c_uint32(4)
                    st_pid = _COREAUDIO_LIB.AudioObjectGetPropertyData(
                        ctypes.c_uint32(obj_id),
                        ctypes.byref(addr_ppid),
                        ctypes.c_uint32(0),
                        None,
                        ctypes.byref(pid_sz),
                        ctypes.byref(pid_val),
                    )
                    if st_pid != 0 or pid_val.value <= 0:
                        continue

                    ext_pid = int(pid_val.value)
                    if known_vifi_pids is None:
                        known_vifi_pids = _get_known_voicefi_pids()
                    if ext_pid in known_vifi_pids:
                        continue

                    app_name, should_ignore = _resolve_external_mic_pid(ext_pid)
                    if should_ignore:
                        continue

                    detected_info = {
                        "pid": ext_pid,
                        "timestamp": time.time(),
                        "state": "external_recording",
                        "conv_id": "",
                        "agent_name": app_name,
                        "app_name": app_name,
                        "source": "external_mic",
                        "detail": f"{app_name} (PID {ext_pid})",
                    }
                    break
    except Exception:
        detected_info = None

    with _EXT_MIC_LOCK:
        _CACHED_EXT_MIC_INFO = detected_info
        _LAST_EXT_MIC_CHECK_TIME = now_mono
    return detected_info


def is_external_mic_recording_active(use_cache: bool = True, ttl_s: float = 0.20) -> bool:
    """Return True if an external non-VoiceFi application is actively recording from the microphone."""
    return get_external_mic_recording_info(use_cache=use_cache, ttl_s=ttl_s) is not None


