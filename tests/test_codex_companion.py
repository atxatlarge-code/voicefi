"""
Unit & integration tests for OpenAI Codex integration with VoiceFi Mobile Companion.
"""

import asyncio
import json
import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from aiohttp.test_utils import AioHTTPTestCase

from voicefi.config import VoiceFiConfig
from voicefi.integrations.codex import (
    get_codex_cli_path,
    parse_codex_session,
    parse_full_codex_conversation_details,
    execute_codex_cli,
    handle_codex_stop_hook,
)
from voicefi.integrations.conversations import (
    ConversationInfo,
    save_session_cookie,
    load_session_cookie,
    set_mobile_turn_origin,
    pop_mobile_turn_origin,
)
from voicefi.integrations.injector import (
    send_message_to_agent,
    DispatchResult,
)
from voicefi.companion.server import CompanionServer


def test_get_codex_cli_path():
    """Test get_codex_cli_path discovers executable paths correctly."""
    with patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True):
        p = get_codex_cli_path()
        assert p == "/Applications/ChatGPT.app/Contents/Resources/codex"

    with patch("pathlib.Path.is_file", return_value=False), \
         patch("shutil.which", return_value="/usr/local/bin/codex"):
        p = get_codex_cli_path()
        assert p == "/usr/local/bin/codex"

    with patch("pathlib.Path.is_file", return_value=False), \
         patch("shutil.which", return_value=None):
        p = get_codex_cli_path()
        assert p is None


def test_parse_codex_session(tmp_path):
    """Test parsing Codex rollout JSONL file into ConversationInfo."""
    session_file = tmp_path / "rollout-2026-09-23T10-00-00-11111111-2222-3333-4444-555555555555.jsonl"

    lines = [
        {"type": "session_meta", "payload": {"id": "11111111-2222-3333-4444-555555555555", "cwd": "/Users/jaketrigg/Projects/VoiceFi"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "text", "text": "Fix database connection pooling"}]}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec_cmd", "input": "git status"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "output": "On branch main"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "text", "text": "I have configured the connection pool limit to 20 connections."}]}},
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "I have configured the connection pool limit to 20 connections."}},
    ]
    with open(session_file, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    info = parse_codex_session(session_file)
    assert info is not None
    assert info.id == "codex_11111111-2222-3333-4444-555555555555"
    assert info.engine == "codex"
    assert "VoiceFi" in info.title
    assert "Fix database connection pooling" in info.title
    assert info.status == "waiting_for_user"
    assert "configured the connection pool limit" in info.last_agent_text
    assert info.last_user_text == "Fix database connection pooling"


def test_parse_full_codex_conversation_details_with_deduplication(tmp_path):
    """Test full turn extraction and user message deduplication in Codex rollout files."""
    session_file = tmp_path / "rollout-2026-09-23T10-00-00-99999999-8888-7777-6666-555555555555.jsonl"

    lines = [
        {"type": "session_meta", "payload": {"id": "99999999-8888-7777-6666-555555555555", "cwd": "/Users/jaketrigg/Projects/VoiceFi"}},
        # Dual user event emission: response_item followed by event_msg
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "text", "text": "Refactor auth middleware"}]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "Refactor auth middleware"}},
        # Tool call and output
        {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "read_file", "input": "auth.py", "call_id": "call-1"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call-1", "output": "def verify_token(): pass"}},
        # Assistant final response
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "text", "text": "Auth middleware has been refactored with token validation."}]}},
        {"type": "event_msg", "payload": {"type": "task_complete"}},
    ]
    with open(session_file, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    details = parse_full_codex_conversation_details(session_file)
    assert details is not None
    assert details["engine"] == "codex"
    # Deduplication check: exactly 1 turn despite double user event emission
    assert len(details["turns"]) == 1

    turn = details["turns"][0]
    assert turn["user_message"] == "Refactor auth middleware"
    assert len(turn["agent_steps"]) == 1
    assert turn["agent_steps"][0]["tool_name"] == "read_file"
    assert turn["agent_steps"][0]["output"] == "def verify_token(): pass"
    assert "Auth middleware has been refactored" in turn["agent_response"]
    assert turn["status"] == "done"


def test_execute_codex_cli_new_session():
    """Test non-interactive execution of a new Codex session."""
    with patch("voicefi.integrations.codex.get_codex_cli_path", return_value="/usr/local/bin/codex"), \
         patch("voicefi.integrations.codex.handle_codex_stop_hook"), \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        res = execute_codex_cli("Create a unit test", async_execution=False)
        assert res.success is True
        assert res.delivery_type == "headless"
        assert res.engine == "codex"
        assert res.target_conv_id.startswith("codex_session_")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:2] == ["/usr/local/bin/codex", "exec"]
        assert "Create a unit test" in cmd
        assert "--json" in cmd
        assert "--skip-git-repo-check" in cmd
        env = mock_run.call_args[1]["env"]
        assert env.get("TERM") == "xterm-256color"


def test_execute_codex_cli_resume_session():
    """Test non-interactive resumption of an existing Codex thread UUID."""
    uuid_str = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    with patch("voicefi.integrations.codex.get_codex_cli_path", return_value="/usr/local/bin/codex"), \
         patch("voicefi.integrations.codex.handle_codex_stop_hook"), \
         patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        res = execute_codex_cli(
            "Run the test suite",
            conv_id=f"codex_{uuid_str}",
            async_execution=False,
        )
        assert res.success is True
        assert res.target_conv_id == f"codex_{uuid_str}"

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:4] == ["/usr/local/bin/codex", "exec", "resume", uuid_str]
        assert "Run the test suite" in cmd
        assert "--json" in cmd


def test_send_message_to_agent_codex_routing():
    """Test unified message dispatcher routes to Codex based on ID, intent, or explicit target."""
    # 1. Routing by codex_ session ID
    with patch("voicefi.integrations.codex.execute_codex_cli") as mock_exec, \
         patch("voicefi.integrations.codex.get_codex_cli_path", return_value="/usr/local/bin/codex"):
        mock_exec.return_value = DispatchResult(success=True, delivery_type="headless", engine="codex")
        res = send_message_to_agent(conv_id="codex_12345678-1234-5678-1234-567812345678", text="Check status")
        assert res.success is True
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        prompt_called = args[0] if args else kwargs.get("prompt")
        assert prompt_called == "Check status"
        assert kwargs.get("conv_id") == "codex_12345678-1234-5678-1234-567812345678"

    # 2. Routing by spoken intent ("hey codex")
    with patch("voicefi.integrations.codex.execute_codex_cli") as mock_exec, \
         patch("voicefi.integrations.codex.get_codex_cli_path", return_value="/usr/local/bin/codex"):
        mock_exec.return_value = DispatchResult(success=True, delivery_type="headless", engine="codex")
        res = send_message_to_agent(conv_id="ag-current-turn", text="hey codex, analyze the build failure")
        assert res.success is True
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        prompt_called = args[0] if args else kwargs.get("prompt")
        assert "analyze the build failure" in prompt_called

    # 3. Routing by target_engine="codex"
    with patch("voicefi.integrations.codex.execute_codex_cli") as mock_exec, \
         patch("voicefi.integrations.codex.get_codex_cli_path", return_value="/usr/local/bin/codex"):
        mock_exec.return_value = DispatchResult(success=True, delivery_type="headless", engine="codex")
        res = send_message_to_agent(conv_id=None, text="Start server", target_engine="codex")
        assert res.success is True
        mock_exec.assert_called_once()
        args, kwargs = mock_exec.call_args
        prompt_called = args[0] if args else kwargs.get("prompt")
        assert prompt_called == "Start server"


def test_codex_voice_resolution():
    """Test voice persona resolver assigns Emma (en-US-EmmaNeural) to Codex."""
    cfg = VoiceFiConfig()
    engine_name, voice_name, rate = cfg.resolve_voice(agent_name="codex")
    assert engine_name == "edge_tts"
    assert voice_name == "en-US-EmmaNeural"

    engine_name, voice_name, rate = cfg.resolve_voice(agent_name="chatgpt")
    assert voice_name == "en-US-EmmaNeural"

    engine_name, voice_name, rate = cfg.resolve_voice(agent_name="openai")
    assert voice_name == "en-US-EmmaNeural"


def test_codex_stop_hook_skips_desktop_mic_for_mobile():
    """Test Codex stop hook skips Mac desktop mic auto-listen when turn originated from mobile companion."""
    mock_cfg = VoiceFiConfig()
    mock_cfg.enabled = True
    mock_cfg.hooks.enabled = True
    mock_cfg.hooks.codex = True
    if hasattr(mock_cfg, "codex"):
        mock_cfg.codex.read_summary_aloud = False
        mock_cfg.codex.auto_listen = True

    with patch("voicefi.integrations.codex.find_latest_codex_session", return_value=Path("/tmp/fake_codex.jsonl")), \
         patch("voicefi.integrations.codex.extract_latest_codex_summary", return_value="Refactoring complete."), \
         patch("voicefi.integrations.codex.claim_turn", return_value=True), \
         patch("voicefi.integrations.codex.pop_mobile_turn_origin", return_value=True), \
         patch("voicefi.integrations.codex.AudioRecorder") as mock_recorder:

        result = handle_codex_stop_hook({"thread_id": "test-uuid-1234"}, config=mock_cfg)
        assert result.get("status") == "mobile_handled"
        assert result.get("agent") == "codex"
        mock_recorder.assert_not_called()


def test_codex_stop_hook_canary_speaks_on_mac_when_mute_mac_false():
    """Test Codex stop hook speaks on Mac when mute_mac_when_companion_active is False (canary mode)."""
    mock_cfg = VoiceFiConfig()
    mock_cfg.enabled = True
    mock_cfg.hooks.enabled = True
    mock_cfg.hooks.codex = True
    mock_cfg.companion.mute_mac_when_companion_active = False
    if hasattr(mock_cfg, "codex"):
        mock_cfg.codex.read_summary_aloud = True
        mock_cfg.codex.auto_listen = False

    mock_engine = MagicMock()
    with patch("voicefi.integrations.codex.find_latest_codex_session", return_value=Path("/tmp/fake_codex.jsonl")), \
         patch("voicefi.integrations.codex.extract_latest_codex_summary", return_value="Why did Codex bring a map?"), \
         patch("voicefi.integrations.codex.claim_turn", return_value=True), \
         patch("voicefi.integrations.codex.pop_mobile_turn_origin", return_value=True), \
         patch("voicefi.audio.meeting_detection.is_user_on_call", return_value=False), \
         patch("voicefi.integrations.codex.get_tts_engine", return_value=mock_engine), \
         patch("voicefi.integrations.codex.set_cross_process_hud_state"):

        result = handle_codex_stop_hook({"thread_id": "test-uuid-5678"}, config=mock_cfg)
        assert result.get("status") != "mobile_handled"
        assert result.get("status") != "mac_muted"
        mock_engine.speak.assert_called_once()
        assert "Why did Codex bring a map" in mock_engine.speak.call_args[0][0]


def test_execute_codex_cli_invokes_stop_hook():
    """Test execute_codex_cli triggers handle_codex_stop_hook when CLI succeeds."""
    with patch("voicefi.integrations.codex.get_codex_cli_path", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run") as mock_run, \
         patch("voicefi.integrations.codex.handle_codex_stop_hook") as mock_hook:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"type": "task_complete", "payload": {"type": "task_complete", "last_agent_message": "All done!"}})
        mock_run.return_value = mock_proc

        res = execute_codex_cli("Tell a joke", async_execution=False)
        assert res.success is True
        mock_hook.assert_called_once()
        hook_payload = mock_hook.call_args[0][0]
        assert hook_payload.get("agent") == "codex"
        assert hook_payload.get("last-assistant-message") == "All done!"


def test_check_codex_session_turn_triggers_stop_hook(tmp_path):
    """Test _check_codex_session_turn triggers handle_codex_stop_hook if not already delivered via hook."""
    server = CompanionServer(config=VoiceFiConfig(), port=5141)
    session_file = tmp_path / "rollout-2026-09-23T10-00-00-12345678-1234-5678-1234-567812345678.jsonl"
    lines = [
        {"type": "session_meta", "payload": {"id": "12345678-1234-5678-1234-567812345678", "cwd": "/tmp"}},
        {"type": "event_msg", "payload": {"type": "task_complete", "last_agent_message": "Test response from codex."}},
    ]
    with open(session_file, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    with patch("voicefi.integrations.codex.handle_codex_stop_hook") as mock_hook, \
         patch.object(server, "broadcast_turn_completion") as mock_broadcast:
        server._check_codex_session_turn(session_file)
        time.sleep(0.1)
        mock_hook.assert_called_once()
        assert mock_hook.call_args[0][0]["agent"] == "codex"
        assert "Test response from codex" in mock_hook.call_args[0][0]["last-assistant-message"]
        mock_broadcast.assert_called_once()


class CodexCompanionServerTestCase(AioHTTPTestCase):
    """Integration test suite for CompanionServer Codex endpoints and TTS."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    async def test_api_conversations_includes_codex(self):
        """Test GET /api/conversations returns Codex conversations."""
        fake_codex = ConversationInfo(
            id="codex_12345678-1111-2222-3333-444444444444",
            title="Codex: Test Query",
            status="waiting_for_user",
            mtime=time.time() + 100.0,
            engine="codex",
            last_agent_text="Task finished.",
            last_user_text="Test Query",
        )
        with patch("voicefi.integrations.codex.find_recent_codex_sessions", return_value=[Path("/tmp/fake.jsonl")]), \
             patch("voicefi.integrations.codex.parse_codex_session", return_value=fake_codex):
            resp = await self.client.get("/api/conversations")
            assert resp.status == 200
            data = await resp.json()
            assert "conversations" in data
            codex_convs = [c for c in data["conversations"] if c.get("engine") == "codex"]
            assert len(codex_convs) >= 1
            assert any(c["id"] == "codex_12345678-1111-2222-3333-444444444444" for c in codex_convs)

    async def test_api_tts_codex_persona(self):
        """Test POST /api/tts with agent_role='codex' requests Emma persona."""
        mock_tts = MagicMock()

        async def fake_synth(text, path):
            Path(path).write_bytes(b"FAKE_AUDIO_CODEX")

        mock_tts.synthesize_to_file = fake_synth

        with patch("voicefi.companion.server.get_tts_engine", return_value=mock_tts) as mock_get_tts:
            resp = await self.client.post("/api/tts", json={
                "text": "Hello, OpenAI Codex is ready to execute code.",
                "agent_role": "codex",
            })
            assert resp.status == 200
            mock_get_tts.assert_called_once_with(self.companion_server.config, agent_name="codex")

    async def test_api_new_codex_conversation(self):
        """Test POST /api/conversation/new with engine='codex' calls execute_codex_cli."""
        mock_disp = DispatchResult(
            success=True,
            delivery_type="headless",
            target_conv_id="codex_new-session-uuid",
            engine="codex",
        )
        with patch("voicefi.integrations.codex.execute_codex_cli", return_value=mock_disp) as mock_exec, \
             patch("voicefi.integrations.codex.get_codex_cli_path", return_value="/usr/local/bin/codex"):
            resp = await self.client.post("/api/conversation/new", json={
                "prompt": "Start a new Codex task",
                "engine": "codex",
            })
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("conv_id") == "codex_new-session-uuid"
            mock_exec.assert_called_once()
            args, kwargs = mock_exec.call_args
            prompt_called = args[0] if args else kwargs.get("prompt")
            assert prompt_called == "Start a new Codex task"
            assert kwargs.get("origin") == "mobile"
