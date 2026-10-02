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
from voicefi.stt.base import BaseSTT


from voicefi.stt.biasing import ProjectContextExtractor, PhoneticNormalizer


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
        if audio is None:
            return ""
        if isinstance(audio, np.ndarray) and len(audio) == 0:
            return ""
        if isinstance(audio, (str, Path)):
            p = Path(audio)
            if not p.exists() or p.stat().st_size == 0:
                return ""

        if not self.api_key:
            raise ValueError("Groq API key is not configured in ~/.voicefi/config.yaml")

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
                err_text = response.text[:200]
                print(f"[GroqSTT] Error {response.status_code}: {err_text}")
                from voicefi.telemetry import capture_exception

                capture_exception(
                    RuntimeError(f"Groq API returned HTTP {response.status_code}"),
                    properties={
                        "component": "stt.groq",
                        "provider": "groq",
                        "provider_status_code": response.status_code,
                        "model": self.model,
                        "$exception_fingerprint": ["stt.groq", f"http_{response.status_code}"],
                    },
                )
                return ""
        except requests.exceptions.RequestException as e:
            print(f"[GroqSTT] Network error: {e}")
            from voicefi.telemetry import capture_exception

            capture_exception(
                e,
                properties={
                    "component": "stt.groq",
                    "provider": "groq",
                    "model": self.model,
                    "$exception_fingerprint": ["stt.groq", type(e).__name__],
                },
            )
            return ""
        except Exception as e:
            print(f"[GroqSTT] Unexpected error: {e}")
            from voicefi.telemetry import capture_exception

            capture_exception(
                e,
                properties={
                    "component": "stt.groq",
                    "provider": "groq",
                    "model": self.model,
                    "$exception_fingerprint": ["stt.groq", type(e).__name__],
                },
            )
            return ""
        finally:
            if temp_created:
                try:
                    Path(audio_path).unlink(missing_ok=True)
                except Exception:
                    pass
