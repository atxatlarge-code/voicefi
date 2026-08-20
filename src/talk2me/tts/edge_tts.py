"""
Microsoft Edge Neural TTS provider.
High-quality natural sounding AI speech synthesis (free, no API key required).
"""

import asyncio
import tempfile
import subprocess
import threading
from pathlib import Path
from typing import Optional
from talk2me.tts.base import BaseTTS


class EdgeTTS(BaseTTS):
    """TTS engine using Edge TTS neural voices."""

    def __init__(self, voice: str = "en-US-ChristopherNeural", rate: int = 0):
        self.voice = voice
        self.rate_str = f"{rate:+d}%" if rate != 0 else "+0%"
        self._current_process: Optional[subprocess.Popen] = None

    async def _generate_audio(self, text: str, output_path: str) -> None:
        import edge_tts
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate_str)
        await communicate.save(output_path)

    def speak(self, text: str, block: bool = True) -> None:
        """Synthesize and play neural speech audio."""
        if not text or not text.strip():
            return

        def _run():
            temp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            temp_path = temp_mp3.name
            temp_mp3.close()

            try:
                # Run async generation
                asyncio.run(self._generate_audio(text, temp_path))
                
                # Play audio via macOS afplay
                self._current_process = subprocess.Popen(
                    ["afplay", temp_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._current_process.wait()
            except Exception as e:
                print(f"[EdgeTTS] Error generating or playing audio: {e}")
            finally:
                self._current_process = None
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass

        if block:
            _run()
        else:
            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

    def stop(self) -> None:
        """Stop current speech playback."""
        if self._current_process and self._current_process.poll() is None:
            self._current_process.terminate()
            self._current_process = None
