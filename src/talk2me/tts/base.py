"""
Base abstract class, factory, and global stop utilities for Text-to-Speech (TTS).
"""

import subprocess
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


def stop_all_speech() -> None:
    """
    Instantly stop any active speech synthesis and audio playback on macOS.
    Kills any running 'say' or 'afplay' processes.
    """
    try:
        subprocess.run(["killall", "say"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

    try:
        subprocess.run(["killall", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
