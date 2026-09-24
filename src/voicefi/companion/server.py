"""
Async HTTP & WebSocket Companion Server for VoiceFi.
Serves the mobile PWA, manages WebSocket turn synchronization, and proxies voice commands to Antigravity.
"""

import asyncio
import io
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Set, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Ensure standard Homebrew and local search paths are available in PATH
_EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin")]
_CURRENT_PATHS = os.environ.get("PATH", "").split(os.pathsep)
for _p in _EXTRA_PATHS:
    if _p not in _CURRENT_PATHS and os.path.isdir(_p):
        _CURRENT_PATHS.insert(0, _p)
os.environ["PATH"] = os.pathsep.join(_CURRENT_PATHS)

from aiohttp import web, WSMsgType
import numpy as np

from voicefi.config import VoiceFiConfig, load_config, save_config
from voicefi.license import FeatureGate
from voicefi.integrations.conversations import (
    ConversationTracker,
    load_session_cookie,
    save_session_cookie,
    set_mobile_turn_origin,
    peek_mobile_turn_origin,
    pop_mobile_turn_origin,
    get_claimed_turn_origin,
    get_turn_delivery_info,
    record_companion_heartbeat,
    has_active_companion_client,
    find_recent_claude_sessions,
    parse_claude_session,
)
from voicefi.integrations.codex import (
    find_recent_codex_sessions,
    parse_codex_session,
)
from voicefi.integrations.injector import (
    send_message_to_antigravity,
    send_message_to_agent,
    create_new_antigravity_conversation,
    inject_text_to_claude,
)
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.integrations.tool_formatter import format_tool_details
from voicefi.integrations.watcher import get_recent_transcript_paths
from voicefi.tts import get_tts_engine
from voicefi.stt import get_stt_engine
from voicefi.audio.ambient import AmbientAudioStream
from voicefi.integrations.proactive import ProactiveDispatcher, ProactiveTask, TriageCategory
from voicefi.memo.models import MemoStore, MemoRecording, CleanedMemo, SynthesizedMemo
from voicefi.memo.recorder import MemoBufferRecorder
from voicefi.memo.cleaner import MemoCleaner
from voicefi.memo.synthesizer import MemoSynthesizer
from voicefi.companion.qr import (
    get_local_ip,
    get_companion_urls,
    print_qr_code,
    generate_qr_base64_png,
)
from voicefi.companion.relay_client import RelayClient, RelaySessionCredentials
from voicefi.companion.handlers.ws import WebSocketHandlersMixin
from voicefi.companion.handlers.conversations import ConversationsHandlersMixin
from voicefi.companion.handlers.peers import PeerHandlersMixin
from voicefi.companion.handlers.vault import VaultHandlersMixin
from voicefi.companion.handlers.audio import AudioHandlersMixin
from voicefi.companion.handlers.studio import StudioHandlersMixin
from voicefi.companion.handlers.downloads import DownloadsHandlersMixin
from voicefi.companion.handlers.live import LiveHandlersMixin


STATIC_DIR = Path(__file__).resolve().parent / "static"
RECORDINGS_DIR = Path.home() / ".voicefi" / "recordings"
MOCKS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "mocks"


class CompanionServer(
    WebSocketHandlersMixin,
    ConversationsHandlersMixin,
    PeerHandlersMixin,
    VaultHandlersMixin,
    AudioHandlersMixin,
    StudioHandlersMixin,
    DownloadsHandlersMixin,
    LiveHandlersMixin,
):
    """Async web and WebSocket companion hub."""

    def __init__(
        self,
        config: Optional[VoiceFiConfig] = None,
        port: int = 5141,
        host: str = "0.0.0.0",
    ):
        self.config = config or load_config()
        self.port = port
        self.host = host
        self.tracker = ConversationTracker()
        self.active_websockets: Set[web.WebSocketResponse] = set()
        self.mobile_websockets: Set[web.WebSocketResponse] = set()
        self.app = web.Application(client_max_size=500 * 1024 * 1024)
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_running = False
        self._processed_steps: Dict[str, int] = {}
        self._ambient_stream: Optional[AmbientAudioStream] = None
        self._ambient_dispatcher = ProactiveDispatcher()
        self._memo_recorder: Optional[MemoBufferRecorder] = None
        self._memo_store = MemoStore()
        self._active_memo_id: Optional[str] = None
        self._memo_thread: Optional[threading.Thread] = None
        self._processed_hook_requests: Dict[str, float] = {}
        self._recent_broadcast_turns: Dict[str, float] = {}
        self.relay_client: Optional[RelayClient] = None

        @web.middleware
        async def cors_middleware(request, handler):
            if request.method == "OPTIONS":
                response = web.Response(status=200)
            else:
                response = await handler(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            return response

        self.app.middlewares.append(cors_middleware)
        self._setup_routes()

    def get_connectivity_summary(self) -> Dict[str, Any]:
        """Return real-time connectivity status of companion server, relay, and active devices."""
        relay_online = bool(
            self.relay_client and self.relay_client.ws and not self.relay_client.ws.closed
        )
        has_relay_peer = bool(self.relay_client and getattr(self.relay_client, "has_peer", False))
        ws_count = len([ws for ws in self.active_websockets if not ws.closed])
        total_peers = ws_count + (1 if has_relay_peer else 0)

        return {
            "port": self.port,
            "port_online": True,
            "relay_connected": relay_online,
            "has_relay_peer": has_relay_peer,
            "connected_clients": ws_count,
            "total_connected_devices": total_peers,
            "is_paired": total_peers > 0,
        }

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/companion", self.handle_index)
        self.app.router.add_get("/companion/", self.handle_index)
        self.app.router.add_get("/rc", self.handle_index)
        self.app.router.add_get("/rc/", self.handle_index)
        self.app.router.add_get("/pair", self.handle_pair)
        self.app.router.add_get("/studio", self.handle_studio)
        self.app.router.add_get("/live", self.handle_live_demo)
        self.app.router.add_get("/ws/live", self.handle_live_ws)
        self.app.router.add_get("/mock", self.handle_mock)
        self.app.router.add_get("/mocks", self.handle_mocks)
        self.app.router.add_get("/hud_mocks", self.handle_hud_mocks)
        self.app.router.add_get("/logo_mock", self.handle_logo_mock)
        self.app.router.add_get("/status_icon", self.handle_logo_mock)
        self.app.router.add_get("/downloads", self.handle_downloads)
        self.app.router.add_get("/downloads/{filename}", self.handle_download_file)
        self.app.router.add_get("/api/downloads", self.handle_api_downloads_list)
        self.app.router.add_post("/api/downloads/upload", self.handle_api_downloads_upload)
        self.app.router.add_post("/api/downloads/rename", self.handle_api_downloads_rename)
        self.app.router.add_get(
            "/api/downloads/{filename}/content", self.handle_api_downloads_get_content
        )
        self.app.router.add_put("/api/downloads/{filename}", self.handle_api_downloads_save_content)
        self.app.router.add_post(
            "/api/downloads/{filename}/save", self.handle_api_downloads_save_content
        )
        self.app.router.add_delete("/api/downloads/{filename}", self.handle_api_downloads_delete)
        self.app.router.add_get("/manifest.json", self.handle_manifest)
        self.app.router.add_get("/sw.js", self.handle_sw)
        self.app.router.add_get("/antigravity-particles.js", self.handle_antigravity_js)
        self.app.router.add_get("/assets/antigravity-particles.js", self.handle_antigravity_js)
        self.app.router.add_get("/api/sheet/spicewood", self.handle_spicewood_sheet)
        self.app.router.add_get("/api/icon", self.handle_icon)
        self.app.router.add_get("/api/status", self.handle_status)
        self.app.router.add_get("/api/stats", self.handle_stats)
        self.app.router.add_get("/api/analytics", self.handle_stats)
        self.app.router.add_get("/api/ambient/status", self.handle_ambient_status)
        self.app.router.add_post("/api/ambient/start", self.handle_ambient_start)
        self.app.router.add_post("/api/ambient/stop", self.handle_ambient_stop)
        self.app.router.add_get("/api/ambient/tasks", self.handle_ambient_tasks)
        self.app.router.add_post(
            "/api/ambient/tasks/{task_id}/action", self.handle_ambient_task_action
        )
        self.app.router.add_get("/api/memos", self.handle_list_memos)
        self.app.router.add_get("/api/memos/{memo_id}", self.handle_get_memo)
        self.app.router.add_post("/api/memos/record", self.handle_record_memo)
        self.app.router.add_post("/api/memos/{memo_id}/action", self.handle_memo_action)
        self.app.router.add_get("/api/config/audio_routing", self.handle_get_audio_routing)
        self.app.router.add_post("/api/config/audio_routing", self.handle_set_audio_routing)
        self.app.router.add_get("/api/config/ag_remote", self.handle_get_ag_remote)
        self.app.router.add_post("/api/config/ag_remote", self.handle_set_ag_remote)
        self.app.router.add_post("/api/plan/action", self.handle_plan_action)
        self.app.router.add_get("/api/conversations", self.handle_conversations)
        self.app.router.add_get("/api/conversation/{conv_id}", self.handle_conversation_detail)
        self.app.router.add_get(
            "/api/conversation/{conv_id}/artifact/{filename}", self.handle_conversation_artifact
        )
        self.app.router.add_post("/api/conversation/new", self.handle_new_conversation)
        self.app.router.add_post("/api/switch", self.handle_switch)
        self.app.router.add_post("/api/send", self.handle_send)
        self.app.router.add_post("/api/turn_notify", self.handle_turn_notify)
        self.app.router.add_post("/api/speak", self.handle_speak)
        self.app.router.add_post("/api/live", self.handle_live)
        self.app.router.add_post("/api/sfx", self.handle_sfx)
        self.app.router.add_post("/api/stop", self.handle_stop)
        self.app.router.add_post("/api/quick-bar/toggle", self.handle_quick_bar_toggle)
        self.app.router.add_post("/api/quick-bar/show", self.handle_quick_bar_show)
        self.app.router.add_post("/api/quick-bar/hide", self.handle_quick_bar_hide)
        self.app.router.add_post(
            "/api/conversation/{conv_id}/artifact_review", self.handle_artifact_review
        )
        self.app.router.add_post("/api/artifact_review", self.handle_artifact_review)
        self.app.router.add_post(
            "/api/conversation/{conv_id}/image_feedback", self.handle_image_feedback
        )
        self.app.router.add_post("/api/image_feedback", self.handle_image_feedback)
        self.app.router.add_post("/api/screenshot", self.handle_screenshot)
        self.app.router.add_post("/api/upload_image", self.handle_upload_image)
        self.app.router.add_post("/api/record_mac", self.handle_record_mac)
        self.app.router.add_post("/api/stop_mac_recording", self.handle_stop_mac_recording)
        self.app.router.add_post("/api/stt", self.handle_stt)
        self.app.router.add_post("/api/tts", self.handle_tts)
        self.app.router.add_post(
            "/api/troubleshoot/feedback_loop", self.handle_troubleshoot_feedback_loop
        )
        self.app.router.add_post(
            "/api/troubleshoot/feedback-loop", self.handle_troubleshoot_feedback_loop
        )
        self.app.router.add_post(
            "/api/troubleshoot/hearing_test", self.handle_troubleshoot_hearing_test
        )
        self.app.router.add_post(
            "/api/troubleshoot/hearing-test", self.handle_troubleshoot_hearing_test
        )
        self.app.router.add_post("/api/vault/query", self.handle_vault_query)
        self.app.router.add_post("/api/vault/capture", self.handle_vault_capture)
        self.app.router.add_post("/api/vault/memo", self.handle_vault_memo)
        self.app.router.add_get("/api/vault/today", self.handle_vault_today)
        self.app.router.add_get("/api/vault/status", self.handle_vault_status)
        self.app.router.add_post("/api/vault/launch_agent", self.handle_vault_launch_agent)
        self.app.router.add_get("/api/qr", self.handle_qr)
        self.app.router.add_get("/api/tunnel/status", self.handle_tunnel_status)
        self.app.router.add_post("/api/tunnel/start", self.handle_tunnel_start)
        self.app.router.add_get("/api/license", self.handle_get_license)
        self.app.router.add_post("/api/license", self.handle_post_license)
        self.app.router.add_get("/api/tier", self.handle_get_license)
        self.app.router.add_post("/api/hook/event", self.handle_hook_event)
        # Voice Recording Studio, Audio FX & Reel Generator APIs
        self.app.router.add_get("/api/studio/presets", self.handle_studio_presets)
        self.app.router.add_get("/api/studio/recordings", self.handle_studio_recordings)
        self.app.router.add_get(
            "/api/studio/recording/{rec_id}", self.handle_studio_recording_stream
        )
        self.app.router.add_post("/api/studio/upload", self.handle_studio_upload)
        self.app.router.add_post("/api/studio/record", self.handle_studio_record)
        self.app.router.add_post("/api/studio/trim", self.handle_studio_trim)
        self.app.router.add_post("/api/studio/apply_fx", self.handle_studio_apply_fx)
        self.app.router.add_post("/api/studio/transcribe", self.handle_studio_transcribe)
        self.app.router.add_post("/api/studio/generate_reel", self.handle_studio_generate_reel)
        # Local Network Peer Discovery & Cross-Mac Data Handoff APIs
        self.app.router.add_get("/api/peer/info", self.handle_peer_info)
        self.app.router.add_post("/api/peer/send", self.handle_peer_send)
        self.app.router.add_get("/api/peer/clip", self.handle_peer_clip_get)
        self.app.router.add_post("/api/peer/clip", self.handle_peer_clip_post)
        self.app.router.add_post("/api/peer/sync", self.handle_peer_sync)
        self.app.router.add_get("/api/peers", self.handle_peers_list)
        self.app.router.add_get("/ws", self.handle_ws)

    # Static Handlers
    async def handle_index(self, request: web.Request) -> web.Response:
        index_path = STATIC_DIR / "index.html"
        if not index_path.is_file():
            return web.Response(text="VoiceFi Companion UI missing.", status=404)
        return web.Response(
            text=index_path.read_text(encoding="utf-8"),
            content_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_pair(self, request: web.Request) -> web.Response:
        pair_path = STATIC_DIR / "pair.html"
        if not pair_path.is_file():
            return web.Response(text="VoiceFi Pair UI missing.", status=404)
        return web.Response(
            text=pair_path.read_text(encoding="utf-8"),
            content_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_studio(self, request: web.Request) -> web.Response:
        studio_path = STATIC_DIR / "studio.html"
        if not studio_path.is_file():
            return web.Response(text="VoiceFi Studio UI missing.", status=404)
        return web.Response(
            text=studio_path.read_text(encoding="utf-8"),
            content_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_mock(self, request: web.Request) -> web.Response:
        mock_path = (
            STATIC_DIR / "mocks.html"
            if (STATIC_DIR / "mocks.html").is_file()
            else (
                STATIC_DIR / "mock.html"
                if (STATIC_DIR / "mock.html").is_file()
                else (
                    MOCKS_DIR / "mocks.html"
                    if (MOCKS_DIR / "mocks.html").is_file()
                    else MOCKS_DIR / "mock.html"
                )
            )
        )
        if not mock_path.is_file():
            return web.Response(text="VoiceFi Mock Studio UI missing.", status=404)
        return web.Response(
            text=mock_path.read_text(encoding="utf-8"),
            content_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_mocks(self, request: web.Request) -> web.Response:
        mock_path = (
            STATIC_DIR / "mocks.html"
            if (STATIC_DIR / "mocks.html").is_file()
            else (
                STATIC_DIR / "mock.html"
                if (STATIC_DIR / "mock.html").is_file()
                else (
                    MOCKS_DIR / "mocks.html"
                    if (MOCKS_DIR / "mocks.html").is_file()
                    else MOCKS_DIR / "mock.html"
                )
            )
        )
        if not mock_path.is_file():
            return web.Response(text="VoiceFi Mocks UI missing.", status=404)
        return web.Response(
            text=mock_path.read_text(encoding="utf-8"),
            content_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_hud_mocks(self, request: web.Request) -> web.Response:
        hud_mock_path = (
            STATIC_DIR / "hud_mocks.html"
            if (STATIC_DIR / "hud_mocks.html").is_file()
            else MOCKS_DIR / "hud_mocks.html"
        )
        if not hud_mock_path.is_file():
            return web.Response(text="VoiceFi Dynamic Island HUD Mocks missing.", status=404)
        return web.Response(
            text=hud_mock_path.read_text(encoding="utf-8"),
            content_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_logo_mock(self, request: web.Request) -> web.Response:
        mock_path = (
            STATIC_DIR / "voicefi_logo_mock.html"
            if (STATIC_DIR / "voicefi_logo_mock.html").is_file()
            else MOCKS_DIR / "voicefi_logo_mock.html"
        )
        if not mock_path.is_file():
            return web.Response(text="VoiceFi Reactive Logo Mock UI missing.", status=404)
        return web.Response(
            text=mock_path.read_text(encoding="utf-8"),
            content_type="text/html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_manifest(self, request: web.Request) -> web.Response:
        manifest_path = STATIC_DIR / "manifest.json"
        if not manifest_path.is_file():
            return web.Response(text="{}", content_type="application/json")
        return web.Response(
            text=manifest_path.read_text(encoding="utf-8"), content_type="application/manifest+json"
        )

    async def handle_sw(self, request: web.Request) -> web.Response:
        sw_path = STATIC_DIR / "sw.js"
        if not sw_path.is_file():
            return web.Response(text="", content_type="application/javascript")
        return web.Response(
            text=sw_path.read_text(encoding="utf-8"),
            content_type="application/javascript",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_antigravity_js(self, request: web.Request) -> web.Response:
        js_path = STATIC_DIR / "antigravity-particles.js"
        if not js_path.is_file():
            return web.Response(text="", content_type="application/javascript", status=404)
        return web.Response(
            text=js_path.read_text(encoding="utf-8"),
            content_type="application/javascript",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    async def handle_icon(self, request: web.Request) -> web.Response:
        candidate_paths = [
            Path(__file__).resolve().parent.parent.parent.parent
            / "assets"
            / "VoiceFi.iconset"
            / "icon_512x512.png",
            Path(__file__).resolve().parent.parent.parent.parent
            / "assets"
            / "VoiceFi.iconset"
            / "icon_256x256.png",
            Path(__file__).resolve().parent.parent.parent.parent / "assets" / "icon.png",
            STATIC_DIR / "assets" / "icon.png",
        ]
        for icon_path in candidate_paths:
            if icon_path.is_file():
                return web.Response(body=icon_path.read_bytes(), content_type="image/png")
        # Minimal transparent 1x1 png fallback
        png_1x1 = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        return web.Response(body=png_1x1, content_type="image/png")

    # API Endpoints
    async def handle_status(self, request: web.Request) -> web.Response:
        active = self.tracker.get_active_or_latest()
        active_data = None
        if active:
            active_data = {
                "id": active.id,
                "title": active.title,
                "status": active.status,
                "last_agent_text": active.last_agent_text,
                "last_user_text": active.last_user_text,
            }
        tier_summary = FeatureGate.get_tier_summary(self.config)
        conn = self.get_connectivity_summary()
        return web.json_response(
            {
                "status": "online",
                "active_conversation": active_data,
                "connected_clients": len(self.active_websockets),
                "total_connected_devices": conn.get("total_connected_devices", 0),
                "relay_connected": conn.get("relay_connected", False),
                "has_relay_peer": conn.get("has_relay_peer", False),
                "audio_routing": getattr(
                    getattr(self.config, "companion", None), "audio_routing", "smart"
                ),
                "mute_mac_when_companion_active": getattr(
                    getattr(self.config, "companion", None), "mute_mac_when_companion_active", False
                ),
                "ambient_active": self._ambient_stream is not None
                and self._ambient_stream.is_running,
                "memo_active": self._memo_recorder is not None,
                "tier": tier_summary.get("tier"),
                "status_text": tier_summary.get("status_text"),
                "is_pro": tier_summary.get("is_pro"),
                "is_trial": tier_summary.get("is_trial"),
                "trial_days_remaining": tier_summary.get("trial_days_remaining"),
                "trial_expires_at": tier_summary.get("trial_expires_at"),
                "pricing": tier_summary.get("pricing"),
            }
        )

    async def handle_stats(self, request: web.Request) -> web.Response:
        """Return analytics summary, HAI cognitive flow breakdown, tool and agent distributions."""
        try:
            from voicefi.analytics import (
                get_analytics_summary,
                get_cognitive_flow_breakdown,
                get_daily_turn_volume,
                get_tool_usage_breakdown,
                get_agent_distribution,
            )

            days_raw = str(request.query.get("days", "7")).strip().lower()
            if days_raw in ("today", "1"):
                days = 1
            elif days_raw in ("all", "all-time", "0"):
                days = 0
            else:
                try:
                    days = int(days_raw)
                except (ValueError, TypeError):
                    days = 7

            summary = get_analytics_summary(days=days)
            flow = get_cognitive_flow_breakdown(days=days)
            daily = get_daily_turn_volume(days=days)
            tools = get_tool_usage_breakdown(days=days)
            agents = get_agent_distribution(days=days)

            return web.json_response(
                {
                    "status": "ok",
                    "days": days,
                    "summary": summary,
                    "cognitive_flow": flow,
                    "daily_volume": daily,
                    "tool_distribution": tools,
                    "agent_distribution": agents,
                }
            )
        except Exception as e:
            return web.json_response(
                {
                    "status": "error",
                    "error": str(e),
                },
                status=500,
            )

    async def handle_get_license(self, request: web.Request) -> web.Response:
        """Return comprehensive licensing, 14-day free trial, and pricing metadata."""
        self.config = load_config()
        FeatureGate.ensure_trial_started(self.config)
        summary = FeatureGate.get_tier_summary(self.config)
        return web.json_response(summary)

    async def handle_post_license(self, request: web.Request) -> web.Response:
        """Activate a Pro license key via REST API."""
        try:
            data = await request.json()
            key = str(data.get("license_key", "")).strip()
            if not key:
                return web.json_response({"error": "Missing or empty license_key"}, status=400)

            result = FeatureGate.activate_license(key, config=self.config)
            if not result.get("success"):
                return web.json_response(
                    {
                        "error": result.get("error", "Invalid license key signature"),
                        "details": result,
                    },
                    status=400,
                )

            self.config = result.get("config") or load_config()
            summary = FeatureGate.get_tier_summary(self.config)
            return web.json_response(
                {
                    "success": True,
                    "message": f"VoiceFi {self.config.tier.capitalize()} license activated ({result.get('expires_at', 'Perpetual')})",
                    "summary": summary,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # Ambient APIs
    async def handle_ambient_status(self, request: web.Request) -> web.Response:
        is_running = self._ambient_stream is not None and self._ambient_stream.is_running
        tasks = []
        if self._ambient_dispatcher:
            for t in self._ambient_dispatcher.get_staged_tasks():
                tasks.append(
                    {
                        "id": t.id,
                        "category": t.category.value,
                        "summary": t.summary,
                        "action_prompt": t.action_prompt,
                        "suggested_workspace": t.suggested_workspace,
                        "status": t.status,
                        "created_at": t.created_at,
                    }
                )
        return web.json_response(
            {
                "is_running": is_running,
                "noise_floor": getattr(self._ambient_stream, "current_noise_floor", 0.006)
                if self._ambient_stream
                else 0.006,
                "staged_tasks": tasks,
            }
        )

    async def handle_ambient_start(self, request: web.Request) -> web.Response:
        try:
            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    pass
            source = data.get("source", "mic")
            success = self.start_ambient(source=source)
            return web.json_response({"success": success, "is_running": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_ambient_stop(self, request: web.Request) -> web.Response:
        try:
            self.stop_ambient()
            return web.json_response({"success": True, "is_running": False})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_ambient_tasks(self, request: web.Request) -> web.Response:
        tasks = []
        if self._ambient_dispatcher:
            for t in self._ambient_dispatcher.get_staged_tasks():
                tasks.append(
                    {
                        "id": t.id,
                        "category": t.category.value,
                        "summary": t.summary,
                        "action_prompt": t.action_prompt,
                        "suggested_workspace": t.suggested_workspace,
                        "status": t.status,
                        "created_at": t.created_at,
                    }
                )
        return web.json_response({"tasks": tasks})

    async def handle_ambient_task_action(self, request: web.Request) -> web.Response:
        task_id = request.match_info.get("task_id", "")
        try:
            data = await request.json()
            action = data.get("action", "dispatch")
            if not self._ambient_dispatcher:
                return web.json_response(
                    {"error": "Ambient dispatcher not initialized"}, status=400
                )

            if action == "dismiss":
                self._ambient_dispatcher.dismiss_task(task_id)
                self.broadcast_event(
                    {
                        "type": "ambient_task_updated",
                        "task_id": task_id,
                        "status": "dismissed",
                        "timestamp": time.time(),
                    }
                )
                return web.json_response({"success": True, "status": "dismissed"})
            elif action == "dispatch":
                tasks = {t.id: t for t in self._ambient_dispatcher.get_staged_tasks()}
                task = tasks.get(task_id)
                if not task:
                    return web.json_response({"error": "Task not found"}, status=404)

                set_mobile_turn_origin(None)
                prompt = f"[{task.category.value}] {task.action_prompt}"
                delivered = send_message_to_antigravity(conv_id=None, text=prompt)
                self._ambient_dispatcher.complete_task(
                    task_id, result_summary="Dispatched to Antigravity"
                )
                self.broadcast_event(
                    {
                        "type": "ambient_task_updated",
                        "task_id": task_id,
                        "status": "completed",
                        "delivered": delivered,
                        "timestamp": time.time(),
                    }
                )
                return web.json_response(
                    {"success": True, "status": "dispatched", "delivered": delivered}
                )
            else:
                return web.json_response({"error": f"Unknown action: {action}"}, status=400)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # Memo APIs
    async def handle_list_memos(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", 50))
        memos = self._memo_store.list_memos(limit=limit)
        return web.json_response({"memos": memos})

    async def handle_get_memo(self, request: web.Request) -> web.Response:
        memo_id = request.match_info.get("memo_id", "")
        res = self._memo_store.get_memo(memo_id)
        if not res:
            return web.json_response({"error": "Memo not found"}, status=404)
        rec, synth = res
        return web.json_response(
            {
                "recording": rec.model_dump() if hasattr(rec, "model_dump") else rec.dict(),
                "synthesis": (synth.model_dump() if hasattr(synth, "model_dump") else synth.dict())
                if synth
                else None,
                "markdown": synth.to_markdown() if synth else rec.raw_transcript,
            }
        )

    async def handle_record_memo(self, request: web.Request) -> web.Response:
        try:
            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    pass
            duration = float(data.get("duration", self.config.memo.default_duration_seconds))
            title = data.get("title", "Voice Memo")
            memo_id = self.start_memo_session(target_duration=duration, title=title)
            return web.json_response({"success": True, "memo_id": memo_id, "duration": duration})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_memo_action(self, request: web.Request) -> web.Response:
        memo_id = request.match_info.get("memo_id", "")
        try:
            data = await request.json()
            action = data.get("action", "")
            if action == "extend":
                seconds = float(data.get("seconds", 60.0))
                self.extend_memo(seconds)
                return web.json_response({"success": True, "extended_seconds": seconds})
            elif action == "pause":
                is_paused = self.pause_memo()
                return web.json_response({"success": True, "is_paused": is_paused})
            elif action == "stop":
                self.stop_memo()
                return web.json_response({"success": True, "stopped": True})
            else:
                return web.json_response({"error": f"Unknown memo action: {action}"}, status=400)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_get_audio_routing(self, request: web.Request) -> web.Response:
        cfg = load_config()
        self.config = cfg
        companion = getattr(cfg, "companion", None)
        return web.json_response(
            {
                "audio_routing": getattr(companion, "audio_routing", "smart"),
                "mute_mac_when_companion_active": getattr(
                    companion, "mute_mac_when_companion_active", False
                ),
                "active_clients": len(self.active_websockets),
            }
        )

    async def handle_set_audio_routing(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            cfg = load_config()
            routing = data.get("audio_routing")
            mute_mac = data.get("mute_mac_when_companion_active")
            if routing and routing in ("smart", "origin_only", "phone_only", "mac_only", "both"):
                cfg.companion.audio_routing = routing
            if mute_mac is not None:
                cfg.companion.mute_mac_when_companion_active = bool(mute_mac)
            save_config(cfg)
            self.config = cfg
            self.broadcast_event(
                {
                    "type": "config_updated",
                    "audio_routing": cfg.companion.audio_routing,
                    "mute_mac_when_companion_active": cfg.companion.mute_mac_when_companion_active,
                }
            )
            return web.json_response(
                {
                    "success": True,
                    "audio_routing": cfg.companion.audio_routing,
                    "mute_mac_when_companion_active": cfg.companion.mute_mac_when_companion_active,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_get_ag_remote(self, request: web.Request) -> web.Response:
        url_file = Path.home() / ".voicefi" / "ag_remote_url.txt"
        saved_url = ""
        if url_file.is_file():
            saved_url = url_file.read_text(encoding="utf-8").strip()
        return web.json_response({"url": saved_url})

    async def handle_set_ag_remote(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            url = str(data.get("url", "")).strip()
            url_file = Path.home() / ".voicefi" / "ag_remote_url.txt"
            url_file.parent.mkdir(parents=True, exist_ok=True)
            url_file.write_text(url, encoding="utf-8")
            self.broadcast_event(
                {
                    "type": "ag_remote_updated",
                    "url": url,
                }
            )
            return web.json_response({"success": True, "url": url})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_speak(self, request: web.Request) -> web.Response:
        """
        Synthesize and play speech aloud through local speakers/TTS within speech_turn_lock.
        Receives JSON: {"text": "...", "voice": "...", "rate": "...", "conv_id": "..."}
        Returns JSON: {"status": "ok", "text": "..."}
        """
        try:
            try:
                data = await request.json()
            except Exception:
                return web.json_response(
                    {"error": "Invalid JSON payload", "status": "error"}, status=400
                )

            if not isinstance(data, dict):
                return web.json_response(
                    {"error": "JSON body must be an object", "status": "error"}, status=400
                )

            raw_text = data.get("text")
            if raw_text is None or not isinstance(raw_text, str) or not raw_text.strip():
                return web.json_response(
                    {"error": "Missing or empty 'text' field", "status": "error"}, status=400
                )

            clean_text = raw_text.strip()
            voice = data.get("voice")
            rate = data.get("rate")
            conv_id = data.get("conv_id") or data.get("conversation_id")
            agent = data.get("agent") or data.get("agent_name") or "antigravity"
            block = bool(data.get("block", True))

            if conv_id:
                try:
                    from voicefi.integrations.conversations import claim_active_conversation_turn

                    claim_active_conversation_turn(clean_text, conv_id=conv_id)
                except Exception:
                    pass

            self.broadcast_event(
                {
                    "type": "speak",
                    "text": clean_text,
                    "conv_id": conv_id or "active",
                    "voice": voice or "Viv",
                    "agent_role": agent,
                }
            )
            self.broadcast_event(
                {
                    "type": "agent_speaking_started",
                    "text": clean_text,
                    "conv_id": conv_id or "active",
                    "voice": voice or "Viv",
                }
            )

            target_device = (data.get("target") or data.get("device") or "").lower()
            speak_on_mac = target_device not in ("phone", "mobile", "companion")

            def _speak_sync():
                from voicefi.config import load_config
                from voicefi.tts import get_tts_engine
                from voicefi.tts.base import speech_turn_lock, DuplicateSpeechSuppressed

                cfg = load_config()
                tts = get_tts_engine(cfg, agent_name=agent, voice_override=voice)
                if rate and hasattr(tts, "rate"):
                    try:
                        tts.rate = str(rate)
                    except Exception:
                        pass

                try:
                    with speech_turn_lock(
                        text=clean_text,
                        agent_name=agent,
                        persona_name=getattr(tts, "persona_name", None),
                    ):
                        tts.speak(clean_text)
                except DuplicateSpeechSuppressed:
                    pass

            if speak_on_mac:
                loop = asyncio.get_running_loop()
                if block:
                    try:
                        await loop.run_in_executor(None, _speak_sync)
                    finally:
                        self.broadcast_event(
                            {
                                "type": "agent_speaking_finished",
                                "conv_id": conv_id or "active",
                            }
                        )
                else:

                    def _background_speak():
                        try:
                            _speak_sync()
                        finally:
                            self.broadcast_event(
                                {
                                    "type": "agent_speaking_finished",
                                    "conv_id": conv_id or "active",
                                }
                            )

                    threading.Thread(target=_background_speak, daemon=True).start()

            return web.json_response(
                {
                    "status": "ok",
                    "text": clean_text,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e), "status": "error"}, status=500)

    async def handle_sfx(self, request: web.Request) -> web.Response:
        """
        Trigger procedural sound effect via play_sfx().
        Receives JSON: {"name": "...", "volume": 0.8, "block": false}
        Returns JSON: {"status": "ok", "sfx": "name"}
        """
        try:
            try:
                data = await request.json()
            except Exception:
                return web.json_response(
                    {"error": "Invalid JSON payload", "status": "error"}, status=400
                )

            if not isinstance(data, dict):
                return web.json_response(
                    {"error": "JSON body must be an object", "status": "error"}, status=400
                )

            raw_name = data.get("name", "drum_smash")
            if raw_name is None or not isinstance(raw_name, str) or not raw_name.strip():
                from voicefi.audio.sfx import list_available_sfx

                return web.json_response(
                    {
                        "error": "Missing or invalid 'name' parameter",
                        "status": "error",
                        "available": list_available_sfx(),
                    },
                    status=400,
                )

            clean_name = raw_name.strip()
            raw_volume = data.get("volume", 0.8)
            try:
                volume = float(raw_volume)
                volume = max(0.0, min(volume, 2.0))
            except (ValueError, TypeError):
                return web.json_response(
                    {
                        "error": "Invalid 'volume' parameter, expected number",
                        "status": "error",
                    },
                    status=400,
                )

            block = bool(data.get("block", False))

            from voicefi.audio.sfx import play_sfx, list_available_sfx

            success = play_sfx(clean_name, block=block, volume=volume)
            if not success:
                return web.json_response(
                    {
                        "error": f"Unknown sound effect: '{clean_name}'",
                        "status": "error",
                        "available": list_available_sfx(),
                    },
                    status=400,
                )

            self.broadcast_event(
                {
                    "type": "sfx_played",
                    "name": clean_name,
                }
            )

            return web.json_response(
                {
                    "status": "ok",
                    "sfx": clean_name,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e), "status": "error"}, status=500)

    async def handle_stop(self, request: web.Request) -> web.Response:
        """
        Trigger stop_all_speech() to halt all active speech playback and audio recording.
        Returns JSON: {"status": "ok", "stopped": true}
        """
        try:
            now = time.time()
            last_stop = getattr(self, "_last_stop_handle_time", 0.0)
            if (now - last_stop) < 0.5:
                return web.json_response({"status": "ok", "stopped": True, "debounced": True})
            self._last_stop_handle_time = now

            from voicefi.tts.base import stop_all_speech

            stop_all_speech(broadcast_web=False)

            # Also stop any active Mac audio recording if in progress
            if hasattr(self, "_active_mac_recorder") and self._active_mac_recorder:
                try:
                    self._active_mac_recorder.stop()
                except Exception:
                    pass

            self.broadcast_event(
                {
                    "type": "speech_stopped",
                    "timestamp": time.time(),
                }
            )

            return web.json_response(
                {
                    "status": "ok",
                    "stopped": True,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e), "status": "error"}, status=500)

    async def handle_quick_bar_toggle(self, request: web.Request) -> web.Response:
        """Toggle the native macOS Quick Prompt Bar window."""
        try:
            from voicefi.ui.quick_bar import QuickPromptBarWindow

            bar = QuickPromptBarWindow.get_instance()
            bar.toggle()
            return web.json_response({"status": "ok", "action": "toggle"})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def handle_quick_bar_show(self, request: web.Request) -> web.Response:
        """Show the native macOS Quick Prompt Bar window, optionally with initial text."""
        try:
            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    data = {}
            initial_text = data.get("text") or data.get("prompt")
            from voicefi.ui.quick_bar import QuickPromptBarWindow

            bar = QuickPromptBarWindow.get_instance()
            bar.show(initial_text=initial_text)
            return web.json_response({"status": "ok", "action": "show", "text": initial_text})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def handle_quick_bar_hide(self, request: web.Request) -> web.Response:
        """Hide the native macOS Quick Prompt Bar window."""
        try:
            from voicefi.ui.quick_bar import QuickPromptBarWindow

            bar = QuickPromptBarWindow.get_instance()
            bar.hide()
            return web.json_response({"status": "ok", "action": "hide"})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def handle_hook_event(self, request: web.Request) -> web.Response:
        """
        Handle lifecycle hook event forwarded from CLI hook.
        Updates active session cookie, broadcasts WebSocket event, and runs the turn worker
        in a background thread with warm STT/TTS engines and Floating HUD.
        """
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}

        now = time.time()
        request_id = str(data.get("request_id") or "")
        if request_id:
            # Clean entries older than 30s
            self._processed_hook_requests = {
                k: v for k, v in self._processed_hook_requests.items() if (now - v) < 30.0
            }
            if request_id in self._processed_hook_requests:
                return web.json_response(
                    {
                        "success": True,
                        "status": "duplicate",
                        "request_id": request_id,
                    }
                )
            self._processed_hook_requests[request_id] = now

        target_agent = str(data.get("agent") or "antigravity").lower().strip()
        is_claude = target_agent in ("claude", "claude_code") or target_agent.startswith("claude")
        is_codex = (
            target_agent in ("codex", "openai", "chatgpt")
            or target_agent.startswith("codex")
            or target_agent.startswith("chatgpt")
            or target_agent.startswith("openai")
        )
        conv_id = (
            data.get("conversationId") or data.get("conversation_id") or data.get("conv_id") or ""
        )
        transcript_path_str = data.get("transcriptPath") or data.get("transcript_path") or ""
        workspace_paths = data.get("workspacePaths") or data.get("workspace_paths") or []
        workspace_path = workspace_paths[0] if workspace_paths else None

        if conv_id:
            engine_type = "claude" if is_claude else ("codex" if is_codex else "antigravity")
            save_session_cookie(
                conv_id=conv_id,
                transcript_path=transcript_path_str,
                workspace_path=workspace_path,
                engine=engine_type,
            )
            self.tracker.set_active_focus(conv_id)

        # Spawn background turn processor on daemon thread so HTTP response returns instantly (< 5ms)
        def _process_hook_turn():
            try:
                fresh_config = load_config()
                if is_claude:
                    from voicefi.integrations.claude import handle_claude_stop_hook

                    handle_claude_stop_hook(data, fresh_config)
                elif is_codex:
                    from voicefi.integrations.codex import handle_codex_stop_hook

                    handle_codex_stop_hook(data, fresh_config)
                else:
                    from voicefi.integrations.antigravity import handle_antigravity_stop_hook

                    handle_antigravity_stop_hook(data, fresh_config)
            except Exception as e:
                print(f"[CompanionServer] Error processing background hook turn: {e}")

        turn_thread = threading.Thread(target=_process_hook_turn, daemon=True)
        turn_thread.start()

        return web.json_response(
            {
                "success": True,
                "status": "handled",
                "agent": target_agent,
                "conversationId": conv_id,
                "request_id": request_id,
            }
        )

    async def handle_troubleshoot_feedback_loop(self, request: web.Request) -> web.Response:
        """Run feedback loop test asynchronously via AudioTroubleshooter and return JSON metrics."""
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}

        voice = data.get("voice", "Aria")
        text = data.get("text", "This is a test feedback loop")
        send = data.get("send", False)
        conv_id = data.get("conv_id")
        rate = data.get("rate")
        provider = data.get("provider")

        from voicefi.troubleshoot import AudioTroubleshooter

        loop = asyncio.get_running_loop()
        troubleshooter = AudioTroubleshooter(self.config)

        res = await loop.run_in_executor(
            None,
            lambda: troubleshooter.test_feedback_loop(
                voice_name_or_id=voice,
                text=text,
                provider=provider,
                rate=rate,
                send_to_conversation=send,
                conv_id=conv_id,
            ),
        )
        return web.json_response(res)

    async def handle_troubleshoot_hearing_test(self, request: web.Request) -> web.Response:
        """Run acoustic hearing test asynchronously via AudioTroubleshooter and return JSON metrics."""
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            data = {}

        voice = data.get("voice", "Aria")
        text = data.get("text", "This is a hearing test")
        rate = data.get("rate")
        provider = data.get("provider")

        from voicefi.troubleshoot import AudioTroubleshooter

        loop = asyncio.get_running_loop()
        troubleshooter = AudioTroubleshooter(self.config)

        res = await loop.run_in_executor(
            None,
            lambda: troubleshooter.test_hearing(
                voice_name_or_id=voice,
                text=text,
                provider=provider,
                rate=rate,
            ),
        )
        return web.json_response(res.to_dict())

    def _speak_in_background(self, spoken: str) -> None:
        """Read text aloud off the event loop, bracketed by lifecycle events."""
        self.broadcast_event({"type": "agent_speaking_started", "text": spoken})

        def _speak_worker():
            try:
                tts = get_tts_engine(self.config)
                tts.speak(spoken)
            except Exception as ex:
                logger.warning("[VaultAgent] TTS playback error: %s", ex)
            finally:
                self.broadcast_event({"type": "agent_speaking_finished"})

        threading.Thread(target=_speak_worker, daemon=True).start()

    async def handle_screenshot(self, request: web.Request) -> web.Response:
        """Capture screenshot on Mac and save in the conversation's artifacts."""
        try:
            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    data = {}

            conv_id = data.get("conv_id")
            if not conv_id:
                active = self.tracker.get_active_or_latest()
                conv_id = active.id if active else "default"

            bdir = self.tracker.brain_dir / conv_id
            bdir.mkdir(parents=True, exist_ok=True)

            ts_str = time.strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{ts_str}.jpg"
            target_path = bdir / filename

            # Execute screencapture on Mac
            res = subprocess.run(
                ["screencapture", "-x", "-t", "jpg", str(target_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=6,
            )

            if not target_path.is_file() or target_path.stat().st_size == 0:
                return web.json_response(
                    {
                        "error": "Failed to capture screenshot",
                        "details": res.stderr.decode(errors="ignore"),
                    },
                    status=500,
                )

            art = self.tracker.get_artifact(conv_id, filename)
            self.broadcast_event(
                {
                    "type": "conversation_updated",
                    "conv_id": conv_id,
                }
            )

            return web.json_response(
                {
                    "success": True,
                    "conv_id": conv_id,
                    "filename": filename,
                    "path": str(target_path),
                    "url": f"/api/conversation/{conv_id}/artifact/{filename}",
                    "artifact": art,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_upload_image(self, request: web.Request) -> web.Response:
        """Handle image upload from phone camera, multi-file gallery, or screen share."""
        try:
            data = await request.json()
            conv_id = data.get("conv_id")
            image_b64 = data.get("image_base64", "")
            raw_filename = data.get("filename", "")

            if not conv_id:
                active = self.tracker.get_active_or_latest()
                conv_id = active.id if active else "default"

            if not image_b64:
                return web.json_response({"error": "Missing image data"}, status=400)

            if "," in image_b64:
                image_b64 = image_b64.split(",", 1)[1]

            import base64
            import uuid

            img_bytes = base64.b64decode(image_b64)

            bdir = self.tracker.brain_dir / conv_id
            bdir.mkdir(parents=True, exist_ok=True)

            ts_str = time.strftime("%Y%m%d_%H%M%S")
            unique_id = uuid.uuid4().hex[:6]
            if raw_filename:
                raw_p = Path(raw_filename)
                clean_stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw_p.stem)
                ext = raw_p.suffix if raw_p.suffix else ".jpg"
                filename = f"{clean_stem}_{ts_str}_{unique_id}{ext}"
            else:
                filename = f"mobile_photo_{ts_str}_{unique_id}.jpg"

            target_path = bdir / filename
            target_path.write_bytes(img_bytes)

            art = self.tracker.get_artifact(conv_id, filename)
            self.broadcast_event(
                {
                    "type": "conversation_updated",
                    "conv_id": conv_id,
                }
            )

            return web.json_response(
                {
                    "success": True,
                    "conv_id": conv_id,
                    "filename": filename,
                    "path": str(target_path),
                    "url": f"/api/conversation/{conv_id}/artifact/{filename}",
                    "artifact": art,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_record_mac(self, request: web.Request) -> web.Response:
        """Trigger one-shot voice recording on Mac microphone and transcribe via local Whisper."""
        try:
            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    data = {}

            conv_id = data.get("conv_id")
            if not conv_id:
                active = self.tracker.get_active_or_latest()
                conv_id = active.id if active else "default"

            self.broadcast_event(
                {
                    "type": "mac_recording_started",
                    "conv_id": conv_id,
                }
            )

            from voicefi.audio.recorder import AudioRecorder

            recorder = AudioRecorder(
                energy_threshold=self.config.vad.energy_threshold,
                silence_duration=self.config.vad.silence_duration,
                max_record_seconds=self.config.vad.max_record_seconds,
                barge_in=self.config.vad.barge_in,
            )
            self._active_mac_recorder = recorder

            def _record_and_transcribe():
                try:
                    _, wav_path = recorder.record_speech_auto()
                    stt = get_stt_engine(self.config)
                    transcript = stt.transcribe(wav_path)
                    try:
                        wav_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return transcript
                finally:
                    self._active_mac_recorder = None

            loop = asyncio.get_event_loop()
            transcript = await loop.run_in_executor(None, _record_and_transcribe)

            if transcript and transcript.strip():
                clean_t = transcript.strip()
                from voicefi.audio.echo_canceller import is_acoustic_echo

                if is_acoustic_echo(clean_t):
                    print(
                        f'[CompanionServer] 🛡️ Filtered acoustic self-echo from Mac mic: "{clean_t}"'
                    )
                    self.broadcast_event(
                        {
                            "type": "mac_recording_empty",
                            "conv_id": conv_id,
                            "reason": "acoustic_echo_filtered",
                        }
                    )
                    return web.json_response(
                        {
                            "success": False,
                            "transcript": "",
                            "error": "Acoustic self-echo filtered",
                        }
                    )

                set_mobile_turn_origin(conv_id)
                delivered = bool(send_message_to_agent(conv_id=conv_id, text=clean_t))
                self.broadcast_event(
                    {
                        "type": "user_command_injected",
                        "conv_id": conv_id,
                        "text": clean_t,
                        "delivered": delivered,
                    }
                )
                return web.json_response(
                    {
                        "success": True,
                        "transcript": clean_t,
                        "delivered": delivered,
                    }
                )
            else:
                self.broadcast_event(
                    {
                        "type": "mac_recording_empty",
                        "conv_id": conv_id,
                    }
                )
                return web.json_response(
                    {"success": False, "transcript": "", "error": "No speech detected"}
                )

        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_stop_mac_recording(self, request: web.Request) -> web.Response:
        """Immediately stop any active Mac audio recording."""
        recorder = getattr(self, "_active_mac_recorder", None)
        if recorder:
            try:
                recorder.stop()
            except Exception:
                pass
        return web.json_response({"success": True})

    async def handle_qr(self, request: web.Request) -> web.Response:
        from voicefi.companion.relay_client import RelaySessionCredentials

        creds = RelaySessionCredentials.load_or_create()
        cloud_url = creds.get_pairing_url("https://companion.voicefi.app")

        urls = get_companion_urls(self.port)
        active_tunnel = get_active_tunnel_url()
        if active_tunnel:
            urls["tunnel_url"] = active_tunnel
        urls["cloud_relay_url"] = cloud_url
        urls["universal_url"] = cloud_url

        # Default preferred pairing URL to Cloud Relay for universal 5G / remote everywhere access
        preferred_url = (
            cloud_url
            or active_tunnel
            or urls.get("ip_url")
            or urls.get("mdns_url")
            or f"http://127.0.0.1:{self.port}"
        )
        qr_b64 = generate_qr_base64_png(preferred_url)
        return web.json_response(
            {
                "urls": urls,
                "cloud_relay_url": cloud_url,
                "active_tunnel_url": active_tunnel,
                "preferred_url": preferred_url,
                "qr_data_uri": qr_b64,
            }
        )

    async def handle_tunnel_status(self, request: web.Request) -> web.Response:
        active_tunnel = get_active_tunnel_url()
        return web.json_response(
            {
                "active": bool(active_tunnel),
                "tunnel_url": active_tunnel,
            }
        )

    async def handle_tunnel_start(self, request: web.Request) -> web.Response:
        import asyncio

        tunnel_url = get_active_tunnel_url()
        if not tunnel_url:
            tunnel_url = await asyncio.to_thread(start_cloudflared_tunnel, self.port)

        if tunnel_url:
            urls = get_companion_urls(self.port)
            urls["tunnel_url"] = tunnel_url
            qr_b64 = generate_qr_base64_png(tunnel_url)
            return web.json_response(
                {
                    "status": "success",
                    "tunnel_url": tunnel_url,
                    "urls": urls,
                    "qr_data_uri": qr_b64,
                }
            )
        return web.json_response(
            {
                "status": "error",
                "message": "Could not create Cloudflare Tunnel. Verify cloudflared is installed.",
            },
            status=500,
        )

    def start_ambient(self, source: str = "mic") -> bool:
        """Start non-blocking ambient audio listener and wire WebSocket event broadcasts."""
        if self._ambient_stream and self._ambient_stream.is_running:
            return True

        if not self._ambient_dispatcher:
            self._ambient_dispatcher = ProactiveDispatcher()

        def _on_energy(energy: float, noise_floor: float, is_speech: bool):
            self.broadcast_event(
                {
                    "type": "ambient_energy",
                    "energy": energy,
                    "noise_floor": noise_floor,
                    "is_speech": is_speech,
                    "timestamp": time.time(),
                }
            )

        def _on_state_change(state: str):
            self.broadcast_event(
                {
                    "type": "ambient_state",
                    "state": state,
                    "timestamp": time.time(),
                }
            )

        def _on_utterance_progress(duration: float):
            self.broadcast_event(
                {
                    "type": "ambient_utterance_progress",
                    "duration": duration,
                    "timestamp": time.time(),
                }
            )

        from voicefi.stt.whisper_local import WhisperLocalSTT

        fast_stream_stt = WhisperLocalSTT(model_size="tiny.en")
        final_stt = get_stt_engine(self.config)
        _last_interim_text = [""]
        _interim_lock = threading.Lock()

        def _on_interim_audio(audio_data: np.ndarray, sample_rate: int):
            def _async_worker():
                if not _interim_lock.acquire(blocking=False):
                    return
                try:
                    partial = fast_stream_stt.transcribe(audio_data, sample_rate=sample_rate)
                    if partial and partial.strip():
                        try:
                            from voicefi.tts.normalizer import collapse_repetitive_artifacts

                            partial = collapse_repetitive_artifacts(partial)
                        except Exception:
                            pass
                    if partial and partial.strip() and partial.strip() != _last_interim_text[0]:
                        _last_interim_text[0] = partial.strip()
                        print(f'[CompanionServer] ✍️ Streaming Live: "{partial.strip()}"')
                        self.broadcast_event(
                            {
                                "type": "interim_transcript",
                                "text": partial.strip(),
                                "is_final": False,
                                "timestamp": time.time(),
                            }
                        )
                except Exception:
                    pass
                finally:
                    _interim_lock.release()

            threading.Thread(target=_async_worker, daemon=True).start()

        def _on_utterance(audio_data, sample_rate: int):
            _last_interim_text[0] = ""
            try:
                text = final_stt.transcribe(audio_data, sample_rate=sample_rate)
                if text and text.strip():
                    try:
                        from voicefi.tts.normalizer import collapse_repetitive_artifacts

                        text = collapse_repetitive_artifacts(text)
                    except Exception:
                        pass
                if text and text.strip():
                    from voicefi.audio.echo_canceller import is_acoustic_echo

                    if is_acoustic_echo(text.strip()):
                        print(f'[CompanionServer] 🛡️ Filtered ambient self-echo: "{text.strip()}"')
                        return
                    print(f'[CompanionServer] 🎙️ Transcribed speech: "{text.strip()}"')
                    task = (
                        self._ambient_dispatcher.process_utterance(text)
                        if self._ambient_dispatcher
                        else None
                    )
                    self.broadcast_event(
                        {
                            "type": "transcript",
                            "text": text,
                            "is_final": True,
                            "timestamp": time.time(),
                            "task_id": task.id if task else None,
                        }
                    )

                    if task:
                        self.broadcast_event(
                            {
                                "type": "ambient_task_created",
                                "task": {
                                    "id": task.id,
                                    "category": task.category.value,
                                    "summary": task.summary,
                                    "action_prompt": task.action_prompt,
                                    "suggested_workspace": task.suggested_workspace,
                                    "status": task.status,
                                    "created_at": task.created_at,
                                },
                                "timestamp": time.time(),
                            }
                        )
            except Exception as e:
                print(f"[CompanionServer] Error processing ambient utterance: {e}")

        self._ambient_stream = AmbientAudioStream(
            sample_rate=self.config.vad.sample_rate,
            energy_threshold=self.config.ambient.energy_threshold,
            silence_duration=0.55,
            max_utterance_duration=self.config.ambient.max_utterance_seconds,
            on_utterance=_on_utterance,
            on_energy=_on_energy,
            on_state_change=_on_state_change,
            on_utterance_progress=_on_utterance_progress,
            on_interim_audio=_on_interim_audio,
        )
        self._ambient_stream.start()
        self.broadcast_event(
            {
                "type": "ambient_state",
                "state": "listening",
                "timestamp": time.time(),
            }
        )
        return True

    def stop_ambient(self):
        """Stop ambient listener stream."""
        if self._ambient_stream:
            self._ambient_stream.stop()
            self._ambient_stream = None
        self.broadcast_event(
            {
                "type": "ambient_state",
                "state": "stopped",
                "timestamp": time.time(),
            }
        )

    def start_memo_session(self, target_duration: float = 180.0, title: str = "Voice Memo") -> str:
        """Start a background voice memo buffer session with real-time WebSocket telemetry."""
        memo_id = f"memo_{int(time.time())}_{str(uuid.uuid4())[:4]}"
        self._active_memo_id = memo_id

        self._memo_recorder = MemoBufferRecorder(
            target_duration_seconds=target_duration,
            sample_rate=self.config.vad.sample_rate,
            energy_threshold=self.config.memo.energy_threshold,
            auto_extend_seconds=self.config.memo.auto_extend_seconds,
        )

        def _recorder_worker():
            def _on_tick(elapsed: float, remaining: float, energy: float):
                self.broadcast_event(
                    {
                        "type": "memo_tick",
                        "memo_id": memo_id,
                        "elapsed": elapsed,
                        "remaining": remaining,
                        "total": elapsed + remaining,
                        "energy": energy,
                        "timestamp": time.time(),
                    }
                )

            def _on_state_change(state: str):
                self.broadcast_event(
                    {
                        "type": "memo_state",
                        "memo_id": memo_id,
                        "state": state,
                        "timestamp": time.time(),
                    }
                )

            def _on_extension_prompt():
                self.broadcast_event(
                    {
                        "type": "memo_extension_prompt",
                        "memo_id": memo_id,
                        "timestamp": time.time(),
                    }
                )

            self.broadcast_event(
                {
                    "type": "memo_state",
                    "memo_id": memo_id,
                    "state": "recording",
                    "timestamp": time.time(),
                }
            )

            try:
                audio_arr, wav_path, actual_duration = self._memo_recorder.record_memo_session(
                    interactive=False,
                    on_tick=_on_tick,
                    on_state_change=_on_state_change,
                    on_extension_prompt=_on_extension_prompt,
                )

                self.broadcast_event(
                    {
                        "type": "memo_state",
                        "memo_id": memo_id,
                        "state": "transcribing",
                        "timestamp": time.time(),
                    }
                )

                stt = get_stt_engine(self.config)
                raw_transcript = ""
                try:
                    raw_transcript = stt.transcribe(wav_path)
                except Exception as ex:
                    print(f"[CompanionServer] Memo STT error: {ex}")

                self.broadcast_event(
                    {
                        "type": "memo_transcript_chunk",
                        "memo_id": memo_id,
                        "text": raw_transcript,
                        "cumulative_text": raw_transcript,
                        "timestamp": time.time(),
                    }
                )

                if not raw_transcript.strip():
                    self.broadcast_event(
                        {
                            "type": "memo_state",
                            "memo_id": memo_id,
                            "state": "empty",
                            "timestamp": time.time(),
                        }
                    )
                    return

                self.broadcast_event(
                    {
                        "type": "memo_state",
                        "memo_id": memo_id,
                        "state": "formatting",
                        "timestamp": time.time(),
                    }
                )

                recording = MemoRecording(
                    id=memo_id,
                    title=title,
                    duration_seconds=actual_duration,
                    target_duration_seconds=target_duration,
                    audio_path=str(wav_path),
                    raw_transcript=raw_transcript,
                    word_count=len(raw_transcript.split()),
                )

                cleaner = MemoCleaner(self.config)
                cleaned_memo = cleaner.process(
                    raw_speech=raw_transcript,
                    memo_id=memo_id,
                    custom_title=title if title != "Voice Memo" else None,
                    duration_seconds=actual_duration,
                )
                recording.title = cleaned_memo.title

                self._memo_store.save_memo(recording, cleaned_memo)

                self.broadcast_event(
                    {
                        "type": "memo_synthesis_complete",
                        "memo_id": memo_id,
                        "title": cleaned_memo.title,
                        "cleaned_transcript": cleaned_memo.cleaned_transcript,
                        "raw_transcript": cleaned_memo.raw_transcript,
                        "plan_markdown": cleaned_memo.to_markdown(),
                        "timestamp": time.time(),
                    }
                )
                self.broadcast_event(
                    {
                        "type": "memo_state",
                        "memo_id": memo_id,
                        "state": "completed",
                        "timestamp": time.time(),
                    }
                )
            except Exception as e:
                print(f"[CompanionServer] Memo recording error: {e}")
                self.broadcast_event(
                    {
                        "type": "memo_state",
                        "memo_id": memo_id,
                        "state": "error",
                        "error": str(e),
                        "timestamp": time.time(),
                    }
                )
            finally:
                self._memo_recorder = None
                self._active_memo_id = None

        self._memo_thread = threading.Thread(
            target=_recorder_worker, daemon=True, name="MemoRecorderWorker"
        )
        self._memo_thread.start()
        return memo_id

    def extend_memo(self, seconds: float):
        """Extend active memo recording duration."""
        if self._memo_recorder:
            self._memo_recorder.extend(seconds)

    def pause_memo(self) -> bool:
        """Toggle pause state for active memo recording."""
        if self._memo_recorder:
            return self._memo_recorder.toggle_pause()
        return False

    def stop_memo(self):
        """Stop active memo recording and begin synthesis."""
        if self._memo_recorder:
            self._memo_recorder.finish()

    def _start_watcher_thread(self):
        self._watcher_running = True
        for p in get_recent_transcript_paths(limit=5):
            self._processed_steps[str(p)] = self._get_highest_step_index(p)
        for p in find_recent_claude_sessions(limit=5):
            self._processed_steps[str(p)] = self._get_highest_claude_line_index(p)
        for p in find_recent_codex_sessions(limit=5):
            self._processed_steps[str(p)] = self._get_highest_codex_line_index(p)

        def _loop():
            while self._watcher_running:
                try:
                    for p in get_recent_transcript_paths(limit=3):
                        self._check_transcript_turn(p)
                    for p in find_recent_claude_sessions(limit=3):
                        self._check_claude_session_turn(p)
                    for p in find_recent_codex_sessions(limit=3):
                        self._check_codex_session_turn(p)
                except Exception:
                    pass
                time.sleep(0.5)

        self._watcher_thread = threading.Thread(target=_loop, daemon=True)
        self._watcher_thread.start()

    def _get_highest_step_index(self, path: Path) -> int:
        highest = -1
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                        idx = step.get("step_index", -1)
                        if idx > highest:
                            highest = idx
                    except Exception:
                        pass
        except Exception:
            pass
        return highest

    def _get_highest_claude_line_index(self, path: Path) -> int:
        count = -1
        try:
            with open(path, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    if line.strip():
                        count = idx
        except Exception:
            pass
        return count

    def _check_transcript_turn(self, path: Path):
        p_str = str(path)
        last_proc = self._processed_steps.get(p_str, -1)
        new_steps = []
        highest_idx = last_proc

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                        idx = step.get("step_index", -1)
                        if idx > last_proc:
                            new_steps.append(step)
                        if idx > highest_idx:
                            highest_idx = idx
                    except Exception:
                        continue
        except Exception:
            return

        if not new_steps or highest_idx <= last_proc:
            return

        conv_info = self.tracker.parse_conversation(path)
        cid = conv_info.id if conv_info else path.parent.parent.parent.name
        self._processed_steps[p_str] = highest_idx

        for step in new_steps:
            stype = step.get("type", "")
            source = step.get("source", "")
            content = step.get("content", "")
            tool_calls = step.get("tool_calls", [])
            idx = step.get("step_index", highest_idx)

            if (
                stype == "PLANNER_RESPONSE"
                and source == "MODEL"
                and step.get("status") == "DONE"
                and not tool_calls
                and content
            ):
                role = step.get("role") or step.get("agent_role") or "antigravity"
                fresh_cfg = self.config
                try:
                    from voicefi.config import load_config

                    fresh_cfg = load_config()
                except Exception:
                    pass
                max_words = (
                    getattr(getattr(fresh_cfg, "antigravity", None), "max_spoken_words", 300) or 300
                )
                summary = clean_markdown_for_speech(content, max_words=max_words)
                turn_sig = f"{cid}:{summary[:35]}"
                claimed_origin = get_claimed_turn_origin(cid, turn_sig, step_index=idx)
                if claimed_origin:
                    origin_tag = claimed_origin
                else:
                    origin_tag = "mobile" if peek_mobile_turn_origin(cid) else "desktop"
                delivery_info = get_turn_delivery_info(cid, turn_sig, step_index=idx)
                delivered_via = delivery_info.get("delivered_via", "otherwise")
                spoken_on_mac = delivery_info.get("spoken_on_mac", False)
                self.broadcast_turn_completion(
                    summary=summary,
                    conv_id=cid,
                    agent_role=str(role),
                    full_response=content,
                    origin=origin_tag,
                    delivered_via=delivered_via,
                    spoken_on_mac=spoken_on_mac,
                    step_index=idx,
                )
            elif tool_calls:
                for tc in tool_calls:
                    t_desc, t_tag = format_tool_details(tc)
                    t_name = tc.get("name") or tc.get("tool_name") or "tool"
                    self.broadcast_event(
                        {
                            "type": "agent_working_step",
                            "conv_id": cid,
                            "step_index": idx,
                            "tool_name": t_name,
                            "summary": t_desc,
                            "action": t_tag,
                            "status": "running",
                            "timestamp": time.time(),
                        }
                    )
            elif step.get("thinking"):
                from voicefi.integrations.watcher import extract_thought_summary

                t_summary = extract_thought_summary(str(step.get("thinking", "")))
                self.broadcast_event(
                    {
                        "type": "agent_thinking_step",
                        "conv_id": cid,
                        "step_index": idx,
                        "detail": t_summary or "Reasoning...",
                        "timestamp": time.time(),
                    }
                )
            elif stype == "GENERIC" and content:
                from voicefi.integrations.tool_formatter import extract_log_summary

                l_summary = extract_log_summary(str(content))
                if l_summary:
                    self.broadcast_event(
                        {
                            "type": "agent_working_step",
                            "conv_id": cid,
                            "step_index": idx,
                            "tool_name": "command",
                            "summary": l_summary,
                            "action": "Ran Command",
                            "status": "completed",
                            "timestamp": time.time(),
                        }
                    )
            else:
                self.broadcast_event(
                    {
                        "type": "conversation_updated",
                        "conv_id": cid,
                        "step_index": idx,
                        "step_type": stype,
                        "timestamp": time.time(),
                    }
                )

    def _check_claude_session_turn(self, path: Path):
        p_str = str(path)
        last_proc = self._processed_steps.get(p_str, -1)
        new_lines = []
        highest_idx = last_proc

        try:
            with open(path, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    if idx > last_proc:
                        try:
                            obj = json.loads(line)
                            new_lines.append((idx, obj))
                        except Exception:
                            pass
                    if idx > highest_idx:
                        highest_idx = idx
        except Exception:
            return

        if not new_lines or highest_idx <= last_proc:
            return

        self._processed_steps[p_str] = highest_idx
        cid = f"claude_{path.stem}"

        for idx, obj in new_lines:
            t = obj.get("type")
            if t == "assistant":
                msg = obj.get("message", {})
                content = msg.get("content", [])
                text_parts = []
                tool_calls = []
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif block.get("type") == "tool_use":
                                tool_calls.append(block)
                elif isinstance(content, str):
                    text_parts.append(content)

                if text_parts and not tool_calls:
                    full_resp = "\n\n".join(text_parts).strip()
                    summary = clean_markdown_for_speech(
                        full_resp, max_words=getattr(self.config.claude, "max_spoken_words", 60)
                    )
                    turn_sig = f"{cid}:{summary[:35]}"
                    claimed_origin = get_claimed_turn_origin(
                        cid, turn_sig
                    ) or get_claimed_turn_origin(path.stem, turn_sig)
                    if claimed_origin:
                        origin_tag = claimed_origin
                    else:
                        origin_tag = (
                            "mobile"
                            if (peek_mobile_turn_origin(cid) or peek_mobile_turn_origin(path.stem))
                            else "desktop"
                        )
                    delivery_info = get_turn_delivery_info(cid, turn_sig)
                    if not delivery_info.get("delivered_via_hook"):
                        alt_info = get_turn_delivery_info(path.stem, turn_sig)
                        if alt_info.get("delivered_via_hook"):
                            delivery_info = alt_info
                    delivered_via = delivery_info.get("delivered_via", "otherwise")
                    spoken_on_mac = delivery_info.get("spoken_on_mac", False)

                    self.broadcast_turn_completion(
                        summary=summary,
                        conv_id=cid,
                        agent_role="claude",
                        full_response=full_resp,
                        origin=origin_tag,
                        delivered_via=delivered_via,
                        spoken_on_mac=spoken_on_mac,
                    )
                elif tool_calls:
                    for tc in tool_calls:
                        t_desc, t_tag = format_tool_details(tc)
                        t_name = tc.get("name", "tool")
                        self.broadcast_event(
                            {
                                "type": "agent_working_step",
                                "conv_id": cid,
                                "step_index": idx,
                                "agent_role": "claude",
                                "tool_name": t_name,
                                "summary": t_desc,
                                "action": t_tag,
                                "status": "running",
                                "timestamp": time.time(),
                            }
                        )
            elif t == "attachment":
                att = obj.get("attachment", {})
                if att.get("type") == "hook_success":
                    self.broadcast_event(
                        {
                            "type": "conversation_updated",
                            "conv_id": cid,
                            "step_index": idx,
                            "step_type": "hook_success",
                            "timestamp": time.time(),
                        }
                    )
            elif t == "user":
                self.broadcast_event(
                    {
                        "type": "conversation_updated",
                        "conv_id": cid,
                        "step_index": idx,
                        "step_type": "user",
                        "timestamp": time.time(),
                    }
                )

    def _get_highest_codex_line_index(self, path: Path) -> int:
        highest = -1
        try:
            with open(path, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    if line.strip():
                        highest = idx
        except Exception:
            pass
        return highest

    def _check_codex_session_turn(self, path: Path):
        p_str = str(path)
        last_proc = self._processed_steps.get(p_str, -1)
        new_lines = []
        highest_idx = last_proc

        try:
            with open(path, "r", encoding="utf-8") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    if idx > last_proc:
                        try:
                            obj = json.loads(line)
                            new_lines.append((idx, obj))
                        except Exception:
                            pass
                    if idx > highest_idx:
                        highest_idx = idx
        except Exception:
            return

        if not new_lines or highest_idx <= last_proc:
            return

        self._processed_steps[p_str] = highest_idx

        # Extract UUID
        m = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            path.stem,
            re.IGNORECASE,
        )
        session_id = m.group(1) if m else path.stem
        cid = f"codex_{session_id}" if not session_id.startswith("codex_") else session_id

        for idx, obj in new_lines:
            t = obj.get("type")
            pld = obj.get("payload", {})
            if not isinstance(pld, dict):
                continue
            pt = pld.get("type")

            if pt == "custom_tool_call":
                t_name = pld.get("name", "tool")
                raw_inp = pld.get("input", "")
                summary = f"{t_name} {str(raw_inp)[:40]}".strip()
                self.broadcast_event(
                    {
                        "type": "agent_working_step",
                        "conv_id": cid,
                        "step_index": idx,
                        "agent_role": "codex",
                        "tool_name": t_name,
                        "summary": summary,
                        "action": t_name,
                        "status": "running",
                        "timestamp": time.time(),
                    }
                )
            elif pt == "custom_tool_call_output":
                self.broadcast_event(
                    {
                        "type": "conversation_updated",
                        "conv_id": cid,
                        "step_index": idx,
                        "step_type": "tool_output",
                        "timestamp": time.time(),
                    }
                )
            elif pt == "task_complete" or (
                pt == "item_completed" and pld.get("item", {}).get("type") == "AgentMessage"
            ):
                agent_msg = ""
                if pt == "task_complete":
                    agent_msg = str(pld.get("last_agent_message") or "")
                else:
                    item = pld.get("item", {})
                    parts = [
                        c.get("text", "")
                        for c in item.get("content", [])
                        if isinstance(c, dict) and c.get("text")
                    ]
                    agent_msg = " ".join(parts).strip()

                if agent_msg:
                    summary = clean_markdown_for_speech(
                        agent_msg,
                        max_words=getattr(
                            getattr(self.config, "codex", None), "max_spoken_words", 60
                        ),
                    )
                    turn_sig = f"{cid}:{summary[:35]}"
                    claimed_origin = get_claimed_turn_origin(
                        cid, turn_sig
                    ) or get_claimed_turn_origin(session_id, turn_sig)
                    if claimed_origin:
                        origin_tag = claimed_origin
                    else:
                        origin_tag = (
                            "mobile"
                            if (peek_mobile_turn_origin(cid) or peek_mobile_turn_origin(session_id))
                            else "desktop"
                        )
                    delivery_info = get_turn_delivery_info(cid, turn_sig)
                    if not delivery_info.get("delivered_via_hook"):
                        alt_info = get_turn_delivery_info(session_id, turn_sig)
                        if alt_info.get("delivered_via_hook"):
                            delivery_info = alt_info
                        else:
                            # If not already claimed by a hook, trigger Codex stop hook asynchronously
                            def _run_codex_hook():
                                try:
                                    from voicefi.integrations.codex import handle_codex_stop_hook

                                    hook_payload = {
                                        "thread_id": session_id,
                                        "conversationId": cid,
                                        "session_path": str(path),
                                        "last-assistant-message": agent_msg,
                                        "agent": "codex",
                                    }
                                    handle_codex_stop_hook(hook_payload, self.config)
                                except Exception as hook_err:
                                    logger.error(
                                        f"[CompanionServer] Error in watcher Codex stop hook: {hook_err}"
                                    )

                            threading.Thread(
                                target=_run_codex_hook,
                                daemon=True,
                                name=f"CodexHookWatcher-{cid[:16]}",
                            ).start()

                    delivered_via = delivery_info.get("delivered_via", "otherwise")
                    spoken_on_mac = delivery_info.get("spoken_on_mac", False)

                    self.broadcast_turn_completion(
                        summary=summary,
                        conv_id=cid,
                        agent_role="codex",
                        full_response=agent_msg,
                        origin=origin_tag,
                        delivered_via=delivered_via,
                        spoken_on_mac=spoken_on_mac,
                    )
            elif pt in ("user_message", "message") and (
                pt == "user_message" or pld.get("role") == "user"
            ):
                self.broadcast_event(
                    {
                        "type": "conversation_updated",
                        "conv_id": cid,
                        "step_index": idx,
                        "step_type": "user",
                        "timestamp": time.time(),
                    }
                )


def ensure_ssl_context() -> Optional[object]:
    """Ensure local self-signed certificate exists and return configured SSLContext."""
    try:
        import ssl
        import subprocess

        voicefi_dir = Path.home() / ".voicefi"
        voicefi_dir.mkdir(parents=True, exist_ok=True)
        cert_path = voicefi_dir / "cert.pem"
        key_path = voicefi_dir / "key.pem"

        if not cert_path.is_file() or not key_path.is_file():
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(key_path),
                    "-out",
                    str(cert_path),
                    "-days",
                    "365",
                    "-nodes",
                    "-subj",
                    "/CN=VoiceFi",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

        if cert_path.is_file() and key_path.is_file():
            ssl_ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_ctx.load_cert_chain(str(cert_path), str(key_path))
            return ssl_ctx
    except Exception as e:
        print(f"[CompanionServer] SSL setup warning: {e}")
    return None


_ACTIVE_TUNNEL_PROC: Optional[Any] = None
_ACTIVE_TUNNEL_URL: Optional[str] = None


def get_active_tunnel_url() -> Optional[str]:
    """Return currently active Cloudflare Quick Tunnel URL if running."""
    global _ACTIVE_TUNNEL_PROC, _ACTIVE_TUNNEL_URL
    if _ACTIVE_TUNNEL_PROC is not None:
        if _ACTIVE_TUNNEL_PROC.poll() is None and _ACTIVE_TUNNEL_URL:
            return _ACTIVE_TUNNEL_URL
        else:
            _ACTIVE_TUNNEL_PROC = None
            _ACTIVE_TUNNEL_URL = None

    # Check persisted file and active process
    tunnel_file = Path.home() / ".voicefi" / "tunnel_url.txt"
    if tunnel_file.is_file():
        try:
            url = tunnel_file.read_text(encoding="utf-8").strip()
            if url.startswith("https://") and "trycloudflare.com" in url:
                import subprocess

                res = subprocess.run(
                    ["pgrep", "-f", "cloudflared tunnel"], capture_output=True, text=True
                )
                if res.returncode == 0 and res.stdout.strip():
                    _ACTIVE_TUNNEL_URL = url
                    return url
                else:
                    tunnel_file.unlink(missing_ok=True)
        except Exception:
            pass
    _ACTIVE_TUNNEL_URL = None
    return None


def start_cloudflared_tunnel(port: int = 5141) -> Optional[str]:
    """Start an ephemeral Cloudflare Quick Tunnel and return the trusted public HTTPS URL."""
    global _ACTIVE_TUNNEL_PROC, _ACTIVE_TUNNEL_URL
    existing = get_active_tunnel_url()
    if existing:
        return existing

    try:
        import subprocess
        import re
        import time
        import shutil
        import threading

        binary = (
            shutil.which("cloudflared")
            or (Path("/opt/homebrew/bin/cloudflared").is_file() and "/opt/homebrew/bin/cloudflared")
            or (Path("/usr/local/bin/cloudflared").is_file() and "/usr/local/bin/cloudflared")
            or (
                (Path.home() / ".local/bin/cloudflared").is_file()
                and str(Path.home() / ".local/bin/cloudflared")
            )
        )
        if not binary:
            return None

        # Kill stale cloudflared instances
        subprocess.run(["pkill", "-f", "cloudflared tunnel"], check=False)
        time.sleep(0.5)

        cmd = [str(binary), "tunnel", "--url", f"http://127.0.0.1:{port}"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        _ACTIVE_TUNNEL_PROC = proc

        start_time = time.time()
        found_url = None
        while time.time() - start_time < 12:
            line = proc.stdout.readline()
            if not line:
                break
            match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
            if match:
                found_url = match.group(0)
                break

        if found_url:
            _ACTIVE_TUNNEL_URL = found_url
            tunnel_file = Path.home() / ".voicefi" / "tunnel_url.txt"
            tunnel_file.parent.mkdir(parents=True, exist_ok=True)
            tunnel_file.write_text(found_url, encoding="utf-8")

            def _drain():
                global _ACTIVE_TUNNEL_URL, _ACTIVE_TUNNEL_PROC
                while proc.poll() is None:
                    if not proc.stdout.readline():
                        break
                _ACTIVE_TUNNEL_URL = None
                _ACTIVE_TUNNEL_PROC = None
                tunnel_f = Path.home() / ".voicefi" / "tunnel_url.txt"
                if tunnel_f.is_file():
                    try:
                        tunnel_f.unlink(missing_ok=True)
                    except Exception:
                        pass

            threading.Thread(target=_drain, daemon=True).start()
            return found_url
    except Exception as e:
        print(f"[CompanionServer] Tunnel warning: {e}")
    return None


def _is_voicefi_running_on_port(port: int) -> bool:
    """Check if VoiceFi background server is already active on target port."""
    try:
        import urllib.request
        import json

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/status",
            headers={"User-Agent": "VoiceFi-CLI"},
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("status") == "online" or "status" in data
    except Exception:
        pass
    return False


def run_companion_server(
    port: int = 5141,
    host: str = "0.0.0.0",
    print_qr: bool = True,
    open_browser: bool = False,
    open_studio: bool = False,
    start_ambient_stream: bool = False,
    tunnel: bool = False,
    config: Optional[VoiceFiConfig] = None,
    initial_path: Optional[str] = None,
):
    """Start and run the VoiceFi Companion Server with Universal Remote Relay."""
    urls = get_companion_urls(port)
    creds = RelaySessionCredentials.load_or_create()
    universal_url = creds.get_pairing_url("https://companion.voicefi.app")

    tunnel_url = None
    if tunnel:
        print("🌐 Creating trusted Cloudflare Quick Tunnel for zero-warning HTTPS...")
        tunnel_url = start_cloudflared_tunnel(port)
        if tunnel_url:
            urls["tunnel_url"] = tunnel_url
            if print_qr:
                print_qr_code(tunnel_url, title="VoiceFi Mobile (Trusted HTTPS)")
        else:
            if print_qr:
                print_qr_code(universal_url, title="VoiceFi Mobile Companion (5G & Local)")
    else:
        if print_qr:
            print_qr_code(universal_url, title="VoiceFi Mobile Companion (5G & Local)")

    if initial_path:
        base = urls["localhost_url"].rstrip("/")
        path = initial_path if initial_path.startswith("/") else f"/{initial_path}"
        target_url = f"{base}{path}"
    else:
        target_url = urls["studio_localhost_url"] if open_studio else urls["localhost_url"]

    if open_browser:
        import webbrowser

        webbrowser.open(target_url)

    # If VoiceFi background server is already active on this port, start RelayClient and attach
    if _is_voicefi_running_on_port(port):
        relay_client = RelayClient(credentials=creds, local_port=port)
        relay_loop = asyncio.new_event_loop()

        def _run_relay_loop():
            asyncio.set_event_loop(relay_loop)
            relay_loop.run_until_complete(relay_client.start())
            relay_loop.run_forever()

        relay_thread = threading.Thread(target=_run_relay_loop, daemon=True)
        relay_thread.start()

        if tunnel_url:
            print(f"🌐 Trusted Public HTTPS:  {tunnel_url}")
        print(f"🌐 Universal Mobile Link: {universal_url}")
        print(f"✅ Connected to active background VoiceFi server on port {port}.")
        print(f"📱 Studio URL:            {urls['studio_localhost_url']}")
        print(f"📱 Local Pairing URL:     {urls['ip_url']}")
        print("💡 Your mobile companion is ready. Press Ctrl+C to exit.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 Exiting companion view (background server remains active).")
        finally:
            relay_loop.call_soon_threadsafe(relay_loop.stop)
        return

    server = CompanionServer(config=config, port=port, host=host)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server.loop = loop
    server._start_watcher_thread()

    # Start Cloud Relay client in server loop
    relay_client = RelayClient(credentials=creds, local_port=port)
    server.relay_client = relay_client
    loop.run_until_complete(relay_client.start())

    if start_ambient_stream:
        server.start_ambient()

    app_runner = web.AppRunner(server.app)
    loop.run_until_complete(app_runner.setup())

    # HTTP Site (Default, e.g. 5141)
    site_http = web.TCPSite(app_runner, host, port)
    try:
        loop.run_until_complete(site_http.start())
    except OSError as e:
        if e.errno == 48:
            if _is_voicefi_running_on_port(port):
                print(f"✅ Connected to active background VoiceFi server on port {port}.")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    print("\n👋 Exiting companion view.")
                return
            else:
                print(
                    f"⚠️ Port {port} is occupied by another application. Try `vifi clean --all` or specify `--port <number>`."
                )
                return
        raise

    # HTTPS Site (Port + 1, e.g. 5142) with self-signed SSL for secure mobile mic access
    ssl_ctx = ensure_ssl_context()
    https_port = port + 1
    if ssl_ctx:
        try:
            site_https = web.TCPSite(app_runner, host, https_port, ssl_context=ssl_ctx)
            loop.run_until_complete(site_https.start())
            print(f"🔒 Local HTTPS:           {urls['https_ip_url']}")
        except Exception as e:
            print(f"[CompanionServer] HTTPS setup warning: {e}")

    if tunnel_url:
        print(f"🌐 Trusted Public HTTPS:  {tunnel_url}")
    print(f"🚀 VoiceFi running on   http://{host}:{port}")
    print(f"🌐 Cloud Relay URL:       {universal_url}")
    print(f"📱 Studio URL:            {urls['studio_localhost_url']}")
    print(f"📱 Local Pairing URL:     {urls['ip_url']}")
    print("Press Ctrl+C to stop.\n")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\n👋 Stopping companion server...")
    finally:
        server._watcher_running = False
        server.stop_ambient()
        server.stop_memo()
        loop.run_until_complete(app_runner.cleanup())
        loop.close()
