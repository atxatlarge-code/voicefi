"""
Groq Cloud Whisper STT provider.
Ultra-fast transcription (~150ms latency) via Groq's high-speed Whisper LPU endpoints.
"""

from pathlib import Path
from typing import Union
import tempfile
import numpy as np
import requests
import soundfile as sf
from talk2me.stt.base import BaseSTT


class GroqSTT(BaseSTT):
    """STT engine using Groq Whisper API."""

    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo", language: str = "en"):
        self.api_key = api_key
        self.model = model
        self.language = language

    def transcribe(self, audio: Union[Path, str, np.ndarray], sample_rate: int = 16000) -> str:
        """Transcribe audio using Groq API."""
        if not self.api_key:
            raise ValueError("Groq API key is not configured in ~/.talk2me/config.yaml")

        temp_created = False
        if isinstance(audio, np.ndarray):
            temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            audio_path = temp_file.name
            temp_file.close()
            sf.write(audio_path, audio, sample_rate)
            temp_created = True
        else:
            audio_path = str(audio)

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            with open(audio_path, "rb") as f:
                files = {"file": (Path(audio_path).name, f, "audio/wav")}
                data = {
                    "model": self.model,
                    "language": self.language,
                    "response_format": "json",
                }
                response = requests.post(url, headers=headers, files=files, data=data, timeout=10)

            if response.status_code == 200:
                result = response.json()
                return result.get("text", "").strip()
            else:
                print(f"[GroqSTT] Error {response.status_code}: {response.text}")
                return ""
        finally:
            if temp_created:
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except Exception:
                    pass
