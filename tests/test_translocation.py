"""
Unit tests for VoiceFi macOS App Translocation & Disk Image Relocation Guard.
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voicefi.ui.translocation import (
    is_running_from_dmg_or_translocation,
    move_to_applications,
    check_and_prompt_move_to_applications,
)


def test_translocation_detection_standard_locations(tmp_path):
    # System /Applications
    sys_app = Path("/Applications/VoiceFi.app")
    assert is_running_from_dmg_or_translocation(sys_app) is False

    # User ~/Applications
    user_app = Path.home() / "Applications" / "VoiceFi.app"
    assert is_running_from_dmg_or_translocation(user_app) is False


def test_translocation_detection_dmg_volume():
    # Mounted DMG volume
    dmg_app = Path("/Volumes/VoiceFi/VoiceFi.app")
    assert is_running_from_dmg_or_translocation(dmg_app) is True

    dmg_app_ver = Path("/Volumes/VoiceFi_v0.2.0/VoiceFi.app")
    assert is_running_from_dmg_or_translocation(dmg_app_ver) is True


def test_translocation_detection_app_translocation():
    # macOS Gatekeeper Translocation sandbox path
    translocated = Path("/private/var/folders/3x/abcd/AppTranslocation/d1234/d/VoiceFi.app")
    assert is_running_from_dmg_or_translocation(translocated) is True


def test_translocation_detection_downloads_folder():
    # User Downloads folder
    dl_app = Path.home() / "Downloads" / "VoiceFi.app"
    assert is_running_from_dmg_or_translocation(dl_app) is True


def test_move_to_applications_logic(tmp_path):
    # Setup mock source bundle in fake volume
    src_volume = tmp_path / "Volumes" / "VoiceFi"
    src_volume.mkdir(parents=True, exist_ok=True)
    src_bundle = src_volume / "VoiceFi.app"
    src_bundle.mkdir(parents=True, exist_ok=True)
    (src_bundle / "Contents").mkdir(parents=True, exist_ok=True)
    (src_bundle / "Contents" / "Info.plist").write_text("<plist></plist>")

    # Mock target directory
    fake_apps = tmp_path / "Applications"
    fake_apps.mkdir(parents=True, exist_ok=True)

    with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
        res = move_to_applications(
            bundle_path=src_bundle,
            target_dir=fake_apps,
            relaunch=True,
        )

        assert res is True
        dest_bundle = fake_apps / "VoiceFi.app"
        assert dest_bundle.is_dir()
        assert (dest_bundle / "Contents" / "Info.plist").is_file()

        # Verify open command called
        mock_popen.assert_called_once()
        open_cmd = mock_popen.call_args[0][0]
        assert open_cmd == ["open", str(dest_bundle)]

        # Verify hdiutil detach called
        detach_calls = [
            call for call in mock_run.call_args_list
            if "hdiutil" in call[0][0] and "detach" in call[0][0]
        ]
        assert len(detach_calls) == 1
        assert detach_calls[0][0][0] == ["hdiutil", "detach", f"/Volumes/{src_volume.name}", "-force", "-quiet"]


def test_check_and_prompt_headless_safety():
    # In headless testing mode, prompt should never block or display UI
    with patch("voicefi.ui.translocation.is_headless", return_value=True):
        res = check_and_prompt_move_to_applications()
        assert res is False


def test_check_and_prompt_skip_when_installed():
    # When running from /Applications, check returns False immediately
    sys_app = Path("/Applications/VoiceFi.app")
    with patch("voicefi.ui.translocation.is_headless", return_value=False):
        res = check_and_prompt_move_to_applications(bundle_path=sys_app)
        assert res is False
