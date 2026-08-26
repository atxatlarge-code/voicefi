"""
Unit tests for VoiceFi Model Context Protocol (MCP) server.
"""

import json
from unittest.mock import patch, MagicMock
import pytest

from voicefi.mcp_server import VoiceFiMCPServer, MCP_TOOLS


@pytest.fixture
def server():
    return VoiceFiMCPServer()


def test_mcp_initialize(server):
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "antigravity", "version": "1.0"},
        },
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "voicefi"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_ping(server):
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "ping",
        "params": {},
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 2
    assert resp["result"] == {}


def test_mcp_notification_ignored(server):
    req = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }
    resp = server.handle_request(req)
    assert resp is None


def test_mcp_tools_list(server):
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/list",
        "params": {},
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 3
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "voicefi_speak" in tool_names
    assert "voicefi_listen" in tool_names
    assert "voicefi_stop" in tool_names
    assert "voicefi_status" in tool_names
    assert "voicefi_set_voice" in tool_names
    assert "voicefi_ping_voice" in tool_names


def test_mcp_tool_call_status(server):
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "voicefi_status",
            "arguments": {},
        },
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 4
    result = resp["result"]
    assert result["isError"] is False
    content = result["content"][0]["text"]
    data = json.loads(content)
    assert "input_device" in data
    assert "output_device" in data
    assert "daemon_running" in data


def test_mcp_tool_call_stop(server):
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "voicefi_stop",
            "arguments": {},
        },
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 5
    result = resp["result"]
    assert result["isError"] is False
    assert "Stopped" in result["content"][0]["text"]


def test_mcp_tool_call_speak_mocked(server):
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "voicefi_speak",
            "arguments": {
                "text": "MCP test speech",
                "persona": "Viv",
            },
        },
    }
    mock_tts = MagicMock()
    mock_tts.persona_name = "Viv"
    with patch("voicefi.tts.get_tts_engine", return_value=mock_tts):
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["id"] == 6
        result = resp["result"]
        assert result["isError"] is False
        mock_tts.stream_speak.assert_called_once_with("MCP test speech", block=True)


def test_mcp_tool_call_set_voice(server):
    req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "voicefi_set_voice",
            "arguments": {
                "agent": "antigravity",
                "persona": "Ava (Premium)",
            },
        },
    }
    with patch("voicefi.config.save_config"):
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["id"] == 7
        result = resp["result"]
        assert result["isError"] is False
        assert "Successfully updated voice" in result["content"][0]["text"]


def test_mcp_unknown_method(server):
    req = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "unknown_rpc_method",
        "params": {},
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp["id"] == 8
    assert "error" in resp
    assert resp["error"]["code"] == -32601
