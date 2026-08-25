"""
Unit and integration tests for Daemon-First Hook Architecture.
Validates fast localhost IPC hook forwarding and seamless standalone fallback.
"""

import json
import argparse
import pytest
from unittest.mock import patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from voicefi.config import VoiceFiConfig
from voicefi.companion.server import CompanionServer
from voicefi.integrations.daemon_client import is_daemon_running, forward_hook_to_daemon
from voicefi.cli import cmd_hook


class TestCompanionHookEndpoint(AioHTTPTestCase):
    """Test /api/hook/event endpoint on the CompanionServer."""

    async def get_application(self):
        self.config = VoiceFiConfig()
        self.server = CompanionServer(config=self.config, port=8765, host="127.0.0.1")
        return self.server.app

    @unittest_run_loop
    async def test_hook_event_endpoint_antigravity(self):
        """Test POST /api/hook/event handles Antigravity payload and spawns background processor."""
        payload = {
            "agent": "antigravity",
            "conversationId": "test-hook-conv-123",
            "transcriptPath": "/tmp/fake_transcript.jsonl",
            "workspacePaths": ["/tmp/workspace"],
        }
        with patch("voicefi.integrations.antigravity.handle_antigravity_stop_hook") as mock_handle:
            resp = await self.client.post("/api/hook/event", json=payload)
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["status"] == "handled"
            assert data["agent"] == "antigravity"
            assert data["conversationId"] == "test-hook-conv-123"

    @unittest_run_loop
    async def test_hook_event_endpoint_claude(self):
        """Test POST /api/hook/event handles Claude Code payload."""
        payload = {
            "agent": "claude",
            "conversationId": "claude_session_999",
            "message": "Task complete!",
        }
        with patch("voicefi.integrations.claude.handle_claude_stop_hook") as mock_handle:
            resp = await self.client.post("/api/hook/event", json=payload)
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["status"] == "handled"
            assert data["agent"] == "claude"


def test_cmd_hook_fast_forward_to_daemon(monkeypatch, capsys):
    """Test cmd_hook immediately returns allow when daemon handles the hook."""
    args = argparse.Namespace(config=None, agent="antigravity")

    # Mock forward_hook_to_daemon returning handled
    mock_forward = MagicMock(return_value={"success": True, "status": "handled"})
    monkeypatch.setattr("voicefi.integrations.daemon_client.forward_hook_to_daemon", mock_forward)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with patch("voicefi.integrations.antigravity.handle_antigravity_stop_hook") as mock_local_handle:
        cmd_hook(args)
        # Standalone handler should NOT be called since daemon handled it
        mock_local_handle.assert_not_called()

    captured = capsys.readouterr()
    res = json.loads(captured.out.strip())
    assert res.get("decision") == "allow"
    assert res.get("forwarded") is True


def test_cmd_hook_offline_standalone_fallback(monkeypatch, capsys):
    """Test cmd_hook gracefully falls back to in-process execution when daemon is offline."""
    args = argparse.Namespace(config=None, agent="antigravity")

    # Mock forward_hook_to_daemon returning None (daemon offline)
    mock_forward = MagicMock(return_value=None)
    monkeypatch.setattr("voicefi.integrations.daemon_client.forward_hook_to_daemon", mock_forward)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    mock_local = MagicMock(return_value={"decision": "allow", "mode": "standalone"})
    monkeypatch.setattr("voicefi.cli.handle_antigravity_stop_hook", mock_local)

    cmd_hook(args)
    mock_local.assert_called_once()

    captured = capsys.readouterr()
    res = json.loads(captured.out.strip())
    assert res.get("decision") == "allow"
    assert res.get("mode") == "standalone"
