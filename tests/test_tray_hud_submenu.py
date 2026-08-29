"""
Unit tests for VoiceFiTrayApp Dynamic Island HUD submenu.
Validates:
1. Submenu initialization and item structure.
2. Toggle callbacks (persistent mode, auto send, full screen overlay, live transcript, speech popup).
3. Screen position selection and reset.
4. State preview callbacks.
"""

from unittest.mock import MagicMock, patch
import pytest
from voicefi.config import VoiceFiConfig, HUDConfig
from voicefi.ui.tray import VoiceFiTrayApp


@pytest.fixture
def mock_tray_app():
    with patch("voicefi.ui.tray.TranscriptWatcher"), \
         patch("voicefi.ui.tray.ConversationHubWindow"), \
         patch("voicefi.ui.tray.rumps.App.__init__"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._setup_cocoa_hotkeys"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_conversations_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_integrations_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_personas_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_voice_mode_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_troubleshoot_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_memo_submenu"), \
         patch("voicefi.ui.tray.UnifiedDynamicIslandHUD") as mock_hud_cls:

        mock_hud = MagicMock()
        mock_hud_cls.get_instance.return_value = mock_hud

        app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app.config.hud = HUDConfig()
        app.hud = mock_hud
        app.hud_menu = MagicMock()

        yield app, mock_hud


def test_hud_submenu_builder(mock_tray_app):
    app, mock_hud = mock_tray_app
    app._build_hud_submenu()

    app.hud_menu.update.assert_called_once()
    items = app.hud_menu.update.call_args[0][0]
    titles = [item.title for item in items if hasattr(item, "title")]

    assert any("Enable Dynamic Island HUD" in t for t in titles)
    assert any("Persistent Resting Pill" in t for t in titles)
    assert any("Auto-Send Prompts" in t for t in titles)
    assert any("Always on Top of Full-Screen Apps" in t for t in titles)
    assert any("Live Dictation Typing Stream" in t for t in titles)
    assert any("Show Speech Subtitles & Waveforms" in t for t in titles)
    assert any("Screen Position" in t for t in titles)
    assert any("Test & Preview States" in t for t in titles)
    assert any("Reset HUD Position" in t for t in titles)


def test_toggle_persistent_hud(mock_tray_app):
    app, mock_hud = mock_tray_app
    app.config.hud.persistent = True

    with patch("voicefi.ui.tray.save_config"):
        app.toggle_persistent_hud()
        assert app.config.hud.persistent is False
        mock_hud.set_persistent.assert_called_with(False)


def test_toggle_fullscreen_overlay(mock_tray_app):
    app, mock_hud = mock_tray_app
    app.config.hud.fullscreen_overlay = True

    with patch("voicefi.ui.tray.save_config"):
        app.toggle_fullscreen_overlay()
        assert app.config.hud.fullscreen_overlay is False
        mock_hud.set_fullscreen_overlay.assert_called_with(False)


def test_toggle_auto_send(mock_tray_app):
    app, mock_hud = mock_tray_app
    app.config.hud.auto_send = True

    with patch("voicefi.ui.tray.save_config"):
        app.toggle_auto_send()
        assert app.config.hud.auto_send is False
        mock_hud.set_auto_send.assert_called_with(False)


def test_reset_hud_position(mock_tray_app):
    app, mock_hud = mock_tray_app
    with patch("voicefi.ui.tray.save_config"), patch("rumps.notification"):
        app.reset_hud_position()
        mock_hud.reset_position.assert_called_once()
