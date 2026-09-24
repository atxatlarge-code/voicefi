import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from voicefi.config import VoiceFiConfig, save_config

# On Linux / non-darwin platforms or headless CI where macOS UI frameworks
# (AppKit, rumps, Cocoa, Quartz, objc) are not available, provide stub modules
# so test collection and headless execution succeed without ModuleNotFoundError.
if sys.platform != "darwin":
    for mod_name in [
        "AppKit",
        "rumps",
        "Cocoa",
        "Quartz",
        "objc",
        "Foundation",
        "PyObjCTools",
        "ApplicationServices",
    ]:
        if mod_name not in sys.modules:
            try:
                __import__(mod_name)
            except ImportError:
                mock_mod = MagicMock()
                mock_mod.__name__ = mod_name
                if mod_name == "objc":
                    mock_mod.python_method = lambda fn: fn
                    mock_mod.IBAction = lambda fn: fn
                elif mod_name == "rumps":

                    class _StubRumpsApp:
                        def __init__(self, *args, **kwargs):
                            self.title = args[0] if args else kwargs.get("name", "VoiceFi")
                            self.menu = {}
                            self.icon = None

                        def run(self):
                            pass

                    class _StubRumpsMenuItem:
                        def __init__(self, *args, **kwargs):
                            self.title = args[0] if args else kwargs.get("title", "")
                            self.state = 0
                            self.callback = kwargs.get("callback")
                            self._items = {}

                        def update(self, *args, **kwargs):
                            return self

                        def clear(self):
                            self._items.clear()

                        def add(self, *args, **kwargs):
                            pass

                        def insert_before(self, *args, **kwargs):
                            pass

                        def insert_after(self, *args, **kwargs):
                            pass

                        def __getitem__(self, key):
                            return self._items.get(key)

                        def __setitem__(self, key, value):
                            self._items[key] = value

                        def __contains__(self, key):
                            return key in self._items

                        def get(self, key, default=None):
                            return self._items.get(key, default)

                    mock_mod.App = _StubRumpsApp
                    mock_mod.MenuItem = _StubRumpsMenuItem
                    mock_mod.Timer = MagicMock
                sys.modules[mod_name] = mock_mod

# On headless environments without X11 or display server, pynput import fails.
# Provide a standard headless stub for pynput.keyboard.
try:
    import pynput.keyboard  # noqa: F401
except Exception:
    import types
    from enum import Enum

    class _StubKey(Enum):
        esc = "Key.esc"
        tab = "Key.tab"
        space = "Key.space"
        enter = "Key.enter"
        cmd = "Key.cmd"
        cmd_l = "Key.cmd_l"
        cmd_r = "Key.cmd_r"
        alt = "Key.alt"
        alt_l = "Key.alt_l"
        alt_r = "Key.alt_r"
        alt_gr = "Key.alt_gr"
        ctrl = "Key.ctrl"
        ctrl_l = "Key.ctrl_l"
        ctrl_r = "Key.ctrl_r"
        shift = "Key.shift"
        shift_l = "Key.shift_l"
        shift_r = "Key.shift_r"
        up = "Key.up"
        down = "Key.down"
        left = "Key.left"
        right = "Key.right"

    class _StubKeyCode:
        def __init__(self, vk=None, char=None):
            self.vk = vk
            self.char = char

        @classmethod
        def from_vk(cls, vk, **kwargs):
            return cls(vk=vk)

        @classmethod
        def from_char(cls, char, **kwargs):
            return cls(char=char)

        def __eq__(self, other):
            if isinstance(other, _StubKeyCode):
                return self.vk == other.vk and self.char == other.char
            return False

        def __str__(self):
            if self.vk is not None:
                return f"<{self.vk}>"
            return f"'{self.char}'"

    class _StubListener:
        def __init__(self, on_press=None, on_release=None, *args, **kwargs):
            self.on_press = on_press
            self.on_release = on_release
            self.running = False
            self.daemon = True

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

        def join(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    _pynput_mod = sys.modules.get("pynput", types.ModuleType("pynput"))
    _pynput_kb = types.ModuleType("pynput.keyboard")
    _pynput_kb.Key = _StubKey
    _pynput_kb.KeyCode = _StubKeyCode
    _pynput_kb.Listener = _StubListener
    _pynput_kb.Controller = MagicMock
    _pynput_mod.keyboard = _pynput_kb
    sys.modules["pynput"] = _pynput_mod
    sys.modules["pynput.keyboard"] = _pynput_kb


@pytest.fixture(autouse=True)
def isolate_test_config(tmp_path, monkeypatch):
    """Isolate tests so they never read or write ~/.voicefi/config.yaml or shared temp files."""
    test_config_file = tmp_path / "config.yaml"
    initial_cfg = VoiceFiConfig()
    save_config(initial_cfg, target_path=test_config_file)
    monkeypatch.setenv("VOICEFI_CONFIG", str(test_config_file))
    monkeypatch.setattr("voicefi.config.get_default_config_path", lambda: test_config_file)
    monkeypatch.setenv("VOICEFI_TELEMETRY", "0")
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("VOICEFI_HEADLESS", "1")
    monkeypatch.setenv("VOICEFI_TESTING", "1")
    monkeypatch.setenv("ANTIGRAVITY_LS_ADDRESS", "127.0.0.1:54321")
    monkeypatch.setenv("ANTIGRAVITY_CSRF_TOKEN", "test-token")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("VECLIB_MAXIMUM_THREADS", "1")
    monkeypatch.setenv("NUMEXPR_NUM_THREADS", "1")
    monkeypatch.setenv("ORT_NUM_THREADS", "1")

    # Ensure PostHog telemetry is never dispatched during test runs
    import voicefi.mcp_server as mcp_mod

    mcp_mod._mcp_posthog = None
    mcp_mod._mcp_posthog_initialized = False
    monkeypatch.setattr("voicefi.mcp_server.get_mcp_posthog", lambda: None)

    # Isolate speech dedup, turns, and spoken history per test
    test_speech_lock = tmp_path / "voicefi_speech.lock"
    monkeypatch.setattr("voicefi.tts.base.SPEECH_LOCK_FILE", test_speech_lock)
    monkeypatch.setenv("VOICEFI_SPEECH_LOCK", str(test_speech_lock))

    test_stop_ts = tmp_path / "voicefi_last_speech_stop.ts"
    monkeypatch.setattr("voicefi.tts.base._LAST_SPEECH_STOP_FILE", test_stop_ts)

    # Isolate cross-process turn locks and companion markers per test
    test_turn_file = tmp_path / "voicefi_active_turns.json"
    test_turn_lock = tmp_path / "voicefi_active_turns.lock"
    test_mobile_turn = tmp_path / "voicefi_mobile_turn.json"
    test_companion_clients = tmp_path / "voicefi_companion_clients.json"
    monkeypatch.setattr("voicefi.integrations.turn_lock._ACTIVE_TURNS_FILE", test_turn_file)
    monkeypatch.setattr("voicefi.integrations.turn_lock._ACTIVE_TURNS_LOCK", test_turn_lock)
    monkeypatch.setattr("voicefi.integrations.turn_lock._MOBILE_TURN_FILE", test_mobile_turn)
    monkeypatch.setattr(
        "voicefi.integrations.turn_lock._COMPANION_CLIENTS_FILE", test_companion_clients
    )

    test_recent_speech = tmp_path / "recent_speech.json"
    monkeypatch.setattr("voicefi.tts.base.RECENT_SPEECH_FILE", test_recent_speech)
    monkeypatch.setenv("VOICEFI_RECENT_SPEECH", str(test_recent_speech))

    test_hud_state = tmp_path / "voicefi_hud_state.json"
    monkeypatch.setattr("voicefi.tts.base.HUD_STATE_STATUS_FILE", test_hud_state)
    monkeypatch.setenv("VOICEFI_HUD_STATE_STATUS", str(test_hud_state))

    test_speaking_file = tmp_path / "voicefi_speaking.status"
    monkeypatch.setattr("voicefi.tts.base.AGENT_SPEAKING_STATUS_FILE", test_speaking_file)
    monkeypatch.setenv("VOICEFI_SPEAKING_STATUS", str(test_speaking_file))

    test_audio_playing_file = tmp_path / "voicefi_audio_playing.status"
    monkeypatch.setattr("voicefi.tts.base.AUDIO_PLAYING_STATUS_FILE", test_audio_playing_file)
    monkeypatch.setenv("VOICEFI_AUDIO_PLAYING_STATUS", str(test_audio_playing_file))

    import voicefi.tts.base as tts_base

    tts_base.set_agent_speaking(False)
    tts_base._IN_PROCESS_SPEAKING = False
    tts_base._IN_PROCESS_AUDIO_PLAYING = False
    tts_base._LOCK_DEPTH = 0

    from voicefi.audio.echo_canceller import clear_agent_spoken_history

    clear_agent_spoken_history()

    yield test_config_file

    tts_base.set_agent_speaking(False)
    tts_base._IN_PROCESS_SPEAKING = False
    tts_base._IN_PROCESS_AUDIO_PLAYING = False
    tts_base._LOCK_DEPTH = 0
    clear_agent_spoken_history()


@pytest.fixture(autouse=True)
def cleanup_ui_singletons():
    """Ensure all HUD, Activity Hub, VAD Monitor UI instances and temp files are cleaned up before and after each test."""

    def _do_cleanup():
        try:
            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

            if UnifiedDynamicIslandHUD._instance is not None:
                UnifiedDynamicIslandHUD._instance.force_hide()
                UnifiedDynamicIslandHUD._instance = None
        except Exception:
            pass

        try:
            from voicefi.ui.hub import ConversationHubWindow

            if ConversationHubWindow._instance is not None:
                ConversationHubWindow._instance.hide()
                ConversationHubWindow._instance = None
        except Exception:
            pass

        try:
            from voicefi.audio.monitor import LiveVADMonitor

            if LiveVADMonitor._instance is not None:
                LiveVADMonitor._instance.stop()
                LiveVADMonitor._instance = None
        except Exception:
            pass

        try:
            from voicefi.audio.wakeword import WakeWordListener

            for inst in list(WakeWordListener._ACTIVE_INSTANCES):
                try:
                    inst.stop()
                except Exception:
                    pass
            WakeWordListener._ACTIVE_INSTANCES.clear()
        except Exception:
            pass

        for p in (
            Path("/tmp/voicefi_cross_process_hud.json"),
            Path("/tmp/voicefi_hud_state.json"),
            Path("/tmp/voicefi_hud_stream.json"),
            Path("/tmp/voicefi_companion_clients.json"),
            Path("/tmp/voicefi_active_turns.json"),
            Path("/tmp/voicefi_active_turns.lock"),
        ):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    _do_cleanup()
    yield
    _do_cleanup()


@pytest.fixture(autouse=True)
def prevent_real_audio_playback(monkeypatch):
    """Ensure automated tests never play real audio or trigger afplay/say subprocesses."""
    import subprocess
    from unittest.mock import MagicMock

    AUDIO_COMMANDS = {"afplay", "say", "ffplay", "mpv", "paplay", "aplay"}

    def is_audio_cmd(args):
        if isinstance(args, (list, tuple)) and len(args) > 0:
            cmd = str(args[0])
            base_cmd = os.path.basename(cmd)
            return base_cmd in AUDIO_COMMANDS
        elif isinstance(args, str):
            first_token = args.split()[0] if args.split() else ""
            base_cmd = os.path.basename(first_token)
            return base_cmd in AUDIO_COMMANDS
        return False

    orig_run = subprocess.run

    def safe_subprocess_run(args, *pargs, **kwargs):
        if is_audio_cmd(args):
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        return orig_run(args, *pargs, **kwargs)

    orig_call = subprocess.call

    def safe_subprocess_call(args, *pargs, **kwargs):
        if is_audio_cmd(args):
            return 0
        return orig_call(args, *pargs, **kwargs)

    orig_check_call = subprocess.check_call

    def safe_subprocess_check_call(args, *pargs, **kwargs):
        if is_audio_cmd(args):
            return 0
        return orig_check_call(args, *pargs, **kwargs)

    orig_popen = subprocess.Popen

    class safe_subprocess_popen(orig_popen):
        def __new__(cls, args, *pargs, **kwargs):
            if is_audio_cmd(args):
                mock_proc = MagicMock()
                mock_proc.returncode = 0
                mock_proc.pid = 99999
                mock_proc.args = args
                mock_proc.wait.return_value = 0
                mock_proc.poll.return_value = 0
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.terminate.return_value = None
                mock_proc.kill.return_value = None
                mock_proc.__enter__.return_value = mock_proc
                mock_proc.__exit__.return_value = None
                mock_proc.stdin = MagicMock()
                mock_proc.stdout = MagicMock()
                mock_proc.stderr = MagicMock()
                return mock_proc
            return orig_popen(args, *pargs, **kwargs)

    monkeypatch.setattr(subprocess, "run", safe_subprocess_run)
    monkeypatch.setattr(subprocess, "call", safe_subprocess_call)
    monkeypatch.setattr(subprocess, "check_call", safe_subprocess_check_call)
    monkeypatch.setattr(subprocess, "Popen", safe_subprocess_popen)

    try:
        import sounddevice as sd

        monkeypatch.setattr(sd, "play", lambda *a, **kw: None)
        monkeypatch.setattr(sd, "stop", lambda *a, **kw: None)

        if os.getenv("VOICEFI_MOCK_AUDIO") == "1":

            class MockAudioStream(MagicMock):
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def start(self):
                    pass

                def stop(self):
                    pass

                def close(self):
                    pass

                def read(self, frames):
                    import numpy as np

                    return np.zeros((frames, 1), dtype=np.float32), False

            monkeypatch.setattr(sd, "OutputStream", lambda *a, **kw: MockAudioStream())
            monkeypatch.setattr(sd, "RawOutputStream", lambda *a, **kw: MockAudioStream())
    except Exception:
        pass

    yield


@pytest.fixture(autouse=True)
def setup_test_license_keys(monkeypatch):
    """Ensure tests have a valid Ed25519 signing keypair matching embedded public key."""
    key_path = Path.home() / ".voicefi" / "admin_keys" / "voicefi_ed25519_private.key"
    if not os.environ.get("VOICEFI_SIGNING_PRIVATE_KEY") and not key_path.is_file():
        monkeypatch.setenv(
            "VOICEFI_SIGNING_PRIVATE_KEY",
            "75517c236305fa2c92df89e5a10edd730baabe0f0e5e8333651633cd49f401ba",
        )


def pytest_unconfigure(config):
    """Cleanly terminate PortAudio and background worker resources before interpreter teardown."""
    try:
        import sounddevice as sd

        sd._terminate()
    except Exception:
        pass
