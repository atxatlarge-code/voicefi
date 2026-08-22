"""
Async HTTP & WebSocket Companion Server for Voicegency.
Serves the mobile PWA, manages WebSocket turn synchronization, and proxies voice commands to Antigravity.
"""

import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Set, Dict, Any, Optional

from aiohttp import web, WSMsgType

from voicegency.config import VoicegencyConfig, load_config
from voicegency.integrations.conversations import ConversationTracker, load_session_cookie, save_session_cookie
from voicegency.integrations.injector import send_message_to_antigravity
from voicegency.integrations.antigravity import clean_markdown_for_speech
from voicegency.integrations.watcher import get_recent_transcript_paths
from voicegency.tts import get_tts_engine
from voicegency.stt import get_stt_engine
from voicegency.companion.qr import get_local_ip, get_companion_urls, print_qr_code, generate_qr_base64_png


STATIC_DIR = Path(__file__).resolve().parent / "static"


class CompanionServer:
    """Async web and WebSocket companion hub."""

    def __init__(
        self,
        config: Optional[VoicegencyConfig] = None,
        port: int = 8765,
        host: str = "0.0.0.0",
    ):
        self.config = config or load_config()
        self.port = port
        self.host = host
        self.tracker = ConversationTracker()
        self.active_websockets: Set[web.WebSocketResponse] = set()
        self.app = web.Application(client_max_size=30 * 1024 * 1024)
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_running = False
        self._processed_steps: Dict[str, int] = {}
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/manifest.json", self.handle_manifest)
        self.app.router.add_get("/sw.js", self.handle_sw)
        self.app.router.add_get("/api/icon", self.handle_icon)
        self.app.router.add_get("/api/status", self.handle_status)
        self.app.router.add_get("/api/conversations", self.handle_conversations)
        self.app.router.add_post("/api/switch", self.handle_switch)
        self.app.router.add_post("/api/send", self.handle_send)
        self.app.router.add_post("/api/stt", self.handle_stt)
        self.app.router.add_post("/api/tts", self.handle_tts)
        self.app.router.add_get("/api/qr", self.handle_qr)
        self.app.router.add_get("/ws", self.handle_ws)

    # Static Handlers
    async def handle_index(self, request: web.Request) -> web.Response:
        index_path = STATIC_DIR / "index.html"
        if not index_path.is_file():
            return web.Response(text="Voicegency Companion UI missing.", status=404)
        return web.Response(text=index_path.read_text(encoding="utf-8"), content_type="text/html")

    async def handle_manifest(self, request: web.Request) -> web.Response:
        manifest_path = STATIC_DIR / "manifest.json"
        if not manifest_path.is_file():
            return web.Response(text="{}", content_type="application/json")
        return web.Response(text=manifest_path.read_text(encoding="utf-8"), content_type="application/manifest+json")

    async def handle_sw(self, request: web.Request) -> web.Response:
        sw_path = STATIC_DIR / "sw.js"
        if not sw_path.is_file():
            return web.Response(text="", content_type="application/javascript")
        return web.Response(text=sw_path.read_text(encoding="utf-8"), content_type="application/javascript")

    async def handle_icon(self, request: web.Request) -> web.Response:
        icon_path = Path(__file__).resolve().parent.parent.parent.parent / "assets" / "icon.png"
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
        return web.json_response({
            "status": "online",
            "active_conversation": active_data,
            "connected_clients": len(self.active_websockets),
        })

    async def handle_conversations(self, request: web.Request) -> web.Response:
        convs = self.tracker.get_all_conversations(limit=10)
        active = self.tracker.get_active_or_latest()
        active_id = active.id if active else ""
        return web.json_response({
            "conversations": [
                {
                    "id": c.id,
                    "title": c.title,
                    "status": c.status,
                    "mtime": c.mtime,
                }
                for c in convs
            ],
            "active_id": active_id,
        })

    async def handle_switch(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            conv_id = data.get("conv_id")
            if conv_id:
                self.tracker.set_active_focus(conv_id)
                self.broadcast_event({
                    "type": "conversation_switched",
                    "conv_id": conv_id,
                })
                return web.json_response({"success": True, "active_id": conv_id})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"error": "Missing conv_id"}, status=400)

    async def handle_send(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            text = data.get("text", "").strip()
            conv_id = data.get("conv_id")
            if not text:
                return web.json_response({"error": "Empty text prompt"}, status=400)

            delivered = send_message_to_antigravity(conv_id=conv_id, text=text)
            self.broadcast_event({
                "type": "user_command_injected",
                "conv_id": conv_id or "active",
                "text": text,
                "delivered": delivered,
            })
            return web.json_response({"success": True, "delivered": delivered})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_stt(self, request: web.Request) -> web.Response:
        """Transcribe uploaded audio blob from phone via local Whisper."""
        try:
            reader = await request.multipart()
            field = await reader.next()
            if not field:
                return web.json_response({"error": "No audio file provided"}, status=400)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                temp_path = Path(tmp.name)
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    tmp.write(chunk)

            stt = get_stt_engine(self.config)
            try:
                transcript = stt.transcribe(temp_path)
            finally:
                temp_path.unlink(missing_ok=True)

            return web.json_response({"transcript": transcript})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_tts(self, request: web.Request) -> web.Response:
        """Synthesize text to audio stream for phone playback."""
        try:
            data = await request.json()
            text = data.get("text", "").strip()
            if not text:
                return web.Response(text="Empty text", status=400)

            tts = get_tts_engine(self.config)
            temp_out = Path(tempfile.gettempdir()) / f"vg_tts_{int(time.time()*1000)}.mp3"

            # Check if engine has synthesis to file
            if hasattr(tts, "synthesize_to_file"):
                await tts.synthesize_to_file(text, temp_out)
            elif hasattr(tts, "speak_to_file"):
                tts.speak_to_file(text, temp_out)
            else:
                # Fallback mac say to wav/aiff
                temp_out = temp_out.with_suffix(".aiff")
                os.system(f'say -o "{temp_out}" "{text}"')

            if temp_out.is_file():
                audio_bytes = temp_out.read_bytes()
                temp_out.unlink(missing_ok=True)
                content_type = "audio/mpeg" if temp_out.suffix == ".mp3" else "audio/aiff"
                return web.Response(body=audio_bytes, content_type=content_type)
            return web.Response(text="TTS synthesis failed", status=500)
        except Exception as e:
            return web.Response(text=f"TTS error: {e}", status=500)

    async def handle_qr(self, request: web.Request) -> web.Response:
        urls = get_companion_urls(self.port)
        qr_b64 = generate_qr_base64_png(urls["ip_url"])
        return web.json_response({
            "urls": urls,
            "qr_data_uri": qr_b64,
        })

    # WebSocket Real-Time Channel
    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.active_websockets.add(ws)

        # Send initial status handshake
        active = self.tracker.get_active_or_latest()
        await ws.send_str(json.dumps({
            "type": "status_update",
            "active_conversation": {
                "id": active.id if active else "",
                "title": active.title if active else "",
                "status": active.status if active else "idle",
            } if active else None,
        }))

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                        msg_type = payload.get("type")
                        if msg_type == "user_voice_command":
                            text = payload.get("text", "")
                            cid = payload.get("conv_id")
                            if text:
                                send_message_to_antigravity(conv_id=cid, text=text)
                                self.broadcast_event({
                                    "type": "user_command_injected",
                                    "conv_id": cid or "active",
                                    "text": text,
                                    "delivered": True,
                                })
                        elif msg_type == "ping":
                            await ws.send_str(json.dumps({"type": "pong"}))
                    except Exception as e:
                        print(f"[Companion WS] Error processing message: {e}")
                elif msg.type == WSMsgType.ERROR:
                    print(f"[Companion WS] Connection error: {ws.exception()}")
        finally:
            self.active_websockets.discard(ws)

        return ws

    def broadcast_event(self, event_data: Dict[str, Any]):
        """Broadcast event to all connected mobile clients."""
        if not self.active_websockets or not self.loop:
            return

        msg = json.dumps(event_data)
        for ws in list(self.active_websockets):
            if not ws.closed:
                asyncio.run_coroutine_threadsafe(ws.send_str(msg), self.loop)

    def broadcast_turn_completion(self, summary: str, conv_id: str, agent_role: str = "antigravity"):
        """Called when an Antigravity agent completes a turn."""
        self.broadcast_event({
            "type": "agent_turn_completed",
            "summary": summary,
            "conv_id": conv_id,
            "agent_role": agent_role,
            "timestamp": time.time(),
        })

    # Background Watcher Loop
    def _start_watcher_thread(self):
        self._watcher_running = True
        for p in get_recent_transcript_paths(limit=5):
            self._processed_steps[str(p)] = self._get_highest_step_index(p)

        def _loop():
            while self._watcher_running:
                try:
                    for p in get_recent_transcript_paths(limit=3):
                        self._check_transcript_turn(p)
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

    def _check_transcript_turn(self, path: Path):
        p_str = str(path)
        last_proc = self._processed_steps.get(p_str, -1)
        highest_idx = -1
        last_step = None

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                        idx = step.get("step_index", -1)
                        if idx > highest_idx:
                            highest_idx = idx
                        last_step = step
                    except Exception:
                        continue
        except Exception:
            return

        if highest_idx <= last_proc or last_step is None:
            return

        step_type = last_step.get("type", "")
        step_source = last_step.get("source", "")
        content = last_step.get("content", "")
        tool_calls = last_step.get("tool_calls", [])

        if (
            step_type == "PLANNER_RESPONSE"
            and step_source == "MODEL"
            and last_step.get("status") == "DONE"
            and not tool_calls
            and content
        ):
            self._processed_steps[p_str] = highest_idx
            conv_info = self.tracker.parse_conversation(path)
            cid = conv_info.id if conv_info else path.parent.parent.parent.name
            role = last_step.get("role") or last_step.get("agent_role") or "antigravity"
            summary = clean_markdown_for_speech(content, max_words=self.config.antigravity.max_spoken_words)
            self.broadcast_turn_completion(summary=summary, conv_id=cid, agent_role=str(role))
        elif step_type == "USER_INPUT":
            self._processed_steps[p_str] = highest_idx


def run_companion_server(
    port: int = 8765,
    host: str = "0.0.0.0",
    print_qr: bool = True,
    open_browser: bool = False,
    config: Optional[VoicegencyConfig] = None,
):
    """Start and run the Voicegency Companion Server."""
    server = CompanionServer(config=config, port=port, host=host)
    urls = get_companion_urls(port)

    if print_qr:
        print_qr_code(urls["ip_url"])

    if open_browser:
        import webbrowser
        webbrowser.open(urls["localhost_url"])

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    server.loop = loop
    server._start_watcher_thread()

    app_runner = web.AppRunner(server.app)
    loop.run_until_complete(app_runner.setup())
    site = web.TCPSite(app_runner, host, port)
    loop.run_until_complete(site.start())

    print(f"🚀 Voicegency Companion running on http://{host}:{port}")
    print(f"📱 Local Pairing URL: {urls['ip_url']}")
    print("Press Ctrl+C to stop.\n")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\n👋 Stopping companion server...")
    finally:
        server._watcher_running = False
        loop.run_until_complete(app_runner.cleanup())
        loop.close()
