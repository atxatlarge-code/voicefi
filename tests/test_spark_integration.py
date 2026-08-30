"""
Unit and integration tests for Gemini Spark agent runner and turn-end hooks.
"""

import asyncio
import os
import pytest

from voicefi.config import load_config
from voicefi.integrations.spark import GeminiSparkRunner, SparkTurnEndHook
from voicefi.ipc.protocol import (
    EVENT_TOOL_COMPLETE,
    EVENT_TOOL_START,
    EVENT_TURN_COMPLETE,
    EVENT_TURN_START,
)
from voicefi.ipc.server import VoiceFiIPCServer


def test_spark_turn_hook_distillation_local_fallback():
    hook = SparkTurnEndHook(default_persona="Viv", agent_name="Spark")
    
    # Complex markdown output from agent
    agent_output = """
### Summary of Changes
I have refactored the database connection pooling in `src/db/pool.py`.
- Added connection timeout of 5000ms.
- Fixed leak in cursor closing logic.

```python
def connect():
    return Pool()
```

Would you like me to deploy this to the staging environment?
"""
    soundbite = hook.distill_spoken_soundbite(agent_output, max_words=30)
    assert len(soundbite.split()) <= 35
    assert "```" not in soundbite
    assert soundbite.endswith("?") or soundbite.endswith(".")


def test_spark_turn_hook_distillation_with_gemini_model(monkeypatch):
    hook = SparkTurnEndHook(default_persona="Christopher", agent_name="Spark")

    # Mock Gemini Flash model response
    monkeypatch.setattr(
        hook._intelligence_engine,
        "is_available",
        lambda: True,
    )
    monkeypatch.setattr(
        hook._intelligence_engine,
        "distill_spoken_soundbite",
        lambda text, max_words=30, timeout=0.8: "I refactored the auth module and all 14 unit tests passed.",
    )

    soundbite = hook.distill_spoken_soundbite("Long detailed agent execution report...")
    assert soundbite == "I refactored the auth module and all 14 unit tests passed."


def test_spark_full_turn_loop_with_ipc_bridge(monkeypatch):
    async def _run():
        sock_path = f"/tmp/test_spark_{os.getpid()}_{int(asyncio.get_event_loop().time() * 1000)}.sock"
        ws_port = 18768

        monkeypatch.setattr("voicefi.ipc.server.get_tts_engine", lambda *a, **kw: type("MockTTS", (), {"persona_name": "Viv", "stream_speak": lambda s, t, block=True: None})())

        server_events = []
        server = VoiceFiIPCServer(
            socket_path=sock_path,
            ws_port=ws_port,
            enable_ws=False,
            on_agent_event=lambda ev: server_events.append(ev),
        )
        await server.start()

        async def _mock_spark_executor(prompt):
            await asyncio.sleep(0.05)
            return f"Executed Spark action for: {prompt}. All tests passed."

        runner = GeminiSparkRunner(
            persona="Viv",
            executor=_mock_spark_executor,
        )
        # Point bridge to test socket
        runner.bridge.socket_path = sock_path
        runner.bridge.auto_reconnect = False

        await runner.start()
        await asyncio.sleep(0.1)
        assert runner.bridge.is_connected

        # Execute a turn
        soundbite = await runner.execute_prompt("Build authentication middleware", session_id="spark-101")
        assert "authentication middleware" in soundbite.lower() or "tests passed" in soundbite.lower()

        await asyncio.sleep(0.1)
        event_types = [ev.get("event_type") for ev in server_events]
        assert EVENT_TURN_START in event_types
        assert EVENT_TURN_COMPLETE in event_types

        turn_complete_event = next(ev for ev in server_events if ev.get("event_type") == EVENT_TURN_COMPLETE)
        assert turn_complete_event["agent_name"] == "Spark"
        assert turn_complete_event["persona"] == "Viv"
        assert turn_complete_event["status"] == "success"

        await runner.stop()
        await server.stop()

    asyncio.run(_run())
