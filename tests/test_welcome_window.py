"""
Tests for VoiceFi Welcome & License Activation Window.
Verifies clipboard auto-detection, Ed25519 validation, and activation state changes.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from voicefi.config import load_config, save_config, VoiceFiConfig
from voicefi.license import generate_license_key, verify_license_key, FeatureGate
from voicefi.ui.welcome import VoiceFiWelcomeWindow


def test_welcome_window_creation(tmp_path):
    """Test VoiceFiWelcomeWindow instance creation and singleton pattern."""
    win1 = VoiceFiWelcomeWindow.get_instance()
    win2 = VoiceFiWelcomeWindow.get_instance()
    assert win1 is win2


def test_welcome_window_activation_valid_key(tmp_path, monkeypatch):
    """Test activating a genuine cryptographic Ed25519 Pro key via welcome window logic."""
    cfg = VoiceFiConfig()
    cfg_file = tmp_path / "config.yaml"
    save_config(cfg, cfg_file)
    monkeypatch.setattr("voicefi.config.get_default_config_path", lambda: cfg_file)

    # Generate genuine key
    valid_key = generate_license_key(tier="PRO", expires="PERP", tag="TEST_ONBOARD")
    assert verify_license_key(valid_key)["is_valid"] is True

    win = VoiceFiWelcomeWindow.get_instance()
    
    # Mock UI field
    mock_field = MagicMock()
    mock_field.stringValue.return_value = valid_key
    win.key_field = mock_field

    # Trigger activation
    win._on_activate_clicked()

    # Verify config updated
    updated_cfg = load_config(cfg_file)
    assert updated_cfg.license_key == valid_key
    assert updated_cfg.tier == "pro"


def test_welcome_window_activation_invalid_key(tmp_path, monkeypatch):
    """Test rejection of invalid/fake license key."""
    cfg = VoiceFiConfig()
    cfg_file = tmp_path / "config.yaml"
    save_config(cfg, cfg_file)
    monkeypatch.setattr("voicefi.config.get_default_config_path", lambda: cfg_file)

    win = VoiceFiWelcomeWindow.get_instance()
    mock_field = MagicMock()
    mock_field.stringValue.return_value = "VF1-PRO-PERP-DEVELOPER..."
    win.key_field = mock_field

    win._on_activate_clicked()

    # Verify config was NOT updated
    updated_cfg = load_config(cfg_file)
    assert updated_cfg.license_key == ""


def test_welcome_window_trial_start(tmp_path, monkeypatch):
    """Test 1-click trial start from welcome window."""
    cfg = VoiceFiConfig()
    cfg_file = tmp_path / "config.yaml"
    save_config(cfg, cfg_file)
    monkeypatch.setattr("voicefi.config.get_default_config_path", lambda: cfg_file)
    monkeypatch.setattr("voicefi.license.load_secondary_receipt", lambda: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")

    win = VoiceFiWelcomeWindow.get_instance()
    win._on_trial_clicked()

    updated_cfg = load_config(cfg_file)
    tier_summary = FeatureGate.get_tier_summary(updated_cfg)
    assert tier_summary["is_trial"] is True
    assert tier_summary["trial_days_remaining"] == 14


def test_welcome_window_appkit_build():
    """Verify that macOS AppKit window builds cleanly without NSInternalInconsistencyException."""
    import sys
    if sys.platform != "darwin":
        pytest.skip("macOS only test")

    # Force non-headless instantiation
    with patch("voicefi.ui.welcome.is_headless", return_value=False):
        VoiceFiWelcomeWindow._instance = None
        win = VoiceFiWelcomeWindow()
        assert win.window is not None
        assert win.key_field is not None
        assert win.status_label is not None
        assert win.detected_banner is not None
        assert win.mic_status_btn is not None
        assert win.ax_status_btn is not None
        assert win.key_help_btn is not None
        assert win.paste_btn is not None
        # Clean up singleton for subsequent tests
        VoiceFiWelcomeWindow._instance = None


def test_permission_helpers():
    from voicefi.ui.welcome import check_accessibility_permission, check_microphone_permission

    # With mocked ApplicationServices
    with patch("ApplicationServices.AXIsProcessTrusted", return_value=True):
        assert check_accessibility_permission() is True

    with patch("ApplicationServices.AXIsProcessTrusted", return_value=False):
        assert check_accessibility_permission() is False

    # With mocked sounddevice
    with patch("sounddevice.InputStream") as mock_stream:
        assert check_microphone_permission() is True

    with patch("sounddevice.InputStream", side_effect=RuntimeError("Device unavailable")):
        assert check_microphone_permission() is False


def test_welcome_window_paste_and_help(tmp_path):
    """Test manual paste key and key help actions."""
    win = VoiceFiWelcomeWindow.get_instance()
    mock_field = MagicMock()
    win.key_field = mock_field
    mock_status = MagicMock()
    win.status_label = mock_status

    # Test paste from clipboard
    with patch("voicefi.ui.welcome.NSPasteboard") as mock_pb_cls:
        mock_pb_instance = MagicMock()
        mock_pb_instance.stringForType_.return_value = "  VF1-PRO-PERP-TESTCLIPBOARD.12345  "
        mock_pb_cls.generalPasteboard.return_value = mock_pb_instance

        win._on_paste_key_clicked()
        mock_field.setStringValue_.assert_called_with("VF1-PRO-PERP-TESTCLIPBOARD.12345")
        assert "pasted from clipboard" in mock_status.setStringValue_.call_args[0][0].lower()

    # Test key help alert (dismissed with 'Got It')
    with patch("voicefi.ui.welcome.NSAlert") as mock_alert_cls:
        mock_alert = MagicMock()
        mock_alert.runModal.return_value = 1002  # 'Got It'
        mock_alert_cls.alloc().init.return_value = mock_alert

        win._on_key_help_clicked()
        assert mock_alert.runModal.called


