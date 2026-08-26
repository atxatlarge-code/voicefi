"""
Unit tests for VoiceFi Daemon, Process Lifecycle, and Cache Management subsystem.
"""

import json
import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from voicefi.daemon import (
    clean_caches,
    clean_lock_files,
    find_running_voicefi_processes,
    get_full_daemon_status,
    get_launchagent_status,
    get_port_listener,
    is_pid_running,
    link_dev_environment,
    stop_all_voicefi_daemons,
)


def test_is_pid_running():
    # Current PID should always be running
    assert is_pid_running(os.getpid()) is True
    # Non-existent high PID should not be running
    assert is_pid_running(9999999) is False
    # Negative PID
    assert is_pid_running(-1) is False


def test_clean_lock_files(tmp_path):
    lock = Path("/tmp/voicefi_tray.lock")
    pid = Path("/tmp/voicefi_tray.pid")
    lock.write_text("lock")
    pid.write_text("12345")

    assert lock.exists()
    assert pid.exists()
    clean_lock_files()
    assert not lock.exists()
    assert not pid.exists()


def test_clean_caches(tmp_path):
    # Create fake pycache and .pyc
    pycache = tmp_path / "pkg" / "__pycache__"
    pycache.mkdir(parents=True)
    pyc_file = pycache / "mod.cpython-312.pyc"
    pyc_file.write_text("bytecode")

    res = clean_caches(
        workspace_root=tmp_path,
        clean_pycache=True,
        clean_tmp_state=False,
        clean_update_cache=False,
        purge_daemons=False,
    )
    assert res["cleaned_pycache_count"] >= 1
    assert not pyc_file.exists()


def test_link_dev_environment(tmp_path):
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    fake_voicefi = venv_bin / "voicefi"
    fake_voicefi.write_text("#!/bin/sh\necho ok")
    fake_voicefi.chmod(0o755)

    with patch("pathlib.Path.home", return_value=tmp_path):
        res = link_dev_environment(workspace_dir=tmp_path)
        assert res["target_binary"] == str(fake_voicefi)

        gemini_hook = tmp_path / ".gemini" / "config" / "hooks.json"
        assert gemini_hook.is_file()
        g_data = json.loads(gemini_hook.read_text())
        assert str(fake_voicefi) in g_data["voicefi-voice-layer"]["Stop"][0]["command"]

        claude_hook = tmp_path / ".claude" / "settings.json"
        assert claude_hook.is_file()
        c_data = json.loads(claude_hook.read_text())
        assert str(fake_voicefi) in c_data["hooks"]["Stop"][0]["hooks"][0]["command"]


def test_get_full_daemon_status():
    status = get_full_daemon_status()
    assert "launchagent" in status
    assert "port_5141" in status
    assert "port_8765" in status
    assert "running_processes" in status
    assert "lock_active" in status
    assert "hooks" in status
    assert "python_executable" in status
