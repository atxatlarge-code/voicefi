import os
import pytest
from pathlib import Path
from voicefi.config import VoiceFiConfig, save_config

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
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("VECLIB_MAXIMUM_THREADS", "1")
    monkeypatch.setenv("NUMEXPR_NUM_THREADS", "1")
    monkeypatch.setenv("ORT_NUM_THREADS", "1")

    # Isolate speech dedup, turns, and spoken history per test
    test_speech_lock = tmp_path / "voicefi_speech.lock"
    monkeypatch.setattr("voicefi.tts.base.SPEECH_LOCK_FILE", test_speech_lock)
    monkeypatch.setenv("VOICEFI_SPEECH_LOCK", str(test_speech_lock))

    test_stop_ts = tmp_path / "voicefi_last_speech_stop.ts"
    monkeypatch.setattr("voicefi.tts.base._LAST_SPEECH_STOP_FILE", test_stop_ts)

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
    orig_run = subprocess.run

    def safe_subprocess_run(args, *pargs, **kwargs):
        if isinstance(args, (list, tuple)) and len(args) > 0:
            cmd = str(args[0])
            if cmd in ("afplay", "say"):
                from unittest.mock import MagicMock
                return MagicMock(returncode=0, stdout=b"", stderr=b"")
        elif isinstance(args, str) and (args.startswith("afplay ") or args.startswith("say ")):
            from unittest.mock import MagicMock
            return MagicMock(returncode=0, stdout=b"", stderr=b"")
        return orig_run(args, *pargs, **kwargs)

    monkeypatch.setattr(subprocess, "run", safe_subprocess_run)
    yield

