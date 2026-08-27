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
        """Test POST /api/conversation/new with engine='claude'."""
        with patch("voicefi.companion.server.inject_text_to_claude", return_value=True) as mock_inject:
            resp = await self.client.post("/api/conversation/new", json={
                "prompt": "Start new Claude task",
                "engine": "claude",
            })
            assert resp.status == 200
            mock_inject.assert_called_once_with("Start new Claude task", submit_enter=True)
