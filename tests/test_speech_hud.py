"""
Unit tests for AgentSpeechHUD (Native macOS Floating Speech Pop-up).
"""

from unittest.mock import MagicMock, patch
import pytest
from voicegency.ui.speech_hud import AgentSpeechHUD, AVATAR_ICONS
from voicegency.config import VoicegencyConfig, AntigravityConfig


def test_speech_hud_singleton():
    """Test AgentSpeechHUD singleton behavior."""
    hud1 = AgentSpeechHUD.get_instance()
    hud2 = AgentSpeechHUD.get_instance()
    assert hud1 is hud2
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
    """Test show_speech, update_text, finish_speech, and hide transitions."""
    hud = AgentSpeechHUD.get_instance()

    hud._panel = MagicMock()
    hud._root_view = MagicMock()
    hud._visual_effect = MagicMock()
    hud._avatar_label = MagicMock()
    hud._header_label = MagicMock()
    hud._persona_label = MagicMock()
    hud._speech_label = MagicMock()

    with patch.object(hud, "_start_wave_animation"):
        # 1. Show speech
        test_msg = "Refactoring completed with zero syntax errors. Ready to merge."
        hud.show_speech(
            test_msg,
            agent_name="Antigravity",
            persona_name="Christopher",
            is_speaking=True,
            position="top_center",
        )

        hud._speech_label.setStringValue_.assert_called_with(test_msg)
        hud._header_label.setStringValue_.assert_called_with("Antigravity")
        hud._persona_label.setStringValue_.assert_called_with("• Christopher")
        hud._avatar_label.setStringValue_.assert_called_with("🧔")
        hud._panel.orderFrontRegardless.assert_called()

    # 2. Update text during streaming
    hud._panel.isVisible.return_value = True
    updated_msg = "Refactoring completed with zero syntax errors. Running tests..."
    hud.update_text(updated_msg)
    hud._speech_label.setStringValue_.assert_called_with(updated_msg)

    # 3. Finish speech and hide
    hud.finish_speech(linger_seconds=0.1)
    if hud._hide_timer:
        hud._hide_timer.cancel()
    assert not hud._is_speaking

    # 4. Immediate hide
    hud.hide()
    hud._panel.orderOut_.assert_called_with(None)


def test_speech_hud_config_integration():
    """Test configuration fields for speech pop-up."""
    cfg = VoicegencyConfig()
    assert cfg.antigravity.show_speech_popup is True
    assert cfg.antigravity.speech_popup_linger_seconds == 3.0
    assert cfg.antigravity.speech_popup_position == "top_center"

    cfg.antigravity.show_speech_popup = False
    cfg.antigravity.speech_popup_position = "top_right"
    assert cfg.antigravity.show_speech_popup is False
    assert cfg.antigravity.speech_popup_position == "top_right"
