"""
Local faster-whisper STT provider.
Runs completely offline on Apple Silicon / CPU with zero API costs.
"""

from pathlib import Path
from typing import Union, Optional
import numpy as np
from talk2me.stt.base import BaseSTT


class WhisperLocalSTT(BaseSTT):
    """Local STT engine using faster-whisper."""

    def __init__(self, model_size: str = "base.en", language: str = "en", device: str = "auto"):
        self.model_size = model_size
        self.language = language
        self.device = device
        self._model = None

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            # On Apple Silicon / macOS, 'auto' selects cpu or best available
            compute_type = "int8" if self.device in ("auto", "cpu") else "float16"
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
        return self._model

    def transcribe(self, audio: Union[Path, str, np.ndarray], sample_rate: int = 16000) -> str:
        """Transcribe audio using local Whisper model."""
        model = self._get_model()

        audio_input = str(audio) if isinstance(audio, (Path, str)) else audio
        segments, info = model.transcribe(
            audio_input,
            language=self.language if self.language else None,
            beam_size=5,
            vad_filter=True,
        )

        texts = [segment.text.strip() for segment in segments]
        return " ".join(texts).strip()
