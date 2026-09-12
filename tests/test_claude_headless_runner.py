"""
Unit and integration tests for ClaudeHeadlessRunner in VoiceFi.
Validates zero-flicker headless execution, token resolution tiers,
per-conversation serialization locks, session targeting, and Antigravity isolation.
"""

import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from voicefi.config import VoiceFiConfig
from voicefi.integrations.claude_runner import (
    ClaudeHeadlessRunner,
    find_claude_binary,
    normalize_claude_conv_id,
    resolve_claude_auth_token,
)
from voicefi.integrations.injector import DispatchResult, send_message_to_agent


def test_normalize_claude_conv_id():
    """Test conversation ID normalization between VoiceFi format and Claude CLI UUID."""
    # 1. New conversation (None, empty, or "new")
    cid1, raw1, is_new1 = normalize_claude_conv_id(None)
    assert is_new1 is True
    assert cid1 == f"claude_{raw1}"
    assert uuid.UUID(raw1)  # Must be valid UUID

    cid2, raw2, is_new2 = normalize_claude_conv_id("new")
    assert is_new2 is True
    assert cid2 == f"claude_{raw2}"

    # 2. Existing standard UUID with prefix
    test_uuid = "2f480db0-c98d-4367-ad09-5ba8b89fff02"
    cid3, raw3, is_new3 = normalize_claude_conv_id(f"claude_{test_uuid}")
    assert is_new3 is False
    assert raw3 == test_uuid
    assert cid3 == f"claude_{test_uuid}"

    # 3. Existing standard UUID without prefix
    cid4, raw4, is_new4 = normalize_claude_conv_id(test_uuid)
    assert is_new4 is False
    assert raw4 == test_uuid
    assert cid4 == f"claude_{test_uuid}"

    # 4. Custom named slug
    cid5, raw5, is_new5 = normalize_claude_conv_id("my-custom-task")
    assert is_new5 is False
    assert cid5 == f"claude_{raw5}"
    assert uuid.UUID(raw5)


def test_resolve_claude_auth_token_env_precedence(monkeypatch):
    """Test that environment variables take top priority in auth token resolution."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-test-env-token")
    token = resolve_claude_auth_token()
    assert token == "sk-ant-test-env-token"


def test_resolve_claude_auth_token_config_override(monkeypatch):
    """Test that config token is used when env var is absent."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    cfg = VoiceFiConfig()
    cfg.claude.oauth_token = "sk-ant-config-token"

    token = resolve_claude_auth_token(config=cfg)
    assert token == "sk-ant-config-token"


def test_headless_runner_dispatch_new_conversation():
    """Test dispatching a new conversation launches claude with --session-id."""
    runner = ClaudeHeadlessRunner.get_instance()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = '{"is_error": false, "result": "I am ready to help."}'
    mock_proc.stderr = ""

    with patch("voicefi.integrations.claude_runner.find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch("voicefi.integrations.claude_runner.resolve_claude_auth_token", return_value="sk-ant-fake-token"), \
         patch("subprocess.run", return_value=mock_proc) as mock_run:

        res = runner.dispatch(text="Start working", conv_id=None)

        assert res.success is True
        assert res.delivery_type == "headless"
        assert res.target_conv_id.startswith("claude_")
        assert res.engine == "claude"

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--session-id" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "Start working" in cmd


def test_headless_runner_dispatch_resume_conversation():
    """Test dispatching an existing conversation launches claude with --resume."""
    runner = ClaudeHeadlessRunner.get_instance()
    test_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = '{"is_error": false, "result": "Continuing task."}'
    mock_proc.stderr = ""

    with patch("voicefi.integrations.claude_runner.find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch("voicefi.integrations.claude_runner.resolve_claude_auth_token", return_value="sk-ant-fake-token"), \
         patch("subprocess.run", return_value=mock_proc) as mock_run:

        res = runner.dispatch(text="Continue working", conv_id=f"claude_{test_uuid}")

        assert res.success is True
        assert res.delivery_type == "headless"
        assert res.target_conv_id == f"claude_{test_uuid}"

        claude_calls = [call[0][0] for call in mock_run.call_args_list if call[0] and call[0][0] and call[0][0][0] == "/usr/local/bin/claude"]
        assert len(claude_calls) >= 1
        cmd = claude_calls[0]
        assert "--resume" in cmd
        assert test_uuid in cmd


def test_headless_runner_per_conversation_lock():
    """Test that two rapid dispatches to the same conversation ID are serialized."""
    runner = ClaudeHeadlessRunner.get_instance()
    test_uuid = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    conv_id = f"claude_{test_uuid}"

    execution_order = []

    def slow_subprocess(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if cmd and cmd[0] == "/usr/local/bin/claude":
            execution_order.append("start")
            time.sleep(0.1)
            execution_order.append("end")
        m = MagicMock()
        m.returncode = 0
        m.stdout = '{"is_error": false, "result": "Done"}'
        m.stderr = ""
        return m

    with patch("voicefi.integrations.claude_runner.find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch("voicefi.integrations.claude_runner.resolve_claude_auth_token", return_value="sk-ant-fake-token"), \
         patch("subprocess.run", side_effect=slow_subprocess):

        t1 = threading.Thread(target=runner.dispatch, kwargs={"text": "Turn 1", "conv_id": conv_id})
        t2 = threading.Thread(target=runner.dispatch, kwargs={"text": "Turn 2", "conv_id": conv_id})

        t1.start()
        t2.start()
        t1.join()
        t2.join()

    # Must be serialized: start, end, start, end (not start, start, end, end)
    assert execution_order == ["start", "end", "start", "end"]


def test_headless_runner_timeout_handling():
    """Test that a hanging Claude subprocess triggers timeout cleanly."""
    runner = ClaudeHeadlessRunner.get_instance()

    with patch("voicefi.integrations.claude_runner.find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch("voicefi.integrations.claude_runner.resolve_claude_auth_token", return_value="sk-ant-fake-token"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=5)):

        res = runner.dispatch(text="Slow prompt", conv_id=None, timeout=5)

        assert res.success is False
        assert "timed out after 5 seconds" in res.error


def test_headless_runner_missing_auth_token_diagnostics(monkeypatch):
    """Test helpful diagnostic message when no auth token is resolved."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    runner = ClaudeHeadlessRunner.get_instance()

    with patch("voicefi.integrations.claude_runner.find_claude_binary", return_value="/usr/local/bin/claude"), \
         patch("voicefi.integrations.claude_runner.resolve_claude_auth_token", return_value=None):

        mock_fail = MagicMock()
        mock_fail.returncode = 1
        mock_fail.stdout = "Not logged in. Please run /login"
        mock_fail.stderr = ""

        with patch("subprocess.run", return_value=mock_fail):
            res = runner.dispatch(text="Hello", conv_id=None)
            assert res.success is False
            assert "authentication required" in res.error.lower()


def test_antigravity_isolation_intact():
    """Verify Antigravity routing remains 100% untouched and isolated."""
    with patch("voicefi.integrations.injector.send_message_to_antigravity") as mock_ag, \
         patch("voicefi.integrations.claude_runner.ClaudeHeadlessRunner.dispatch") as mock_claude:

        mock_ag.return_value = DispatchResult(success=True, engine="antigravity", delivery_type="ipc")

        # 1. Antigravity engine
        res1 = send_message_to_agent(conv_id="agy-12345", text="Inspect code", target_engine="antigravity")
        assert res1.success is True
        mock_ag.assert_called_once()
        mock_claude.assert_not_called()

    with patch("voicefi.integrations.injector.send_message_to_antigravity") as mock_ag, \
         patch("voicefi.integrations.claude_runner.ClaudeHeadlessRunner.dispatch") as mock_claude:

        mock_ag.return_value = DispatchResult(success=True, engine="antigravity", delivery_type="ipc")

        # 2. Inferred from Antigravity UUID format
        res2 = send_message_to_agent(conv_id="12345678-1234-1234-1234-123456789abc", text="Check health")
        assert res2.success is True
        mock_ag.assert_called_once()
        mock_claude.assert_not_called()