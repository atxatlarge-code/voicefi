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

    _ACTIVE_INSTANCES: set = set()

    def __init__(
        self,
        config: Optional[VoiceFiConfig] = None,
        on_wake: Optional[Callable[[str, str], None]] = None,
        on_energy: Optional[Callable[[float, float, bool], None]] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        sample_rate: int = 16000,
        chunk_duration: float = 0.05,  # 50ms chunks
    ):
        WakeWordListener._ACTIVE_INSTANCES.add(self)
        self.config = config or load_config()
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self.chunk_size = int(self.sample_rate * self.chunk_duration)

        self.on_wake = on_wake
        self.on_energy = on_energy
        self.on_state_change = on_state_change

        configured_aliases = list(
            getattr(
                self.config.wakeword,
                "aliases",
                [
                    "voicefi",
                    "vi-fi",
                    "hey voicefi",
                    "hey vi-fi",
                    "vifi",
                    "hey vifi",
                    "hey viv",
                    "viv",
                    "hey antigravity",
                    "hey claude",
                    "claude",
                    "hey pal",
                    "pal",
                    "hey brok",
                    "brok",
                    "hey channel",
                    "talk now",
                    "talk-now",
                ],
            )
        )
        alert_words = list(getattr(self.config.wakeword, "alert_words", []))
        self.aliases = list(
            dict.fromkeys([w.lower() for w in alert_words + configured_aliases if w])
        )
        for extra in (
            "hey claude",
            "claude",
            "voicefi",
            "vi-fi",
            "hey pal",
            "pal",
            "hey brok",
            "brok",
            "hey brock",
            "brock",
            "hey brook",
            "brook",
            "hey channel",
            "transcribe",
            "talk now",
            "talk-now",
        ):
            if extra not in [a.lower() for a in self.aliases]:
                self.aliases.append(extra)
        if getattr(
            self.config.wakeword, "phrase", None
        ) and self.config.wakeword.phrase.lower() not in [a.lower() for a in self.aliases]:
            self.aliases.insert(0, self.config.wakeword.phrase.lower())

        wake_terms = [
            "Hey Pal",
            "Pal",
            "Hey Brock",
            "Brock",
            "Hey Brok",
            "Brok",
            "Hey Viv",
            "Viv",
            "VoiceFi",
            "Vi-Fi",
            "Claude",
            "Hey Claude",
            "Antigravity",
            "talk now",
            "transcribe",
        ]
        self._stt_wake_prompt = f"Wake words: {', '.join(wake_terms)}."

        self.vad = VoiceActivityDetector(
            engine="auto",
            speech_threshold=self.config.vad.speech_threshold,
            energy_threshold=self.config.wakeword.energy_threshold
            if hasattr(self.config, "wakeword")
            else 0.005,
            sample_rate=self.sample_rate,
        )

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stream_closed_event = threading.Event()
        self._stream_closed_event.set()
        self._stt_lock = threading.Lock()
        self._candidate_lock = threading.Lock()
        self._stt_instance = None
        self._current_state = "stopped"
        self._last_wake_time = 0.0
        self._pending_wake_phrase: Optional[str] = None
        self._pending_wake_time: float = 0.0
        self._latest_pending_candidate: Optional[np.ndarray] = None
        self._live_frames_ref: Optional[List[np.ndarray]] = None
        self._last_handoff_audio: Optional[np.ndarray] = None
        self._prefix_wake_signal: Optional[Tuple[str, str, int]] = None
        self._prefix_check_inflight: bool = False

    def consume_handoff_audio(self) -> Optional[np.ndarray]:
        """Return and clear any buffered audio frames captured during wake-word handoff."""
        audio = self._last_handoff_audio
        self._last_handoff_audio = None
        return audio

    def _set_state(self, state: str):
        if self._current_state != state:
            self._current_state = state
            if self.on_state_change:
                try:
                    self.on_state_change(state)
                except Exception as ex:
                    print(f"[WakeWord] State change callback error: {ex}")

    def _get_stt(self):
        """Lazy load lightweight in-memory STT engine for sub-second keyword spotting."""
        if self._stt_instance is None:
            with self._stt_lock:
                if self._stt_instance is None:
                    from voicefi.stt.whisper_local import WhisperLocalSTT

                    model_size = getattr(self.config.stt, "model_size", "base.en") or "base.en"
                    if "/" in model_size or "large" in model_size or "turbo" in model_size:
                        model_size = "base.en"
                    language = getattr(self.config.stt, "language", "en") or "en"
                    self._stt_instance = WhisperLocalSTT(model_size=model_size, language=language)
        return self._stt_instance

    def start(self):
        """Start the background wake word listener thread."""
        if self._running:
            return
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._set_state("listening")
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get(
            "VOICEFI_TEST_ALLOW_WAKEWORD"
        ):
            return
        # Pre-warm STT model in background so the first wake word has zero cold-start delay
        threading.Thread(
            target=self._prewarm_stt, daemon=True, name="WakeWordSTTPrewarm"
        ).start()
        self._thread = threading.Thread(
            target=self._listener_loop, daemon=True, name="WakeWordListener"
        )
        self._thread.start()
        print(
            f"[WakeWord] 🎙️ Wake-word listener active (Triggers: {', '.join(self.aliases[:3])}...)"
        )

    def _prewarm_stt(self):
        try:
            self._get_stt()
        except Exception:
            pass

    def stop(self):
        """Stop background listening."""
        WakeWordListener._ACTIVE_INSTANCES.discard(self)
        self._running = False
        self._stop_event.set()
        self._set_state("stopped")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._thread = None

    def __del__(self):
        WakeWordListener._ACTIVE_INSTANCES.discard(self)

    def pause(self):
        """Pause listening to yield microphone device to active recording sessions."""
        self._paused = True
        self._prefix_wake_signal = None
        self._latest_pending_candidate = None
        self._set_state("paused")
        if (
            self._thread
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
            and not os.environ.get("PYTEST_CURRENT_TEST")
        ):
            self._stream_closed_event.wait(timeout=0.6)

    def resume(self):
        """Resume wake-word listening."""
        self._paused = False
        self._prefix_wake_signal = None
        self._latest_pending_candidate = None
        self._prefix_check_inflight = False
        try:
            self.vad.reset()
        except Exception:
            pass
        self._set_state("listening")

    @classmethod
    def pause_all(cls):
        """Pause all active wake-word listeners to yield microphone to recording."""
        for inst in list(cls._ACTIVE_INSTANCES):
            try:
                inst.pause()
            except Exception:
                pass

    @classmethod
    def resume_all(cls):
        """Resume all active wake-word listeners."""
        for inst in list(cls._ACTIVE_INSTANCES):
            try:
                inst.resume()
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._running and not self._paused

    def _listener_loop(self):
        """Background continuous stream monitoring for wake phrases."""
        from collections import deque

        pre_roll: deque = deque(maxlen=8)  # ~400ms pre-speech onset buffer
        recorded_frames: List[np.ndarray] = []
        self._live_frames_ref = recorded_frames
        self._pre_roll_ref = pre_roll
        speech_started = False
        speech_chunks_since_start = 0
        silence_chunks = 0
        short_silence_limit = int(
            0.45 / self.chunk_duration
        )  # 450ms trigger so natural comma pauses ("Hey Brok, open Spotify") stay in one utterance
        silence_limit = int(
            0.55 / self.chunk_duration
        )  # 550ms trailing silence for longer multi-word utterances
        min_speech_chunks = int(0.20 / self.chunk_duration)  # ~200ms minimum speech
        max_chunks = int(7.0 / self.chunk_duration)  # 7.0s maximum candidate window
        chunk_count = 0

        cooldown_chunks = 0
        while not self._stop_event.is_set():
            from voicefi.tts.base import is_mic_recording_active

            if (
                self._paused
                or is_mic_recording_active()
                or not getattr(self.config.wakeword, "enabled", True)
            ):
                time.sleep(0.05)
                continue

            try:
                self._stream_closed_event.clear()
                try:
                    from voicefi.audio.device import auto_pin_mac_microphone

                    pinned, msg = auto_pin_mac_microphone()
                    if pinned and "Already pinned" not in msg:
                        time.sleep(0.06)
                except Exception:
                    pass
                with sd.InputStream(
                    samplerate=self.sample_rate, channels=1, dtype="float32"
                ) as stream:
                    while not self._stop_event.is_set() and not self._paused:
                        if is_mic_recording_active():
                            break
                        # Always read from stream to drain hardware buffer
                        chunk, overflowed = stream.read(self.chunk_size)
                        if self._stop_event.is_set() or self._paused or is_mic_recording_active():
                            break

                        # Check if streaming prefix spotter found a wake word mid-utterance
                        if self._prefix_wake_signal is not None:
                            matched_p, partial_pr, snap_idx = self._prefix_wake_signal
                            self._prefix_wake_signal = None
                            trailing_frames = list(recorded_frames[snap_idx:])
                            trailing_frames.append(chunk.flatten())
                            if trailing_frames:
                                self._last_handoff_audio = np.concatenate(trailing_frames, axis=0)
                            else:
                                self._last_handoff_audio = None
                            recorded_frames.clear()
                            pre_roll.clear()
                            speech_started = False
                            speech_chunks_since_start = 0
                            silence_chunks = 0
                            self.vad.reset()
                            self._dispatch_wake_match(
                                matched_p, partial_pr, is_followup=False, is_streaming_prefix=True
                            )
                            break

                        # Suppress listening while agent is speaking, audio is playing, or recently interrupted
                        from voicefi.tts.base import is_speech_interrupted, is_system_audio_playing

                        if (
                            is_agent_speaking()
                            or is_agent_audio_playing()
                            or is_system_audio_playing()
                            or is_speech_interrupted()
                        ):
                            recorded_frames.clear()
                            pre_roll.clear()
                            speech_started = False
                            speech_chunks_since_start = 0
                            silence_chunks = 0
                            self.vad.reset()
                            cooldown_chunks = int(0.25 / self.chunk_duration)
                            continue

                        # Drain room decay & acoustic dissipation
                        if cooldown_chunks > 0:
                            cooldown_chunks -= 1
                            recorded_frames.clear()
                            pre_roll.clear()
                            speech_started = False
                            speech_chunks_since_start = 0
                            silence_chunks = 0
                            continue

                        chunk_count += 1
                        audio_chunk = chunk.flatten()
                        vad_res = self.vad.process(audio_chunk)
                        energy = vad_res["energy"]
                        is_speech = vad_res["is_speech"]

                        try:
                            from voicefi.audio.monitor import LiveVADMonitor

                            mon = LiveVADMonitor._INSTANCE
                            if mon is not None and mon.is_active:
                                mon.dispatch_external_chunk(
                                    energy=energy,
                                    confidence=float(vad_res.get("confidence", 0.0)),
                                    is_speech=bool(is_speech or speech_started),
                                    noise_floor=float(self.vad.running_noise_floor),
                                )
                        except Exception:
                            pass

                        # Broadcast energy telemetry at 10Hz
                        if self.on_energy and (chunk_count % 2 == 0):
                            try:
                                self.on_energy(
                                    energy,
                                    self.vad.running_noise_floor,
                                    is_speech or speech_started,
                                )
                            except Exception:
                                pass

                        if is_speech:
                            if not speech_started:
                                speech_started = True
                                speech_chunks_since_start = 0
                                self._set_state("speech_detected")
                                # Prepend pre-roll buffer to retain leading syllable (e.g. "Hey")
                                recorded_frames.extend(list(pre_roll))
                            recorded_frames.append(audio_chunk)
                            speech_chunks_since_start += 1
                            silence_chunks = 0

                            # Streaming prefix spotter: if user is speaking continuously without pausing
                            # (e.g. "Hey Viv what's the weather..."), check prefix at ~600ms and ~1.1s of speech!
                            if (
                                speech_chunks_since_start in (12, 22)
                                and not self._prefix_check_inflight
                                and not self._candidate_lock.locked()
                            ):
                                snap_idx = len(recorded_frames)
                                snap_audio = np.concatenate(recorded_frames, axis=0)
                                self._prefix_check_inflight = True
                                threading.Thread(
                                    target=self._check_streaming_prefix,
                                    args=(snap_audio, snap_idx),
                                    daemon=True,
                                    name="WakeWordPrefixSTT",
                                ).start()
                        elif speech_started:
                            recorded_frames.append(audio_chunk)
                            silence_chunks += 1

                            eff_silence_limit = (
                                short_silence_limit
                                if len(recorded_frames) <= 44
                                else silence_limit
                            )

                            # End of candidate utterance detected (eff_silence_limit reached or max window hit)
                            if (
                                silence_chunks >= eff_silence_limit
                                or len(recorded_frames) >= max_chunks
                            ):
                                from voicefi.audio.meeting_detection import is_user_on_call
                                from voicefi.audio.media_detection import is_active_media_playing

                                if (
                                    not is_user_on_call()
                                    and not is_active_media_playing()
                                    and len(recorded_frames) >= min_speech_chunks
                                ):
                                    full_audio = np.concatenate(recorded_frames, axis=0)
                                    threading.Thread(
                                        target=self._process_candidate_audio,
                                        args=(full_audio,),
                                        daemon=True,
                                        name="WakeWordSTT",
                                    ).start()
                                recorded_frames.clear()
                                pre_roll.clear()
                                speech_started = False
                                speech_chunks_since_start = 0
                                silence_chunks = 0
                                self.vad.reset()
                                self._set_state("listening")
                        else:
                            pre_roll.append(audio_chunk)

            except Exception as e:
                print(f"[WakeWord] Listener exception: {e}", flush=True)
                # If audio device error, sleep briefly and retry
                time.sleep(0.5)
            finally:
                self._stream_closed_event.set()

    def _check_streaming_prefix(self, audio_snapshot: np.ndarray, snapshot_idx: int):
        """Check an in-progress speech prefix (~600ms-1.1s) for a wake word while the user keeps talking."""
        try:
            if time.time() - self._last_wake_time < 0.45:
                return
            from voicefi.tts.base import is_speech_interrupted, is_mic_recording_active, is_system_audio_playing
            from voicefi.audio.meeting_detection import is_user_on_call
            from voicefi.audio.media_detection import is_active_media_playing

            if (
                is_mic_recording_active()
                or is_user_on_call()
                or is_active_media_playing()
                or is_agent_speaking()
                or is_agent_audio_playing()
                or is_system_audio_playing()
                or is_speech_interrupted()
            ):
                return

            stt = self._get_stt()
            transcript = stt.transcribe(
                audio_snapshot, sample_rate=self.sample_rate, prompt=self._stt_wake_prompt
            )
            if not transcript or not transcript.strip():
                return
            clean_text = transcript.strip()
            from voicefi.audio.echo_canceller import is_acoustic_echo

            if is_acoustic_echo(clean_text):
                return

            matched_phrase, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(
                clean_text, aliases=self.aliases
            )
            if matched_phrase and time.time() - self._last_wake_time >= 0.45:
                self._prefix_wake_signal = (matched_phrase, prompt, snapshot_idx)
        except Exception:
            pass
        finally:
            self._prefix_check_inflight = False

    def _dispatch_wake_match(
        self,
        matched_phrase: str,
        prompt: str,
        is_followup: bool = False,
        is_streaming_prefix: bool = False,
    ):
        """Play chime (if enabled) and invoke on_wake callback or default local router."""
        now = time.time()
        if not is_followup and (now - self._last_wake_time) < 0.45:
            return
        self._last_wake_time = now
        self._prefix_wake_signal = None
        self._latest_pending_candidate = None
        if not prompt and self.on_wake is None:
            self._pending_wake_phrase = matched_phrase
            self._pending_wake_time = now
        else:
            self._pending_wake_phrase = None

        if not is_followup:
            print(
                f"\n⚡ [WakeWord] WAKE WORD DETECTED: '{matched_phrase}' | Prompt: '{prompt}' (streaming_prefix={is_streaming_prefix})",
                flush=True,
            )
            self._set_state("wake_triggered")

            if getattr(self.config.wakeword, "chime", True):
                try:
                    play_chime("start", block=False)
                except Exception:
                    pass

        if self.on_wake:
            try:
                import inspect

                sig = inspect.signature(self.on_wake)
                if "is_streaming_prefix" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                ):
                    self.on_wake(matched_phrase, prompt, is_streaming_prefix=is_streaming_prefix)
                else:
                    self.on_wake(matched_phrase, prompt)
            except Exception as ex:
                print(f"[WakeWord] on_wake handler error: {ex}", flush=True)
        elif (
            getattr(getattr(self.config, "local_model", None), "intent_routing", False)
            and prompt
        ):
            try:
                from voicefi.local.intent import LocalIntentRouter

                router = LocalIntentRouter(config=self.config)
                route = router.route_prompt(prompt)
                if route.get("status") in ("handled_local", "routed_obsidian"):
                    spoken = route.get("spoken_response")
                    if spoken:
                        from voicefi.tts import get_tts_engine

                        tts = get_tts_engine(self.config)
                        tts.speak(spoken, block=False)
                elif route.get("target") in ("antigravity", "claude", "codex"):
                    from voicefi.integrations.injector import send_message_to_agent

                    send_message_to_agent(
                        text=prompt,
                        sender_name=f"{self.config.user_name} ({matched_phrase})",
                        title=f"Prompt via {matched_phrase}",
                        target_engine=route.get("target"),
                    )
            except Exception as ex:
                print(f"[WakeWord] Default intent routing error: {ex}", flush=True)

    def _process_candidate_audio(self, audio_data: np.ndarray):
        """Transcribe candidate speech utterance and check for wake word triggers."""
        if not self._candidate_lock.acquire(blocking=False):
            # Queue latest candidate so a wake word spoken right after room noise is never dropped
            self._latest_pending_candidate = audio_data
            return

        try:
            current_audio: Optional[np.ndarray] = audio_data
            while current_audio is not None:
                self._latest_pending_candidate = None
                self._evaluate_single_candidate(current_audio)
                if time.time() - self._last_wake_time < 0.45 or self._prefix_wake_signal is not None:
                    self._latest_pending_candidate = None
                    break
                current_audio = self._latest_pending_candidate
        finally:
            self._candidate_lock.release()

    def _evaluate_single_candidate(self, audio_data: np.ndarray):
        """Evaluate a single candidate audio buffer for wake word match."""
        # Cooldown guard: ignore triggers within 0.45s of last trigger
        if time.time() - self._last_wake_time < 0.45:
            return
        self._prefix_wake_signal = None

        # Acoustic echo guard: ignore candidates if on a call, agent is speaking, audio is playing, or recently interrupted
        from voicefi.tts.base import is_speech_interrupted, is_system_audio_playing
        from voicefi.audio.meeting_detection import is_user_on_call
        from voicefi.audio.media_detection import is_active_media_playing

        if (
            is_user_on_call()
            or is_active_media_playing()
            or is_agent_speaking()
            or is_agent_audio_playing()
            or is_system_audio_playing()
            or is_speech_interrupted()
        ):
            return

        try:
            stt = self._get_stt()
            transcript = stt.transcribe(
                audio_data, sample_rate=self.sample_rate, prompt=self._stt_wake_prompt
            )
            dur = len(audio_data) / self.sample_rate
            if not transcript or not transcript.strip():
                return

            clean_text = transcript.strip()
            print(
                f"[WakeWord] Candidate ({dur:.2f}s) transcribed: {repr(clean_text)}", flush=True
            )

            from voicefi.audio.echo_canceller import is_acoustic_echo

            if is_acoustic_echo(clean_text):
                print(
                    f"[WakeWord] 🛡️ Suppressed acoustic self-echo: {repr(clean_text)}",
                    flush=True,
                )
                return

            is_followup = False
            # Check for wake word prefix
            matched_phrase, prompt = ActiveListeningEngine.extract_wakeword_and_prompt(
                clean_text, aliases=self.aliases
            )

            # Conversational follow-up (only used when on_wake is None)
            if not matched_phrase and self._pending_wake_phrase and self.on_wake is None:
                if time.time() - self._pending_wake_time <= 8.0:
                    matched_phrase = self._pending_wake_phrase
                    prompt = clean_text
                    self._pending_wake_phrase = None
                    is_followup = True
                    print(
                        f"\n⚡ [WakeWord] PENDING WAKE FOLLOW-UP: '{matched_phrase}' | Prompt: '{prompt}'",
                        flush=True,
                    )
                else:
                    self._pending_wake_phrase = None

            if matched_phrase:
                # Capture any new frames that arrived in _listener_loop while STT was running
                live_frames = list(self._live_frames_ref) if self._live_frames_ref else []
                pre_frames = (
                    list(self._pre_roll_ref)
                    if (not live_frames and getattr(self, "_pre_roll_ref", None))
                    else []
                )
                handoff_frames = live_frames or pre_frames
                if handoff_frames:
                    self._last_handoff_audio = np.concatenate(handoff_frames, axis=0)
                    if self._live_frames_ref is not None:
                        self._live_frames_ref.clear()
                    if getattr(self, "_pre_roll_ref", None) is not None:
                        self._pre_roll_ref.clear()
                else:
                    self._last_handoff_audio = None

                self._dispatch_wake_match(
                    matched_phrase, prompt, is_followup=is_followup, is_streaming_prefix=False
                )

        except Exception as ex:
            print(f"[WakeWord] Audio processing error: {ex}", flush=True)
