#!/usr/bin/env python3
"""
Gemini 3.8 Live Comedian & Demo Studio for VoiceFi.

Streams real-time bidirectional audio/text to Google's Gemini 3.8 Live API,
delivering stand-up comedic timing, chuckles, affective dialogue, and co-timed
punchline sound effects (rimshots, applause, sad trombone) via VoiceFi.
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import Dict, Any, Optional, List

# Ensure src/ is in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from voicefi.config import load_config, resolve_gemini_api_key, VALID_GEMINI_LIVE_VOICES

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("[Error] google-genai is required. Please install with: pip install google-genai>=1.65.0")
    sys.exit(1)


SFX_DIR = Path.home() / ".voicefi" / "sfx"
AVAILABLE_SFX = {
    "rimshot": SFX_DIR / "rimshot.wav",
    "drum_smash": SFX_DIR / "drum_smash.wav",
    "applause": SFX_DIR / "applause.wav",
    "sad_trombone": SFX_DIR / "sad_trombone.wav",
    "crickets": SFX_DIR / "crickets.wav",
    "honk": SFX_DIR / "honk.wav",
    "boing": SFX_DIR / "boing.wav",
}


def play_sound_effect(name: str) -> str:
    """
    Play a punchline sound effect (rimshot, applause, sad_trombone, drum_smash, crickets).
    """
    clean_name = name.lower().strip().replace(" ", "_")
    sfx_file = AVAILABLE_SFX.get(clean_name)
    if not sfx_file or not sfx_file.is_file():
        # Fallback to closest match
        for k, p in AVAILABLE_SFX.items():
            if k in clean_name and p.is_file():
                sfx_file = p
                clean_name = k
                break

    if sfx_file and sfx_file.is_file():
        print(f"\n🥁 [SFX] Triggered: {clean_name.upper()} ({sfx_file.name})")
        try:
            subprocess.Popen(["afplay", str(sfx_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Played sound effect '{clean_name}'"
        except Exception as e:
            return f"Error playing sound effect: {e}"
    return f"Sound effect '{name}' not found"


SYSTEM_INSTRUCTIONS = {
    "comedy": (
        "You are an energetic, quick-witted stand-up comedian performing live. "
        "Deliver snappy jokes with punchy comedic timing, natural conversational pauses, "
        "and expressive laughter. Whenever you hit a punchline, immediately invoke the "
        "play_sound_effect tool: use 'rimshot' or 'drum_smash' for strong punchlines, "
        "'applause' for crowd pleasers, 'crickets' for intentional groaner dad jokes, or "
        "'sad_trombone' for self-deprecating fails."
    ),
    "roast": (
        "You are a sharp, hilarious comedy roastmaster. Roast tech habits, messy git repos, "
        "over-engineered microservices, and AI hype with comedic flair and sharp delivery. "
        "Fire a 'rimshot' or 'sad_trombone' sound effect right at the punchline."
    ),
    "banter": (
        "You are a quick, playful conversationalist. Keep turns punchy, witty, and back-and-forth. "
        "React naturally with chuckles and conversational fillers."
    ),
    "assistant": (
        "You are a lightning-fast, articulate voice assistant powered by Gemini 3.8 Live. "
        "Answer clearly, concisely, and naturally in spoken conversation."
    ),
}


class GeminiLiveComedianRunner:
    """Interactive bidirectional streaming runner for Gemini 3.8 Live."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-3.8-live",
        voice: str = "Puck",
        mode: str = "comedy",
        use_thinking: bool = False,
        thinking_level: str = "LOW",
        enable_sfx: bool = True,
        play_audio: bool = True,
    ):
        self.config = load_config()
        self.api_key = api_key or resolve_gemini_api_key(self.config)
        if not self.api_key:
            raise ValueError(
                "Gemini API Key not found. Please set GEMINI_API_KEY environment variable "
                "or configure in ~/.voicefi/config.yaml."
            )

        self.model = "gemini-3.8-live-extended-thinking" if use_thinking else model
        self.voice = voice if voice in VALID_GEMINI_LIVE_VOICES else "Puck"
        self.mode = mode
        self.use_thinking = use_thinking
        self.thinking_level = thinking_level.upper()
        self.enable_sfx = enable_sfx
        self.play_audio = play_audio
        self.client = genai.Client(api_key=self.api_key)

    def _build_live_config(self) -> types.LiveConnectConfig:
        system_instruction_text = SYSTEM_INSTRUCTIONS.get(self.mode, SYSTEM_INSTRUCTIONS["comedy"])

        tools = [play_sound_effect] if self.enable_sfx else None

        thinking_cfg = None
        if self.use_thinking or "extended-thinking" in self.model:
            t_level = getattr(types.ThinkingLevel, self.thinking_level, types.ThinkingLevel.LOW)
            thinking_cfg = types.ThinkingConfig(thinking_level=t_level)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(
                parts=[types.Part.from_text(text=system_instruction_text)]
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice
                    )
                )
            ),
            thinking_config=thinking_cfg,
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tools,
        )

    async def run_prompt(self, prompt: str) -> Dict[str, Any]:
        """Send a single prompt and stream speech output + live transcription."""
        config = self._build_live_config()

        print(f"\n⚡ Connecting to {self.model} (Voice: {self.voice}, Mode: {self.mode})...")
        t0 = time.time()

        audio_chunks = []
        transcript_chunks = []
        first_audio_ms = None
        triggered_sfx = []

        async with self.client.aio.live.connect(model=self.model, config=config) as session:
            t_conn = time.time()
            conn_ms = int((t_conn - t0) * 1000)
            print(f"✅ Connected in {conn_ms}ms! Sending prompt...")

            t_send = time.time()
            await session.send_realtime_input(text=prompt)

            print("🎙️ Spoken response streaming: ", end="", flush=True)

            async for response in session.receive():
                # Handle tool calls (SFX triggers)
                if response.tool_call:
                    for call in response.tool_call.function_calls:
                        if call.name == "play_sound_effect":
                            sfx_arg = call.args.get("name", "rimshot")
                            triggered_sfx.append(sfx_arg)
                            res = play_sound_effect(sfx_arg) if self.enable_sfx else "SFX disabled"
                            await session.send_tool_response(
                                function_responses=[
                                    types.FunctionResponse(
                                        name=call.name,
                                        id=call.id,
                                        response={"result": res},
                                    )
                                ]
                            )

                # Handle model spoken audio & transcript
                if response.server_content:
                    sc = response.server_content
                    ot = getattr(sc, "output_transcription", None)
                    if ot and ot.text:
                        print(ot.text, end="", flush=True)
                        transcript_chunks.append(ot.text)

                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                if first_audio_ms is None:
                                    first_audio_ms = int((time.time() - t_send) * 1000)
                                audio_chunks.append(part.inline_data.data)

                    if sc.turn_complete:
                        print("\n✨ [Turn Complete]")
                        break

        total_audio = b"".join(audio_chunks)
        duration_sec = len(total_audio) / (24000 * 2) if total_audio else 0.0
        full_transcript = "".join(transcript_chunks).strip()

        print(f"\n📊 Performance Metrics:")
        print(f"   • Time to First Audio (TTFA): {first_audio_ms or 0}ms")
        print(f"   • Audio Duration: {duration_sec:.2f}s ({len(total_audio):,} bytes)")
        if triggered_sfx:
            print(f"   • Co-timed Sound Effects: {', '.join(triggered_sfx)}")

        # Save audio file
        out_wav = Path(f"/tmp/gemini_live_{int(time.time())}.wav")
        if total_audio:
            with wave.open(str(out_wav), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(total_audio)

            if self.play_audio:
                try:
                    subprocess.run(["afplay", str(out_wav)], check=True)
                except Exception as e:
                    print(f"Audio playback error: {e}")

        return {
            "transcript": full_transcript,
            "audio_file": str(out_wav) if total_audio else None,
            "duration_sec": duration_sec,
            "ttfa_ms": first_audio_ms,
            "triggered_sfx": triggered_sfx,
        }

    async def run_interactive_loop(self):
        """Interactive terminal session: prompt or type jokes in real time."""
        print(f"\n🎭 Welcome to the Gemini 3.8 Live Comedy Studio!")
        print(f"   Model: {self.model} | Voice: {self.voice} | Mode: {self.mode}")
        print("   Type your topic, joke prompt, or heckle below. Type 'exit' or press Ctrl+C to quit.\n")

        while True:
            try:
                user_input = input("\n🎤 You > ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "q"):
                    print("👋 Exiting comedy studio. Keep 'em laughing!")
                    break

                await self.run_prompt(user_input)

            except (KeyboardInterrupt, EOFError):
                print("\n👋 Exiting comedy studio.")
                break


def main():
    parser = argparse.ArgumentParser(
        description="Gemini 3.8 Live Comedian & Demo Studio for VoiceFi"
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        default=None,
        help="Optional prompt or topic to execute once (e.g. 'Tell me a joke about Python')",
    )
    parser.add_argument(
        "-v",
        "--voice",
        default="Puck",
        choices=list(VALID_GEMINI_LIVE_VOICES),
        help="Voice persona (default: Puck)",
    )
    parser.add_argument(
        "-m",
        "--mode",
        default="comedy",
        choices=["comedy", "roast", "banter", "assistant"],
        help="Persona mode (default: comedy)",
    )
    parser.add_argument(
        "-t",
        "--thinking",
        action="store_true",
        help="Use Gemini 3.8 Live Extended Thinking model",
    )
    parser.add_argument(
        "--thinking-level",
        default="LOW",
        choices=["MINIMAL", "LOW", "MEDIUM", "HIGH"],
        help="Thinking level for extended thinking (default: LOW)",
    )
    parser.add_argument(
        "--no-sfx",
        action="store_true",
        help="Disable synchronized punchline sound effects",
    )
    parser.add_argument(
        "--no-play",
        action="store_true",
        help="Do not play audio aloud through speakers",
    )

    args = parser.parse_args()

    runner = GeminiLiveComedianRunner(
        voice=args.voice,
        mode=args.mode,
        use_thinking=args.thinking,
        thinking_level=args.thinking_level,
        enable_sfx=not args.no_sfx,
        play_audio=not args.no_play,
    )

    if args.prompt:
        prompt_text = " ".join(args.prompt).strip()
        asyncio.run(runner.run_prompt(prompt_text))
    else:
        asyncio.run(runner.run_interactive_loop())


if __name__ == "__main__":
    main()
