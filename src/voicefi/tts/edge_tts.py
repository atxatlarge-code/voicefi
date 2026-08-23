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
from voicefi.tts.base import BaseTTS, speech_turn_lock


def normalize_edge_rate(rate: any) -> str:
    """
    Normalize rate input into an EdgeTTS rate string (e.g. '-25%', '+0%', '+10%').
    Handles:
      - Offset percentage int/float: -25 -> '-25%', +10 -> '+10%', 0 -> '+0%'
      - Speed percentage: 75 -> '-25%' (75% speed), 100 -> '+0%', 120 -> '+20%'
      - WPM values: 150 -> '-25%', 200 -> '+0%', 250 -> '+25%'
      - Strings: '-25%', '75%', '-25', '150', '150wpm'
    """
    if rate is None:
        return "+0%"

    if isinstance(rate, str):
        rate_str = rate.strip().lower()
        if rate_str.endswith("wpm"):
            try:
                rate = float(rate_str[:-3].strip())
            except ValueError:
                return "+0%"
        elif (rate_str.startswith("+") or rate_str.startswith("-")) and rate_str.endswith("%"):
            return rate_str
        elif rate_str.endswith("%"):
            try:
                val = float(rate_str[:-1].strip())
                offset = int(round(val - 100))
                return f"{offset:+d}%"
            except ValueError:
                return "+0%"
        else:
            try:
                rate = float(rate_str)
            except ValueError:
                return "+0%"

    if isinstance(rate, (int, float)):
        if rate == 0:
            return "+0%"
        # Direct negative offset e.g. -25 for -25%
        if -90 <= rate < 0:
            return f"{int(round(rate)):+d}%"
        # Direct small positive offset e.g. +5, +10, +25
        if 1 <= rate <= 45:
            return f"{int(round(rate)):+d}%"
        # Percentage of normal speed e.g. 50% - 120% (e.g. 75 for 75% speed)
        if 45 < rate <= 120:
            offset = int(round(rate - 100))
            return f"{offset:+d}%"
        # WPM (121 - 400 WPM, where 200 WPM is baseline 100% -> 150 WPM is 75% speed / -25%)
        if rate > 120:
            offset = int(round(((rate - 200.0) / 200.0) * 100))
            return f"{offset:+d}%"

    return "+0%"


class EdgeTTS(BaseTTS):
    """TTS engine using Edge TTS neural voices with reliable playback and turn queuing."""

    def __init__(self, voice: str = "en-US-ChristopherNeural", rate: any = 0, streaming: bool = True):
        self.voice = voice
        self.rate_str = normalize_edge_rate(rate)
        self.streaming = streaming
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    async def _generate_audio(self, text: str, output_path: str) -> None:
        import edge_tts
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate_str)
        await communicate.save(output_path)

    def speak(self, text: str, block: bool = True) -> None:
        """Synthesize and play neural speech audio with cross-process turn queuing."""
        if not text or not text.strip():
            return

        self._stop_requested = False

        def _run():
            with speech_turn_lock():
                if self._stop_requested:
                    return

                temp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                temp_path = temp_mp3.name
                temp_mp3.close()

                try:
                    asyncio.run(self._generate_audio(text, temp_path))
                    if not self._stop_requested and Path(temp_path).is_file() and Path(temp_path).stat().st_size > 0:
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

    def stream_speak(self, text: str, block: bool = True) -> None:
        """Explicit low-latency streaming entrypoint."""
        self.speak(text, block=block)

    def stop(self) -> None:
        """Stop current speech playback."""
        self._stop_requested = True
        if self._current_process and self._current_process.poll() is None:
            self._current_process.terminate()
            self._current_process = None
