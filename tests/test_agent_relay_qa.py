"""
Quality Assurance tests for VoiceFi Agent Relay & Cross-Agent Dispatch.
Validates:
1. DispatchResult serialization and to_dict() contract.
2. send_message_to_agent engine alias and kwargs compatibility.
3. Companion server /api/peer/send JSON serialization.
4. Companion server broadcast_event resilience with custom dataclasses.
5. MCP voicefi_send headless support for zero screen hijacking.
6. CLI argument parser --headless flag.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest
from aiohttp.test_utils import make_mocked_request

from voicefi.integrations.injector import DispatchResult, send_message_to_agent
from voicefi.mcp_server import VoiceFiMCPServer
from voicefi.cli import build_parser


def test_dispatch_result_contract():
    """Verify DispatchResult bool conversion, to_dict(), and JSON serialization."""
    res = DispatchResult(
        success=True,
        delivery_type="ipc",
        error=None,
        target_conv_id="conv-123",
        engine="antigravity",
    )
    assert bool(res) is True
    assert res == True

    as_dict = res.to_dict()
    assert as_dict["success"] is True
    assert as_dict["delivery_type"] == "ipc"
    assert as_dict["target_conv_id"] == "conv-123"

    # Should serialize cleanly via json.dumps with to_dict()
    encoded = json.dumps(as_dict)
    assert "conv-123" in encoded


def test_send_message_to_agent_engine_alias():
    """Verify send_message_to_agent supports engine= parameter and **kwargs."""
    with patch("voicefi.integrations.injector.send_message_to_antigravity") as mock_agy:
        mock_agy.return_value = DispatchResult(success=True, delivery_type="ipc")

        # Call with engine= instead of target_engine=
        res = send_message_to_agent(
            engine="antigravity",
            text="Testing engine alias",
            extra_unrecognized_arg="should_not_raise",
        )
        assert bool(res) is True
        mock_agy.assert_called_once()


def test_handle_peer_send_json_serializable():
    """Verify /api/peer/send endpoint serializes DispatchResult cleanly without 500 error."""
    from voicefi.companion.server import CompanionServer
    from voicefi.config import VoiceFiConfig

    cfg = VoiceFiConfig()
    server = CompanionServer(config=cfg)

    payload = {
        "text": "Task from peer Mac",
        "sender_name": "Dev",
        "sender_device": "Jake's MacBook",
        "target_engine": "antigravity",
    }

    req = make_mocked_request(
        "POST",
        "/api/peer/send",
        headers={"Content-Type": "application/json"},
    )
    async def mock_json():
        return payload
    req.json = mock_json

    with patch("voicefi.companion.handlers.peers.send_message_to_agent") as mock_send:
        mock_send.return_value = DispatchResult(
            success=True,
            delivery_type="ipc",
            target_conv_id="target-conv-999",
            engine="antigravity",
        )

        resp = asyncio.run(server.handle_peer_send(req))
        assert resp.status == 200
        body = json.loads(resp.body.decode("utf-8"))
        assert body["success"] is True
        assert body["delivered"] is True
        assert body["delivery_type"] == "ipc"


def test_broadcast_event_resilience():
    """Verify broadcast_event does not crash when event_data contains DispatchResult or dataclass."""
    from voicefi.companion.server import CompanionServer
    from voicefi.config import VoiceFiConfig

    server = CompanionServer(config=VoiceFiConfig())
    server.loop = MagicMock()

    # Pass an event containing a raw DispatchResult dataclass
    raw_result = DispatchResult(success=True, delivery_type="ipc", target_conv_id="abc")
    event_data = {
        "type": "test_event",
        "result": raw_result,
    }

    # Must not raise TypeError
    server.broadcast_event(event_data)


def test_mcp_voicefi_send_headless_support():
    """Verify MCP voicefi_send sets use_headless=True when requested to prevent screen focus stealing."""
    server = VoiceFiMCPServer()

    with patch("voicefi.integrations.injector.send_message_to_agent") as mock_send:
        mock_send.return_value = DispatchResult(
            success=True,
            delivery_type="headless",
            target_conv_id="claude_test",
            engine="claude",
        )

        args = {
            "text": "Review PR #42",
            "to": "claude",
            "headless": True,
        }
        res = server._tool_send(args)
        assert res["isError"] is False

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        assert call_kwargs.get("use_headless") is True


def test_cli_parser_send_headless_flag():
    """Verify vifi send accepts --headless flag."""
    parser = build_parser()
    args = parser.parse_args(["send", "Hello", "from", "test", "--to", "claude", "--headless"])
    assert args.text == ["Hello", "from", "test"]
    assert args.to == "claude"
    assert args.headless is True
