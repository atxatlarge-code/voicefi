#!/usr/bin/env python3
"""
Empirical benchmark comparing model candidates for the character voice turn-in pipeline:
1. Summarization: Local Gemma 4 2B (port 9379) vs Gemini 2.5 Flash Lite vs Gemini 2.5 Flash
2. TTS: Gemini 3.8 Live (WebSockets streaming) vs Gemini 3.8 Flash TTS / 2.5 Flash Preview TTS
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# Add src to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from voicefi.config import resolve_gemini_api_key
from google import genai
from google.genai import types

TEST_PROMPT = (
    "I have analyzed the database logs and noticed that the connection pool "
    "was completely exhausted after 50 concurrent requests because the connection "
    "cleanup callback was not registered on the socket error event. "
    "I patched the handler, restarted the worker pool, and verified all integration tests pass."
)

PERSONA = "A weary, sarcastic systems engineer delivering dry Elizabethan irony"


def benchmark_local_gemma_2b(prompt: str) -> dict:
    """Benchmark warm local Gemma 4 2B on port 9379."""
    start = time.perf_counter()
    req_data = json.dumps(
        {
            "model": "gemma4-2b",
            "messages": [
                {
                    "role": "system",
                    "content": f"You are {PERSONA}. Condense this into 1 or 2 spoken sentences with stage directions like [big sigh] or [deadpan]. Output ONLY dialogue.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 70,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:9379/v1/chat/completions",
        data=req_data,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = (time.perf_counter() - start) * 1000.0
            content = data["choices"][0]["message"]["content"].strip()
            tokens = data.get("usage", {}).get("completion_tokens", 0)
            return {
                "model": "Local Gemma 4 2B (Apple Silicon / LiteRT)",
                "latency_ms": round(elapsed, 1),
                "tokens": tokens,
                "output": content,
                "status": "success",
            }
    except Exception as e:
        return {
            "model": "Local Gemma 4 2B",
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 1),
            "error": str(e),
            "status": "error",
        }


def benchmark_gemini_cloud(model_name: str, prompt: str, api_key: str) -> dict:
    """Benchmark cloud Gemini model for character summarization."""
    client = genai.Client(api_key=api_key)
    start = time.perf_counter()
    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=(
                f"You are {PERSONA}. Condense this into 1 or 2 spoken sentences with stage directions "
                f"like [big sigh] or [deadpan]. Output ONLY dialogue:\n\n{prompt}"
            ),
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        text = resp.text.strip() if resp and resp.text else ""
        return {
            "model": f"Cloud {model_name}",
            "latency_ms": round(elapsed, 1),
            "output": text,
            "status": "success",
        }
    except Exception as e:
        return {
            "model": f"Cloud {model_name}",
            "latency_ms": round((time.perf_counter() - start) * 1000.0, 1),
            "error": str(e),
            "status": "error",
        }


async def benchmark_gemini_38_live_streaming(text: str, api_key: str) -> dict:
    """Benchmark Gemini 3.8 Live WebSocket TTFA (Time to First Audio Byte)."""
    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck")
            )
        ),
    )

    start = time.perf_counter()
    ttfa = None
    total_bytes = 0

    try:
        async with client.aio.live.connect(model="gemini-3.8-live", config=config) as session:
            conn_time = (time.perf_counter() - start) * 1000.0
            await session.send_realtime_input(text=f"Read this line verbatim: {text}")

            async for response in session.receive():
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            if ttfa is None:
                                ttfa = (time.perf_counter() - start) * 1000.0
                            total_bytes += len(part.inline_data.data)
                if response.server_content and response.server_content.turn_complete:
                    break

        total_time = (time.perf_counter() - start) * 1000.0
        return {
            "engine": "Gemini 3.8 Live (WebSocket Streaming)",
            "connect_ms": round(conn_time, 1),
            "ttfa_ms": round(ttfa, 1) if ttfa else None,
            "total_ms": round(total_time, 1),
            "audio_bytes": total_bytes,
            "status": "success",
        }
    except Exception as e:
        return {
            "engine": "Gemini 3.8 Live (WebSocket Streaming)",
            "error": str(e),
            "status": "error",
        }


async def main():
    api_key = resolve_gemini_api_key() or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY not found!")
        return

    print("=" * 65)
    print("🔬 VOICEFI CHARACTER & TTS LATENCY BENCHMARK")
    print("=" * 65)
    print(f"Target Persona: {PERSONA}")
    print(f"Sample Input:   {TEST_PROMPT[:80]}...\n")

    # 1. Summarization Benchmark
    print("─── 1. Summarization / Distillation Models ───")
    res_local = benchmark_local_gemma_2b(TEST_PROMPT)
    print(f"• {res_local['model']:<36}: {res_local['latency_ms']} ms")
    if "output" in res_local:
        print(f'  └─ Line: "{res_local["output"]}"')

    res_flash_lite = benchmark_gemini_cloud("gemini-2.5-flash-lite", TEST_PROMPT, api_key)
    print(f"• {res_flash_lite['model']:<36}: {res_flash_lite['latency_ms']} ms")
    if "output" in res_flash_lite:
        print(f'  └─ Line: "{res_flash_lite["output"]}"')

    res_flash = benchmark_gemini_cloud("gemini-2.5-flash", TEST_PROMPT, api_key)
    print(f"• {res_flash['model']:<36}: {res_flash['latency_ms']} ms")
    if "output" in res_flash:
        print(f'  └─ Line: "{res_flash["output"]}"')

    # 2. Audio Latency Benchmark
    print("\n─── 2. Speech Synthesis Latency (TTFA) ───")
    chosen_text = (
        res_local.get("output") or res_flash.get("output") or "Your database pool is dead."
    )
    res_audio = await benchmark_gemini_38_live_streaming(chosen_text, api_key)
    if res_audio.get("status") == "success":
        print(f"• {res_audio['engine']}")
        print(f"  ├─ WebSocket Connect: {res_audio['connect_ms']} ms")
        print(f"  ├─ Time to First Audio (TTFA): {res_audio['ttfa_ms']} ms ⚡")
        print(
            f"  └─ Total Stream Transfer: {res_audio['total_ms']} ms ({res_audio['audio_bytes']:,} bytes)"
        )
    else:
        print(f"• Audio Error: {res_audio.get('error')}")

    print("\n" + "=" * 65)
    print("🏆 SUMMARY: TOTAL PIPELINE LATENCY")
    print("=" * 65)
    if res_local.get("status") == "success" and res_audio.get("status") == "success":
        local_total = res_local["latency_ms"] + res_audio["ttfa_ms"]
        print(
            f"  Option A [Local Gemma 4 2B + 3.8 Live]:  {local_total:.1f} ms to first audio sound"
        )
    if res_flash_lite.get("status") == "success" and res_audio.get("status") == "success":
        cloud_lite_total = res_flash_lite["latency_ms"] + res_audio["ttfa_ms"]
        print(
            f"  Option B [Cloud 2.5 Flash Lite + 3.8 Live]: {cloud_lite_total:.1f} ms to first audio sound"
        )
    if res_flash.get("status") == "success" and res_audio.get("status") == "success":
        cloud_flash_total = res_flash["latency_ms"] + res_audio["ttfa_ms"]
        print(
            f"  Option C [Cloud 2.5 Flash + 3.8 Live]:      {cloud_flash_total:.1f} ms to first audio sound"
        )


if __name__ == "__main__":
    asyncio.run(main())
