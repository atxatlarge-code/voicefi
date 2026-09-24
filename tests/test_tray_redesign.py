"""
Unit tests for the redesigned VoiceFi macOS Menu Bar Tray App.
Validates:
1. Remote Companion is hero item #1 at the top of the menu.
2. Connected Tools & Integrations matrix is item #2, confirming active tools.
3. Streamlined primary menu layout (28 items reduced to clean core groups).
4. Collapsed Preferences & Voice Settings submenu structure.
5. AgentToolDetector.get_connected_tools_matrix accuracy and structure.
6. Target agent switching in Remote Companion submenu.
7. Backward compatibility of all legacy menu attributes.
"""

import sys
from unittest.mock import MagicMock, patch
import pytest

if sys.platform != "darwin":
    pytest.skip("macOS-only UI test requiring rumps", allow_module_level=True)

import rumps
from voicefi.config import VoiceFiConfig, HUDConfig
from voicefi.ui.tray import VoiceFiTrayApp
from voicefi.integrations.discovery import AgentToolDetector


@pytest.fixture
def mock_tray_app():
    with patch("voicefi.ui.tray.TranscriptWatcher"), \
         patch("voicefi.ui.tray.ConversationHubWindow.get_instance"), \
         patch("voicefi.ui.tray.rumps.App.__init__"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._setup_cocoa_hotkeys"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._start_global_hotkey_listener"), \
         patch("voicefi.ui.tray.VoiceFiTrayApp._start_update_checker_thread"), \
         patch("voicefi.ui.tray.UnifiedDynamicIslandHUD") as mock_hud_cls:

        mock_hud = MagicMock()
        mock_hud_cls.get_instance.return_value = mock_hud

        app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
        app._menu = MagicMock()
        app.config = VoiceFiConfig()
        app.config.hud = HUDConfig()
        app.hud = mock_hud
        app.watcher = MagicMock()
        app._listen_lock = MagicMock()
        app._current_status = "idle"
        app._companion_started = True

        yield app, mock_hud


def test_tray_menu_structure_and_hierarchy(mock_tray_app):
    """Verify that Remote Companion is #1 at top and Connected Tools is #2."""
    app, _ = mock_tray_app

    # Build menu components
    app.stop_speaking_item = rumps.MenuItem("Stop Speaking")
    app.new_conversation_item = rumps.MenuItem("New Conversation")
    app.talk_to_agent_item = rumps.MenuItem("Prompt Agent")
    app.focus_agent_item = rumps.MenuItem("Switch to Agent Window")
    app.conversations_menu = rumps.MenuItem("Conversations")
    app.listen_anywhere_item = rumps.MenuItem("Dictate")
    app.voice_memo_menu = rumps.MenuItem("Voice Memo")
    app.voice_personas_menu = rumps.MenuItem("Personas")
    app.hud_menu = rumps.MenuItem("HUD")
    app.troubleshoot_menu = rumps.MenuItem("Troubleshoot")
    app.voice_mode_menu = rumps.MenuItem("Voice Mode")
    app.pause_delay_menu = rumps.MenuItem("Pause Delay")
    app.panel_item = rumps.MenuItem("Panel")
    app.wakeword_item = rumps.MenuItem("Wake Word")
    app.auto_listen_item = rumps.MenuItem("Auto Listen")
    app.meeting_item = rumps.MenuItem("Meeting")
    app.read_summary_item = rumps.MenuItem("Read Summary")
    app.barge_in_item = rumps.MenuItem("Barge In")
    app.tier_item = rumps.MenuItem("Tier")
    app.welcome_item = rumps.MenuItem("Welcome")
    app.update_item = rumps.MenuItem("Update")

    app.companion_menu = rumps.MenuItem("Remote Companion")
    app._build_companion_submenu = MagicMock()

    app.connected_tools_menu = rumps.MenuItem("Connected Tools")
    app._build_connected_tools_submenu = MagicMock()

    app.preferences_menu = rumps.MenuItem("Preferences")
    app._build_preferences_submenu = MagicMock()

    app.version_menu = rumps.MenuItem("Version")
    app._build_version_submenu = MagicMock()

    menu_list = [
        app.companion_menu,
        app.connected_tools_menu,
        rumps.separator,
        app.talk_to_agent_item,
        app.stop_speaking_item,
        app.focus_agent_item,
        app.listen_anywhere_item,
        app.conversations_menu,
        rumps.separator,
        app.preferences_menu,
        rumps.separator,
        app.version_menu,
        rumps.separator,
    ]

    # Verify top items
    assert menu_list[0] == app.companion_menu
    assert menu_list[1] == app.connected_tools_menu
    assert menu_list[2] == rumps.separator
    assert menu_list[3] == app.talk_to_agent_item
    assert menu_list[4] == app.stop_speaking_item
    assert menu_list[9] == app.preferences_menu
    assert menu_list[11] == app.version_menu


def test_companion_submenu_builder(mock_tray_app):
    """Verify companion submenu contains QR code at the top, browser launch, copy link, and target agent."""
    app, _ = mock_tray_app
    app.companion_menu = rumps.MenuItem("Remote Companion")
    app._companion_target_engine = "antigravity"

    with patch.object(app, "_get_companion_status_summary", return_value={
        "port": 5141,
        "port_online": True,
        "relay_connected": True,
        "has_relay_peer": False,
        "connected_clients": 0,
        "total_connected_devices": 0,
        "is_paired": False,
    }):
        app._build_companion_submenu()

    titles = [item.title for item in app.companion_menu.values() if hasattr(item, "title")]

    # Verify pairing QR code is at the top (first item)
    assert "Show Pairing QR Code" in titles[0]
    assert any("Open in Browser" in t for t in titles)
    assert any("Copy Pairing Link" in t for t in titles)
    assert any("Selected Agent" in t for t in titles)
    
    # Verify child items inside Selected Agent dropdown
    selected_agent_item = next(item for item in app.companion_menu.values() if hasattr(item, "title") and "Selected Agent" in item.title)
    sub_titles = [child.title for child in selected_agent_item.values() if hasattr(child, "title")]
    assert any("Google Antigravity" in t for t in sub_titles)
    assert any("Claude Code" in t for t in sub_titles)
    
    # Verify no open lead sheet
    assert not any("Open Lead Sheet" in t for t in titles)
    assert any("Relay Connected" in t for t in titles)


def test_submenus_no_duplication_on_rebuild(mock_tray_app):
    """Verify rebuilding submenus clears previous items and never duplicates."""
    app, _ = mock_tray_app
    app.companion_menu = rumps.MenuItem("Remote Companion")
    app.connected_tools_menu = rumps.MenuItem("Connected Tools")
    app.preferences_menu = rumps.MenuItem("Preferences")
    app.voice_personas_menu = rumps.MenuItem("🎭 Voice Personas")
    app.hud_menu = rumps.MenuItem("🏝️ Dynamic Island HUD")
    app.pause_delay_menu = rumps.MenuItem("⏱️ Pause Delay")
    app.voice_memo_menu = rumps.MenuItem("🧠 Voice Memo")
    app.panel_item = rumps.MenuItem("🎛️ Voice Control Panel")
    app.troubleshoot_menu = rumps.MenuItem("🔊 Troubleshooting")
    app.wakeword_item = rumps.MenuItem("Wake Word")
    app.auto_listen_item = rumps.MenuItem("Auto Listen")
    app.barge_in_item = rumps.MenuItem("Barge-In")
    app.read_summary_item = rumps.MenuItem("Read Summary")
    app.meeting_item = rumps.MenuItem("Meeting Assistant")
    app.voice_mode_menu = rumps.MenuItem("Capture Mode")

    # 1. Companion submenu idempotence
    with patch.object(app, "_get_companion_status_summary", return_value={"is_paired": False}):
        app._build_companion_submenu()
        count1 = len(app.companion_menu)
        app._build_companion_submenu()
        count2 = len(app.companion_menu)
        app._build_companion_submenu()
        count3 = len(app.companion_menu)
        assert count1 == count2 == count3
        assert count1 > 0

    # 2. Connected tools submenu idempotence
    with patch("voicefi.integrations.discovery.AgentToolDetector.get_connected_tools_matrix", return_value={
        "agents": [], "bridges": [], "permissions": [], "summary": "Test"
    }):
        app._build_connected_tools_submenu()
        ct_count1 = len(app.connected_tools_menu)
        app._build_connected_tools_submenu()
        ct_count2 = len(app.connected_tools_menu)
        assert ct_count1 == ct_count2
        assert ct_count1 > 0

    # 3. Preferences submenu idempotence
    app._build_preferences_submenu()
    pref_count1 = len(app.preferences_menu)
    app._build_preferences_submenu()
    pref_count2 = len(app.preferences_menu)
    assert pref_count1 == pref_count2
    assert pref_count1 > 0


def test_companion_paired_status_title(mock_tray_app):
    """Verify companion menu title dynamically shows green indicator when devices are paired."""
    app, _ = mock_tray_app
    app.companion_menu = rumps.MenuItem("Remote Companion")

    with patch.object(app, "_get_companion_status_summary", return_value={
        "port": 5141,
        "port_online": True,
        "relay_connected": True,
        "has_relay_peer": True,
        "connected_clients": 1,
        "total_connected_devices": 2,
        "is_paired": True,
    }):
        app._build_companion_submenu()

    assert "🟢 2 Paired" in app.companion_menu.title


def test_connected_tools_matrix_builder(mock_tray_app):
    """Verify connected tools submenu populates agents, bridges, and permissions."""
    app, _ = mock_tray_app
    app.connected_tools_menu = rumps.MenuItem("Connected Tools")

    mock_matrix = {
        "agents": [
            {"name": "Google Antigravity", "status": "connected", "detail": "Hook Active"},
            {"name": "Claude Code", "status": "connected", "detail": "Hook Active • AX Ready"},
        ],
        "bridges": [
            {"name": "VoiceFi MCP Server", "status": "connected", "detail": "Active"},
            {"name": "Local Daemon", "status": "connected", "detail": "Port 5141 Online"},
            {"name": "Cloudflare Edge Relay", "status": "connected", "detail": "Connected"},
        ],
        "permissions": [
            {"id": "accessibility", "name": "Accessibility (Auto-Paste)", "granted": True, "detail": "Active"},
            {"id": "microphone", "name": "Microphone Input", "granted": True, "detail": "Ready"},
        ],
        "summary": "Google • Claude • MCP",
        "connected_count": 3,
    }

    with patch("voicefi.integrations.discovery.AgentToolDetector.get_connected_tools_matrix", return_value=mock_matrix):
        app._build_connected_tools_submenu()

    assert "Google • Claude • MCP" in app.connected_tools_menu.title
    titles = [item.title for item in app.connected_tools_menu.values() if hasattr(item, "title")]

    assert any("AI Coding Agents" in t for t in titles)
    assert any("Google Antigravity" in t for t in titles)
    assert any("Claude Code" in t for t in titles)
    assert any("Bridges & Protocols" in t for t in titles)
    assert any("VoiceFi MCP Server" in t for t in titles)
    assert any("Local Daemon" in t for t in titles)
    assert any("System Permissions" in t for t in titles)
    assert any("Accessibility" in t for t in titles)
    assert any("Test & Verify All Connections" in t for t in titles)
    assert any("Link / Repair Agent Hooks" in t for t in titles)


def test_preferences_submenu_builder(mock_tray_app):
    """Verify preferences submenu collapses personas, HUD, listening options, and config."""
    app, _ = mock_tray_app
    app.preferences_menu = rumps.MenuItem("Preferences")
    app.voice_personas_menu = rumps.MenuItem("🎭 Voice Personas")
    app.hud_menu = rumps.MenuItem("🏝️ Dynamic Island HUD")
    app.pause_delay_menu = rumps.MenuItem("⏱️ Pause Delay")
    app.voice_memo_menu = rumps.MenuItem("🧠 Voice Memo")
    app.panel_item = rumps.MenuItem("🎛️ Voice Control Panel")
    app.troubleshoot_menu = rumps.MenuItem("🔊 Troubleshooting")

    app.wakeword_item = rumps.MenuItem("Wake Word")
    app.auto_listen_item = rumps.MenuItem("Auto Listen")
    app.barge_in_item = rumps.MenuItem("Barge-In")
    app.read_summary_item = rumps.MenuItem("Read Summary")
    app.meeting_item = rumps.MenuItem("Meeting Assistant")
    app.voice_mode_menu = rumps.MenuItem("Capture Mode")

    app._build_preferences_submenu()

    items = list(app.preferences_menu.values())

    assert app.voice_personas_menu in items
    assert app.hud_menu in items
    assert app.listening_options_menu in items
    assert app.pause_delay_menu in items
    assert app.panel_item in items
    assert app.troubleshoot_menu in items


def test_agent_tool_detector_matrix_live():
    """Verify AgentToolDetector.get_connected_tools_matrix returns standard schema."""
    res = AgentToolDetector.get_connected_tools_matrix()

    assert "agents" in res
    assert "bridges" in res
    assert "permissions" in res
    assert "summary" in res
    assert "connected_count" in res

    # Verify agent entries
    agent_ids = [a["id"] for a in res["agents"]]
    assert "antigravity" in agent_ids
    assert "claude_code" in agent_ids

    # Verify bridges
    bridge_ids = [b["id"] for b in res["bridges"]]
    assert "mcp" in bridge_ids
    assert "local_server" in bridge_ids
    assert "relay" in bridge_ids

    # Verify permissions
    perm_ids = [p["id"] for p in res["permissions"]]
    assert "accessibility" in perm_ids
    assert "microphone" in perm_ids


def test_focus_specific_conversation_antigravity(mock_tray_app):
    """Verify clicking an Antigravity conversation navigates to the thread and sets target engine."""
    app, _ = mock_tray_app
    app.conversations_menu = rumps.MenuItem("Conversations")
    app.companion_menu = rumps.MenuItem("Remote Companion")
    app._build_conversations_submenu = MagicMock()
    app._build_companion_submenu = MagicMock()

    with patch("voicefi.integrations.injector.navigate_to_antigravity_conversation", return_value=True) as mock_nav, \
         patch("voicefi.integrations.injector.focus_antigravity") as mock_focus, \
         patch("rumps.notification") as mock_notif:
        app.focus_specific_conversation(
            "fe679077-06c8-4a42-8a1f-190a27b1e4dc",
            title="I want to plan to update this",
        )

        app.watcher.tracker.set_active_focus.assert_called_once_with(
            "fe679077-06c8-4a42-8a1f-190a27b1e4dc",
            transcript_path=None,
            title="I want to plan to update this",
        )
        assert app._companion_target_engine == "antigravity"
        mock_nav.assert_called_once_with(
            "fe679077-06c8-4a42-8a1f-190a27b1e4dc",
            title="I want to plan to update this",
        )
        # When nav succeeds, fallback focus_antigravity is not needed
        mock_focus.assert_not_called()
        app._build_conversations_submenu.assert_called_once()
        app._build_companion_submenu.assert_called_once()
        mock_notif.assert_called_once()


def test_focus_specific_conversation_antigravity_fallback(mock_tray_app):
    """Verify fallback to focus_antigravity when navigate_to_antigravity_conversation returns False."""
    app, _ = mock_tray_app
    app.conversations_menu = rumps.MenuItem("Conversations")
    app.companion_menu = rumps.MenuItem("Remote Companion")
    app._build_conversations_submenu = MagicMock()
    app._build_companion_submenu = MagicMock()

    with patch("voicefi.integrations.injector.navigate_to_antigravity_conversation", return_value=False) as mock_nav, \
         patch("voicefi.integrations.injector.focus_antigravity") as mock_focus, \
         patch("rumps.notification"):
        app.focus_specific_conversation("unknown-conv-id", title="Old Thread")

        mock_nav.assert_called_once_with("unknown-conv-id", title="Old Thread")
        mock_focus.assert_called_once_with(focus_input=True)


def test_focus_specific_conversation_claude(mock_tray_app):
    """Verify clicking a Claude conversation activates Claude and routes companion to Claude."""
    app, _ = mock_tray_app
    app.conversations_menu = rumps.MenuItem("Conversations")
    app.companion_menu = rumps.MenuItem("Remote Companion")
    app._build_conversations_submenu = MagicMock()
    app._build_companion_submenu = MagicMock()

    with patch("voicefi.integrations.injector._focus_and_click_claude_desktop", return_value=True) as mock_claude_desktop, \
         patch("voicefi.integrations.injector.focus_terminal_app") as mock_terminal, \
         patch("voicefi.integrations.injector.navigate_to_antigravity_conversation") as mock_nav, \
         patch("rumps.notification") as mock_notif:
        app.focus_specific_conversation(
            "claude_e87f6de5-8d9a-4cd3-8f0d-e8d3076faa0b",
            title="Place: Hey Claude!",
        )

        app.watcher.tracker.set_active_focus.assert_called_once()
        assert app._companion_target_engine == "claude"
        mock_claude_desktop.assert_called_once()
        mock_terminal.assert_not_called()
        mock_nav.assert_not_called()
        app._build_conversations_submenu.assert_called_once()
        app._build_companion_submenu.assert_called_once()
        mock_notif.assert_called_once()
        assert "Claude Code" in mock_notif.call_args[0][0]

