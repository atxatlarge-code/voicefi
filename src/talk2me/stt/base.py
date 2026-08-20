"""
Base abstract class for Speech-to-Text (STT) providers.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union
import numpy as np


class BaseSTT(ABC):
    """Abstract interface for STT transcription engines."""

    @abstractmethod
    def transcribe(self, audio: Union[Path, str, np.ndarray], sample_rate: int = 16000) -> str:
        """
        Transcribe audio file or numpy array to text.
        
        Args:
            audio: Path to WAV audio file or numpy float32 audio array.
            sample_rate: Audio sample rate (default 16000).
            
        Returns:
            Transcribed text string.
        """
        pass
