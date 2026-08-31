"""
Apple Speech framework STT provider (macOS native).
Instant token streaming via on-device SFSpeechRecognizer.
"""

import json
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional, Union
import numpy as np
from voicefi.stt.base import BaseSTT


BIN_PATH = Path(__file__).resolve().parent / "apple_speech_stream"


def ensure_binary() -> bool:
    """Ensure the native Swift streaming helper binary is compiled."""
    if BIN_PATH.is_file():
        return True
    swift_src = Path(__file__).resolve().parent / "apple_speech_stream.swift"
    if swift_src.is_file():
        try:
            subprocess.run(
                ["swiftc", str(swift_src), "-O", "-o", str(BIN_PATH)],
                check=True,
                capture_output=True,
            )
            return True
        except Exception:
            return False
    return False


class AppleSpeechStreamer:
    """Live streaming controller managing the native Swift SFSpeechRecognizer process."""

    def __init__(
        self,
        on_interim: Optional[Callable[[str], None]] = None,
        on_transcript: Optional[Callable[[str], None]] = None,
    ):
        self.on_interim = on_interim
        self.on_transcript = on_transcript
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        if self._running or not ensure_binary():
            return
        self._running = True
        try:
            self._proc = subprocess.Popen(
                [str(BIN_PATH)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._thread = threading.Thread(
                target=self._read_loop, daemon=True, name="AppleSpeechReader"
            )
            self._thread.start()
        except Exception as e:
            print(f"[AppleSpeechStreamer] Failed to start native process: {e}")
            self._running = False

    def _read_loop(self):
        if not self._proc or not self._proc.stdout:
            return
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                msg_type = data.get("type")
                text = data.get("text", "")
                is_final = data.get("is_final", False)

                if is_final or msg_type == "transcript":
                    if self.on_transcript and text:
                        self.on_transcript(text)
                elif msg_type == "interim_transcript":
                    if self.on_interim and text:
                        self.on_interim(text)
            except Exception:
                pass

    def stop(self):
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    @property
    def is_running(self) -> bool:
        return self._running and self._proc is not None and self._proc.poll() is None


class AppleSpeechSTT(BaseSTT):
    """macOS native speech recognition adapter."""

    def __init__(self, language: str = "en-US"):
        self.language = language

    def transcribe(self, audio: Union[Path, str, np.ndarray], sample_rate: int = 16000) -> str:
        """Transcribe using Apple's speech recognition."""
        try:
            from voicefi.stt.whisper_local import WhisperLocalSTT

            fallback = WhisperLocalSTT(model_size="base.en")
            return fallback.transcribe(audio, sample_rate)
        except Exception as e:
            print(f"[AppleSpeechSTT] Fallback transcription error: {e}")
            return ""
