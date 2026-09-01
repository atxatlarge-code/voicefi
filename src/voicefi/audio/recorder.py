"""
Microphone audio capture with Adaptive Voice Activity Detection (VAD).
Uses smoothed energy tracking and robust 0.8s silence cutoff to prevent background noise hangs.
Supports instant manual completion via Enter key / stop_event.
"""

import time
import tempfile
import threading
from pathlib import Path
from typing import Optional, Tuple, Callable, Any, Literal
import numpy as np
import sounddevice as sd
import soundfile as sf


from voicefi.tts.base import is_agent_speaking, is_agent_audio_playing
from voicefi.audio.device import is_using_builtin_speakers, is_headphone_or_headset_active
from voicefi.audio.vad import VoiceActivityDetector


def resolve_barge_in_mode(barge_in_setting: Any) -> Tuple[bool, bool]:
    """
    Resolve effective barge-in enabled status and whether acoustic safe mode is active.
    Returns: (is_barge_in_active, is_safe_mode)

    When barge_in is 'auto' (the default):
      - Headphones / AirPods / Headsets: Barge-in is ENABLED with instantaneous full-duplex responsiveness.
      - Built-in laptop speakers: Barge-in is DISABLED during agent speech (acoustic safe mode)
        to completely eliminate speaker bleed, premature cutoffs, and preserve 100% full loud volume.
    """
    if isinstance(barge_in_setting, str) and barge_in_setting.lower() == "auto":
        builtin = is_using_builtin_speakers()
        if builtin:
            return False, True
        return True, False
    elif bool(barge_in_setting) is True:
        builtin = is_using_builtin_speakers()
        return True, builtin
    else:
        return False, False


class AudioRecorder:
    """Records audio from default input device with robust, snappy neural Silero VAD and Active Barge-In."""

    def __init__(
        self,
        sample_rate: int = 16000,
        energy_threshold: float = 0.004,
        silence_duration: float = 2.0,
        max_record_seconds: float = 45.0,
        barge_in: Any = "auto",
        barge_in_sensitivity: float = 1.0,
        vad_engine: Literal["silero", "energy", "auto"] = "auto",
        speech_threshold: float = 0.5,
    ):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.max_record_seconds = max_record_seconds
        self.barge_in = barge_in
        self.barge_in_sensitivity = max(0.1, barge_in_sensitivity)
        self.vad_engine = vad_engine
        self.speech_threshold = speech_threshold
        self.vad = VoiceActivityDetector(
            engine=vad_engine,
            speech_threshold=speech_threshold,
            energy_threshold=energy_threshold,
            sample_rate=sample_rate,
        )
        self.stop_event = threading.Event()

    def stop(self):
        """Immediately signal recorder to stop and process captured audio."""
        self.stop_event.set()

    def _create_input_stream(self):
        """Create standard sounddevice InputStream for clean, loud, unattenuated audio capture."""
        return sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32")

    def record_speech_auto(
        self,
        on_speech_start: Optional[Callable[[], None]] = None,
        on_listening_tick: Optional[Callable[[float], None]] = None,
        on_pause_change: Optional[Callable[[bool], None]] = None,
        on_barge_in: Optional[Callable[[], None]] = None,
        on_live_transcript: Optional[Callable[[str], None]] = None,
        on_chunk: Optional[Callable[[np.ndarray], None]] = None,
        stop_event: Optional[threading.Event] = None,
        cancel_on_typing: bool = True,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Tuple[np.ndarray, Path]:
        """
        Record audio from mic until speech is detected and followed by natural silence.
        When barge_in is True/"auto": actively monitors microphone during agent speech playback.
        If user speaks, immediately kills agent speech output and captures user prompt seamlessly.
        When barge_in is False: pauses and discards incoming audio when an AI agent is speaking.
        Can be terminated immediately via Enter key / stop_event.
        """
        self.stop_event.clear()
        trigger_stop = stop_event or self.stop_event
        cancelled_by_user = False
        _last_speech_stop_time = 0.0

        # Pause background monitor to yield device
        try:
            from voicefi.audio.monitor import LiveVADMonitor

            LiveVADMonitor.get_instance().pause()
        except ImportError:
            pass

        kb_listener = None
        try:
            from pynput import keyboard
            from voicefi.tts.base import is_escape_key

            def _on_key_press(k):
                nonlocal cancelled_by_user
                if is_escape_key(k):
                    from voicefi.tts.base import stop_all_speech, record_speech_stopped

                    cancelled_by_user = True
                    record_speech_stopped()
                    stop_all_speech()
                    self.stop_event.set()
                elif cancel_on_typing:
                    # Ignore typing cancellations during startup grace period (0.6s) so hotkey chords don't self-cancel
                    if (time.time() - start_time) < 0.6:
                        return
                    if speech_started:
                        return

                    from voicefi.tts.base import is_agent_speaking, is_system_audio_playing

                    if not is_agent_speaking() and not is_system_audio_playing():
                        # Exclude modifier keys so shortcuts like Ctrl+R don't trigger typing cancel
                        is_mod = False
                        for mod_attr in (
                            "ctrl",
                            "ctrl_l",
                            "ctrl_r",
                            "shift",
                            "shift_l",
                            "shift_r",
                            "alt",
                            "alt_l",
                            "alt_r",
                            "cmd",
                            "cmd_l",
                            "cmd_r",
                            "caps_lock",
                        ):
                            if hasattr(keyboard.Key, mod_attr) and k == getattr(
                                keyboard.Key, mod_attr
                            ):
                                is_mod = True
                                break
                        if not is_mod:
                            if hasattr(keyboard.Key, "enter") and k in (
                                keyboard.Key.enter,
                                keyboard.Key.space,
                                keyboard.Key.tab,
                            ):
                                return
                            cancelled_by_user = True
                            self.stop_event.set()

            kb_listener = keyboard.Listener(on_press=_on_key_press)
            kb_listener.daemon = True
            kb_listener.start()
        except Exception:
            kb_listener = None

        try:
            chunk_duration = 0.05  # 50ms chunks for rapid response
            chunk_size = int(self.sample_rate * chunk_duration)

            self.vad.reset()

            recorded_frames = []
            speech_started = False
            speech_start_notified = False
            speech_start_time = 0.0
            speech_candidate_chunks = 0
            consecutive_silence_chunks = 0
            # Silence pause needed to finish (honors Fibonacci scale from 1s to 11s)
            chunks_needed_for_silence = max(
                6, int(max(0.4, float(self.silence_duration)) / chunk_duration)
            )
            start_time = time.time()

            # Dynamic noise floor and speech detection tracking
            running_noise_floor = 0.006
            smoothed_energy = 0.0
            peak_speech_energy = 0.0

            is_paused = False
            cooldown_remaining_chunks = 0
            barge_in_candidate_chunks = 0
            agent_speaking_chunks = 0
            speaker_bleed_floor = 0.0
            agent_speaking_pre_roll = []  # Ring buffer to preserve onset syllables on barge-in

            # Live streaming transcription worker
            streaming_lock = threading.Lock()
            latest_partial_audio = None
            is_transcribing = False
            last_stream_chunk_count = 0

            def _partial_worker():
                nonlocal is_transcribing, latest_partial_audio
                while not (trigger_stop.is_set() or self.stop_event.is_set()):
                    audio_to_transcribe = None
                    with streaming_lock:
                        if latest_partial_audio is not None and not is_transcribing:
                            audio_to_transcribe = latest_partial_audio
                            latest_partial_audio = None
                            is_transcribing = True

                    if audio_to_transcribe is not None:
                        try:
                            from voicefi.stt.whisper_local import WhisperLocalSTT

                            stt = WhisperLocalSTT()
                            txt = stt.transcribe(audio_to_transcribe, sample_rate=self.sample_rate)
                            if txt and on_live_transcript:
                                on_live_transcript(txt)
                        except Exception:
                            pass
                        finally:
                            with streaming_lock:
                                is_transcribing = False

                    time.sleep(0.12)

            if on_live_transcript:
                transcription_thread = threading.Thread(target=_partial_worker, daemon=True)
                transcription_thread.start()

            with self._create_input_stream() as stream:
                chunk_count = 0
                while True:
                    # Check for manual instant stop (e.g. Enter, Space, Esc, stop_event, or cross-process Esc kill)
                    from voicefi.tts.base import is_speech_interrupted

                    if (
                        trigger_stop.is_set()
                        or self.stop_event.is_set()
                        or is_speech_interrupted(start_time)
                    ):
                        cancelled_by_user = True
                        break

                    chunk, overflowed = stream.read(chunk_size)
                    if (
                        trigger_stop.is_set()
                        or self.stop_event.is_set()
                        or is_speech_interrupted(start_time)
                    ):
                        cancelled_by_user = True
                        break

                    audio_chunk = chunk.flatten()

                    # Check if an AI agent is speaking aloud
                    agent_speaking = is_agent_speaking()

                    if agent_speaking:
                        is_barge_in_on, is_safe_mode = resolve_barge_in_mode(self.barge_in)
                        if is_barge_in_on:
                            audio_playing = is_agent_audio_playing()
                            if not audio_playing:
                                # TTS synthesis/download wait phase: sound is not producing out of speakers yet
                                agent_speaking_chunks = 0
                                speaker_bleed_floor = 0.0
                                barge_in_candidate_chunks = 0
                                recorded_frames.clear()
                                start_time += chunk_duration
                                if speech_start_time > 0:
                                    speech_start_time += chunk_duration
                                continue

                            agent_speaking_chunks += 1
                            vad_res = self.vad.process(audio_chunk)
                            smoothed_energy = vad_res["energy"]
                            speech_conf = vad_res["confidence"]
                            active_engine = vad_res["engine"]

                            # Dynamic acoustic threshold & grace window
                            if is_safe_mode:
                                # Built-in laptop speakers: adapt against speaker bleed
                                grace_chunks = max(
                                    10, int(1.0 / chunk_duration)
                                )  # 1.0s settling window from audio onset
                                in_grace_period = agent_speaking_chunks < grace_chunks
                                if in_grace_period:
                                    # During grace period, track peak speaker bleed floor
                                    speaker_bleed_floor = max(speaker_bleed_floor, smoothed_energy)
                                else:
                                    # Post-grace: track baseline for low/moderate levels so human speech doesn't inflate floor
                                    if smoothed_energy < (speaker_bleed_floor * 1.35):
                                        speaker_bleed_floor = (
                                            0.95 * speaker_bleed_floor + 0.05 * smoothed_energy
                                        )

                                barge_in_threshold = (
                                    max(
                                        0.045,
                                        speaker_bleed_floor * 1.30 + 0.010,
                                    )
                                    / self.barge_in_sensitivity
                                )
                                required_chunks = 2 if active_engine == "silero" else 3
                            else:
                                # Headphones / AirPods: responsive threshold with robust floor against ambient noise
                                grace_chunks = 6  # 300ms settling window from audio onset
                                min_barge_energy = max(
                                    0.015,
                                    self.energy_threshold * 1.5,
                                    self.vad.running_noise_floor * 1.5,
                                )
                                barge_in_threshold = (
                                    max(
                                        0.035,
                                        self.energy_threshold * 2.2,
                                        (self.vad.running_noise_floor * 2.0 + 0.012),
                                    )
                                    / self.barge_in_sensitivity
                                )
                                required_chunks = 2 if active_engine == "silero" else 3
                                in_grace_period = agent_speaking_chunks < grace_chunks

                            if on_listening_tick:
                                try:
                                    on_listening_tick(smoothed_energy, speech_conf, True)
                                except Exception:
                                    pass

                            agent_speaking_pre_roll.append(audio_chunk)
                            if len(agent_speaking_pre_roll) > 3:
                                agent_speaking_pre_roll.pop(0)

                            if in_grace_period:
                                barge_in_candidate_chunks = 0
                            else:
                                if active_engine == "silero":
                                    if is_safe_mode:
                                        # On built-in speakers, speaker audio has high speech_conf, so we require energy exceeding the bleed floor
                                        is_barge_candidate = (
                                            smoothed_energy > barge_in_threshold
                                            and speech_conf >= 0.35
                                        )
                                    else:
                                        # On headphones, require minimum energy floor AND speech confidence to prevent faint room noise / echo false positives
                                        is_barge_candidate = (
                                            smoothed_energy > barge_in_threshold
                                            and speech_conf >= 0.25
                                        ) or (
                                            smoothed_energy > min_barge_energy
                                            and speech_conf >= 0.75
                                        )
                                else:
                                    is_barge_candidate = smoothed_energy > barge_in_threshold

                                if is_barge_candidate:
                                    barge_in_candidate_chunks += 1
                                    if barge_in_candidate_chunks >= required_chunks:
                                        # User spoke over agent speech -> BARGE IN!
                                        mode_desc = f"{'acoustic safe-mode' if is_safe_mode else 'headphones'} [{active_engine}]"
                                        print(
                                            f"[VAD] ⚡ Barge-In detected ({mode_desc}, conf={speech_conf:.2f}, energy={smoothed_energy:.4f}, thresh={barge_in_threshold:.4f}) -> stopping agent speech"
                                        )
                                        from voicefi.tts.base import stop_all_speech

                                        stop_all_speech()
                                        try:
                                            from voicefi.telemetry import capture_barge_in_event

                                            capture_barge_in_event(
                                                device_type="acoustic_safe_mode"
                                                if is_safe_mode
                                                else "headphones",
                                                is_full_duplex=(not is_safe_mode),
                                                ambient_energy_level=smoothed_energy,
                                            )
                                        except Exception:
                                            pass
                                        if on_barge_in:
                                            try:
                                                on_barge_in()
                                            except Exception:
                                                pass

                                        # Clear any past frames before barge-in to avoid speaker bleed
                                        recorded_frames.clear()
                                        speech_started = True
                                        speech_start_time = time.time()
                                        peak_speech_energy = smoothed_energy
                                        is_paused = False
                                        barge_in_candidate_chunks = 0
                                        agent_speaking_chunks = 0
                                        speaker_bleed_floor = 0.0
                                        if on_speech_start and not speech_start_notified:
                                            on_speech_start()
                                            speech_start_notified = True
                                        continue
                                else:
                                    barge_in_candidate_chunks = max(
                                        0, barge_in_candidate_chunks - 1
                                    )

                            if not is_paused:
                                is_paused = True
                                mode_info = f"{'acoustic safe-mode' if is_safe_mode else 'active listening'} [{active_engine}]"
                                print(
                                    f"[VAD] Agent is speaking aloud -> barge-in monitoring ({mode_info})..."
                                )
                                if on_pause_change:
                                    try:
                                        on_pause_change(True)
                                    except Exception:
                                        pass
                                recorded_frames.clear()

                            # Freeze timeout timer while agent is speaking
                            start_time += chunk_duration
                            if speech_start_time > 0:
                                speech_start_time += chunk_duration
                            continue
                        else:
                            # Standard mute mode: pause and discard all frames
                            if not is_paused:
                                is_paused = True
                                print(
                                    "[VAD] Agent is speaking aloud -> pausing mic capture & purging audio bleed"
                                )
                                if on_pause_change:
                                    try:
                                        on_pause_change(True)
                                    except Exception:
                                        pass
                                recorded_frames.clear()
                                speech_started = False
                                speech_start_notified = False
                                consecutive_silence_chunks = 0
                                peak_speech_energy = 0.0

                            start_time += chunk_duration
                            if speech_start_time > 0:
                                speech_start_time += chunk_duration
                            continue

                    if is_paused and not agent_speaking:
                        # Agent just finished speaking: enter acoustic cooldown to let room reverb dissipate
                        is_paused = False
                        cooldown_remaining_chunks = 8  # ~400ms acoustic dissipation window
                        running_noise_floor = 0.006
                        smoothed_energy = 0.0
                        barge_in_candidate_chunks = 0
                        agent_speaking_chunks = 0
                        speaker_bleed_floor = 0.0
                        agent_speaking_pre_roll.clear()
                        recorded_frames.clear()
                        print(
                            "[VAD] Agent finished speaking -> cooling down & resuming mic capture"
                        )
                        if on_pause_change:
                            try:
                                on_pause_change(False)
                            except Exception:
                                pass

                    if cooldown_remaining_chunks > 0:
                        cooldown_remaining_chunks -= 1
                        start_time += chunk_duration
                        continue

                    recorded_frames.append(audio_chunk)

                    if on_chunk:
                        try:
                            on_chunk(audio_chunk)
                        except Exception:
                            pass

                    chunk_count += 1
                    vad_result = self.vad.process(audio_chunk)
                    smoothed_energy = vad_result["energy"]
                    speech_confidence = vad_result["confidence"]
                    is_speech = vad_result["is_speech"]
                    active_engine = vad_result["engine"]
                    active_threshold = vad_result["active_threshold"]

                    now = time.time()
                    elapsed = now - start_time

                    if on_listening_tick:
                        try:
                            on_listening_tick(smoothed_energy, speech_confidence, is_speech)
                        except TypeError:
                            on_listening_tick(smoothed_energy)

                    # Dynamic speech detection with neural/energy tracking
                    if is_speech:
                        if not speech_started:
                            speech_candidate_chunks += 1
                            min_candidates = 1 if active_engine == "silero" else 2
                            if speech_candidate_chunks >= min_candidates:
                                speech_started = True
                                speech_start_time = now
                                speech_candidate_chunks = 0
                                print(
                                    f"[VAD] Speech started (engine={active_engine}, conf={speech_confidence:.2f}, energy={smoothed_energy:.4f})"
                                )
                                if on_speech_start and not speech_start_notified:
                                    on_speech_start()
                                    speech_start_notified = True
                        else:
                            speech_candidate_chunks = 0
                        peak_speech_energy = max(peak_speech_energy, smoothed_energy)
                        consecutive_silence_chunks = max(0, consecutive_silence_chunks - 3)
                    else:
                        speech_candidate_chunks = 0
                        if speech_started:
                            if active_engine == "silero":
                                is_silence = speech_confidence < 0.35
                            else:
                                silence_cutoff = max(
                                    self.vad.running_noise_floor * 1.25,
                                    min(active_threshold * 0.85, peak_speech_energy * 0.3),
                                )
                                is_silence = smoothed_energy <= silence_cutoff

                            if is_silence:
                                consecutive_silence_chunks += 1
                            else:
                                consecutive_silence_chunks = max(0, consecutive_silence_chunks - 2)

                            if consecutive_silence_chunks >= chunks_needed_for_silence:
                                print(
                                    f"[VAD] Natural silence detected ({consecutive_silence_chunks * chunk_duration:.2f}s, engine={active_engine}) -> finishing recording"
                                )
                                break

                    # Stream partial live transcription to HUD while user speaks
                    if (
                        on_live_transcript
                        and speech_started
                        and (chunk_count - last_stream_chunk_count) >= 6
                    ):
                        last_stream_chunk_count = chunk_count
                        with streaming_lock:
                            if not is_transcribing and recorded_frames:
                                latest_partial_audio = np.concatenate(recorded_frames, axis=0)

                    # Max speech burst cutoff (dynamically scaled for conversational flow or extended brain dumps)
                    max_burst_limit = max(30.0, float(self.silence_duration) * 3.0)
                    if speech_started and (now - speech_start_time) >= max_burst_limit:
                        print(
                            f"[VAD] Maximum continuous speech burst ({max_burst_limit:.1f}s) reached -> finishing"
                        )
                        break

                    # Max total record duration safety cutoff
                    if elapsed >= self.max_record_seconds:
                        print(
                            f"[VAD] Maximum record duration ({self.max_record_seconds}s) reached -> finishing"
                        )
                        break

                    # If no speech at all after timeout seconds, exit gracefully
                    speech_timeout = float(timeout) if timeout is not None else 12.0
                    if not speech_started and elapsed >= speech_timeout:
                        print(
                            f"[VAD] No speech detected within {speech_timeout:.1f}s -> closing mic"
                        )
                        break

            if cancelled_by_user or not recorded_frames or not speech_started:
                return np.zeros(0, dtype=np.float32), None

            full_audio = np.concatenate(recorded_frames, axis=0)

            # Save to temporary WAV file
            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_path = Path(temp_wav.name)
            temp_wav.close()

            sf.write(str(temp_path), full_audio, self.sample_rate)
            return full_audio, temp_path
        finally:
            if kb_listener is not None:
                try:
                    kb_listener.stop()
                except Exception:
                    pass

            # Resume background monitor
            try:
                from voicefi.audio.monitor import LiveVADMonitor

                LiveVADMonitor.get_instance().resume()
            except ImportError:
                pass

    def record_push_to_talk(
        self,
        stop_event: Optional[threading.Event] = None,
        on_listening_tick: Optional[Callable[[float], None]] = None,
        on_chunk: Optional[Callable[[np.ndarray], None]] = None,
        on_pause_change: Optional[Callable[[bool], None]] = None,
        on_barge_in: Optional[Callable[[], None]] = None,
        on_live_transcript: Optional[Callable[[str], None]] = None,
        ptt_release_delay_ms: int = 150,
    ) -> Tuple[np.ndarray, Path]:
        """
        Record audio in Push-to-Talk (PTT) mode.
        Continues recording while stop_event is NOT set.
        When barge_in is True: instantly kills ongoing agent speech playback on PTT trigger.
        When barge_in is False: pauses and discards incoming audio when an AI agent is speaking.
        Once stop_event is triggered (key released), captures a brief safety buffer (~150ms)
        to prevent trailing phoneme cutoffs, then immediately stops with 0ms silence delay.
        """
        self.stop_event.clear()
        trigger_stop = stop_event or self.stop_event
        cancelled_by_user = False

        # Pause background monitor to yield device
        try:
            from voicefi.audio.monitor import LiveVADMonitor

            LiveVADMonitor.get_instance().pause()
        except ImportError:
            pass

        kb_listener = None
        try:
            from pynput import keyboard
            from voicefi.tts.base import is_escape_key

            def _on_ptt_key(k):
                nonlocal cancelled_by_user
                if is_escape_key(k):
                    from voicefi.tts.base import stop_all_speech, record_speech_stopped

                    cancelled_by_user = True
                    record_speech_stopped()
                    stop_all_speech()
                    self.stop_event.set()

            kb_listener = keyboard.Listener(on_press=_on_ptt_key)
            kb_listener.daemon = True
            kb_listener.start()
        except Exception:
            kb_listener = None

        try:
            chunk_duration = 0.05  # 50ms chunks

            chunk_size = int(self.sample_rate * chunk_duration)
            extra_chunks_after_stop = max(1, int((ptt_release_delay_ms / 1000.0) / chunk_duration))

            recorded_frames = []
            smoothed_energy = 0.0
            start_time = time.time()
            stop_signaled_count = 0

            is_paused = False
            cooldown_remaining_chunks = 0

            # Live streaming transcription worker
            streaming_lock = threading.Lock()
            latest_partial_audio = None
            is_transcribing = False
            last_stream_chunk_count = 0

            def _partial_worker():
                nonlocal is_transcribing, latest_partial_audio
                while not (trigger_stop.is_set() or self.stop_event.is_set()):
                    audio_to_transcribe = None
                    with streaming_lock:
                        if latest_partial_audio is not None and not is_transcribing:
                            audio_to_transcribe = latest_partial_audio
                            latest_partial_audio = None
                            is_transcribing = True

                    if audio_to_transcribe is not None:
                        try:
                            from voicefi.stt.whisper_local import WhisperLocalSTT

                            stt = WhisperLocalSTT()
                            txt = stt.transcribe(audio_to_transcribe, sample_rate=self.sample_rate)
                            if txt and on_live_transcript:
                                on_live_transcript(txt)
                        except Exception:
                            pass
                        finally:
                            with streaming_lock:
                                is_transcribing = False

                    time.sleep(0.12)

            if on_live_transcript:
                transcription_thread = threading.Thread(target=_partial_worker, daemon=True)
                transcription_thread.start()

            with self._create_input_stream() as stream:
                chunk_count = 0
                while True:
                    chunk, overflowed = stream.read(chunk_size)
                    audio_chunk = chunk.flatten()
                    chunk_count += 1

                    agent_speaking = is_agent_speaking()
                    if agent_speaking:
                        is_barge_in_on, _ = resolve_barge_in_mode(self.barge_in)
                        if is_barge_in_on:
                            from voicefi.tts.base import stop_all_speech

                            stop_all_speech()
                            if on_barge_in:
                                try:
                                    on_barge_in()
                                except Exception:
                                    pass
                            is_paused = False
                        else:
                            if not is_paused:
                                is_paused = True
                                if on_pause_change:
                                    try:
                                        on_pause_change(True)
                                    except Exception:
                                        pass
                                if recorded_frames:
                                    recorded_frames = (
                                        recorded_frames[:-5] if len(recorded_frames) > 5 else []
                                    )
                            start_time += chunk_duration
                            continue

                    if is_paused and not agent_speaking:
                        is_paused = False
                        cooldown_remaining_chunks = 5
                        if on_pause_change:
                            try:
                                on_pause_change(False)
                            except Exception:
                                pass

                    if cooldown_remaining_chunks > 0:
                        cooldown_remaining_chunks -= 1
                        start_time += chunk_duration
                        continue

                    recorded_frames.append(audio_chunk)

                    if on_chunk:
                        try:
                            on_chunk(audio_chunk)
                        except Exception:
                            pass

                    # Process VAD for UI visualizer & speech tracking
                    vad_result = self.vad.process(audio_chunk)
                    smoothed_energy = vad_result["energy"]
                    speech_confidence = vad_result["confidence"]
                    is_speech = vad_result["is_speech"]

                    if on_listening_tick:
                        try:
                            on_listening_tick(smoothed_energy, speech_confidence, is_speech)
                        except TypeError:
                            on_listening_tick(smoothed_energy)

                    # Stream partial live transcription to HUD
                    if on_live_transcript and (chunk_count - last_stream_chunk_count) >= 6:
                        last_stream_chunk_count = chunk_count
                        with streaming_lock:
                            if not is_transcribing and recorded_frames:
                                latest_partial_audio = np.concatenate(recorded_frames, axis=0)

                    if trigger_stop.is_set():
                        stop_signaled_count += 1
                        if stop_signaled_count >= extra_chunks_after_stop:
                            break

                    # Max duration safety cutoff
                    if (time.time() - start_time) >= self.max_record_seconds:
                        break

            if cancelled_by_user or not recorded_frames:
                full_audio = np.zeros(self.sample_rate, dtype=np.float32)
            else:
                full_audio = np.concatenate(recorded_frames, axis=0)

            temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_path = Path(temp_wav.name)
            temp_wav.close()

            sf.write(str(temp_path), full_audio, self.sample_rate)
            return full_audio, temp_path
        finally:
            if kb_listener is not None:
                try:
                    kb_listener.stop()
                except Exception:
                    pass

            # Resume background monitor
            try:
                from voicefi.audio.monitor import LiveVADMonitor

                LiveVADMonitor.get_instance().resume()
            except ImportError:
                pass

    def record_fixed_duration(self, seconds: float) -> Tuple[np.ndarray, Path]:
        """Record for an exact duration in seconds."""
        num_frames = int(self.sample_rate * seconds)
        audio = sd.rec(num_frames, samplerate=self.sample_rate, channels=1, dtype="float32")
        sd.wait()
        audio_flat = audio.flatten()

        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_path = Path(temp_wav.name)
        temp_wav.close()

        sf.write(str(temp_path), audio_flat, self.sample_rate)
        return audio_flat, temp_path
