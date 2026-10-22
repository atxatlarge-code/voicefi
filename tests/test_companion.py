"""
Unit and integration tests for the VoiceFi Mobile Companion, PWA, and WebSocket Hub.
"""

import asyncio
import json
from pathlib import Path
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
        """Test GET / serves mobile PWA HTML and defaults strictly to voice tab."""
        resp = await self.client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "VoiceFi Companion" in text
        assert "Hands-Free Loop" in text
        assert "convSelect" in text
        # Verify voice stage is default active view and chat is hidden initially
        assert '<section id="viewVoice"' in text
        assert '<section id="viewChat" class="hidden' in text
        # Verify switchView('voice') is called on initialization
        assert "switchView('voice')" in text
        # Verify active view is persisted and does not jump to chat on command submit
        assert "voicefi_companion_view" in text
        assert "if (currentView !== 'chat') {\n          switchView('chat');" not in text

    async def test_locked_conversation_selection(self):
        """Test companion PWA preserves locked conversation and does not jump on activity."""
        resp = await self.client.get("/")
        assert resp.status == 200
        text = await resp.text()

        # Verify activeConvId is initialized from localStorage
        assert 'localStorage.getItem("voicefi_active_conv_id") || "";' in text

        # Verify preferredId remains locked to activeConvId or storedId
        assert "let preferredId = activeConvId || storedId;" in text

        # Verify localStorage is not wiped when stored ID is outside top conversations
        assert 'localStorage.removeItem("voicefi_active_conv_id")' not in text

    async def test_get_rc_routes(self):
        """Test GET /rc and /rc/ serve companion PWA HTML."""
        resp1 = await self.client.get("/rc")
        assert resp1.status == 200
        text1 = await resp1.text()
        assert "VoiceFi Companion" in text1

        resp2 = await self.client.get("/rc/")
        assert resp2.status == 200
        text2 = await resp2.text()
        assert "VoiceFi Companion" in text2

    async def test_get_pair_route(self):
        """Test GET /pair serves pairing & editable downloads companion hub."""
        resp = await self.client.get("/pair")
        assert resp.status == 200
        text = await resp.text()
        assert "VoiceFi" in text
        assert "Mobile Pairing" in text
        assert "Companion Downloads" in text
        assert "dropZone" in text
        assert "editorModal" in text
        assert "mediaModal" in text

    async def test_get_spicewood_sheet_api(self):
        """Test GET /api/sheet/spicewood returns Spicewood lead sheet metadata and markdown."""
        downloads_dir = Path(__file__).resolve().parents[1] / "src" / "voicefi" / "companion" / "static" / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        sheet_path = downloads_dir / "spicewood_texas_lead_sheet.md"
        created_sheet = False
        if not sheet_path.is_file():
            sheet_path.write_text("# SPICEWOOD, TEXAS\nBPM: 85\nProducer: Shinra B\nLyrics and cues...")
            created_sheet = True

        try:
            resp = await self.client.get("/api/sheet/spicewood")
            assert resp.status == 200
            data = await resp.json()
            assert data.get("title") == "Spicewood, Texas"
            assert data.get("bpm") == 85
            assert "SPICEWOOD, TEXAS" in data.get("content")
            assert "Shinra B" in data.get("content")
        finally:
            if created_sheet and sheet_path.is_file():
                sheet_path.unlink(missing_ok=True)

    async def test_get_spicewood_downloads(self):
        """Test downloading Spicewood lead sheet and audio beat."""
        downloads_dir = Path(__file__).resolve().parents[1] / "src" / "voicefi" / "companion" / "static" / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        sheet_path = downloads_dir / "spicewood_texas_lead_sheet.md"
        created_sheet = False
        if not sheet_path.is_file():
            sheet_path.write_text("# SPICEWOOD, TEXAS\nBPM: 85\nProducer: Shinra B\nLyrics and cues...")
            created_sheet = True

        beat_path = downloads_dir / "spicewood_texas_beat_85bpm.mp3"
        created_beat = False
        if not beat_path.is_file():
            with open(beat_path, "wb") as f:
                f.seek(1024 * 1024 + 100)
                f.write(b"\0")
            created_beat = True

        try:
            resp_md = await self.client.get("/downloads/spicewood_texas_lead_sheet.md")
            assert resp_md.status == 200
            text = await resp_md.text()
            assert "SPICEWOOD, TEXAS" in text

            resp_mp3 = await self.client.get("/downloads/spicewood_texas_beat_85bpm.mp3")
            assert resp_mp3.status in (200, 206)
            assert resp_mp3.content_type == "audio/mpeg"
            assert resp_mp3.content_length > 1000000
        finally:
            if created_sheet and sheet_path.is_file():
                sheet_path.unlink(missing_ok=True)
            if created_beat and beat_path.is_file():
                beat_path.unlink(missing_ok=True)

    async def test_api_downloads_list_and_act1_file(self):
        """Test GET /api/downloads returns complete file catalog including spicewood_act1_picture_lock.mp4."""
        downloads_dir = Path(__file__).resolve().parents[1] / "src" / "voicefi" / "companion" / "static" / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        sheet_path = downloads_dir / "spicewood_texas_lead_sheet.md"
        created_sheet = False
        if not sheet_path.is_file():
            sheet_path.write_text("# SPICEWOOD, TEXAS\nBPM: 85\nProducer: Shinra B\nLyrics and cues...")
            created_sheet = True

        act1_path = downloads_dir / "spicewood_act1_picture_lock.mp4"
        created_dummy = False
        if not act1_path.is_file():
            act1_path.parent.mkdir(parents=True, exist_ok=True)
            with open(act1_path, "wb") as f:
                f.seek(11 * 1024 * 1024)
                f.write(b"\0")
            created_dummy = True

        try:
            resp = await self.client.get("/api/downloads")
            assert resp.status == 200
            data = await resp.json()
            assert data.get("status") == "ok"
            assert data.get("total_count") > 0
            filenames = [f["name"] for f in data.get("files", [])]
            assert "spicewood_texas_lead_sheet.md" in filenames
            assert "spicewood_act1_picture_lock.mp4" in filenames

            # Verify classifications
            for f in data.get("files", []):
                if f["name"] == "spicewood_texas_lead_sheet.md":
                    assert f["editable"] is True
                    assert f["category"] == "document"
                if f["name"] == "spicewood_act1_picture_lock.mp4":
                    assert f["playable"] is True
                    assert f["category"] == "video"
                    assert f["size"] > 10 * 1024 * 1024
        finally:
            if created_sheet and sheet_path.is_file():
                try:
                    sheet_path.unlink()
                except Exception:
                    pass
            if created_dummy and act1_path.is_file():
                try:
                    act1_path.unlink()
                except Exception:
                    pass

    async def test_api_downloads_crud_lifecycle(self):
        """Test file upload, read content, edit/save content, rename, and delete lifecycle."""
        test_filename = "test_companion_sheet.md"
        init_content = "# Test Companion Sheet\nInitial test line."

        # 1. Upload new file via JSON
        upload_resp = await self.client.post(
            "/api/downloads/upload",
            json={"filename": test_filename, "content": init_content}
        )
        assert upload_resp.status == 200
        upload_data = await upload_resp.json()
        assert upload_data.get("status") == "ok"
        assert len(upload_data.get("uploaded", [])) == 1

        # 2. Read content via GET /api/downloads/{filename}/content
        get_resp = await self.client.get(f"/api/downloads/{test_filename}/content")
        assert get_resp.status == 200
        get_data = await get_resp.json()
        assert get_data.get("content") == init_content
        assert get_data.get("info")["editable"] is True

        # 3. Update/Save content via PUT /api/downloads/{filename}
        updated_content = "# Test Companion Sheet\nUpdated content with edits."
        put_resp = await self.client.put(
            f"/api/downloads/{test_filename}",
            json={"content": updated_content}
        )
        assert put_resp.status == 200
        put_data = await put_resp.json()
        assert put_data.get("status") == "ok"

        # Verify saved content
        verify_resp = await self.client.get(f"/api/downloads/{test_filename}/content")
        assert verify_resp.status == 200
        verify_data = await verify_resp.json()
        assert verify_data.get("content") == updated_content

        # 4. Rename file
        renamed_filename = "test_companion_sheet_renamed.md"
        rename_resp = await self.client.post(
            "/api/downloads/rename",
            json={"old_name": test_filename, "new_name": renamed_filename}
        )
        assert rename_resp.status == 200
        rename_data = await rename_resp.json()
        assert rename_data.get("status") == "ok"
        assert rename_data["file"]["name"] == renamed_filename

        # 5. Delete file
        del_resp = await self.client.delete(f"/api/downloads/{renamed_filename}")
        assert del_resp.status == 200
        del_data = await del_resp.json()
        assert del_data.get("status") == "ok"

        # 6. Verify deleted
        del_check = await self.client.get(f"/api/downloads/{renamed_filename}/content")
        assert del_check.status == 404

    async def test_api_downloads_security_guards(self):
        """Test path traversal attempts are blocked safely."""
        resp1 = await self.client.get("/api/downloads/..%2F..%2Fetc%2Fpasswd/content")
        assert resp1.status in (400, 404)

        resp2 = await self.client.delete("/api/downloads/..%2F..%2Fetc%2Fpasswd")
        assert resp2.status in (400, 404)

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

    async def test_api_stats(self):
        """Test GET /api/stats and /api/analytics endpoints return structured developer analytics."""
        resp = await self.client.get("/api/stats?days=7")
        assert resp.status == 200
        data = await resp.json()
        assert data.get("status") == "ok"
        assert data.get("days") == 7
        assert "summary" in data
        assert "cognitive_flow" in data
        assert "daily_volume" in data
        assert "tool_distribution" in data
        assert "agent_distribution" in data

        # Check /api/analytics alias
        resp_alias = await self.client.get("/api/analytics")
        assert resp_alias.status == 200
        data_alias = await resp_alias.json()
        assert data_alias.get("status") == "ok"

        # Check /api/stats?days=today
        resp_today = await self.client.get("/api/stats?days=today")
        assert resp_today.status == 200
        data_today = await resp_today.json()
        assert data_today.get("days") == 1

        # Check /api/stats?days=all
        resp_all = await self.client.get("/api/stats?days=all")
        assert resp_all.status == 200
        data_all = await resp_all.json()
        assert data_all.get("days") == 0

    async def test_api_dictate_endpoint(self):
        """Test POST /api/dictate triggers dictation callback with target app."""
        mock_callback = MagicMock()
        self.companion_server._on_trigger_manual_listen = mock_callback

        resp = await self.client.post(
            "/api/dictate",
            json={"target_app": "LinkedIn", "initial_prompt": ""}
        )
        assert resp.status == 200
        data = await resp.json()
        assert data.get("success") is True
        assert data.get("target_app") == "LinkedIn"

        # Give the timer a moment to fire
        await asyncio.sleep(0.1)
        mock_callback.assert_called_once_with(
            from_wakeword=True,
            wake_phrase="transcribe",
            target_app="LinkedIn",
            initial_prompt="",
        )

    async def test_api_conversations(self):
        """Test GET /api/conversations returns list of conversations and projects."""
        resp = await self.client.get("/api/conversations")
        assert resp.status == 200
        data = await resp.json()
        assert "conversations" in data
        assert isinstance(data["conversations"], list)
        assert "projects" in data
        assert isinstance(data["projects"], list)
        if len(data["projects"]) > 0:
            first_proj = data["projects"][0]
            assert "name" in first_proj
            assert "path" in first_proj

    async def test_api_new_conversation_with_workspace_path(self):
        """Test POST /api/conversation/new passes workspace_path to conversation creator."""
        target_ws = "/Users/jaketrigg/Projects/vifi.co"
        with patch("voicefi.companion.server.create_new_antigravity_conversation", return_value="proj-conv-101") as mock_create:
            resp = await self.client.post("/api/conversation/new", json={
                "prompt": "Build landing page",
                "engine": "antigravity",
                "workspace_path": target_ws,
                "project": "vifi.co",
            })
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("conv_id") == "proj-conv-101"
            mock_create.assert_called_once_with(
                prompt="Build landing page",
                title=None,
                model=None,
                workspace_path=target_ws,
            )

    async def test_api_new_conversation_antigravity(self):
        """Test POST /api/conversation/new creates and focuses an Antigravity conversation."""
        with patch("voicefi.companion.server.create_new_antigravity_conversation", return_value="new-ag-conv-456") as mock_create:
            resp = await self.client.post("/api/conversation/new", json={
                "prompt": "Hello",
                "engine": "antigravity",
            })
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("conv_id") == "new-ag-conv-456"
            assert "conversations" in data
            mock_create.assert_called_once_with(prompt="Hello", title=None, model=None, workspace_path=None)

    async def test_api_new_conversation_custom_params(self):
        """Test POST /api/conversation/new with custom prompt, title, and model."""
        with patch("voicefi.companion.server.create_new_antigravity_conversation", return_value="custom-conv-789") as mock_create:
            resp = await self.client.post("/api/conversation/new", json={
                "prompt": "Refactor database schema",
                "title": "DB Refactor",
                "model": "pro",
                "engine": "antigravity",
            })
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("conv_id") == "custom-conv-789"
            mock_create.assert_called_once_with(prompt="Refactor database schema", title="DB Refactor", model="pro", workspace_path=None)

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
                use_headless=True,
            )

    async def test_api_send_with_workspace_path(self):
        """Test POST /api/send resolves and passes workspace_path as cwd to agent injector."""
        from voicefi.integrations.injector import DispatchResult
        mock_res = DispatchResult(success=True, delivery_type="ipc", target_conv_id="test-conv-999", engine="antigravity")
        with patch("voicefi.audio.echo_canceller.is_acoustic_echo", return_value=False), \
             patch("voicefi.companion.server.send_message_to_agent", return_value=mock_res) as mock_send:
            resp_send = await self.client.post("/api/send", json={
                "conv_id": "test-conv-999",
                "text": "Refactor router",
                "workspace_path": "/Users/jaketrigg/Projects/VoiceFi",
            })
            assert resp_send.status == 200
            data_send = await resp_send.json()
            assert data_send.get("success") is True
            mock_send.assert_called_once_with(
                conv_id="test-conv-999",
                text="Refactor router",
                sender_name="ViFi Companion",
                title="Message from ViFi Companion",
                target_engine=None,
                from_conv_id=None,
                from_engine=None,
                include_envelope=False,
                allow_foreground_fallback=False,
                use_headless=True,
                cwd=Path("/Users/jaketrigg/Projects/VoiceFi"),
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
        """Test GET /api/qr returns pairing metadata with Cloud Relay as default preferred URL."""
        with patch("voicefi.companion.server.get_active_tunnel_url", return_value=None):
            resp = await self.client.get("/api/qr")
            assert resp.status == 200
            data = await resp.json()
            assert "urls" in data
            assert "qr_data_uri" in data
            assert data["qr_data_uri"].startswith("data:image/png;base64,")
            assert "cloud_relay_url" in data
            assert data.get("preferred_url") == data.get("cloud_relay_url")
            assert "companion.voicefi.app" in data.get("preferred_url")

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

        # 3. Test QR endpoint reflects active tunnel in metadata while defaulting preferred_url to Cloud Relay
        with patch("voicefi.companion.server.get_active_tunnel_url", return_value="https://test-quick-tunnel.trycloudflare.com"):
            resp_qr = await self.client.get("/api/qr")
            assert resp_qr.status == 200
            data_qr = await resp_qr.json()
            assert data_qr.get("active_tunnel_url") == "https://test-quick-tunnel.trycloudflare.com"
            assert data_qr.get("urls", {}).get("tunnel_url") == "https://test-quick-tunnel.trycloudflare.com"
            assert data_qr.get("preferred_url") == data_qr.get("cloud_relay_url")

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
                use_headless=True,
            )

        # 3b. Test sending voice command with workspace_path over WebSocket
        with patch("voicefi.companion.server.send_message_to_agent", return_value=True) as mock_send_ws:
            await ws.send_json({
                "type": "user_voice_command",
                "conv_id": "test-conv-789",
                "text": "Inspect tests",
                "workspace_path": "/Users/jaketrigg/Projects/VoiceFi",
            })
            msg_conf2 = await ws.receive_json()
            assert msg_conf2.get("type") == "user_command_injected"
            assert msg_conf2.get("text") == "Inspect tests"
            mock_send_ws.assert_called_once_with(
                conv_id="test-conv-789",
                text="Inspect tests",
                sender_name="ViFi Companion",
                title="Message from ViFi Companion",
                use_headless=True,
                cwd=Path("/Users/jaketrigg/Projects/VoiceFi"),
            )

        # 4. Test server broadcasting agent turn completion
        self.companion_server.broadcast_turn_completion(
            summary="Build completed successfully. Ready to deploy?",
            conv_id="test-conv-456",
            agent_role="antigravity",
        )
        msg_start1 = await ws.receive_json()
        assert msg_start1.get("type") == "agent_speaking_started"

        msg_turn1 = await ws.receive_json()
        assert msg_turn1.get("type") == "agent_turn_completed"
        assert "Build completed successfully" in msg_turn1.get("summary")
        assert msg_turn1.get("step_index") is None

        # Repeat turn with same summary but advancing step_index (e.g. tell joke again)
        self.companion_server.broadcast_turn_completion(
            summary="Build completed successfully. Ready to deploy?",
            conv_id="test-conv-456",
            agent_role="antigravity",
            step_index=42,
        )
        msg_start2 = await ws.receive_json()
        assert msg_start2.get("type") == "agent_speaking_started"

        msg_turn2 = await ws.receive_json()
        assert msg_turn2.get("type") == "agent_turn_completed"
        assert msg_turn2.get("step_index") == 42

        # Immediate duplicate for step 42 should be suppressed
        self.companion_server.broadcast_turn_completion(
            summary="Build completed successfully. Ready to deploy?",
            conv_id="test-conv-456",
            agent_role="antigravity",
            step_index=42,
        )

        # Step 43 with same summary must broadcast
        self.companion_server.broadcast_turn_completion(
            summary="Build completed successfully. Ready to deploy?",
            conv_id="test-conv-456",
            agent_role="antigravity",
            step_index=43,
        )
        msg_start3 = await ws.receive_json()
        assert msg_start3.get("type") == "agent_speaking_started"

        msg_turn3 = await ws.receive_json()
        assert msg_turn3.get("step_index") == 43

        await ws.close()

    async def test_turn_eval_endpoint(self):
        """Test POST /api/turn_eval returns Shortwire / Cue dynamic turn completion states."""
        resp_done = await self.client.post(
            "/api/turn_eval",
            json={"text": "Can you run the unit tests now?", "is_dictation": False},
        )
        assert resp_done.status == 200
        data_done = await resp_done.json()
        assert data_done.get("state") == "DONE"
        assert data_done.get("wait_seconds") == 0.50
        assert data_done.get("wait_ms") == 500

        resp_hold = await self.client.post(
            "/api/turn_eval",
            json={"text": "I want to refactor the", "is_dictation": False},
        )
        assert resp_hold.status == 200
        data_hold = await resp_hold.json()
        assert data_hold.get("state") == "HOLDING"
        assert data_hold.get("wait_seconds") == 2.25
        assert data_hold.get("wait_ms") == 2250

    async def test_upload_image_endpoint(self):
        """Test POST /api/upload_image attaches image to conversation brain directory."""
        tiny_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        resp = await self.client.post(
            "/api/upload_image",
            json={
                "conv_id": "test-conv-123",
                "image_base64": tiny_png,
                "filename": "pasted_screenshot.png",
            },
        )
        assert resp.status == 200
        data = await resp.json()
        assert data.get("success") is True
        assert "pasted_screenshot_" in data.get("filename", "")
        assert data.get("filename", "").endswith(".png")
        assert data.get("is_image") is True
        assert data.get("category") == "image"
        assert Path(data["path"]).is_file()

        # Verify ?raw=1 serves raw image bytes for chat bubble thumbnail
        raw_resp = await self.client.get(data["raw_url"])
        assert raw_resp.status == 200
        raw_bytes = await raw_resp.read()
        assert len(raw_bytes) > 0

    async def test_upload_file_universal_types_and_multipart(self):
        """Test POST /api/upload_file preserves extensions for code, PDF, and markdown via multipart and JSON."""
        import aiohttp
        import base64

        # 1. Multipart FormData upload of a Python source file
        form = aiohttp.FormData()
        form.add_field("conv_id", "test-conv-123")
        form.add_field("filename", "helper_module.py")
        form.add_field(
            "file",
            b"def greet():\n    return 'hello'\n",
            filename="helper_module.py",
            content_type="text/x-python",
        )
        resp_py = await self.client.post("/api/upload_file", data=form)
        assert resp_py.status == 200
        data_py = await resp_py.json()
        assert data_py.get("success") is True
        assert data_py.get("filename", "").endswith(".py")
        assert data_py.get("extension") == "py"
        assert data_py.get("category") == "code"
        assert data_py.get("is_image") is False
        assert Path(data_py["path"]).read_text(encoding="utf-8") == "def greet():\n    return 'hello'\n"

        # 2. JSON base64 upload of a PDF document
        pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
        pdf_b64 = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("ascii")
        resp_pdf = await self.client.post(
            "/api/upload_file",
            json={
                "conv_id": "test-conv-123",
                "file_base64": pdf_b64,
                "filename": "architecture_spec.pdf",
                "mime_type": "application/pdf",
            },
        )
        assert resp_pdf.status == 200
        data_pdf = await resp_pdf.json()
        assert data_pdf.get("success") is True
        assert data_pdf.get("filename", "").endswith(".pdf")
        assert data_pdf.get("category") == "pdf"
        assert data_pdf.get("is_image") is False
        assert Path(data_pdf["path"]).read_bytes() == pdf_bytes

    async def test_workspace_files_autocomplete_endpoint(self):
        """Test GET /api/workspace/files searches workspace files for @file mentions."""
        resp = await self.client.get("/api/workspace/files?q=server.py&limit=10")
        assert resp.status == 200
        data = await resp.json()
        assert data.get("success") is True
        files = data.get("files", [])
        assert any(f.get("filename") == "server.py" for f in files)


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


def test_cli_rc_alias_parsing():
    """Test 'vifi rc' and 'vifi RC' CLI parsing."""
    from voicefi.cli import build_parser

    parser = build_parser()
    args_rc = parser.parse_args(["rc"])
    assert args_rc.command in ("companion", "rc")

    args_rc_cap = parser.parse_args(["RC"])
    assert args_rc_cap.command in ("companion", "RC")

    args_sheet = parser.parse_args(["rc", "sheet"])
    assert args_sheet.action == "sheet"

    args_flag = parser.parse_args(["rc", "--sheet"])
    assert args_flag.sheet is True


def test_cli_companion_sheet_invocation():
    """Test 'vifi rc sheet' triggers browser opening to Spicewood sheet."""
    args = MagicMock()
    args.port = 5141
    args.host = "0.0.0.0"
    args.no_qr = True
    args.open = False
    args.config = None
    args.sheet = True
    args.action = None

    with patch("voicefi.companion.server.run_companion_server") as mock_run:
        cmd_companion(args)
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["open_browser"] is True
        assert "spicewood" in kwargs["initial_path"]
