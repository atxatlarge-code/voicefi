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
        self.server = CompanionServer(config=self.config, port=5141, host="127.0.0.1")
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

    async def test_hook_event_endpoint_claude_alias(self):
        """Test POST /api/hook/event handles Claude Code alias (e.g. claude2) with voice override."""
        payload = {
            "agent": "claude2",
            "voice": "en-GB-RyanNeural",
            "conversationId": "claude_session_alias",
            "message": "Task complete!",
        }
        with patch("voicefi.integrations.claude.handle_claude_stop_hook") as mock_handle:
            resp = await self.client.post("/api/hook/event", json=payload)
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["status"] == "handled"
            assert data["agent"] == "claude2"

    async def test_hook_event_endpoint_codex_alias(self):
        """Test POST /api/hook/event handles Codex alias (e.g. codex2) with voice override."""
        payload = {
            "agent": "codex2",
            "voice": "en-US-AvaNeural",
            "conversationId": "codex_session_alias",
            "last-assistant-message": "Task complete!",
        }
        with patch("voicefi.integrations.codex.handle_codex_stop_hook") as mock_handle:
            resp = await self.client.post("/api/hook/event", json=payload)
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["status"] == "handled"
            assert data["agent"] == "codex2"


def test_cmd_hook_fast_forward_to_daemon(monkeypatch, capsys):
    """Test cmd_hook immediately returns allow when daemon/server handles the hook."""
    args = argparse.Namespace(config=None, agent="antigravity")

    # Mock forward_hook_to_server returning handled
    mock_forward = MagicMock(return_value={"success": True, "status": "handled"})
    monkeypatch.setattr("voicefi.integrations.server_client.forward_hook_to_server", mock_forward)
    monkeypatch.setattr("voicefi.integrations.daemon_client.forward_hook_to_daemon", mock_forward)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with patch("voicefi.integrations.antigravity.handle_antigravity_stop_hook") as mock_local_handle:
        cmd_hook(args)
        # Standalone handler should NOT be called since daemon handled it
        mock_local_handle.assert_not_called()

    captured = capsys.readouterr()
    json_lines = [l for l in captured.out.strip().splitlines() if l.strip().startswith("{")]
    assert json_lines, f"No JSON line found in stdout: {captured.out}"
    res = json.loads(json_lines[-1])
    assert isinstance(res, dict)


def test_cmd_hook_offline_standalone_fallback(monkeypatch, capsys):
    """Test cmd_hook gracefully falls back to in-process execution when server is offline."""
    args = argparse.Namespace(config=None, agent="antigravity")

    # Mock forward_hook_to_server returning None (server offline)
    mock_forward = MagicMock(return_value=None)
    monkeypatch.setattr("voicefi.integrations.server_client.forward_hook_to_server", mock_forward)
    monkeypatch.setattr("voicefi.integrations.daemon_client.forward_hook_to_daemon", mock_forward)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    mock_local = MagicMock(return_value={"decision": "allow", "mode": "standalone"})
    monkeypatch.setattr("voicefi.cli.handle_antigravity_stop_hook", mock_local)

    cmd_hook(args)
    mock_local.assert_called_once()

    captured = capsys.readouterr()
    res = json.loads(captured.out.strip())
    assert res.get("decision") == "approve"
    assert res.get("mode") == "standalone"


def test_cmd_hook_when_globally_disabled(monkeypatch, capsys):
    """Test cmd_hook immediately returns empty JSON when VoiceFi is disabled."""
    args = argparse.Namespace(config=None, agent="antigravity", action=None, disable=False, enable=False, status=False, remove=False)
    cfg = VoiceFiConfig(enabled=False)
    monkeypatch.setattr("voicefi.cli.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with patch("voicefi.integrations.server_client.forward_hook_to_server") as mock_forward, \
         patch("voicefi.integrations.antigravity.handle_antigravity_stop_hook") as mock_handle:
        cmd_hook(args)
        mock_forward.assert_not_called()
        mock_handle.assert_not_called()

    captured = capsys.readouterr()
    assert captured.out.strip() == "{}"


def test_cmd_hook_when_hooks_disabled(monkeypatch, capsys):
    """Test cmd_hook immediately returns empty JSON when hooks.enabled is False."""
    args = argparse.Namespace(config=None, agent="antigravity", action=None, disable=False, enable=False, status=False, remove=False)
    cfg = VoiceFiConfig(enabled=True)
    cfg.hooks.enabled = False
    monkeypatch.setattr("voicefi.cli.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with patch("voicefi.integrations.server_client.forward_hook_to_server") as mock_forward, \
         patch("voicefi.integrations.antigravity.handle_antigravity_stop_hook") as mock_handle:
        cmd_hook(args)
        mock_forward.assert_not_called()
        mock_handle.assert_not_called()

    captured = capsys.readouterr()
    assert captured.out.strip() == "{}"


def test_cmd_hook_when_agent_hooks_disabled(monkeypatch, capsys):
    """Test cmd_hook exits when specific agent hook or auto_listen/summary is disabled."""
    args = argparse.Namespace(config=None, agent="antigravity", action=None, disable=False, enable=False, status=False, remove=False)
    cfg = VoiceFiConfig(enabled=True)
    cfg.hooks.antigravity = False
    monkeypatch.setattr("voicefi.cli.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with patch("voicefi.integrations.server_client.forward_hook_to_server") as mock_forward, \
         patch("voicefi.integrations.antigravity.handle_antigravity_stop_hook") as mock_handle:
        cmd_hook(args)
        mock_forward.assert_not_called()
        mock_handle.assert_not_called()

    captured = capsys.readouterr()
    assert captured.out.strip() == "{}"


def test_cmd_hook_action_disable_and_enable(monkeypatch, capsys):
    """Test vifi hook disable and vifi hook enable toggle config state."""
    cfg = VoiceFiConfig(enabled=True)
    cfg.hooks.enabled = True
    saved_cfgs = []
    monkeypatch.setattr("voicefi.cli.load_config", lambda *a, **kw: cfg)
    monkeypatch.setattr("voicefi.cli.save_config", lambda c: saved_cfgs.append(c))

    # Disable
    args_dis = argparse.Namespace(config=None, action="disable", disable=False, enable=False, status=False, remove=False)
    cmd_hook(args_dis)
    assert cfg.hooks.enabled is False
    assert len(saved_cfgs) == 1

    # Enable
    args_en = argparse.Namespace(config=None, action="enable", disable=False, enable=False, status=False, remove=False)
    cmd_hook(args_en)
    assert cfg.hooks.enabled is True
    assert len(saved_cfgs) == 2


class TestMultiInstanceAgentVoiceOverrides:
    """Validate multi-agent subscription aliases and per-hook voice overrides."""

    def test_cmd_hook_populates_agent_alias_and_voice(self, monkeypatch, capsys):
        """Test vifi hook --agent claude2 --voice Ryan passes metadata to server."""
        args = argparse.Namespace(
            config=None,
            agent="claude2",
            voice="en-GB-RyanNeural",
            action=None,
            extra_args=[],
            disable=False,
            enable=False,
            status=False,
            remove=False,
        )
        forwarded_payloads = []
        monkeypatch.setattr(
            "voicefi.integrations.server_client.forward_hook_to_server",
            lambda p, c: forwarded_payloads.append(p) or {"status": "handled"},
        )
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        cmd_hook(args)
        assert len(forwarded_payloads) == 1
        assert forwarded_payloads[0]["agent"] == "claude2"
        assert forwarded_payloads[0]["voice"] == "en-GB-RyanNeural"

    def test_handle_claude_stop_hook_uses_voice_override(self, monkeypatch):
        """Test handle_claude_stop_hook passes voice_override to get_tts_engine."""
        from voicefi.integrations.claude import handle_claude_stop_hook

        cfg = VoiceFiConfig(enabled=True)
        cfg.claude.read_summary_aloud = True
        cfg.claude.auto_listen = False

        payload = {
            "agent": "claude2",
            "voice": "en-GB-RyanNeural",
            "message": "Claude 2 finished compiling the assets.",
        }

        mock_tts = MagicMock()
        mock_tts.voice = "Ryan"
        captured_kwargs = {}

        def mock_get_tts(config, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_tts

        monkeypatch.setattr("voicefi.integrations.claude.get_tts_engine", mock_get_tts)
        monkeypatch.setattr("voicefi.integrations.claude.claim_turn", lambda *a, **kw: True)
        monkeypatch.setattr("voicefi.audio.meeting_detection.is_user_on_call", lambda: False)

        result = handle_claude_stop_hook(payload, cfg)
        assert captured_kwargs.get("agent_name") == "claude2"
        assert captured_kwargs.get("voice_override") == "en-GB-RyanNeural"
        mock_tts.stream_speak.assert_called_once()

    def test_handle_codex_stop_hook_uses_voice_override(self, monkeypatch):
        """Test handle_codex_stop_hook passes voice_override to get_tts_engine."""
        from voicefi.integrations.codex import handle_codex_stop_hook

        cfg = VoiceFiConfig(enabled=True)
        cfg.codex.read_summary_aloud = True
        cfg.codex.auto_listen = False

        payload = {
            "agent": "codex2",
            "voice": "en-US-AvaNeural",
            "last-assistant-message": "Codex 2 finished writing the migration script.",
            "thread-id": "codex_sub_2",
        }

        mock_tts = MagicMock()
        mock_tts.voice = "Ava"
        captured_kwargs = {}

        def mock_get_tts(config, **kwargs):
            captured_kwargs.update(kwargs)
            return mock_tts

        monkeypatch.setattr("voicefi.integrations.codex.get_tts_engine", mock_get_tts)
        monkeypatch.setattr("voicefi.integrations.codex.claim_turn", lambda *a, **kw: True)
        monkeypatch.setattr("voicefi.audio.meeting_detection.is_user_on_call", lambda: False)

        result = handle_codex_stop_hook(payload, cfg)
        assert captured_kwargs.get("agent_name") == "codex2"
        assert captured_kwargs.get("voice_override") == "en-US-AvaNeural"
        mock_tts.speak.assert_called_once()


