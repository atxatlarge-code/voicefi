"""
Empirical Adversarial Stress Suite for Milestone M3 (Challenger 2).

Systematically tests:
1. Comedy banter duels (`vifi duel`) boundary conditions, concurrent duel stress,
   rapid interleaved SFX triggers, and live dispatch resilience.
2. Attack boundaries on provenance envelope parsing and injection escaping:
   - Shell metacharacters, AppleScript injection strings, SQL injection, format strings.
   - Multiline, deeply nested JSON, Unicode, zero-width chars, extreme payload sizes.
   - Concurrency stress on agent route journal (/tmp/voicefi_agent_routes.json).
3. Third-party standalone client execution in completely isolated environments:
   - PYTHONPATH stripped, sys.path isolated.
   - Mock REST HTTP server with fuzzing (malformed bodies, 500s, truncated streams, connection resets).
   - Mock MCP JSON-RPC server with fuzzing (invalid responses, protocol errors, unexpected EOF).
"""

import ast
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
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


# ============================================================================
# Challenge 1: Comedy Banter Duels & Interleaved SFX Concurrency
# ============================================================================

class TestComedyDuelAndSFXAdversarial:
    """Adversarial stress-testing of comedy banter duels and audio effect queuing."""

    def test_duel_turn_boundary_values(self):
        """Test vifi duel with boundary turn values: 0, negative, and oversized."""
        from voicefi.cli import cmd_duel
        import argparse

        mock_tts_agy = MagicMock()
        mock_tts_cld = MagicMock()

        def _get_tts(cfg, agent_name="antigravity", **kwargs):
            return mock_tts_agy if agent_name == "antigravity" else mock_tts_cld

        with patch("voicefi.config.load_config"), \
             patch("voicefi.tts.get_tts_engine", side_effect=_get_tts), \
             patch("voicefi.audio.sfx.play_sfx", return_value=True), \
             patch("time.sleep"):

            # 1. turns = -5 (should execute 0 rounds cleanly without crashing)
            mock_tts_agy.reset_mock()
            mock_tts_cld.reset_mock()
            cmd_duel(argparse.Namespace(turns=-5, live=False))
            assert mock_tts_agy.speak.call_count == 0
            assert mock_tts_cld.speak.call_count == 0

            # 2. turns = 100 (should clamp to max available rounds: 3)
            mock_tts_agy.reset_mock()
            mock_tts_cld.reset_mock()
            cmd_duel(argparse.Namespace(turns=100, live=False))
            assert mock_tts_agy.speak.call_count == 3
            assert mock_tts_cld.speak.call_count == 3

    def test_duel_concurrent_execution_stress(self):
        """Stress-test multiple concurrent duel sessions running simultaneously."""
        from voicefi.cli import cmd_duel
        from voicefi.config import load_config as real_load_config
        import argparse

        num_threads = 8
        errors = []

        mock_tts_agy = MagicMock()
        mock_tts_cld = MagicMock()

        def _get_tts(cfg, agent_name="antigravity", **kwargs):
            return mock_tts_agy if agent_name == "antigravity" else mock_tts_cld

        clean_cfg = real_load_config()

        def _run_duel(worker_id):
            try:
                cmd_duel(argparse.Namespace(turns=3, live=False))
            except Exception as e:
                errors.append((worker_id, str(e)))

        with patch("voicefi.config.load_config", return_value=clean_cfg), \
             patch("voicefi.tts.get_tts_engine", side_effect=_get_tts), \
             patch("voicefi.audio.sfx.play_sfx", return_value=True), \
             patch("time.sleep"):
            threads = [threading.Thread(target=_run_duel, args=(i,)) for i in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(errors) == 0, f"Concurrent duel failed with errors: {errors}"

    def test_interleaved_rapid_sfx_and_dispatch_storm(self, tmp_path):
        """Simulate high-frequency interleaved SFX and dispatch triggers."""
        test_routes = tmp_path / "routes_sfx_storm.json"
        with patch("voicefi.integrations.conversations._AGENT_ROUTES_FILE", test_routes), \
             patch("voicefi.integrations.injector.set_clipboard_text", return_value=True), \
             patch("voicefi.integrations.injector.focus_terminal_app", return_value="iTerm2"), \
             patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="true")):

            from voicefi.audio.sfx import play_sfx, list_available_sfx
            available_sfx = list_available_sfx()
            assert len(available_sfx) >= 6

            for i in range(20):
                sfx_name = available_sfx[i % len(available_sfx)]
                # Test non-blocking SFX trigger
                sfx_ok = play_sfx(sfx_name, block=False)
                assert sfx_ok is True

                # Concurrently dispatch message
                res = send_message_to_agent(
                    text=f"Banter punchline {i} [sfx:{sfx_name}]",
                    target_engine="claude",
                    from_conv_id=f"conv-{i}",
                    include_envelope=True,
                )
                assert res.success is True

    def test_duel_tts_engine_failure_resilience(self):
        """Verify duel gracefully handles TTS synthesis exceptions without unhandled crash."""
        from voicefi.cli import cmd_duel
        import argparse

        mock_tts_broken = MagicMock()
        mock_tts_broken.speak.side_effect = RuntimeError("TTS synthesis failure")

        with patch("voicefi.config.load_config"), \
             patch("voicefi.tts.get_tts_engine", return_value=mock_tts_broken), \
             patch("voicefi.audio.sfx.play_sfx", return_value=True), \
             patch("time.sleep"):

            with pytest.raises(RuntimeError, match="TTS synthesis failure"):
                cmd_duel(argparse.Namespace(turns=1, live=False))


# ============================================================================
# Challenge 2: Attack Boundaries on Provenance Envelopes & Injection Escaping
# ============================================================================

class TestProvenanceEnvelopeAndInjectionAttacks:
    """Security and boundary stress-testing of provenance envelope generation and parsing."""

    ADVERSARIAL_PAYLOADS = [
        # Shell injection vectors
        '"; rm -rf /tmp/test; echo "pwned',
        '`whoami`',
        '$(cat /etc/passwd)',
        'foo | nc -l 1337',
        'test & echo "backgrounded" &',

        # AppleScript injection vectors
        'tell application "Finder" to display dialog "Exploit"',
        '" & keystroke "q" using {command down} & "',
        'end tell\nbeep 3\ntell application "System Events"',

        # JSON breaking characters
        '{"malformed": "json\'"\\}',
        '{"nested": {"array": [1, 2, "quote\\"escape"]}}',
        '\\"\\n\\r\\t\\\\',

        # Format string attacks
        '%s%s%s%s%s%s%s%s%n',
        '{0.__class__.__mro__[1].__subclasses__()}',

        # Unicode, zero-width, and bidirectional override
        '🚀🔥 ba-dum-tss! \u202e\u200b\u200c\uFEFF',
        'Special chars: \x00\x01\x1f\x7f\t\r\n',
        'Zalgo: H̸̡e̸̢l̸̡l̷̢o̵̧',

        # Deep / massive strings
        "A" * 10000,
        "Line1\nLine2\r\nLine3\n\n\nLine4" * 100,
    ]

    def test_adversarial_payloads_in_claude_envelope(self):
        """Verify adversarial payloads in from_conv_id and text do not break envelope or crash injector."""
        for payload in self.ADVERSARIAL_PAYLOADS:
            with patch("voicefi.integrations.injector.set_clipboard_text", return_value=True) as mock_clip, \
                 patch("voicefi.integrations.injector.focus_terminal_app", return_value="Terminal"), \
                 patch("voicefi.integrations.conversations.record_agent_route") as mock_route, \
                 patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="true")):

                success = inject_text_to_claude(
                    text=payload,
                    from_conv_id=payload[:50],  # test payload as conv_id
                    from_engine="antigravity",
                    include_envelope=True,
                )
                assert success is True
                mock_clip.assert_called_once()
                clipped_text = mock_clip.call_args[0][0]

                # Envelope should cleanly wrap the text
                assert f"[From: Antigravity | Conversation: {payload[:50]}]" in clipped_text
                assert payload in clipped_text

    def test_adversarial_payloads_in_agentapi_ipc(self):
        """Verify adversarial payloads passed to send_message_to_antigravity are safely routed via subprocess arguments."""
        for payload in self.ADVERSARIAL_PAYLOADS:
            with patch("pathlib.Path.is_file", return_value=True), \
                 patch("os.access", return_value=True), \
                 patch("subprocess.run") as mock_run:

                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

                res = send_message_to_antigravity(
                    conv_id=payload[:36],
                    text=payload,
                    sender_name=payload[:20],
                    title=payload[:20],
                )

                assert res.success is True
                assert res.delivery_type == "ipc"

                # Verify arguments were passed as a direct list, NOT shell-interpolated
                mock_run.assert_called_once()
                cmd = mock_run.call_args[0][0]
                assert isinstance(cmd, list)
                assert cmd[0].endswith("agentapi")
                assert cmd[1] == "send-message"
                assert payload.strip() in cmd

    def test_agent_routes_journal_unwritable_fallback(self, tmp_path):
        """Test journal degrades gracefully if file or dir is unwritable."""
        read_only_dir = tmp_path / "read_only"
        read_only_dir.mkdir(parents=True, exist_ok=True)
        read_only_dir.chmod(0o555)
        unwritable_file = read_only_dir / "routes.json"
        try:
            with patch("voicefi.integrations.conversations._AGENT_ROUTES_FILE", unwritable_file):
                # Should not raise exception
                record_agent_route(
                    from_engine="antigravity",
                    from_conv_id="test-conv",
                    to_engine="claude",
                )
                route = get_return_route()
                assert route is None
        finally:
            read_only_dir.chmod(0o755)


# ============================================================================
# Challenge 3: Standalone Client Isolated Execution & Fuzzing
# ============================================================================

class MockRESTServerHandler(BaseHTTPRequestHandler):
    """Mock HTTP server for testing VoiceFiRestClient against various HTTP behaviors."""

    def do_GET(self):
        if self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ready", "server": "mock"}).encode("utf-8"))
        elif self.path == "/api/500":
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error": "Internal Server Error"}')
        elif self.path == "/api/malformed":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"invalid_json": ')
        elif self.path == "/api/empty":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b"{}"

        if self.path in ("/api/speak", "/api/sfx", "/api/send", "/api/stop"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                req_data = json.loads(body)
                self.wfile.write(json.dumps({"status": "ok", "echo": req_data}).encode("utf-8"))
            except Exception:
                self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress console log spam during tests


@pytest.fixture(scope="module")
def live_mock_http_server():
    """Start a real local HTTP server on a random port for live wire testing."""
    server = HTTPServer(("127.0.0.1", 0), MockRESTServerHandler)
    host, port = server.server_address
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield host, port
    server.shutdown()


class TestIsolatedStandaloneClientAdversarial:
    """Stress-testing standalone client execution and communication protocols in isolation."""

    def test_client_execution_with_isolated_sys_path(self, live_mock_http_server):
        """Execute standalone_voicefi_client in an isolated subprocess with stripped PYTHONPATH."""
        host, port = live_mock_http_server
        client_path = Path(__file__).parent.parent / "examples" / "standalone_voicefi_client.py"

        env = os.environ.copy()
        env["PYTHONPATH"] = ""  # Strip pythonpath

        # 1. Test status via REST
        res1 = subprocess.run(
            [sys.executable, str(client_path), "--mode", "rest", "--host", host, "--port", str(port), "--status", "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        assert res1.returncode == 0
        data1 = json.loads(res1.stdout)
        assert data1.get("status") == "ready"

        # 2. Test speak via REST
        res2 = subprocess.run(
            [sys.executable, str(client_path), "--mode", "rest", "--host", host, "--port", str(port), "--speak", "Testing isolated client", "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        assert res2.returncode == 0
        data2 = json.loads(res2.stdout)
        assert data2.get("status") == "ok"
        assert data2.get("echo", {}).get("text") == "Testing isolated client"

        # 3. Test send via REST
        res3 = subprocess.run(
            [sys.executable, str(client_path), "--mode", "rest", "--host", host, "--port", str(port), "--send", "Deploy task", "--to", "antigravity", "--title", "TaskTitle", "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
        assert res3.returncode == 0
        data3 = json.loads(res3.stdout)
        assert data3.get("status") == "ok"
        assert data3.get("echo", {}).get("title") == "TaskTitle"

    def test_rest_client_fuzzing_and_malformed_responses(self, live_mock_http_server):
        """Fuzz VoiceFiRestClient against 500s, malformed json, empty bodies, and port connection failures."""
        host, port = live_mock_http_server
        client = VoiceFiRestClient(host=host, port=port, timeout=3.0)

        # 1. 500 Internal Server Error
        res_500 = client._request("/api/500")
        assert res_500.get("http_code") == 500
        assert "Internal Server Error" in str(res_500.get("error"))

        # 2. Malformed JSON response body
        res_malformed = client._request("/api/malformed")
        assert "Request exception" in res_malformed.get("error", "") or "JSONDecodeError" in str(res_malformed)

        # 3. Empty body (HTTP 204)
        res_empty = client._request("/api/empty")
        assert res_empty.get("status") == "ok"

        # 4. Connection refused on dead port
        dead_client = VoiceFiRestClient(host="127.0.0.1", port=65530, timeout=1.0)
        res_dead = dead_client.status()
        assert res_dead.get("connection_error") is True
        assert "Connection failed" in res_dead.get("error", "")

    def test_mcp_client_fuzzing_and_protocol_errors(self):
        """Fuzz VoiceFiMCPClient against JSON-RPC protocol violations, tool errors, and unexpected termination."""
        # 1. Server returns JSON-RPC error on initialize
        mock_proc_init_err = MagicMock()
        mock_proc_init_err.poll.return_value = None
        mock_proc_init_err.stdin = MagicMock()
        mock_proc_init_err.stdout.readline.return_value = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid Request"},
        }) + "\n"

        with patch("subprocess.Popen", return_value=mock_proc_init_err):
            client = VoiceFiMCPClient(command=["mock_vifi", "mcp"], timeout=2.0)
            with pytest.raises(RuntimeError, match="MCP initialize failed"):
                client.start()

        # 2. Server crashes unexpectedly mid-session
        mock_proc_crash = MagicMock()
        mock_proc_crash.poll.return_value = 1
        mock_proc_crash.returncode = 1
        mock_proc_crash.stderr.read.return_value = "Segmentation fault"
        mock_proc_crash.stdin = MagicMock()
        mock_proc_crash.stdout = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc_crash):
            client2 = VoiceFiMCPClient(command=["mock_vifi", "mcp"], timeout=1.0)
            client2.process = mock_proc_crash
            with pytest.raises(RuntimeError, match="MCP server terminated unexpectedly with code 1"):
                client2._send_request({"jsonrpc": "2.0", "id": 1, "method": "test"})

        # 3. Tool call returns isError: True
        mock_proc_tool_err = MagicMock()
        mock_proc_tool_err.poll.return_value = None
        mock_proc_tool_err.stdin = MagicMock()
        mock_proc_tool_err.stdout.readline.side_effect = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n",  # init
            json.dumps({"jsonrpc": "2.0", "id": 2, "error": {"code": -32000, "message": "Audio device locked"}}) + "\n",  # tool call
        ]

        with patch("subprocess.Popen", return_value=mock_proc_tool_err):
            client3 = VoiceFiMCPClient(command=["mock_vifi", "mcp"], timeout=2.0)
            client3.start()
            res = client3.call_tool("voicefi_speak", {"text": "hello"})
            assert res.get("isError") is True
            assert res.get("error", {}).get("message") == "Audio device locked"
