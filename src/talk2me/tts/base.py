"""
Base abstract class and factory for Text-to-Speech (TTS) providers.
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseTTS(ABC):
    """Abstract interface for all TTS engines."""

    @abstractmethod
    def speak(self, text: str, block: bool = True) -> None:
        """
        Synthesize and speak the provided text aloud.
        
        Args:
            text: Text to speak.
            block: Whether to wait for audio playback to complete before returning.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Interrupt any ongoing speech playback."""
        pass
