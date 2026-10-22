"""
Unit tests for vifi doctor CLI, 4-point instant pipe & latency health check (<200ms),
and self-healing diagnostics.
"""

import argparse
import io
import json
import socket
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError
import urllib.request

import pytest

from voicefi.cli_commands.doctor import (
    check_audio_devices,
    check_audio_input,
    check_companion_bridge,
    check_hook_latency,
    check_ipc_socket,
    check_local_llm_warmth,
    check_package_dependencies,
    check_port_availability,
    check_privacy_and_airgap,
    check_python_environment,
    cmd_doctor,
    format_doctor_table,
    run_diagnostics,
    run_pipe_health_check,
)


def test_check_ipc_socket_roundtrip_latency(tmp_path):
    sock_file = Path("/tmp") / f"vifi_test_{int(time.time() * 1000)}.sock"
    if sock_file.exists():
        sock_file.unlink()

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_file))
    srv.listen(1)

    def _responder():
        try:
            conn, _ = srv.accept()
            with conn:
                data = conn.recv(1024)
                if b"vifi.ping" in data:
                    conn.sendall(b'{"jsonrpc":"2.0","result":{"pong":true},"id":1}\n')
        except Exception:
            pass
        finally:
            srv.close()

    t = threading.Thread(target=_responder, daemon=True)
    t.start()

    try:
        res = check_ipc_socket(socket_path=str(sock_file))
        assert res["name"] == "IPC Socket"
        assert res["status"] == "pass"
        assert res["is_connected"] is True
        assert res["pong"] is True
        assert isinstance(res["latency_ms"], float)
        assert res["latency_ms"] < 200.0
        assert "ms RTT" in res["details"]
    finally:
        t.join(timeout=1.0)
        if sock_file.exists():
            sock_file.unlink()


def test_check_ipc_socket_offline():
    res = check_ipc_socket(socket_path="/tmp/vifi_nonexistent_test.sock")
    assert res["name"] == "IPC Socket"
    assert res["status"] == "warn"
    assert res["is_connected"] is False
    assert res["latency_ms"] is None
    assert "offline" in res["details"]


def test_check_companion_bridge_listening():
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_sock_cls.return_value = mock_sock

        res = check_companion_bridge(ports=(5141, 5142))
        assert res["name"] == "Companion Bridge"
        assert res["status"] == "pass"
        assert res["all_listening"] is True
        assert res["listening_ports"] == [5141, 5142]
        assert "5141/5142 listening" in res["details"]


def test_check_companion_bridge_partial_and_offline():
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.connect_ex.side_effect = [0, 61]  # 5141 open, 5142 refused
        mock_sock_cls.return_value = mock_sock

        res_partial = check_companion_bridge(ports=(5141, 5142))
        assert res_partial["status"] == "warn"
        assert res_partial["is_listening"] is True
        assert res_partial["all_listening"] is False
        assert "Port 5141 listening" in res_partial["details"]
        assert "Port 5142 offline" in res_partial["details"]

        mock_sock.connect_ex.side_effect = [61, 61]
        res_down = check_companion_bridge(ports=(5141, 5142))
        assert res_down["status"] == "warn"
        assert res_down["is_listening"] is False
        assert "offline" in res_down["details"]


def test_check_audio_input_mac_vs_airpods():
    with patch("voicefi.cli_commands.doctor._get_bound_macos_mic_name", return_value="MacBook Pro Microphone"):
        res_mac = check_audio_input()
        assert res_mac["name"] == "Audio Input"
        assert res_mac["status"] == "pass"
        assert res_mac["input_device"] == "MacBook Pro Microphone"
        assert res_mac["is_airpod_or_bt"] is False
        assert "MacBook Pro Microphone" in res_mac["details"]

    with patch("voicefi.cli_commands.doctor._get_bound_macos_mic_name", return_value="Jake’s AirPods Pro"):
        res_bt = check_audio_input()
        assert res_bt["status"] == "warn"
        assert res_bt["is_airpod_or_bt"] is True
        assert "AirPods Pro" in res_bt["details"]
        assert "Bluetooth/AirPod" in res_bt["details"]

    with patch("voicefi.cli_commands.doctor._get_bound_macos_mic_name", return_value=None):
        res_none = check_audio_input()
        assert res_none["status"] == "fail"
        assert res_none["input_device"] is None


def test_check_local_llm_warmth_warm_vs_cold(monkeypatch):
    # Case 1: qwen2.5-coder warm in Unified Memory, gemma cold on disk
    warm_payload = {
        "models": [
            {
                "name": "qwen2.5-coder:7b",
                "model": "qwen2.5-coder:7b",
                "size": 4700000000,
                "size_vram": 4700000000,
            }
        ]
    }

    class _FakeResp:
        status = 200

        def __init__(self, body: dict):
            self._raw = json.dumps(body).encode("utf-8")

        def read(self):
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=0.08: _FakeResp(warm_payload),
    )
    res_warm = check_local_llm_warmth()
    assert res_warm["name"] == "Local LLM Warmth"
    assert res_warm["status"] == "pass"
    assert res_warm["is_ollama_online"] is True
    assert "qwen2.5-coder:7b" in res_warm["warm_models"]
    assert "gemma" in res_warm["cold_models"]
    assert "Warm (Unified Memory)" in res_warm["details"]
    assert "Cold (Disk): gemma" in res_warm["details"]

    # Case 2: 0 models loaded in Unified Memory (all cold on disk)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=0.08: _FakeResp({"models": []}),
    )
    res_cold = check_local_llm_warmth()
    assert res_cold["status"] == "warn"
    assert res_cold["warm_models"] == []
    assert "Cold on disk" in res_cold["details"]

    # Case 3: Ollama daemon unreachable
    def _raise_err(*args, **kwargs):
        raise URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_err)
    res_offline = check_local_llm_warmth()
    assert res_offline["status"] == "warn"
    assert res_offline["is_ollama_online"] is False
    assert "Cold on disk" in res_offline["details"]


def test_run_pipe_health_check_under_200ms():
    report = run_pipe_health_check()
    assert len(report["checks"]) == 4
    assert report["elapsed_ms"] < 200.0
    check_names = [c["name"] for c in report["checks"]]
    assert check_names == [
        "IPC Socket",
        "Companion Bridge",
        "Audio Input",
        "Local LLM Warmth",
    ]
    table = format_doctor_table(report["checks"], elapsed_ms=report["elapsed_ms"])
    assert "IPC Socket" in table
    assert "Companion Bridge" in table
    assert "Audio Input" in table
    assert "Local LLM Warmth" in table


def test_check_python_environment():
    res = check_python_environment()
    assert res["category"] == "Environment"
    assert res["status"] in ("pass", "warn")
    assert "version" in res


def test_check_package_dependencies():
    res = check_package_dependencies()
    assert isinstance(res, list)
    assert len(res) >= 2
    names = [r["name"] for r in res]
    assert any("Tokenizers" in n for n in names)


def test_check_audio_devices():
    with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
        mock_devs.return_value = (
            {"name": "Studio Mic"},
            {"name": "Studio Monitors", "default_samplerate": 48000.0},
        )
        res = check_audio_devices()
        assert res["status"] == "pass"
        assert res["output_samplerate"] == 48000.0
        assert "Studio Monitors" in res["details"]
        assert res["audio_input_lock_recommended"] is False


def test_check_audio_devices_bluetooth_input_lock_warning():
    with patch("voicefi.audio.device.get_default_audio_devices") as mock_devs:
        mock_devs.return_value = (
            {"name": "Pixel Buds Pro 2"},
            {"name": "Pixel Buds Pro 2", "default_samplerate": 44100.0},
        )
        res = check_audio_devices()
        assert res["status"] == "warn"
        assert res["audio_input_lock_recommended"] is True
        assert "Audio Input Device Lock" in res["details"]
        assert "MacBook Pro Microphone" in res["details"]


def test_check_port_availability():
    with patch("socket.socket") as mock_sock_cls:
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0  # Port is open/listening
        mock_sock_cls.return_value = mock_sock

        res = check_port_availability()
        assert len(res) == 2
        assert res[0]["is_running"] is True


def test_check_privacy_and_airgap(monkeypatch):
    # Online mode
    monkeypatch.delenv("VOICEFI_OFFLINE", raising=False)
    monkeypatch.delenv("VOICEFI_AIRGAP", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    monkeypatch.setenv("VOICEFI_TELEMETRY", "1")

    res_online = check_privacy_and_airgap()
    assert res_online["is_offline_mode"] is False

    # Offline mode
    monkeypatch.setenv("VOICEFI_OFFLINE", "1")
    res_offline = check_privacy_and_airgap()
    assert res_offline["is_offline_mode"] is True
    assert "Air-Gap Active" in res_offline["details"]


def test_check_hook_latency():
    res = check_hook_latency()
    assert res["category"] == "Agent Integration"
    assert res["status"] in ("pass", "warn")
    assert "details" in res


def test_check_hook_latency_daemon_offline(monkeypatch):
    def mock_urlopen(*args, **kwargs):
        raise URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    res = check_hook_latency()
    assert res["status"] == "warn"
    assert res["is_daemon_active"] is False
    assert "not responding" in res["details"]


def test_cmd_doctor_cli(monkeypatch, capsys):
    args = argparse.Namespace(json=False, fix=False, full=False, socket=None)
    ret = cmd_doctor(args)
    assert ret in (0, 1)
    captured = capsys.readouterr().out
    assert "VoiceFi Doctor" in captured
    assert "IPC Socket" in captured
    assert "Companion Bridge" in captured
    assert "Audio Input" in captured
    assert "Local LLM Warmth" in captured

    args_json = argparse.Namespace(json=True, fix=False, full=False, socket=None)
    ret_json = cmd_doctor(args_json)
    assert ret_json in (0, 1)
    json_out = json.loads(capsys.readouterr().out)
    assert len(json_out["checks"]) == 4
