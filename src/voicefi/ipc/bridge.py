"""
VoiceFi Local IPC Bridge Client & Process Lifecycle Manager.
Connects to VoiceFi local daemon (/tmp/voicefi.sock or ws://127.0.0.1:8765),
manages serialized prompt execution queues, handles instant SIGINT/SIGTERM barge-in
cancellation on speech detection, and dispatches outbound turn-completion events.
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import aiohttp

from voicefi.config import VoiceFiConfig, load_config
from voicefi.ipc.protocol import (
    METHOD_AGENT_EVENT,
    METHOD_PROMPT_DISPATCH,
    METHOD_SIGNAL_INTERRUPT,
    METHOD_VAD_SPEECH,
    EVENT_TURN_START,
    EVENT_TOOL_START,
    EVENT_TOOL_COMPLETE,
    EVENT_TURN_COMPLETE,
    EVENT_TURN_ERROR,
    EVENT_TURN_INTERRUPTED,
    build_agent_event,
    parse_jsonrpc_message,
)

logger = logging.getLogger("voicefi.ipc.bridge")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[VoiceFi IPC Bridge] %(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

DEFAULT_SOCKET_PATH = "/tmp/voicefi.sock"
DEFAULT_WS_URL = "ws://127.0.0.1:8765/ws"


class VoiceFiIPCBridge:
    """
    Bridge client that binds Gemini Spark & Antigravity agents to VoiceFi's ambient audio runtime.
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        ws_url: str = DEFAULT_WS_URL,
        agent_name: str = "Spark",
        persona: str = "Viv",
        prompt_runner: Optional[Callable[[str, Optional[str]], Any]] = None,
        config: Optional[VoiceFiConfig] = None,
        auto_reconnect: bool = True,
        reconnect_interval: float = 1.5,
    ):
        self.socket_path = socket_path
        self.ws_url = ws_url
        self.agent_name = agent_name
        self.persona = persona
        self.prompt_runner = prompt_runner
        self.config = config or load_config()
        self.auto_reconnect = auto_reconnect
        self.reconnect_interval = reconnect_interval

        # Connection handles
        self._unix_reader: Optional[asyncio.StreamReader] = None
        self._unix_writer: Optional[asyncio.StreamWriter] = None
        self._ws_session: Optional[aiohttp.ClientSession] = None
        self._ws_conn: Optional[aiohttp.ClientWebSocketResponse] = None
        self._active_transport: Optional[str] = None  # "unix" or "websocket"

        # Lifecycle & Queue
        self._is_running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._turn_queue: asyncio.Queue = asyncio.Queue()
        self._current_task: Optional[asyncio.Task] = None
        self._active_subprocess: Optional[subprocess.Popen] = None
        self._is_turn_active = False

        # Event hooks / callbacks
        self._on_interrupt_callbacks: List[Callable[[], Any]] = []
        self._on_prompt_callbacks: List[Callable[[str, Dict[str, Any]], Any]] = []

    @property
    def is_connected(self) -> bool:
        if self._active_transport == "unix" and self._unix_writer is not None:
            return not self._unix_writer.is_closing()
        if self._active_transport == "websocket" and self._ws_conn is not None:
            return not self._ws_conn.closed
        return False

    @property
    def active_transport(self) -> Optional[str]:
        return self._active_transport

    @property
    def is_turn_active(self) -> bool:
        return self._is_turn_active

    def register_on_interrupt(self, callback: Callable[[], Any]):
        """Register a callback to be invoked immediately upon speech detection or interrupt signal."""
        self._on_interrupt_callbacks.append(callback)

    def register_on_prompt(self, callback: Callable[[str, Dict[str, Any]], Any]):
        """Register a callback for incoming vifi.prompt.dispatch events."""
        self._on_prompt_callbacks.append(callback)

    async def start(self):
        """Start the bridge connection manager and asynchronous turn queue worker."""
        if self._is_running:
            return

        self._loop = asyncio.get_running_loop()
        self._is_running = True

        # Start background queue processor
        asyncio.create_task(self._process_turn_queue())

        # Start persistent connection loop
        asyncio.create_task(self._connection_supervisor())
        logger.info(
            "VoiceFi IPC Bridge started (agent: %s, persona: %s)", self.agent_name, self.persona
        )

    async def _connection_supervisor(self):
        """Maintains active socket connection with automatic fallback and reconnect."""
        while self._is_running:
            if not self.is_connected:
                connected = await self._attempt_connect()
                if not connected and self.auto_reconnect:
                    await asyncio.sleep(self.reconnect_interval)
                    continue

            # Monitor active connection
            try:
                if self._active_transport == "unix":
                    await self._read_unix_stream()
                elif self._active_transport == "websocket":
                    await self._read_ws_stream()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Connection lost: %s", e)
            finally:
                await self._close_transport()

            if self.auto_reconnect and self._is_running:
                await asyncio.sleep(self.reconnect_interval)

    async def _attempt_connect(self) -> bool:
        # 1. Try Unix domain socket first
        sock_p = Path(self.socket_path)
        if sock_p.is_socket() or sock_p.exists():
            try:
                reader, writer = await asyncio.open_unix_connection(self.socket_path)
                self._unix_reader = reader
                self._unix_writer = writer
                self._active_transport = "unix"
                logger.info(
                    "🔗 Connected to VoiceFi daemon via Unix domain socket (%s)", self.socket_path
                )
                return True
            except Exception as e:
                logger.debug("Unix socket connection failed: %s", e)

        # 2. Try WebSocket fallback
        try:
            if self._ws_session is None or self._ws_session.closed:
                self._ws_session = aiohttp.ClientSession()
            ws_timeout = getattr(aiohttp, "ClientWSTimeout", None)
            timeout_arg = ws_timeout(ws_close=1.5) if ws_timeout else 1.5
            ws = await self._ws_session.ws_connect(self.ws_url, timeout=timeout_arg)
            self._ws_conn = ws
            self._active_transport = "websocket"
            logger.info("🔗 Connected to VoiceFi daemon via WebSocket (%s)", self.ws_url)
            return True
        except Exception as e:
            logger.debug("WebSocket fallback connection failed: %s", e)

        return False

    async def _read_unix_stream(self):
        while self._is_running and self._unix_reader and not self._unix_writer.is_closing():
            line = await self._unix_reader.readline()
            if not line:
                break
            await self._handle_inbound_message(line)

    async def _read_ws_stream(self):
        if not self._ws_conn:
            return
        async for msg in self._ws_conn:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._handle_inbound_message(msg.data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                break

    async def _handle_inbound_message(self, data: Union[str, bytes]):
        try:
            payload = parse_jsonrpc_message(data)
        except Exception as e:
            logger.warning("Error parsing inbound JSON-RPC message: %s", e)
            return

        method = payload.get("method")
        params = payload.get("params", {})

        if method == METHOD_PROMPT_DISPATCH:
            transcript = params.get("transcript", "").strip()
            session_id = params.get("session_id")
            if transcript:
                logger.info('🎙️ Received prompt dispatch: "%s"', transcript)
                for cb in self._on_prompt_callbacks:
                    try:
                        res = cb(transcript, params)
                        if asyncio.iscoroutine(res):
                            asyncio.create_task(res)
                    except Exception as e:
                        logger.error("Error in on_prompt callback: %s", e)

                # Enqueue turn
                await self._turn_queue.put((transcript, session_id, params))

        elif method in (METHOD_SIGNAL_INTERRUPT, METHOD_VAD_SPEECH):
            reason = params.get("reason", "speech_detected")
            energy = params.get("energy", 0.0)
            logger.info(
                "⚡ Inbound interrupt signal received (reason: %s, energy: %.4f)", reason, energy
            )
            await self.interrupt_active_turn(reason=reason)

    async def interrupt_active_turn(self, reason: str = "speech_detected"):
        """
        Immediately interrupt and cancel any running agent task or subprocess.
        Issues SIGINT to active process group, escalating to SIGTERM if necessary.
        """
        logger.info("🛑 Executing mid-turn barge-in interruption...")

        # 1. Trigger registered interrupt callbacks
        for cb in self._on_interrupt_callbacks:
            try:
                res = cb()
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error("Error in on_interrupt callback: %s", e)

        # 2. Terminate active child process group
        if self._active_subprocess is not None:
            proc = self._active_subprocess
            self._active_subprocess = None
            try:
                pgid = os.getpgid(proc.pid)
                logger.info("Sending SIGINT to child process group %d (PID: %d)", pgid, proc.pid)
                os.killpg(pgid, signal.SIGINT)

                # Wait up to 350ms before escalating to SIGTERM
                for _ in range(7):
                    if proc.poll() is not None:
                        break
                    await asyncio.sleep(0.05)

                if proc.poll() is None:
                    logger.warning(
                        "Process %d did not terminate on SIGINT; escalating to SIGTERM", proc.pid
                    )
                    os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, OSError) as e:
                logger.debug("Process cleanup exception: %s", e)

        # 3. Cancel active async task
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
            self._current_task = None

        self._is_turn_active = False

        # 4. Notify daemon of turn interruption
        await self.emit_agent_event(
            event_type=EVENT_TURN_INTERRUPTED,
            spoken_summary="Task cancelled due to speech interruption.",
            status="interrupted",
        )

    async def _process_turn_queue(self):
        """Sequential FIFO queue processor for voice execution turns."""
        while self._is_running:
            try:
                transcript, session_id, metadata = await self._turn_queue.get()
                self._is_turn_active = True

                # Notify daemon of turn start
                await self.emit_agent_event(
                    event_type=EVENT_TURN_START,
                    spoken_summary=f"Running task: {transcript[:40]}",
                    status="running",
                )

                if self.prompt_runner:
                    self._current_task = asyncio.create_task(
                        self._execute_runner(transcript, session_id, metadata)
                    )
                    try:
                        await self._current_task
                    except asyncio.CancelledError:
                        logger.info("Turn task was cancelled via interrupt.")
                    except Exception as e:
                        logger.error("Error executing prompt runner: %s", e)
                        await self.emit_agent_event(
                            event_type=EVENT_TURN_ERROR,
                            spoken_summary=f"Encountered an error: {str(e)[:40]}",
                            status="error",
                        )
                else:
                    logger.warning("No prompt_runner registered for bridge; skipping execution.")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Turn queue worker exception: %s", e)
            finally:
                self._is_turn_active = False
                self._current_task = None

    async def _execute_runner(
        self, transcript: str, session_id: Optional[str], metadata: Dict[str, Any]
    ):
        if not self.prompt_runner:
            return

        res = self.prompt_runner(transcript, session_id)
        if asyncio.iscoroutine(res):
            await res

    def run_subprocess_command(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Run a subprocess command inside an isolated Process Group (setsid)
        so that SIGINT/SIGTERM cleanly cancels the whole tree on barge-in.
        """
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=proc_env,
            text=True,
            preexec_fn=os.setsid,  # New process group for clean killpg
        )
        self._active_subprocess = proc

        stdout, stderr = "", ""
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            returncode = -1
        finally:
            self._active_subprocess = None

        return {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": returncode == 0,
        }

    async def emit_agent_event(
        self,
        event_type: str = EVENT_TURN_COMPLETE,
        spoken_summary: str = "",
        status: str = "success",
        details: Optional[Dict[str, Any]] = None,
        agent_name: Optional[str] = None,
        persona: Optional[str] = None,
    ) -> bool:
        """Emit a vifi.agent.event notification payload back to the VoiceFi daemon socket."""
        payload = build_agent_event(
            event_type=event_type,
            agent_name=agent_name or self.agent_name,
            persona=persona or self.persona,
            spoken_summary=spoken_summary,
            status=status,
            details=details,
        )
        return await self.send_message(payload)

    async def send_message(self, message: Dict[str, Any]) -> bool:
        """Send a JSON-RPC message over the active socket transport."""
        raw_bytes = (json.dumps(message) + "\n").encode("utf-8")
        raw_str = json.dumps(message)

        if (
            self._active_transport == "unix"
            and self._unix_writer
            and not self._unix_writer.is_closing()
        ):
            try:
                self._unix_writer.write(raw_bytes)
                await self._unix_writer.drain()
                return True
            except Exception as e:
                logger.warning("Error writing to Unix socket: %s", e)
                await self._close_transport()

        elif self._active_transport == "websocket" and self._ws_conn and not self._ws_conn.closed:
            try:
                await self._ws_conn.send_str(raw_str)
                return True
            except Exception as e:
                logger.warning("Error sending over WebSocket: %s", e)
                await self._close_transport()

        return False

    async def _close_transport(self):
        if self._unix_writer:
            try:
                self._unix_writer.close()
                await self._unix_writer.wait_closed()
            except Exception:
                pass
            self._unix_writer = None
            self._unix_reader = None

        if self._ws_conn:
            try:
                await self._ws_conn.close()
            except Exception:
                pass
            self._ws_conn = None

        self._active_transport = None

    async def stop(self):
        """Shut down the bridge service cleanly."""
        self._is_running = False
        if self._is_turn_active:
            await self.interrupt_active_turn(reason="shutdown")
        await self._close_transport()
        if self._ws_session and not self._ws_session.closed:
            await self._ws_session.close()
        logger.info("VoiceFi IPC Bridge stopped.")
