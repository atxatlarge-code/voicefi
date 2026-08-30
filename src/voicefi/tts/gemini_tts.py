"""
Google Gemini Neural Voice & Multimodal Live TTS Provider for VoiceFi.
Supports Google's native neural voices: Aoede, Puck, Charon, Kore, Fenrir.
"""

import base64
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any
import requests

from voicefi.tts.base import (
    BaseTTS,
    speech_turn_lock,
    DuplicateSpeechSuppressed,
    is_speech_interrupted,
    set_agent_audio_playing,
    is_agent_speaking,
)
from voicefi.audio.meeting_detection import is_user_on_call
from voicefi.tts.normalizer import normalize_tts_text

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiTTS(BaseTTS):
    """
    Text-to-Speech provider using Google Gemini Neural Voices.
    Supports Aoede, Puck, Charon, Kore, Fenrir with instant offline fallback.
    """

    VALID_VOICES = {"aoede": "Aoede", "puck": "Puck", "charon": "Charon", "kore": "Kore", "fenrir": "Fenrir"}

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice: str = "Aoede",
        model: str = "gemini-2.0-flash-exp",
        temperature: float = 0.3,
    ):
        super().__init__()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
        self.voice = self._normalize_voice_name(voice)
        self.model = model or "gemini-2.0-flash-exp"
        self.temperature = temperature
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    def _normalize_voice_name(self, voice: str) -> str:
        """Normalize voice name to valid Gemini voice."""
        if not voice:
            return "Aoede"
        clean = voice.lower().strip()
        return self.VALID_VOICES.get(clean, "Aoede")

    def stop(self) -> None:
        """Interrupt any ongoing speech playback."""
        self._stop_requested = True
        proc = self._current_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            self._current_process = None

    def _fallback_speak_direct(self, clean_text: str, turn_start_time: float = 0.0) -> None:
        """Fallback speak directly using macOS say without re-acquiring lock."""
        if not clean_text or not clean_text.strip() or self._stop_requested or is_speech_interrupted(turn_start_time):
            return
        try:
            from voicefi.tts.offline import is_voice_installed
            try:
                has_fb, exact_fb = is_voice_installed("Ava (Premium)")
                target_voice = exact_fb if (has_fb and exact_fb) else ("Ava" if has_fb else "Samantha")
            except Exception:
                target_voice = "Samantha"
            print(f"[GeminiTTS] ⚠️ Online synthesis unavailable; falling back to offline voice '{target_voice}'")
            cmd = ["say", "-v", target_voice, "--", clean_text]
            if not self._stop_requested and not is_speech_interrupted(turn_start_time) and is_agent_speaking():
                set_agent_audio_playing(True)
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._current_process = proc
                proc.wait()
                was_interrupted = self._stop_requested or is_speech_interrupted(turn_start_time) or (proc.returncode in (-9, -15, 137, 143))
                if not was_interrupted and proc.returncode != 0:
                    fallback = subprocess.Popen(["say", "--", clean_text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self._current_process = fallback
                    fallback.wait()
        except Exception as ex:
            print(f"[GeminiTTS] Offline fallback error: {ex}")
        finally:
            set_agent_audio_playing(False)
            self._current_process = None

    def _generate_audio_bytes(self, text: str, timeout: float = 4.0) -> Optional[bytes]:
        """Request audio synthesis from Gemini API."""
        if not self.api_key:
            return None

        url = f"{GEMINI_API_URL}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        body: Dict[str, Any] = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": self.voice
                        }
                    }
                }
            }
        }

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        inline_data = part.get("inlineData", {})
                        if inline_data.get("mimeType", "").startswith("audio/") and inline_data.get("data"):
                            return base64.b64decode(inline_data["data"])
            else:
                logger.debug("Gemini TTS non-200 response [%s]: %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.debug("Gemini TTS synthesis request failed: %s", e)

        return None

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize audio directly to a file without playing through speakers."""
        if not text or not text.strip():
            return False
        clean_text = normalize_tts_text(text)
        audio_bytes = self._generate_audio_bytes(clean_text)
        if audio_bytes:
            try:
                output_path.write_bytes(audio_bytes)
                return True
            except Exception:
                pass
        return False

    async def synthesize_to_file(self, text: str, output_path: Path) -> bool:
        """Asynchronously synthesize speech directly to an audio file."""
        return self.speak_to_file(text, output_path)

    def speak(self, text: str, block: bool = True) -> None:
        """Synthesize and play speech via Gemini Neural Voice with instant offline fallback."""
        if not text or not text.strip():
            return

        if is_user_on_call():
            print("[GeminiTTS] User is on a call. Skipping speech synthesis.")
            return

        clean_text = normalize_tts_text(text)
        self._stop_requested = False
        turn_start_time = time.time()

        def _run():
            try:
                with speech_turn_lock(
                    text=clean_text,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name=self.voice,
                ):
                    if self._stop_requested or is_speech_interrupted(turn_start_time):
                        return

                    audio_bytes = self._generate_audio_bytes(clean_text)
                    if not audio_bytes or self._stop_requested or is_speech_interrupted(turn_start_time):
                        if not self._stop_requested and not is_speech_interrupted(turn_start_time):
                            self._fallback_speak_direct(clean_text, turn_start_time=turn_start_time)
                        return

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        temp_path = Path(f.name)
                        temp_path.write_bytes(audio_bytes)

                    try:
                        if not self._stop_requested and not is_speech_interrupted(turn_start_time) and is_agent_speaking():
                            set_agent_audio_playing(True)
                            proc = subprocess.Popen(["afplay", str(temp_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            self._current_process = proc
                            proc.wait()
                    finally:
                        set_agent_audio_playing(False)
                        self._current_process = None
                        temp_path.unlink(missing_ok=True)

            except DuplicateSpeechSuppressed:
                pass
            except Exception as e:
                logger.debug("GeminiTTS speak error: %s", e)
                if not self._stop_requested and not is_speech_interrupted(turn_start_time):
                    self._fallback_speak_direct(clean_text, turn_start_time=turn_start_time)

        if block:
            _run()
        else:
            t = threading.Thread(target=_run, daemon=True)
            t.start()

    def stream_speak(self, text: str, block: bool = True) -> None:
        """Stream and speak audio with minimal latency."""
        self.speak(text, block=block)
