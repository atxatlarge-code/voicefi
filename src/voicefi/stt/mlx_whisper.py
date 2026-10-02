"""
Apple Silicon native MLX Whisper STT provider.
Runs completely on Apple Silicon Metal GPU & Unified Memory via Apple MLX.
Sub-150ms transcription latency with zero CPU contention.
"""

import tempfile
import threading
from pathlib import Path
from typing import Union, Optional
import numpy as np
import soundfile as sf

from voicefi.stt.base import BaseSTT
from voicefi.stt.biasing import ProjectContextExtractor, PhoneticNormalizer


class MLXWhisperSTT(BaseSTT):
    """Local STT engine using mlx-whisper accelerated by Apple Silicon Metal GPU."""

    def __init__(
        self,
        model_name: str = "mlx-community/whisper-large-v3-turbo",
        language: str = "en",
        path_or_hf_repo: Optional[str] = None,
    ):
        self.model_name = path_or_hf_repo or model_name
        self.language = language
        self.context_extractor = ProjectContextExtractor()
        self._lock = threading.Lock()

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
            import mlx_whisper
        except ImportError as e:
            from voicefi.telemetry import capture_exception

            capture_exception(
                e,
                properties={
                    "component": "stt.mlx_whisper",
                    "provider": "mlx_whisper",
                    "$exception_fingerprint": ["stt.mlx_whisper", "ImportError"],
                },
            )
            raise ImportError(
                "mlx-whisper is required for MLXWhisperSTT on Apple Silicon. "
                "Install it with `pip install mlx-whisper` on macOS with Apple Silicon Metal support."
            ) from e

        # Build biased initial prompt if none provided explicitly
        if prompt is None:
            prompt = self.context_extractor.get_bias_prompt()

        temp_wav = None
        try:
            if isinstance(audio, np.ndarray):
                # Save numpy array to a temporary WAV file for mlx_whisper
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                    temp_wav = tf.name
                sf.write(temp_wav, audio, sample_rate)
                audio_path = temp_wav
            else:
                audio_path = str(audio)

            try:
                with self._lock:
                    result = mlx_whisper.transcribe(
                        audio_path,
                        path_or_hf_repo=self.model_name,
                        language=self.language if self.language else None,
                        initial_prompt=prompt if prompt else None,
                        temperature=(0.0, 0.2, 0.4),
                    )
            except Exception as e:
                print(f"[MLXWhisperSTT] Transcription error: {e}")
                from voicefi.telemetry import capture_exception

                capture_exception(
                    e,
                    properties={
                        "component": "stt.mlx_whisper",
                        "provider": "mlx_whisper",
                        "model_name": self.model_name,
                        "$exception_fingerprint": ["stt.mlx_whisper", type(e).__name__],
                    },
                )
                return ""

            raw_text = (
                result.get("text", "").strip() if isinstance(result, dict) else str(result).strip()
            )

            # Filter Whisper silence/noise hallucinations
            filtered = self.filter_hallucinations(raw_text)
            if not filtered:
                return ""

            # Apply phonetic normalization to developer jargon
            return PhoneticNormalizer.normalize(filtered)

        finally:
            if temp_wav and Path(temp_wav).exists():
                try:
                    Path(temp_wav).unlink()
                except Exception:
                    pass

    @staticmethod
    def filter_hallucinations(text: str) -> str:
        """Filter out common Whisper silence and low-energy hallucinations."""
        from voicefi.stt.whisper_local import WhisperLocalSTT

        return WhisperLocalSTT.filter_hallucinations(text)
