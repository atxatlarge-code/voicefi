"""
Unit tests for VoiceFi IPC JSON-RPC 2.0 protocol specifications and framing.
"""

import json
import pytest

from voicefi.ipc.protocol import (
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCNotification,
    METHOD_PROMPT_DISPATCH,
    METHOD_SIGNAL_INTERRUPT,
    METHOD_VAD_SPEECH,
    METHOD_AGENT_EVENT,
    EVENT_TURN_START,
    EVENT_TOOL_START,
    EVENT_TOOL_COMPLETE,
    EVENT_TURN_COMPLETE,
    EVENT_TURN_ERROR,
    EVENT_TURN_INTERRUPTED,
    build_agent_event,
    build_prompt_dispatch_event,
    build_signal_interrupt_event,
    parse_jsonrpc_message,
)


def test_jsonrpc_request_serialization():
    req = JSONRPCRequest(method="vifi.ping", params={"key": "val"}, id=1)
    encoded = req.encode()
    assert encoded.endswith(b"\n")
    parsed = parse_jsonrpc_message(encoded)
    assert parsed["jsonrpc"] == "2.0"
    assert parsed["method"] == "vifi.ping"
    assert parsed["params"] == {"key": "val"}
    assert parsed["id"] == 1


def test_jsonrpc_response_serialization():
    resp = JSONRPCResponse(id="req-123", result={"status": "ok"})
    encoded = resp.encode()
    parsed = parse_jsonrpc_message(encoded)
    assert parsed["jsonrpc"] == "2.0"
    assert parsed["id"] == "req-123"
    assert parsed["result"] == {"status": "ok"}
    assert "error" not in parsed

    err_resp = JSONRPCResponse(id="req-456", error={"code": -32600, "message": "Invalid Request"})
    err_parsed = parse_jsonrpc_message(err_resp.encode())
    assert err_parsed["error"]["code"] == -32600
    assert "result" not in err_parsed


def test_jsonrpc_notification_serialization():
    notif = JSONRPCNotification(method=METHOD_SIGNAL_INTERRUPT, params={"reason": "speech_detected"})
    encoded = notif.encode()
    parsed = parse_jsonrpc_message(encoded)
    assert parsed["jsonrpc"] == "2.0"
    assert parsed["method"] == METHOD_SIGNAL_INTERRUPT
    assert parsed["params"]["reason"] == "speech_detected"
    assert "id" not in parsed


def test_build_prompt_dispatch_event():
    event = build_prompt_dispatch_event(
        transcript="Refactor the authentication flow and add unit tests.",
        session_id="conv-spark-001",
        source="whisperkit",
        confidence=0.98,
        metadata={"priority": "high"},
    )
    assert event["jsonrpc"] == "2.0"
    assert event["method"] == METHOD_PROMPT_DISPATCH
    assert event["params"]["transcript"] == "Refactor the authentication flow and add unit tests."
    assert event["params"]["session_id"] == "conv-spark-001"
    assert event["params"]["source"] == "whisperkit"
    assert event["params"]["confidence"] == 0.98
    assert event["params"]["metadata"]["priority"] == "high"


def test_build_signal_interrupt_event():
    event = build_signal_interrupt_event(reason="barge_in_voice", energy=0.082)
    assert event["jsonrpc"] == "2.0"
    assert event["method"] == METHOD_SIGNAL_INTERRUPT
    assert event["params"]["reason"] == "barge_in_voice"
    assert event["params"]["energy"] == 0.082
    assert "timestamp" in event["params"]


def test_build_agent_event_turn_complete():
    event = build_agent_event(
        event_type=EVENT_TURN_COMPLETE,
        agent_name="Spark",
        persona="Viv",
        spoken_summary="I refactored the auth module and all tests passed.",
        status="success",
        details={"duration_ms": 1250},
    )
    assert event["jsonrpc"] == "2.0"
    assert event["method"] == METHOD_AGENT_EVENT
    assert event["params"]["event_type"] == EVENT_TURN_COMPLETE
    assert event["params"]["agent_name"] == "Spark"
    assert event["params"]["persona"] == "Viv"
    assert event["params"]["spoken_summary"] == "I refactored the auth module and all tests passed."
    assert event["params"]["status"] == "success"
    assert event["params"]["details"]["duration_ms"] == 1250


def test_parse_jsonrpc_message_validation():
    with pytest.raises(ValueError, match="Empty message data"):
        parse_jsonrpc_message("")

    with pytest.raises(ValueError, match="JSON-RPC message must be a JSON object"):
        parse_jsonrpc_message("12345")

    with pytest.raises(ValueError, match="Missing or invalid 'jsonrpc' version"):
        parse_jsonrpc_message('{"method": "test"}')

    valid = parse_jsonrpc_message('{"jsonrpc": "2.0", "method": "test", "params": {}}')
    assert valid["method"] == "test"
