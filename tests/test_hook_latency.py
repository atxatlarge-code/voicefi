"""
CI Performance and Latency Regression Tests for VoiceFi Agent Hooks.
Enforces sub-100ms IPC dispatch and sub-350ms process execution to guarantee
that IDE and agent turns (Antigravity, Claude Code, Codex) never freeze or hold.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
import pytest


def test_companion_daemon_hook_ping_latency():
    """Verify that localhost companion daemon responds to hook pings in < 100ms."""
    url = "http://127.0.0.1:5141/api/hook/event"
    payload = json.dumps({"agent": "antigravity", "test_ping": True}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data.get("status") == "pong"
            # Daemon response should be essentially instantaneous (< 100ms)
            assert elapsed_ms < 100.0, f"IPC hook ping took {elapsed_ms:.1f}ms (threshold 100ms)"
    except urllib.error.URLError:
        pytest.skip("VoiceFi companion daemon is not running on port 5141")


def test_cli_hook_subshell_execution_latency():
    """
    Verify that executing `voicefi hook` in a real subprocess completes in < 350ms.
    Guards against:
      - Heavy top-level imports (torch, mlx, faster-whisper, cryptography)
      - Blocking telemetry flushes (posthog.flush in atexit)
      - Disk retention sweeps on CLI startup
    """
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)  # Ensure real os._exit(0) fast path is exercised

    sample_payload = json.dumps({
        "agent": "antigravity",
        "conversationId": "test-perf-conv-001",
        "test_ping": True,
    })

    import socket
    s = socket.socket()
    s.settimeout(0.3)
    is_daemon_up = (s.connect_ex(("127.0.0.1", 5141)) == 0)
    s.close()
    if not is_daemon_up:
        pytest.skip("VoiceFi companion daemon is not running on port 5141 (fast path requires running daemon)")

    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "voicefi", "hook"],
        input=sample_payload + "\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=3.0,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert proc.returncode == 0, f"Hook failed with stderr: {proc.stderr}"
    # Standard hook return must be valid JSON
    output_json = json.loads(proc.stdout.strip())
    assert isinstance(output_json, dict)

    # Hard SLA: Process must terminate in under 350ms (typically 50-80ms with fast path)
    assert elapsed_ms < 350.0, f"Subshell hook took {elapsed_ms:.1f}ms (SLA threshold 350ms)"
