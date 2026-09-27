"""
Unit tests for VoiceFi Quick Prompt Bar (Control+Space floating pill bar).
Tests:
- Subclassing & AppKit Key Window capabilities
- Target action callbacks and text field delegate handling (Enter/Escape)
- Agent selection, dynamic placeholders, and config persistence
- Multi-agent dispatch routing (Antigravity, Claude Code, Gemini Flash, ChatGPT)
- Hotkey configuration defaults and validation
"""

import sys
import time
from unittest.mock import MagicMock, patch
import pytest

if sys.platform != "darwin":
    pytest.skip("macOS-only UI test requiring AppKit", allow_module_level=True)

from voicefi.config import load_config, GlobalHotkeyConfig
from voicefi.ui.quick_bar import (
    QuickBarPanel,
    QuickBarActionTarget,
    QuickBarTextDelegate,
    QuickPromptBarWindow,
    SUPPORTED_AGENTS,
)


@pytest.fixture(autouse=True)
def reset_quick_bar_singleton():
    QuickPromptBarWindow._instance = None
    yield
    if QuickPromptBarWindow._instance is not None:
        try:
            if QuickPromptBarWindow._instance._panel:
                QuickPromptBarWindow._instance.hide()
                QuickPromptBarWindow._instance._panel.orderOut_(None)
                QuickPromptBarWindow._instance._panel.close()
        except Exception:
            pass
        QuickPromptBarWindow._instance = None


def test_quick_bar_panel_key_window():
    """Verify QuickBarPanel allows borderless panels to become key & main windows."""
    panel = QuickBarPanel.alloc().init()
    assert panel.canBecomeKeyWindow() is True
    assert panel.canBecomeMainWindow() is True


def test_quick_bar_action_target():
    """Verify QuickBarActionTarget executes its callback when button clicked."""
    called = []
    target = QuickBarActionTarget.alloc().initWithCallback_(lambda: called.append("clicked"))
    target.buttonClicked_(None)
    assert called == ["clicked"]


def test_quick_bar_text_delegate_keys():
    """Verify QuickBarTextDelegate intercepts Enter to submit and Escape to dismiss."""
    mock_bar = MagicMock()
    delegate = QuickBarTextDelegate.alloc().initWithBar_(mock_bar)

    # 1. Enter key (insertNewline:)
    res_enter = delegate.control_textView_doCommandBySelector_(None, None, "insertNewline:")
    assert res_enter is True
    assert mock_bar._on_submit_action.called

    # 2. Escape key (cancelOperation:)
    res_esc = delegate.control_textView_doCommandBySelector_(None, None, "cancelOperation:")
    assert res_esc is True
    assert mock_bar.hide.called

    # 3. Arbitrary other selector passes through
    res_other = delegate.control_textView_doCommandBySelector_(None, None, "moveUp:")
    assert res_other is False


def test_quick_bar_singleton():
    """Verify QuickPromptBarWindow implements the singleton pattern."""
    bar1 = QuickPromptBarWindow.get_instance()
    bar2 = QuickPromptBarWindow.get_instance()
    assert bar1 is bar2


def test_supported_agents_registry():
    """Verify all required agents are registered with complete metadata."""
    agent_ids = [a["id"] for a in SUPPORTED_AGENTS]
    assert "antigravity" in agent_ids
    assert "claude" in agent_ids
    assert "flash" in agent_ids
    assert "chatgpt" in agent_ids

    for agent in SUPPORTED_AGENTS:
        assert "name" in agent
        assert "icon" in agent
        assert "placeholder" in agent
        assert len(agent["placeholder"]) > 0


def test_select_agent():
    """Verify selecting an agent updates state and placeholder."""
    bar = QuickPromptBarWindow.get_instance()
    bar._agent_btn = MagicMock()
    bar._text_field = MagicMock()

    with patch("voicefi.ui.quick_bar.save_config") as mock_save:
        bar.select_agent("claude")
        assert bar.current_agent_id == "claude"
        assert bar._agent_btn.setTitle_.called
        assert bar._text_field.setPlaceholderString_.called
        assert mock_save.called


def test_submit_action_custom_callback():
    """Verify _on_submit_action invokes custom callback when provided."""
    submitted = []

    def _on_sub(text, agent_id):
        submitted.append((text, agent_id))

    bar = QuickPromptBarWindow.get_instance(on_submit=_on_sub)
    bar._text_field = MagicMock()
    bar._text_field.stringValue.return_value = "Test custom prompt"
    bar.current_agent_id = "flash"

    bar._on_submit_action()
    assert len(submitted) == 1
    assert submitted[0] == ("Test custom prompt", "flash")


def test_dispatch_to_agent_antigravity():
    """Verify default dispatch injects prompt to active Antigravity session."""
    bar = QuickPromptBarWindow.get_instance()
    with patch("voicefi.integrations.injector.inject_text_to_antigravity") as mock_inject:
        mock_inject.return_value = True
        bar.dispatch_to_agent("Build authentication flow", "antigravity")
        mock_inject.assert_called_once_with(
            "Build authentication flow",
            submit_enter=True,
            new_conversation=False,
        )


def test_dispatch_to_agent_antigravity_new_conversation():
    """Verify dispatch with new_conversation=True creates new Antigravity session."""
    bar = QuickPromptBarWindow.get_instance()
    with patch("voicefi.integrations.injector.create_new_antigravity_conversation") as mock_create:
        bar.dispatch_to_agent("Build authentication flow", "antigravity", new_conversation=True)
        mock_create.assert_called_once_with(prompt="Build authentication flow")


def test_dispatch_to_agent_claude():
    """Verify default dispatch injects prompt to Claude Code."""
    bar = QuickPromptBarWindow.get_instance()
    with (
        patch("voicefi.integrations.injector.inject_text_to_claude") as mock_inject,
        patch("voicefi.integrations.injector.focus_app_by_name") as mock_focus,
    ):
        bar.dispatch_to_agent("Refactor audio buffer", "claude")
        mock_inject.assert_called_once_with(text="Refactor audio buffer", auto_submit=True)
        mock_focus.assert_called_once_with("Claude")


def test_dispatch_to_agent_chatgpt():
    """Verify default dispatch injects prompt to ChatGPT Desktop."""
    bar = QuickPromptBarWindow.get_instance()
    with (
        patch("voicefi.integrations.injector.inject_text_to_chatgpt") as mock_inject,
        patch("voicefi.integrations.injector.focus_app_by_name") as mock_focus,
    ):
        bar.dispatch_to_agent("Summarize paper", "chatgpt")
        mock_inject.assert_called_once_with(text="Summarize paper", auto_submit=True)
        mock_focus.assert_called_once_with("ChatGPT")


def test_global_hotkey_config_defaults():
    """Verify GlobalHotkeyConfig includes quick_bar fields with correct defaults."""
    cfg = GlobalHotkeyConfig()
    assert cfg.quick_bar_hotkey == "<ctrl>+space"
    assert cfg.quick_bar_agent == "antigravity"
    assert cfg.quick_bar_enabled is True
    assert cfg.quick_bar_focus_target is True


def test_quick_bar_toggle_behavior():
    """Verify toggle() switches visibility correctly."""
    bar = QuickPromptBarWindow.get_instance()
    bar._panel = MagicMock()

    # When not visible, toggle calls show
    bar._panel.isVisible.return_value = False
    with patch.object(bar, "show") as mock_show:
        bar.toggle()
        mock_show.assert_called_once()

    # When visible, toggle calls hide
    bar._panel.isVisible.return_value = True
    with patch.object(bar, "hide") as mock_hide:
        bar.toggle()
        mock_hide.assert_called_once()


def test_get_agent_icon_resolution():
    """Verify get_agent_icon resolves valid native brand logos for all supported agents."""
    bar = QuickPromptBarWindow.get_instance()
    for agent in SUPPORTED_AGENTS:
        icon = bar.get_agent_icon(agent["id"], size=18)
        assert icon is not None, f"Failed to resolve icon for agent: {agent['id']}"
        assert icon.isValid() is True
        assert icon.size().width == 18.0
        assert icon.size().height == 18.0


def test_agent_menu_logos_and_clean_titles():
    """Verify agent menu items display brand logos without emojis in the title."""
    bar = QuickPromptBarWindow.get_instance()
    menu = bar._build_agent_menu()

    assert menu.numberOfItems() == len(SUPPORTED_AGENTS)

    for i, agent in enumerate(SUPPORTED_AGENTS):
        item = menu.itemAtIndex_(i)
        assert item.title() == agent["name"]
        # Ensure no emoji prefixes remain in the titles
        for emoji in ["🤖", "🎭", "✨", "⚡", "✳️"]:
            assert emoji not in item.title()
        # Verify brand logo NSImage is attached to each menu item
        assert item.image() is not None
        assert item.image().isValid() is True


def test_quick_bar_buttons_and_layout_symmetry():
    """Verify right-side buttons have dedicated mic dictation and send arrow roles with symmetric layout."""
    bar = QuickPromptBarWindow.get_instance()
    # Force panel creation for layout inspection
    bar._build_panel()

    assert bar._mic_btn is not None
    assert bar._action_btn is not None
    assert bar._vifi_btn is bar._mic_btn

    # Verify tooltips clearly distinguish Voice Dictation from Send Prompt
    assert "Voice Dictation" in bar._mic_btn.toolTip()
    assert "Send Prompt" in bar._action_btn.toolTip()

    # Verify layout geometry: perfect vertical center line at Y=26.0 (container height 52.0)
    assert bar._plus_btn.frame().origin.y + (bar._plus_btn.frame().size.height / 2.0) == 26.0
    assert bar._mic_btn.frame().origin.y + (bar._mic_btn.frame().size.height / 2.0) == 26.0
    assert bar._action_btn.frame().origin.y + (bar._action_btn.frame().size.height / 2.0) == 26.0
    assert bar._agent_btn.frame().origin.y + (bar._agent_btn.frame().size.height / 2.0) == 26.0
    assert bar._text_field.frame().origin.y + (bar._text_field.frame().size.height / 2.0) == 26.0

    # Symmetric margins: 12px on left, 12px on right
    assert bar._plus_btn.frame().origin.x == 12.0
    right_edge = bar._action_btn.frame().origin.x + bar._action_btn.frame().size.width
    assert bar.STANDARD_WIDTH - right_edge == 12.0


def test_quick_bar_voice_toggle_and_callback():
    """Verify start_voice_input and stop_voice_input toggle state and trigger callback."""
    events = []
    bar = QuickPromptBarWindow.get_instance(on_voice_toggle=lambda active: events.append(active))
    bar._text_field = MagicMock()
    bar._text_field.stringValue.return_value = "Existing prompt"

    with (
        patch("voicefi.audio.recorder.AudioRecorder"),
        patch("threading.Thread") as mock_thread,
        patch("voicefi.audio.chimes.play_chime"),
    ):
        bar.start_voice_input()
        assert bar.is_voice_active is True
        assert bar._initial_text_before_voice == "Existing prompt"
        assert True in events

        bar.stop_voice_input()
        assert bar.is_voice_active is False
        assert False in events


def test_quick_bar_submit_while_recording_defers_and_dispatches():
    """Verify submitting while recording sets _pending_submit and defers dispatch until speech finalized."""
    bar = QuickPromptBarWindow.get_instance()
    bar._text_field = MagicMock()
    bar._text_field.stringValue.return_value = "Initial speech fragment"
    bar.is_voice_active = True

    with patch.object(bar, "stop_voice_input") as mock_stop:
        bar._on_submit_action(new_conversation=True)
        assert bar._pending_submit == {"new_conversation": True, "silent_send": False}
        mock_stop.assert_called_once()


def test_quick_bar_panel_key_equivalent_shortcuts():
    """Verify panel intercepts Cmd+D, Ctrl+M, and Ctrl+Space to toggle voice dictation."""
    bar = QuickPromptBarWindow.get_instance()
    panel = QuickBarPanel.alloc().init()

    with patch.object(bar, "toggle_voice_input") as mock_toggle:
        # Mock NSEvent
        # 1. Cmd+D (vk 2, flags 0x100000)
        ev_cmd_d = MagicMock()
        ev_cmd_d.keyCode.return_value = 2
        ev_cmd_d.modifierFlags.return_value = 0x100000
        assert panel.performKeyEquivalent_(ev_cmd_d) is True
        assert mock_toggle.call_count == 1

        # 2. Ctrl+M (vk 46, flags 0x40000)
        ev_ctrl_m = MagicMock()
        ev_ctrl_m.keyCode.return_value = 46
        ev_ctrl_m.modifierFlags.return_value = 0x40000
        assert panel.performKeyEquivalent_(ev_ctrl_m) is True
        assert mock_toggle.call_count == 2

        # 3. Ctrl+Space (vk 49, flags 0x40000)
        ev_ctrl_space = MagicMock()
        ev_ctrl_space.keyCode.return_value = 49
        ev_ctrl_space.modifierFlags.return_value = 0x40000
        assert panel.performKeyEquivalent_(ev_ctrl_space) is True
        assert mock_toggle.call_count == 3


def test_tray_toggle_quick_bar_toggles_voice_when_window_is_key():
    """Verify tray.toggle_quick_bar delegates to quick_bar.toggle_voice_input when window is key."""
    from voicefi.ui.tray import VoiceFiTrayApp

    tray = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
    tray.quick_bar = MagicMock()
    mock_panel = MagicMock()
    tray.quick_bar._panel = mock_panel

    # Case 1: Panel is visible and key window -> toggle_voice_input
    mock_panel.isVisible.return_value = True
    mock_panel.isKeyWindow.return_value = True
    tray.toggle_quick_bar()
    tray.quick_bar.toggle_voice_input.assert_called_once()
    assert not tray.quick_bar.toggle.called

    # Case 2: Panel is not visible -> toggle
    mock_panel.isVisible.return_value = False
    mock_panel.isKeyWindow.return_value = False
    tray._last_quick_bar_toggle_time = 0.0
    tray.quick_bar.toggle_voice_input.reset_mock()
    tray.toggle_quick_bar()
    tray.quick_bar.toggle.assert_called_once()
    assert not tray.quick_bar.toggle_voice_input.called


def test_quick_bar_silent_send_dispatches_cleanly():
    """Verify silent_send=True attempts IPC and restores focus to previous application."""
    bar = QuickPromptBarWindow.get_instance()
    bar._prev_active_app = MagicMock()

    with (
        patch("voicefi.integrations.injector.send_message_to_antigravity") as mock_ipc,
        patch.object(bar, "restore_previous_focus") as mock_restore,
    ):
        mock_ipc.return_value = True
        bar.dispatch_to_agent("Silent background query", "antigravity", silent_send=True)
        mock_ipc.assert_called_once_with(text="Silent background query")
        mock_restore.assert_called_once()


def test_quick_bar_text_delegate_option_enter_silent_send():
    """Verify QuickBarTextDelegate detects Option modifier and triggers silent_send."""
    mock_bar = MagicMock()
    delegate = QuickBarTextDelegate.alloc().initWithBar_(mock_bar)

    mock_event = MagicMock()
    # 0x80000 is NSEventModifierFlagOption
    mock_event.modifierFlags.return_value = 0x80000

    with patch("voicefi.ui.quick_bar._get_current_event", return_value=mock_event):
        res = delegate.control_textView_doCommandBySelector_(None, None, "insertNewline:")
        assert res is True
        mock_bar._on_submit_action.assert_called_once_with(new_conversation=False, silent_send=True)
