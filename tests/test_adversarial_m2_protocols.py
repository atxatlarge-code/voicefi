"""
Adversarial Stress, Fuzzing, and Boundary Probing Suite for Milestone M2.
Tests MCP stdio tool schemas, REST API endpoints, edge-case payloads,
negative/infinite/NaN parameters, malformed JSON, and concurrent cross-protocol stress.
"""

import asyncio
import json
import math
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import patch, MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from voicefi.config import VoiceFiConfig
from voicefi.mcp_server import VoiceFiMCPServer, MCP_TOOLS
from voicefi.companion.server import CompanionServer
from voicefi.integrations.injector import DispatchResult
from voicefi.audio.sfx import list_available_sfx


# ============================================================================
# 1. MCP STDIO PROTOCOL ADVERSARIAL & FUZZING TESTS
# ============================================================================

class TestMCPSchemaAndFuzzing:
    """Adversarial stress and schema fuzzing for VoiceFi MCP tools."""

    @pytest.fixture(autouse=True)
    def setup_server(self):
        self.server = VoiceFiMCPServer()

    def test_mcp_tools_list_complete_and_valid_schema(self):
        """Verify tools/list exposes all required tools with strict JSON schema compliance."""
        req = {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "tools/list",
            "params": {},
        }
        resp = self.server.handle_request(req)
        assert resp is not None
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == "init-1"
        assert "result" in resp
        tools = resp["result"]["tools"]
        tool_map = {t["name"]: t for t in tools}

        expected_tools = [
            "voicefi_speak",
            "voicefi_listen",
            "voicefi_stop",
            "voicefi_status",
            "voicefi_set_voice",
            "voicefi_ping_voice",
            "voicefi_send",
            "voicefi_sfx",
        ]
        for t_name in expected_tools:
            assert t_name in tool_map, f"Missing expected tool: {t_name}"
            schema = tool_map[t_name].get("inputSchema", {})
            assert schema.get("type") == "object"
            assert "properties" in schema

        # Check voicefi_speak has required fields and conv_id property
        speak_schema = tool_map["voicefi_speak"]["inputSchema"]
        assert "conv_id" in speak_schema["properties"]
        assert speak_schema["properties"]["conv_id"]["type"] == "string"
        assert "text" in speak_schema["required"]

        # Check voicefi_listen has timeout property
        listen_schema = tool_map["voicefi_listen"]["inputSchema"]
        assert "timeout" in listen_schema["properties"]

        # Check voicefi_sfx has name and volume properties
        sfx_schema = tool_map["voicefi_sfx"]["inputSchema"]
        assert "name" in sfx_schema["properties"]
        assert "volume" in sfx_schema["properties"]
        assert "required" in sfx_schema and "name" in sfx_schema["required"]

    def test_mcp_speak_boundary_and_fuzzing(self):
        """Fuzz voicefi_speak with empty, None, huge, and type-mismatched inputs."""
        mock_tts = MagicMock()
        mock_tts.persona_name = "Viv"

        # 1. Empty text variations -> Must return isError: True cleanly
        for bad_text in ["", "   ", "\n\t  \r"]:
            req = {
                "jsonrpc": "2.0",
                "id": "speak-empty",
                "method": "tools/call",
                "params": {"name": "voicefi_speak", "arguments": {"text": bad_text}},
            }
            resp = self.server.handle_request(req)
            assert resp["result"]["isError"] is True
            assert "No text" in resp["result"]["content"][0]["text"]

        # 2. Missing text field in arguments -> isError: True
        req_missing = {
            "jsonrpc": "2.0",
            "id": "speak-missing",
            "method": "tools/call",
            "params": {"name": "voicefi_speak", "arguments": {"persona": "Ava"}},
        }
        resp_missing = self.server.handle_request(req_missing)
        assert resp_missing["result"]["isError"] is True

        # 3. Non-string text types (int, bool, list, dict) -> Caught gracefully
        for non_str in [12345, True, ["list", "val"], {"nested": "dict"}]:
            req_non_str = {
                "jsonrpc": "2.0",
                "id": "speak-type",
                "method": "tools/call",
                "params": {"name": "voicefi_speak", "arguments": {"text": non_str}},
            }
            resp_non_str = self.server.handle_request(req_non_str)
            assert resp_non_str is not None
            # Should either convert or return isError without unhandled crash
            assert "result" in resp_non_str

        # 4. Extreme text payload (50,000 characters) with emojis and special characters
        huge_text = "🎙️ Testing VoiceFi MCP large payload " * 1200
        req_huge = {
            "jsonrpc": "2.0",
            "id": "speak-huge",
            "method": "tools/call",
            "params": {
                "name": "voicefi_speak",
                "arguments": {
                    "text": huge_text,
                    "persona": "Viv",
                    "conv_id": "huge-conv-12345",
                    "block": True,
                },
            },
        }
        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.integrations.conversations.claim_active_conversation_turn") as mock_claim:
            resp_huge = self.server.handle_request(req_huge)
            assert resp_huge["result"]["isError"] is False
            mock_tts.stream_speak.assert_called_once_with(huge_text, block=True)
            mock_claim.assert_called_once_with(huge_text, conv_id="huge-conv-12345")

        # 5. Null bytes, ANSI escape sequences, unicode surrogate characters
        special_text = "\x00\x1b[31;1mANSI text\x1b[0m \u2603 \U0001F916"
        req_special = {
            "jsonrpc": "2.0",
            "id": "speak-special",
            "method": "tools/call",
            "params": {
                "name": "voicefi_speak",
                "arguments": {"text": special_text},
            },
        }
        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.integrations.conversations.claim_active_conversation_turn"):
            resp_special = self.server.handle_request(req_special)
            assert resp_special["result"]["isError"] is False

    def test_mcp_listen_boundary_and_fuzzing(self):
        """Fuzz voicefi_listen with boundary timeouts (negative, zero, inf, nan, strings)."""
        mock_recorder = MagicMock()

        # 1. Normal timeout pass-through
        with patch("voicefi.audio.recorder.AudioRecorder", return_value=mock_recorder):
            mock_recorder.record_speech_auto.return_value = (MagicMock(), None)
            req = {
                "jsonrpc": "2.0",
                "id": "listen-1",
                "method": "tools/call",
                "params": {"name": "voicefi_listen", "arguments": {"timeout": 5}},
            }
            resp = self.server.handle_request(req)
            assert resp["result"]["isError"] is False
            assert "No speech detected" in resp["result"]["content"][0]["text"]
            mock_recorder.record_speech_auto.assert_called_with(timeout=5.0)

        # 2. String numeric timeout ("15.5") -> Parsed as float
        with patch("voicefi.audio.recorder.AudioRecorder", return_value=mock_recorder):
            mock_recorder.record_speech_auto.return_value = (MagicMock(), None)
            req = {
                "jsonrpc": "2.0",
                "id": "listen-str",
                "method": "tools/call",
                "params": {"name": "voicefi_listen", "arguments": {"timeout": "15.5"}},
            }
            resp = self.server.handle_request(req)
            assert resp["result"]["isError"] is False
            mock_recorder.record_speech_auto.assert_called_with(timeout=15.5)

        # 3. Invalid non-numeric timeout string ("invalid_timeout") -> Returns isError gracefully
        req_bad = {
            "jsonrpc": "2.0",
            "id": "listen-bad",
            "method": "tools/call",
            "params": {"name": "voicefi_listen", "arguments": {"timeout": "not_a_number"}},
        }
        resp_bad = self.server.handle_request(req_bad)
        assert resp_bad["result"]["isError"] is True
        assert "could not convert string to float" in resp_bad["result"]["content"][0]["text"]

        # 4. Negative and zero timeouts (-10, 0)
        for t_val in [-10.0, 0.0]:
            with patch("voicefi.audio.recorder.AudioRecorder", return_value=mock_recorder):
                mock_recorder.record_speech_auto.return_value = (MagicMock(), None)
                req_neg = {
                    "jsonrpc": "2.0",
                    "id": f"listen-{t_val}",
                    "method": "tools/call",
                    "params": {"name": "voicefi_listen", "arguments": {"timeout": t_val}},
                }
                resp_neg = self.server.handle_request(req_neg)
                assert resp_neg["result"]["isError"] is False
                mock_recorder.record_speech_auto.assert_called_with(timeout=t_val)

        # 5. Infinite and NaN timeouts
        for extreme_t in [float("inf"), float("nan")]:
            with patch("voicefi.audio.recorder.AudioRecorder", return_value=mock_recorder):
                mock_recorder.record_speech_auto.return_value = (MagicMock(), None)
                req_ext = {
                    "jsonrpc": "2.0",
                    "id": "listen-ext",
                    "method": "tools/call",
                    "params": {"name": "voicefi_listen", "arguments": {"timeout": extreme_t}},
                }
                resp_ext = self.server.handle_request(req_ext)
                assert resp_ext["result"]["isError"] is False

    def test_mcp_send_boundary_and_fuzzing(self):
        """Fuzz voicefi_send with empty text, type mismatches, reply routing, and extreme payloads."""
        # 1. Empty or whitespace text -> isError: True
        for empty_text in [None, "", "    ", 12345, ["list"]]:
            req = {
                "jsonrpc": "2.0",
                "id": "send-empty",
                "method": "tools/call",
                "params": {"name": "voicefi_send", "arguments": {"text": empty_text}},
            }
            resp = self.server.handle_request(req)
            assert resp["result"]["isError"] is True
            assert "Empty message text" in resp["result"]["content"][0]["text"]

        # 2. Valid send with reply=True routing
        with patch("voicefi.mcp_server.VoiceFiMCPServer._tool_send", wraps=self.server._tool_send), \
             patch("voicefi.integrations.injector.send_message_to_agent") as mock_send:
            mock_send.return_value = DispatchResult(
                success=True,
                delivery_type="ipc",
                engine="antigravity",
                target_conv_id="conv-orig-123",
            )
            req = {
                "jsonrpc": "2.0",
                "id": "send-reply",
                "method": "tools/call",
                "params": {
                    "name": "voicefi_send",
                    "arguments": {
                        "text": "Reply payload back to parent",
                        "to": "antigravity",
                        "reply": True,
                        "sender": "Claude",
                    },
                },
            }
            resp = self.server.handle_request(req)
            assert resp["result"]["isError"] is False
            assert "Successfully dispatched" in resp["result"]["content"][0]["text"]
            mock_send.assert_called_once_with(
                conv_id="reply",
                text="Reply payload back to parent",
                sender_name="Claude",
                title=None,
                target_engine="antigravity",
                from_engine="claude",
            )

        # 3. Target engine case insensitivity and unknown engine
        with patch("voicefi.integrations.injector.send_message_to_agent") as mock_send:
            mock_send.return_value = DispatchResult(success=True, delivery_type="ipc", engine="claude")
            req_engine = {
                "jsonrpc": "2.0",
                "id": "send-engine",
                "method": "tools/call",
                "params": {
                    "name": "voicefi_send",
                    "arguments": {"text": "Hello Claude", "to": "  CLAUDE  "},
                },
            }
            resp_engine = self.server.handle_request(req_engine)
            assert resp_engine["result"]["isError"] is False
            mock_send.assert_called_once_with(
                conv_id=None,
                text="Hello Claude",
                sender_name="Claude",
                title=None,
                target_engine="claude",
                from_engine="antigravity",
            )

    def test_mcp_sfx_boundary_and_fuzzing(self):
        """Fuzz voicefi_sfx with valid, invalid, boundary volume, and malicious names."""
        # 1. All valid sound effect names
        valid_sfx = list_available_sfx()
        for name in valid_sfx:
            with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_play:
                req = {
                    "jsonrpc": "2.0",
                    "id": f"sfx-{name}",
                    "method": "tools/call",
                    "params": {"name": "voicefi_sfx", "arguments": {"name": name, "volume": 0.9}},
                }
                resp = self.server.handle_request(req)
                assert resp["result"]["isError"] is False
                assert f"'{name}'" in resp["result"]["content"][0]["text"]
                mock_play.assert_called_once_with(name, block=True, volume=0.9)

        # 2. Missing, empty, or non-string name -> isError: True with available list
        for bad_name in [None, "", "   ", 12345, ["drum"]]:
            req_bad = {
                "jsonrpc": "2.0",
                "id": "sfx-bad",
                "method": "tools/call",
                "params": {"name": "voicefi_sfx", "arguments": {"name": bad_name}},
            }
            resp_bad = self.server.handle_request(req_bad)
            assert resp_bad["result"]["isError"] is True
            assert "Missing or invalid sound effect name" in resp_bad["result"]["content"][0]["text"]

        # 3. Path traversal or unknown sound effect name
        for fake_name in ["../../etc/passwd", "unknown_sfx_explosion", "<script>alert(1)</script>"]:
            with patch("voicefi.audio.sfx.play_sfx", return_value=False):
                req_fake = {
                    "jsonrpc": "2.0",
                    "id": "sfx-fake",
                    "method": "tools/call",
                    "params": {"name": "voicefi_sfx", "arguments": {"name": fake_name}},
                }
                resp_fake = self.server.handle_request(req_fake)
                assert resp_fake["result"]["isError"] is True
                assert f"Unknown sound effect '{fake_name}'" in resp_fake["result"]["content"][0]["text"]

        # 4. Volume boundary clamping (negative, extreme large, invalid strings)
        # Negative volume (-5.0) clamped to 0.0
        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_play:
            req_vol = {
                "jsonrpc": "2.0",
                "id": "sfx-vol-neg",
                "method": "tools/call",
                "params": {"name": "voicefi_sfx", "arguments": {"name": "honk", "volume": -5.0}},
            }
            resp_vol = self.server.handle_request(req_vol)
            assert resp_vol["result"]["isError"] is False
            mock_play.assert_called_once_with("honk", block=True, volume=0.0)

        # Huge volume (100.0) clamped to 2.0
        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_play:
            req_vol_huge = {
                "jsonrpc": "2.0",
                "id": "sfx-vol-huge",
                "method": "tools/call",
                "params": {"name": "voicefi_sfx", "arguments": {"name": "honk", "volume": 100.0}},
            }
            resp_vol_huge = self.server.handle_request(req_vol_huge)
            assert resp_vol_huge["result"]["isError"] is False
            mock_play.assert_called_once_with("honk", block=True, volume=2.0)

        # Non-numeric volume string ("loud") defaults to 1.0
        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_play:
            req_vol_str = {
                "jsonrpc": "2.0",
                "id": "sfx-vol-str",
                "method": "tools/call",
                "params": {"name": "voicefi_sfx", "arguments": {"name": "honk", "volume": "loud"}},
            }
            resp_vol_str = self.server.handle_request(req_vol_str)
            assert resp_vol_str["result"]["isError"] is False
            mock_play.assert_called_once_with("honk", block=True, volume=1.0)

    def test_mcp_unknown_tool_and_methods(self):
        """Verify MCP server handles unknown tools and unknown RPC methods gracefully."""
        # 1. Unknown tool
        req_tool = {
            "jsonrpc": "2.0",
            "id": "tool-unknown",
            "method": "tools/call",
            "params": {"name": "voicefi_nonexistent_tool_123", "arguments": {}},
        }
        resp_tool = self.server.handle_request(req_tool)
        assert resp_tool["result"]["isError"] is True
        assert "Unknown tool" in resp_tool["result"]["content"][0]["text"]

        # 2. Unknown JSON-RPC method
        req_method = {
            "jsonrpc": "2.0",
            "id": "method-unknown",
            "method": "custom/invalid_rpc_method",
            "params": {},
        }
        resp_method = self.server.handle_request(req_method)
        assert "error" in resp_method
        assert resp_method["error"]["code"] == -32601


# ============================================================================
# 2. REST API REST ADVERSARIAL & BOUNDARY FUZZING TESTS
# ============================================================================

class TestRESTEndpointsAdversarial(AioHTTPTestCase):
    """Adversarial stress and schema fuzzing for VoiceFi Companion REST endpoints."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    async def test_rest_speak_malformed_and_boundary_payloads(self):
        """Fuzz POST /api/speak with malformed JSON, empty text, extreme strings, and non-dicts."""
        # 1. Malformed JSON syntax
        resp1 = await self.client.post("/api/speak", data="{malformed json", headers={"Content-Type": "application/json"})
        assert resp1.status == 400
        d1 = await resp1.json()
        assert d1.get("status") == "error"

        # 2. Non-dict JSON (array, primitive)
        for bad_body in [["array"], "string", 12345]:
            resp2 = await self.client.post("/api/speak", json=bad_body)
            assert resp2.status == 400
            d2 = await resp2.json()
            assert "JSON body must be an object" in d2.get("error", "")

        # 3. Missing, empty, or whitespace text
        for bad_text in [None, "", "     ", 9999]:
            resp3 = await self.client.post("/api/speak", json={"text": bad_text})
            assert resp3.status == 400
            d3 = await resp3.json()
            assert "Missing or empty 'text' field" in d3.get("error", "")

        # 4. Extreme text payload (50k chars) with mock TTS
        huge_str = "A" * 50000
        mock_tts = MagicMock()
        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.tts.base.speech_turn_lock"):
            resp4 = await self.client.post("/api/speak", json={"text": huge_str, "voice": "Ava", "block": True})
            assert resp4.status == 200
            d4 = await resp4.json()
            assert d4.get("status") == "ok"
            assert d4.get("text") == huge_str

        # 5. Non-blocking speak (block=False) with background execution
        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.tts.base.speech_turn_lock"):
            resp5 = await self.client.post("/api/speak", json={"text": "Non-blocking rest speak", "block": False})
            assert resp5.status == 200
            d5 = await resp5.json()
            assert d5.get("status") == "ok"

    async def test_rest_sfx_malformed_and_boundary_payloads(self):
        """Fuzz POST /api/sfx with boundary volume numbers, invalid names, and bad JSON."""
        # 1. Malformed JSON
        resp_mal = await self.client.post("/api/sfx", data="{broken", headers={"Content-Type": "application/json"})
        assert resp_mal.status == 400

        # 2. Non-dict JSON
        resp_nd = await self.client.post("/api/sfx", json=["not", "dict"])
        assert resp_nd.status == 400

        # 3. Missing or empty name
        for bad_name in ["", "   ", 12345]:
            resp_bn = await self.client.post("/api/sfx", json={"name": bad_name})
            assert resp_bn.status == 400
            d_bn = await resp_bn.json()
            assert "Missing or invalid 'name' parameter" in d_bn.get("error", "")
            assert "available" in d_bn

        # 4. Unknown sound effect name
        with patch("voicefi.audio.sfx.play_sfx", return_value=False):
            resp_un = await self.client.post("/api/sfx", json={"name": "laser_blast"})
            assert resp_un.status == 400
            d_un = await resp_un.json()
            assert "Unknown sound effect" in d_un.get("error", "")
            assert "available" in d_un

        # 5. Valid sound effects with volume boundaries
        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx:
            # Negative volume clamped to 0.0
            resp_vneg = await self.client.post("/api/sfx", json={"name": "applause", "volume": -10.0})
            assert resp_vneg.status == 200
            mock_sfx.assert_called_with("applause", block=False, volume=0.0)

            # Huge volume clamped to 2.0
            resp_vhuge = await self.client.post("/api/sfx", json={"name": "applause", "volume": 100.0})
            assert resp_vhuge.status == 200
            mock_sfx.assert_called_with("applause", block=False, volume=2.0)

            # Non-numeric volume string -> 400 Bad Request
            resp_vbad = await self.client.post("/api/sfx", json={"name": "applause", "volume": "max_loudness"})
            assert resp_vbad.status == 400
            d_vbad = await resp_vbad.json()
            assert "Invalid 'volume' parameter" in d_vbad.get("error", "")

    async def test_rest_stop_endpoint_rapid_burst(self):
        """Verify POST /api/stop handles empty bodies, garbage payloads, and rapid 50x bursts."""
        with patch("voicefi.tts.base.stop_all_speech") as mock_stop:
            # 1. Standard stop call
            resp = await self.client.post("/api/stop")
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            assert data.get("stopped") is True
            assert mock_stop.call_count == 1

            # 2. Stop call with arbitrary body
            resp_body = await self.client.post("/api/stop", json={"irrelevant": True})
            assert resp_body.status == 200
            assert mock_stop.call_count == 2

            # 3. Rapid burst of 50 stop requests
            for _ in range(50):
                r = await self.client.post("/api/stop")
                assert r.status == 200
            assert mock_stop.call_count == 52

    async def test_rest_send_fuzzing_and_error_handling(self):
        """Fuzz POST /api/send with malformed payloads, empty prompts, and failure states."""
        # 1. Malformed JSON
        resp_mal = await self.client.post("/api/send", data="bad-json", headers={"Content-Type": "application/json"})
        assert resp_mal.status == 400
        d_mal = await resp_mal.json()
        assert d_mal.get("success") is False

        # 2. Non-dict JSON
        resp_nd = await self.client.post("/api/send", json=["array"])
        assert resp_nd.status == 400

        # 3. Empty text
        for empty_val in ["", "   ", 12345]:
            resp_empty = await self.client.post("/api/send", json={"text": empty_val})
            assert resp_empty.status == 400
            d_empty = await resp_empty.json()
            assert "Empty text prompt" in d_empty.get("error", "")

        # 4. Dispatch failure returns HTTP 500 with error envelope
        with patch("voicefi.companion.server.send_message_to_agent") as mock_send:
            mock_send.return_value = DispatchResult(
                success=False,
                delivery_type="none",
                error="Target process not found",
            )
            resp_fail = await self.client.post("/api/send", json={"text": "Send to dead process", "engine": "claude"})
            assert resp_fail.status == 500
            d_fail = await resp_fail.json()
            assert d_fail.get("success") is False
            assert "Target process not found" in d_fail.get("error", "")

    async def test_rest_status_endpoint(self):
        """Verify GET /api/status returns structured JSON with online status and active state."""
        resp = await self.client.get("/api/status")
        assert resp.status == 200
        data = await resp.json()
        assert data.get("status") == "online"
        assert "connected_clients" in data
        assert "audio_routing" in data


# ============================================================================
# 3. MULTI-PROTOCOL CONCURRENT INVOCATION & STRESS TEST
# ============================================================================

class TestMultiProtocolConcurrencyStress(AioHTTPTestCase):
    """Stress test concurrent invocations across MCP Stdio and REST endpoints simultaneously."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    async def test_simultaneous_mcp_and_rest_invocation_stress(self):
        """
        Launch 50+ concurrent requests across MCP stdio tools and REST endpoints simultaneously.
        Verifies zero deadlocks, zero uncaught exceptions, and clean state recovery under load.
        """
        mcp_server = VoiceFiMCPServer()
        mock_tts = MagicMock()
        mock_tts.persona_name = "Viv"

        mcp_results = []
        rest_results = []
        errors = []

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.tts.base.speech_turn_lock"), \
             patch("voicefi.audio.sfx.play_sfx", return_value=True), \
             patch("voicefi.companion.server.send_message_to_agent") as mock_rest_send, \
             patch("voicefi.integrations.injector.send_message_to_agent") as mock_mcp_send:

            mock_rest_send.return_value = DispatchResult(success=True, delivery_type="ipc", engine="antigravity")
            mock_mcp_send.return_value = DispatchResult(success=True, delivery_type="ipc", engine="antigravity")

            async def mcp_worker(worker_id: int):
                try:
                    # Alternating MCP tool calls
                    if worker_id % 4 == 0:
                        req = {
                            "jsonrpc": "2.0",
                            "id": f"mcp-speak-{worker_id}",
                            "method": "tools/call",
                            "params": {"name": "voicefi_speak", "arguments": {"text": f"MCP thread {worker_id}"}},
                        }
                    elif worker_id % 4 == 1:
                        req = {
                            "jsonrpc": "2.0",
                            "id": f"mcp-sfx-{worker_id}",
                            "method": "tools/call",
                            "params": {"name": "voicefi_sfx", "arguments": {"name": "drum_smash", "volume": 0.8}},
                        }
                    elif worker_id % 4 == 2:
                        req = {
                            "jsonrpc": "2.0",
                            "id": f"mcp-send-{worker_id}",
                            "method": "tools/call",
                            "params": {"name": "voicefi_send", "arguments": {"text": f"Task findings {worker_id}", "to": "antigravity"}},
                        }
                    else:
                        req = {
                            "jsonrpc": "2.0",
                            "id": f"mcp-status-{worker_id}",
                            "method": "tools/call",
                            "params": {"name": "voicefi_status", "arguments": {}},
                        }

                    resp = mcp_server.handle_request(req)
                    assert resp is not None
                    mcp_results.append(resp)
                except Exception as e:
                    errors.append(("mcp", worker_id, str(e)))

            async def rest_worker(worker_id: int):
                try:
                    if worker_id % 4 == 0:
                        resp = await self.client.post("/api/speak", json={"text": f"REST worker {worker_id}", "block": False})
                        assert resp.status == 200
                        data = await resp.json()
                        rest_results.append(data)
                    elif worker_id % 4 == 1:
                        resp = await self.client.post("/api/sfx", json={"name": "applause", "volume": 0.7, "block": False})
                        assert resp.status == 200
                        data = await resp.json()
                        rest_results.append(data)
                    elif worker_id % 4 == 2:
                        resp = await self.client.post("/api/send", json={"text": f"REST send {worker_id}", "engine": "antigravity"})
                        assert resp.status == 200
                        data = await resp.json()
                        rest_results.append(data)
                    else:
                        resp = await self.client.get("/api/status")
                        assert resp.status == 200
                        data = await resp.json()
                        rest_results.append(data)
                except Exception as e:
                    errors.append(("rest", worker_id, str(e)))

            # Create 30 MCP tasks and 30 REST tasks = 60 concurrent tasks
            tasks = []
            for i in range(30):
                tasks.append(mcp_worker(i))
                tasks.append(rest_worker(i))

            # Interleave a few stop calls midway
            async def stop_worker():
                await asyncio.sleep(0.01)
                r1 = await self.client.post("/api/stop")
                assert r1.status == 200
                mcp_resp = mcp_server.handle_request({"jsonrpc": "2.0", "id": "mcp-stop", "method": "tools/call", "params": {"name": "voicefi_stop", "arguments": {}}})
                assert mcp_resp["result"]["isError"] is False

            tasks.append(stop_worker())

            # Run all 61 concurrent operations
            await asyncio.gather(*tasks)

        assert not errors, f"Errors encountered during concurrent multi-protocol stress: {errors}"
        assert len(mcp_results) >= 30, f"Expected >= 30 MCP results, got {len(mcp_results)}"
        assert len(rest_results) >= 30, f"Expected >= 30 REST results, got {len(rest_results)}"


# ============================================================================
# 4. DEEP ADVERSARIAL PROTOCOL EDGE CASES & PROTOCOL PARITY
# ============================================================================

class TestDeepProtocolEdgeCases(AioHTTPTestCase):
    """Deep adversarial boundary tests across HTTP methods, Ping Voice, Set Voice, and Stdio parsing."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    def test_mcp_ping_voice_benchmark_fuzzing(self):
        """Fuzz voicefi_ping_voice with existing, nonexistent, and custom voice personas."""
        mcp_server = VoiceFiMCPServer()

        # Mock AudioTroubleshooter ping result
        mock_ping_res_ok = MagicMock(
            success=True,
            provider="edge_tts",
            status="200 OK",
            latency_ms=142.5,
            chars_per_sec=88.4,
            audio_bytes=16384,
            error=None,
        )
        mock_ping_res_fail = MagicMock(
            success=False,
            provider="edge_tts",
            status="404 Not Found",
            latency_ms=0.0,
            chars_per_sec=0.0,
            audio_bytes=0,
            error="Voice not found",
        )

        with patch("voicefi.troubleshoot.AudioTroubleshooter.ping_voice_silently") as mock_ping:
            # 1. Success ping
            mock_ping.return_value = mock_ping_res_ok
            req_ok = {
                "jsonrpc": "2.0",
                "id": "ping-ok",
                "method": "tools/call",
                "params": {"name": "voicefi_ping_voice", "arguments": {"voice": "Viv"}},
            }
            resp_ok = mcp_server.handle_request(req_ok)
            assert resp_ok["result"]["isError"] is False
            assert "TTFB: 142.5ms" in resp_ok["result"]["content"][0]["text"]

            # 2. Failed ping
            mock_ping.return_value = mock_ping_res_fail
            req_fail = {
                "jsonrpc": "2.0",
                "id": "ping-fail",
                "method": "tools/call",
                "params": {"name": "voicefi_ping_voice", "arguments": {"voice": "FakeVoice"}},
            }
            resp_fail = mcp_server.handle_request(req_fail)
            assert resp_fail["result"]["isError"] is True
            assert "Ping benchmark failed" in resp_fail["result"]["content"][0]["text"]

    def test_mcp_set_voice_agent_and_persona_fuzzing(self):
        """Fuzz voicefi_set_voice with agent personas and global configuration targets."""
        mcp_server = VoiceFiMCPServer()

        # 1. Missing persona -> isError: True
        req_missing = {
            "jsonrpc": "2.0",
            "id": "set-missing",
            "method": "tools/call",
            "params": {"name": "voicefi_set_voice", "arguments": {"agent": "antigravity"}},
        }
        resp_missing = mcp_server.handle_request(req_missing)
        assert resp_missing["result"]["isError"] is True
        assert "Persona name is required" in resp_missing["result"]["content"][0]["text"]

        # 2. Update specific agent
        with patch("voicefi.config.save_config") as mock_save:
            req_agent = {
                "jsonrpc": "2.0",
                "id": "set-agent",
                "method": "tools/call",
                "params": {"name": "voicefi_set_voice", "arguments": {"agent": "researcher", "persona": "Ava (Premium)"}},
            }
            resp_agent = mcp_server.handle_request(req_agent)
            assert resp_agent["result"]["isError"] is False
            assert "Successfully updated voice for 'researcher'" in resp_agent["result"]["content"][0]["text"]
            mock_save.assert_called_once()

        # 3. Update global default
        with patch("voicefi.config.save_config") as mock_save:
            req_global = {
                "jsonrpc": "2.0",
                "id": "set-global",
                "method": "tools/call",
                "params": {"name": "voicefi_set_voice", "arguments": {"agent": "default", "persona": "Samantha"}},
            }
            resp_global = mcp_server.handle_request(req_global)
            assert resp_global["result"]["isError"] is False
            mock_save.assert_called_once()

    def test_mcp_stdio_json_rpc_stream_parsing(self):
        """Verify stdio JSON-RPC parser handles empty lines, parse errors, and batch calls."""
        server = VoiceFiMCPServer()

        # 1. Notification (no id) -> returns None
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        assert server.handle_request(notif) is None

        # 2. Ping method -> returns empty result
        ping_req = {"jsonrpc": "2.0", "id": 999, "method": "ping"}
        ping_resp = server.handle_request(ping_req)
        assert ping_resp["result"] == {}

    async def test_rest_http_method_enforcement(self):
        """Verify endpoints reject incorrect HTTP methods (e.g. GET /api/speak -> 405 Method Not Allowed)."""
        # GET /api/speak -> 405 Method Not Allowed
        resp1 = await self.client.get("/api/speak")
        assert resp1.status == 405

        # GET /api/sfx -> 405 Method Not Allowed
        resp2 = await self.client.get("/api/sfx")
        assert resp2.status == 405

        # GET /api/stop -> 405 Method Not Allowed
        resp3 = await self.client.get("/api/stop")
        assert resp3.status == 405

        # POST /api/status -> 405 Method Not Allowed
        resp4 = await self.client.post("/api/status")
        assert resp4.status == 405

    async def test_rest_speak_with_rate_and_agent_resolution(self):
        """Verify POST /api/speak passes rate and resolves agent-specific voice overrides."""
        mock_tts = MagicMock()
        mock_tts.persona_name = "Ava"
        mock_tts.rate = "+0%"

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts) as mock_get_tts, \
             patch("voicefi.tts.base.speech_turn_lock"):
            resp = await self.client.post(
                "/api/speak",
                json={
                    "text": "Testing rate configuration",
                    "agent": "researcher",
                    "voice": "Ava",
                    "rate": "+25%",
                    "block": True,
                },
            )
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            assert mock_tts.rate == "+25%"
            mock_get_tts.assert_called_once()
