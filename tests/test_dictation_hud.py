"""
Unit tests for DictationHUD (Unified Dynamic Island Adapter).
"""

from unittest.mock import MagicMock, patch
import pytest
from voicefi.ui.dictation_hud import DictationHUD
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD


def test_dictation_hud_singleton():
    """Test DictationHUD singleton behavior and unification."""
    hud1 = DictationHUD.get_instance()
    hud2 = DictationHUD.get_instance()
    unified = UnifiedDynamicIslandHUD.get_instance()
    assert hud1 is hud2
    assert hud1 is unified
    assert hud1._panel is not None


def test_dictation_hud_states():
    """Test show_listening, show_transcribing, show_done, and hide state transitions."""
    hud = DictationHUD.get_instance()

    with patch.object(hud, "_position_top_center") as mock_pos:
        hud._panel = MagicMock()
        hud._root_view = MagicMock()
        hud._effect_view = MagicMock()
        hud._avatar_box = MagicMock()
        hud._avatar_lbl = MagicMock()
        hud._title_lbl = MagicMock()
        hud._tag_lbl = MagicMock()
        hud._body_lbl = MagicMock()

        # Listening
        hud.show_listening()
        hud._tag_lbl.setStringValue_.assert_called_with("🔴 Recording (Live Mic)")
        hud._panel.orderFrontRegardless.assert_called()

        # Transcribing
        hud.show_transcribing()
        hud._tag_lbl.setStringValue_.assert_called_with("• Transcribing...")

        # Done
        hud.show_done(preview_text="Hello world dictation test")
        hud._tag_lbl.setStringValue_.assert_called_with("• Done")

        # Hide
        hud.persistent = False
        hud._panel.isVisible.return_value = True
        hud.hide()
        hud._panel.orderOut_.assert_called_with(None)
