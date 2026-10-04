"""
Unit tests for PalHighlightOverlay focused window and screen halo presentation.
"""

from unittest.mock import MagicMock, patch
import pytest

from voicefi.ui.screen_highlight import PalHighlightOverlay


class TestPalHighlightOverlay:
    """Test overlay initialization, styles, and focused window coordinate conversion."""

    def test_singleton_instance(self):
        inst1 = PalHighlightOverlay.get_instance()
        inst2 = PalHighlightOverlay.get_instance()
        assert inst1 is inst2

    def test_colors_configuration(self):
        overlay = PalHighlightOverlay.get_instance()
        assert "hearing" in overlay.COLORS
        assert "training" in overlay.COLORS
        assert "executing" in overlay.COLORS
        assert "screen" in overlay.COLORS

    @patch("voicefi.ui.screen_highlight.is_headless", return_value=True)
    def test_show_and_hide_calls_in_headless(self, mock_headless):
        overlay = PalHighlightOverlay.get_instance()
        overlay.show_for_focused_window(color_type="hearing")
        assert overlay._current_mode == "focused_window"
        assert overlay._current_color_type == "hearing"

        overlay.show_screen_perimeter(color_type="training")
        assert overlay._current_mode == "screen"
        assert overlay._current_color_type == "training"

        overlay.hide()
        assert overlay._is_visible is False
