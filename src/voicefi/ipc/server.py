"""
VoiceFi Local IPC Daemon Server.
Manages Unix domain socket (/tmp/voicefi.sock) and WebSocket (:8765) listeners,
dispatches inbound STT speech events, broadcasts barge-in interrupt signals,
and handles outbound agent turn completion events with 48 kHz neural persona voice synthesis.
"""

import asyncio
import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

from aiohttp import web, WSMsgType

from voicefi.config import VoiceFiConfig, load_config
from voicefi.ipc.protocol import (
    METHOD_AGENT_EVENT,
    METHOD_PROMPT_DISPATCH,
    METHOD_SIGNAL_INTERRUPT,
    METHOD_VAD_SPEECH,
    EVENT_TURN_COMPLETE,
    EVENT_TURN_INTERRUPTED,
    build_prompt_dispatch_event,
    build_signal_interrupt_event,
    parse_jsonrpc_message,
)
from voicefi.tts import get_tts_engine, stop_all_speech
from voicefi.tts.base import set_cross_process_hud_state

logger = logging.getLogger("voicefi.ipc.server")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[VoiceFi IPC Server] %(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

DEFAULT_SOCKET_PATH = "/tmp/voicefi.sock"
DEFAULT_WS_PORT = 8765
DEFAULT_WS_HOST = "127.0.0.1"


class VoiceFiIPCServer:
    """
    Bidirectional IPC server for the VoiceFi ambient daemon runtime.
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        ws_port: int = DEFAULT_WS_PORT,
        ws_host: str = DEFAULT_WS_HOST,
        enable_ws: bool = True,
        config: Optional[VoiceFiConfig] = None,
        on_agent_event: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.socket_path = socket_path
        self.ws_port = ws_port
        self.ws_host = ws_host
        self.enable_ws = enable_ws
        self.config = config or load_config()
        self.on_agent_event = on_agent_event

        self._unix_server: Optional[asyncio.AbstractServer] = None
        self._ws_app: Optional[web.Application] = None
        self._ws_runner: Optional[web.AppRunner] = None
        self._ws_site: Optional[web.TCPSite] = None

        self._unix_clients: Set[asyncio.StreamWriter] = set()
        self._ws_clients: Set[web.WebSocketResponse] = set()
        self._is_running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def connected_client_count(self) -> int:
        return len(self._unix_clients) + len(self._ws_clients)

    async def start(self):
        """Start both the Unix domain socket server and the fallback WebSocket server."""
        if self._is_running:
            return

        self._loop = asyncio.get_running_loop()
        self._is_running = True

        # 1. Initialize and start Unix domain socket server
        await self._start_unix_server()

        # 2. Initialize and start fallback WebSocket server if enabled
        if self.enable_ws:
            await self._start_ws_server()

        logger.info(
            "🚀 VoiceFi IPC Server listening at %s%s",
            self.socket_path,
            f" and ws://{self.ws_host}:{self.ws_port}" if self.enable_ws else "",
        )

    async def _start_unix_server(self):
        # Remove stale socket file if present
        sock_p = Path(self.socket_path)
        if sock_p.exists():
            try:
                sock_p.unlink()
            except OSError as e:
                logger.warning("Could not unlink existing socket file %s: %s", self.socket_path, e)

        try:
            self._unix_server = await asyncio.start_unix_server(
                self._handle_unix_client,
                path=self.socket_path,
            )
            # Set secure socket permissions (read/write for user and group)
            os.chmod(self.socket_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP)
            logger.info("Bound Unix domain socket at %s", self.socket_path)
        except Exception as e:
            logger.error("Failed to bind Unix domain socket at %s: %s", self.socket_path, e)
            if not self.enable_ws:
                raise

    async def _start_ws_server(self):
        try:
            self._ws_app = web.Application()
            self._ws_app.router.add_get("/", self._handle_ws_client)
            self._ws_app.router.add_get("/ws", self._handle_ws_client)
            self._ws_app.router.add_get("/api/status", self._handle_http_status)

            self._ws_runner = web.AppRunner(self._ws_app)
            await self._ws_runner.setup()
            self._ws_site = web.TCPSite(self._ws_runner, host=self.ws_host, port=self.ws_port)
            await self._ws_site.start()
            logger.info("Bound WebSocket server at ws://%s:%d", self.ws_host, self.ws_port)
        except Exception as e:
            logger.warning("Could not bind fallback WebSocket server on port %d: %s", self.ws_port, e)

    async def _handle_http_status(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "server": "voicefi-daemon-ipc",
            "socket_path": self.socket_path,
            "connected_clients": self.connected_client_count,
            "unix_clients": len(self._unix_clients),
            "ws_clients": len(self._ws_clients),
        })

    async def _handle_unix_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._unix_clients.add(writer)
        logger.debug("Unix client connected (total: %d)", len(self._unix_clients))
        try:
            while self._is_running:
                line = await reader.readline()
                if not line:
                    break
                await self._process_raw_message(line, writer=writer)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Unix client stream exception: %s", e)
        finally:
            self._unix_clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.debug("Unix client disconnected (remaining: %d)", len(self._unix_clients))

    async def _handle_ws_client(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_clients.add(ws)
        logger.debug("WebSocket client connected (total: %d)", len(self._ws_clients))

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._process_raw_message(msg.data, ws=ws)
                elif msg.type == WSMsgType.ERROR:
                    logger.debug("WebSocket connection error: %s", ws.exception())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("WebSocket client exception: %s", e)
        finally:
            self._ws_clients.discard(ws)
            logger.debug("WebSocket client disconnected (remaining: %d)", len(self._ws_clients))

        return ws

    async def _process_raw_message(
        self,
        data: Union[str, bytes],
        writer: Optional[asyncio.StreamWriter] = None,
        ws: Optional[web.WebSocketResponse] = None,
    ):
        try:
            payload = parse_jsonrpc_message(data)
        except Exception as e:
            logger.warning("Malformed JSON-RPC message received: %s (raw: %r)", e, data[:100] if data else "")
            err_resp = {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}
            await self._send_to_single_client(err_resp, writer=writer, ws=ws)
            return

        method = payload.get("method")
        msg_id = payload.get("id")
        params = payload.get("params", {})

        if method == METHOD_AGENT_EVENT:
            await self._handle_agent_event(params, msg_id=msg_id, writer=writer, ws=ws)
        elif method == "vifi.ping":
            resp = {"jsonrpc": "2.0", "result": {"pong": True}, "id": msg_id}
            await self._send_to_single_client(resp, writer=writer, ws=ws)
        else:
            logger.debug("Received unhandled method '%s'", method)
            if msg_id is not None:
                resp = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                    "id": msg_id,
                }
                await self._send_to_single_client(resp, writer=writer, ws=ws)

    async def _handle_agent_event(
        self,
        params: Dict[str, Any],
        msg_id: Optional[Union[str, int]] = None,
        writer: Optional[asyncio.StreamWriter] = None,
        ws: Optional[web.WebSocketResponse] = None,
    ):
        event_type = params.get("event_type", EVENT_TURN_COMPLETE)
        agent_name = params.get("agent_name", "Spark")
        persona = params.get("persona", "Viv")
        spoken_summary = params.get("spoken_summary", "")
        status = params.get("status", "success")

        logger.info(
            "📥 Inbound agent event [%s] from %s (persona: %s, status: %s): \"%s\"",
            event_type,
            agent_name,
            persona,
            status,
            spoken_summary[:60] if spoken_summary else "<empty>",
        )

        if self.on_agent_event:
            try:
                res = self.on_agent_event(params)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error("Error in on_agent_event callback: %s", e)

        # Handle speech synthesis for turn_complete
        if event_type == EVENT_TURN_COMPLETE and spoken_summary.strip():
            set_cross_process_hud_state("speaking", text=spoken_summary, agent_name=agent_name)
            
            # Synthesize in background task so socket is not blocked
            asyncio.create_task(self._synthesize_spoken_summary(spoken_summary, persona=persona, agent_name=agent_name))

        elif event_type == EVENT_TURN_INTERRUPTED:
            set_cross_process_hud_state("idle", text="Interrupted", agent_name=agent_name)
            stop_all_speech()

        if msg_id is not None:
            resp = {"jsonrpc": "2.0", "result": {"handled": True, "event_type": event_type}, "id": msg_id}
            await self._send_to_single_client(resp, writer=writer, ws=ws)

    async def _synthesize_spoken_summary(self, summary: str, persona: str = "Viv", agent_name: str = "Spark"):
        """Synthesize and stream audio in 48 kHz / high-quality neural voice."""
        try:
            loop = asyncio.get_running_loop()
            def _speak():
                tts = get_tts_engine(self.config, agent_name=agent_name)
                # If specific persona requested and supported, override
                if hasattr(tts, "persona_name") and persona:
                    tts.persona_name = persona
                tts.stream_speak(summary, block=True)

            await loop.run_in_executor(None, _speak)
        except Exception as e:
            logger.error("TTS synthesis error: %s", e)
        finally:
            set_cross_process_hud_state("done", agent_name=agent_name)

    async def _send_to_single_client(
        self,
        msg: Dict[str, Any],
        writer: Optional[asyncio.StreamWriter] = None,
        ws: Optional[web.WebSocketResponse] = None,
    ):
        raw = (json.dumps(msg) + "\n").encode("utf-8")
        if writer is not None and not writer.is_closing():
            try:
                writer.write(raw)
                await writer.drain()
            except Exception:
                pass
        if ws is not None and not ws.closed:
            try:
                await ws.send_str(json.dumps(msg))
            except Exception:
                pass

    async def broadcast_message(self, message: Dict[str, Any]):
        """Broadcast a JSON-RPC message or notification to all connected clients."""
        raw_bytes = (json.dumps(message) + "\n").encode("utf-8")
        raw_str = json.dumps(message)

        # Broadcast to Unix domain socket clients
        for w in list(self._unix_clients):
            try:
                w.write(raw_bytes)
                await w.drain()
            except Exception:
                self._unix_clients.discard(w)

        # Broadcast to WebSocket clients
        for ws in list(self._ws_clients):
            try:
                if not ws.closed:
                    await ws.send_str(raw_str)
            except Exception:
                self._ws_clients.discard(ws)

    async def broadcast_prompt_dispatch(
        self,
        transcript: str,
        session_id: Optional[str] = None,
        source: str = "whisperkit",
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Broadcast an inbound transcribed speech prompt to all connected agent bridges."""
        event = build_prompt_dispatch_event(
            transcript=transcript,
            session_id=session_id,
            source=source,
            confidence=confidence,
            metadata=metadata,
        )
        logger.info("📢 Broadcasting vifi.prompt.dispatch: \"%s\"", transcript)
        await self.broadcast_message(event)

    async def broadcast_interrupt(
        self,
        reason: str = "speech_detected",
        energy: float = 0.0,
    ):
        """Broadcast an instantaneous mid-turn barge-in interruption signal."""
        event = build_signal_interrupt_event(reason=reason, energy=energy)
        logger.info("⚡ Broadcasting vifi.signal.interrupt (reason: %s, energy: %.4f)", reason, energy)
        await self.broadcast_message(event)

    async def stop(self):
        """Gracefully shut down the server and cleanup socket files."""
        self._is_running = False

        # Close all Unix client connections
        for w in list(self._unix_clients):
            try:
                w.close()
                await w.wait_closed()
            except Exception:
                pass
        self._unix_clients.clear()

        # Close Unix server
        if self._unix_server:
            self._unix_server.close()
            await self._unix_server.wait_closed()
            self._unix_server = None

        # Clean socket file
        sock_p = Path(self.socket_path)
        if sock_p.exists():
            try:
                sock_p.unlink()
            except Exception:
                pass

        # Close WebSocket clients and runner
        for ws in list(self._ws_clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._ws_clients.clear()

        if self._ws_runner:
            await self._ws_runner.cleanup()
            self._ws_runner = None
            self._ws_site = None

        logger.info("VoiceFi IPC Server stopped cleanly.")
