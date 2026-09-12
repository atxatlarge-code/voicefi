"""
Unit tests for VoiceFi Quick Prompt Bar (Control+Space floating pill bar).
Tests:
- Subclassing & AppKit Key Window capabilities
- Target action callbacks and text field delegate handling (Enter/Escape)
- Agent selection, dynamic placeholders, and config persistence
- Multi-agent dispatch routing (Antigravity, Claude Code, Gemini Flash, ChatGPT)
- Hotkey configuration defaults and validation
"""

import time
from unittest.mock import MagicMock, patch
import pytest

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
    with patch("voicefi.integrations.injector.inject_text_to_claude") as mock_inject, \
         patch("voicefi.integrations.injector.focus_app_by_name") as mock_focus:
        bar.dispatch_to_agent("Refactor audio buffer", "claude")
        mock_inject.assert_called_once_with(text="Refactor audio buffer", auto_submit=True)
        mock_focus.assert_called_once_with("Claude")


def test_dispatch_to_agent_chatgpt():
    """Verify default dispatch injects prompt to ChatGPT Desktop."""
    bar = QuickPromptBarWindow.get_instance()
    with patch("voicefi.integrations.injector.inject_text_to_chatgpt") as mock_inject, \
         patch("voicefi.integrations.injector.focus_app_by_name") as mock_focus:
        bar.dispatch_to_agent("Summarize paper", "chatgpt")
        mock_inject.assert_called_once_with(text="Summarize paper", auto_submit=True)
        mock_focus.assert_called_once_with("ChatGPT")


def test_global_hotkey_config_defaults():
    """Verify GlobalHotkeyConfig includes quick_bar fields with correct defaults."""
    cfg = GlobalHotkeyConfig()
    assert cfg.quick_bar_hotkey == "<ctrl>+space"
    assert cfg.quick_bar_agent == "antigravity"
    assert cfg.quick_bar_enabled is True


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
