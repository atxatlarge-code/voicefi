import time
import tempfile
import subprocess
import threading
from pathlib import Path
from typing import Optional
import requests
from voicefi.tts.base import BaseTTS, speech_turn_lock, DuplicateSpeechSuppressed
from voicefi.audio.meeting_detection import is_user_on_call
from voicefi.tts.normalizer import normalize_tts_text


class ElevenLabsTTS(BaseTTS):
    """TTS engine using ElevenLabs Flash v2.5 & Turbo v2.5 low-latency API."""

    def __init__(
        self,
        api_key: str,
        voice_id: str = "21m00Tcm4TlvDq8ikWAM",
        model_id: str = "eleven_flash_v2_5",
        stability: float = 0.5,
        similarity_boost: float = 0.8,
    ):
        super().__init__()
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id or "eleven_flash_v2_5"
        self.stability = stability
        self.similarity_boost = similarity_boost
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    def stop(self) -> None:
        """Interrupt any ongoing speech playback."""
        self._stop_requested = True
        proc = self._current_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            self._current_process = None

    def _fallback_speak_direct(self, clean_text: str, turn_start_time: float = 0.0) -> None:
        """Fallback speak directly using macOS say without re-acquiring lock."""
        from voicefi.tts.base import (
            is_speech_interrupted,
            set_agent_audio_playing,
            is_agent_speaking,
        )

        if (
            not clean_text
            or not clean_text.strip()
            or self._stop_requested
            or is_speech_interrupted(turn_start_time)
        ):
            return
        try:
            from voicefi.tts.offline import is_voice_installed

            try:
                has_fb, exact_fb = is_voice_installed("Ava (Premium)")
                target_voice = (
                    exact_fb if (has_fb and exact_fb) else ("Ava" if has_fb else "Samantha")
                )
            except Exception:
                target_voice = "Samantha"
            print(
                f"[ElevenLabsTTS] ⚠️ Online synthesis unavailable; falling back to offline voice '{target_voice}'"
            )
            cmd = ["say", "-v", target_voice, "--", clean_text]
            if (
                not self._stop_requested
                and not is_speech_interrupted(turn_start_time)
                and is_agent_speaking()
            ):
                set_agent_audio_playing(True)
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._current_process = proc
                proc.wait()
                was_interrupted = (
                    self._stop_requested
                    or is_speech_interrupted(turn_start_time)
                    or (proc.returncode in (-9, -15, 137, 143))
                )
                if not was_interrupted and proc.returncode != 0:
                    fallback = subprocess.Popen(
                        ["say", "--", clean_text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._current_process = fallback
                    fallback.wait()
        except Exception as ex:
            print(f"[ElevenLabsTTS] Offline fallback error: {ex}")
        finally:
            set_agent_audio_playing(False)
            self._current_process = None

    def _safe_fallback(self, clean_text: str, turn_start_time: float = 0.0) -> None:
        try:
            self._fallback_speak_direct(clean_text, turn_start_time=turn_start_time)
        except TypeError:
            self._fallback_speak_direct(clean_text)

    def speak(self, text: str, block: bool = True) -> None:
        """Synthesize and play speech via ElevenLabs Flash streaming API with offline fallback."""
        if not text or not text.strip():
            return

        if is_user_on_call():
            print("[ElevenLabsTTS] User is on a call. Skipping speech synthesis.")
            return

        clean_text = normalize_tts_text(text)
        self._stop_requested = False
        turn_start_time = time.time()

        def _run():
            try:
                with speech_turn_lock(
                    text=clean_text,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name=getattr(
                        self, "persona_name", getattr(self, "voice_id", "ElevenLabs")
                    ),
                ):
                    from voicefi.tts.base import is_speech_interrupted

                    if self._stop_requested or is_speech_interrupted(turn_start_time):
                        return

                    if not self.api_key:
                        print(
                            "[ElevenLabsTTS] API key not configured; falling back to offline voice."
                        )
                        self._safe_fallback(clean_text, turn_start_time=turn_start_time)
                        return

                    url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream?optimize_streaming_latency=3"
                    headers = {
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    }
                    payload = {
                        "text": clean_text,
                        "model_id": self.model_id,
                        "voice_settings": {
                            "stability": self.stability,
                            "similarity_boost": self.similarity_boost,
                            "style": 0.0,
                            "use_speaker_boost": True,
                        },
                    }

                    temp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    temp_path = temp_mp3.name
                    temp_mp3.close()

                    try:
                        response = requests.post(url, json=payload, headers=headers, timeout=15)
                        if response.status_code == 200:
                            with open(temp_path, "wb") as f:
                                f.write(response.content)

                            if not self._stop_requested and not is_speech_interrupted(
                                turn_start_time
                            ):
                                proc = subprocess.Popen(
                                    ["afplay", temp_path],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                )
                                self._current_process = proc
                                proc.wait()
                                was_interrupted = (
                                    self._stop_requested
                                    or is_speech_interrupted(turn_start_time)
                                    or (proc.returncode in (-9, -15, 137, 143))
                                )
                                if not was_interrupted and proc.returncode != 0:
                                    self._safe_fallback(clean_text, turn_start_time=turn_start_time)
                        else:
                            print(
                                f"[ElevenLabsTTS] API returned status {response.status_code}: {response.text}; falling back to offline voice"
                            )
                            if not self._stop_requested and not is_speech_interrupted(
                                turn_start_time
                            ):
                                self._safe_fallback(clean_text, turn_start_time=turn_start_time)
                    except Exception as e:
                        print(
                            f"[ElevenLabsTTS] Error during synthesis: {e}; falling back to offline voice"
                        )
                        if not self._stop_requested and not is_speech_interrupted(turn_start_time):
                            self._safe_fallback(clean_text, turn_start_time=turn_start_time)
                    finally:
                        self._current_process = None
                        try:
                            Path(temp_path).unlink(missing_ok=True)
                        except Exception:
                            pass
            except DuplicateSpeechSuppressed:
                return

        if block:
            _run()
        else:
            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize speech directly to an audio file without playing."""
        if not text or not text.strip() or not self.api_key:
            return False
        clean_text = normalize_tts_text(text)
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}?optimize_streaming_latency=3"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": clean_text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": self.similarity_boost,
                "style": 0.0,
                "use_speaker_boost": True,
            },
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
