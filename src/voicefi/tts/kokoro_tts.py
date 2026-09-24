"""
Kokoro-82M ONNX TTS Provider for VoiceFi.
Provides fast, lightweight, 100% offline neural text-to-speech using ONNX Runtime.
82M parameters, CPU/MPS realtime, 24kHz output, Apache 2.0 license.
"""

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Tuple, Union

import soundfile as sf

from voicefi.tts.base import (
    BaseTTS,
    set_agent_audio_playing,
    set_agent_speaking,
    speech_turn_lock,
    stop_all_speech,
    DuplicateSpeechSuppressed,
)


KOKORO_VOICES = {
    # American English female
    "af_heart": "Heart (Warm & Expressive)",
    "af_bella": "Bella (Playful)",
    "af_nicole": "Nicole (Crisp)",
    "af_sarah": "Sarah (Direct)",
    "af_sky": "Sky (Breathy)",
    # American English male
    "am_adam": "Adam (Grounded & Technical)",
    "am_michael": "Michael (Deep & Authoritative)",
    "am_echo": "Echo (Resonant)",
    "am_eric": "Eric (Conversational)",
    "am_fenrir": "Fenrir (Rich)",
    "am_liam": "Liam (Crisp)",
    "am_onyx": "Onyx (Deep Bass)",
    # British English
    "bf_emma": "Emma (British Female)",
    "bf_isabella": "Isabella (British Female)",
    "bm_george": "George (British Male)",
    "bm_lewis": "Lewis (British Male)",
}
KOKORO_VOICE_MAP = KOKORO_VOICES


class KokoroTTS(BaseTTS):
    """
    Lightweight Kokoro-82M ONNX Neural TTS Provider.
    Zero-PyTorch dependency: runs entirely via ONNX Runtime and SoundFile.
    """

    _kokoro_instance = None

    def __init__(
        self,
        voice: str = "af_heart",
        speed: float = 1.0,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
    ):
        super().__init__()
        self.provider = "kokoro"
        self.voice = voice or "af_heart"
        self.speed = speed
        self.model_path = model_path
        self.voices_path = voices_path
        self._stop_requested = False

    @classmethod
    def get_models_dir(cls) -> Path:
        """Return directory where Kokoro ONNX model weights and voice vectors live."""
        d = Path.home() / ".voicefi" / "models" / "kokoro"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def is_available(cls) -> bool:
        """Check if kokoro-onnx package and model files are available."""
        try:
            import kokoro_onnx  # noqa: F401

            models_dir = cls.get_models_dir()
            model_file = models_dir / "kokoro-v0_19.onnx"
            voices_file = (
                models_dir / "voices.bin"
                if (models_dir / "voices.bin").exists()
                else models_dir / "voices.json"
            )
            return model_file.exists() and voices_file.exists()
        except ImportError:
            return False

    @classmethod
    def get_kokoro_instance(cls):
        """Lazy-load and cache the Kokoro ONNX engine."""
        if cls._kokoro_instance is not None:
            return cls._kokoro_instance

        try:
            from kokoro_onnx import Kokoro

            models_dir = cls.get_models_dir()
            model_file = models_dir / "kokoro-v0_19.onnx"
            voices_file = (
                models_dir / "voices.bin"
                if (models_dir / "voices.bin").exists()
                else models_dir / "voices.json"
            )

            if not model_file.exists() or not voices_file.exists():
                raise FileNotFoundError(
                    f"Kokoro model files not found in {models_dir}. "
                    "Download with: 'vifi voice download-kokoro'"
                )

            cls._kokoro_instance = Kokoro(str(model_file), str(voices_file))
            return cls._kokoro_instance
        except ImportError:
            raise ImportError(
                "kokoro-onnx is not installed. Install with: 'pip install kokoro-onnx'"
            )

    def synthesize_to_wav(self, text: str, output_path: str) -> bool:
        """Synthesize text into a 24kHz WAV file using Kokoro ONNX."""
        kokoro = self.get_kokoro_instance()
        target_voice = self.voice if self.voice in KOKORO_VOICES else "af"
        if target_voice == "af_heart":
            target_voice = "af"
        lang = "en-gb" if target_voice.startswith("b") else "en-us"

        samples, sample_rate = kokoro.create(
            text=text,
            voice=target_voice,
            speed=self.speed,
            lang=lang,
        )
        sf.write(output_path, samples, sample_rate)
        return True

    def speak_to_file(self, text: str, output_path: Any) -> bool:
        """Synthesize text and write to output audio file."""
        return self.synthesize_to_wav(text, str(output_path))

    def speak(
        self,
        text: str,
        block: bool = False,
        is_summary: bool = True,
        auto_listen: bool = False,
        conv_id: Optional[str] = None,
        step_index: Optional[int] = None,
    ) -> bool:
        """Synthesize and play speech aloud via afplay."""
        clean_text = text.strip()
        if not clean_text:
            return False

        # Attempt synthesis with Kokoro; if unavailable, fallback to MacSayTTS
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                temp_wav = tf.name

            self.synthesize_to_wav(clean_text, temp_wav)

            # Play audio via CoreAudio afplay
            import subprocess

            proc = subprocess.Popen(["afplay", temp_wav])
            if block:
                proc.wait()
            return True
        except Exception as e:
            from voicefi.tts.mac_say import MacSayTTS

            fallback = MacSayTTS(voice="Ava (Premium)")
            return fallback.speak(
                clean_text,
                block=block,
                is_summary=is_summary,
                auto_listen=auto_listen,
                conv_id=conv_id,
                step_index=step_index,
            )

    def stop(self) -> None:
        """Interrupt any ongoing speech playback."""
        self._stop_requested = True
        stop_all_speech()
        set_agent_speaking(False)
        set_agent_audio_playing(False)
