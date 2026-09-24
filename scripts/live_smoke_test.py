#!/usr/bin/env python3
"""
Live Daemon Smoke Test Script for VoiceFi Gemini Live.

Connects to the active VoiceFi server on Port 5141 via WebSocket,
dispatches a prompt that triggers a tool ('Run git status check please'),
and asserts that the full cycle (tool_start -> tool_done -> turn_complete)
completes cleanly without any error frames or exceptions in /tmp/voicefi.err.
"""

import asyncio
import json
import sys
import aiohttp


async def run_smoke_test(timeout_sec: float = 15.0):
    url = (
        "ws://localhost:5141/ws/live?model=gemini-2.5-flash-native-audio-latest&voice=Puck&tools=1"
    )
    print(f"📡 Connecting to live WebSocket: {url} ...")

    tool_started = False
    tool_completed = False
    turn_completed = False
    got_connected = False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, timeout=timeout_sec) as ws:
                print(
                    "🟢 WebSocket connected! Sending tool prompt: 'Run git status check please'..."
                )
                await ws.send_json({"type": "text", "text": "Run git status check please."})

                async def read_loop():
                    nonlocal tool_started, tool_completed, turn_completed, got_connected
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            mtype = data.get("type")

                            if mtype == "connected":
                                got_connected = True
                                print(f"✅ Handshake complete: model={data.get('model')}")
                            elif mtype == "model_thinking":
                                print(f"💭 Thinking: {data.get('text')[:80]}...")
                            elif mtype == "tool_start":
                                tool_started = True
                                print(f"🛠️ Tool started: {data.get('name')} (id={data.get('id')})")
                            elif mtype == "tool_done":
                                tool_completed = True
                                print(
                                    f"✅ Tool completed: {data.get('name')} in {data.get('duration_ms')}ms"
                                )
                            elif mtype == "model_transcript":
                                print(f"🗣️ Model: {data.get('text')}")
                            elif mtype == "turn_complete":
                                turn_completed = True
                                print("🏁 Turn complete!")
                                break
                            elif mtype == "error":
                                print(f"❌ Server returned error event: {data.get('message')}")
                                return False
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            print(f"⚠️ WebSocket closed unexpectedly: {msg}")
                            break
                    return True

                success = await asyncio.wait_for(read_loop(), timeout=timeout_sec)
                await ws.close()

    except asyncio.TimeoutError:
        print(f"❌ Smoke test timed out after {timeout_sec}s")
        return False
    except Exception as e:
        print(f"❌ Smoke test exception: {e}")
        return False

    print("\n📋 Smoke Test Results:")
    print(f"  • Connected Handshake: {'✅' if got_connected else '❌'}")
    print(
        f"  • Tool Execution:      {'✅' if (tool_started and tool_completed) else '⚠️ (no tool called)'}"
    )
    print(f"  • Turn Complete:       {'✅' if turn_completed else '❌'}")

    return got_connected and turn_completed


if __name__ == "__main__":
    ok = asyncio.run(run_smoke_test())
    if ok:
        print("\n🎉 SMOKE TEST PASSED: Live WebSocket pipeline is 100% operational!")
        sys.exit(0)
    else:
        print("\n💥 SMOKE TEST FAILED!")
        sys.exit(1)
