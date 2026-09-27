"""
Unit tests for Always Detach hook execution and background worker lifecycle.
Verifies that lifecycle hooks return instantly (<25ms) to calling agents
while audio playback and listening run detached in the background.
"""

import json
import os
import tempfile
import argparse
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voicefi.cli import cmd_hook
from voicefi.tts.base import stop_active_playback, _LAST_SPEECH_STOP_FILE


def test_cmd_hook_always_detach_spawns_worker_process(monkeypatch, capsys):
    """
    Verify cmd_hook spawns a detached worker process and immediately prints {}
    when running outside pytest sync mode.
    """
    # Temporarily remove PYTEST_CURRENT_TEST to simulate agent CLI invocation
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("VOICEFI_HOOK_SYNC", raising=False)
    monkeypatch.delenv("VOICEFI_HOOK_WORKER", raising=False)

    args = argparse.Namespace(
        config=None,
        agent="antigravity",
        action=None,
        extra_args=[],
        voice=None,
        disable=False,
        enable=False,
        status=False,
        remove=False,
        worker=False,
        sync=False,
    )

    mock_forward = MagicMock(return_value=None)
    monkeypatch.setattr("voicefi.integrations.server_client.forward_hook_to_server", mock_forward)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    spawned_cmds = []

    def mock_popen(cmd, **kwargs):
        spawned_cmds.append((cmd, kwargs))
        return MagicMock()

    monkeypatch.setattr("subprocess.Popen", mock_popen)

    cmd_hook(args)

    # 1. Parent process returns {} instantly
    captured = capsys.readouterr()
    res = json.loads(captured.out.strip())
    assert res == {}

    # 2. Subprocess was spawned with start_new_session=True and --worker
    assert len(spawned_cmds) == 1
    cmd, kwargs = spawned_cmds[0]
    assert "--worker" in cmd
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdin") is not None
    assert kwargs.get("stdout") is not None

    # Check env payload file was configured and then clean it up
    env = kwargs.get("env", {})
    assert env.get("VOICEFI_HOOK_WORKER") == "1"
    payload_file = env.get("VOICEFI_HOOK_PAYLOAD_FILE")
    assert payload_file is not None
    if os.path.exists(payload_file):
        os.unlink(payload_file)


def test_cmd_hook_worker_execution_reads_payload_file(monkeypatch, capsys):
    """
    Verify worker mode reads payload from VOICEFI_HOOK_PAYLOAD_FILE,
    unlinks it, and executes handle_antigravity_stop_hook.
    """
    test_payload = {
        "conversationId": "test-detached-conv-999",
        "agent": "antigravity",
        "transcriptPath": "/tmp/transcript.jsonl",
    }

    temp_f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(test_payload, temp_f)
    temp_f.close()

    monkeypatch.setenv("VOICEFI_HOOK_WORKER", "1")
    monkeypatch.setenv("VOICEFI_HOOK_PAYLOAD_FILE", temp_f.name)
    monkeypatch.setattr("voicefi.integrations.server_client.forward_hook_to_server", lambda *a, **k: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    mock_handler = MagicMock(return_value={})
    monkeypatch.setattr("voicefi.integrations.antigravity.handle_antigravity_stop_hook", mock_handler)
    # Also patch in sys.modules if voicefi.cli has cached reference
    monkeypatch.setattr("voicefi.cli.handle_antigravity_stop_hook", mock_handler, raising=False)

    args = argparse.Namespace(
        config=None,
        agent="antigravity",
        action=None,
        extra_args=[],
        voice=None,
        disable=False,
        enable=False,
        status=False,
        remove=False,
        worker=True,
        sync=False,
    )

    cmd_hook(args)

    # Payload file was removed
    assert not os.path.exists(temp_f.name)

    # Handler was called with the exact payload
    assert mock_handler.call_count == 1
    called_payload = mock_handler.call_args[0][0]
    assert called_payload.get("conversationId") == "test-detached-conv-999"


def test_cmd_hook_sync_flag_executes_in_process(monkeypatch, capsys):
    """
    Verify passing --sync bypasses detached worker and runs synchronously.
    """
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("VOICEFI_HOOK_WORKER", raising=False)

    args = argparse.Namespace(
        config=None,
        agent="antigravity",
        action=None,
        extra_args=[],
        voice=None,
        disable=False,
        enable=False,
        status=False,
        remove=False,
        worker=False,
        sync=True,
    )

    monkeypatch.setattr("voicefi.integrations.server_client.forward_hook_to_server", lambda *a, **k: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    mock_handler = MagicMock(return_value={"decision": "allow", "sync_run": True})
    monkeypatch.setattr("voicefi.cli.handle_antigravity_stop_hook", mock_handler, raising=False)
    monkeypatch.setattr("voicefi.integrations.antigravity.handle_antigravity_stop_hook", mock_handler)

    mock_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", mock_popen)

    cmd_hook(args)

    # Popen was not called because it ran synchronously
    mock_popen.assert_not_called()
    assert mock_handler.call_count == 1

    captured = capsys.readouterr()
    res = json.loads(captured.out.strip())
    assert res.get("decision") == "approve"
    assert res.get("sync_run") is True


def test_stop_active_playback_terminates_afplay_without_marking_stop_file(monkeypatch):
    """
    Verify stop_active_playback terminates afplay and say processes
    without updating _LAST_SPEECH_STOP_FILE (preserving the ability for
    the incoming turn to speak immediately).
    """
    executed_commands = []

    def mock_run(cmd, **kwargs):
        executed_commands.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr("subprocess.run", mock_run)

    # Remove any existing stop file
    _LAST_SPEECH_STOP_FILE.unlink(missing_ok=True)

    stop_active_playback()

    # Verify killall afplay and say were invoked
    assert ["killall", "-9", "afplay"] in executed_commands
    assert ["killall", "-9", "say"] in executed_commands

    # Verify stop file was NOT created (no user-interruption penalty)
    assert not _LAST_SPEECH_STOP_FILE.exists()
