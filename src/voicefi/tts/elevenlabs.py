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
from voicefi.tts.base import BaseTTS, speech_turn_lock
from voicefi.audio.meeting_detection import is_user_on_call


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
            
        if is_user_on_call():
            print("[ElevenLabsTTS] User is on a call. Skipping speech synthesis.")
            return

        def _run():
            with speech_turn_lock():
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

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize speech directly to an audio file without playing."""
        if not text or not text.strip() or not self.api_key:
            return False
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
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=15)
            if res.status_code == 200:
                p = Path(output_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(res.content)
                return p.is_file() and p.stat().st_size > 0
            else:
                print(f"[ElevenLabsTTS] API returned status {res.status_code}: {res.text}")
                return False
        except Exception as e:
            print(f"[ElevenLabsTTS] Error saving speech to file: {e}")
            return False

    async def synthesize_to_file(self, text: str, output_path: Path) -> bool:
        """Asynchronously synthesize speech directly to an audio file."""
        return self.speak_to_file(text, output_path)

    @classmethod
    def add_voice(
        cls,
        api_key: str,
        name: str,
        audio_file_paths: list,
        description: str = "",
        labels: Optional[dict] = None,
    ) -> dict:
        """
        Create a new custom cloned voice on ElevenLabs using audio sample files.
        Returns the API response containing `voice_id`.
        """
        if not api_key:
            raise ValueError("ElevenLabs API key is required to clone voice.")
        if not audio_file_paths:
            raise ValueError("At least one audio sample file is required for voice cloning.")

        url = "https://api.elevenlabs.io/v1/voices/add"
        headers = {
            "xi-api-key": api_key,
        }
        data = {
            "name": name,
            "description": description or f"Cloned voice of {name} for VoiceFi",
        }
        if labels:
            import json
            data["labels"] = json.dumps(labels)

        files = []
        file_handles = []
        try:
            for p in audio_file_paths:
                path_obj = Path(p)
                if not path_obj.exists():
                    continue
                fh = open(path_obj, "rb")
                file_handles.append(fh)
                files.append(("files", (path_obj.name, fh, "audio/wav")))

            if not files:
                raise ValueError("None of the specified audio sample files exist.")

            response = requests.post(url, headers=headers, data=data, files=files, timeout=45)
            if response.status_code == 200:
                return response.json()
            else:
                raise RuntimeError(
                    f"ElevenLabs API returned error ({response.status_code}): {response.text}"
                )
        finally:
            for fh in file_handles:
                try:
                    fh.close()
                except Exception:
                    pass

    @classmethod
    def get_voices(cls, api_key: str) -> list:
        """Fetch all available voices associated with the account."""
        if not api_key:
            return []
        url = "https://api.elevenlabs.io/v1/voices"
        headers = {"xi-api-key": api_key}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return data.get("voices", [])
        except Exception as e:
            print(f"[ElevenLabsTTS] Error fetching voices: {e}")
        return []

    @classmethod
    def delete_voice(cls, api_key: str, voice_id: str) -> bool:
        """Delete a custom cloned voice from ElevenLabs."""
        if not api_key or not voice_id:
            return False
        url = f"https://api.elevenlabs.io/v1/voices/{voice_id}"
        headers = {"xi-api-key": api_key}
        try:
            response = requests.delete(url, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"[ElevenLabsTTS] Error deleting voice {voice_id}: {e}")
            return False

