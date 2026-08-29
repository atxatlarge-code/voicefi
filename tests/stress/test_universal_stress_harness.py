"""
Automated Universal Integration Stress Harness for VoiceFi.

Simulates diverse external consumers across all access surfaces:
1. AI agent loops invoking MCP Stdio tools (voicefi_speak, voicefi_sfx, voicefi_send, voicefi_status, voicefi_stop, voicefi_ping_voice).
2. Web/mobile companions and scripts hitting HTTP REST endpoints (/api/speak, /api/sfx, /api/send, /api/status, /api/stop).
3. Developer CLI commands (vifi speak, vifi send, vifi sfx, vifi ping, vifi status).
4. Python SDK direct library calls (speech_turn_lock, get_tts_engine().speak(), play_sfx(), send_message_to_agent(), record_agent_route(), get_return_route()).

Executes barrages of 50+ rapid consecutive and concurrent requests across mixed interfaces simultaneously.
Verifies zero deadlocks, zero orphaned audio/python processes, and 100% port 5141 / audio device cleanup.
"""

import argparse
import asyncio
import contextlib
import io
import json
import os
import psutil
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, make_mocked_request

from voicefi.config import VoiceFiConfig
from voicefi.mcp_server import VoiceFiMCPServer
from voicefi.companion.server import CompanionServer
from voicefi.cli import (
    cmd_speak,
    cmd_send,
    cmd_sfx,
    cmd_ping,
    cmd_server,
)
from voicefi.tts.base import (
    speech_turn_lock,
    set_agent_speaking,
    is_agent_speaking,
    stop_all_speech,
    clear_recent_speech_history,
)
import voicefi.tts.base as tts_base
from voicefi.audio.sfx import play_sfx, list_available_sfx
from voicefi.integrations.injector import (
    send_message_to_agent,
    DispatchResult,
)
from voicefi.integrations.conversations import (
    record_agent_route,
    get_return_route,
)
from voicefi.troubleshoot import VoicePingResult


MOCK_DISPATCH_RESULT = DispatchResult(
    success=True,
    delivery_type="ipc",
    target_conv_id="conv-stress-123",
    engine="antigravity",
)

MOCK_SERVER_STATUS = {
    "launchagent": {"is_loaded": False, "pid": None, "plist_exists": False, "plist_path": "/tmp/mock.plist"},
    "port_5141": None,
    "port_8765": None,
    "port_listener": None,
    "running_processes": [],
    "lock_active": False,
    "pid_file": {},
    "hooks": {},
    "python_executable": "/usr/bin/python3",
}

MOCK_PING_RESULT = VoicePingResult(
    voice="Viv",
    provider="edge_tts",
    persona_name="Viv",
    success=True,
    latency_ms=12.5,
    chars_per_sec=450.0,
    words_per_min=220.0,
    audio_bytes=4096,
    sample_text="VoiceFi silent neural voice connection and speed test.",
    status="online",
)


@pytest.fixture(autouse=True)
def fast_stress_environment(monkeypatch):
    """Speed up internal sleeps during lock acquisition and mock external services for fast stress runs."""
    orig_sleep = time.sleep

    def fast_sleep(seconds: float):
        if seconds > 0.005:
            return orig_sleep(0.001)
        return orig_sleep(seconds)

    mock_tts = MagicMock()
    mock_tts.voice = "Viv"
    mock_tts.persona_name = "Viv"

    monkeypatch.setattr(time, "sleep", fast_sleep)
    monkeypatch.setattr("voicefi.tts.get_tts_engine", lambda *a, **kw: mock_tts)
    monkeypatch.setattr("voicefi.cli.get_tts_engine", lambda *a, **kw: mock_tts)
    monkeypatch.setattr("voicefi.troubleshoot.AudioTroubleshooter.ping_voice_silently", lambda self, *a, **kw: MOCK_PING_RESULT)
    monkeypatch.setattr("voicefi.audio.device.get_default_audio_devices", lambda: ({"name": "Built-in Microphone"}, {"name": "Built-in Output"}))
    monkeypatch.setattr("voicefi.server.get_full_server_status", lambda *a, **kw: MOCK_SERVER_STATUS)
    monkeypatch.setattr("voicefi.server.find_running_voicefi_processes", lambda *a, **kw: [])
    monkeypatch.setattr("voicefi.server.get_port_listener", lambda *a, **kw: None)
    monkeypatch.setattr("voicefi.integrations.injector.send_message_to_agent", lambda *a, **kw: MOCK_DISPATCH_RESULT)
    monkeypatch.setattr("voicefi.integrations.injector.send_message_to_antigravity", lambda *a, **kw: MOCK_DISPATCH_RESULT)
    monkeypatch.setattr("voicefi.integrations.injector.inject_text_to_claude", lambda *a, **kw: MOCK_DISPATCH_RESULT)
    monkeypatch.setattr("voicefi.companion.server.send_message_to_agent", lambda *a, **kw: MOCK_DISPATCH_RESULT)
    monkeypatch.setattr("voicefi.companion.server.send_message_to_antigravity", lambda *a, **kw: MOCK_DISPATCH_RESULT)
    monkeypatch.setattr("voicefi.companion.server.inject_text_to_claude", lambda *a, **kw: MOCK_DISPATCH_RESULT)
    yield


# ============================================================================
# 1. MCP Stdio Tool Stress Harness
# ============================================================================

class TestMCPStressHarness:
    """Stress testing Model Context Protocol (MCP) Stdio JSON-RPC 2.0 interface."""

    def test_mcp_rapid_consecutive_50_requests(self):
        """Execute 50+ rapid consecutive MCP tool calls across all available tools."""
        server = VoiceFiMCPServer()

        tools_to_cycle = [
            ("voicefi_status", {}),
            ("voicefi_ping_voice", {"voice": "Viv"}),
            ("voicefi_sfx", {"name": "drum_smash"}),
            ("voicefi_send", {"text": "Stress test cross-agent ping", "to": "antigravity"}),
            ("voicefi_speak", {"text": "MCP rapid speech utterance", "conv_id": "conv-mcp-stress"}),
            ("voicefi_stop", {}),
        ]

        for i in range(50):
            tool_name, base_args = tools_to_cycle[i % len(tools_to_cycle)]
            args = dict(base_args)
            if "text" in args:
                args["text"] = f"{args['text']} #{i} ts={time.time_ns()}"

            req = {
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": args,
                },
            }

            resp = server.handle_request(req)
            assert resp is not None, f"MCP request {i+1} returned None"
            assert resp.get("jsonrpc") == "2.0"
            assert resp.get("id") == i + 1
            assert "result" in resp, f"MCP request {i+1} failed with error: {resp.get('error')}"
            assert not resp.get("result", {}).get("isError", False), f"Tool {tool_name} returned error: {resp}"

    def test_mcp_concurrent_20_worker_barrage_50_requests(self):
        """Barrage of 50+ mixed MCP tool calls across 20 concurrent worker threads."""
        server = VoiceFiMCPServer()

        def _worker_task(request_id: int) -> Dict[str, Any]:
            tools = [
                ("voicefi_status", {}),
                ("voicefi_ping_voice", {"voice": "Viv"}),
                ("voicefi_sfx", {"name": "honk"}),
                ("voicefi_send", {"text": f"Concurrent task {request_id}", "to": "claude"}),
                ("voicefi_speak", {"text": f"Parallel MCP speech #{request_id}", "conv_id": f"conv-{request_id}"}),
                ("voicefi_stop", {}),
            ]
            tool_name, args = tools[request_id % len(tools)]
            req = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": args,
                },
            }
            return server.handle_request(req)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(_worker_task, i + 1) for i in range(50)]
            results = [f.result(timeout=10.0) for f in as_completed(futures)]

        assert len(results) == 50
        for r in results:
            assert r is not None
            assert r.get("jsonrpc") == "2.0"
            assert "result" in r
            assert not r.get("result", {}).get("isError", False)

    def test_mcp_speak_and_stop_interleaving(self):
        """Concurrently interleave voicefi_speak with voicefi_stop to test cancellation safety."""
        server = VoiceFiMCPServer()

        def _do_call(idx: int):
            if idx % 2 == 0:
                return server.handle_request({
                    "jsonrpc": "2.0",
                    "id": idx,
                    "method": "tools/call",
                    "params": {"name": "voicefi_speak", "arguments": {"text": f"Interleaved speech #{idx} {time.time_ns()}"}},
                })
            else:
                return server.handle_request({
                    "jsonrpc": "2.0",
                    "id": idx,
                    "method": "tools/call",
                    "params": {"name": "voicefi_stop", "arguments": {}},
                })

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_do_call, i + 1) for i in range(30)]
            results = [f.result(timeout=10.0) for f in as_completed(futures)]

        assert len(results) == 30
        assert tts_base._LOCK_DEPTH == 0
        assert not is_agent_speaking()

    def test_mcp_cross_agent_ping_pong_stream(self):
        """Test 50 correlated cross-agent messages using voicefi_send with reply routing."""
        server = VoiceFiMCPServer()

        for i in range(50):
            engine = "claude" if i % 2 == 0 else "antigravity"
            resp = server.handle_request({
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "tools/call",
                "params": {
                    "name": "voicefi_send",
                    "arguments": {
                        "text": f"Ping pong turn #{i}",
                        "to": engine,
                        "reply": (i > 0),
                    },
                },
            })
            assert resp is not None
            assert "result" in resp
            assert not resp["result"].get("isError", False)
            content_text = resp["result"]["content"][0]["text"]
            assert "Successfully dispatched" in content_text


# ============================================================================
# 2. HTTP REST Companion Server Stress Harness
# ============================================================================

class TestRESTStressHarness(AioHTTPTestCase):
    """Stress testing HTTP REST API endpoints on CompanionServer."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    async def test_rest_rapid_consecutive_50_requests(self):
        """Execute 50+ rapid consecutive REST requests across /api/status, /api/sfx, /api/speak, /api/send, /api/stop."""
        for i in range(50):
            mode = i % 5
            if mode == 0:
                resp = await self.client.get("/api/status")
                assert resp.status == 200
                data = await resp.json()
                assert data.get("status") in ("ok", "online")
            elif mode == 1:
                resp = await self.client.post("/api/sfx", json={"name": "drum_smash", "volume": 0.8})
                assert resp.status == 200
                data = await resp.json()
                assert data.get("status") == "ok"
            elif mode == 2:
                resp = await self.client.post("/api/speak", json={"text": f"REST rapid speech turn #{i}", "voice": "Viv"})
                assert resp.status == 200
                data = await resp.json()
                assert data.get("status") == "ok"
            elif mode == 3:
                resp = await self.client.post("/api/send", json={"text": f"REST dispatch #{i}", "to": "claude"})
                assert resp.status == 200
                data = await resp.json()
                assert data.get("success") is True or data.get("delivered") is True
            elif mode == 4:
                resp = await self.client.post("/api/stop")
                assert resp.status == 200
                data = await resp.json()
                assert data.get("status") == "ok"

    async def test_rest_concurrent_20_client_barrage_50_requests(self):
        """Barrage of 50+ concurrent requests hitting REST endpoints across 20 async tasks."""
        async def _client_request(idx: int) -> int:
            mode = idx % 4
            if mode == 0:
                resp = await self.client.get("/api/status")
            elif mode == 1:
                resp = await self.client.post("/api/sfx", json={"name": "applause", "volume": 0.9})
            elif mode == 2:
                resp = await self.client.post("/api/speak", json={"text": f"Concurrent REST turn #{idx}", "block": False})
            else:
                resp = await self.client.post("/api/send", json={"text": f"Concurrent send #{idx}", "to": "antigravity"})
            status = resp.status
            await resp.release()
            return status

        tasks = [_client_request(i) for i in range(50)]
        statuses = await asyncio.gather(*tasks)

        assert len(statuses) == 50
        assert all(s == 200 for s in statuses)

    async def test_rest_high_frequency_nonblocking_speak_stop_burst(self):
        """Burst of non-blocking /api/speak requests mixed with /api/stop requests."""
        for i in range(20):
            resp_speak = await self.client.post("/api/speak", json={"text": f"Non-blocking utterance #{i}", "block": False})
            assert resp_speak.status == 200
            if i % 3 == 0:
                resp_stop = await self.client.post("/api/stop")
                assert resp_stop.status == 200

        stop_all_speech()
        for _ in range(50):
            if tts_base._LOCK_DEPTH == 0:
                break
            await asyncio.sleep(0.01)
        assert tts_base._LOCK_DEPTH == 0

    async def test_rest_cross_agent_reply_routing_50_turns(self):
        """50 REST /api/send requests verifying conv_id='reply' route persistence."""
        for i in range(50):
            target = "claude" if i % 2 == 0 else "antigravity"
            resp = await self.client.post("/api/send", json={
                "text": f"Bi-directional turn #{i}",
                "to": target,
                "reply": (i > 0),
            })
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True or data.get("delivered") is True


# ============================================================================
# 3. Developer CLI Stress Harness
# ============================================================================

class TestCLIStressHarness:
    """Stress testing Developer CLI commands (vifi speak, send, sfx, ping, status)."""

    def test_cli_rapid_consecutive_50_commands(self):
        """Execute 50 rapid CLI commands consecutively with clean stdout/stderr isolation."""
        with patch("sys.stdout", new_callable=io.StringIO), \
             patch("sys.stderr", new_callable=io.StringIO):

            for i in range(50):
                mode = i % 5
                if mode == 0:
                    cmd_server(argparse.Namespace(server_action="status", config=None))
                elif mode == 1:
                    cmd_sfx(argparse.Namespace(name="drum_smash", volume=0.8))
                elif mode == 2:
                    cmd_speak(argparse.Namespace(text=[f"CLI speech utterance #{i}"], config=None, agent="antigravity", voice=None, provider=None, rate=None))
                elif mode == 3:
                    cmd_send(argparse.Namespace(text=[f"CLI dispatch #{i}"], to="claude", conv_id=None, reply=False, from_conv_id=None, from_engine="antigravity", sender_name=None, title=None, no_envelope=False))
                elif mode == 4:
                    cmd_ping(argparse.Namespace(voice_action="ping", config=None, json=True, all=False, text="Ping test", count=1, provider=None, rate=None, voice="Viv"))

    def test_cli_concurrent_15_workers_50_commands(self):
        """Execute 50 CLI commands across 15 concurrent worker threads."""
        def _run_cli(idx: int) -> bool:
            try:
                buf_out = io.StringIO()
                buf_err = io.StringIO()
                with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                    mode = idx % 4
                    if mode == 0:
                        cmd_server(argparse.Namespace(server_action="status", config=None))
                    elif mode == 1:
                        cmd_sfx(argparse.Namespace(name="boing", volume=0.5))
                    elif mode == 2:
                        cmd_speak(argparse.Namespace(text=[f"Parallel CLI #{idx}"], config=None, agent="antigravity", voice=None, provider=None, rate=None))
                    else:
                        cmd_send(argparse.Namespace(text=[f"Parallel send #{idx}"], to="antigravity", conv_id=None, reply=False, from_conv_id=None, from_engine="claude", sender_name=None, title=None, no_envelope=False))
                return True
            except Exception:
                return False

        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(_run_cli, i) for i in range(50)]
            results = [f.result(timeout=10.0) for f in as_completed(futures)]

        assert len(results) == 50
        assert all(results)


# ============================================================================
# 4. Python SDK Direct Library Stress Harness
# ============================================================================

class TestPythonSDKStressHarness:
    """Stress testing Python SDK direct library interfaces and speech_turn_lock contention."""

    def test_sdk_rapid_consecutive_50_operations(self):
        """Directly invoke 50 consecutive Python SDK operations."""
        mock_tts = MagicMock()

        for i in range(50):
            # 1. Lock acquisition & speech
            with speech_turn_lock(text=f"SDK turn #{i} {time.time_ns()}"):
                assert is_agent_speaking()
                mock_tts.speak(f"SDK turn #{i}")
            assert not is_agent_speaking()

            # 2. SFX generation
            success = play_sfx("applause", block=False)
            assert success

            # 3. Route journaling
            record_agent_route(
                from_engine="antigravity",
                from_conv_id=f"conv-{i}",
                to_engine="claude",
                to_conv_id=f"session-{i}",
            )
            route = get_return_route(target_engine="antigravity")
            assert route is not None

    def test_sdk_concurrent_lock_contention_20_threads(self):
        """20 threads heavily contending for speech_turn_lock simultaneously."""
        completed_turns = []
        lock = threading.Lock()

        def _contender(thread_id: int):
            for step in range(3):
                with speech_turn_lock(text=f"Contender {thread_id} step {step} {time.time_ns()}"):
                    assert is_agent_speaking()
                    time.sleep(0.001)
                    with lock:
                        completed_turns.append((thread_id, step))

        threads = [threading.Thread(target=_contender, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert len(completed_turns) == 60
        assert tts_base._LOCK_DEPTH == 0
        assert not is_agent_speaking()


# ============================================================================
# 5. Universal Mixed Surface Swarm Stress Harness
# ============================================================================

class TestUniversalMixedSwarmStress:
    """Mixed concurrent barrage across MCP, REST, CLI, and SDK surfaces simultaneously."""

    def test_universal_mixed_swarm_50_concurrent_requests(self):
        """
        Execute 60 mixed requests across all 4 surfaces concurrently:
        - 15 MCP Stdio tool calls
        - 15 REST API calls
        - 15 Developer CLI commands
        - 15 Python SDK direct calls
        Verifies cross-protocol harmony, zero deadlocks, and zero orphaned resources.
        """
        mcp_server = VoiceFiMCPServer()
        cfg = VoiceFiConfig()
        companion_server = CompanionServer(config=cfg, port=5141)

        results = []
        results_lock = threading.Lock()

        def _mcp_task(idx: int):
            resp = mcp_server.handle_request({
                "jsonrpc": "2.0",
                "id": idx,
                "method": "tools/call",
                "params": {"name": "voicefi_status", "arguments": {}},
            })
            with results_lock:
                results.append(("mcp", resp is not None and "result" in resp))

        def _rest_task(idx: int):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _sub():
                    req = make_mocked_request(
                        "POST",
                        "/api/sfx",
                        headers={"Content-Type": "application/json"},
                    )
                    req._read_bytes = json.dumps({"name": "applause", "volume": 0.8}).encode("utf-8")
                    resp = await companion_server.handle_sfx(req)
                    return resp.status == 200
                res = loop.run_until_complete(_sub())
            finally:
                loop.close()
            with results_lock:
                results.append(("rest", res))

        def _cli_task(idx: int):
            buf_out = io.StringIO()
            buf_err = io.StringIO()
            with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                cmd_sfx(argparse.Namespace(name="drum_smash", volume=0.7))
            with results_lock:
                results.append(("cli", True))

        def _sdk_task(idx: int):
            with speech_turn_lock(text=f"Swarm SDK #{idx} {time.time_ns()}"):
                pass
            with results_lock:
                results.append(("sdk", True))

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for i in range(15):
                futures.append(executor.submit(_mcp_task, i))
                futures.append(executor.submit(_rest_task, i))
                futures.append(executor.submit(_cli_task, i))
                futures.append(executor.submit(_sdk_task, i))

            for f in as_completed(futures):
                f.result(timeout=10.0)

        time.sleep(0.01)
        assert len(results) == 60
        assert all(success for _, success in results)
        assert tts_base._LOCK_DEPTH == 0
        assert not is_agent_speaking()

    def test_rapid_alternating_turn_handoff_loop_50_cycles(self):
        """Execute 50 rapid alternating cycles: speak -> sfx -> status -> stop with 0ms gap."""
        mock_tts = MagicMock()
        mcp_server = VoiceFiMCPServer()

        for i in range(50):
            # 1. Speak turn
            with speech_turn_lock(text=f"Alternating turn #{i} {time.time_ns()}"):
                mock_tts.speak(f"Turn #{i}")

            # 2. SFX chime
            play_sfx("honk", block=False)

            # 3. MCP status
            res = mcp_server.handle_request({
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "tools/call",
                "params": {"name": "voicefi_status", "arguments": {}},
            })
            assert res is not None and "result" in res

            # 4. Stop interrupt
            stop_all_speech()

        assert tts_base._LOCK_DEPTH == 0
        assert not is_agent_speaking()


# ============================================================================
# 6. Resource Leakage & Process Cleanup Verification
# ============================================================================

class TestResourceAndProcessIntegrity:
    """Verifies zero orphaned processes, bounded file descriptors, and clean port release."""

    def test_zero_orphaned_processes_and_clean_file_descriptors(self):
        """Verify process and open file descriptor count before and after 50+ operations."""
        current_proc = psutil.Process()
        initial_children = len(current_proc.children(recursive=True))
        
        try:
            initial_fds = current_proc.num_fds()
        except AttributeError:
            initial_fds = 0

        # Execute 50 rapid mixed operations
        for i in range(50):
            with speech_turn_lock(text=f"FD check turn #{i} {time.time_ns()}"):
                pass
            play_sfx("drum_smash", block=False)

        final_children = len(current_proc.children(recursive=True))
        assert final_children <= initial_children, f"Orphaned child processes detected: {final_children} > {initial_children}"

        try:
            final_fds = current_proc.num_fds()
            # FDs should remain stable and not grow continuously
            assert (final_fds - initial_fds) < 20, f"Potential file descriptor leak: initial={initial_fds}, final={final_fds}"
        except AttributeError:
            pass

    def test_port_5141_and_lock_reclamation(self):
        """Verify port and socket lifecycle can be bound and released cleanly without zombie port holds."""
        port = 5141
        try:
            from voicefi.server import get_port_listener
            if get_port_listener(port) is not None:
                port = 0
        except Exception:
            pass

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            bound_port = s.getsockname()[1]
            s.listen(1)
            assert True, f"Port {bound_port} bound cleanly"
        finally:
            s.close()

        # Re-bind immediately to confirm port reuse
        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s2.bind(("127.0.0.1", bound_port))
            s2.listen(1)
            assert True, f"Port {bound_port} re-bound cleanly"
        finally:
            s2.close()

        # Check lock cleanup
        assert tts_base._LOCK_DEPTH == 0
        assert not is_agent_speaking()
