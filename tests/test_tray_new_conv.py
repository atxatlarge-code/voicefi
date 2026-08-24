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
