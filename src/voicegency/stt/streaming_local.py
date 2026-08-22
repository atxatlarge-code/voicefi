"""
Local streaming faster-whisper STT provider.
Processes audio in real-time sliding chunks for low-latency live preview.
"""

from pathlib import Path
from typing import Union, Optional, List
import numpy as np
from voicegency.stt.base import BaseStreamingSTT
from voicegency.stt.whisper_local import WhisperLocalSTT


class StreamingLocalSTT(BaseStreamingSTT):
    """Local streaming STT engine using faster-whisper with sliding buffer."""

    def __init__(self, model_size: str = "base.en", language: str = "en", device: str = "auto"):
        self.underlying = WhisperLocalSTT(model_size=model_size, language=language, device=device)
        self.buffer: List[np.ndarray] = []
        self.sample_rate = 16000
        self._partial_text = ""
        self._chunks_since_last_partial = 0

    def feed_chunk(self, chunk: np.ndarray) -> Optional[str]:
        """Feed an audio chunk and periodically compute partial text."""
        self.buffer.append(chunk)
        self._chunks_since_last_partial += 1

        # Run partial transcription every ~10 chunks (0.5s of audio)
        if self._chunks_since_last_partial >= 10:
            self._chunks_since_last_partial = 0
            full_audio = np.concatenate(self.buffer, axis=0)
            if len(full_audio) >= self.sample_rate * 0.5:
                try:
                    self._partial_text = self.underlying.transcribe(full_audio, self.sample_rate)
                    return self._partial_text
                except Exception:
                    pass
        return None

    def finish_stream(self) -> str:
        """Finalize stream and return full accurate transcription."""
        if not self.buffer:
            return ""
        full_audio = np.concatenate(self.buffer, axis=0)
        self.buffer.clear()
        self._chunks_since_last_partial = 0
        return self.underlying.transcribe(full_audio, self.sample_rate)

    def transcribe(self, audio: Union[Path, str, np.ndarray], sample_rate: int = 16000) -> str:
        """Standard batch transcription entrypoint."""
        return self.underlying.transcribe(audio, sample_rate)
