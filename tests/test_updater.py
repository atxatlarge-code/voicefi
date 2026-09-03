"""
Unit tests for VoiceFi Self-Updater, Version Checking, and Pro Auto-Update.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from voicefi.config import VoiceFiConfig
from voicefi.license import FeatureGate
from voicefi.updater import (
    parse_semver,
    read_update_cache,
    write_update_cache,
    check_for_updates,
    perform_update,
    run_auto_update_if_enabled,
    CACHE_TTL_SECONDS,
)
from voicefi.cli import cmd_update


def test_semver_parsing():
    """Verify semantic version parsing and ordering."""
    assert parse_semver("0.1.0") == (0, 1, 0)
    assert parse_semver("v1.2.3") == (1, 2, 3)
    assert parse_semver("v2.0.0-alpha.1") == (2, 0, 0)
    assert parse_semver("0.1.0") < parse_semver("0.1.1")
    assert parse_semver("0.1.9") < parse_semver("0.2.0")
    assert parse_semver("1.0.0") > parse_semver("0.9.9")


def test_update_cache_read_write(tmp_path):
    """Verify cache persistence and TTL expiration."""
    cache_file = tmp_path / ".update_check.json"
    with patch("voicefi.updater.CACHE_FILE", cache_file):
        # Initial: no cache
        assert read_update_cache() is None

        # Write fresh cache
        data = {"update_available": True, "latest_version": "0.2.0"}
        write_update_cache(data)

        cached = read_update_cache()
        assert cached is not None
        assert cached["latest_version"] == "0.2.0"
        assert cached["update_available"] is True

        # Expired cache
        data_expired = {"update_available": False, "latest_version": "0.1.0", "timestamp": time.time() - (CACHE_TTL_SECONDS + 100)}
        cache_file.write_text(json.dumps(data_expired), encoding="utf-8")
        assert read_update_cache() is None


def test_check_for_updates_remote_release():
    """Verify check_for_updates flags newer versions from remote GitHub API."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({
        "tag_name": "v99.0.0",
        "html_url": "https://github.com/atxatlarge-code/voicefi/releases/v99.0.0",
        "body": "Major release with neural personas",
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("voicefi.updater.urlopen", return_value=mock_resp), \
         patch("voicefi.updater.read_update_cache", return_value=None), \
         patch("voicefi.updater.write_update_cache"):
        is_avail, ver, url = check_for_updates(force=True)
        assert is_avail is True
        assert ver == "99.0.0"
        assert "releases/v99.0.0" in url


def test_perform_update_flow():
    """Verify perform_update invokes pip install and setup correctly."""
    mock_proc_pip = MagicMock(returncode=0, stdout="Successfully installed voicefi", stderr="")
    mock_proc_ver = MagicMock(returncode=0, stdout="0.2.0\n", stderr="")

    def mock_subprocess_run(cmd, *args, **kwargs):
        if "-m" in cmd and "pip" in cmd:
            return mock_proc_pip
        return mock_proc_ver

    with patch("subprocess.run", side_effect=mock_subprocess_run):
        res = perform_update(relink_hooks=False)
        assert res["success"] is True
        assert "Successfully updated" in res["message"]


def test_pro_auto_updater_feature_gate():
    """Verify auto-updater requires Pro tier license."""
    from voicefi.license import compute_trial_hmac, get_hardware_identifier

    hw_id = get_hardware_identifier()
    seal = compute_trial_hmac(1000.0, hw_id, 14)
    with patch("voicefi.license.load_secondary_receipt", return_value=None):
        community_cfg = VoiceFiConfig(
            tier="community", auto_update=True, trial_started_at=1000.0, trial_seal=seal, trial_duration_days=14
        )
        assert not FeatureGate.can_use_feature("auto_update", community_cfg)

        pro_cfg = VoiceFiConfig(tier="pro", license_key="PRO-123456", auto_update=True)
        assert FeatureGate.can_use_feature("auto_update", pro_cfg)


def test_cmd_update_cli_check_flag(capsys):
    """Verify vifi update --check outputs version status without running pip."""
    with patch("voicefi.updater.check_for_updates", return_value=(True, "0.5.0", "https://github.com/atxatlarge-code/voicefi/releases/v0.5.0")):
        args = MagicMock()
        args.check = True
        args.repo = None
        cmd_update(args)

        captured = capsys.readouterr()
        assert "Update available" in captured.out
        assert "v0.5.0" in captured.out
        assert "vifi update" in captured.out
