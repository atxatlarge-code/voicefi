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
    assert "voicefi_send" in tool_names
    assert "voicefi_sfx" in tool_names

    # Check voicefi_speak schema has conv_id
    speak_tool = next(t for t in tools if t["name"] == "voicefi_speak")
    assert "conv_id" in speak_tool["inputSchema"]["properties"]

    # Check voicefi_listen schema has timeout
    listen_tool = next(t for t in tools if t["name"] == "voicefi_listen")
    assert "timeout" in listen_tool["inputSchema"]["properties"]


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
                "conv_id": "test-conv-speak-123",
            },
        },
    }
    mock_tts = MagicMock()
    mock_tts.persona_name = "Viv"
    with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
         patch("voicefi.integrations.conversations.claim_active_conversation_turn") as mock_claim:
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["id"] == 6
        result = resp["result"]
        assert result["isError"] is False
        mock_claim.assert_called_once_with("MCP test speech", conv_id="test-conv-speak-123")
        mock_tts.stream_speak.assert_called_once_with("MCP test speech", block=True)


def test_mcp_tool_call_speak_empty_text(server):
    req = {
        "jsonrpc": "2.0",
        "id": 61,
        "method": "tools/call",
        "params": {
            "name": "voicefi_speak",
            "arguments": {"text": "   "},
        },
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp["result"]["isError"] is True
    assert "No text provided" in resp["result"]["content"][0]["text"]


def test_mcp_tool_call_listen(server):
    from pathlib import Path
    req = {
        "jsonrpc": "2.0",
        "id": 62,
        "method": "tools/call",
        "params": {
            "name": "voicefi_listen",
            "arguments": {
                "timeout": 5,
                "max_seconds": 15,
            },
        },
    }
    mock_recorder = MagicMock()
    fake_wav = Path("/tmp/fake_test_audio.wav")
    fake_wav.write_bytes(b"RIFF....WAVE")
    mock_recorder.record_speech_auto.return_value = (None, fake_wav)

    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "Hello VoiceFi from test"

    with patch("voicefi.audio.recorder.AudioRecorder", return_value=mock_recorder) as mock_rec_cls, \
         patch("voicefi.stt.get_stt_engine", return_value=mock_stt):
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["id"] == 62
        assert resp["result"]["isError"] is False
        assert resp["result"]["content"][0]["text"] == "Hello VoiceFi from test"
        mock_rec_cls.assert_called_once()
        mock_recorder.record_speech_auto.assert_called_once_with(timeout=5.0)


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


def test_mcp_tool_call_send(server):
    from voicefi.integrations.injector import DispatchResult
    mock_success = DispatchResult(success=True, delivery_type="ipc", target_conv_id="conv-456", engine="antigravity")

    req = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "voicefi_send",
            "arguments": {
                "text": "Refactor the database module",
                "to": "antigravity",
                "conv_id": "conv-456",
                "sender": "Claude",
                "title": "Task Update",
            },
        },
    }

    with patch("voicefi.integrations.injector.send_message_to_agent", return_value=mock_success) as mock_send:
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["id"] == 9
        assert resp["result"]["isError"] is False
        assert "Successfully dispatched message" in resp["result"]["content"][0]["text"]
        mock_send.assert_called_once_with(
            conv_id="conv-456",
            text="Refactor the database module",
            sender_name="Claude",
            title="Task Update",
            target_engine="antigravity",
            from_engine="claude",
        )


def test_mcp_tool_call_send_reply(server):
    from voicefi.integrations.injector import DispatchResult
    mock_success = DispatchResult(success=True, delivery_type="ipc", target_conv_id="conv-reply", engine="claude")

    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "voicefi_send",
            "arguments": {
                "text": "All tests are passing!",
                "to": "claude",
                "reply": True,
            },
        },
    }

    with patch("voicefi.integrations.injector.send_message_to_agent", return_value=mock_success) as mock_send:
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["result"]["isError"] is False
        mock_send.assert_called_once_with(
            conv_id="reply",
            text="All tests are passing!",
            sender_name="Claude",
            title=None,
            target_engine="claude",
            from_engine="antigravity",
        )


def test_mcp_tool_call_send_failure(server):
    from voicefi.integrations.injector import DispatchResult
    mock_fail = DispatchResult(success=False, delivery_type="none", error="Connection refused")

    req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "voicefi_send",
            "arguments": {
                "text": "Failing message",
                "to": "antigravity",
            },
        },
    }

    with patch("voicefi.integrations.injector.send_message_to_agent", return_value=mock_fail):
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["result"]["isError"] is True
        assert "Failed to dispatch" in resp["result"]["content"][0]["text"]


def test_mcp_tool_call_send_empty_text(server):
    req = {
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {
            "name": "voicefi_send",
            "arguments": {"text": "   "},
        },
    }
    resp = server.handle_request(req)
    assert resp is not None
    assert resp["result"]["isError"] is True
    assert "Empty message text" in resp["result"]["content"][0]["text"]


def test_mcp_tool_call_sfx(server):
    req = {
        "jsonrpc": "2.0",
        "id": 13,
        "method": "tools/call",
        "params": {
            "name": "voicefi_sfx",
            "arguments": {
                "name": "applause",
                "volume": 0.8,
            },
        },
    }
    with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx:
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["id"] == 13
        assert resp["result"]["isError"] is False
        assert "Successfully played sound effect 'applause'" in resp["result"]["content"][0]["text"]
        mock_sfx.assert_called_once_with("applause", block=True, volume=0.8)


def test_mcp_tool_call_sfx_invalid_name(server):
    req = {
        "jsonrpc": "2.0",
        "id": 14,
        "method": "tools/call",
        "params": {
            "name": "voicefi_sfx",
            "arguments": {
                "name": "non_existent_sfx_name",
            },
        },
    }
    with patch("voicefi.audio.sfx.play_sfx", return_value=False):
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["result"]["isError"] is True
        assert "Unknown sound effect" in resp["result"]["content"][0]["text"]


def test_mcp_tool_call_ping_voice(server):
    from voicefi.troubleshoot import VoicePingResult
    mock_ping = VoicePingResult(
        voice="Viv",
        provider="edge_tts",
        persona_name="Viv",
        success=True,
        latency_ms=120.5,
        audio_bytes=24500,
        chars_per_sec=45.2,
        status="OK",
    )
    req = {
        "jsonrpc": "2.0",
        "id": 15,
        "method": "tools/call",
        "params": {
            "name": "voicefi_ping_voice",
            "arguments": {"voice": "Viv"},
        },
    }
    with patch("voicefi.troubleshoot.AudioTroubleshooter.ping_voice_silently", return_value=mock_ping):
        resp = server.handle_request(req)
        assert resp is not None
        assert resp["result"]["isError"] is False
        assert "TTFB: 120.5ms" in resp["result"]["content"][0]["text"]


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


def test_mcp_tool_call_vifi_aliases(server):
    """Test that 'vifi_*' and bare tool names are normalized and dispatched seamlessly."""
    # Test vifi_status
    req_status = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "vifi_status",
            "arguments": {},
        },
    }
    resp_status = server.handle_request(req_status)
    assert resp_status is not None
    assert resp_status["id"] == 20
    assert resp_status["result"]["isError"] is False
    status_data = json.loads(resp_status["result"]["content"][0]["text"])
    assert "primary_tts_provider" in status_data
    assert "input_device" in status_data

    # Test vifi_sfx alias
    with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx:
        req_sfx = {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {
                "name": "vifi_sfx",
                "arguments": {"name": "applause"},
            },
        }
        resp_sfx = server.handle_request(req_sfx)
        assert resp_sfx is not None
        assert resp_sfx["id"] == 21
        assert resp_sfx["result"]["isError"] is False
        mock_sfx.assert_called_once_with("applause", block=True, volume=1.0)

    # Test bare 'speak' alias
    with patch("voicefi.tts.get_tts_engine") as mock_get_tts, \
         patch("voicefi.integrations.conversations.claim_active_conversation_turn"):
        mock_engine = MagicMock()
        mock_get_tts.return_value = mock_engine
        req_speak = {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {
                "name": "speak",
                "arguments": {"text": "Testing bare speak alias"},
            },
        }
        resp_speak = server.handle_request(req_speak)
        assert resp_speak is not None
        assert resp_speak["id"] == 22
        assert resp_speak["result"]["isError"] is False
        mock_engine.stream_speak.assert_called_once_with("Testing bare speak alias", block=True)


def test_mcp_auxiliary_protocol_methods(server):
    """Test standard MCP auxiliary queries return compliant results."""
    # resources/list
    res = server.handle_request({"jsonrpc": "2.0", "id": 30, "method": "resources/list"})
    assert res is not None and res["result"] == {"resources": []}

    # resources/templates/list
    res_tpl = server.handle_request({"jsonrpc": "2.0", "id": 31, "method": "resources/templates/list"})
    assert res_tpl is not None and res_tpl["result"] == {"resourceTemplates": []}

    # prompts/list
    res_pr = server.handle_request({"jsonrpc": "2.0", "id": 32, "method": "prompts/list"})
    assert res_pr is not None and res_pr["result"] == {"prompts": []}

    # roots/list
    res_rt = server.handle_request({"jsonrpc": "2.0", "id": 33, "method": "roots/list"})
    assert res_rt is not None and res_rt["result"] == {"roots": []}

    # logging/setLevel
    res_log = server.handle_request({"jsonrpc": "2.0", "id": 34, "method": "logging/setLevel", "params": {"level": "info"}})
    assert res_log is not None and res_log["result"] == {}

    # notifications (any method with no id)
    notif = server.handle_request({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {}})
    assert notif is None


def test_mcp_run_stdio_stream_isolation(server, monkeypatch):
    """Ensure run_stdio redirects sys.stdout to sys.stderr so internal prints don't corrupt JSON-RPC."""
    import io
    import sys

    input_data = (
        json.dumps({"jsonrpc": "2.0", "id": 100, "method": "ping"}) + "\n"
    )
    fake_stdin = io.StringIO(input_data)
    fake_stdout = io.StringIO()
    fake_stderr = io.StringIO()

    monkeypatch.setattr(sys, "stdin", fake_stdin)
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    server.run_stdio()

    # JSON-RPC response must be on fake_stdout
    output_lines = [l.strip() for l in fake_stdout.getvalue().splitlines() if l.strip()]
    assert len(output_lines) == 1
    resp = json.loads(output_lines[0])
    assert resp["id"] == 100
    assert resp["result"] == {}


