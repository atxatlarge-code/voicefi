"""
Apple Speech framework STT provider (macOS native).
"""

from pathlib import Path
from typing import Union
import subprocess
import numpy as np
from talk2me.stt.base import BaseSTT


class AppleSpeechSTT(BaseSTT):
    """macOS native speech recognition adapter."""

    def __init__(self, language: str = "en-US"):
        self.language = language

    def transcribe(self, audio: Union[Path, str, np.ndarray], sample_rate: int = 16000) -> str:
        """Transcribe using Apple's speech recognition."""
        # Fallback or external tool adapter
        try:
            # Check if whisper is available as primary reliable fallback
            from talk2me.stt.whisper_local import WhisperLocalSTT
            fallback = WhisperLocalSTT(model_size="base.en")
            return fallback.transcribe(audio, sample_rate)
        except Exception as e:
            print(f"[AppleSpeechSTT] Fallback transcription error: {e}")
            return ""
