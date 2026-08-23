"""
Base abstract class for Speech-to-Text (STT) providers.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union, Optional
import numpy as np


class BaseSTT(ABC):
    """Abstract interface for STT transcription engines."""

    @abstractmethod
    def transcribe(
        self,
        audio: Union[Path, str, np.ndarray],
        sample_rate: int = 16000,
        prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe audio file or numpy array to text.
        
        Args:
            audio: Path to WAV audio file or numpy float32 audio array.
            sample_rate: Audio sample rate (default 16000).
            prompt: Optional context prompt / vocabulary hints for STT biasing.
            
        Returns:
            Transcribed text string.
        """
        pass


class BaseStreamingSTT(BaseSTT):
    """Abstract interface for real-time streaming STT engines."""

    @abstractmethod
    def feed_chunk(self, chunk: np.ndarray) -> Optional[str]:
        """Feed a live audio chunk and return any updated partial transcript."""
        pass

    @abstractmethod
    def finish_stream(self) -> str:
        """Finalize the stream and return full final transcription."""
        pass
