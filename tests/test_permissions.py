"""
Unit tests for macOS Accessibility permissions checks and onboarding prompts.
"""

from unittest.mock import patch, MagicMock
from voicefi.cli import cmd_permissions
from voicefi.onboarding import check_and_prompt_permissions


def test_cmd_permissions_trusted(capsys):
    """Verify cmd_permissions output when Accessibility is granted."""
    args = MagicMock()
    with patch("ApplicationServices.AXIsProcessTrustedWithOptions", return_value=True):
        cmd_permissions(args)
        captured = capsys.readouterr()
        assert "Accessibility permissions are granted and active!" in captured.out


def test_cmd_permissions_untrusted(capsys):
    """Verify cmd_permissions opens settings when Accessibility is not yet granted."""
    args = MagicMock()
    with patch("ApplicationServices.AXIsProcessTrustedWithOptions", return_value=False):
        with patch("voicefi.integrations.injector.open_accessibility_settings") as mock_open:
            cmd_permissions(args)
            captured = capsys.readouterr()
            assert "Accessibility permission is not yet enabled" in captured.out
            mock_open.assert_called_once()


def test_onboarding_check_and_prompt_permissions():
    """Verify onboarding triggers permission check and opens settings if untrusted."""
    with patch("ApplicationServices.AXIsProcessTrustedWithOptions", return_value=False):
        with patch("voicefi.integrations.injector.open_accessibility_settings") as mock_open:
            with patch("time.sleep"):
                res = check_and_prompt_permissions()
                assert res is False
                mock_open.assert_called_once()
