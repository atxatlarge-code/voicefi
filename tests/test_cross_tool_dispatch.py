"""
Comprehensive tests for Universal Cross-Tool & Cross-Agent Command Dispatch.

Covers:
1. Bidirectional Correlation Tracking and Automatic Reply Routing (Antigravity ↔ Claude).
2. Provenance Envelope Parsing and Executable Return Instruction Formatting.
3. Strict Fallback Isolation in agentapi IPC.
4. Standalone Third-Party Integration Client (REST and Stdio MCP modes).
5. CLI Command Dispatch (vifi send) and Comedy Duel Orchestration (vifi duel).
6. Zero-VoiceFi-Dependency Integrity Verification.
"""

import ast
import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from voicefi.integrations.injector import (
    DispatchResult,
    inject_text_to_claude,
    send_message_to_agent,
    send_message_to_antigravity,
)
from voicefi.integrations.conversations import (
    get_return_route,
    record_agent_route,
    _AGENT_ROUTES_FILE,
)
from examples.standalone_voicefi_client import (
    VoiceFiRestClient,
    VoiceFiMCPClient,
    run_integration_demo,
)


@pytest.fixture(autouse=True)
def clean_routes_file(tmp_path):
    """Ensure a clean test routes file for each test."""
    test_routes_file = tmp_path / "voicefi_agent_routes.json"
    with patch("voicefi.integrations.conversations._AGENT_ROUTES_FILE", test_routes_file):
        yield test_routes_file


# ============================================================================
# 1. Bidirectional Route Journal & Correlation Tracking Tests
# ============================================================================

def test_record_and_get_return_route_lifecycle(clean_routes_file):
    """Test recording agent routes and querying bidirectional return routes."""
    # 1. Initially empty
    assert get_return_route() is None
    assert get_return_route(target_engine="antigravity") is None

    # 2. Antigravity delegates to Claude
    record_agent_route(
        from_engine="antigravity",
        from_conv_id="conv-agy-001",
        to_engine="claude",
        to_conv_id="claude-session-99",
        metadata={"task": "refactor"},
    )

    # 3. Claude queries return route to reply to Antigravity
    route = get_return_route(target_engine="antigravity")
    assert route is not None
    assert route["from_engine"] == "antigravity"
    assert route["from_conv_id"] == "conv-agy-001"
    assert route["to_engine"] == "claude"
    assert route["metadata"]["task"] == "refactor"

    # 4. Claude sends a new task to Antigravity
    record_agent_route(
        from_engine="claude",
        from_conv_id="claude-session-99",
        to_engine="antigravity",
        to_conv_id="conv-agy-002",
    )

    # 5. Check specific engine queries
    cld_route = get_return_route(target_engine="claude")
    assert cld_route is not None
    assert cld_route["from_engine"] == "claude"
    assert cld_route["from_conv_id"] == "claude-session-99"

    agy_route = get_return_route(target_engine="antigravity")
    assert agy_route is not None
    assert agy_route["from_engine"] == "antigravity"
    assert agy_route["from_conv_id"] == "conv-agy-001"

    # 6. Default get_return_route() returns the latest route (claude -> antigravity)
    latest = get_return_route()
    assert latest is not None
    assert latest["from_engine"] == "claude"


def test_routes_file_expiration_and_limit(clean_routes_file):
    """Test routes journal caps at 20 entries and purges expired routes (>24h)."""
    now = time.time()
    old_time = now - 90000.0  # > 24 hours ago

    # Write old route directly
    initial = [
        {"from_engine": "antigravity", "from_conv_id": "expired-conv", "to_engine": "claude", "timestamp": old_time}
    ]
    clean_routes_file.write_text(json.dumps(initial))

    # Add 25 new routes
    for i in range(25):
        record_agent_route(
            from_engine="antigravity",
            from_conv_id=f"conv-{i}",
            to_engine="claude",
        )

    data = json.loads(clean_routes_file.read_text())
    assert len(data) == 20  # capped at 20
    # The expired route must be purged
    assert all(r["from_conv_id"] != "expired-conv" for r in data)
    assert data[-1]["from_conv_id"] == "conv-24"


def test_routes_file_corrupted_json_recovery(clean_routes_file):
    """Test routes journal recovers cleanly if the JSON file is corrupted."""
    clean_routes_file.write_text("{corrupted_json_data!!!")

    # Should not raise exception and should return None
    assert get_return_route() is None

    # Recording should overwrite/fix the file cleanly
    record_agent_route(
        from_engine="antigravity",
        from_conv_id="recovered-conv",
        to_engine="claude",
    )
    route = get_return_route()
    assert route is not None
    assert route["from_conv_id"] == "recovered-conv"


# ============================================================================
# 2. Provenance Envelope & Bidirectional Round-Trip Dispatch Tests
# ============================================================================

def test_provenance_envelope_content_and_formatting():
    """Verify the provenance envelope includes sender info, origin conv ID, and executable reply commands."""
    with patch("voicefi.integrations.injector.set_clipboard_text") as mock_clip, \
         patch("voicefi.integrations.injector.focus_terminal_app", return_value="Warp"), \
         patch("voicefi.integrations.conversations.record_agent_route") as mock_route, \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0, stdout="true")

        success = inject_text_to_claude(
            "Please review PR #42 and optimize DB queries.",
            from_conv_id="conv-agy-987654",
            from_engine="antigravity",
            include_envelope=True,
        )

        assert success is True
        mock_route.assert_called_once_with(
            from_engine="antigravity",
            from_conv_id="conv-agy-987654",
            to_engine="claude",
        )

        mock_clip.assert_called_once()
        text = mock_clip.call_args[0][0]

        # Check envelope header
        assert "[From: Antigravity | Conversation: conv-agy-987654]" in text
        assert "Please review PR #42 and optimize DB queries." in text

        # Check CLI reply command in envelope
        assert "vifi send --to antigravity --reply" in text

        # Check REST reply command in envelope
        assert "curl -s -X POST http://localhost:5141/api/send" in text
        assert "conv-agy-987654" in text


def test_end_to_end_bidirectional_dispatch_reply_loop(clean_routes_file):
    """
    Test complete round-trip loop:
    1. Antigravity dispatches task to Claude.
    2. Journal records the provenance route.
    3. Claude dispatches findings back with conv_id='reply'.
    4. Antigravity receives reply at the exact originating conversation ID.
    """
    # --- Step 1: Antigravity -> Claude ---
    with patch("voicefi.integrations.injector.set_clipboard_text", return_value=True) as mock_clip, \
         patch("voicefi.integrations.injector.focus_terminal_app", return_value="Ghostty"), \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0, stdout="true")

        res1 = send_message_to_agent(
            text="Perform security audit on auth middleware",
            target_engine="claude",
            from_conv_id="conv-agy-secure-101",
            from_engine="antigravity",
            include_envelope=True,
        )
        assert res1.success is True
        assert res1.engine == "claude"

        mock_clip.assert_called_once()
        clipped_text = mock_clip.call_args[0][0]
        assert "[From: Antigravity | Conversation: conv-agy-secure-101]" in clipped_text

    # Verify route was recorded in journal
    route = get_return_route(target_engine="antigravity")
    assert route is not None
    assert route["from_conv_id"] == "conv-agy-secure-101"

    # --- Step 2: Claude -> Antigravity (Reply) ---
    with patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True), \
         patch("subprocess.run") as mock_agentapi_run:

        mock_agentapi_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res2 = send_message_to_agent(
            conv_id="reply",
            text="Security audit complete: 0 vulnerabilities found.",
            sender_name="Claude",
            target_engine="antigravity",
        )

        assert res2.success is True
        assert res2.delivery_type == "ipc"
        assert res2.target_conv_id == "conv-agy-secure-101"

        mock_agentapi_run.assert_called_once()
        cmd = mock_agentapi_run.call_args[0][0]
        assert "send-message" in cmd
        assert "--title=Message from Claude" in cmd
        assert "conv-agy-secure-101" in cmd
        assert "Security audit complete: 0 vulnerabilities found." in cmd


def test_send_message_to_agent_engine_inference():
    """Test engine inference when target_engine is not explicitly passed."""
    # 1. Claude prefix in conv_id
    with patch("voicefi.integrations.injector.inject_text_to_claude", return_value=True) as mock_inj:
        res = send_message_to_agent(conv_id="claude_project_session_1", text="Hello Claude")
        assert res.success is True
        assert res.engine == "claude"
        mock_inj.assert_called_once()

    # 2. Antigravity UUID
    with patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        res = send_message_to_agent(conv_id="12345678-1234-1234-1234-123456789abc", text="Hello Ava")
        assert res.success is True
        assert res.engine == "antigravity"


def test_send_message_empty_text_returns_failure():
    """Test empty or whitespace text fails validation immediately."""
    res1 = send_message_to_agent(text="")
    assert res1.success is False
    assert "Empty message text" in str(res1.error)

    res2 = send_message_to_agent(text="   \n  ")
    assert res2.success is False
    assert "Empty message text" in str(res2.error)

    res3 = send_message_to_antigravity(text="")
    assert res3.success is False
    assert "Empty message text" in str(res3.error)


# ============================================================================
# 3. CLI Command Dispatch & Comedy Duel Verification
# ============================================================================

def test_cli_cmd_send_standard_and_reply(clean_routes_file):
    """Test vifi send CLI command with flags, reply routing, and telemetry."""
    from voicefi.cli import cmd_send
    import argparse

    # Test 1: Standard send to claude
    args1 = argparse.Namespace(
        text=["Run", "unit", "tests"],
        to="claude",
        conv_id=None,
        reply=False,
        from_conv_id="conv-origin-42",
        from_engine="antigravity",
        sender_name="Antigravity",
        title="Test Task",
        no_envelope=False,
    )

    with patch("voicefi.integrations.injector.send_message_to_agent", return_value=DispatchResult(success=True)) as mock_send, \
         patch("voicefi.telemetry.capture_agent_dispatch") as mock_telem:

        cmd_send(args1)
        mock_send.assert_called_once_with(
            conv_id=None,
            text="Run unit tests",
            sender_name="Antigravity",
            title="Test Task",
            target_engine="claude",
            from_conv_id="conv-origin-42",
            from_engine="antigravity",
            include_envelope=True,
        )
        mock_telem.assert_called_once()

    # Test 2: Reply flag sets conv_id='reply'
    args2 = argparse.Namespace(
        text=["All", "tests", "passed"],
        to="antigravity",
        conv_id=None,
        reply=True,
        from_conv_id=None,
        from_engine="claude",
        sender_name="Claude",
        title=None,
        no_envelope=True,
    )

    with patch("voicefi.integrations.injector.send_message_to_agent", return_value=DispatchResult(success=True)) as mock_send, \
         patch("voicefi.telemetry.capture_agent_dispatch"):

        cmd_send(args2)
        mock_send.assert_called_once_with(
            conv_id="reply",
            text="All tests passed",
            sender_name="Claude",
            title=None,
            target_engine="antigravity",
            from_conv_id=None,
            from_engine="claude",
            include_envelope=False,
        )


def test_cli_cmd_duel_orchestration():
    """Test vifi duel comedy banter orchestrates Ava, Steffan, SFX, and live dispatch."""
    from voicefi.cli import cmd_duel
    import argparse

    args = argparse.Namespace(turns=3, live=True)

    mock_tts_agy = MagicMock()
    mock_tts_cld = MagicMock()

    def _get_tts(cfg, agent_name="antigravity", **kwargs):
        return mock_tts_agy if agent_name == "antigravity" else mock_tts_cld

    with patch("voicefi.config.load_config"), \
         patch("voicefi.tts.get_tts_engine", side_effect=_get_tts), \
         patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx, \
         patch("voicefi.integrations.injector.send_message_to_agent") as mock_live_send, \
         patch("time.sleep"):

        cmd_duel(args)

        # Ava spoke 3 times, Steffan spoke 3 times
        assert mock_tts_agy.speak.call_count == 3
        assert mock_tts_cld.speak.call_count == 3

        # SFX played for all 3 rounds: drum_smash, honk, applause
        assert mock_sfx.call_count == 3
        sfx_names = [call[0][0] for call in mock_sfx.call_args_list]
        assert sfx_names == ["drum_smash", "honk", "applause"]

        # Live dispatch sent prompts to Claude
        assert mock_live_send.call_count == 3
        for call in mock_live_send.call_args_list:
            assert call.kwargs.get("target_engine") == "claude"
            assert call.kwargs.get("include_envelope") is True


# ============================================================================
# 4. Standalone Integration Client (examples/standalone_voicefi_client.py) Tests
# ============================================================================

def test_standalone_rest_client_operations():
    """Test VoiceFiRestClient methods against simulated HTTP responses."""
    client = VoiceFiRestClient(host="127.0.0.1", port=5141, timeout=5.0)

    # 1. status()
    with patch("urllib.request.urlopen", side_effect=lambda req, **kwargs: io.BytesIO(b'{"status": "online", "input_device": "Mic", "output_device": "Speaker"}')):
        res = client.status()
        assert res.get("status") == "online"
        assert res.get("input_device") == "Mic"

    # 2. speak()
    with patch("urllib.request.urlopen", side_effect=lambda req, **kwargs: io.BytesIO(b'{"status": "ok", "text": "Hello World"}')):
        res = client.speak("Hello World", voice="Viv", conv_id="conv-123")
        assert res.get("status") == "ok"

    # 3. sfx()
    with patch("urllib.request.urlopen", side_effect=lambda req, **kwargs: io.BytesIO(b'{"status": "ok", "sfx": "drum_smash"}')):
        res = client.sfx("drum_smash", volume=0.8)
        assert res.get("status") == "ok"

    # 4. send() standard
    with patch("urllib.request.urlopen", side_effect=lambda req, **kwargs: io.BytesIO(b'{"success": true, "delivered": true, "delivered_ipc": true}')):
        res = client.send("Deploy updates", to="antigravity", title="Deploy")
        assert res.get("success") is True
        assert res.get("delivered") is True

    # 5. send() with reply=True
    with patch("urllib.request.urlopen", side_effect=lambda req, **kwargs: io.BytesIO(b'{"success": true, "delivered": true, "delivered_ipc": true}')):
        res = client.send("Reply text", to="claude", reply=True)
        assert res.get("success") is True

    # 6. stop()
    with patch("urllib.request.urlopen", side_effect=lambda req, **kwargs: io.BytesIO(b'{"status": "ok", "stopped": true}')):
        res = client.stop()
        assert res.get("stopped") is True


def test_standalone_rest_client_error_handling():
    """Test VoiceFiRestClient handles HTTP errors, connection refused, and timeouts."""
    client = VoiceFiRestClient(host="127.0.0.1", port=5141, timeout=2.0)

    # 1. HTTP 400 with JSON error body
    err_body = io.BytesIO(b'{"error": "Missing or empty text field"}')
    http_err = urllib.error.HTTPError("http://127.0.0.1:5141/api/speak", 400, "Bad Request", {}, err_body)
    with patch("urllib.request.urlopen", side_effect=http_err):
        res = client.speak("")
        assert "Missing or empty text field" in res.get("error", "")
        assert res.get("http_code") == 400

    # 2. Connection Refused (URLError)
    url_err = urllib.error.URLError("Connection refused")
    with patch("urllib.request.urlopen", side_effect=url_err):
        res = client.status()
        assert "Connection failed" in res.get("error", "")
        assert res.get("connection_error") is True


def test_standalone_mcp_client_operations():
    """Test VoiceFiMCPClient JSON-RPC handshake and tool calling via mock pipes."""
    client = VoiceFiMCPClient(command=["mock_vifi", "mcp"], timeout=5.0)

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.stdin = MagicMock()

    # Pre-populate JSON-RPC response sequence
    responses = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "voicefi"}, "capabilities": {"tools": {}}}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "voicefi_speak"}, {"name": "voicefi_sfx"}, {"name": "voicefi_send"}, {"name": "voicefi_status"}]}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "Synthesized OK"}], "isError": False}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 4, "result": {"content": [{"type": "text", "text": "Played SFX OK"}], "isError": False}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 5, "result": {"content": [{"type": "text", "text": "Dispatched OK"}], "isError": False}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 6, "result": {"content": [{"type": "text", "text": "Status OK"}], "isError": False}}) + "\n",
    ]
    mock_proc.stdout.readline.side_effect = responses

    with patch("subprocess.Popen", return_value=mock_proc):
        with client:
            # 1. List tools
            tools = client.list_tools()
            assert len(tools) == 4
            assert tools[0]["name"] == "voicefi_speak"

            # 2. Speak
            sp_res = client.speak("Hello from MCP", persona="Viv")
            assert sp_res["isError"] is False
            assert "Synthesized OK" in sp_res["content"][0]["text"]

            # 3. SFX
            sfx_res = client.sfx("applause", volume=0.9)
            assert sfx_res["isError"] is False

            # 4. Send
            send_res = client.send("Task prompt", to="antigravity", reply=True, title="MCP Task")
            assert send_res["isError"] is False

            # 5. Status
            st_res = client.status()
            assert st_res["isError"] is False

    mock_proc.terminate.assert_called_once()


def test_standalone_demo_routine():
    """Test run_integration_demo across REST and MCP paths."""
    # 1. REST Demo
    with patch.object(VoiceFiRestClient, "status", return_value={"status": "online"}), \
         patch.object(VoiceFiRestClient, "speak", return_value={"status": "ok"}), \
         patch.object(VoiceFiRestClient, "sfx", return_value={"status": "ok"}), \
         patch.object(VoiceFiRestClient, "send", return_value={"success": True}), \
         patch.object(VoiceFiRestClient, "stop", return_value={"stopped": True}):

        success = run_integration_demo(mode="rest")
        assert success is True

    # 2. MCP Demo
    with patch.object(VoiceFiMCPClient, "start"), \
         patch.object(VoiceFiMCPClient, "close"), \
         patch.object(VoiceFiMCPClient, "list_tools", return_value=[{"name": "voicefi_speak"}, {"name": "voicefi_sfx"}]), \
         patch.object(VoiceFiMCPClient, "status", return_value={"content": [{"type": "text", "text": "{}"}]}), \
         patch.object(VoiceFiMCPClient, "speak", return_value={"isError": False}), \
         patch.object(VoiceFiMCPClient, "sfx", return_value={"isError": False}), \
         patch.object(VoiceFiMCPClient, "send", return_value={"isError": False}):

        success = run_integration_demo(mode="mcp")
        assert success is True


def test_standalone_client_cli_entrypoint_subprocess():
    """Test executing standalone_voicefi_client.py via CLI subprocess."""
    client_script = Path(__file__).parent.parent / "examples" / "standalone_voicefi_client.py"
    assert client_script.is_file()

    # Test --help
    res = subprocess.run(
        [sys.executable, str(client_script), "--help"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert res.returncode == 0
    assert "Standalone VoiceFi Third-Party Integration Client" in res.stdout
    assert "--mode" in res.stdout
    assert "--speak" in res.stdout
    assert "--send" in res.stdout
    assert "--sfx" in res.stdout


def test_standalone_client_zero_internal_dependencies_integrity():
    """
    Forensic integrity check: Verify examples/standalone_voicefi_client.py contains
    ZERO imports from 'voicefi' or external packages. Only stdlib permitted.
    """
    client_script = Path(__file__).parent.parent / "examples" / "standalone_voicefi_client.py"
    content = client_script.read_text()
    tree = ast.parse(content, filename=str(client_script))

    stdlib_modules = {
        "argparse", "json", "os", "shutil", "subprocess",
        "sys", "time", "typing", "urllib",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0]
                assert root_pkg in stdlib_modules, f"Disallowed import: {alias.name}"
                assert "voicefi" not in alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0]
                assert root_pkg in stdlib_modules, f"Disallowed from-import: {node.module}"
                assert "voicefi" not in node.module
