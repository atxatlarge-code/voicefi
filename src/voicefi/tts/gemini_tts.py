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

    VALID_VOICES = {
        "puck": "Puck",
        "charon": "Charon",
        "kore": "Kore",
        "fenrir": "Fenrir",
        "aoede": "Aoede",
        "zephyr": "Zephyr",
        "leda": "Leda",
        "orus": "Orus",
        "callirrhoe": "Callirrhoe",
        "autonoe": "Autonoe",
        "enceladus": "Enceladus",
        "iapetus": "Iapetus",
        "umbriel": "Umbriel",
        "algieba": "Algieba",
        "despina": "Despina",
        "erinome": "Erinome",
        "algenib": "Algenib",
        "rasalgethi": "Rasalgethi",
        "laomedeia": "Laomedeia",
        "achernar": "Achernar",
        "alnilam": "Alnilam",
        "schedar": "Schedar",
        "gacrux": "Gacrux",
        "pulcherrima": "Pulcherrima",
        "achird": "Achird",
        "zubenelgenubi": "Zubenelgenubi",
        "vindemiatrix": "Vindemiatrix",
        "sadachbia": "Sadachbia",
        "sadaltager": "Sadaltager",
        "sulafat": "Sulafat",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice: str = "Puck",
        model: str = "gemini-3.8-flash-tts",
        temperature: float = 0.3,
        style: Optional[str] = None,
    ):
        super().__init__()
        from voicefi.config import resolve_gemini_api_key

        self.api_key = (
            api_key
            or resolve_gemini_api_key()
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or ""
        )
        self.voice = self._normalize_voice_name(voice)
        self.model = model or "gemini-3.8-flash-tts"
        self.temperature = temperature
        self.style = style
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
        if (
            not clean_text
            or not clean_text.strip()
            or self._stop_requested
            or is_speech_interrupted(turn_start_time)
        ):
            return
        try:
            from voicefi.tts.offline import is_voice_installed

            try:
                has_fb, exact_fb = is_voice_installed("Ava (Premium)")
                target_voice = (
                    exact_fb if (has_fb and exact_fb) else ("Ava" if has_fb else "Samantha")
                )
            except Exception:
                target_voice = "Samantha"
            print(
                f"[GeminiTTS] ⚠️ Online synthesis unavailable; falling back to offline voice '{target_voice}'"
            )
            cmd = ["say", "-v", target_voice, "--", clean_text]
            if (
                not self._stop_requested
                and not is_speech_interrupted(turn_start_time)
                and is_agent_speaking()
            ):
                set_agent_audio_playing(True)
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._current_process = proc
                proc.wait()
                was_interrupted = (
                    self._stop_requested
                    or is_speech_interrupted(turn_start_time)
                    or (proc.returncode in (-9, -15, 137, 143))
                )
                if not was_interrupted and proc.returncode != 0:
                    fallback = subprocess.Popen(
                        ["say", "--", clean_text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._current_process = fallback
                    fallback.wait()
        except Exception as ex:
            print(f"[GeminiTTS] Offline fallback error: {ex}")
        finally:
            set_agent_audio_playing(False)
            self._current_process = None

    def _generate_audio_bytes_live(self, text: str) -> Optional[bytes]:
        """Synthesize audio using bidirectional WebSocket Live streaming."""
        if not self.api_key:
            return None
        try:
            import asyncio
            import io
            import wave
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.voice)
                    )
                ),
            )

            async def _run():
                chunks = []
                async with client.aio.live.connect(model=self.model, config=config) as session:
                    await session.send_realtime_input(text=text)
                    async for response in session.receive():
                        if response.server_content and response.server_content.model_turn:
                            for part in response.server_content.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    chunks.append(part.inline_data.data)
                        if response.server_content and response.server_content.turn_complete:
                            break
                if chunks:
                    raw_pcm = b"".join(chunks)
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(raw_pcm)
                    return buf.getvalue()
                return None

            return asyncio.run(_run())
        except Exception as e:
            logger.debug("Gemini Live synthesis failed: %s", e)
            return None

    def _generate_audio_bytes(
        self, text: str, style: Optional[str] = None, timeout: float = 15.0
    ) -> Optional[bytes]:
        """Request audio synthesis from Gemini API with optional style tags."""
        if not self.api_key:
            return None

        if "live" in self.model:
            live_bytes = self._generate_audio_bytes_live(text)
            if live_bytes:
                return live_bytes

        url = f"{GEMINI_API_URL}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}

        effective_style = style or self.style
        part_dict: Dict[str, Any] = {"text": text}
        if effective_style:
            part_dict["speech_metadata"] = {"style": str(effective_style)}

        body: Dict[str, Any] = {
            "contents": [{"parts": [part_dict]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}},
            },
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
                        if inline_data.get("mimeType", "").startswith("audio/") and inline_data.get(
                            "data"
                        ):
                            return base64.b64decode(inline_data["data"])
            else:
                logger.debug(
                    "Gemini TTS non-200 response [%s]: %s", resp.status_code, resp.text[:200]
                )
        except Exception as e:
            logger.debug("Gemini TTS synthesis request failed: %s", e)

        return None

    def generate_dialogue_bytes(
        self,
        turns: list[Dict[str, Any]],
        speakers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> Optional[bytes]:
        """Synthesize multi-speaker scripted dialogue from Gemini 3.8 Flash TTS."""
        if not self.api_key or not turns:
            return None

        # Collect unique speakers
        unique_speakers: list[str] = []
        for t in turns:
            spk = t.get("speaker", "Speaker")
            if spk not in unique_speakers:
                unique_speakers.append(spk)

        resolved_speakers: Dict[str, str] = {}
        if speakers:
            resolved_speakers = {k: self._normalize_voice_name(v) for k, v in speakers.items()}
        else:
            default_voices = [self.voice, "Charon" if self.voice != "Charon" else "Puck"]
            for i, spk in enumerate(unique_speakers):
                resolved_speakers[spk] = default_voices[i % len(default_voices)]

        # Gemini MultiSpeakerVoiceConfig requires exactly 2 speaker configurations
        speaker_configs = [
            {"speaker": spk_name, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}}
            for spk_name, voice_name in list(resolved_speakers.items())[:2]
        ]

        script_parts = []
        for turn in turns:
            spk = turn.get("speaker", unique_speakers[0] if unique_speakers else "Speaker")
            txt = normalize_tts_text(turn.get("text", ""))
            if not txt:
                continue
            meta: Dict[str, Any] = {"speaker": spk}
            if turn.get("style"):
                meta["style"] = str(turn["style"])
            script_parts.append({"text": txt, "speech_metadata": meta})

        if not script_parts:
            return None

        url = f"{GEMINI_API_URL}/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        body: Dict[str, Any] = {
            "contents": [{"parts": script_parts}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "multi_speaker_voice_config": {"speaker_voice_configs": speaker_configs}
                },
            },
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
                        if inline_data.get("mimeType", "").startswith("audio/") and inline_data.get(
                            "data"
                        ):
                            return base64.b64decode(inline_data["data"])
            else:
                logger.debug(
                    "Gemini TTS dialogue non-200 response [%s]: %s",
                    resp.status_code,
                    resp.text[:200],
                )
        except Exception as e:
            logger.debug("Gemini TTS dialogue request failed: %s", e)

        return None

    def speak_to_file(self, text: str, output_path: Path, style: Optional[str] = None) -> bool:
        """Synthesize audio directly to a file without playing through speakers."""
        if not text or not text.strip():
            return False
        clean_text = normalize_tts_text(text)
        audio_bytes = self._generate_audio_bytes(clean_text, style=style)
        if audio_bytes:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(audio_bytes)
                return True
            except Exception:
                pass
        return False

    async def synthesize_to_file(
        self, text: str, output_path: Path, style: Optional[str] = None
    ) -> bool:
        """Asynchronously synthesize speech directly to an audio file."""
        return self.speak_to_file(text, output_path, style=style)

    def synthesize_dialogue_to_file(
        self,
        turns: list[Dict[str, Any]],
        output_path: Path,
        speakers: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Synthesize multi-speaker scripted dialogue directly to audio file."""
        audio_bytes = self.generate_dialogue_bytes(turns, speakers=speakers)
        if audio_bytes:
            try:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(audio_bytes)
                return True
            except Exception as e:
                logger.error("Failed writing dialogue audio to %s: %s", output_path, e)
        return False

    def speak(self, text: str, block: bool = True, style: Optional[str] = None) -> None:
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
                    app_name=getattr(self, "app_name", "Antigravity"),
                    conv_id=getattr(self, "conv_id", ""),
                    workspace_path=getattr(self, "workspace_path", ""),
                ):
                    nonlocal turn_start_time
                    turn_start_time = time.time()
                    self._stop_requested = False

                    if self._stop_requested or is_speech_interrupted(turn_start_time):
                        return

                    audio_bytes = self._generate_audio_bytes(clean_text, style=style)
                    if (
                        not audio_bytes
                        or self._stop_requested
                        or is_speech_interrupted(turn_start_time)
                    ):
                        if not self._stop_requested and not is_speech_interrupted(turn_start_time):
                            self._fallback_speak_direct(clean_text, turn_start_time=turn_start_time)
                        return

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        temp_path = Path(f.name)
                        temp_path.write_bytes(audio_bytes)

                    try:
                        if (
                            not self._stop_requested
                            and not is_speech_interrupted(turn_start_time)
                            and is_agent_speaking()
                        ):
                            set_agent_audio_playing(True)
                            proc = subprocess.Popen(
                                ["afplay", str(temp_path)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
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

    def speak_dialogue(
        self,
        turns: list[Dict[str, Any]],
        speakers: Optional[Dict[str, str]] = None,
        block: bool = True,
    ) -> None:
        """Synthesize and play multi-speaker dialogue with turn locking."""
        if not turns:
            return
        if is_user_on_call():
            print("[GeminiTTS] User is on a call. Skipping dialogue playback.")
            return

        full_transcript = " ".join(t.get("text", "") for t in turns)
        self._stop_requested = False
        turn_start_time = time.time()

        def _run():
            try:
                with speech_turn_lock(
                    text=full_transcript,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name="Dialogue",
                    app_name=getattr(self, "app_name", "Antigravity"),
                    conv_id=getattr(self, "conv_id", ""),
                    workspace_path=getattr(self, "workspace_path", ""),
                ):
                    nonlocal turn_start_time
                    turn_start_time = time.time()
                    self._stop_requested = False

                    if self._stop_requested or is_speech_interrupted(turn_start_time):
                        return

                    audio_bytes = self.generate_dialogue_bytes(turns, speakers=speakers)
                    if (
                        not audio_bytes
                        or self._stop_requested
                        or is_speech_interrupted(turn_start_time)
                    ):
                        return

                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        temp_path = Path(f.name)
                        temp_path.write_bytes(audio_bytes)

                    try:
                        if (
                            not self._stop_requested
                            and not is_speech_interrupted(turn_start_time)
                            and is_agent_speaking()
                        ):
                            set_agent_audio_playing(True)
                            proc = subprocess.Popen(
                                ["afplay", str(temp_path)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            self._current_process = proc
                            proc.wait()
                    finally:
                        set_agent_audio_playing(False)
                        self._current_process = None
                        temp_path.unlink(missing_ok=True)
            except DuplicateSpeechSuppressed:
                pass
            except Exception as e:
                logger.debug("GeminiTTS speak_dialogue error: %s", e)

        if block:
            _run()
        else:
            t = threading.Thread(target=_run, daemon=True)
            t.start()

    def stream_speak(self, text: str, block: bool = True, style: Optional[str] = None) -> None:
        """Stream and speak audio with minimal latency."""
        self.speak(text, block=block, style=style)
