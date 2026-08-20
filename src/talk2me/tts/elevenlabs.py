"""
ElevenLabs TTS provider (Pro Tier).
Ultra-realistic custom cloned and generative AI voices.
"""

import tempfile
import subprocess
import threading
from pathlib import Path
from typing import Optional
import requests
from talk2me.tts.base import BaseTTS


class ElevenLabsTTS(BaseTTS):
    """TTS engine using ElevenLabs REST API."""

    def __init__(self, api_key: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
        self.api_key = api_key
        self.voice_id = voice_id
        self._current_process: Optional[subprocess.Popen] = None

    def speak(self, text: str, block: bool = True) -> None:
        """Synthesize and play speech via ElevenLabs API."""
        if not text or not text.strip():
            return
        if not self.api_key:
            print("[ElevenLabsTTS] Error: API key is not configured.")
            return

        def _run():
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            headers = {
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            payload = {
                "text": text,
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }

            temp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            temp_path = temp_mp3.name
            temp_mp3.close()

            try:
                response = requests.post(url, json=payload, headers=headers, timeout=15)
                if response.status_code == 200:
                    with open(temp_path, "wb") as f:
                        f.write(response.content)

                    self._current_process = subprocess.Popen(
                        ["afplay", temp_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._current_process.wait()
                else:
                    print(f"[ElevenLabsTTS] API returned status {response.status_code}: {response.text}")
            except Exception as e:
                print(f"[ElevenLabsTTS] Error during synthesis: {e}")
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
        """Stop current playback."""
        if self._current_process and self._current_process.poll() is None:
            self._current_process.terminate()
            self._current_process = None
