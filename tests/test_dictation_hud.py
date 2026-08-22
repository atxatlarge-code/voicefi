"""
Unit tests for DictationHUD and floating status capsule.
"""

from unittest.mock import MagicMock, patch
import pytest
from voicegency.ui.dictation_hud import DictationHUD


def test_dictation_hud_singleton():
    """Test DictationHUD singleton behavior."""
    DictationHUD._instance = None
    hud1 = DictationHUD.get_instance()
    hud2 = DictationHUD.get_instance()
    assert hud1 is hud2
    assert hud1._panel is not None


def test_dictation_hud_states():
    """Test show_listening, show_transcribing, show_done, and hide state transitions."""
    DictationHUD._instance = None
    hud = DictationHUD.get_instance()

    with patch.object(hud, "_position_top_center") as mock_pos:
        hud._panel = MagicMock()
        hud._label = MagicMock()

        # Listening
        hud.show_listening()
        hud._label.setStringValue_.assert_called_with("🔴 Listening... (Speak)")
        hud._panel.orderFrontRegardless.assert_called()

        # Transcribing
        hud.show_transcribing()
        hud._label.setStringValue_.assert_called_with("⏳ Transcribing...")

        # Done
        hud.show_done(preview_text="Hello world dictation test")
        hud._label.setStringValue_.assert_called_with("✅ Hello world dictatio...")

        # Hide
        hud._panel.isVisible.return_value = True
        hud.hide()
        hud._panel.orderOut_.assert_called_with(None)
