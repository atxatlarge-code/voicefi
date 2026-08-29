"""
Unit tests for Native macOS HUD Quick Controls and Fibonacci Pause Delay scale.
"""

import os
import pytest
from unittest.mock import MagicMock, patch

from voicefi.config import load_config, save_config, FIBONACCI_PAUSE_DELAYS
from voicefi.ui.quick_controls import HUDQuickControlsPanel


def test_fibonacci_pause_delays_scale():
    """Verify Fibonacci pause delay presets match the required 1s, 2s, 3s, 5s, 8s, 11s scale."""
    assert FIBONACCI_PAUSE_DELAYS == [1.0, 2.0, 3.0, 5.0, 8.0, 11.0]


def test_quick_controls_singleton():
    """Verify HUDQuickControlsPanel is a singleton."""
    panel1 = HUDQuickControlsPanel.get_instance()
    panel2 = HUDQuickControlsPanel.get_instance()
    assert panel1 is panel2
    assert panel1.PANEL_WIDTH == 480.0
    assert panel1.PANEL_HEIGHT == 460.0


def test_quick_controls_proactive_listening_toggle(tmp_path, monkeypatch):
    """Verify toggling ProActive Listening syncs across proactive and agent configs."""
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setenv("VOICEFI_CONFIG", str(cfg_file))

    panel = HUDQuickControlsPanel.get_instance()

    mock_sender = MagicMock()
    mock_sender.selectedSegment.return_value = 0  # ON
    panel._on_proactive_toggle(mock_sender)

    cfg = load_config()
    assert cfg.proactive.feedback_loop.enabled is True
    assert cfg.antigravity.auto_listen is True

    mock_sender.selectedSegment.return_value = 1  # OFF
    panel._on_proactive_toggle(mock_sender)

    cfg = load_config()
    assert cfg.proactive.feedback_loop.enabled is False
    assert cfg.antigravity.auto_listen is False


def test_quick_controls_barge_in_toggle(tmp_path, monkeypatch):
    """Verify toggling Active Barge-In properly updates config."""
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setenv("VOICEFI_CONFIG", str(cfg_file))

    panel = HUDQuickControlsPanel.get_instance()

    mock_sender = MagicMock()
    mock_sender.selectedSegment.return_value = 0  # AUTO
    panel._on_barge_in_toggle(mock_sender)
    assert load_config().vad.barge_in == "auto"

    mock_sender.selectedSegment.return_value = 1  # ON
    panel._on_barge_in_toggle(mock_sender)
    assert load_config().vad.barge_in is True

    mock_sender.selectedSegment.return_value = 2  # OFF
    panel._on_barge_in_toggle(mock_sender)
    assert load_config().vad.barge_in is False


def test_quick_controls_pause_delay_fibonacci(tmp_path, monkeypatch):
    """Verify Fibonacci pause delay selections (1s, 2s, 3s, 5s, 8s, 11s) update silence duration."""
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setenv("VOICEFI_CONFIG", str(cfg_file))

    panel = HUDQuickControlsPanel.get_instance()
    mock_sender = MagicMock()

    for idx, expected_sec in enumerate(FIBONACCI_PAUSE_DELAYS):
        mock_sender.selectedSegment.return_value = idx
        panel._on_pause_delay_toggle(mock_sender)
        assert load_config().vad.silence_duration == expected_sec


def test_quick_controls_auto_send_toggle(tmp_path, monkeypatch):
    """Verify auto-send vs review & edit prompt mode toggle."""
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setenv("VOICEFI_CONFIG", str(cfg_file))

    panel = HUDQuickControlsPanel.get_instance()
    mock_sender = MagicMock()

    mock_sender.selectedSegment.return_value = 0  # Auto
    panel._on_auto_send_toggle(mock_sender)
    assert load_config().hud.auto_send is True

    mock_sender.selectedSegment.return_value = 1  # Review
    panel._on_auto_send_toggle(mock_sender)
    assert load_config().hud.auto_send is False


def test_quick_controls_spoken_summaries_toggle(tmp_path, monkeypatch):
    """Verify spoken summaries mute/unmute toggle."""
    cfg_file = tmp_path / "config.yaml"
    monkeypatch.setenv("VOICEFI_CONFIG", str(cfg_file))

    panel = HUDQuickControlsPanel.get_instance()
    mock_sender = MagicMock()

    mock_sender.selectedSegment.return_value = 0  # ON
    panel._on_spoken_summaries_toggle(mock_sender)
    assert load_config().antigravity.read_summary_aloud is True

    mock_sender.selectedSegment.return_value = 1  # MUTE
    panel._on_spoken_summaries_toggle(mock_sender)
    assert load_config().antigravity.read_summary_aloud is False
