#!/usr/bin/env python3
import asyncio
import argparse
import sys
import os
import wave
import subprocess
from pathlib import Path

# Add VoiceFi to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from voicefi.local import ReconScout
from voicefi.config import resolve_gemini_api_key
from google import genai
from google.genai import types

async def synthesize_streaming(text: str, character_prompt: str, voice_name: str, out_path: str):
    print(f"🎙️  Direct Acoustic Synthesis via WebSockets (gemini-3.8-live)...")
    key = resolve_gemini_api_key() or os.environ.get("GEMINI_API_KEY")
    client = genai.Client(api_key=key)
    
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=character_prompt)]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
    )

    chunks = []
    # Using the fast streaming websocket endpoint
    async with client.aio.live.connect(model="gemini-3.8-live", config=config) as session:
        await session.send_realtime_input(text=f"Read this line verbatim, including any emotional stage directions: {text}")
        
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data and part.inline_data.data:
                        chunks.append(part.inline_data.data)
            if response.server_content and response.server_content.turn_complete:
                break

    if chunks:
        pcm = b"".join(chunks)
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm)
        print(f"✅ Generated {len(pcm)} bytes of audio.")
    else:
        print("❌ No audio received from Gemini.")

async def main():
    parser = argparse.ArgumentParser(description="Prototype: Local Character Summary + Gemini 3.8 Live TTS")
    parser.add_argument("--text", type=str, required=True, help="The full markdown/text response to summarize.")
    parser.add_argument("--voice", type=str, default="Puck", help="Gemini 3.8 Live Voice to use (Puck, Aoede, Charon, Kore, Fenrir).")
    args = parser.parse_args()

    # The character instruction we pass to Gemini to enforce the inflection
    character_prompt = (
        "You are a weary, sarcastic systems engineer delivering dry Elizabethan irony. "
        "Speak with deadpan condescension, a mocking chuckle, and zero genuine sympathy. "
        "Pay strict attention to inline stage directions like [big sigh], [chuckles], [deadpan], or [emphasize]."
    )

    temp_in = Path("/tmp/voicefi_proto_input.txt")
    temp_in.write_text(args.text, encoding="utf-8")

    print(f"🕵️  Local Gemma 4 Compression (Apple Silicon)...")
    scout = ReconScout()
    
    # Instruct Gemma to actually write out the stage directions for Gemini to read
    gemma_query = (
        "You are a sarcastic systems engineer. Summarize this text into 1 or 2 spoken sentences. "
        "You MUST include inline emotional stage directions like [big sigh], [deadpan], [chuckles], or [emphasize] directly in the text. "
        "Return ONLY the summarized dialogue, no prefixes."
    )
    
    result = await scout.scout(
        target_path=str(temp_in),
        query=gemma_query
    )
    
    summary_text = result.findings.strip()
    print("\n📝 Local Model Summary (Character):")
    print(f"> {summary_text}\n")
    
    out_wav = "/tmp/voicefi_proto_character.wav"
    
    # Run the streaming synth
    await synthesize_streaming(
        text=summary_text,
        character_prompt=character_prompt,
        voice_name=args.voice,
        out_path=out_wav
    )
    
    print("🔊 Playing audio via afplay...")
    subprocess.run(["afplay", out_wav])
    print("\n✅ Done!")

if __name__ == "__main__":
    asyncio.run(main())
