"""
End-to-end integration test for the Gemini Live WebSocket server pipeline (/ws/live).
Tests connection, model thinking, tool invocation, tool response dispatch,
audio gating, and turn completion without any UnboundLocalError or protocol deadlocks.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from voicefi.companion.server import CompanionServer


class LiveWebSocketPipelineTestCase(AioHTTPTestCase):
    async def get_application(self):
        server = CompanionServer()
        return server.app

    @unittest_run_loop
    async def test_live_ws_full_tool_call_lifecycle(self):
        """
        Verify that handle_live_ws cleanly handles:
        1. Connected handshake
        2. Thinking chunk
        3. Tool call execution (run_shell_check)
        4. Audio packet gating during tool call
        5. FunctionResponse upstream dispatch
        6. Turn complete
        All without any UnboundLocalError or exceptions.
        """
        mock_session = MagicMock()
        mock_session._receive = AsyncMock()
        mock_session.send_realtime_input = AsyncMock()
        mock_session.send_tool_response = AsyncMock()

        # Build mock server messages from Gemini Live
        msg_connected = MagicMock(
            tool_call=None,
            server_content=MagicMock(
                interrupted=False,
                input_transcription=None,
                output_transcription=None,
                model_turn=MagicMock(
                    parts=[
                        MagicMock(thought=True, text="I will check system uptime."),
                    ]
                ),
                turn_complete=False,
            ),
        )

        func_call = MagicMock()
        func_call.name = "run_shell_check"
        func_call.id = "test-call-456"
        func_call.args = {"command": "uptime"}
        msg_tool_call = MagicMock(
            tool_call=MagicMock(function_calls=[func_call]),
            server_content=None,
        )

        msg_turn_complete = MagicMock(
            tool_call=None,
            server_content=MagicMock(
                interrupted=False,
                input_transcription=None,
                output_transcription=MagicMock(text="System is up and running."),
                model_turn=MagicMock(
                    parts=[
                        MagicMock(thought=False, text="System is up and running.", inline_data=None),
                    ]
                ),
                turn_complete=True,
            ),
        )

        tool_response_sent = asyncio.Event()

        async def mock_send_tool_response(*args, **kwargs):
            tool_response_sent.set()

        mock_session.send_tool_response.side_effect = mock_send_tool_response

        # Sequence of messages returned by session._receive()
        step = 0

        async def mock_receive():
            nonlocal step
            step += 1
            if step == 1:
                return msg_connected
            elif step == 2:
                return msg_tool_call
            elif step == 3:
                # Wait until execute_and_reply_tool has actually called session.send_tool_response
                await tool_response_sent.wait()
                return msg_turn_complete
            else:
                await asyncio.sleep(1.0)
                raise asyncio.CancelledError()

        mock_session._receive.side_effect = mock_receive

        class MockLiveConnectContext:
            async def __aenter__(self):
                return mock_session

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_client = MagicMock()
        mock_client.aio.live.connect.return_value = MockLiveConnectContext()

        with patch("google.genai.Client", return_value=mock_client), \
             patch.dict("os.environ", {"GEMINI_API_KEY": "AIzaSyTestKey1234567890"}):

            ws = await self.client.ws_connect("/ws/live?model=gemini-2.5-flash-native-audio-latest&voice=Puck&tools=1")

            # 1. Expect connected
            msg1 = await ws.receive_json()
            assert msg1["type"] == "connected"
            assert msg1["model"] == "gemini-2.5-flash-native-audio-latest"

            # 2. Expect thinking
            msg2 = await ws.receive_json()
            assert msg2["type"] == "model_thinking"
            assert "uptime" in msg2["text"]

            # 3. Expect tool_start
            msg3 = await ws.receive_json()
            assert msg3["type"] == "tool_start"
            assert msg3["name"] == "run_shell_check"
            assert msg3["id"] == "test-call-456"

            # 4. Stream audio packet while tool is in flight (should be gated without crashing)
            dummy_pcm = b"\x00" * 640
            await ws.send_bytes(dummy_pcm)

            # 5. Expect tool_done
            msg4 = await ws.receive_json()
            assert msg4["type"] == "tool_done"
            assert msg4["name"] == "run_shell_check"
            assert "result" in msg4

            # 6. Verify session.send_tool_response was called upstream to Gemini
            assert mock_session.send_tool_response.called
            call_args = mock_session.send_tool_response.call_args
            assert call_args is not None
            fn_responses = call_args[1].get("function_responses") or call_args[0][0]
            assert len(fn_responses) > 0
            assert fn_responses[0].name == "run_shell_check"
            assert fn_responses[0].id == "test-call-456"

            # 7. Expect model transcript & turn complete
            msg5 = await ws.receive_json()
            assert msg5["type"] == "model_transcript"
            assert "System is up" in msg5["text"]

            msg6 = await ws.receive_json()
            assert msg6["type"] == "turn_complete"

            await ws.close()
