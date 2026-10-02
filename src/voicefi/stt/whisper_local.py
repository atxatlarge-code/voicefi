"""
Local faster-whisper STT provider.
Runs completely offline on Apple Silicon / CPU with zero API costs.
"""

import re
import threading
from pathlib import Path
from typing import Union, Optional, Dict, Tuple, Any
import numpy as np
from voicefi.stt.base import BaseSTT


from voicefi.stt.biasing import ProjectContextExtractor, PhoneticNormalizer

# Thread-safe global model cache to prevent repeated CTranslate2 allocations
_MODEL_CACHE: Dict[Tuple[str, str, str], Any] = {}
_MODEL_LOCK = threading.Lock()


def clear_whisper_model_cache():
    """Clear cached WhisperModel instances to allow complete memory reclamation."""
    with _MODEL_LOCK:
        _MODEL_CACHE.clear()


class WhisperLocalSTT(BaseSTT):
    """Local STT engine using faster-whisper with developer vocabulary biasing."""

    def __init__(self, model_size: str = "base.en", language: str = "en", device: str = "auto"):
        self.model_size = model_size
        self.language = language
        self.device = device
        self._model = None
        self.context_extractor = ProjectContextExtractor()

    def _get_model(self):
        if self._model is not None:
            return self._model

        compute_type = "int8" if self.device in ("auto", "cpu") else "float16"
        cache_key = (self.model_size, self.device, compute_type)
        if cache_key not in _MODEL_CACHE:
            with _MODEL_LOCK:
                if cache_key not in _MODEL_CACHE:
                    from faster_whisper import WhisperModel

                    _MODEL_CACHE[cache_key] = WhisperModel(
                        self.model_size, device=self.device, compute_type=compute_type
                    )
        self._model = _MODEL_CACHE[cache_key]
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

        try:
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

            texts = []
            for segment in segments:
                nsp = getattr(segment, "no_speech_prob", None)
                if isinstance(nsp, (int, float)) and nsp >= 0.65:
                    continue
                texts.append(segment.text.strip())
            raw_text = " ".join(texts).strip()

            # Filter Whisper silence/noise hallucinations
            filtered = self.filter_hallucinations(raw_text)
            if not filtered:
                return ""

            # Apply phonetic normalization to developer jargon
            return PhoneticNormalizer.normalize(filtered)
        except Exception as e:
            print(f"[WhisperLocalSTT] Transcription error: {e}")
            from voicefi.telemetry import capture_exception

            capture_exception(
                e,
                properties={
                    "component": "stt.whisper_local",
                    "provider": "whisper_local",
                    "model_size": self.model_size,
                    "device": self.device,
                    "$exception_fingerprint": ["stt.whisper_local", type(e).__name__],
                },
            )
            return ""

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
        raw_lower = stripped.lower().strip().rstrip(".")
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
            "mooji",
            "mooji org",
            "www mooji org",
            "wwwmoojiorg",
            "amara org",
            "opensubtitles org",
            "bye",
            "bye bye",
        }
        if norm in common_hallucinations or raw_lower in {"www.mooji.org", "mooji.org", "amara.org", "opensubtitles.org"}:
            return ""

        # Subtitle credit lines & trailing volunteer attribution
        if re.match(r"^(subtitles by|translated by|transcribed by|closed captioning)\b", norm):
            return ""
        if re.search(r"\b(mooji\.org|amara\.org|opensubtitles\.org)\b", raw_lower):
            return ""

        # Strip Whisper hallucination loops (word runs and phrase loops)
        try:
            from voicefi.tts.normalizer import collapse_repetitive_artifacts

            stripped = collapse_repetitive_artifacts(stripped)
        except Exception:
            pass

        return stripped
