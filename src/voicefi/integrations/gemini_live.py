"""
Gemini 3.8 Live Integration Module for VoiceFi.

Provides real-time bidirectional WebSocket streaming to Google Gemini 3.8 Live
and Gemini 3.8 Live Extended Thinking, supporting affective dialogue,
comedic timing, and co-timed punchline sound effects.
"""

import asyncio
import logging
import os
import subprocess
import time
import wave
from pathlib import Path
from typing import Dict, Any, Optional, List

from voicefi.config import load_config, resolve_gemini_api_key, VALID_GEMINI_LIVE_VOICES

logger = logging.getLogger("voicefi.integrations.gemini_live")

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
        for k, p in AVAILABLE_SFX.items():
            if k in clean_name and p.is_file():
                sfx_file = p
                clean_name = k
                break

    if sfx_file and sfx_file.is_file():
        logger.info("🥁 [SFX] Triggered: %s (%s)", clean_name.upper(), sfx_file.name)
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


class GeminiLiveRunner:
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

        try:
            from google import genai
            from google.genai import types
            self._genai = genai
            self._types = types
        except ImportError:
            raise ImportError("google-genai is required. Install with: pip install google-genai>=1.65.0")

        self.model = "gemini-3.8-live-extended-thinking" if use_thinking else model
        self.voice = voice if voice in VALID_GEMINI_LIVE_VOICES else "Puck"
        self.mode = mode
        self.use_thinking = use_thinking
        self.thinking_level = thinking_level.upper()
        self.enable_sfx = enable_sfx
        self.play_audio = play_audio
        self.client = self._genai.Client(api_key=self.api_key)

    def _build_live_config(self):
        system_instruction_text = SYSTEM_INSTRUCTIONS.get(self.mode, SYSTEM_INSTRUCTIONS["comedy"])

        tools = [play_sound_effect] if self.enable_sfx else None

        thinking_cfg = None
        if self.use_thinking or "extended-thinking" in self.model:
            t_level = getattr(self._types.ThinkingLevel, self.thinking_level, self._types.ThinkingLevel.LOW)
            thinking_cfg = self._types.ThinkingConfig(thinking_level=t_level)

        return self._types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self._types.Content(
                parts=[self._types.Part.from_text(text=system_instruction_text)]
            ),
            speech_config=self._types.SpeechConfig(
                voice_config=self._types.VoiceConfig(
                    prebuilt_voice_config=self._types.PrebuiltVoiceConfig(
                        voice_name=self.voice
                    )
                )
            ),
            thinking_config=thinking_cfg,
            output_audio_transcription=self._types.AudioTranscriptionConfig(),
            tools=tools,
        )

    async def run_prompt(self, prompt: str) -> Dict[str, Any]:
        """Send a single prompt and stream speech output + live transcription."""
        config = self._build_live_config()

        t0 = time.time()
        audio_chunks = []
        transcript_chunks = []
        first_audio_ms = None
        triggered_sfx = []

        async with self.client.aio.live.connect(model=self.model, config=config) as session:
            t_conn = time.time()
            conn_ms = int((t_conn - t0) * 1000)
            logger.debug("Connected to %s in %dms", self.model, conn_ms)

            t_send = time.time()
            await session.send_realtime_input(text=prompt)

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
                                    self._types.FunctionResponse(
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
                        transcript_chunks.append(ot.text)

                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                if first_audio_ms is None:
                                    first_audio_ms = int((time.time() - t_send) * 1000)
                                audio_chunks.append(part.inline_data.data)

                    if sc.turn_complete:
                        break

        total_audio = b"".join(audio_chunks)
        duration_sec = len(total_audio) / (24000 * 2) if total_audio else 0.0
        full_transcript = "".join(transcript_chunks).strip()

        # Save audio file
        out_wav = Path(f"/tmp/gemini_live_{int(time.time())}.wav")
        audio_data_uri = None
        if total_audio:
            with wave.open(str(out_wav), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(total_audio)

            try:
                import base64
                wav_bytes = out_wav.read_bytes()
                audio_data_uri = f"data:audio/wav;base64,{base64.b64encode(wav_bytes).decode('ascii')}"
            except Exception as e:
                logger.debug("Failed to encode audio_data_uri: %s", e)

            if self.play_audio:
                try:
                    subprocess.run(["afplay", str(out_wav)], check=True)
                except Exception as e:
                    logger.debug("Audio playback error: %s", e)

        return {
            "transcript": full_transcript,
            "audio_file": str(out_wav) if total_audio else None,
            "audio_data_uri": audio_data_uri,
            "duration_sec": duration_sec,
            "ttfa_ms": first_audio_ms,
            "conn_ms": conn_ms if 'conn_ms' in locals() else None,
            "triggered_sfx": triggered_sfx,
        }
