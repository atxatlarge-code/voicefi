"""
VoiceFi Native Cloud Relay Client.
Establishes a persistent outbound WebSocket bridge to the VoiceFi Cloud Relay at voicefi.org
allowing remote mobile phones (Pixel/iPhone) on 5G/external networks to securely pair
and control local AI coding agents with zero router configuration or port forwarding.
"""

import asyncio
import io
import json
import logging
import secrets
import ssl
import string
import time
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, Callable

import aiohttp
import certifi

logger = logging.getLogger("voicefi.relay_client")

DEFAULT_RELAY_URL = "wss://companion.voicefi.app/v1/relay"
DEFAULT_PUBLIC_PWA_URL = "https://companion.voicefi.app"


class RelaySessionCredentials:
    """Stores or generates ephemeral session pairing keys."""

    def __init__(self, session_id: Optional[str] = None, token: Optional[str] = None):
        self.session_id = session_id or f"vifi_{secrets.token_hex(4)}"
        self.token = token or secrets.token_urlsafe(16)
        self.created_at = time.time()

    def get_pairing_url(self, base_url: str = DEFAULT_PUBLIC_PWA_URL) -> str:
        """Construct universal pairing URL with query and hash parameters for full compatibility."""
        clean_base = base_url.rstrip("/")
        return (
            f"{clean_base}/?s={self.session_id}&t={self.token}#s={self.session_id}&t={self.token}"
        )

    def save_to_disk(self, path: Optional[Path] = None) -> None:
        p = path or (Path.home() / ".voicefi" / "relay_session.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": self.session_id,
            "token": self.token,
            "created_at": self.created_at,
        }
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load_or_create(cls, path: Optional[Path] = None) -> "RelaySessionCredentials":
        p = path or (Path.home() / ".voicefi" / "relay_session.json")
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                s_id = data.get("session_id")
                tok = data.get("token")
                if s_id and tok:
                    return cls(session_id=s_id, token=tok)
            except Exception:
                pass
        creds = cls()
        creds.save_to_disk(p)
        return creds


class RelayClient:
    """
    Outbound WebSocket client that connects the local Mac VoiceFi server
    to the global VoiceFi Edge Relay.
    """

    def __init__(
        self,
        credentials: Optional[RelaySessionCredentials] = None,
        relay_url: str = DEFAULT_RELAY_URL,
        local_port: int = 5141,
        on_peer_connected: Optional[Callable[[], None]] = None,
        on_peer_disconnected: Optional[Callable[[], None]] = None,
    ):
        self.credentials = credentials or RelaySessionCredentials.load_or_create()
        self.relay_url = relay_url
        self.local_port = local_port
        self.on_peer_connected = on_peer_connected
        self.on_peer_disconnected = on_peer_disconnected
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.is_running = False
        self.has_peer = False
        self._task: Optional[asyncio.Task] = None

    @property
    def pairing_url(self) -> str:
        return self.credentials.get_pairing_url()

    async def start(self) -> None:
        """Start the persistent relay connection background task."""
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop relay client."""
        self.is_running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session and not self.session.closed:
            await self.session.close()
        if self._task:
            self._task.cancel()

    async def broadcast(self, data: Dict[str, Any]) -> None:
        """Broadcast a message or event payload up to the connected phone."""
        if self.ws and not self.ws.closed:
            try:
                await self.ws.send_str(json.dumps(data))
            except Exception as e:
                logger.debug(f"[RelayClient] broadcast error: {e}")

    async def _run_loop(self) -> None:
        reconnect_delay = 1.0
        while self.is_running:
            try:
                if not self.session or self.session.closed:
                    self.session = aiohttp.ClientSession()

                params = {
                    "session": self.credentials.session_id,
                    "role": "host",
                    "token": self.credentials.token,
                }
                url = f"{self.relay_url}?{urllib.parse.urlencode(params)}"
                ssl_ctx = None
                try:
                    import certifi

                    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
                except Exception:
                    ssl_ctx = ssl.create_default_context()
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE

                async with self.session.ws_connect(
                    url,
                    heartbeat=15.0,
                    ssl=ssl_ctx,
                    headers={"User-Agent": "VoiceFi-Host-Bridge/1.0"},
                ) as ws:
                    self.ws = ws
                    reconnect_delay = 1.0
                    print(
                        f"[RelayClient] 🟢 Connected to VoiceFi Cloud Relay for session: {self.credentials.session_id}",
                        flush=True,
                    )

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_incoming_message(msg.data)
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            pass
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            print(f"[RelayClient] ⚠️ WS closed/error: {msg.type}", flush=True)
                            break

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[RelayClient] ❌ Connection error: {e}", flush=True)

            self.has_peer = False
            if self.is_running:
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 1.5, 10.0)

    async def _handle_incoming_message(self, text: str) -> None:
        """Handle incoming messages and RPC requests from the phone."""
        try:
            payload = json.loads(text)
        except Exception:
            return

        msg_type = payload.get("type")

        if msg_type == "relay_connected":
            self.has_peer = payload.get("has_client", False)
            if self.has_peer and self.on_peer_connected:
                self.on_peer_connected()

        elif msg_type == "peer_connected":
            self.has_peer = True
            logger.info("[RelayClient] 📱 Remote phone connected!")
            if self.on_peer_connected:
                self.on_peer_connected()

        elif msg_type == "peer_disconnected":
            self.has_peer = False
            logger.info("[RelayClient] 📱 Remote phone disconnected")
            if self.on_peer_disconnected:
                self.on_peer_disconnected()

        elif msg_type == "rpc_request":
            # Proxy HTTP request to local daemon
            await self._proxy_rpc_request(payload)

        elif msg_type in ("user_voice_command", "send_prompt"):
            from voicefi.integrations.injector import send_message_to_agent
            from voicefi.integrations.conversations import set_mobile_turn_origin

            text_prompt = payload.get("text", "").strip()
            engine = payload.get("engine")
            conv_id = payload.get("conv_id")
            sender_name = payload.get("sender_name") or "Pixel Remote"
            title = payload.get("title") or f"Message from {sender_name}"
            print(
                f"[RelayClient] 📥 Received voice/text command from phone: '{text_prompt}' (conv: {conv_id})",
                flush=True,
            )
            if text_prompt:
                try:
                    set_mobile_turn_origin(conv_id)
                except Exception:
                    pass
                res = send_message_to_agent(
                    conv_id=conv_id,
                    text=text_prompt,
                    target_engine=engine,
                    sender_name=sender_name,
                    title=title,
                    include_envelope=True,
                )
                print(
                    f"[RelayClient] 🚀 Injected to agent: success={getattr(res, 'success', True)}",
                    flush=True,
                )
                await self.broadcast(
                    {
                        "type": "user_command_injected",
                        "conv_id": conv_id or "active",
                        "success": getattr(res, "success", True),
                        "delivered": getattr(res, "success", True),
                        "text": text_prompt,
                    }
                )

        elif msg_type == "ping":
            await self.broadcast({"type": "pong", "timestamp": time.time()})

    async def _proxy_rpc_request(self, payload: Dict[str, Any]) -> None:
        """Proxy a REST API request to localhost:local_port and return response to phone."""
        req_id = payload.get("id")
        path = payload.get("path", "/api/status")
        method = payload.get("method", "GET").upper()
        body = payload.get("body")
        headers = payload.get("headers", {})

        url = f"http://127.0.0.1:{self.local_port}{path}"

        try:
            if not self.session or self.session.closed:
                self.session = aiohttp.ClientSession()

            req_kwargs = {"headers": headers}
            if body is not None:
                if isinstance(body, str) and (body.startswith("data:") or ";base64," in body):
                    import base64

                    _, b64data = body.split(";base64,", 1) if ";base64," in body else ("", body)
                    req_kwargs["data"] = base64.b64decode(b64data)
                elif isinstance(body, (dict, list)):
                    req_kwargs["json"] = body
                else:
                    req_kwargs["data"] = str(body)

            async with self.session.request(
                method, url, timeout=aiohttp.ClientTimeout(total=10), **req_kwargs
            ) as resp:
                status = resp.status
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    data = await resp.json()
                else:
                    data = await resp.text()

                await self.broadcast(
                    {
                        "type": "rpc_response",
                        "id": req_id,
                        "status": status,
                        "data": data,
                    }
                )
        except Exception as e:
            await self.broadcast(
                {
                    "type": "rpc_response",
                    "id": req_id,
                    "status": 500,
                    "error": str(e),
                }
            )
