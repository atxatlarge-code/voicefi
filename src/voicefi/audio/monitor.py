"""
Live Voice Activity Detection (VAD) Monitor.
Provides a continuous, low-overhead background microphone stream that feeds
real-time acoustic telemetry to the Dynamic Island HUD and Expert VAD Inspector.
Designed to gracefully pause and yield the microphone device during active recording sessions.
"""

import time
import threading
import numpy as np
import sounddevice as sd
from typing import Optional, Callable, List, Tuple

from voicefi.config import load_config
from voicefi.audio.vad import VoiceActivityDetector


class LiveVADMonitor:
    """Singleton background VAD monitor broadcasting live audio metrics."""

    _instance: Optional["LiveVADMonitor"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "LiveVADMonitor":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.config = load_config()
        self.sample_rate = self.config.vad.sample_rate
        self.chunk_duration = 0.05
        self.chunk_size = int(self.sample_rate * self.chunk_duration)

        self.vad = VoiceActivityDetector(
            engine=self.config.vad.engine,
            speech_threshold=self.config.vad.speech_threshold,
            energy_threshold=self.config.vad.energy_threshold,
            sample_rate=self.sample_rate,
        )

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stream_closed_event = threading.Event()
        self._stream_closed_event.set()
        self._listeners: List[Callable[[float, float, bool, np.ndarray, float, float], None]] = []

    def reload_config(self):
        """Reload VAD thresholds from config dynamically."""
        self.config = load_config()
        self.vad.speech_threshold = self.config.vad.speech_threshold
        self.vad.energy_threshold = self.config.vad.energy_threshold
        # If engine changed, this requires a restart of the VAD object which we do simply:
        if self.vad.requested_engine != self.config.vad.engine:
            self.vad = VoiceActivityDetector(
                engine=self.config.vad.engine,
                speech_threshold=self.config.vad.speech_threshold,
                energy_threshold=self.config.vad.energy_threshold,
                sample_rate=self.sample_rate,
            )

    def add_listener(
        self, callback: Callable[[float, float, bool, np.ndarray, float, float], None]
    ):
        """
        Callback signature:
        (energy, speech_prob, is_speech, raw_chunk, noise_floor, active_threshold)
        """
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def start(self):
        """Start the background monitor stream."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self.vad.reset()
        self._thread = threading.Thread(
            target=self._stream_loop, daemon=True, name="LiveVADMonitor"
        )
        self._thread.start()

    def stop(self):
        """Stop the background monitor stream."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def pause(self):
        """Yield the microphone to another process (e.g. active AudioRecorder)."""
        self._paused = True
        import os

        if (
            self._thread
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
            and not os.environ.get("PYTEST_CURRENT_TEST")
        ):
            self._stream_closed_event.wait(timeout=0.15)

    def resume(self):
        """Resume monitoring the microphone."""
        self._paused = False
        self.reload_config()
        self.vad.reset()

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    def dispatch_external_chunk(
        self,
        energy: float,
        confidence: float,
        is_speech: bool,
        audio_chunk: np.ndarray,
        noise_floor: float,
        active_threshold: float,
    ):
        """Receive VAD telemetry from WakeWordListener without opening a second PortAudio InputStream."""
        if self._paused or not self._listeners:
            return
        for listener in list(self._listeners):
            try:
                listener(
                    energy,
                    confidence,
                    is_speech,
                    audio_chunk,
                    noise_floor,
                    active_threshold,
                )
            except Exception as e:
                print(f"[LiveVADMonitor] Error in listener: {e}")

    def _stream_loop(self):
        while not self._stop_event.is_set():
            from voicefi.audio.wakeword import WakeWordListener
            from voicefi.tts.base import is_mic_recording_active

            wakeword_sharing_mic = any(
                inst.is_running for inst in list(WakeWordListener._ACTIVE_INSTANCES)
            )
            if (
                self._paused
                or not self._listeners
                or wakeword_sharing_mic
                or is_mic_recording_active()
            ):
                self._stream_closed_event.set()
                time.sleep(0.1)
                continue

            try:
                self._stream_closed_event.clear()
                # Open short-lived stream to allow quick yielding if paused
                with sd.InputStream(
                    samplerate=self.sample_rate, channels=1, dtype="float32"
                ) as stream:
                    while (
                        not self._stop_event.is_set()
                        and not self._paused
                        and self._listeners
                        and not is_mic_recording_active()
                    ):
                        if any(
                            inst.is_running for inst in list(WakeWordListener._ACTIVE_INSTANCES)
                        ):
                            break
                        chunk, overflowed = stream.read(self.chunk_size)
                        if (
                            self._stop_event.is_set()
                            or self._paused
                            or is_mic_recording_active()
                        ):
                            break

                        audio_chunk = chunk.flatten()
                        vad_res = self.vad.process(audio_chunk)

                        energy = vad_res["energy"]
                        confidence = vad_res["confidence"]
                        is_speech = vad_res["is_speech"]
                        noise_floor = self.vad.running_noise_floor
                        active_threshold = vad_res["active_threshold"]

                        for listener in list(self._listeners):
                            try:
                                listener(
                                    energy,
                                    confidence,
                                    is_speech,
                                    audio_chunk,
                                    noise_floor,
                                    active_threshold,
                                )
                            except Exception as e:
                                print(f"[LiveVADMonitor] Error in listener: {e}")

            except Exception:
                # E.g. Device unavailable, wait before retrying
                time.sleep(1.0)
            finally:
                self._stream_closed_event.set()
