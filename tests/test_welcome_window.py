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

    win = VoiceFiWelcomeWindow.get_instance()
    win._on_trial_clicked()

    updated_cfg = load_config(cfg_file)
    tier_summary = FeatureGate.get_tier_summary(updated_cfg)
    assert tier_summary["is_trial"] is True
    assert tier_summary["trial_days_remaining"] == 14
