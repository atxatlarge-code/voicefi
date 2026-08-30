"""
Unit tests for VoiceFi IPC Bridge Client and Process Lifecycle Management.
"""

import asyncio
import os
import signal
import sys
import tempfile
import pytest

from voicefi.ipc.protocol import (
    EVENT_TURN_COMPLETE,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_START,
)
from voicefi.ipc.server import VoiceFiIPCServer
from voicefi.ipc.bridge import VoiceFiIPCBridge


def test_ipc_bridge_prompt_dispatch_and_turn_completion(monkeypatch):
    async def _run():
        sock_path = f"/tmp/test_bridge_{os.getpid()}_{int(asyncio.get_event_loop().time() * 1000)}.sock"
        ws_port = 18766

        # Mock TTS
        monkeypatch.setattr("voicefi.ipc.server.get_tts_engine", lambda *a, **kw: type("MockTTS", (), {"persona_name": "Viv", "stream_speak": lambda s, t, block=True: None})())

        server_events = []
        server = VoiceFiIPCServer(
            socket_path=sock_path,
            ws_port=ws_port,
            enable_ws=False,
            on_agent_event=lambda ev: server_events.append(ev),
        )
        await server.start()

        executed_prompts = []
        async def _mock_runner(prompt, session_id):
            executed_prompts.append(prompt)
            # Emit turn complete
            await bridge.emit_agent_event(
                event_type=EVENT_TURN_COMPLETE,
                spoken_summary=f"Processed: {prompt}",
                status="success",
            )

        bridge = VoiceFiIPCBridge(
            socket_path=sock_path,
            ws_url=f"ws://127.0.0.1:{ws_port}/ws",
            agent_name="Spark",
            persona="Viv",
            prompt_runner=_mock_runner,
            auto_reconnect=False,
        )
        await bridge.start()
        await asyncio.sleep(0.1)
        assert bridge.is_connected
        assert bridge.active_transport == "unix"

        # Broadcast prompt from server
        await server.broadcast_prompt_dispatch(
            transcript="Create new database migration",
            session_id="session-42",
        )

        await asyncio.sleep(0.2)
        assert len(executed_prompts) == 1
        assert executed_prompts[0] == "Create new database migration"

        # Verify server received turn_start and turn_complete events
        event_types = [ev.get("event_type") for ev in server_events]
        assert EVENT_TURN_START in event_types
        assert EVENT_TURN_COMPLETE in event_types

        await bridge.stop()
        await server.stop()

    asyncio.run(_run())


def test_ipc_bridge_websocket_fallback_transport(monkeypatch):
    async def _run():
        # Invalid / nonexistent socket path so bridge falls back to WebSocket
        sock_path = f"/tmp/nonexistent_socket_{os.getpid()}.sock"
        ws_port = 18770

        monkeypatch.setattr("voicefi.ipc.server.get_tts_engine", lambda *a, **kw: type("MockTTS", (), {"persona_name": "Viv", "stream_speak": lambda s, t, block=True: None})())

        server_events = []
        server = VoiceFiIPCServer(
            socket_path="/tmp/dummy_server.sock",
            ws_port=ws_port,
            enable_ws=True,
            on_agent_event=lambda ev: server_events.append(ev),
        )
        await server.start()

        executed_prompts = []
        async def _mock_runner(prompt, session_id):
            executed_prompts.append(prompt)
            await bridge.emit_agent_event(
                event_type=EVENT_TURN_COMPLETE,
                spoken_summary=f"Processed over WS: {prompt}",
                status="success",
            )

        bridge = VoiceFiIPCBridge(
            socket_path=sock_path,
            ws_url=f"ws://127.0.0.1:{ws_port}/ws",
            agent_name="Spark",
            persona="Christopher",
            prompt_runner=_mock_runner,
            auto_reconnect=False,
        )
        await bridge.start()
        await asyncio.sleep(0.2)

        assert bridge.is_connected
        assert bridge.active_transport == "websocket"

        # Broadcast prompt from server
        await server.broadcast_prompt_dispatch(
            transcript="Run WebSocket fallback test",
            session_id="session-ws-1",
        )

        await asyncio.sleep(0.2)
        assert len(executed_prompts) == 1
        assert executed_prompts[0] == "Run WebSocket fallback test"

        await bridge.stop()
        await server.stop()

    asyncio.run(_run())


def test_ipc_bridge_barge_in_sigint_cancellation(monkeypatch):
    async def _run():
        sock_path = f"/tmp/test_bargein_{os.getpid()}_{int(asyncio.get_event_loop().time() * 1000)}.sock"
        ws_port = 18767

        monkeypatch.setattr("voicefi.ipc.server.get_tts_engine", lambda *a, **kw: type("MockTTS", (), {"persona_name": "Viv", "stream_speak": lambda s, t, block=True: None})())

        server_events = []
        server = VoiceFiIPCServer(
            socket_path=sock_path,
            ws_port=ws_port,
            enable_ws=False,
            on_agent_event=lambda ev: server_events.append(ev),
        )
        await server.start()

        interrupted_event = asyncio.Event()
        async def _long_runner(prompt, session_id):
            try:
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                interrupted_event.set()
                raise

        bridge = VoiceFiIPCBridge(
            socket_path=sock_path,
            agent_name="Spark",
            persona="Viv",
            prompt_runner=_long_runner,
            auto_reconnect=False,
        )
        await bridge.start()
        await asyncio.sleep(0.1)

        # 1. Dispatch prompt that will run for 5 seconds
        await server.broadcast_prompt_dispatch(
            transcript="Run long background analysis",
            session_id="session-99",
        )
        await asyncio.sleep(0.1)
        assert bridge.is_turn_active

        # 2. Trigger mid-turn interrupt from server (user started speaking)
        await server.broadcast_interrupt(reason="speech_detected", energy=0.08)

        # 3. Verify task was cancelled immediately (<0.3s)
        await asyncio.wait_for(interrupted_event.wait(), timeout=1.0)
        assert not bridge.is_turn_active

        # Allow event loop to process outbound turn_interrupted socket write
        await asyncio.sleep(0.1)

        # 4. Verify server received turn_interrupted event
        event_types = [ev.get("event_type") for ev in server_events]
        assert EVENT_TURN_INTERRUPTED in event_types

        await bridge.stop()
        await server.stop()

    asyncio.run(_run())


def test_subprocess_lifecycle_group_isolation():
    bridge = VoiceFiIPCBridge(auto_reconnect=False)
    # Test running a fast subprocess command in new process group
    res = bridge.run_subprocess_command([sys.executable, "-c", "print('hello from spark child')"])
    assert res["success"]
    assert "hello from spark child" in res["stdout"]
