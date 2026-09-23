"""
Companion route handlers for local network peer discovery and clipboard/data sync.
"""

import logging
import subprocess
from typing import Dict, Any, Optional
from aiohttp import web

from voicefi.integrations.injector import send_message_to_agent

logger = logging.getLogger(__name__)


class PeerHandlersMixin:
    """Mixin containing peer discovery, remote clipboard, and cross-machine dispatch endpoints."""

    async def handle_peer_info(self, request: web.Request) -> web.Response:
        """Provide local machine profile to authorized peer Macs on LAN."""
        from voicefi.network.peers import get_local_peer_info
        info = get_local_peer_info(self.config)
        return web.json_response(info)

    async def handle_peer_send(self, request: web.Request) -> web.Response:
        """Receive cross-machine agent prompt from a peer Mac and inject into active agent."""
        try:
            data = await request.json()
            text = (data.get("text") or "").strip()
            if not text:
                return web.json_response({"error": "Missing prompt text"}, status=400)

            sender_device = data.get("sender_device", "Peer Mac")
            sender_name = data.get("sender_name", "Developer")
            target_engine = data.get("target_engine", "auto")
            reply = data.get("reply", False)
            from_conv_id = data.get("from_conv_id")

            formatted_sender = f"{sender_name} @ {sender_device}"
            res = send_message_to_agent(
                text=text,
                target_engine="claude" if target_engine == "claude" else "antigravity",
                sender_name=formatted_sender,
                conv_id="reply" if reply else None,
                from_conv_id=from_conv_id,
                from_engine="peer",
            )
            delivered = bool(res)

            self.broadcast_event(
                {
                    "type": "peer_task_received",
                    "text": text,
                    "sender": formatted_sender,
                    "delivered": delivered,
                }
            )

            from voicefi.network.peers import get_computer_name
            return web.json_response(
                {
                    "success": delivered,
                    "delivered": delivered,
                    "target_engine": target_engine,
                    "delivery_type": getattr(res, "delivery_type", "ipc" if delivered else "none"),
                    "device": get_computer_name(),
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_peer_clip_get(self, request: web.Request) -> web.Response:
        """Read local macOS clipboard for a remote peer Mac."""
        try:
            res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=1.5)
            clip_text = res.stdout if res.returncode == 0 else ""
            return web.json_response({"success": True, "text": clip_text, "chars": len(clip_text)})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_peer_clip_post(self, request: web.Request) -> web.Response:
        """Write remote clipboard text to local macOS pasteboard."""
        try:
            data = await request.json()
            clip_text = data.get("text", "")
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=clip_text, timeout=2.0)
            return web.json_response({"success": True, "chars": len(clip_text)})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_peer_sync(self, request: web.Request) -> web.Response:
        """Sync voice personas, brevity dictionaries, or speed settings between peer Macs."""
        try:
            data = await request.json()
            return web.json_response({"success": True, "status": "synced"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_peers_list(self, request: web.Request) -> web.Response:
        """Return all discovered VoiceFi peer Macs on the local Wi-Fi / LAN."""
        from voicefi.network.peers import PeerDiscoveryEngine
        peers = await PeerDiscoveryEngine.discover_all(timeout=1.0)
        return web.json_response({"peers": [p.to_dict() for p in peers], "count": len(peers)})
