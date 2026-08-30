"""
Wake Word Listener and Keyword Spotting Engine for VoiceFi.
Continuously runs in the background LaunchAgent server to detect 'Hey Viv' (and configured aliases),
triggering acoustic feedback, HUD animations, and autonomous Antigravity dispatch.
"""

import os
import sys
import time
import threading
import numpy as np
import sounddevice as sd
from typing import Callable, Optional, List, Dict, Any, Tuple

from voicefi.config import VoiceFiConfig, load_config
from voicefi.audio.vad import VoiceActivityDetector
from voicefi.audio.chimes import play_chime
from voicefi.tts.base import is_agent_speaking, is_agent_audio_playing
from voicefi.integrations.active_listening import ActiveListeningEngine


class WakeWordListener:
    """
    Non-blocking, low-overhead background microphone listener that monitors for
    wake words ('Hey Viv', 'Viv', 'Hey ViFi') and manages conversational handoff.
    """

    def __init__(
        self,
        config: Optional[VoiceFiConfig] = None,
        on_wake: Optional[Callable[[str, str], None]] = None,
        on_energy: Optional[Callable[[float, float, bool], None]] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        sample_rate: int = 16000,
        chunk_duration: float = 0.05,  # 50ms chunks
    ):
        self.config = config or load_config()
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.chunk_size = int(self.sample_rate * self.chunk_duration)

        self.on_wake = on_wake
        self.on_energy = on_energy
        self.on_state_change = on_state_change

        self.aliases = list(getattr(self.config.wakeword, "aliases", ["hey viv", "viv", "hey vifi", "vifi", "hey antigravity"]))
        if getattr(self.config.wakeword, "phrase", None) and self.config.wakeword.phrase.lower() not in [a.lower() for a in self.aliases]:
            self.aliases.insert(0, self.config.wakeword.phrase.lower())

        self.vad = VoiceActivityDetector(
            engine="auto",
            speech_threshold=self.config.vad.speech_threshold,
            energy_threshold=self.config.wakeword.energy_threshold if hasattr(self.config, "wakeword") else 0.005,
            sample_rate=self.sample_rate,
        )

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stt_lock = threading.Lock()
        self._stt_instance = None
        self._current_state = "stopped"
        self._last_wake_time = 0.0

    def _set_state(self, state: str):
        if self._current_state != state:
            self._current_state = state
            if self.on_state_change:
                try:
                    self.on_state_change(state)
                except Exception as ex:
                    print(f"[WakeWord] State change callback error: {ex}")

    def _get_stt(self):
        """Lazy load STT engine for keyword spotting."""
        if self._stt_instance is None:
            with self._stt_lock:
                if self._stt_instance is None:
                    from voicefi.stt import get_stt_engine
                    self._stt_instance = get_stt_engine(self.config)
        return self._stt_instance

    def start(self):
        """Start the background wake word listener thread."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._set_state("listening")
        self._thread = threading.Thread(target=self._listener_loop, daemon=True, name="WakeWordListener")
        self._thread.start()
        print(f"[WakeWord] 🎙️ Wake-word listener active (Triggers: {', '.join(self.aliases[:3])}...)")

    def stop(self):
        """Stop background listening."""
        self._running = False
        self._stop_event.set()
        self._set_state("stopped")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def pause(self):
        """Pause listening to yield microphone device to active recording sessions."""
        self._paused = True
        self._set_state("paused")

    def resume(self):
        """Resume wake-word listening."""
        self._paused = False
        self._set_state("listening")

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    def _listener_loop(self):
        """Background continuous stream monitoring for wake phrases."""
        from collections import deque
        pre_roll: deque = deque(maxlen=8)  # ~400ms pre-speech onset buffer
        recorded_frames: List[np.ndarray] = []
        speech_started = False
        silence_chunks = 0
        silence_limit = int(0.95 / self.chunk_duration)  # ~950ms trailing silence for natural phrasing
        min_speech_chunks = int(0.20 / self.chunk_duration)  # ~200ms minimum speech
        max_chunks = int(7.0 / self.chunk_duration)  # 7.0s maximum candidate window
        chunk_count = 0

        while not self._stop_event.is_set():
            if self._paused or not getattr(self.config.wakeword, "enabled", True):
                time.sleep(0.1)
                continue

            try:
                with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
                    while not self._stop_event.is_set() and not self._paused:
                        # Suppress listening while agent is speaking to avoid self-activation
                        if is_agent_speaking() or is_agent_audio_playing():
                            time.sleep(0.08)
                            recorded_frames.clear()
                            pre_roll.clear()
                            speech_started = False
                            continue

                        chunk, overflowed = stream.read(self.chunk_size)
                        if self._stop_event.is_set() or self._paused:
                            break

                        chunk_count += 1
                        audio_chunk = chunk.flatten()
                        vad_res = self.vad.process(audio_chunk)
                        energy = vad_res["energy"]
                        is_speech = vad_res["is_speech"]

                        # Broadcast energy telemetry at 10Hz
                        if self.on_energy and (chunk_count % 2 == 0):
                            try:
                                self.on_energy(energy, self.vad.running_noise_floor, is_speech or speech_started)
                            except Exception:
                                pass

                        if is_speech:
                            if not speech_started:
                                speech_started = True
                                self._set_state("speech_detected")
                                # Prepend pre-roll buffer to retain leading syllable (e.g. "Hey")
                                recorded_frames.extend(list(pre_roll))
                            recorded_frames.append(audio_chunk)
                            silence_chunks = 0
                        elif speech_started:
                            recorded_frames.append(audio_chunk)
                            silence_chunks += 1

                            # End of candidate utterance detected (silence_limit reached or max window hit)
                            if silence_chunks >= silence_limit or len(recorded_frames) >= max_chunks:
                                if len(recorded_frames) >= min_speech_chunks:
                                    full_audio = np.concatenate(recorded_frames, axis=0)
                                    threading.Thread(
                                        target=self._process_candidate_audio,
                                        args=(full_audio,),
                                        daemon=True,
                                        name="WakeWordSTT"
                                    ).start()
                                recorded_frames.clear()
                                pre_roll.clear()
                                speech_started = False
                                silence_chunks = 0
                                self.vad.reset()
                                self._set_state("listening")
                        else:
                            pre_roll.append(audio_chunk)

            except Exception as e:
                print(f"[WakeWord] Listener exception: {e}", flush=True)
                # If audio device error, sleep briefly and retry
                time.sleep(0.5)

    def _process_candidate_audio(self, audio_data: np.ndarray):
        """Transcribe candidate speech utterance and check for wake word triggers."""
        # Cooldown guard: ignore triggers within 1.2s of last trigger
        if time.time() - self._last_wake_time < 1.2:
            return

        try:
            stt = self._get_stt()
            transcript = stt.transcribe(audio_data, sample_rate=self.sample_rate)
            dur = len(audio_data) / self.sample_rate
            if not transcript or not transcript.strip():
                return

            clean_text = transcript.strip()
            # print candidate transcript if debug or testing
            print(f"[WakeWord] Candidate ({dur:.2f}s) transcribed: {repr(clean_text)}", flush=True)

            # Check for wake word prefix
            matched_phrase, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(
                clean_text, aliases=self.aliases
            )

            if matched_phrase:
                self._last_wake_time = time.time()
                print(f"\n⚡ [WakeWord] WAKE WORD DETECTED: '{matched_phrase}' | Prompt: '{prompt}'", flush=True)
                self._set_state("wake_triggered")

                if getattr(self.config.wakeword, "chime", True):
                    try:
                        play_chime("start")
                    except Exception:
                        pass

                if self.on_wake:
                    try:
                        self.on_wake(matched_phrase, prompt)
                    except Exception as ex:
                        print(f"[WakeWord] on_wake handler error: {ex}", flush=True)

        except Exception as ex:
            print(f"[WakeWord] Audio processing error: {ex}", flush=True)
