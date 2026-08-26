"""
Unit tests for ConversationHubWindow and Activity Hub hotkey toggle debouncing.
"""

import time
import threading
from unittest.mock import MagicMock, patch
import pytest

from AppKit import NSRect, NSPoint, NSSize
from voicefi.integrations.conversations import ConversationTracker, ConversationInfo
from voicefi.ui.hub import ConversationHubWindow, HubActionTarget


@pytest.fixture
def mock_tracker(tmp_path):
    tracker = ConversationTracker(brain_dir=tmp_path)
    return tracker


@pytest.fixture(autouse=True)
def cleanup_hub_window():
    ConversationHubWindow._instance = None
    yield
    if ConversationHubWindow._instance is not None:
        try:
            if ConversationHubWindow._instance._panel:
                ConversationHubWindow._instance.hide()
                ConversationHubWindow._instance._panel.orderOut_(None)
                ConversationHubWindow._instance._panel.close()
        except Exception:
            pass
        ConversationHubWindow._instance = None


def test_hub_action_target():
    """Test HubActionTarget callback execution."""
    called = []
    target = HubActionTarget.alloc().initWithCallback_(lambda: called.append(True))
    target.buttonClicked_(None)
    assert len(called) == 1


def test_conversation_hub_window_singleton(mock_tracker):
    """Test ConversationHubWindow get_instance singleton pattern."""
    ConversationHubWindow._instance = None
    hub1 = ConversationHubWindow.get_instance(mock_tracker)
    hub2 = ConversationHubWindow.get_instance(mock_tracker)
    assert hub1 is hub2
    assert hub1._panel is not None


def test_conversation_hub_window_debounce(mock_tracker):
    """Test rapid calls to hub.toggle() are debounced and only execute once."""
    ConversationHubWindow._instance = None
    hub = ConversationHubWindow.get_instance(mock_tracker)
    hub._panel = MagicMock()
    hub._panel.isVisible.return_value = False

    with patch.object(hub, "show") as mock_show, \
         patch.object(hub, "hide") as mock_hide:
        # First toggle should call show (panel not visible)
        hub.toggle()
        assert mock_show.call_count == 1
        assert mock_hide.call_count == 0

        # Immediate second toggle within 0.4s should be debounced and ignored
        hub.toggle()
        assert mock_show.call_count == 1
        assert mock_hide.call_count == 0

        # Reset debounce time and toggle again
        hub._last_toggle_time = time.time() - 1.0
        # Mock panel visible
        hub._panel.isVisible.return_value = True
        hub.toggle()
        assert mock_hide.call_count == 1


def test_conversation_hub_window_show_and_hide(mock_tracker):
    """Test show and hide methods manage auto-refresh and orderFront/orderOut."""
    ConversationHubWindow._instance = None
    hub = ConversationHubWindow.get_instance(mock_tracker)

    with patch.object(hub, "_refresh_ui") as mock_refresh_ui, \
         patch.object(hub, "_start_auto_refresh") as mock_start_auto, \
         patch.object(hub, "_stop_auto_refresh") as mock_stop_auto:
        
        hub._panel = MagicMock()
        hub._panel.isVisible.return_value = False

        # Show
        hub.show()
        mock_refresh_ui.assert_called_once()
        mock_start_auto.assert_called_once()
        hub._panel.orderFrontRegardless.assert_called_once()
        hub._panel.makeKeyAndOrderFront_.assert_called_once_with(None)

        # Hide
        hub._panel.isVisible.return_value = True
        hub.hide()
        mock_stop_auto.assert_called_once()
        hub._panel.orderOut_.assert_called_once_with(None)


def test_conversation_hub_auto_refresh_lifecycle(mock_tracker):
    """Test starting and stopping auto-refresh timers."""
    ConversationHubWindow._instance = None
    hub = ConversationHubWindow.get_instance(mock_tracker)

    hub._start_auto_refresh()
    assert hub._timer is not None

    hub._stop_auto_refresh()
    assert hub._timer is None


def test_tray_toggle_hub_debouncing():
    """Test VoiceFiTrayApp.toggle_hub debounces rapid duplicate calls."""
    from voicefi.ui.tray import VoiceFiTrayApp

    with patch("voicefi.ui.tray.TranscriptWatcher"), \
         patch("voicefi.ui.tray.ConversationHubWindow") as mock_hub_cls, \
         patch("voicefi.ui.tray.rumps.App.__init__"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._setup_cocoa_hotkeys"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_conversations_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_integrations_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_personas_submenu"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._build_voice_mode_submenu"):

        mock_hub_instance = MagicMock()
        mock_hub_cls.get_instance.return_value = mock_hub_instance

        app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
        app.hub = mock_hub_instance

        # First call should call hub.toggle()
        app.toggle_hub()
        assert mock_hub_instance.toggle.call_count == 1

        # Second call immediately should be ignored by debounce
        app.toggle_hub()
        assert mock_hub_instance.toggle.call_count == 1

        # After cooldown passes, call should proceed
        app._last_hub_toggle_time = time.time() - 1.0
        app.toggle_hub()
        assert mock_hub_instance.toggle.call_count == 2


def test_conversation_hub_new_conversation_action(mock_tracker):
    """Test clicking the New (Tools) button triggers the on_new_conversation callback."""
    ConversationHubWindow._instance = None
    new_conv_called = []
    hub = ConversationHubWindow.get_instance(
        mock_tracker,
        on_new_conversation=lambda: new_conv_called.append(True),
    )
    assert hub.on_new_conversation is not None

    hub.show()
    assert len(hub._targets) >= 4  # New conv, Focus, Sync, Panel

    # First target in list is the new_conv action target
    hub._targets[0].buttonClicked_(None)
    assert len(new_conv_called) == 1


def test_conversation_hub_positioning(mock_tracker):
    """Test Activity Hub window is positioned right-aligned and below the main HUD with gap."""
    from voicefi.config import VoiceFiConfig
    ConversationHubWindow._instance = None
    hub = ConversationHubWindow.get_instance(mock_tracker)
    hub._panel = MagicMock()
    hub._panel.frame.return_value = NSRect(NSPoint(0, 0), NSSize(520, 420))

    mock_screen = MagicMock()
    mock_visible = MagicMock()
    mock_visible.origin.x = 0.0
    mock_visible.origin.y = 0.0
    mock_visible.size.width = 1920.0
    mock_visible.size.height = 1080.0
    mock_screen.visibleFrame.return_value = mock_visible

    mock_nsscreen = MagicMock()
    mock_nsscreen.mainScreen.return_value = mock_screen

    cfg = VoiceFiConfig()
    cfg.hud.margin_x = 20.0
    cfg.hud.margin_y = 96.0

    with patch("voicefi.ui.hub.NSScreen", mock_nsscreen), \
         patch("voicefi.config.load_config", return_value=cfg):
        hub._position_top_right()

        # width = 520, height = 420
        # Expected x = 1920 - 520 - 0.0 (margin_right, no gap) = 1400.0
        # Expected y = 1080 - 420 - 96 (margin_y) - 58 (hud_height) - 8 (gap) = 498.0
        assert hub._panel.setFrameOrigin_.called
        call_point = hub._panel.setFrameOrigin_.call_args[0][0]
        assert call_point.x == 1400.0
        assert call_point.y == 498.0


