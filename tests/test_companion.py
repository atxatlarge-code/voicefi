"""
Unit and integration tests for the VoiceFi Mobile Companion, PWA, and WebSocket Hub.
"""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from voicefi.config import VoiceFiConfig
from voicefi.companion.qr import (
    get_local_ip,
    get_mdns_hostname,
    get_companion_urls,
    generate_qr_ascii,
    generate_qr_base64_png,
)
from voicefi.companion.server import CompanionServer
from voicefi.cli import cmd_companion


def test_qr_network_utilities():
    """Test local network IP detection, mDNS, and URL generation."""
    ip = get_local_ip()
    assert ip is not None
    assert len(ip.split(".")) == 4

    hostname = get_mdns_hostname()
    assert hostname is not None
    assert len(hostname) > 0

    urls = get_companion_urls(port=5141)
    assert "ip_url" in urls
    assert "mdns_url" in urls
    assert "localhost_url" in urls
    assert urls["localhost_url"] == "http://localhost:5141"


def test_qr_code_rendering():
    """Test ASCII and PNG QR code generator output."""
    test_url = "http://192.168.1.50:5141"

    ascii_qr = generate_qr_ascii(test_url)
    assert ascii_qr is not None
    assert len(ascii_qr) > 20

    png_b64 = generate_qr_base64_png(test_url)
    assert png_b64.startswith("data:image/png;base64,")


class CompanionServerTestCase(AioHTTPTestCase):
    """Integration test suite for CompanionServer async HTTP & WebSocket endpoints."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    async def test_get_index_html(self):
        """Test GET / serves mobile PWA HTML."""
        resp = await self.client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "VoiceFi Companion" in text
        assert "Hands-Free Loop" in text
        assert "convSelect" in text

    async def test_get_manifest(self):
        """Test GET /manifest.json serves PWA manifest."""
        resp = await self.client.get("/manifest.json")
        assert resp.status == 200
        data = await resp.json()
        assert data.get("name") == "VoiceFi Companion"
        assert data.get("display") == "standalone"

    async def test_get_sw(self):
        """Test GET /sw.js serves Service Worker."""
        resp = await self.client.get("/sw.js")
        assert resp.status == 200
        text = await resp.text()
        assert "CACHE_NAME" in text

    async def test_api_status(self):
        """Test GET /api/status returns active agent state."""
        resp = await self.client.get("/api/status")
        assert resp.status == 200
        data = await resp.json()
        assert data.get("status") == "online"
        assert "connected_clients" in data

    async def test_api_conversations(self):
        """Test GET /api/conversations returns list of conversations."""
        resp = await self.client.get("/api/conversations")
        assert resp.status == 200
        data = await resp.json()
        assert "conversations" in data
        assert isinstance(data["conversations"], list)

    async def test_api_switch_and_send(self):
        """Test POST /api/switch and POST /api/send."""
        # 1. Switch conversation
        resp_switch = await self.client.post("/api/switch", json={"conv_id": "test-conv-123"})
        assert resp_switch.status == 200
        data_switch = await resp_switch.json()
        assert data_switch.get("active_id") == "test-conv-123"

        # 2. Send prompt with mocked agent message dispatcher
        from voicefi.integrations.injector import DispatchResult
        mock_res = DispatchResult(success=True, delivery_type="ipc", target_conv_id="test-conv-123", engine="antigravity")
        with patch("voicefi.audio.echo_canceller.is_acoustic_echo", return_value=False), \
             patch("voicefi.companion.server.send_message_to_agent", return_value=mock_res) as mock_send:
            resp_send = await self.client.post("/api/send", json={"conv_id": "test-conv-123", "text": "Run unit tests"})
            assert resp_send.status == 200
            data_send = await resp_send.json()
            assert data_send.get("success") is True
            assert data_send.get("delivered_ipc") is True
            assert data_send.get("pasted_to_foreground") is False
            mock_send.assert_called_once_with(
                conv_id="test-conv-123",
                text="Run unit tests",
                sender_name="ViFi Companion",
                title="Message from ViFi Companion",
                target_engine=None,
                from_conv_id=None,
                from_engine=None,
                include_envelope=False,
                allow_foreground_fallback=False,
            )

    async def test_api_send_failure_response(self):
        """Test POST /api/send returns 500 and delivered_ipc=False when IPC fails."""
        from voicefi.integrations.injector import DispatchResult
        fail_res = DispatchResult(success=False, delivery_type="none", error="agentapi unavailable: connection refused")
        with patch("voicefi.audio.echo_canceller.is_acoustic_echo", return_value=False), \
             patch("voicefi.companion.server.send_message_to_agent", return_value=fail_res):
            resp = await self.client.post("/api/send", json={"conv_id": "test-conv-123", "text": "Run unit tests"})
            assert resp.status == 500
            data = await resp.json()
            assert data.get("success") is False
            assert data.get("delivered_ipc") is False
            assert data.get("pasted_to_foreground") is False
            assert "unavailable" in data.get("error", "")

    async def test_api_artifact_review(self):

        """Test POST /api/conversation/{conv_id}/artifact_review with structured review comments."""
        with patch("voicefi.companion.server.send_message_to_antigravity", return_value=True) as mock_send:
            payload = {
                "filename": "implementation_plan.md",
                "comments": [
                    {
                        "snippet": "Proposed Changes to UI",
                        "comment": "Move the review bar to the bottom and make it sticky."
                    },
                    {
                        "snippet": "port = 8080",
                        "comment": "Change default port to 5141."
                    }
                ],
                "general_feedback": "Looks solid overall.",
                "sender_name": "Mobile Reviewer"
            }
            resp = await self.client.post("/api/conversation/test-conv-123/artifact_review", json=payload)
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("comments_count") == 2
            assert "Review Comments on `implementation_plan.md`" in data.get("message")
            assert "Move the review bar to the bottom" in data.get("message")
            mock_send.assert_called_once()
            called_args = mock_send.call_args.kwargs
            assert called_args["conv_id"] == "test-conv-123"
            assert "implementation_plan.md" in called_args["title"]

    async def test_api_image_feedback(self):
        """Test POST /api/conversation/{conv_id}/image_feedback with annotated image markup."""
        # 1x1 transparent PNG in base64
        sample_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        with patch("voicefi.companion.server.send_message_to_antigravity", return_value=True) as mock_send:
            payload = {
                "original_filename": "mockup_v1.png",
                "annotated_image_base64": sample_b64,
                "feedback_text": "I circled the header: make it bold and add 10px margin.",
                "sender_name": "Visual QA"
            }
            resp = await self.client.post("/api/conversation/test-conv-123/image_feedback", json=payload)
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("original_filename") == "mockup_v1.png"
            assert data.get("filename").startswith("annotated_mockup_v1_")
            assert "Visual Markup & Feedback on `mockup_v1.png`" in data.get("message")
            assert "make it bold" in data.get("message")
            mock_send.assert_called_once()

    async def test_api_qr(self):
        """Test GET /api/qr returns pairing metadata."""
        resp = await self.client.get("/api/qr")
        assert resp.status == 200
        data = await resp.json()
        assert "urls" in data
        assert "qr_data_uri" in data
        assert data["qr_data_uri"].startswith("data:image/png;base64,")

    async def test_api_tunnel_endpoints(self):
        """Test GET /api/tunnel/status and POST /api/tunnel/start."""
        # 1. Test status before start
        resp_status = await self.client.get("/api/tunnel/status")
        assert resp_status.status == 200
        data_status = await resp_status.json()
        assert "active" in data_status

        # 2. Test starting tunnel with mock
        with patch("voicefi.companion.server.get_active_tunnel_url", return_value=None), \
             patch("voicefi.companion.server.start_cloudflared_tunnel", return_value="https://test-quick-tunnel.trycloudflare.com"):
            resp_start = await self.client.post("/api/tunnel/start")
            assert resp_start.status == 200
            data_start = await resp_start.json()
            assert data_start.get("status") == "success"
            assert data_start.get("tunnel_url") == "https://test-quick-tunnel.trycloudflare.com"
            assert "urls" in data_start
            assert data_start["urls"]["tunnel_url"] == "https://test-quick-tunnel.trycloudflare.com"

        # 3. Test QR endpoint reflects active tunnel
        with patch("voicefi.companion.server.get_active_tunnel_url", return_value="https://test-quick-tunnel.trycloudflare.com"):
            resp_qr = await self.client.get("/api/qr")
            assert resp_qr.status == 200
            data_qr = await resp_qr.json()
            assert data_qr.get("active_tunnel_url") == "https://test-quick-tunnel.trycloudflare.com"
            assert data_qr.get("preferred_url") == "https://test-quick-tunnel.trycloudflare.com"

    async def test_websocket_channel(self):
        """Test bidirectional WebSocket handshake and event broadcasting."""
        ws = await self.client.ws_connect("/ws")
        assert len(self.companion_server.active_websockets) == 1

        # 1. Receive initial status message
        msg1 = await ws.receive_json()
        assert msg1.get("type") == "status_update"

        # 2. Test ping / pong
        await ws.send_json({"type": "ping"})
        msg_pong = await ws.receive_json()
        assert msg_pong.get("type") == "pong"

        # 3. Test sending voice command over WebSocket
        with patch("voicefi.companion.server.send_message_to_agent", return_value=True) as mock_send:
            await ws.send_json({
                "type": "user_voice_command",
                "conv_id": "test-conv-456",
                "text": "Check git diff",
            })
            # Receive broadcast confirmation
            msg_conf = await ws.receive_json()
            assert msg_conf.get("type") == "user_command_injected"
            assert msg_conf.get("text") == "Check git diff"
            mock_send.assert_called_once_with(
                conv_id="test-conv-456",
                text="Check git diff",
                sender_name="ViFi Companion",
                title="Message from ViFi Companion",
            )

        # 4. Test server broadcasting agent turn completion
        self.companion_server.broadcast_turn_completion(
            summary="Build completed successfully. Ready to deploy?",
            conv_id="test-conv-456",
            agent_role="antigravity",
        )
        msg_turn = await ws.receive_json()
        assert msg_turn.get("type") == "agent_turn_completed"
        assert "Build completed successfully" in msg_turn.get("summary")
        assert msg_turn.get("conv_id") == "test-conv-456"

        await ws.close()


def test_cli_companion_invocation():
    """Test 'vg companion' CLI command argument handling."""
    args = MagicMock()
    args.port = 5141
    args.host = "0.0.0.0"
    args.no_qr = True
    args.open = False
    args.config = None

    with patch("voicefi.companion.server.run_companion_server") as mock_run:
        cmd_companion(args)
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["port"] == 5141
        assert kwargs["host"] == "0.0.0.0"
        assert kwargs["print_qr"] is False
        assert kwargs["open_browser"] is False
