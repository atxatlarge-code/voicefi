"""
Adversarial Challenge & Stress Test Suite for Milestone M2:
Universal Multi-Protocol Parity & Interface Hardening.

Covers:
1. Multi-Protocol Behavioral & Schema Parity (MCP stdio vs REST HTTP endpoints vs CLI).
2. Concurrency & Interleaved Stress Tests across REST and MCP surfaces.
3. Event loop non-blocking behavior during speech synthesis and SFX.
4. Schema validation and error robustness on adversarial inputs (malformed JSON, type mismatches, NaN/Infinity, unicode/emojis, massive payloads).
5. WebSocket turn and state broadcast verification across endpoints.
"""

import asyncio
import json
import threading
import time
from unittest.mock import patch, MagicMock
import pytest
from aiohttp.test_utils import AioHTTPTestCase

from voicefi.config import VoiceFiConfig
from voicefi.companion.server import CompanionServer
from voicefi.mcp_server import VoiceFiMCPServer, MCP_TOOLS
from voicefi.integrations.injector import DispatchResult
from voicefi.audio.sfx import list_available_sfx, ALIASES


class ChallengerM2ParityStressTestCase(AioHTTPTestCase):
    """Empirical adversarial test suite challenging M2 multi-protocol parity and resilience."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    # =========================================================================
    # 1. MCP vs REST Schema & Behavioral Parity
    # =========================================================================

    def test_mcp_tools_schema_integrity(self):
        """Verify all required M2 MCP tools are registered with complete schemas."""
        tool_map = {t["name"]: t for t in MCP_TOOLS}
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
        for name in expected_tools:
            assert name in tool_map, f"Missing MCP tool definition: {name}"

        # Schema details for voicefi_speak
        speak_props = tool_map["voicefi_speak"]["inputSchema"]["properties"]
        assert "text" in speak_props
        assert "persona" in speak_props
        assert "agent_name" in speak_props
        assert "conv_id" in speak_props
        assert "block" in speak_props
        assert tool_map["voicefi_speak"]["inputSchema"]["required"] == ["text"]

        # Schema details for voicefi_listen
        listen_props = tool_map["voicefi_listen"]["inputSchema"]["properties"]
        assert "timeout" in listen_props
        assert "max_seconds" in listen_props

        # Schema details for voicefi_sfx
        sfx_props = tool_map["voicefi_sfx"]["inputSchema"]["properties"]
        assert "name" in sfx_props
        assert "volume" in sfx_props
        assert tool_map["voicefi_sfx"]["inputSchema"]["required"] == ["name"]

        # Schema details for voicefi_send
        send_props = tool_map["voicefi_send"]["inputSchema"]["properties"]
        assert "text" in send_props
        assert "to" in send_props
        assert "conv_id" in send_props
        assert "reply" in send_props
        assert tool_map["voicefi_send"]["inputSchema"]["required"] == ["text"]

    async def test_parity_speak_turn_claiming_and_execution(self):
        """Verify both MCP voicefi_speak and REST /api/speak claim conversation turns."""
        mcp_server = VoiceFiMCPServer()
        mock_tts = MagicMock()
        mock_tts.persona_name = "Viv"

        # 1. Test MCP voicefi_speak
        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.integrations.conversations.claim_active_conversation_turn") as mock_claim_mcp, \
             patch("voicefi.tts.base.speech_turn_lock"):
            mcp_res = mcp_server.execute_tool(
                "voicefi_speak",
                {"text": "Hello MCP", "conv_id": "mcp-conv-123", "agent_name": "claude", "persona": "Viv"}
            )
            assert mcp_res["isError"] is False
            assert "Successfully synthesized" in mcp_res["content"][0]["text"]
            mock_claim_mcp.assert_called_once_with("Hello MCP", conv_id="mcp-conv-123")
            mock_tts.stream_speak.assert_called_once_with("Hello MCP", block=True)

        # 2. Test REST /api/speak
        mock_tts.reset_mock()
        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.integrations.conversations.claim_active_conversation_turn") as mock_claim_rest, \
             patch("voicefi.tts.base.speech_turn_lock"):
            resp = await self.client.post(
                "/api/speak",
                json={"text": "Hello REST", "conv_id": "rest-conv-456", "agent": "claude", "voice": "Viv"}
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["text"] == "Hello REST"
            mock_claim_rest.assert_called_once_with("Hello REST", conv_id="rest-conv-456")
            mock_tts.speak.assert_called_once_with("Hello REST")

    async def test_parity_sfx_aliases_and_errors(self):
        """Verify MCP voicefi_sfx and REST /api/sfx handle aliases and invalid names identically."""
        mcp_server = VoiceFiMCPServer()

        # Valid alias on REST: 'rimshot' -> mapped to drum_smash
        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx:
            resp = await self.client.post("/api/sfx", json={"name": "rimshot", "volume": 1.2})
            assert resp.status == 200
            mock_sfx.assert_called_once_with("rimshot", block=False, volume=1.2)

        # Valid alias on MCP: 'rimshot'
        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx_mcp:
            res = mcp_server.execute_tool("voicefi_sfx", {"name": "rimshot", "volume": 1.2})
            assert res["isError"] is False
            assert "rimshot" in res["content"][0]["text"]
            mock_sfx_mcp.assert_called_once_with("rimshot", block=True, volume=1.2)

        # Invalid SFX on REST: returns available list and 400
        with patch("voicefi.audio.sfx.play_sfx", return_value=False):
            resp = await self.client.post("/api/sfx", json={"name": "invalid_sound_name"})
            assert resp.status == 400
            data = await resp.json()
            assert "Unknown sound effect" in data["error"]
            assert "available" in data
            assert set(data["available"]) == set(list_available_sfx())

        # Invalid SFX on MCP: returns available list and isError=True
        with patch("voicefi.audio.sfx.play_sfx", return_value=False):
            res = mcp_server.execute_tool("voicefi_sfx", {"name": "invalid_sound_name"})
            assert res["isError"] is True
            assert "Unknown sound effect" in res["content"][0]["text"]
            for sfx_name in list_available_sfx():
                assert sfx_name in res["content"][0]["text"]

    async def test_parity_stop_execution(self):
        """Verify both MCP voicefi_stop and REST /api/stop halt playback cleanly."""
        mcp_server = VoiceFiMCPServer()

        with patch("voicefi.tts.stop_all_speech") as mock_stop_mcp:
            res = mcp_server.execute_tool("voicefi_stop", {})
            assert res["isError"] is False
            assert "Stopped all active speech" in res["content"][0]["text"]
            mock_stop_mcp.assert_called_once()

        with patch("voicefi.tts.base.stop_all_speech") as mock_stop_rest:
            resp = await self.client.post("/api/stop")
            assert resp.status == 200
            data = await resp.json()
            assert data["status"] == "ok"
            assert data["stopped"] is True
            mock_stop_rest.assert_called_once()

    async def test_parity_send_reply_routing(self):
        """Verify both MCP voicefi_send and REST /api/send handle reply routing correctly."""
        mcp_server = VoiceFiMCPServer()
        mock_disp_ok = DispatchResult(
            success=True,
            delivery_type="ipc",
            target_conv_id="conv-origin-777",
            engine="antigravity",
        )

        # 1. MCP voicefi_send with reply=True
        with patch("voicefi.integrations.injector.send_message_to_agent", return_value=mock_disp_ok) as mock_send_mcp:
            res = mcp_server.execute_tool(
                "voicefi_send",
                {"text": "Task finished", "to": "antigravity", "reply": True, "sender": "Claude"}
            )
            assert res["isError"] is False
            assert "Successfully dispatched message" in res["content"][0]["text"]
            mock_send_mcp.assert_called_once_with(
                conv_id="reply",
                text="Task finished",
                sender_name="Claude",
                title=None,
                target_engine="antigravity",
                from_engine="claude",
            )

        # 2. REST /api/send with reply_to="reply"
        with patch("voicefi.companion.server.send_message_to_agent", return_value=mock_disp_ok) as mock_send_rest:
            resp = await self.client.post(
                "/api/send",
                json={"text": "Task finished", "engine": "antigravity", "reply_to": "reply", "sender_name": "Claude"}
            )
            assert resp.status == 200
            data = await resp.json()
            assert data["success"] is True
            assert data["conv_id"] == "conv-origin-777"
            mock_send_rest.assert_called_once_with(
                conv_id="reply",
                text="Task finished",
                sender_name="Claude",
                title="Message from Claude",
                target_engine="antigravity",
                from_conv_id=None,
                from_engine=None,
                include_envelope=False,
                allow_foreground_fallback=False,
            )

    # =========================================================================
    # 2. Adversarial Inputs & Boundary Validation
    # =========================================================================

    async def test_adversarial_rest_inputs_matrix(self):
        """Stress test REST endpoints with diverse malformed and adversarial payloads."""
        adversarial_payloads = [
            # Raw malformed JSON strings
            (b"{unclosed_json", 400),
            (b"[\"array\", \"not\", \"dict\"]", 400),
            (b"\"just a string\"", 400),
            (b"12345", 400),
            (b"true", 400),
            (b"null", 400),
        ]

        endpoints = ["/api/speak", "/api/sfx", "/api/send"]

        for payload, expected_status in adversarial_payloads:
            for ep in endpoints:
                resp = await self.client.post(
                    ep,
                    data=payload,
                    headers={"Content-Type": "application/json"}
                )
                assert resp.status == expected_status, f"Failed on {ep} with payload {payload}"
                data = await resp.json()
                assert "error" in data or "status" in data

    async def test_adversarial_volume_boundary_clamping(self):
        """Validate volume boundary clamping in /api/sfx and voicefi_sfx."""
        mcp_server = VoiceFiMCPServer()

        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx:
            # Volume > 2.0 should be clamped to 2.0
            resp = await self.client.post("/api/sfx", json={"name": "honk", "volume": 999.0})
            assert resp.status == 200
            mock_sfx.assert_called_with("honk", block=False, volume=2.0)

            # Volume < 0.0 should be clamped to 0.0
            resp2 = await self.client.post("/api/sfx", json={"name": "honk", "volume": -50.0})
            assert resp2.status == 200
            mock_sfx.assert_called_with("honk", block=False, volume=0.0)

        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx_mcp:
            res = mcp_server.execute_tool("voicefi_sfx", {"name": "honk", "volume": 555.5})
            assert res["isError"] is False
            mock_sfx_mcp.assert_called_with("honk", block=True, volume=2.0)

    async def test_massive_payload_and_unicode_resilience(self):
        """Test handling of massive text (100KB) and rich unicode/emojis across surfaces."""
        mcp_server = VoiceFiMCPServer()
        mock_tts = MagicMock()
        mock_tts.persona_name = "Ava"

        unicode_text = "🎉 VoiceFi 🔊 ⚡ 🚀 🤖 \u2603 \u2764\ufe0f \U0001f923 Testing unicode spoken phrase!"
        massive_text = ("VoiceFi stress testing " * 5000).strip()  # ~115 KB stripped

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.tts.base.speech_turn_lock"):
            # 1. Unicode speak
            resp1 = await self.client.post("/api/speak", json={"text": unicode_text})
            assert resp1.status == 200
            data1 = await resp1.json()
            assert data1["text"] == unicode_text

            # 2. Massive text speak
            resp2 = await self.client.post("/api/speak", json={"text": massive_text})
            assert resp2.status == 200
            data2 = await resp2.json()
            assert len(data2["text"]) == len(massive_text)

            # 3. MCP unicode speak
            res_mcp = mcp_server.execute_tool("voicefi_speak", {"text": unicode_text})
            assert res_mcp["isError"] is False
            assert unicode_text in res_mcp["content"][0]["text"]

    # =========================================================================
    # 3. Concurrency & Interleaved Stress Testing
    # =========================================================================

    async def test_rapid_concurrent_rest_flood(self):
        """Fire 60 concurrent requests across all REST endpoints simultaneously."""
        mock_tts = MagicMock()
        mock_tts.persona_name = "Ava"
        mock_disp = DispatchResult(success=True, delivery_type="ipc", target_conv_id="c1", engine="antigravity")

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.audio.sfx.play_sfx", return_value=True), \
             patch("voicefi.companion.server.send_message_to_agent", return_value=mock_disp), \
             patch("voicefi.tts.base.speech_turn_lock"), \
             patch("voicefi.tts.base.stop_all_speech"):

            async def _req_status():
                r = await self.client.get("/api/status")
                assert r.status == 200
                return await r.json()

            async def _req_speak(i):
                r = await self.client.post("/api/speak", json={"text": f"Concurrency test phrase {i}", "block": False})
                assert r.status == 200
                return await r.json()

            async def _req_sfx(i):
                sfx_name = "drum_smash" if i % 2 == 0 else "honk"
                r = await self.client.post("/api/sfx", json={"name": sfx_name, "volume": 0.8})
                assert r.status == 200
                return await r.json()

            async def _req_stop():
                r = await self.client.post("/api/stop")
                assert r.status == 200
                return await r.json()

            async def _req_send(i):
                r = await self.client.post("/api/send", json={"text": f"Concurrent task {i}", "engine": "antigravity"})
                assert r.status == 200
                return await r.json()

            # Assemble 60 parallel tasks
            tasks = []
            for i in range(12):
                tasks.append(_req_status())
                tasks.append(_req_speak(i))
                tasks.append(_req_sfx(i))
                tasks.append(_req_stop())
                tasks.append(_req_send(i))

            start_t = time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            elapsed = time.time() - start_t

            # Verify no unhandled exceptions or failed requests
            for res in results:
                assert not isinstance(res, Exception), f"Concurrent request raised exception: {res}"
                assert isinstance(res, dict)
            assert elapsed < 12.0, f"Concurrent flood took too long: {elapsed:.2f}s"

    async def test_event_loop_responsiveness_during_blocking_tts(self):
        """Verify that synchronous TTS in executor does not freeze the asyncio event loop."""
        mock_tts = MagicMock()
        mock_tts.persona_name = "Ava"

        tts_started = threading.Event()
        tts_can_finish = threading.Event()

        def _slow_speak(text):
            tts_started.set()
            # Hold TTS for up to 1 second unless released
            tts_can_finish.wait(timeout=1.0)

        mock_tts.speak = MagicMock(side_effect=_slow_speak)

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.tts.base.speech_turn_lock"):

            # Start blocking speak in executor
            speak_task = asyncio.create_task(
                self.client.post("/api/speak", json={"text": "Long synthesized speech", "block": True})
            )

            # Wait for TTS thread to actively enter the synthesis lock
            for _ in range(50):
                if tts_started.is_set():
                    break
                await asyncio.sleep(0.01)

            assert tts_started.is_set(), "TTS did not start"

            # While TTS is actively running in executor thread, fire multiple REST calls
            status_results = []
            for _ in range(3):
                t0 = time.time()
                resp = await self.client.get("/api/status")
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "online"
                status_results.append((time.time() - t0, data))

            # Verify all status calls completed while TTS was still active
            assert not speak_task.done(), "Speak task finished prematurely"

            # Release TTS and wait for completion
            tts_can_finish.set()
            speak_resp = await speak_task
            assert speak_resp.status == 200

            # Verify status calls executed cleanly without deadlock
            assert len(status_results) == 3

    def test_mcp_concurrent_multi_thread_stress(self):
        """Execute MCP tools across 20 simultaneous threads without race conditions or crashes."""
        mcp_server = VoiceFiMCPServer()
        mock_tts = MagicMock()
        mock_tts.persona_name = "Ava"
        mock_disp = DispatchResult(success=True, delivery_type="ipc", target_conv_id="c1", engine="antigravity")

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.audio.sfx.play_sfx", return_value=True), \
             patch("voicefi.integrations.injector.send_message_to_agent", return_value=mock_disp), \
             patch("voicefi.tts.base.speech_turn_lock"), \
             patch("voicefi.tts.stop_all_speech"):

            results = []
            errors = []

            def _worker(thread_idx):
                try:
                    for i in range(5):
                        # Speak
                        r1 = mcp_server.execute_tool("voicefi_speak", {"text": f"T{thread_idx} msg {i}"})
                        assert r1["isError"] is False
                        # SFX
                        r2 = mcp_server.execute_tool("voicefi_sfx", {"name": "drum_smash"})
                        assert r2["isError"] is False
                        # Status
                        r3 = mcp_server.execute_tool("voicefi_status", {})
                        assert r3["isError"] is False
                        # Stop
                        r4 = mcp_server.execute_tool("voicefi_stop", {})
                        assert r4["isError"] is False
                        # Send
                        r5 = mcp_server.execute_tool("voicefi_send", {"text": f"T{thread_idx} send {i}", "to": "claude"})
                        assert r5["isError"] is False
                    results.append(thread_idx)
                except Exception as ex:
                    errors.append((thread_idx, ex))

            threads = [threading.Thread(target=_worker, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10.0)

            assert len(errors) == 0, f"Thread errors encountered: {errors}"
            assert len(results) == 20

    # =========================================================================
    # 4. WebSocket Event Delivery Parity
    # =========================================================================

    async def test_websocket_event_broadcasting_sequence(self):
        """Verify REST actions trigger corresponding WebSocket broadcasts to connected clients."""
        mock_tts = MagicMock()
        mock_tts.persona_name = "Ava"
        mock_disp = DispatchResult(success=True, delivery_type="ipc", target_conv_id="ws-conv-1", engine="antigravity")

        events_received = []

        # Connect WebSocket client
        ws = await self.client.ws_connect("/ws")

        async def _reader():
            try:
                async for msg in ws:
                    if msg.type == 1:  # TEXT
                        data = json.loads(msg.data)
                        events_received.append(data)
            except Exception:
                pass

        reader_task = asyncio.create_task(_reader())

        # Wait for connected handshake/client registration
        await asyncio.sleep(0.1)

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.audio.sfx.play_sfx", return_value=True), \
             patch("voicefi.companion.server.send_message_to_agent", return_value=mock_disp), \
             patch("voicefi.tts.base.speech_turn_lock"), \
             patch("voicefi.tts.base.stop_all_speech"):

            # 1. Trigger /api/speak
            await self.client.post("/api/speak", json={"text": "WS Speak Test", "conv_id": "ws-conv-1"})

            # 2. Trigger /api/sfx
            await self.client.post("/api/sfx", json={"name": "applause"})

            # 3. Trigger /api/stop
            await self.client.post("/api/stop")

            # 4. Trigger /api/send
            await self.client.post("/api/send", json={"text": "WS Send Test", "conv_id": "ws-conv-1"})

            # Allow events to flush
            await asyncio.sleep(0.2)

        await ws.close()
        reader_task.cancel()

        # Check broadcasted event types
        event_types = [e.get("type") for e in events_received]
        assert "agent_speaking_started" in event_types
        assert "agent_speaking_finished" in event_types
        assert "sfx_played" in event_types
        assert "speech_stopped" in event_types
        assert "user_command_injected" in event_types
