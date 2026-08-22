"""
Ambient background audio stream and sliding window capture.
Continuously captures ambient speech in non-blocking background threads,
emitting completed utterances for real-time proactive triage and transcription.
"""

import time
import threading
from typing import Callable, Optional, List
import numpy as np
import sounddevice as sd

from voicegency.tts.base import is_agent_speaking


class AmbientAudioStream:
    """Non-blocking background audio listener that captures natural spoken utterances."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration: float = 0.05,  # 50ms chunks
        energy_threshold: float = 0.005,
        silence_duration: float = 1.2,
        min_speech_duration: float = 0.8,
        max_utterance_duration: float = 15.0,
        on_utterance: Optional[Callable[[np.ndarray, int], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.chunk_size = int(self.sample_rate * self.chunk_duration)
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.min_speech_duration = min_speech_duration
        self.max_utterance_duration = max_utterance_duration
        self.on_utterance = on_utterance

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.current_noise_floor = 0.006

    def start(self):
        """Start the background listening thread."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._stream_loop, daemon=True, name="AmbientAudioStream")
        self._thread.start()

    def stop(self):
        """Stop background listening."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def pause(self):
        """Temporarily pause capturing."""
        self._paused = True

    def resume(self):
        """Resume capturing."""
        self._paused = False

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    def _stream_loop(self):
        """Background loop continuously monitoring microphone audio."""
        recorded_frames: List[np.ndarray] = []
        speech_started = False
        consecutive_silence_chunks = 0
        chunks_needed_for_silence = int(self.silence_duration / self.chunk_duration)
        min_chunks_for_speech = int(self.min_speech_duration / self.chunk_duration)
        max_chunks_for_utterance = int(self.max_utterance_duration / self.chunk_duration)

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
                while not self._stop_event.is_set():
                    if self._paused or is_agent_speaking():
                        time.sleep(0.05)
                        recorded_frames.clear()
                        speech_started = False
                        continue

                    chunk, overflowed = stream.read(self.chunk_size)
                    if self._stop_event.is_set():
                        break

                    audio_chunk = chunk.flatten()
                    energy = float(np.sqrt(np.mean(audio_chunk ** 2)))

                    # Dynamically update noise floor
                    if not speech_started and energy < self.energy_threshold:
                        self.current_noise_floor = 0.95 * self.current_noise_floor + 0.05 * energy

                    is_speech = energy > max(self.energy_threshold, self.current_noise_floor * 1.5)

                    if is_speech:
                        if not speech_started:
                            speech_started = True
                            consecutive_silence_chunks = 0
                        recorded_frames.append(audio_chunk)
                        consecutive_silence_chunks = 0
                    elif speech_started:
                        recorded_frames.append(audio_chunk)
                        consecutive_silence_chunks += 1

                        # Check if natural pause completed utterance or hit max duration
                        hit_silence = consecutive_silence_chunks >= chunks_needed_for_silence
                        hit_max_duration = len(recorded_frames) >= max_chunks_for_utterance

                        if hit_silence or hit_max_duration:
                            if len(recorded_frames) >= min_chunks_for_speech:
                                # Completed utterance captured!
                                utterance_audio = np.concatenate(recorded_frames, axis=0)
                                if self.on_utterance:
                                    try:
                                        self.on_utterance(utterance_audio, self.sample_rate)
                                    except Exception as ex:
                                        print(f"[AmbientAudioStream] Error in utterance callback: {ex}")

                            # Reset state for next utterance
                            recorded_frames.clear()
                            speech_started = False
                            consecutive_silence_chunks = 0
                    else:
                        # Keep a small pre-roll buffer of 2 chunks (~100ms) to avoid clipping start of speech
                        recorded_frames.append(audio_chunk)
                        if len(recorded_frames) > 2:
                            recorded_frames.pop(0)

        except Exception as ex:
            print(f"[AmbientAudioStream] Stream error: {ex}")
        finally:
            self._running = False
