"""
Companion route handlers for speech-to-text (STT) and text-to-speech (TTS) streaming.
"""

import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, Optional

from aiohttp import web

from voicefi.config import load_config
from voicefi.stt import get_stt_engine
from voicefi.tts import get_tts_engine

logger = logging.getLogger(__name__)


def _resolve_tts_engine(cfg, **kwargs):
    server_mod = sys.modules.get("voicefi.companion.server")
    tts_fn = getattr(server_mod, "get_tts_engine", get_tts_engine) if server_mod else get_tts_engine
    return tts_fn(cfg, **kwargs)


def _resolve_stt_engine(cfg):
    server_mod = sys.modules.get("voicefi.companion.server")
    stt_fn = getattr(server_mod, "get_stt_engine", get_stt_engine) if server_mod else get_stt_engine
    return stt_fn(cfg)


class AudioHandlersMixin:
    """Mixin containing STT upload transcription and TTS voice synthesis endpoints."""

    async def handle_stt(self, request: web.Request) -> web.Response:
        """Transcribe uploaded audio blob from phone via local Whisper."""
        try:
            content_type = request.headers.get("Content-Type", "").lower()
            temp_ext = (
                ".webm"
                if "webm" in content_type
                else (
                    ".mp4"
                    if "mp4" in content_type or "m4a" in content_type or "aac" in content_type
                    else ".wav"
                )
            )
            with tempfile.NamedTemporaryFile(suffix=temp_ext, delete=False) as tmp:
                temp_path = Path(tmp.name)
                if "multipart" in content_type:
                    reader = await request.multipart()
                    field = await reader.next()
                    if not field:
                        return web.json_response({"error": "No audio file provided"}, status=400)
                    while True:
                        chunk = await field.read_chunk()
                        if not chunk:
                            break
                        tmp.write(chunk)
                else:
                    body = await request.read()
                    if not body:
                        return web.json_response({"error": "Empty audio body"}, status=400)
                    tmp.write(body)

            # Convert to clean 16kHz mono WAV using ffmpeg if available
            wav_path = temp_path.with_suffix(".16k.wav")
            transcribe_target = temp_path
            if temp_path.suffix.lower() != ".wav":
                try:
                    res = subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(temp_path),
                            "-ar",
                            "16000",
                            "-ac",
                            "1",
                            "-c:a",
                            "pcm_s16le",
                            str(wav_path),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    if res.returncode == 0 and wav_path.is_file() and wav_path.stat().st_size > 44:
                        transcribe_target = wav_path
                except Exception as e:
                    logger.warning("[STT] ffmpeg conversion warning: %s", e)

            stt = _resolve_stt_engine(self.config)
            try:
                transcript = stt.transcribe(transcribe_target)
            finally:
                temp_path.unlink(missing_ok=True)
                wav_path.unlink(missing_ok=True)

            return web.json_response({"transcript": transcript})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_tts(self, request: web.Request) -> web.Response:
        """Synthesize text to audio stream for phone playback using agent-specific voice persona."""
        try:
            data = await request.json()
            text = data.get("text", "").strip()
            agent_role = (
                data.get("agent_role")
                or data.get("agent")
                or request.query.get("agent")
                or "antigravity"
            )
            if not text:
                return web.Response(text="Empty text", status=400)

            cfg = load_config()
            self.config = cfg
            tts = _resolve_tts_engine(cfg, agent_name=agent_role)

            temp_out = None
            if hasattr(tts, "synthesize_to_file"):
                temp_out = Path(tempfile.gettempdir()) / f"vg_tts_{int(time.time() * 1000)}.mp3"
                await tts.synthesize_to_file(text, temp_out)
            elif hasattr(tts, "speak_to_file"):
                temp_out = Path(tempfile.gettempdir()) / f"vg_tts_{int(time.time() * 1000)}.aiff"
                tts.speak_to_file(text, temp_out)
            else:
                temp_out = Path(tempfile.gettempdir()) / f"vg_tts_{int(time.time() * 1000)}.aiff"
                subprocess.run(
                    ["say", "-o", str(temp_out), "--", text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            if temp_out and temp_out.is_file() and temp_out.suffix in (".aiff", ".wav"):
                m4a_out = temp_out.with_suffix(".m4a")
                try:
                    res = subprocess.run(
                        ["afconvert", "-f", "mp4f", "-d", "aac", str(temp_out), str(m4a_out)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
                    if res.returncode == 0 and m4a_out.is_file() and m4a_out.stat().st_size > 0:
                        temp_out.unlink(missing_ok=True)
                        temp_out = m4a_out
                except Exception:
                    pass

            if temp_out and temp_out.is_file():
                audio_bytes = temp_out.read_bytes()
                temp_out.unlink(missing_ok=True)
                if temp_out.suffix == ".m4a":
                    content_type = "audio/mp4"
                elif temp_out.suffix == ".mp3":
                    content_type = "audio/mpeg"
                else:
                    content_type = "audio/wav"
                return web.Response(body=audio_bytes, content_type=content_type)
            return web.Response(text="TTS synthesis failed", status=500)
        except Exception as e:
            return web.Response(text=f"TTS error: {e}", status=500)
