"""
Ambient background audio stream and sliding window capture.
Continuously captures ambient speech in non-blocking background threads,
emitting completed utterances for real-time proactive triage and transcription.
"""

import time
import threading
from typing import Callable, Optional, List, Literal
import numpy as np
import sounddevice as sd

from voicefi.tts.base import is_agent_speaking
from voicefi.audio.vad import VoiceActivityDetector


class AmbientAudioStream:
    """Non-blocking background audio listener that captures natural spoken utterances with Silero neural VAD."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration: float = 0.05,  # 50ms chunks
        energy_threshold: float = 0.005,
        silence_duration: float = 0.55,
        min_speech_duration: float = 0.4,
        max_utterance_duration: float = 15.0,
        on_utterance: Optional[Callable[[np.ndarray, int], None]] = None,
        on_energy: Optional[Callable[[float, float, bool], None]] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        on_utterance_progress: Optional[Callable[[float], None]] = None,
        on_interim_audio: Optional[Callable[[np.ndarray, int], None]] = None,
        vad_engine: Literal["silero", "energy", "auto"] = "auto",
        speech_threshold: float = 0.5,
    ):
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.chunk_size = int(self.sample_rate * self.chunk_duration)
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.min_speech_duration = min_speech_duration
        self.max_utterance_duration = max_utterance_duration
        self.on_utterance = on_utterance
        self.on_energy = on_energy
        self.on_state_change = on_state_change
        self.on_utterance_progress = on_utterance_progress
        self.on_interim_audio = on_interim_audio
        self.vad_engine = vad_engine
        self.speech_threshold = speech_threshold
        self.vad = VoiceActivityDetector(
            engine=vad_engine,
            speech_threshold=speech_threshold,
            energy_threshold=energy_threshold,
            sample_rate=sample_rate,
        )

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.current_noise_floor = 0.006
        self._current_state = "stopped"

    def _set_state(self, state: str):
        if self._current_state != state:
            self._current_state = state
            if self.on_state_change:
                try:
                    self.on_state_change(state)
                except Exception as ex:
                    print(f"[AmbientAudioStream] State change callback error: {ex}")

    def start(self):
        """Start the background listening thread."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._set_state("listening")
        self._thread = threading.Thread(
            target=self._stream_loop, daemon=True, name="AmbientAudioStream"
        )
        self._thread.start()

    def stop(self):
        """Stop background listening."""
        self._running = False
        self._stop_event.set()
        self._set_state("stopped")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def pause(self):
        """Temporarily pause capturing."""
        self._paused = True
        self._set_state("paused")

    def resume(self):
        """Resume capturing."""
        self._paused = False
        self._set_state("listening")

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
        chunk_count = 0

        cooldown_chunks = 0
        was_agent_speaking = False

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
                while not self._stop_event.is_set():
                    if self._paused:
                        self._set_state("paused")
                        time.sleep(0.05)
                        recorded_frames.clear()
                        speech_started = False
                        continue

                    if is_agent_speaking():
                        self._set_state("agent_suppressed")
                        was_agent_speaking = True
                        time.sleep(0.05)
                        recorded_frames.clear()
                        speech_started = False
                        continue

                    if was_agent_speaking:
                        was_agent_speaking = False
                        cooldown_chunks = 8  # ~400ms acoustic dissipation cooldown
                        recorded_frames.clear()
                        speech_started = False
                        self._set_state("listening")

                    if cooldown_chunks > 0:
                        cooldown_chunks -= 1
                        # Discard stream audio during cooldown
                        stream.read(self.chunk_size)
                        continue

                    chunk, overflowed = stream.read(self.chunk_size)
                    if self._stop_event.is_set():
                        break

                    chunk_count += 1
                    audio_chunk = chunk.flatten()
                    vad_res = self.vad.process(audio_chunk)
                    energy = vad_res["energy"]
                    self.current_noise_floor = self.vad.running_noise_floor
                    is_speech = vad_res["is_speech"]
                    confidence = vad_res["confidence"]
                    active_engine = vad_res["engine"]

                    # 10Hz throttled energy broadcast (every 2nd 50ms chunk)
                    if self.on_energy and (chunk_count % 2 == 0):
                        try:
                            self.on_energy(
                                energy, self.current_noise_floor, is_speech or speech_started
                            )
                        except Exception as ex:
                            print(f"[AmbientAudioStream] Energy callback error: {ex}")

                    if is_speech:
                        if not speech_started:
                            consecutive_speech_chunks = getattr(self, "_consec_speech", 0) + 1
                            self._consec_speech = consecutive_speech_chunks
                            # Require 1 chunk for neural Silero or 2 for energy to filter clicks
                            min_start_chunks = 1 if active_engine == "silero" else 2
                            if consecutive_speech_chunks >= min_start_chunks:
                                speech_started = True
                                self._consec_speech = 0
                                consecutive_silence_chunks = 0
                                self._set_state("speech_detected")
                        else:
                            self._consec_speech = 0

                        recorded_frames.append(audio_chunk)
                        consecutive_silence_chunks = 0

                        if self.on_utterance_progress:
                            try:
                                current_dur = len(recorded_frames) * self.chunk_duration
                                self.on_utterance_progress(current_dur)
                            except Exception:
                                pass

                        if (
                            self.on_interim_audio
                            and len(recorded_frames) >= 3
                            and (len(recorded_frames) % 2 == 0)
                        ):
                            try:
                                interim_audio = np.concatenate(recorded_frames, axis=0)
                                self.on_interim_audio(interim_audio, self.sample_rate)
                            except Exception:
                                pass
                    elif speech_started:
                        self._consec_speech = 0
                        recorded_frames.append(audio_chunk)
                        consecutive_silence_chunks += 1

                        if self.on_utterance_progress:
                            try:
                                current_dur = len(recorded_frames) * self.chunk_duration
                                self.on_utterance_progress(current_dur)
                            except Exception:
                                pass

                        if (
                            self.on_interim_audio
                            and len(recorded_frames) >= 3
                            and (len(recorded_frames) % 2 == 0)
                        ):
                            try:
                                interim_audio = np.concatenate(recorded_frames, axis=0)
                                self.on_interim_audio(interim_audio, self.sample_rate)
                            except Exception:
                                pass

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
                                        print(
                                            f"[AmbientAudioStream] Error in utterance callback: {ex}"
                                        )

                            # Reset state for next utterance
                            recorded_frames.clear()
                            self.vad.reset()
                            speech_started = False
                            consecutive_silence_chunks = 0
                            self._set_state("listening")
                    else:
                        self._consec_speech = 0
                        self._set_state("listening")
                        # Keep a small pre-roll buffer of 2 chunks (~100ms) to avoid clipping start of speech
                        recorded_frames.append(audio_chunk)
                        if len(recorded_frames) > 2:
                            recorded_frames.pop(0)

        except Exception as ex:
            print(f"[AmbientAudioStream] Stream error: {ex}")
        finally:
            self._running = False
            self._set_state("stopped")
