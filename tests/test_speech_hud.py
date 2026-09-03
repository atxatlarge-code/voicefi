"""
Unit tests for AgentSpeechHUD (Unified Dynamic Island Adapter).
"""

from unittest.mock import MagicMock, patch
import pytest
from voicefi.ui.speech_hud import AgentSpeechHUD, AVATAR_ICONS
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
from voicefi.config import VoiceFiConfig, AntigravityConfig


def test_speech_hud_singleton():
    """Test AgentSpeechHUD singleton behavior and unification."""
    hud1 = AgentSpeechHUD.get_instance()
    hud2 = AgentSpeechHUD.get_instance()
    unified = UnifiedDynamicIslandHUD.get_instance()
    assert hud1 is hud2
    assert hud1 is unified
    assert hud1._panel is not None


def test_speech_hud_avatar_resolution():
    """Test avatar resolution for various agent names and personas."""
    hud = AgentSpeechHUD.get_instance()

    assert hud._resolve_avatar("antigravity", "Christopher") == "🧔"
    assert hud._resolve_avatar("antigravity", "Aria") == "⚡"
    assert hud._resolve_avatar("researcher", None) == "🔍"
    assert hud._resolve_avatar("debugger", None) == "🐞"
    assert hud._resolve_avatar("architect", None) == "📐"
    assert hud._resolve_avatar("unknown_agent", None) == "🤖"


def test_speech_hud_show_and_update():
    """Test show_speech, update_text, finish_speech, and hide transitions on unified HUD."""
    hud = AgentSpeechHUD.get_instance()

    hud._panel = MagicMock()
    hud._root_view = MagicMock()
    hud._effect_view = MagicMock()
    hud._avatar_box = MagicMock()
    hud._avatar_lbl = MagicMock()
    hud._app_box = MagicMock()
    hud._app_lbl = MagicMock()
    hud._app_img = MagicMock()
    hud._title_lbl = MagicMock()
    hud._tag_lbl = MagicMock()
    hud._body_lbl = MagicMock()

    # 1. Show speech
    test_msg = "Refactoring completed with zero syntax errors. Ready to merge."
    hud.show_speech(
        test_msg,
        agent_name="Antigravity",
        persona_name="Christopher",
        is_speaking=True,
        position="top_center",
    )

    hud._body_lbl.setStringValue_.assert_called_with(f'"{test_msg}"')
    hud._title_lbl.setStringValue_.assert_called_with("Antigravity")
    hud._tag_lbl.setStringValue_.assert_called_with("Christopher [Speaking • ⇥ Tab to focus]")
    hud._panel.orderFrontRegardless.assert_called()

    # 2. Update text during streaming
    hud._panel.isVisible.return_value = True
    updated_msg = "Refactoring completed with zero syntax errors. Running tests..."
    hud.update_text(updated_msg)
    hud._body_lbl.setStringValue_.assert_called_with(updated_msg)

    # 3. Finish speech and hide
    hud.finish_speech(linger_seconds=0.1)
    if hud._hide_timer:
        hud._hide_timer.cancel()
    assert not hud.is_speaking

    # 4. Immediate hide (non-persistent)
    hud.persistent = False
    hud.hide()
    hud._panel.orderOut_.assert_called_with(None)
    UnifiedDynamicIslandHUD._instance = None


def test_speech_hud_config_integration():
    """Test configuration fields for speech pop-up."""
    cfg = VoiceFiConfig()
    assert cfg.antigravity.show_speech_popup is True
    assert cfg.antigravity.speech_popup_linger_seconds == 3.0
    assert cfg.antigravity.speech_popup_position == "top_right"

    cfg.antigravity.show_speech_popup = False
    cfg.antigravity.speech_popup_position = "bottom_right"
    assert cfg.antigravity.show_speech_popup is False
    assert cfg.antigravity.speech_popup_position == "bottom_right"
