"""
Adversarial Challenge & Stress Test Suite for Milestone M3:
Universal Cross-Tool & Cross-Agent Command Dispatch.

Challenges:
1. Multi-turn cross-agent ping-pong loops (Antigravity <-> Claude Code) with correlation ID tracking.
2. Route journal recovery under concurrent writes, corrupted JSON files, and expired records.
3. Execution of `examples/standalone_voicefi_client.py` across diverse CLI arguments, REST timeouts, and MCP stdio pipe terminations.
"""

import ast
import concurrent.futures
import io
import json
import os
import subprocess
import sys
import threading
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
    main as standalone_main,
)


@pytest.fixture
def clean_test_routes(tmp_path):
    """Provide an isolated, clean routes journal file for testing."""
    test_file = tmp_path / "voicefi_agent_routes.json"
    with patch("voicefi.integrations.conversations._AGENT_ROUTES_FILE", test_file):
        yield test_file


# ============================================================================
# Challenge 1: Multi-Turn Cross-Agent Ping-Pong Loops with Correlation Tracking
# ============================================================================

def test_adversarial_10_turn_ping_pong_correlation(clean_test_routes):
    """
    Stress-test a 10-turn alternating dialog between Antigravity and Claude Code.
    Verifies that bidirectional correlation tracking correctly alternates routes
    and resolves `conv_id='reply'` at each turn without losing origin attribution.
    """
    agy_conv_id = "conv-agy-session-alpha-999"
    claude_conv_id = "conv-claude-session-beta-888"

    agentapi_calls = []
    clipboard_calls = []

    def mock_subprocess_dispatch(cmd, **kwargs):
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if "osascript" in cmd_str:
            return MagicMock(returncode=0, stdout="true", stderr="")
        if "agentapi" in cmd_str:
            agentapi_calls.append(cmd)
            return MagicMock(returncode=0, stdout="", stderr="")
        return MagicMock(returncode=0, stdout="true", stderr="")

    def mock_pbcopy(text):
        clipboard_calls.append(text)
        return True

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True), \
         patch("subprocess.run", side_effect=mock_subprocess_dispatch), \
         patch("voicefi.integrations.injector.set_clipboard_text", side_effect=mock_pbcopy), \
         patch("voicefi.integrations.injector.focus_terminal_app", return_value="Ghostty"):

        for turn in range(1, 11):
            if turn % 2 == 1:
                # Odd turns: Antigravity -> Claude
                res = send_message_to_agent(
                    text=f"Turn {turn}: Antigravity task dispatch payload",
                    target_engine="claude",
                    from_conv_id=agy_conv_id,
                    from_engine="antigravity",
                    include_envelope=True,
                )
                assert res.success is True
                assert res.engine == "claude"

                # Verify Claude can find return route to Antigravity
                route = get_return_route(target_engine="antigravity")
                assert route is not None
                assert route["from_conv_id"] == agy_conv_id
                assert route["from_engine"] == "antigravity"
            else:
                # Even turns: Claude -> Antigravity (using reply)
                res = send_message_to_agent(
                    conv_id="reply",
                    text=f"Turn {turn}: Claude findings response payload",
                    sender_name="Claude",
                    target_engine="antigravity",
                    from_conv_id=claude_conv_id,
                )
                assert res.success is True
                assert res.delivery_type == "ipc"
                assert res.target_conv_id == agy_conv_id

                # Verify Antigravity can find return route to Claude
                route = get_return_route(target_engine="claude")
                assert route is not None
                assert route["from_conv_id"] == claude_conv_id
                assert route["from_engine"] == "claude"

    # Verify all 5 Antigravity -> Claude injections contained proper provenance envelopes
    assert len(clipboard_calls) == 5
    for i, clip_text in enumerate(clipboard_calls):
        assert f"[From: Antigravity | Conversation: {agy_conv_id}]" in clip_text
        assert f"Turn {i*2 + 1}: Antigravity task dispatch payload" in clip_text
        assert "vifi send --to antigravity --reply" in clip_text

    # Verify all 5 Claude -> Antigravity IPC dispatches targeted the correct conversation
    assert len(agentapi_calls) == 5
    for i, cmd in enumerate(agentapi_calls):
        assert "send-message" in cmd
        assert agy_conv_id in cmd
        assert f"Turn {(i+1)*2}: Claude findings response payload" in cmd


def test_adversarial_multi_conversation_interleaved_routes(clean_test_routes):
    """
    Stress-test route resolution when multiple conversations interleave calls.
    Verifies that target_engine filtering correctly isolates the latest origin.
    """
    # 1. Thread A: Antigravity-1 -> Claude
    record_agent_route("antigravity", "conv-agy-1", "claude")
    # 2. Thread B: Mobile -> Antigravity
    record_agent_route("mobile", "conv-mob-1", "antigravity")
    # 3. Thread C: Antigravity-2 -> Claude
    record_agent_route("antigravity", "conv-agy-2", "claude")
    # 4. Thread D: Claude -> Antigravity
    record_agent_route("claude", "session-cld-1", "antigravity")

    # Claude queries return route to reply to Antigravity -> should get conv-agy-2
    agy_route = get_return_route(target_engine="antigravity")
    assert agy_route is not None
    assert agy_route["from_conv_id"] == "conv-agy-2"

    # Antigravity queries return route to reply to Claude -> should get session-cld-1
    cld_route = get_return_route(target_engine="claude")
    assert cld_route is not None
    assert cld_route["from_conv_id"] == "session-cld-1"

    # Query for mobile origin
    mob_route = get_return_route(target_engine="mobile")
    assert mob_route is not None
    assert mob_route["from_conv_id"] == "conv-mob-1"


def test_adversarial_unroutable_reply_fallback(clean_test_routes):
    """
    Test when conv_id='reply' is requested but no route exists in journal.
    Verifies it gracefully falls back to latest active conversation without crashing.
    """
    # 1. With no routes in journal, unroutable reply passes literal 'reply'
    with patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True), \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0)

        res = send_message_to_agent(
            conv_id="reply",
            text="Testing unroutable reply fallback",
            target_engine="antigravity",
        )
        assert res.success is True
        assert res.target_conv_id == "reply"

    # 2. Once a route is recorded, conv_id='reply' resolves to originating conversation
    record_agent_route("antigravity", "conv-origin-777", "claude")
    with patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True), \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0)

        res2 = send_message_to_agent(
            conv_id="reply",
            text="Testing routed reply",
            target_engine="antigravity",
        )
        assert res2.success is True
        assert res2.target_conv_id == "conv-origin-777"


def test_adversarial_payload_characters_and_formatting():
    """
    Test sending prompts with complex Unicode, emojis, newlines, quotes, and markdown.
    """
    complex_text = """🚀 Deploy PR #42: "Fix O(n^2) regex in `auth.py`"
Line 1: 100% verified.
Line 2: 'Single quotes' & "Double quotes" & `code blocks`
Special chars: <>&;|$!*{}[]()~
"""
    with patch("voicefi.integrations.injector.set_clipboard_text") as mock_clip, \
         patch("voicefi.integrations.injector.focus_terminal_app", return_value="Ghostty"), \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0, stdout="true")

        success = inject_text_to_claude(
            complex_text,
            from_conv_id="conv-unicode-test",
            from_engine="antigravity",
            include_envelope=True,
        )
        assert success is True
        mock_clip.assert_called_once()
        text = mock_clip.call_args[0][0]
        assert "🚀 Deploy PR #42" in text
        assert "Special chars: <>&;|$!*{}[]()~" in text


# ============================================================================
# Challenge 2: Route Journal Recovery Under Concurrency & Corruption
# ============================================================================

def test_adversarial_concurrent_journal_writes(clean_test_routes):
    """
    Stress-test route journal under 50 concurrent thread writes.
    Verifies that file locking and exception handling prevent corrupted JSON.
    """
    num_threads = 50

    def worker(idx):
        record_agent_route(
            from_engine="antigravity" if idx % 2 == 0 else "claude",
            from_conv_id=f"concurrent-conv-{idx}",
            to_engine="claude" if idx % 2 == 0 else "antigravity",
            metadata={"worker_index": idx, "time": time.time()},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()  # Should not raise any unhandled exceptions

    assert clean_test_routes.is_file()
    content = clean_test_routes.read_text()
    data = json.loads(content)
    assert isinstance(data, list)
    assert len(data) <= 20  # Capped at 20 entries
    assert len(data) > 0

    # Ensure all entries are well-formed
    for entry in data:
        assert "from_engine" in entry
        assert "from_conv_id" in entry
        assert "to_engine" in entry
        assert "timestamp" in entry


@pytest.mark.parametrize("corrupted_content", [
    "{incomplete_json_object: true,",
    "[\n  {\"from_engine\": \"antigravity\",\n",
    "\x00\x00\xff\xfe\x12\x34",
    "",
    "   \n\t  ",
    "\"a plain json string\"",
    "123456789",
    "true",
    "{\"dict_instead_of_list\": true}",
])
def test_adversarial_corrupted_journal_recovery_scenarios(clean_test_routes, corrupted_content):
    """
    Test route journal self-healing across 9 distinct corrupted or invalid file states.
    """
    clean_test_routes.write_text(corrupted_content)

    # 1. get_return_route() must return None without raising an exception
    route = get_return_route()
    assert route is None

    # 2. record_agent_route() must successfully overwrite the corrupted file with valid JSON
    record_agent_route(
        from_engine="antigravity",
        from_conv_id="recovered-session-ok",
        to_engine="claude",
    )

    # 3. Subsequent reads must work cleanly
    route_after = get_return_route()
    assert route_after is not None
    assert route_after["from_conv_id"] == "recovered-session-ok"
    assert route_after["from_engine"] == "antigravity"

    # 4. File on disk must be valid JSON list
    data = json.loads(clean_test_routes.read_text())
    assert isinstance(data, list)
    assert len(data) == 1


def test_adversarial_route_expiration_and_sliding_window(clean_test_routes):
    """
    Test routes older than 24 hours (86400s) are automatically pruned upon new writes,
    and verify the sliding window retention limit of 20 entries.
    """
    now = time.time()
    stale_records = [
        {"from_engine": "antigravity", "from_conv_id": f"stale-{i}", "to_engine": "claude", "timestamp": now - 100000.0}
        for i in range(10)
    ]
    fresh_records = [
        {"from_engine": "claude", "from_conv_id": f"fresh-{i}", "to_engine": "antigravity", "timestamp": now - 3600.0}
        for i in range(5)
    ]
    clean_test_routes.write_text(json.dumps(stale_records + fresh_records))

    # Add 20 new records
    for i in range(20):
        record_agent_route("antigravity", f"new-{i}", "claude")

    data = json.loads(clean_test_routes.read_text())
    assert len(data) == 20
    # All stale records must be purged
    assert not any("stale-" in r["from_conv_id"] for r in data)
    # The newest records must be present
    assert data[-1]["from_conv_id"] == "new-19"


# ============================================================================
# Challenge 3: Standalone Client CLI, REST, & MCP Stdio Adversarial Stress
# ============================================================================

def test_adversarial_standalone_rest_client_timeouts_and_http_errors():
    """
    Stress-test VoiceFiRestClient handling timeouts, HTTP 500, HTTP 502, and bad payloads.
    """
    client = VoiceFiRestClient(host="127.0.0.1", port=5141, timeout=0.5)

    # 1. Socket Timeout
    timeout_err = urllib.error.URLError("timed out")
    with patch("urllib.request.urlopen", side_effect=timeout_err):
        res = client.status()
        assert "timed out" in res.get("error", "")
        assert res.get("connection_error") is True

    # 2. HTTP 500 with HTML error response
    html_err_body = io.BytesIO(b"<html><body>500 Internal Server Error</body></html>")
    http_500 = urllib.error.HTTPError("http://127.0.0.1:5141/api/speak", 500, "Internal Server Error", {}, html_err_body)
    with patch("urllib.request.urlopen", side_effect=http_500):
        res = client.speak("Test text")
        assert res.get("http_code") == 500
        assert "500" in res.get("error", "")

    # 3. HTTP 502 Bad Gateway
    http_502 = urllib.error.HTTPError("http://127.0.0.1:5141/api/sfx", 502, "Bad Gateway", {}, io.BytesIO(b"Bad Gateway"))
    with patch("urllib.request.urlopen", side_effect=http_502):
        res = client.sfx("drum_smash")
        assert res.get("http_code") == 502

    # 4. HTTP 404 Endpoint Not Found
    http_404 = urllib.error.HTTPError("http://127.0.0.1:5141/api/send", 404, "Not Found", {}, io.BytesIO(b'{"error": "Endpoint not found"}'))
    with patch("urllib.request.urlopen", side_effect=http_404):
        res = client.send("Task prompt")
        assert res.get("http_code") == 404
        assert "Endpoint not found" in res.get("error", "")


def test_adversarial_standalone_mcp_client_pipe_terminations_and_errors():
    """
    Stress-test VoiceFiMCPClient against abrupt pipe terminations, stderr crash logs, and JSON-RPC errors.
    """
    # 1. Server terminates abruptly during request
    client1 = VoiceFiMCPClient(command=["mock_vifi", "mcp"], timeout=1.0)
    mock_proc_crash = MagicMock()
    mock_proc_crash.poll.return_value = 1
    mock_proc_crash.returncode = 1
    mock_proc_crash.stderr.read.return_value = "Fatal: Port 5141 binding collision"
    mock_proc_crash.stdin = MagicMock()

    with patch("subprocess.Popen", return_value=mock_proc_crash):
        with pytest.raises(RuntimeError) as exc_info:
            client1.start()
        assert "MCP server terminated unexpectedly" in str(exc_info.value)
        assert "Port 5141 binding collision" in str(exc_info.value)

    # 2. JSON-RPC error response payload
    client2 = VoiceFiMCPClient(command=["mock_vifi", "mcp"], timeout=1.0)
    mock_proc_err = MagicMock()
    mock_proc_err.poll.return_value = None
    mock_proc_err.stdin = MagicMock()
    responses = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "voicefi"}}}) + "\n",
        json.dumps({"jsonrpc": "2.0", "id": 2, "error": {"code": -32602, "message": "Invalid params"}}) + "\n",
    ]
    mock_proc_err.stdout.readline.side_effect = responses

    with patch("subprocess.Popen", return_value=mock_proc_err):
        with client2:
            res = client2.call_tool("voicefi_speak", {"invalid": "param"})
            assert res.get("isError") is True
            assert res.get("error", {}).get("message") == "Invalid params"

    # 3. Timeout when server hangs
    client3 = VoiceFiMCPClient(command=["mock_vifi", "mcp"], timeout=0.3)
    mock_proc_hang = MagicMock()
    mock_proc_hang.poll.return_value = None
    mock_proc_hang.stdin = MagicMock()
    
    def _hang_readline():
        yield json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "voicefi"}}}) + "\n"
        while True:
            yield ""

    mock_proc_hang.stdout.readline.side_effect = _hang_readline()

    with patch("subprocess.Popen", return_value=mock_proc_hang):
        with client3:
            with pytest.raises(TimeoutError) as exc_timeout:
                client3.call_tool("voicefi_sfx", {"name": "drum_smash"})
            assert "timed out" in str(exc_timeout.value)


def test_adversarial_standalone_client_cli_argparse_variations():
    """
    Test standalone_voicefi_client.py across a matrix of diverse CLI argument combinations.
    """
    cli_test_cases = [
        # Case 1: Status query in rest mode
        (["--mode", "rest", "--status"], 0),
        # Case 2: Speak text with custom persona and conversation id
        (["--mode", "rest", "--speak", "Hello adversarial tester", "--persona", "Ava (Premium)", "--conv-id", "test-123"], 0),
        # Case 3: SFX playback with custom volume
        (["--mode", "rest", "--sfx", "drum_smash", "--volume", "1.5"], 0),
        # Case 4: Send task to claude with title and custom sender
        (["--mode", "rest", "--send", "Audit PR #99", "--to", "claude", "--title", "Security", "--sender", "AuditBot"], 0),
        # Case 5: Send reply to antigravity
        (["--mode", "rest", "--send", "Reply from audit", "--to", "antigravity", "--reply"], 0),
        # Case 6: Stop audio command
        (["--mode", "rest", "--stop"], 0),
        # Case 7: Invalid mode argument -> should exit code 2 (argparse error)
        (["--mode", "invalid_proto", "--status"], 2),
    ]

    for args_list, expected_code in cli_test_cases:
        with patch.object(VoiceFiRestClient, "status", return_value={"status": "online"}), \
             patch.object(VoiceFiRestClient, "speak", return_value={"status": "ok"}), \
             patch.object(VoiceFiRestClient, "sfx", return_value={"status": "ok"}), \
             patch.object(VoiceFiRestClient, "send", return_value={"success": True}), \
             patch.object(VoiceFiRestClient, "stop", return_value={"stopped": True}):

            if expected_code != 0:
                with pytest.raises(SystemExit) as exc_info:
                    standalone_main(args_list)
                assert exc_info.value.code == expected_code
            else:
                code = standalone_main(args_list)
                assert code == expected_code, f"Failed on args {args_list}: got code {code}"
