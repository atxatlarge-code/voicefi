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

    # Isolate speech dedup, turns, and spoken history per test
    test_recent_speech = tmp_path / "recent_speech.json"
    monkeypatch.setattr("voicefi.tts.base.RECENT_SPEECH_FILE", test_recent_speech)

    test_hud_state = tmp_path / "voicefi_hud_state.json"
    monkeypatch.setattr("voicefi.tts.base.HUD_STATE_STATUS_FILE", test_hud_state)

    from voicefi.audio.echo_canceller import clear_agent_spoken_history
    clear_agent_spoken_history()

    yield test_config_file


@pytest.fixture(autouse=True)
def cleanup_ui_singletons():
    """Ensure all HUD and Activity Hub UI instances and timers are cleaned up after each test."""
    yield
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
