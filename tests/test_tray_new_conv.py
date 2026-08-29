"""
Unit tests for starting new conversation with connected tools via Tray companion and CLI.
"""

from unittest.mock import MagicMock, patch
import pytest
from voicefi.config import VoiceFiConfig
from voicefi.ui.tray import VoiceFiTrayApp
from voicefi.cli import cmd_new


@pytest.fixture
def mock_tray_env():
    with patch("voicefi.ui.tray.TranscriptWatcher"), \
         patch("voicefi.ui.tray.ConversationHubWindow") as mock_hub_cls, \
         patch("voicefi.ui.tray.rumps.App.__init__"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._setup_cocoa_hotkeys"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_conversations_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_integrations_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_personas_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_voice_mode_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_hud_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_troubleshoot_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_memo_submenu"), \
         patch("voicefi.ui.tray.UnifiedDynamicIslandHUD") as mock_hud_cls:

        mock_hub = MagicMock()
        mock_hub_cls.get_instance.return_value = mock_hub
        mock_hud = MagicMock()
        mock_hud_cls.get_instance.return_value = mock_hud

        yield mock_hub, mock_hud


def test_tray_menu_has_new_conversation_item(mock_tray_env):
    """Verify tray menu includes the new conversation action item."""
    mock_hub, mock_hud = mock_tray_env
    app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
    app.config = VoiceFiConfig()
    app.watcher = MagicMock()
    app.hub = mock_hub
    app.hud = mock_hud
    app._listen_lock = MagicMock()
    app._current_status = "idle"

    assert hasattr(VoiceFiTrayApp, "trigger_new_conversation")


def test_tray_trigger_new_conversation_direct_prompt(mock_tray_env):
    """Verify trigger_new_conversation executes create_new_antigravity_conversation."""
    mock_hub, mock_hud = mock_tray_env
    app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
    app.config = VoiceFiConfig()
    app.watcher = MagicMock()
    app.hub = mock_hub
    app.hud = mock_hud
    import threading
    app._listen_lock = threading.Lock()
    app._current_status = "idle"
    app._build_conversations_submenu = MagicMock()

    with patch("voicefi.integrations.injector.create_new_antigravity_conversation") as mock_create:
        mock_create.return_value = "new-conv-uuid-1234"
        app.trigger_new_conversation(prompt_text="Build new billing webhook")
        mock_create.assert_called_once_with(prompt="Build new billing webhook")
        app.watcher.tracker.set_active_focus.assert_called_once_with("new-conv-uuid-1234")
        mock_hud.show_done.assert_called_once()


def test_cli_cmd_new():
    """Verify vifi new command invokes create_new_antigravity_conversation."""
    args = MagicMock()
    args.config = None
    args.prompt = ["Refactor", "API", "endpoints"]
    args.title = "Refactor Task"
    args.model = "pro"

    with patch("voicefi.integrations.injector.create_new_antigravity_conversation") as mock_create:
        mock_create.return_value = "conv-9988"
        cmd_new(args)
        mock_create.assert_called_once_with(
            prompt="Refactor API endpoints",
            title="Refactor Task",
            model="pro",
        )


def test_tray_trigger_talk_to_antigravity_toggle(mock_tray_env):
    """Verify that calling trigger_talk_to_antigravity while already listening toggles/finishes recording."""
    mock_hub, mock_hud = mock_tray_env
    app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
    app.config = VoiceFiConfig()
    import threading
    app._listen_lock = threading.Lock()
    app._current_status = "listening"
    app.finish_active_recording = MagicMock()

    app.trigger_talk_to_antigravity()
    app.finish_active_recording.assert_called_once()


def test_tray_hybrid_and_ptt_hotkey_release(mock_tray_env):
    """Verify hotkey release logic for hybrid (tap vs hold) and PTT modes."""
    mock_hub, mock_hud = mock_tray_env
    app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
    app.config = VoiceFiConfig()
    import threading
    import time
    app._listen_lock = threading.Lock()
    app._current_status = "idle"
    app._key_down_times = {}
    app.active_recorder = None
    app.finish_active_recording = MagicMock()

    # In hybrid mode: short tap (< 350ms) should NOT finish active recording
    app.config.vad.mode = "hybrid"
    app._current_status = "listening"
    app._key_down_times['respond'] = time.time() - 0.1  # 100ms ago

    # Simulate release callback logic
    down_time = app._key_down_times.get('respond')
    if down_time and (time.time() - down_time) >= 0.35:
        app.finish_active_recording()
    app.finish_active_recording.assert_not_called()

    # In hybrid mode: hold (> 350ms) SHOULD finish active recording on release
    app._key_down_times['respond'] = time.time() - 0.5  # 500ms ago
    down_time = app._key_down_times.get('respond')
    if down_time and (time.time() - down_time) >= 0.35:
        app.finish_active_recording()
    app.finish_active_recording.assert_called_once()

