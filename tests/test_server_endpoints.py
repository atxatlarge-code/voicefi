"""
Comprehensive integration tests for VoiceFi Companion HTTP REST API endpoints.
Tests /api/speak, /api/sfx, /api/stop, /api/send, /api/status, parameter validation,
and error handling for malformed JSON or invalid types.
"""

import asyncio
import json
from unittest.mock import patch, MagicMock
import pytest
from aiohttp.test_utils import AioHTTPTestCase

from voicefi.config import VoiceFiConfig
from voicefi.companion.server import CompanionServer
from voicefi.integrations.injector import DispatchResult


class ServerEndpointsTestCase(AioHTTPTestCase):
    """Integration test suite for CompanionServer REST endpoints."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    # --- POST /api/speak Tests ---

    async def test_api_speak_success(self):
        """Test POST /api/speak with standard parameters."""
        mock_tts = MagicMock()
        mock_tts.persona_name = "Viv"

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.tts.base.speech_turn_lock") as mock_lock:
            resp = await self.client.post(
                "/api/speak",
                json={"text": "Synthesize this phrase", "voice": "Viv", "rate": "+10%"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            assert data.get("text") == "Synthesize this phrase"
            mock_tts.speak.assert_called_once_with("Synthesize this phrase")
            mock_lock.assert_called_once()

    async def test_api_speak_with_conv_id(self):
        """Test POST /api/speak claims conversation turn when conv_id is provided."""
        mock_tts = MagicMock()
        mock_tts.persona_name = "Ava"

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.integrations.conversations.claim_active_conversation_turn") as mock_claim, \
             patch("voicefi.tts.base.speech_turn_lock"):
            resp = await self.client.post(
                "/api/speak",
                json={"text": "Speaking to conversation", "conv_id": "test-conv-999"},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            mock_claim.assert_called_once_with("Speaking to conversation", conv_id="test-conv-999")

    async def test_api_speak_non_blocking(self):
        """Test POST /api/speak with block=False returns immediately."""
        mock_tts = MagicMock()

        with patch("voicefi.tts.get_tts_engine", return_value=mock_tts), \
             patch("voicefi.tts.base.speech_turn_lock"):
            resp = await self.client.post(
                "/api/speak",
                json={"text": "Async non-blocking speech", "block": False},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            assert data.get("text") == "Async non-blocking speech"

    async def test_api_speak_missing_or_empty_text(self):
        """Test POST /api/speak returns 400 when text is empty or missing."""
        # 1. Missing text field
        resp1 = await self.client.post("/api/speak", json={"voice": "Viv"})
        assert resp1.status == 400
        data1 = await resp1.json()
        assert "Missing or empty 'text' field" in data1.get("error", "")

        # 2. Empty string text
        resp2 = await self.client.post("/api/speak", json={"text": "   "})
        assert resp2.status == 400
        data2 = await resp2.json()
        assert "Missing or empty 'text' field" in data2.get("error", "")

        # 3. Non-string text
        resp3 = await self.client.post("/api/speak", json={"text": 12345})
        assert resp3.status == 400
        data3 = await resp3.json()
        assert "Missing or empty 'text' field" in data3.get("error", "")

    async def test_api_speak_malformed_json(self):
        """Test POST /api/speak returns 400 on malformed JSON payload."""
        resp = await self.client.post(
            "/api/speak",
            data="not-valid-json{",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "Invalid JSON payload" in data.get("error", "")

    async def test_api_speak_non_dict_json(self):
        """Test POST /api/speak returns 400 when JSON body is a list instead of dict."""
        resp = await self.client.post(
            "/api/speak",
            json=["not", "a", "dict"],
        )
        assert resp.status == 400
        data = await resp.json()
        assert "JSON body must be an object" in data.get("error", "")

    # --- POST /api/sfx Tests ---

    async def test_api_sfx_success_defaults(self):
        """Test POST /api/sfx with default parameters."""
        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx:
            resp = await self.client.post("/api/sfx", json={"name": "drum_smash"})
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            assert data.get("sfx") == "drum_smash"
            mock_sfx.assert_called_once_with("drum_smash", block=False, volume=0.8)

    async def test_api_sfx_custom_params(self):
        """Test POST /api/sfx with custom volume and block=True."""
        with patch("voicefi.audio.sfx.play_sfx", return_value=True) as mock_sfx:
            resp = await self.client.post(
                "/api/sfx",
                json={"name": "applause", "volume": 0.5, "block": True},
            )
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            assert data.get("sfx") == "applause"
            mock_sfx.assert_called_once_with("applause", block=True, volume=0.5)

    async def test_api_sfx_unknown_name(self):
        """Test POST /api/sfx returns 400 when sound effect name is unknown."""
        with patch("voicefi.audio.sfx.play_sfx", return_value=False):
            resp = await self.client.post("/api/sfx", json={"name": "unknown_sfx"})
            assert resp.status == 400
            data = await resp.json()
            assert "Unknown sound effect" in data.get("error", "")
            assert "available" in data

    async def test_api_sfx_missing_or_invalid_name(self):
        """Test POST /api/sfx returns 400 when name is missing or non-string."""
        # 1. Missing name
        resp1 = await self.client.post("/api/sfx", json={"volume": 0.9})
        assert resp1.status == 200  # Default is "drum_smash"

        # 2. Empty name
        resp2 = await self.client.post("/api/sfx", json={"name": ""})
        assert resp2.status == 400
        data2 = await resp2.json()
        assert "Missing or invalid 'name' parameter" in data2.get("error", "")

        # 3. Non-string name
        resp3 = await self.client.post("/api/sfx", json={"name": 999})
        assert resp3.status == 400
        data3 = await resp3.json()
        assert "Missing or invalid 'name' parameter" in data3.get("error", "")

    async def test_api_sfx_invalid_volume(self):
        """Test POST /api/sfx returns 400 when volume cannot be parsed as a float."""
        resp = await self.client.post("/api/sfx", json={"name": "honk", "volume": "max_loud"})
        assert resp.status == 400
        data = await resp.json()
        assert "Invalid 'volume' parameter" in data.get("error", "")

    async def test_api_sfx_malformed_json(self):
        """Test POST /api/sfx returns 400 on malformed JSON payload."""
        resp = await self.client.post(
            "/api/sfx",
            data="{malformed_json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "Invalid JSON payload" in data.get("error", "")

    # --- POST /api/stop Tests ---

    async def test_api_stop_success(self):
        """Test POST /api/stop invokes stop_all_speech and returns status ok."""
        mock_rec = MagicMock()
        self.companion_server._active_mac_recorder = mock_rec

        with patch("voicefi.tts.base.stop_all_speech") as mock_stop:
            resp = await self.client.post("/api/stop")
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            assert data.get("stopped") is True
            mock_stop.assert_called_once()
            mock_rec.stop.assert_called_once()

    # --- POST /api/send Tests ---

    async def test_api_send_success(self):
        """Test POST /api/send successfully dispatches via IPC."""
        mock_res = DispatchResult(
            success=True,
            delivery_type="ipc",
            target_conv_id="test-conv-001",
            engine="antigravity",
        )
        with patch("voicefi.audio.echo_canceller.is_acoustic_echo", return_value=False), \
             patch("voicefi.companion.server.send_message_to_agent", return_value=mock_res) as mock_send:
            resp = await self.client.post(
                "/api/send",
                json={
                    "conv_id": "test-conv-001",
                    "text": "Perform code review",
                    "sender_name": "Test Runner",
                },
            )
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("delivered") is True
            assert data.get("delivered_ipc") is True
            mock_send.assert_called_once()

    async def test_api_send_failure(self):
        """Test POST /api/send returns 500 when dispatch fails."""
        mock_res = DispatchResult(
            success=False,
            delivery_type="none",
            error="Connection refused: agentapi not running",
        )
        with patch("voicefi.audio.echo_canceller.is_acoustic_echo", return_value=False), \
             patch("voicefi.companion.server.send_message_to_agent", return_value=mock_res):
            resp = await self.client.post(
                "/api/send",
                json={"conv_id": "test-conv-001", "text": "Will fail"},
            )
            assert resp.status == 500
            data = await resp.json()
            assert data.get("success") is False
            assert data.get("delivered") is False
            assert "agentapi not running" in data.get("error", "")

    async def test_api_send_empty_text(self):
        """Test POST /api/send returns 400 when text is empty."""
        resp = await self.client.post("/api/send", json={"text": "   "})
        assert resp.status == 400
        data = await resp.json()
        assert "Empty text prompt" in data.get("error", "")

    async def test_api_send_malformed_json(self):
        """Test POST /api/send returns 400 on malformed JSON body."""
        resp = await self.client.post(
            "/api/send",
            data="{bad_json:",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "Invalid JSON payload" in data.get("error", "")

    # --- GET /api/status Tests ---

    async def test_api_status_success(self):
        """Test GET /api/status returns full server state."""
        resp = await self.client.get("/api/status")
        assert resp.status == 200
        data = await resp.json()
        assert data.get("status") == "online"
        assert "connected_clients" in data
        assert "audio_routing" in data
        assert "ambient_active" in data
        assert "memo_active" in data
