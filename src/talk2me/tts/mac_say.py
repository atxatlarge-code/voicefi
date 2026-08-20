"""
Native macOS 'say' TTS provider.
Zero-setup, lightning fast, offline, and supports all system installed voices.
"""

import subprocess
import threading
from typing import Optional, List
from talk2me.tts.base import BaseTTS


class MacSayTTS(BaseTTS):
    """TTS engine powered by macOS native `say` command."""

    def __init__(self, voice: str = "Samantha", rate: int = 200):
        self.voice = voice
        self.rate = rate
        self._current_process: Optional[subprocess.Popen] = None

    def speak(self, text: str, block: bool = True) -> None:
        """Speak text aloud using macOS say."""
        if not text or not text.strip():
            return

        cmd = ["say", "-v", self.voice, "-r", str(self.rate), text]

        def _run():
            try:
                self._current_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self._current_process.wait()
            except Exception as e:
                print(f"[MacSayTTS] Error speaking: {e}")
            finally:
                self._current_process = None

        if block:
            _run()
        else:
            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

    def stop(self) -> None:
        """Stop current speech synthesis."""
        if self._current_process and self._current_process.poll() is None:
            self._current_process.terminate()
            self._current_process = None

    @staticmethod
    def list_available_voices() -> List[str]:
        """List all voices available on the current macOS system."""
        try:
            output = subprocess.check_output(["say", "-v", "?"], text=True)
            voices = []
            for line in output.strip().split("\n"):
                if line:
                    voice_name = line.split()[0]
                    voices.append(voice_name)
            return voices
        except Exception:
            return ["Samantha", "Alex", "Victoria", "Daniel"]
