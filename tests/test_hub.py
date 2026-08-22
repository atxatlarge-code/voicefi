"""
Unit tests for ConversationHubWindow and Activity Hub hotkey toggle debouncing.
"""

import time
import threading
from unittest.mock import MagicMock, patch
import pytest

from voicegency.integrations.conversations import ConversationTracker, ConversationInfo
from voicegency.ui.hub import ConversationHubWindow, HubActionTarget


@pytest.fixture
def mock_tracker(tmp_path):
    tracker = ConversationTracker(brain_dir=tmp_path)
    return tracker


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
    """Test VoicegencyTrayApp.toggle_hub debounces rapid duplicate calls."""
    from voicegency.ui.tray import VoicegencyTrayApp

    with patch("voicegency.ui.tray.TranscriptWatcher"), \
         patch("voicegency.ui.tray.ConversationHubWindow") as mock_hub_cls, \
         patch("voicegency.ui.tray.rumps.App.__init__"), \
         patch("voicegency.ui.tray.VoicegencyTrayApp._setup_cocoa_hotkeys"), \
         patch("voicegency.ui.tray.VoicegencyTrayApp._build_conversations_submenu"), \
         patch("voicegency.ui.tray.VoicegencyTrayApp._build_integrations_submenu"), \
         patch("voicegency.ui.tray.VoicegencyTrayApp._build_personas_submenu"), \
         patch("voicegency.ui.tray.VoicegencyTrayApp._build_voice_mode_submenu"):

        mock_hub_instance = MagicMock()
        mock_hub_cls.get_instance.return_value = mock_hub_instance

        app = VoicegencyTrayApp.__new__(VoicegencyTrayApp)
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
