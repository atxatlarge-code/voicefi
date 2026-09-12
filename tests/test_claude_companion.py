"""
Unit & integration tests for Claude Code integration with VoiceFi Mobile Companion.
"""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from aiohttp.test_utils import AioHTTPTestCase

from voicefi.config import VoiceFiConfig
from voicefi.integrations.conversations import (
    find_recent_claude_sessions,
    parse_claude_session,
    parse_full_claude_conversation_details,
    ConversationTracker,
    save_session_cookie,
    load_session_cookie,
    set_mobile_turn_origin,
    pop_mobile_turn_origin,
)
from voicefi.integrations.injector import (
    send_message_to_agent,
    inject_text_to_claude,
)
from voicefi.companion.server import CompanionServer


def test_parse_claude_session(tmp_path):
    """Test parsing Claude Code session JSONL file into ConversationInfo."""
    project_dir = tmp_path / "projects" / "-Users-jaketrigg-Projects-VoiceFi"
    project_dir.mkdir(parents=True)
    session_file = project_dir / "abc-123.jsonl"

    lines = [
        {"type": "user", "message": {"role": "user", "content": "Refactor the authentication module"}, "cwd": "/Users/jaketrigg/Projects/VoiceFi"},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "I have refactored auth.py and updated all unit tests. Should I run the test suite now?"}
                ],
            },
        },
    ]
    with open(session_file, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    info = parse_claude_session(session_file)
    assert info is not None
    assert info.id == "claude_abc-123"
    assert info.engine == "claude"
    assert "VoiceFi" in info.title
    assert "Refactor the authentication" in info.title
    assert info.status == "waiting_for_user"
    assert "Should I run the test suite now?" in info.last_agent_text
    assert info.last_user_text == "Refactor the authentication module"


def test_parse_full_claude_conversation_details(tmp_path):
    """Test parsing full turns, tool calls, and assistant responses from Claude Code session."""
    project_dir = tmp_path / "projects" / "-Users-jaketrigg-Projects-VoiceFi"
    project_dir.mkdir(parents=True)
    session_file = project_dir / "test-claude-session.jsonl"

    lines = [
        {"type": "user", "message": {"role": "user", "content": "List files in src"}, "timestamp": 1700000000},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": "bash", "input": {"command": "ls -la src"}},
                ],
            },
            "timestamp": 1700000001,
        },
        {
            "type": "attachment",
            "attachment": {"type": "tool_result", "output": "file1.py\nfile2.py"},
            "timestamp": 1700000002,
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Found 2 files in src directory: `file1.py` and `file2.py`."},
                ],
            },
            "timestamp": 1700000003,
        },
    ]
    with open(session_file, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    details = parse_full_claude_conversation_details(session_file)
    assert details is not None
    assert details["engine"] == "claude"
    assert len(details["turns"]) == 1

    turn = details["turns"][0]
    assert turn["user_message"] == "List files in src"
    assert len(turn["agent_steps"]) == 1
    assert turn["agent_steps"][0]["tool_name"] == "bash"
    assert turn["agent_steps"][0]["output"] == "file1.py\nfile2.py"
    assert "Found 2 files in src directory" in turn["agent_response"]
    assert turn["status"] == "done"


def test_send_message_to_agent_routing():
    """Test unified message dispatcher routes to Claude or Antigravity appropriately."""
    with patch("voicefi.integrations.injector.inject_text_to_claude", return_value=True) as mock_claude, \
         patch("voicefi.integrations.injector.send_message_to_antigravity", return_value=True) as mock_ag:

        # 1. Claude session ID
        send_message_to_agent(conv_id="claude_12345", text="Run tests")
        mock_claude.assert_called_once_with("Run tests", submit_enter=True, from_conv_id=None, from_engine="antigravity", include_envelope=False)
        mock_ag.assert_not_called()

    with patch("voicefi.integrations.injector.inject_text_to_claude", return_value=True) as mock_claude, \
         patch("voicefi.integrations.injector.send_message_to_antigravity", return_value=True) as mock_ag:

        # 2. Antigravity session ID
        send_message_to_agent(conv_id="ag-conv-987", text="Create plan")
        mock_ag.assert_called_once_with(conv_id="ag-conv-987", text="Create plan", sender_name=None, title=None, from_conv_id=None, allow_foreground_fallback=False)
        mock_claude.assert_not_called()


class ClaudeCompanionServerTestCase(AioHTTPTestCase):
    """Integration test suite for CompanionServer Claude Code endpoints and TTS."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    async def test_api_conversations_includes_claude_engine(self):
        """Test GET /api/conversations includes engine metadata."""
        resp = await self.client.get("/api/conversations")
        assert resp.status == 200
        data = await resp.json()
        assert "conversations" in data
        for c in data["conversations"]:
            assert "engine" in c
            assert c["engine"] in ("antigravity", "claude")

    async def test_api_tts_claude_persona(self):
        """Test POST /api/tts with agent_role='claude' requests Guy Neural persona."""
        mock_tts = MagicMock()

        async def fake_synth(text, path):
            Path(path).write_bytes(b"FAKE_AUDIO")

        mock_tts.synthesize_to_file = fake_synth

        with patch("voicefi.companion.server.get_tts_engine", return_value=mock_tts) as mock_get_tts:
            resp = await self.client.post("/api/tts", json={
                "text": "Hello, Claude Code is ready for your instructions.",
                "agent_role": "claude",
            })
            assert resp.status == 200
            mock_get_tts.assert_called_once_with(self.companion_server.config, agent_name="claude")

    async def test_api_new_claude_conversation(self):
        """Test POST /api/conversation/new with engine='claude' invokes headless runner."""
        from voicefi.integrations.injector import DispatchResult

        mock_disp = DispatchResult(
            success=True,
            delivery_type="headless",
            target_conv_id="claude_new-uuid-1234",
            engine="claude",
        )
        with patch("voicefi.integrations.claude_runner.ClaudeHeadlessRunner.dispatch", return_value=mock_disp) as mock_dispatch:
            resp = await self.client.post("/api/conversation/new", json={
                "prompt": "Start new Claude task",
                "engine": "claude",
            })
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("conv_id") == "claude_new-uuid-1234"
            mock_dispatch.assert_called_once()
            args, kwargs = mock_dispatch.call_args
            assert kwargs.get("text") == "Start new Claude task" or (len(args) > 0 and args[0] == "Start new Claude task")


def test_claude_stop_hook_skips_desktop_mic_for_mobile():
    """Test Claude stop hook skips Mac desktop mic auto-listen when turn originated from mobile companion."""
    from voicefi.integrations.claude import handle_claude_stop_hook

    mock_cfg = VoiceFiConfig()
    mock_cfg.enabled = True
    mock_cfg.hooks.enabled = True
    mock_cfg.hooks.claude = True
    mock_cfg.claude.read_summary_aloud = False
    mock_cfg.claude.auto_listen = True

    with patch("voicefi.integrations.claude.find_latest_claude_session", return_value=Path("/tmp/fake_claude.jsonl")), \
         patch("voicefi.integrations.claude.extract_latest_claude_summary", return_value="Task completed."), \
         patch("voicefi.integrations.claude.claim_turn", return_value=True), \
         patch("voicefi.integrations.claude.pop_mobile_turn_origin", return_value=True), \
         patch("voicefi.integrations.claude.AudioRecorder") as mock_recorder:

        result = handle_claude_stop_hook({"session_id": "test-123"}, config=mock_cfg)
        assert result.get("status") == "mobile_handled"
        assert result.get("agent") == "claude"
        # AudioRecorder must NOT have been instantiated to record on Mac desktop mic
        mock_recorder.assert_not_called()


def test_relay_client_voice_command_no_envelope():
    """Test RelayClient dispatches user_voice_command with include_envelope=False."""
    from voicefi.companion.relay_client import RelayClient

    client = RelayClient(local_port=5141)

    with patch("voicefi.integrations.injector.send_message_to_agent") as mock_send, \
         patch("voicefi.integrations.conversations.set_mobile_turn_origin") as mock_origin, \
         patch.object(client, "broadcast", return_value=None):

        payload = {
            "type": "user_voice_command",
            "text": "What is the status of the refactor?",
            "conv_id": "claude_abc-123",
            "sender_name": "Mobile Jake",
        }

        asyncio.run(client._handle_incoming_message(json.dumps(payload)))
        mock_origin.assert_called_once_with("claude_abc-123")
        mock_send.assert_called_once_with(
            conv_id="claude_abc-123",
            text="What is the status of the refactor?",
            target_engine=None,
            sender_name="Mobile Jake",
            title="Message from Mobile Jake",
            include_envelope=False,
        )
