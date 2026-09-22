import asyncio
import json
import aiohttp

async def test_relay_audio():
    session_id = "vifi_4d098c55"
    token = "MkNCI_F2Wczaf18jX4ZORQ"
    url = f"wss://companion.voicefi.app/v1/relay?session={session_id}&token={token}&role=client"
    print(f"Connecting to relay as client: {url}")
    
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url) as ws:
            print("Connected to relay!")
            msg = await ws.receive_json()
            print("Received:", msg)
            
            # Send live_start
            payload = {
                "type": "live_start",
                "params": {
                    "model": "gemini-2.5-flash-native-audio-latest",
                    "voice": "Puck",
                    "thinking": False,
                    "tools": True
                }
            }
            await ws.send_json(payload)
            
            # Wait for connected
            connected = False
            for _ in range(5):
                msg = await asyncio.wait_for(ws.receive(), timeout=10.0)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "connected":
                        connected = True
                        print("✅ Connected event received!")
                        break
            
            if not connected:
                print("❌ Failed to connect")
                return False
                
            # Send a prompt via live_text
            print("Sending prompt via live_text...")
            await ws.send_json({"type": "live_text", "text": "Say 'Live Relay Connected' in two words."})
            
            got_transcript = False
            got_audio = False
            for _ in range(30):
                msg = await asyncio.wait_for(ws.receive(), timeout=10.0)
                print(f"DEBUG msg.type={msg.type}")
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    mtype = data.get("type")
                    print(f"Text event: {mtype} - {data.get('text', '')}")
                    if mtype == "model_transcript":
                        got_transcript = True
                    if mtype == "turn_complete":
                        print("🏁 Turn complete!")
                        break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    got_audio = True
                    print(f"Binary audio chunk: {len(msg.data)} bytes")
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
                    print("Relay WS closed")
                    break
                    
            print(f"Results: got_transcript={got_transcript}, got_audio={got_audio}")
            return got_transcript and got_audio

if __name__ == "__main__":
    ok = asyncio.run(test_relay_audio())
    if ok:
        print("🎉 FULL RELAY AUDIO & TEXT PIPELINE VERIFIED!")
    else:
        print("❌ FAILED")
