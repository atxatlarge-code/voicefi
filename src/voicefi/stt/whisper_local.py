"""
Local faster-whisper STT provider.
Runs completely offline on Apple Silicon / CPU with zero API costs.
"""

import re
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
            self._model = WhisperModel(
                self.model_size, device=self.device, compute_type=compute_type
            )
        return self._model

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
            vad_filter=False,
            vad_parameters=dict(min_silence_duration_ms=500),
            condition_on_previous_text=False,
            repetition_penalty=1.15,
            no_repeat_ngram_size=3,
            temperature=[0.0, 0.2, 0.4],
        )

        texts = [segment.text.strip() for segment in segments]
        raw_text = " ".join(texts).strip()

        # Filter Whisper silence/noise hallucinations
        filtered = self.filter_hallucinations(raw_text)
        if not filtered:
            return ""

        # Apply phonetic normalization to developer jargon
        return PhoneticNormalizer.normalize(filtered)

    @staticmethod
    def filter_hallucinations(text: str) -> str:
        """Filter out common Whisper silence and low-energy hallucinations."""
        if not text:
            return ""

        stripped = text.strip()
        # Empty or punctuation only
        if not re.sub(r"[^\w\s]", "", stripped).strip():
            return ""

        # Non-speech sound descriptions in brackets or parentheses: [BLANK_AUDIO], [applause], (music)
        if re.match(r"^(\[.*?\]|\(.*?\))$", stripped, re.IGNORECASE):
            return ""

        # Common trailing silence hallucinations
        norm = re.sub(r"[^\w\s]", "", stripped).lower().strip()
        common_hallucinations = {
            "thank you",
            "thank you very much",
            "thanks for watching",
            "thank you for watching",
            "please subscribe",
            "subscribe to my channel",
            "subscribe to our channel",
            "don't forget to subscribe",
            "subtitles by",
            "you",
            "silence",
            "blank audio",
        }
        if norm in common_hallucinations:
            return ""

        # Subtitle credit lines
        if re.match(r"^(subtitles by|translated by|transcribed by)\b", norm):
            return ""

        # Strip Whisper hallucination loops (word runs and phrase loops)
        try:
            from voicefi.tts.normalizer import collapse_repetitive_artifacts

            stripped = collapse_repetitive_artifacts(stripped)
        except Exception:
            pass

        return stripped

