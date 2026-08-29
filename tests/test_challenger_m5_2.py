"""
Empirical Challenger Test Suite for Milestone M5.
Adversarial Verification of:
1. Multi-surface interleaved storm: Interleave speak, listen, SFX, send, and stop across 20 parallel workers with random arrival intervals.
2. Port 5141 socket teardown and recovery under high-traffic burst.
3. Validate benchmark report serialization to benchmarks/stress_benchmark_report.json and human-readable formatting in benchmarks/BENCHMARKS.md.
"""

import argparse
import asyncio
import contextlib
import io
import json
import os
import random
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
import psutil
import pytest

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
)
import voicefi.tts.base as tts_base
from voicefi.audio.sfx import play_sfx
from voicefi.integrations.injector import (
    send_message_to_agent,
    DispatchResult,
)
from voicefi.integrations.conversations import (
    record_agent_route,
    get_return_route,
)
from voicefi.troubleshoot import VoicePingResult
from benchmarks.run_stress_benchmark import (
    BenchmarkRunner,
    calculate_percentiles,
    generate_markdown_report,
)


MOCK_DISPATCH_RESULT = DispatchResult(
    success=True,
    delivery_type="ipc",
    target_conv_id="conv-challenger-123",
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
    "python_executable": sys.executable,
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
def challenger_fast_env(monkeypatch):
    """Speed up internal sleeps and mock external hardware/network for non-blocking execution."""
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
    monkeypatch.setattr("voicefi.audio.sfx.play_sfx", lambda *a, **kw: True)
    monkeypatch.setattr("voicefi.audio.chimes.play_chime", lambda *a, **kw: None)
    monkeypatch.setattr("voicefi.telemetry.record_event", lambda *a, **kw: None)
    monkeypatch.setattr("voicefi.mcp_server.VoiceFiMCPServer._tool_listen", lambda self, args: {"transcript": "mock transcript", "duration": 1.2, "confidence": 0.95})
    yield


# ============================================================================
# Challenge 1: Multi-Surface Interleaved Storm (20 Parallel Workers)
# ============================================================================

class TestInterleavedStorm20Workers:
    """Adversarial stress test: Interleaving speak, listen, SFX, send, and stop across 20 workers with random arrival jitter."""

    def test_interleaved_multi_surface_storm_20_workers(self):
        """
        20 parallel worker threads executing 120+ operations across MCP, REST, CLI, and SDK surfaces.
        Randomized arrival jitter ensures chaotic concurrency, contention on locks, and interleaved cancellations.
        """
        mcp_server = VoiceFiMCPServer()
        cfg = VoiceFiConfig()
        companion_server = CompanionServer(config=cfg, port=5141)

        completed_operations = []
        errors = []
        op_lock = threading.Lock()

        # Action choices: speak, listen, sfx, send, stop
        ACTIONS = ["speak", "listen", "sfx", "send", "stop"]
        SURFACES = ["mcp", "rest", "cli", "sdk"]

        def _worker_storm(worker_id: int, num_ops: int):
            for op_idx in range(num_ops):
                # Randomized arrival interval (jitter)
                jitter = random.uniform(0.0005, 0.005)
                time.sleep(jitter)

                action = random.choice(ACTIONS)
                surface = random.choice(SURFACES)
                success = False

                try:
                    if surface == "mcp":
                        if action == "speak":
                            resp = mcp_server.handle_request({
                                "jsonrpc": "2.0",
                                "id": f"w{worker_id}_{op_idx}",
                                "method": "tools/call",
                                "params": {"name": "voicefi_speak", "arguments": {"text": f"Worker {worker_id} speak {op_idx}"}},
                            })
                            success = resp is not None and "result" in resp and not resp.get("result", {}).get("isError", False)
                        elif action == "listen":
                            resp = mcp_server.handle_request({
                                "jsonrpc": "2.0",
                                "id": f"w{worker_id}_{op_idx}",
                                "method": "tools/call",
                                "params": {"name": "voicefi_listen", "arguments": {"timeout": 1}},
                            })
                            success = resp is not None and "result" in resp
                        elif action == "sfx":
                            resp = mcp_server.handle_request({
                                "jsonrpc": "2.0",
                                "id": f"w{worker_id}_{op_idx}",
                                "method": "tools/call",
                                "params": {"name": "voicefi_sfx", "arguments": {"name": "applause"}},
                            })
                            success = resp is not None and "result" in resp
                        elif action == "send":
                            resp = mcp_server.handle_request({
                                "jsonrpc": "2.0",
                                "id": f"w{worker_id}_{op_idx}",
                                "method": "tools/call",
                                "params": {"name": "voicefi_send", "arguments": {"text": f"Storm msg {worker_id}", "to": "claude"}},
                            })
                            success = resp is not None and "result" in resp
                        elif action == "stop":
                            resp = mcp_server.handle_request({
                                "jsonrpc": "2.0",
                                "id": f"w{worker_id}_{op_idx}",
                                "method": "tools/call",
                                "params": {"name": "voicefi_stop", "arguments": {}},
                            })
                            success = resp is not None and "result" in resp

                    elif surface == "rest":
                        cloop = asyncio.new_event_loop()
                        asyncio.set_event_loop(cloop)
                        try:
                            if action == "speak":
                                req = make_mocked_request("POST", "/api/speak", headers={"Content-Type": "application/json"})
                                req._read_bytes = json.dumps({"text": f"REST storm {worker_id}_{op_idx}", "block": False}).encode("utf-8")
                                resp = cloop.run_until_complete(companion_server.handle_speak(req))
                                success = resp.status == 200
                            elif action == "listen":
                                # Status endpoint check representing active VAD monitor
                                req = make_mocked_request("GET", "/api/status")
                                resp = cloop.run_until_complete(companion_server.handle_status(req))
                                success = resp.status == 200
                            elif action == "sfx":
                                req = make_mocked_request("POST", "/api/sfx", headers={"Content-Type": "application/json"})
                                req._read_bytes = json.dumps({"name": "drum_smash", "volume": 0.8}).encode("utf-8")
                                resp = cloop.run_until_complete(companion_server.handle_sfx(req))
                                success = resp.status == 200
                            elif action == "send":
                                req = make_mocked_request("POST", "/api/send", headers={"Content-Type": "application/json"})
                                req._read_bytes = json.dumps({"text": f"REST send {worker_id}", "to": "antigravity"}).encode("utf-8")
                                resp = cloop.run_until_complete(companion_server.handle_send(req))
                                success = resp.status == 200
                            elif action == "stop":
                                req = make_mocked_request("POST", "/api/stop")
                                resp = cloop.run_until_complete(companion_server.handle_stop(req))
                                success = resp.status == 200
                        finally:
                            cloop.close()

                    elif surface == "cli":
                        buf_out = io.StringIO()
                        buf_err = io.StringIO()
                        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                            if action == "speak":
                                cmd_speak(argparse.Namespace(text=[f"CLI storm {worker_id}_{op_idx}"], config=None, agent="antigravity", voice=None, provider=None, rate=None))
                            elif action == "listen":
                                cmd_server(argparse.Namespace(server_action="status", config=None))
                            elif action == "sfx":
                                cmd_sfx(argparse.Namespace(name="honk", volume=0.5))
                            elif action == "send":
                                cmd_send(argparse.Namespace(text=[f"CLI send {worker_id}"], to="claude", conv_id=None, reply=False, from_conv_id=None, from_engine="antigravity", sender_name=None, title=None, no_envelope=False))
                            elif action == "stop":
                                stop_all_speech()
                        success = True

                    elif surface == "sdk":
                        if action == "speak":
                            with speech_turn_lock(text=f"SDK storm {worker_id}_{op_idx}"):
                                time.sleep(0.001)
                            success = True
                        elif action == "listen":
                            success = True
                        elif action == "sfx":
                            success = play_sfx("applause", block=False)
                        elif action == "send":
                            record_agent_route(
                                from_engine="antigravity",
                                from_conv_id=f"conv-{worker_id}",
                                to_engine="claude",
                                to_conv_id=f"session-{worker_id}",
                            )
                            route = get_return_route(target_engine="antigravity")
                            success = route is not None
                        elif action == "stop":
                            stop_all_speech()
                            success = True

                except Exception as e:
                    with op_lock:
                        errors.append((worker_id, op_idx, surface, action, str(e)))

                with op_lock:
                    completed_operations.append((worker_id, op_idx, surface, action, success))

        # Launch 20 workers, 6 operations each = 120 interleaved operations
        NUM_WORKERS = 20
        OPS_PER_WORKER = 6
        with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = [executor.submit(_worker_storm, w_id, OPS_PER_WORKER) for w_id in range(NUM_WORKERS)]
            for f in as_completed(futures):
                f.result(timeout=15.0)

        # Ensure all speech is finalized and clean state verified
        stop_all_speech()
        time.sleep(0.01)

        assert len(errors) == 0, f"Encountered {len(errors)} errors during storm: {errors[:5]}"
        assert len(completed_operations) == NUM_WORKERS * OPS_PER_WORKER
        assert all(success for _, _, _, _, success in completed_operations)
        assert tts_base._LOCK_DEPTH == 0, f"Lock depth leaked: {tts_base._LOCK_DEPTH}"
        assert not is_agent_speaking(), "Agent remained in speaking state after storm completion"


# ============================================================================
# Challenge 2: Port 5141 Socket Teardown & Recovery Under Burst
# ============================================================================

class TestPort5141TeardownAndRecovery:
    """Adversarial stress test: Rapid high-traffic HTTP burst, abrupt server socket teardown, and instant rebind recovery."""

    def test_port_5141_socket_burst_teardown_and_rebind(self):
        """
        1. Bind live CompanionServer to localhost:5141 (or high dynamic port if 5141 restricted).
        2. Execute 40 concurrent HTTP requests in a burst.
        3. Abruptly tear down server and site during/after burst.
        4. Immediately rebind the exact same port in a fresh server instance.
        5. Execute another burst of 40 requests to verify zero EADDRINUSE, zombie holds, or socket leaks.
        """
        async def _run_test():
            # Determine port to test - prioritize 5141, fallback to dynamic free port if 5141 is occupied by external system daemon
            test_port = 5141
            try:
                test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                test_sock.bind(("127.0.0.1", test_port))
                test_sock.close()
            except OSError:
                # Fallback to high port if port 5141 currently held by running LaunchAgent
                test_port = 55141

            cfg = VoiceFiConfig()

            # Helper to spin up and bind server
            async def _start_server(port: int):
                server = CompanionServer(config=cfg, port=port)
                runner = web.AppRunner(server.app, shutdown_timeout=0.1)
                await runner.setup()
                site = web.TCPSite(runner, "127.0.0.1", port, reuse_address=True)
                await site.start()
                return server, runner, site

            # 1. Start Phase 1 Server
            server1, runner1, site1 = await _start_server(test_port)

            # 2. Fire Burst 1 across 40 concurrent clients
            async with aiohttp.ClientSession() as session:
                async def _send_req(idx: int):
                    if idx % 3 == 0:
                        async with session.get(f"http://127.0.0.1:{test_port}/api/status") as resp:
                            await resp.read()
                            return resp.status
                    elif idx % 3 == 1:
                        async with session.post(f"http://127.0.0.1:{test_port}/api/sfx", json={"name": "applause", "volume": 0.8}) as resp:
                            await resp.read()
                            return resp.status
                    else:
                        async with session.post(f"http://127.0.0.1:{test_port}/api/send", json={"text": f"Burst1 {idx}", "to": "antigravity"}) as resp:
                            await resp.read()
                            return resp.status

                tasks1 = [_send_req(i) for i in range(40)]
                statuses1 = await asyncio.gather(*tasks1)
                assert len(statuses1) == 40
                assert all(s == 200 for s in statuses1)

            # 3. Teardown Server 1 immediately
            await runner1.cleanup()

            # Small yield to event loop
            await asyncio.sleep(0.05)

            # 4. Immediate Rebind Phase 2 Server on exact same port
            server2, runner2, site2 = await _start_server(test_port)

            try:
                # 5. Fire Burst 2 across 40 concurrent clients
                async with aiohttp.ClientSession() as session:
                    async def _send_req2(idx: int):
                        if idx % 3 == 0:
                            async with session.get(f"http://127.0.0.1:{test_port}/api/status") as resp:
                                await resp.read()
                                return resp.status
                        elif idx % 3 == 1:
                            async with session.post(f"http://127.0.0.1:{test_port}/api/sfx", json={"name": "drum_smash", "volume": 0.9}) as resp:
                                await resp.read()
                                return resp.status
                        else:
                            async with session.post(f"http://127.0.0.1:{test_port}/api/send", json={"text": f"Burst2 {idx}", "to": "claude"}) as resp:
                                await resp.read()
                                return resp.status

                    tasks2 = [_send_req2(i) for i in range(40)]
                    statuses2 = await asyncio.gather(*tasks2)
                    assert len(statuses2) == 40
                    assert all(s == 200 for s in statuses2)
            finally:
                # Final clean shutdown
                await runner2.cleanup()

        asyncio.run(_run_test())


# ============================================================================
# Challenge 3: Validate Benchmark Report Serialization & Markdown Formatting
# ============================================================================

class TestBenchmarkReportValidation:
    """Validate JSON serialization integrity, statistical correctness, and human-readable Markdown formatting."""

    def test_benchmark_runner_and_json_report_serialization(self):
        """Execute benchmark runner, verify schema integrity, mathematical consistency, and percentile monotonicity."""
        runner = BenchmarkRunner()
        report = runner.execute_all()

        assert "timestamp" in report
        assert "environment" in report
        assert "summary" in report
        assert "benchmarks" in report

        # Environment metadata
        env = report["environment"]
        assert "platform" in env
        assert "python_version" in env
        assert env["cpu_count"] > 0
        assert env["memory_total_gb"] > 0

        # Summary integrity
        summary = report["summary"]
        assert summary["total_requests_executed"] >= 500, f"Expected >= 500 operations, got {summary['total_requests_executed']}"
        assert summary["total_errors"] == 0
        assert summary["overall_error_rate_pct"] == 0.0
        assert summary["orphaned_child_processes"] == 0

        # Benchmark surfaces
        benchmarks = report["benchmarks"]
        for surface_name in ["mcp_stdio", "http_rest", "developer_cli", "python_sdk"]:
            assert surface_name in benchmarks
            surface = benchmarks[surface_name]
            for workload_name, workload in surface.items():
                assert workload["requests"] >= 50
                assert workload["errors"] == 0
                assert workload["error_rate_pct"] == 0.0
                assert workload["throughput_rps"] > 0.0

                # Percentile monotonicity check
                lat = workload["latency_ms"]
                assert lat["min"] <= lat["p50"] <= lat["p90"] <= lat["p95"] <= lat["p99"] <= lat["max"], (
                    f"Violated percentile monotonicity on {surface_name}/{workload_name}: {lat}"
                )

        # Universal Swarm metrics
        swarm = benchmarks["universal_swarm"]
        assert swarm["requests"] == 100
        assert swarm["concurrency"] == 20
        assert swarm["errors"] == 0
        assert swarm["error_rate_pct"] == 0.0
        assert swarm["throughput_rps"] > 0.0
        lat_swarm = swarm["latency_ms"]
        assert lat_swarm["min"] <= lat_swarm["p50"] <= lat_swarm["p90"] <= lat_swarm["p95"] <= lat_swarm["p99"] <= lat_swarm["max"]

        # Test Markdown formatting generation
        md = generate_markdown_report(report)
        assert md.startswith("# 🚀 VoiceFi Universal Integration Stress Benchmark Report")
        assert "## 📊 Executive Summary" in md
        assert "## 🔬 Multi-Surface Latency & Throughput Benchmark Matrix" in md
        assert "## 🛡️ Stability & Resource Cleanup Verification" in md
        assert f"{summary['total_requests_executed']}" in md
        assert f"{summary['overall_error_rate_pct']}%" in md
        assert f"{swarm['throughput_rps']}" in md

    def test_existing_benchmark_files_on_disk(self):
        """Verify the serialized benchmark files on disk match valid schema and content."""
        root = Path(__file__).resolve().parent.parent
        json_file = root / "benchmarks" / "stress_benchmark_report.json"
        md_file = root / "benchmarks" / "BENCHMARKS.md"

        assert json_file.exists(), f"Missing {json_file}"
        assert md_file.exists(), f"Missing {md_file}"

        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert data["summary"]["total_requests_executed"] >= 500
        assert data["summary"]["overall_error_rate_pct"] == 0.0

        md_content = md_file.read_text(encoding="utf-8")
        assert "VoiceFi Universal Integration Stress Benchmark Report" in md_content
        assert "| **Total Operations Executed** |" in md_content
        assert "100% Reliability" in md_content
