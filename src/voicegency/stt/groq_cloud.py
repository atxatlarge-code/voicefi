"""
Groq Cloud Whisper STT provider.
Ultra-fast transcription (~150ms latency) via Groq's high-speed Whisper LPU endpoints.
"""

from pathlib import Path
from typing import Union, Optional
import tempfile
import numpy as np
import requests
import soundfile as sf
from voicegency.stt.base import BaseSTT


from voicegency.stt.biasing import ProjectContextExtractor, PhoneticNormalizer


class GroqSTT(BaseSTT):
    """STT engine using Groq Whisper API with developer vocabulary biasing."""

    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo", language: str = "en"):
        self.api_key = api_key
        self.model = model
        self.language = language
        self.context_extractor = ProjectContextExtractor()

    def transcribe(
        self,
        audio: Union[Path, str, np.ndarray],
        sample_rate: int = 16000,
        prompt: Optional[str] = None,
    ) -> str:
        """Transcribe audio using Groq API with developer biasing."""
        if not self.api_key:
            raise ValueError("Groq API key is not configured in ~/.voicegency/config.yaml")

        if prompt is None:
            prompt = self.context_extractor.get_bias_prompt()

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
                if prompt:
                    data["prompt"] = prompt

                response = requests.post(url, headers=headers, files=files, data=data, timeout=10)

            if response.status_code == 200:
                result = response.json()
                raw_text = result.get("text", "").strip()
                return PhoneticNormalizer.normalize(raw_text)
            else:
                print(f"[GroqSTT] Error {response.status_code}: {response.text}")
                return ""
        finally:
            if temp_created:
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except Exception:
                    pass
