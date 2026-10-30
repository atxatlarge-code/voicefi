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
from voicefi.integrations.screenpipe import record_audio_transcription
from voicefi.stt import get_stt_engine
from voicefi.tts import get_tts_engine
from voicefi.tts.base import BaseTTS

logger = logging.getLogger(__name__)


_TTS_AUDIO_CACHE: Dict[tuple[str, str], tuple[bytes, str]] = {}
_TTS_CACHE_MAX = 64


def get_cached_tts_audio(voice: str, text: str) -> Optional[tuple[bytes, str]]:
    key = ((voice or "default").strip().lower(), (text or "").strip())
    return _TTS_AUDIO_CACHE.get(key)


def set_cached_tts_audio(voice: str, text: str, audio_bytes: bytes, content_type: str) -> None:
    if not text or not audio_bytes:
        return
    key = ((voice or "default").strip().lower(), text.strip())
    if len(_TTS_AUDIO_CACHE) >= _TTS_CACHE_MAX and key not in _TTS_AUDIO_CACHE:
        try:
            oldest_key = next(iter(_TTS_AUDIO_CACHE))
            _TTS_AUDIO_CACHE.pop(oldest_key, None)
        except Exception:
            pass
    _TTS_AUDIO_CACHE[key] = (audio_bytes, content_type)


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

            # Convert to clean 16kHz mono WAV using ffmpeg if available (offloaded to thread pool)
            # Apply a gentle 70Hz highpass + dynamic audio normalizer in ffmpeg so raw MediaStream
            # recordings captured while the phone screen is locked (when browser AudioContext is suspended)
            # still get pocket-rustle filtering and muffled-voice gain boost on the server.
            import asyncio

            pocket_boost = request.headers.get("X-VoiceFi-Pocket-Boost", "").strip() == "1"
            audio_filter = (
                "highpass=f=80,dynaudnorm=f=150:g=15:p=0.95:m=4.0"
                if pocket_boost
                else "highpass=f=65,dynaudnorm=f=150:g=11:p=0.92:m=2.5"
            )

            wav_path = temp_path.with_suffix(".16k.wav")
            transcribe_target = temp_path
            if temp_path.suffix.lower() != ".wav":
                try:
                    res = await asyncio.to_thread(
                        subprocess.run,
                        [
                            "ffmpeg",
                            "-y",
                            "-i",
                            str(temp_path),
                            "-af",
                            audio_filter,
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
                transcript = await asyncio.to_thread(stt.transcribe, transcribe_target)
            finally:
                temp_path.unlink(missing_ok=True)
                wav_path.unlink(missing_ok=True)

            if transcript and str(transcript).strip():
                try:
                    record_audio_transcription(
                        transcription=transcript,
                        device="Companion Phone Mic",
                    )
                except Exception as tee_err:
                    logger.warning("[STT] Screenpipe dual-ingest tee warning: %s", tee_err)
                try:
                    if hasattr(self, "record_phone_transcript"):
                        self.record_phone_transcript(transcript, record_to_screenpipe=False)
                    else:
                        self._last_phone_transcript_at = time.time()
                        self._phone_recording_active = True
                except Exception:
                    pass

            return web.json_response({"transcript": transcript})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_tts(self, request: web.Request) -> web.Response:
        """Synthesize text to audio stream for phone playback using agent-specific voice persona."""
        try:
            data: Dict[str, Any] = {}
            if request.method != "GET":
                try:
                    data = await request.json()
                except Exception:
                    data = {}
            text = (data.get("text") or request.query.get("text") or "").strip()
            agent_role = (
                data.get("agent_role")
                or data.get("agent")
                or request.query.get("agent")
                or "antigravity"
            )
            voice_override = data.get("voice") or request.query.get("voice")
            if not text:
                return web.Response(text="Empty text", status=400)

            cfg = load_config()
            self.config = cfg

            # Apply Walken voice acting cadence if Walken / Continental is configured
            global_voice = str(getattr(getattr(cfg, "tts", None), "voice", "") or "").lower()
            global_provider = str(getattr(getattr(cfg, "tts", None), "provider", "") or "").lower()
            active_voice = str(voice_override or global_voice).lower()
            provider_override = None
            if "walken" in global_voice or "continental" in global_voice or "the_continental" in global_voice or "acting" in global_provider:
                from voicefi.tts.director import TheatricalDirector
                archetype = "continental" if "continental" in global_voice else "standard"
                text = TheatricalDirector.direct_walken_cadence(text, archetype=archetype, include_prefix=False)
                provider_override = "voice_acting"
                voice_override = getattr(cfg.tts, "voice", "the_continental")
            elif "walken" in active_voice or "continental" in active_voice or "the_continental" in active_voice:
                from voicefi.tts.director import TheatricalDirector
                archetype = "continental" if "continental" in active_voice else "standard"
                text = TheatricalDirector.direct_walken_cadence(text, archetype=archetype, include_prefix=False)
                provider_override = "voice_acting"

            cache_voice_key = str(voice_override or agent_role or "default")
            cached = get_cached_tts_audio(cache_voice_key, text)
            if cached:
                return web.Response(body=cached[0], content_type=cached[1])

            tts = _resolve_tts_engine(
                cfg,
                agent_name=agent_role,
                voice_override=voice_override,
                provider_override=provider_override,
            )

            temp_out = None
            if hasattr(tts, "speak_to_file") and type(tts).speak_to_file is not BaseTTS.speak_to_file:
                temp_out = Path(tempfile.gettempdir()) / f"vg_tts_{int(time.time() * 1000)}.wav"
                import asyncio
                await asyncio.to_thread(tts.speak_to_file, text, temp_out)
            elif hasattr(tts, "synthesize_to_file") and type(tts).synthesize_to_file is not BaseTTS.synthesize_to_file:
                temp_out = Path(tempfile.gettempdir()) / f"vg_tts_{int(time.time() * 1000)}.mp3"
                await tts.synthesize_to_file(text, temp_out)
            elif hasattr(tts, "speak_to_file"):
                temp_out = Path(tempfile.gettempdir()) / f"vg_tts_{int(time.time() * 1000)}.wav"
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
                set_cached_tts_audio(cache_voice_key, text, audio_bytes, content_type)
                return web.Response(body=audio_bytes, content_type=content_type)
            return web.Response(text="TTS synthesis failed", status=500)
        except Exception as e:
            return web.Response(text=f"TTS error: {e}", status=500)

