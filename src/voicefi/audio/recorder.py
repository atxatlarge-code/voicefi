"""
Microphone audio capture with Adaptive Voice Activity Detection (VAD).
Uses smoothed energy tracking and robust 0.8s silence cutoff to prevent background noise hangs.
Supports instant manual completion via Enter key / stop_event.
"""

import os
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
        vad_engine: Optional[Literal["silero", "energy", "auto"]] = None,
        speech_threshold: Optional[float] = None,
        turn_detection: Optional[Literal["auto", "cue", "lexical", "fixed"]] = None,
        turn_model: Optional[str] = None,
        smart_turn_enabled: Optional[bool] = None,
        near_field_gate: Optional[bool] = None,
        near_field_dropoff_ratio: Optional[float] = None,
        near_field_min_energy: Optional[float] = None,
    ):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.max_record_seconds = max_record_seconds
        self.barge_in = barge_in
        self.barge_in_sensitivity = max(0.1, barge_in_sensitivity)
        self._explicit_turn_detection = turn_detection is not None

        # Pull VAD defaults from config if not explicitly specified
        if (
            vad_engine is None
            or speech_threshold is None
            or turn_detection is None
            or turn_model is None
            or smart_turn_enabled is None
            or near_field_gate is None
            or near_field_dropoff_ratio is None
            or near_field_min_energy is None
        ):
            try:
                from voicefi.config import load_config

                cfg_vad = load_config().vad
                if vad_engine is None:
                    vad_engine = getattr(cfg_vad, "engine", "auto")
                if speech_threshold is None:
                    speech_threshold = getattr(cfg_vad, "speech_threshold", 0.37)
                if turn_detection is None:
                    turn_detection = getattr(cfg_vad, "turn_detection", "auto")
                if turn_model is None:
                    turn_model = getattr(cfg_vad, "turn_model", "qwen2.5-coder:1.5b")
                if smart_turn_enabled is None:
                    smart_turn_enabled = getattr(cfg_vad, "smart_turn_enabled", True)
                if near_field_gate is None:
                    near_field_gate = getattr(cfg_vad, "near_field_gate", True)
                if near_field_dropoff_ratio is None:
                    near_field_dropoff_ratio = getattr(cfg_vad, "near_field_dropoff_ratio", 0.22)
                if near_field_min_energy is None:
                    near_field_min_energy = getattr(cfg_vad, "near_field_min_energy", 0.0075)
            except Exception:
                pass

        self.vad_engine = vad_engine or "auto"
        self.speech_threshold = speech_threshold if speech_threshold is not None else 0.37
        self.turn_detection: Literal["auto", "cue", "lexical", "fixed"] = (
            turn_detection or "auto"
        )
        self.turn_model = turn_model or "qwen2.5-coder:1.5b"
        self.smart_turn_enabled = (
            bool(smart_turn_enabled) if smart_turn_enabled is not None else True
        )
        self.near_field_gate = bool(near_field_gate) if near_field_gate is not None else True
        self.near_field_dropoff_ratio = (
            float(near_field_dropoff_ratio) if near_field_dropoff_ratio is not None else 0.22
        )
        self.near_field_min_energy = (
            float(near_field_min_energy) if near_field_min_energy is not None else 0.0075
        )

        self.vad = VoiceActivityDetector(
            engine=self.vad_engine,
            speech_threshold=self.speech_threshold,
            energy_threshold=energy_threshold,
            sample_rate=sample_rate,
            near_field_gate=self.near_field_gate,
            near_field_min_energy=self.near_field_min_energy,
        )
        from voicefi.audio.turn_detector import CueTurnCascade

        self.turn_detector = CueTurnCascade(
            mode=self.turn_detection,
            turn_model=self.turn_model,
            smart_turn_enabled=self.smart_turn_enabled,
        )
        self.last_turn_decision = None
        self.stop_event = threading.Event()
        self._stream_closed_event = threading.Event()
        self._stream_closed_event.set()
        self.cancelled = False
        self.stopped_by_enter = False

    def stop(self):
        """Immediately signal recorder to stop and process captured audio."""
        self.stop_event.set()

    def cancel(self):
        """Immediately abort recording and discard any captured audio."""
        self.cancelled = True
        self.stop_event.set()

    def _create_input_stream(self):
        """Create standard sounddevice InputStream for clean, loud, unattenuated audio capture."""
        try:
            from voicefi.audio.device import auto_pin_mac_microphone

            pinned, msg = auto_pin_mac_microphone()
            if pinned and "Already pinned" not in msg:
                time.sleep(0.06)
        except Exception:
            pass

        try:
            return sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32")
        except Exception as first_err:
            # Self-heal PortAudio CoreAudio AUHAL cache (e.g. PaErrorCode -9986 / err='!obj' after Bluetooth/input switch)
            print(f"[AudioRecorder] 🔄 Self-healing PortAudio InputStream ({first_err})...")
            try:
                time.sleep(0.08)
                if hasattr(sd, "_terminate") and hasattr(sd, "_initialize"):
                    sd._terminate()
                    sd._initialize()
            except Exception:
                pass
            try:
                return sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32")
            except Exception:
                # Fallback: explicitly locate built-in or valid input device index
                for idx, dev in enumerate(sd.query_devices()):
                    if dev.get("max_input_channels", 0) > 0:
                        name_low = str(dev.get("name", "")).lower()
                        if "macbook" in name_low or "built-in" in name_low or "microphone" in name_low:
                            return sd.InputStream(
                                device=idx,
                                samplerate=self.sample_rate,
                                channels=1,
                                dtype="float32",
                            )
                raise

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
        conv_id: Optional[str] = None,
        agent_name: Optional[str] = None,
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
        self.cancelled = False
        self.stopped_by_enter = False
        trigger_stop = stop_event or self.stop_event
        cancelled_by_user = False
        _last_speech_stop_time = 0.0
        is_dictation = bool(kwargs.get("is_dictation", False))

        # Set cross-process recording flag to yield device from background LaunchAgent
        try:
            from voicefi.tts.base import set_mic_recording

            set_mic_recording(True, state="listening", conv_id=conv_id, agent_name=agent_name)
        except Exception:
            pass

        # Pause background monitor and wake-word listener to yield device
        try:
            from voicefi.audio.wakeword import WakeWordListener

            WakeWordListener.pause_all()
        except ImportError:
            pass
        try:
            from voicefi.audio.monitor import LiveVADMonitor

            LiveVADMonitor.get_instance().pause()
        except ImportError:
            pass

        # Check active media playback (Quick Look or QuickTime) before capturing audio
        try:
            from voicefi.audio.media_detection import is_active_media_playing

            if is_active_media_playing():
                print(
                    "[AudioRecorder] 🎬 Media playback active. Suppressing mic capture to avoid clip feedback."
                )
                cancelled_by_user = True
                self.stop_event.set()
        except Exception:
            pass

        kb_listener = None
        try:
            from pynput import keyboard
            from voicefi.tts.base import is_escape_key

            shift_held = False

            def _on_key_press(k):
                nonlocal cancelled_by_user, shift_held
                if is_escape_key(k):
                    from voicefi.tts.base import stop_all_speech, record_speech_stopped

                    cancelled_by_user = True
                    record_speech_stopped()
                    stop_all_speech()
                    self.stop_event.set()
                elif hasattr(keyboard.Key, "shift") and k in (
                    getattr(keyboard.Key, "shift", None),
                    getattr(keyboard.Key, "shift_l", None),
                    getattr(keyboard.Key, "shift_r", None),
                ):
                    shift_held = True
                elif is_dictation and hasattr(keyboard.Key, "enter") and k == keyboard.Key.enter:
                    # Bare Enter cleanly commits and stops dictation; Shift+Enter creates a multiline newline
                    if not shift_held:
                        print("[VAD] ⌨️ Enter key pressed during dictation -> committing and finishing")
                        self.stopped_by_enter = True
                        self.stop_event.set()
                elif cancel_on_typing:
                    # Ignore typing cancellations during startup grace period (0.6s) so hotkey chords don't self-cancel
                    if (time.time() - start_time) < 0.6:
                        return
                    if speech_started:
                        return

                    # Check modifier/special keys first (0 syscalls, 0 subprocesses on CGEventTap thread!)
                    vk = getattr(k, "vk", None)
                    if vk in (54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 36, 76, 49, 48):
                        return
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
                        "enter",
                        "space",
                        "tab",
                    ):
                        if hasattr(keyboard.Key, mod_attr) and k == getattr(
                            keyboard.Key, mod_attr
                        ):
                            is_mod = True
                            break
                    if is_mod:
                        return

                    # CRITICAL: Never call is_system_audio_playing() here because it runs pgrep subprocesses
                    # synchronously on the macOS CGEventTap thread, stalling game/OS keystrokes!
                    from voicefi.tts import base as _tts_base
                    from voicefi.audio.output_lock import is_audio_output_locked

                    if not _tts_base._IN_PROCESS_SPEAKING and not _tts_base._IN_PROCESS_AUDIO_PLAYING and not is_audio_output_locked():
                        cancelled_by_user = True
                        self.stop_event.set()

            def _on_key_release(k):
                nonlocal shift_held
                if hasattr(keyboard.Key, "shift") and k in (
                    getattr(keyboard.Key, "shift", None),
                    getattr(keyboard.Key, "shift_l", None),
                    getattr(keyboard.Key, "shift_r", None),
                ):
                    shift_held = False

            from voicefi.tts.base import is_tray_hotkey_listener_active

            if not is_tray_hotkey_listener_active():
                kb_listener = keyboard.Listener(on_press=_on_key_press, on_release=_on_key_release)
                kb_listener.daemon = True
                kb_listener.start()
        except Exception:
            kb_listener = None

        try:
            chunk_duration = 0.05  # 50ms chunks for rapid response
            chunk_size = int(self.sample_rate * chunk_duration)

            self.vad.reset()

            recorded_frames = []
            pre_speech_ring = []  # 300ms (6-chunk) pre-roll ring buffer before speech_started
            speech_started = False
            speech_start_notified = False
            speech_start_time = 0.0
            speech_candidate_chunks = 0
            active_speech_chunks = 0
            consecutive_silence_chunks = 0
            # Silence pause needed to finish (honors Fibonacci scale from 1s to 11s)
            baseline_silence_chunks = max(
                6, int(max(0.4, float(self.silence_duration)) / chunk_duration)
            )
            chunks_needed_for_silence = baseline_silence_chunks
            start_time = time.time()

            # Dynamic noise floor and speech detection tracking
            running_noise_floor = 0.006
            smoothed_energy = 0.0
            peak_speech_energy = 0.0
            last_touch_time = 0.0

            is_paused = False
            is_barge_in_on, _ = resolve_barge_in_mode(self.barge_in)
            is_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
            use_dynamic_turn = (
                self.turn_detection != "fixed"
                and self.turn_detector is not None
                and (not is_test or self._explicit_turn_detection)
            )
            pause_eval_chunk = 7  # Evaluate turn completion at 350ms of silence
            pause_evaluated = False
            thought_holds = 0
            false_starts_ignored = 0
            self.last_turn_decision = None

            cooldown_remaining_chunks = (
                0 if (is_barge_in_on or is_test) else 3
            )  # 150ms acoustic settle margin
            barge_in_candidate_chunks = 0
            agent_speaking_chunks = 0
            speaker_bleed_floor = 0.0
            agent_speaking_pre_roll = []  # Ring buffer to preserve onset syllables on barge-in
            stop_when_agent_finishes = bool(kwargs.get("stop_when_agent_finishes", False))
            agent_done_event = kwargs.get("agent_done_event")
            saw_agent_speaking = False

            # Live streaming transcription worker
            streaming_lock = threading.Lock()
            latest_partial_audio = None
            initial_prompt_preview: Optional[str] = (
                kwargs.get("initial_prompt_preview") or kwargs.get("initial_partial_text")
            )
            latest_partial_text: Optional[str] = initial_prompt_preview
            is_transcribing = False
            last_stream_chunk_count = 0

            # Seed zero-gap handoff audio / initial prompt preview from WakeWordListener
            initial_audio = kwargs.get("initial_audio")
            if initial_audio is not None and len(initial_audio) > 0:
                flat_init = np.asarray(initial_audio, dtype=np.float32).flatten()
                init_chunks = [
                    flat_init[i : i + chunk_size]
                    for i in range(0, len(flat_init), chunk_size)
                    if len(flat_init[i : i + chunk_size]) > 0
                ]
                handoff_speech_chunks = 0
                for ch in init_chunks:
                    if len(ch) == chunk_size:
                        try:
                            vr = self.vad.process(ch)
                            if vr.get("is_speech"):
                                handoff_speech_chunks += 1
                        except Exception:
                            pass
                if (initial_prompt_preview and initial_prompt_preview.strip()) or handoff_speech_chunks >= 2:
                    recorded_frames.extend(init_chunks)
                    speech_started = True
                    speech_start_notified = True
                    speech_start_time = time.time()
                    active_speech_chunks = max(6, len(recorded_frames))
                    cooldown_remaining_chunks = 0
                    if on_speech_start:
                        try:
                            on_speech_start()
                        except Exception:
                            pass
                else:
                    # Keep up to 12 chunks (600ms) in pre_speech_ring so immediate continuation speech is never clipped,
                    # while waiting for actual speech onset if the user paused after saying the wake word.
                    pre_speech_ring.extend(init_chunks[-12:])
                    cooldown_remaining_chunks = 0
            elif initial_prompt_preview and initial_prompt_preview.strip():
                speech_started = True
                speech_start_notified = True
                speech_start_time = time.time()
                active_speech_chunks = 8
                cooldown_remaining_chunks = 0

            if initial_prompt_preview and initial_prompt_preview.strip() and on_live_transcript:
                try:
                    on_live_transcript(initial_prompt_preview.strip())
                except Exception:
                    pass

            def _partial_worker():
                nonlocal is_transcribing, latest_partial_audio, latest_partial_text
                stt_instance = None
                while not (trigger_stop.is_set() or self.stop_event.is_set()):
                    audio_to_transcribe = None
                    with streaming_lock:
                        if latest_partial_audio is not None and not is_transcribing:
                            audio_to_transcribe = latest_partial_audio
                            latest_partial_audio = None
                            is_transcribing = True

                    if audio_to_transcribe is not None:
                        try:
                            if stt_instance is None:
                                try:
                                    from voicefi.config import load_config
                                    from voicefi.stt import get_stt_engine

                                    cfg = load_config()
                                    if getattr(cfg.stt, "provider", "") in (
                                        "mlx_whisper",
                                        "mlx",
                                        "metal",
                                        "whisper_local",
                                        "auto",
                                    ):
                                        stt_instance = get_stt_engine(cfg)
                                except Exception:
                                    pass
                                if stt_instance is None:
                                    from voicefi.stt.whisper_local import WhisperLocalSTT

                                    stt_instance = WhisperLocalSTT()

                            # Keep live preview fast and continuous across full utterances up to 12s
                            max_preview_samples = int(self.sample_rate * 12.0)
                            preview_audio = (
                                audio_to_transcribe[-max_preview_samples:]
                                if len(audio_to_transcribe) > max_preview_samples
                                else audio_to_transcribe
                            )

                            txt = stt_instance.transcribe(
                                preview_audio, sample_rate=self.sample_rate
                            )
                            if txt:
                                try:
                                    from voicefi.tts.normalizer import collapse_repetitive_artifacts

                                    txt = collapse_repetitive_artifacts(txt)
                                except Exception:
                                    pass
                                try:
                                    from voicefi.integrations.active_listening import (
                                        ActiveListeningEngine,
                                    )

                                    mw, stripped = (
                                        ActiveListeningEngine.extract_wakeword_and_prompt(txt)
                                    )
                                    if mw and stripped:
                                        txt = stripped
                                except Exception:
                                    pass
                                if (
                                    initial_prompt_preview
                                    and initial_prompt_preview.strip()
                                    and not txt.lower().startswith(
                                        initial_prompt_preview.strip().lower()
                                    )
                                ):
                                    txt = f"{initial_prompt_preview.strip()} {txt}".strip()
                                latest_partial_text = txt
                                if is_dictation and txt:
                                    import re

                                    if re.search(
                                        r"(?i)\b(?:transcribe\s+done|stop\s+transcrib(?:ing|e)|done\s+transcribing|stop\s+dictat(?:ing|e))\b[.!?\s]*$",
                                        txt,
                                    ):
                                        print(
                                            f"[VAD] 🛑 Spoken stop command detected in dictation: {repr(txt)}"
                                        )
                                        self.stop_event.set()
                            if (
                                txt
                                and on_live_transcript
                                and not self.stop_event.is_set()
                                and not trigger_stop.is_set()
                                and not self.stopped_by_enter
                                and not self.cancelled
                                and not cancelled_by_user
                            ):
                                on_live_transcript(txt)
                        except Exception:
                            pass
                        finally:
                            with streaming_lock:
                                is_transcribing = False

                    time.sleep(0.12)

            if on_live_transcript or (use_dynamic_turn and not is_test):
                transcription_thread = threading.Thread(target=_partial_worker, daemon=True)
                transcription_thread.start()


            self._stream_closed_event.clear()
            try:
                with self._create_input_stream() as stream:
                    chunk_count = 0
                    while True:
                        # Check for manual instant stop (e.g. Enter, Space, Esc, stop_event, or cross-process Esc kill)
                        from voicefi.tts.base import is_speech_interrupted

                        if is_speech_interrupted(start_time):
                            cancelled_by_user = True
                            break

                        if trigger_stop.is_set() or self.stop_event.is_set():
                            break

                        chunk, overflowed = stream.read(chunk_size)
                        if is_speech_interrupted(start_time):
                            cancelled_by_user = True
                            break

                        if trigger_stop.is_set() or self.stop_event.is_set():
                            break

                        audio_chunk = chunk.flatten()
                        chunk_count += 1

                        # Check periodically if another conversation acquired the exclusive active listener lock
                        if conv_id and chunk_count % 6 == 0:
                            try:
                                from voicefi.integrations.turn_lock import get_current_active_listener

                                current_listener = get_current_active_listener()
                                if current_listener and current_listener != conv_id:
                                    print(
                                        f"[AudioRecorder] ⏸️ Mic preempted by conversation {current_listener[:8]} (this is {conv_id[:8]}). Closing mic.",
                                        flush=True,
                                    )
                                    cancelled_by_user = True
                                    break
                            except Exception:
                                pass

                        if not speech_started and chunk_count % 8 == 0:
                            try:
                                from voicefi.audio.media_detection import is_active_media_playing

                                if is_active_media_playing():
                                    print(
                                        "[AudioRecorder] 🎬 Media playback started during listen. Yielding immediately."
                                    )
                                    cancelled_by_user = True
                                    break
                            except Exception:
                                pass

                        # Check if an AI agent is speaking aloud
                        agent_speaking = is_agent_speaking()
                        if agent_speaking:
                            if not saw_agent_speaking:
                                saw_agent_speaking = True
                                self.vad.reset()
                        elif (
                            agent_done_event is not None
                            and not agent_done_event.is_set()
                            and not saw_agent_speaking
                            and not speech_started
                        ):
                            # TTS thread is starting up / synthesizing before acquiring speech_turn_lock
                            start_time += chunk_duration
                            continue
                        elif (
                            stop_when_agent_finishes
                            and not speech_started
                            and (
                                agent_done_event.is_set()
                                if agent_done_event is not None
                                else saw_agent_speaking
                            )
                        ):
                            print(
                                "[VAD] Agent finished speaking (auto_listen=False, no barge-in) -> closing mic"
                            )
                            break

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
                                    # Headphones / AirPods: responsive threshold with robust floor against ambient noise / café chatter
                                    grace_chunks = 6  # 300ms settling window from audio onset
                                    ambient_babble = getattr(self.vad, "ambient_babble_floor", 0.0)
                                    min_barge_energy = max(
                                        0.015,
                                        self.energy_threshold * 1.5,
                                        self.vad.running_noise_floor * 1.5,
                                        ambient_babble * 2.2,
                                    )
                                    barge_in_threshold = (
                                        max(
                                            0.035,
                                            self.energy_threshold * 2.2,
                                            (self.vad.running_noise_floor * 2.0 + 0.012),
                                            (ambient_babble * 2.8 + 0.012),
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
                                            # On headphones, require minimum energy floor AND speech confidence to prevent faint room noise / café false positives
                                            is_far_field_barge = bool(
                                                vad_res.get("is_far_field_speech", False)
                                            )
                                            is_barge_candidate = not is_far_field_barge and (
                                                (
                                                    smoothed_energy > barge_in_threshold
                                                    and speech_conf >= 0.25
                                                )
                                                or (
                                                    smoothed_energy > min_barge_energy
                                                    and speech_conf >= 0.75
                                                )
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

                                            # Clear past speaker bleed frames, but preserve onset frames to avoid clipped syllables
                                            recorded_frames.clear()
                                            if agent_speaking_pre_roll:
                                                recorded_frames.extend(agent_speaking_pre_roll)
                                                agent_speaking_pre_roll.clear()
                                            speech_started = True
                                            now_barge = time.time()
                                            start_time = now_barge + 0.05
                                            speech_start_time = now_barge
                                            peak_speech_energy = smoothed_energy
                                            is_paused = False
                                            barge_in_candidate_chunks = 0
                                            agent_speaking_chunks = 0
                                            speaker_bleed_floor = 0.0
                                            if on_speech_start and not speech_start_notified:
                                                try:
                                                    on_speech_start()
                                                except Exception:
                                                    pass
                                                speech_start_notified = True
                                            try:
                                                from voicefi.tts.base import set_mic_recording

                                                set_mic_recording(
                                                    True,
                                                    state="hearing",
                                                    conv_id=conv_id,
                                                    agent_name=agent_name,
                                                )
                                            except Exception:
                                                pass
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

                        if speech_started:
                            recorded_frames.append(audio_chunk)
                        else:
                            pre_speech_ring.append(audio_chunk)
                            max_preroll = 8 if initial_audio is not None else 6
                            if len(pre_speech_ring) > max_preroll:
                                pre_speech_ring.pop(0)

                        if on_chunk:
                            try:
                                on_chunk(audio_chunk)
                            except Exception:
                                pass

                        vad_result = self.vad.process(audio_chunk)
                        smoothed_energy = vad_result["energy"]
                        speech_confidence = vad_result["confidence"]
                        is_speech = vad_result["is_speech"]
                        active_engine = vad_result["engine"]
                        active_threshold = vad_result["active_threshold"]
                        is_far_field_speech = bool(vad_result.get("is_far_field_speech", False))

                        # Dynamic Near-Field Dropoff Gate ("Coffee Shop Hang" protection):
                        # Once the primary speaker establishes near-field speaking energy (peak_speech_energy >= 0.015),
                        # background voices at neighboring café tables or a TV across the room (>12-13 dB quieter,
                        # i.e. < near_field_dropoff_ratio * peak_speech_energy) must NOT hold the turn open or
                        # false-trigger Thought Hold recovery when the primary speaker pauses.
                        far_field_dropoff_rejected = False
                        if (
                            self.near_field_gate
                            and speech_started
                            and peak_speech_energy >= 0.015
                        ):
                            dropoff_floor = max(
                                self.energy_threshold * 1.25,
                                min(0.025, peak_speech_energy * self.near_field_dropoff_ratio),
                            )
                            if smoothed_energy < dropoff_floor:
                                far_field_dropoff_rejected = True
                                if is_speech:
                                    is_speech = False

                        now = time.time()
                        elapsed = now - start_time

                        if (now - last_touch_time) >= 3.0:
                            last_touch_time = now
                            try:
                                from voicefi.tts.base import touch_mic_recording

                                touch_mic_recording()
                            except Exception:
                                pass

                        if on_listening_tick:
                            try:
                                on_listening_tick(smoothed_energy, speech_confidence, is_speech)
                            except TypeError:
                                on_listening_tick(smoothed_energy)

                        # Dynamic speech detection with neural/energy tracking
                        if is_speech:
                            active_speech_chunks += 1
                            if not speech_started:
                                speech_candidate_chunks += 1
                                if active_engine == "silero":
                                    ambient_babble = getattr(self.vad, "ambient_babble_floor", 0.0)
                                    needs_debounce = self.near_field_gate and (
                                        smoothed_energy < max(0.016, self.vad.running_noise_floor * 2.2)
                                        or ambient_babble > 0.002
                                    )
                                    min_candidates = 2 if needs_debounce else 1
                                else:
                                    min_candidates = 2
                                if speech_candidate_chunks >= min_candidates:
                                    speech_started = True
                                    speech_start_time = now
                                    speech_candidate_chunks = 0
                                    if pre_speech_ring:
                                        recorded_frames.extend(pre_speech_ring)
                                        pre_speech_ring.clear()
                                    print(
                                        f"[VAD] Speech started (engine={active_engine}, conf={speech_confidence:.2f}, energy={smoothed_energy:.4f})"
                                    )
                                    if on_speech_start and not speech_start_notified:
                                        on_speech_start()
                                        speech_start_notified = True
                                    try:
                                        from voicefi.tts.base import set_mic_recording

                                        set_mic_recording(
                                            True,
                                            state="hearing",
                                            conv_id=conv_id,
                                            agent_name=agent_name,
                                        )
                                    except Exception:
                                        pass
                            else:
                                speech_candidate_chunks = 0
                                # If user resumed speaking after pause onset evaluation -> Thought Hold recovered!
                                if pause_evaluated:
                                    thought_holds += 1
                                    pause_evaluated = False
                                    chunks_needed_for_silence = baseline_silence_chunks
                                    print(
                                        f"[VAD] 🧠 Thought Hold #{thought_holds} recovered -> user resumed speaking"
                                    )
                            peak_speech_energy = max(peak_speech_energy * 0.995, smoothed_energy)
                            consecutive_silence_chunks = 0
                        else:
                            speech_candidate_chunks = 0
                            if speech_started:
                                # Attenuate far-field background voices during pauses so STT doesn't transcribe neighboring tables
                                if (
                                    (far_field_dropoff_rejected or is_far_field_speech)
                                    and consecutive_silence_chunks >= 2
                                    and recorded_frames
                                ):
                                    recorded_frames[-1] = audio_chunk * 0.02

                                if active_engine == "silero":
                                    is_silence = (
                                        speech_confidence < 0.35
                                        or far_field_dropoff_rejected
                                        or is_far_field_speech
                                    )
                                else:
                                    silence_cutoff = max(
                                        self.vad.running_noise_floor * 1.25,
                                        min(active_threshold * 0.85, peak_speech_energy * 0.3),
                                    )
                                    if self.near_field_gate and peak_speech_energy >= 0.015:
                                        silence_cutoff = max(
                                            silence_cutoff,
                                            min(0.025, peak_speech_energy * self.near_field_dropoff_ratio),
                                        )
                                    is_silence = (
                                        smoothed_energy <= silence_cutoff
                                        or far_field_dropoff_rejected
                                    )

                                if is_silence:
                                    consecutive_silence_chunks += 1
                                    # Pause-Clock Dynamic End-of-Turn Evaluation (~350ms silence onset)
                                    if (
                                        use_dynamic_turn
                                        and not pause_evaluated
                                        and consecutive_silence_chunks == pause_eval_chunk
                                    ):
                                        eval_audio = (
                                            np.concatenate(recorded_frames, axis=0)
                                            if recorded_frames
                                            else None
                                        )
                                        speech_dur_s = active_speech_chunks * chunk_duration
                                        decision = self.turn_detector.evaluate_turn(
                                            audio=eval_audio,
                                            partial_text=latest_partial_text,
                                            sample_rate=self.sample_rate,
                                            baseline_silence_s=self.silence_duration,
                                            is_dictation=is_dictation,
                                        )
                                        # False-start noise burst check (<200ms sound with 0 words and low prosody)
                                        if self.turn_detector.is_false_start(
                                            speech_duration_s=speech_dur_s,
                                            partial_text=latest_partial_text,
                                            p_voice=decision.p_voice,
                                        ):
                                            false_starts_ignored += 1
                                            speech_started = False
                                            speech_start_notified = False
                                            active_speech_chunks = 0
                                            consecutive_silence_chunks = 0
                                            pause_evaluated = False
                                            recorded_frames.clear()
                                            try:
                                                from voicefi.tts.base import set_mic_recording

                                                set_mic_recording(
                                                    True,
                                                    state="listening",
                                                    conv_id=conv_id,
                                                    agent_name=agent_name,
                                                )
                                            except Exception:
                                                pass
                                            if on_pause_change:
                                                try:
                                                    on_pause_change(False)
                                                except Exception:
                                                    pass
                                            print(
                                                f"[VAD] 💨 False-start noise burst ({speech_dur_s:.2f}s, p_voice={decision.p_voice:.2f}) -> resetting to idle listen"
                                            )
                                            continue

                                        pause_evaluated = True
                                        self.last_turn_decision = decision
                                        chunks_needed_for_silence = max(
                                            pause_eval_chunk + 3,
                                            int(round(decision.wait_seconds / chunk_duration)),
                                        )
                                        dict_tag = " [dictation]" if is_dictation else ""
                                        print(
                                            f"[VAD] 🎯 Turn Eval [{decision.state}]{dict_tag} score={decision.score:.2f} "
                                            f"(p_end={decision.p_end:.2f}, p_voice={decision.p_voice:.2f}, "
                                            f"wait={chunks_needed_for_silence * chunk_duration:.2f}s, {decision.latency_ms:.1f}ms, {decision.engine})"
                                        )
                                else:
                                    consecutive_silence_chunks = 0

                                if consecutive_silence_chunks >= chunks_needed_for_silence:
                                    print(
                                        f"[VAD] Natural silence detected ({consecutive_silence_chunks * chunk_duration:.2f}s, engine={active_engine}) -> finishing recording"
                                    )
                                    break

                        # Stream partial live transcription to HUD / turn evaluator while user speaks
                        if (
                            (on_live_transcript or (use_dynamic_turn and not is_test))
                            and speech_started
                            and (chunk_count - last_stream_chunk_count) >= 6
                        ):
                            last_stream_chunk_count = chunk_count
                            with streaming_lock:
                                if not is_transcribing and recorded_frames:
                                    latest_partial_audio = np.concatenate(recorded_frames, axis=0)

                        # Max speech burst cutoff (dynamically scaled for conversational flow or extended brain dumps)
                        max_burst_limit = (
                            max(180.0, float(self.silence_duration) * 10.0)
                            if is_dictation
                            else max(30.0, float(self.silence_duration) * 3.0)
                        )
                        if speech_started and (now - speech_start_time) >= max_burst_limit:
                            print(
                                f"[VAD] Maximum continuous speech burst ({max_burst_limit:.1f}s) reached -> finishing"
                            )
                            break

                        # Max total record duration safety cutoff
                        dictation_max = 300.0 if is_dictation else self.max_record_seconds
                        if elapsed >= dictation_max:
                            print(
                                f"[VAD] Maximum record duration ({dictation_max}s) reached -> finishing"
                            )
                            break

                        # If no speech at all after timeout seconds, exit gracefully
                        speech_timeout = float(timeout) if timeout is not None else 12.0
                        if not speech_started and elapsed >= speech_timeout:
                            print(
                                f"[VAD] No speech detected within {speech_timeout:.1f}s -> closing mic"
                            )
                            break
            finally:
                self._stream_closed_event.set()

            if cancelled_by_user or self.cancelled:
                return np.zeros(0, dtype=np.float32), None

            manual_stop = trigger_stop.is_set() or self.stop_event.is_set()
            if not recorded_frames and pre_speech_ring and manual_stop:
                recorded_frames.extend(pre_speech_ring)
                pre_speech_ring.clear()

            if not recorded_frames:
                return np.zeros(0, dtype=np.float32), None

            if not speech_started and not (manual_stop and len(recorded_frames) >= 2):
                return np.zeros(0, dtype=np.float32), None

            # Persist privacy-safe Turn Decision Trace to local SQLite analytics
            if self.last_turn_decision is not None:
                try:
                    from voicefi.analytics.store import get_analytics_store

                    d_trace = self.last_turn_decision
                    get_analytics_store().record_turn_decision_trace(
                        turn_state=d_trace.state,
                        score=d_trace.score,
                        p_end=d_trace.p_end,
                        p_voice=d_trace.p_voice,
                        wait_ms=int(round(d_trace.wait_seconds * 1000)),
                        baseline_wait_ms=int(round(float(self.silence_duration) * 1000)),
                        thought_holds=thought_holds,
                        false_starts_ignored=false_starts_ignored,
                        eval_latency_ms=d_trace.latency_ms,
                        engine=d_trace.engine,
                        reason=d_trace.reason,
                        caller_agent=agent_name,
                    )
                except Exception:
                    pass

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

            # Clear cross-process recording flag
            try:
                from voicefi.tts.base import set_mic_recording

                set_mic_recording(False)
            except Exception:
                pass

            if not kwargs.get("keep_wakeword_paused", False):
                # Resume background monitor and wake-word listener
                try:
                    from voicefi.audio.wakeword import WakeWordListener

                    WakeWordListener.resume_all()
                except Exception:
                    pass
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
        conv_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        **kwargs,
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

        # Set cross-process recording flag to yield device from background LaunchAgent
        try:
            from voicefi.tts.base import set_mic_recording

            set_mic_recording(True, state="hearing", conv_id=conv_id, agent_name=agent_name)
        except Exception:
            pass

        # Pause background monitor and wake-word listener to yield device
        try:
            from voicefi.audio.wakeword import WakeWordListener

            WakeWordListener.pause_all()
        except ImportError:
            pass
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

            from voicefi.tts.base import is_tray_hotkey_listener_active

            if not is_tray_hotkey_listener_active():
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
            last_touch_time = 0.0
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
                stt_instance = None
                while not (trigger_stop.is_set() or self.stop_event.is_set()):
                    audio_to_transcribe = None
                    with streaming_lock:
                        if latest_partial_audio is not None and not is_transcribing:
                            audio_to_transcribe = latest_partial_audio
                            latest_partial_audio = None
                            is_transcribing = True

                    if audio_to_transcribe is not None:
                        try:
                            if stt_instance is None:
                                from voicefi.stt.whisper_local import WhisperLocalSTT

                                stt_instance = WhisperLocalSTT()

                            # Keep live preview fast: slice to last 3.5s of audio if longer
                            max_preview_samples = int(self.sample_rate * 3.5)
                            preview_audio = (
                                audio_to_transcribe[-max_preview_samples:]
                                if len(audio_to_transcribe) > max_preview_samples
                                else audio_to_transcribe
                            )

                            txt = stt_instance.transcribe(
                                preview_audio, sample_rate=self.sample_rate
                            )
                            if txt:
                                try:
                                    from voicefi.tts.normalizer import collapse_repetitive_artifacts

                                    txt = collapse_repetitive_artifacts(txt)
                                except Exception:
                                    pass
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

            self._stream_closed_event.clear()
            try:
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

                        now = time.time()
                        if (now - last_touch_time) >= 3.0:
                            last_touch_time = now
                            try:
                                from voicefi.tts.base import touch_mic_recording

                                touch_mic_recording()
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
            finally:
                self._stream_closed_event.set()

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

            # Clear cross-process recording flag
            try:
                from voicefi.tts.base import set_mic_recording

                set_mic_recording(False)
            except Exception:
                pass

            # Resume background monitor and wake-word listener
            try:
                from voicefi.audio.wakeword import WakeWordListener

                WakeWordListener.resume_all()
            except Exception:
                pass
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
