"""
End-to-end live verification for VoiceFi IPC Daemon Bridge, Gemini Spark Runner,
spoken soundbite distillation, and mid-turn barge-in interruption.
"""

import asyncio
import os
import signal
import sys
import time
import pytest

from voicefi.config import load_config
from voicefi.integrations.spark import GeminiSparkRunner, SparkTurnEndHook
from voicefi.ipc.bridge import VoiceFiIPCBridge
from voicefi.ipc.protocol import (
    EVENT_TURN_COMPLETE,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_START,
    METHOD_AGENT_EVENT,
    METHOD_PROMPT_DISPATCH,
    METHOD_SIGNAL_INTERRUPT,
)
from voicefi.ipc.server import VoiceFiIPCServer


def test_live_e2e_voice_prompt_to_turn_complete_loop(monkeypatch):
    """
    Test full loop:
    1. STT transcribes speech -> daemon broadcasts vifi.prompt.dispatch
    2. Bridge receives transcript -> enqueues turn -> executes prompt
    3. Spark distill soundbite -> emits turn_complete back to daemon
    4. Daemon receives turn_complete with spoken_summary in Viv/Christopher persona
    """
    monkeypatch.setattr(
        "voicefi.ipc.server.get_tts_engine",
        lambda *a, **kw: type("MockTTS", (), {"persona_name": "Viv", "stream_speak": lambda s, t, block=True: None})(),
    )

    async def _run():
        sock_path = f"/tmp/test_e2e_voicefi_{os.getpid()}.sock"
        ws_port = 18780

        daemon_received_events = []
        synthesized_summaries = []

        def _on_daemon_agent_event(ev):
            daemon_received_events.append(ev)

        server = VoiceFiIPCServer(
            socket_path=sock_path,
            ws_port=ws_port,
            enable_ws=True,
            on_agent_event=_on_daemon_agent_event,
        )
        await server.start()
        assert server.is_running
        assert os.path.exists(sock_path)

        # 2. Start Gemini Spark Runner attached to IPC bridge
        async def _spark_task_executor(prompt):
            # Simulates an agent refactoring code and producing markdown output
            return f"""
### Database Optimization Completed
- Added index on `user_id` in `accounts` table.
- Query latency reduced by 72% across all endpoints.
All 24 integration tests passed!
"""

        runner = GeminiSparkRunner(
            persona="Viv",
            executor=_spark_task_executor,
        )
        runner.bridge.socket_path = sock_path
        runner.bridge.auto_reconnect = False

        await runner.start()
        await asyncio.sleep(0.15)
        assert runner.bridge.is_connected
        assert runner.bridge.active_transport == "unix"

        # 3. Simulate WhisperKit STT emitting transcribed voice command
        spoken_prompt = "Optimize the database queries for the accounts table and run tests."
        await server.broadcast_prompt_dispatch(
            transcript=spoken_prompt,
            session_id="conv-spark-live-01",
            source="whisperkit-metal",
            confidence=0.97,
        )

        # Wait for prompt execution, distillation, and turn_complete emission
        await asyncio.sleep(0.3)

        # 4. Verify daemon received turn_start and turn_complete events
        event_types = [ev.get("event_type") for ev in daemon_received_events]
        assert EVENT_TURN_START in event_types
        assert EVENT_TURN_COMPLETE in event_types

        complete_event = next(ev for ev in daemon_received_events if ev.get("event_type") == EVENT_TURN_COMPLETE)
        assert complete_event["agent_name"] == "Spark"
        assert complete_event["persona"] == "Viv"
        assert complete_event["status"] == "success"
        
        spoken_summary = complete_event["spoken_summary"]
        assert len(spoken_summary) > 0
        assert len(spoken_summary.split()) <= 35
        print(f"\n✅ Live E2E Spoken Soundbite: \"{spoken_summary}\"")

        # 5. Clean teardown
        await runner.stop()
        await server.stop()
        assert not os.path.exists(sock_path)

    asyncio.run(_run())


def test_live_e2e_barge_in_instant_cancellation():
    """
    Test live mid-turn interrupt (Barge-In):
    1. Agent starts a long execution task
    2. User speaks -> STT/VAD emits vifi.signal.interrupt
    3. Bridge cancels active process / task instantly
    4. Daemon receives turn_interrupted and cleans up
    """
    async def _run():
        sock_path = f"/tmp/test_e2e_bargein_{os.getpid()}.sock"
        ws_port = 18781

        daemon_events = []
        server = VoiceFiIPCServer(
            socket_path=sock_path,
            ws_port=ws_port,
            enable_ws=False,
            on_agent_event=lambda ev: daemon_events.append(ev),
        )
        await server.start()

        task_cancelled = False
        async def _long_running_task(prompt):
            nonlocal task_cancelled
            try:
                # Long task
                await asyncio.sleep(10.0)
                return "Task finished after 10s"
            except asyncio.CancelledError:
                task_cancelled = True
                raise

        runner = GeminiSparkRunner(
            persona="Christopher",
            executor=_long_running_task,
        )
        runner.bridge.socket_path = sock_path
        runner.bridge.auto_reconnect = False

        await runner.start()
        await asyncio.sleep(0.15)

        # 1. Dispatch prompt
        await server.broadcast_prompt_dispatch(
            transcript="Run long architectural migration",
            session_id="conv-long-01",
        )
        await asyncio.sleep(0.1)
        assert runner.bridge.is_turn_active

        # 2. Simulate user speaking mid-turn (Barge-In)
        interrupt_start = time.time()
        await server.broadcast_interrupt(reason="speech_detected", energy=0.085)

        # 3. Wait for cancellation to settle
        await asyncio.sleep(0.2)
        interrupt_duration_ms = (time.time() - interrupt_start) * 1000

        assert task_cancelled is True
        assert not runner.bridge.is_turn_active
        print(f"\n⚡ Mid-turn barge-in cancelled active task in {interrupt_duration_ms:.1f}ms")

        # 4. Verify daemon received turn_interrupted event
        event_types = [ev.get("event_type") for ev in daemon_events]
        assert EVENT_TURN_INTERRUPTED in event_types

        await runner.stop()
        await server.stop()

    asyncio.run(_run())
