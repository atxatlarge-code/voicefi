"""
Unit tests for VoiceFi IPC Daemon Server (Unix domain socket and WebSocket transports).
"""

import asyncio
import json
import os
import pytest

from voicefi.ipc.protocol import (
    METHOD_AGENT_EVENT,
    METHOD_PROMPT_DISPATCH,
    METHOD_SIGNAL_INTERRUPT,
    EVENT_TURN_COMPLETE,
    build_agent_event,
    parse_jsonrpc_message,
)
from voicefi.ipc.server import VoiceFiIPCServer


def test_ipc_server_unix_socket_lifecycle(monkeypatch):
    async def _run():
        sock_path = f"/tmp/test_voicefi_{os.getpid()}_{int(asyncio.get_event_loop().time() * 1000)}.sock"
        ws_port = 18765

        # Mock TTS synthesis to prevent actual audio playback during test
        tts_calls = []
        class MockTTS:
            def __init__(self, *args, **kwargs):
                self.persona_name = "Viv"
            def stream_speak(self, text, block=True):
                tts_calls.append(text)

        monkeypatch.setattr("voicefi.ipc.server.get_tts_engine", lambda *a, **kw: MockTTS())

        agent_events = []
        def _on_event(ev):
            agent_events.append(ev)

        server = VoiceFiIPCServer(
            socket_path=sock_path,
            ws_port=ws_port,
            enable_ws=True,
            on_agent_event=_on_event,
        )

        await server.start()
        assert server.is_running
        assert os.path.exists(sock_path)

        # 1. Connect a test Unix socket client
        reader, writer = await asyncio.open_unix_connection(sock_path)
        await asyncio.sleep(0.05)
        assert server.connected_client_count >= 1

        # 2. Test server broadcasting prompt dispatch
        await server.broadcast_prompt_dispatch(
            transcript="Test voice command",
            session_id="session-1",
            source="whisperkit",
            confidence=0.99,
        )

        line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        parsed = parse_jsonrpc_message(line)
        assert parsed["method"] == METHOD_PROMPT_DISPATCH
        assert parsed["params"]["transcript"] == "Test voice command"
        assert parsed["params"]["session_id"] == "session-1"

        # 3. Test server broadcasting barge-in interrupt
        await server.broadcast_interrupt(reason="speech_detected", energy=0.065)
        line2 = await asyncio.wait_for(reader.readline(), timeout=2.0)
        parsed2 = parse_jsonrpc_message(line2)
        assert parsed2["method"] == METHOD_SIGNAL_INTERRUPT
        assert parsed2["params"]["reason"] == "speech_detected"

        # 4. Test client sending vifi.agent.event to server
        event = build_agent_event(
            event_type=EVENT_TURN_COMPLETE,
            agent_name="Spark",
            persona="Viv",
            spoken_summary="Refactored the codebase cleanly.",
            status="success",
        )
        writer.write((json.dumps(event) + "\n").encode("utf-8"))
        await writer.drain()

        await asyncio.sleep(0.1)
        assert len(agent_events) == 1
        assert agent_events[0]["event_type"] == EVENT_TURN_COMPLETE
        assert agent_events[0]["spoken_summary"] == "Refactored the codebase cleanly."
        assert "Refactored the codebase cleanly." in tts_calls

        # 5. Clean teardown
        writer.close()
        await writer.wait_closed()
        await server.stop()
        assert not server.is_running
        assert not os.path.exists(sock_path)

    asyncio.run(_run())
