"""
Local faster-whisper STT provider.
Runs completely offline on Apple Silicon / CPU with zero API costs.
"""

from pathlib import Path
from typing import Union, Optional
import numpy as np
from voicefi.stt.base import BaseSTT


from voicefi.stt.biasing import ProjectContextExtractor, PhoneticNormalizer


class WhisperLocalSTT(BaseSTT):
    """Local STT engine using faster-whisper with developer vocabulary biasing."""

    def __init__(self, model_size: str = "base.en", language: str = "en", device: str = "auto"):
        self.model_size = model_size
        self.language = language
        self.device = device
        self._model = None
        self.context_extractor = ProjectContextExtractor()

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            # On Apple Silicon / macOS, 'auto' selects cpu or best available
            compute_type = "int8" if self.device in ("auto", "cpu") else "float16"
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
        return self._model

    def transcribe(
        self,
        audio: Union[Path, str, np.ndarray],
        sample_rate: int = 16000,
        prompt: Optional[str] = None,
    ) -> str:
        """Transcribe audio using local Whisper model with developer biasing."""
        model = self._get_model()

        # Build biased initial prompt if none provided explicitly
        if prompt is None:
            prompt = self.context_extractor.get_bias_prompt()

        audio_input = str(audio) if isinstance(audio, (Path, str)) else audio
        segments, info = model.transcribe(
            audio_input,
            language=self.language if self.language else None,
            initial_prompt=prompt if prompt else None,
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False,
            repetition_penalty=1.15,
            no_repeat_ngram_size=3,
            temperature=[0.0, 0.2, 0.4],
        )

        texts = [segment.text.strip() for segment in segments]
        raw_text = " ".join(texts).strip()

        # Apply phonetic normalization to developer jargon
        return PhoneticNormalizer.normalize(raw_text)
