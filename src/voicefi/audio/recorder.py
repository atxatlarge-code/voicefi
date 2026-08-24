"""
Microphone audio capture with Adaptive Voice Activity Detection (VAD).
Uses smoothed energy tracking and robust 0.8s silence cutoff to prevent background noise hangs.
Supports instant manual completion via Enter key / stop_event.
"""

import time
import tempfile
import threading
from pathlib import Path
from typing import Optional, Tuple, Callable, Any
import numpy as np
import sounddevice as sd
import soundfile as sf


from voicefi.tts.base import is_agent_speaking, is_agent_audio_playing
from voicefi.audio.device import is_using_builtin_speakers, is_headphone_or_headset_active


def resolve_barge_in_mode(barge_in_setting: Any) -> Tuple[bool, bool]:
    """
    Resolve effective barge-in enabled status and whether acoustic safe mode is active.
    Returns: (is_barge_in_active, is_safe_mode)

    When barge_in is 'auto' (the default):
      - Built-in laptop speakers: Barge-in is DISABLED so agent speech output is never cut off by mic bleed.
      - Headphones / AirPods: Barge-in is ENABLED with hands-free responsiveness.
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
    """Records audio from default input device with robust, snappy energy VAD and Active Barge-In."""

    def __init__(
        self,
        sample_rate: int = 16000,
        energy_threshold: float = 0.004,
        silence_duration: float = 2.0,
        max_record_seconds: float = 45.0,
        barge_in: Any = "auto",
        barge_in_sensitivity: float = 1.0,
    ):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.max_record_seconds = max_record_seconds
        self.barge_in = barge_in
        self.barge_in_sensitivity = max(0.1, barge_in_sensitivity)
        self.stop_event = threading.Event()

    def stop(self):
        """Immediately signal recorder to stop and process captured audio."""
        self.stop_event.set()

    def record_speech_auto(
        self,
        on_speech_start: Optional[Callable[[], None]] = None,
        on_listening_tick: Optional[Callable[[float], None]] = None,
        on_pause_change: Optional[Callable[[bool], None]] = None,
        on_barge_in: Optional[Callable[[], None]] = None,
        on_live_transcript: Optional[Callable[[str], None]] = None,
        on_chunk: Optional[Callable[[np.ndarray], None]] = None,
        stop_event: Optional[threading.Event] = None,
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

        kb_listener = None
        try:
            from pynput import keyboard
            def _on_key_press(k):
                nonlocal cancelled_by_user
                vk = getattr(k, 'vk', None)
                if k == keyboard.Key.esc or vk == 53:
                    cancelled_by_user = True
                    from voicefi.tts.base import stop_all_speech
                    stop_all_speech()
                    self.stop_event.set()
                elif k in (keyboard.Key.enter, keyboard.Key.space) or vk in (36, 76, 49):
                    self.stop_event.set()

            kb_listener = keyboard.Listener(on_press=_on_key_press)
            kb_listener.daemon = True
            kb_listener.start()
        except Exception:
            kb_listener = None

        chunk_duration = 0.05  # 50ms chunks for rapid response
        chunk_size = int(self.sample_rate * chunk_duration)

        recorded_frames = []
        speech_started = False
        speech_start_notified = False
        speech_start_time = 0.0
        consecutive_silence_chunks = 0
        # 0.8s silence pause needed to finish (~16 chunks)
        chunks_needed_for_silence = max(12, int(min(1.0, max(0.6, self.silence_duration)) / chunk_duration))
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

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
            chunk_count = 0
            while True:
                # Check for manual instant stop (e.g. Enter, Space, Esc, or stop_event)
                if trigger_stop.is_set() or self.stop_event.is_set():
                    break

                chunk, overflowed = stream.read(chunk_size)
                if trigger_stop.is_set() or self.stop_event.is_set():
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
                        # Active Barge-In: monitor energy during physical agent playback
                        energy = float(np.sqrt(np.mean(audio_chunk ** 2)))
                        smoothed_energy = 0.35 * smoothed_energy + 0.65 * energy

                        # Dynamic acoustic threshold & grace window
                        if is_safe_mode:
                            # Built-in laptop speakers: adapt against speaker bleed
                            grace_chunks = max(10, int(1.2 / chunk_duration))  # 1.2s settling window from audio onset
                            in_grace_period = agent_speaking_chunks < grace_chunks
                            if in_grace_period:
                                # During grace period, calibrate speaker bleed floor to steady speaker output
                                speaker_bleed_floor = 0.80 * speaker_bleed_floor + 0.20 * energy
                            else:
                                # Post-grace: only track baseline for low/moderate levels so human speech doesn't inflate floor
                                if energy < 0.070:
                                    speaker_bleed_floor = 0.95 * speaker_bleed_floor + 0.05 * energy

                            barge_in_threshold = max(
                                0.070,
                                speaker_bleed_floor * 1.65 + 0.020,
                            ) / self.barge_in_sensitivity
                            required_chunks = 5  # ~250ms sustained speech
                        else:
                            # Headphones / AirPods: responsive threshold
                            grace_chunks = 3  # 150ms minimal settling
                            barge_in_threshold = max(
                                self.energy_threshold * 2.2,
                                (running_noise_floor * 2.2 + 0.012),
                            ) / self.barge_in_sensitivity
                            required_chunks = 3
                            in_grace_period = agent_speaking_chunks < grace_chunks

                        agent_speaking_pre_roll.append(audio_chunk)
                        if len(agent_speaking_pre_roll) > 3:
                            agent_speaking_pre_roll.pop(0)

                        if in_grace_period:
                            barge_in_candidate_chunks = 0
                        elif smoothed_energy > barge_in_threshold:
                            barge_in_candidate_chunks += 1
                            if barge_in_candidate_chunks >= required_chunks:
                                # User spoke over agent speech -> BARGE IN!
                                mode_desc = "acoustic safe-mode" if is_safe_mode else "headphones"
                                print(f"[VAD] ⚡ Barge-In detected ({mode_desc}, energy={smoothed_energy:.4f}, thresh={barge_in_threshold:.4f}) -> stopping agent speech")
                                from voicefi.tts.base import stop_all_speech
                                stop_all_speech()
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
                            barge_in_candidate_chunks = max(0, barge_in_candidate_chunks - 1)

                        if not is_paused:
                            is_paused = True
                            mode_info = "acoustic safe-mode" if is_safe_mode else "active listening"
                            print(f"[VAD] Agent is speaking aloud -> barge-in monitoring ({mode_info})...")
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
                            print("[VAD] Agent is speaking aloud -> pausing mic capture & purging audio bleed")
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
                    print("[VAD] Agent finished speaking -> cooling down & resuming mic capture")
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

                # Compute RMS energy
                energy = float(np.sqrt(np.mean(audio_chunk ** 2)))
                smoothed_energy = 0.4 * smoothed_energy + 0.6 * energy
                chunk_count += 1

                # Track running background noise floor
                if not speech_started:
                    running_noise_floor = 0.88 * running_noise_floor + 0.12 * min(0.015, energy)

                # Dynamic speech threshold based on room background noise
                active_threshold = max(self.energy_threshold, running_noise_floor * 1.5 + 0.0035)

                now = time.time()
                elapsed = now - start_time

                if on_listening_tick:
                    on_listening_tick(smoothed_energy)

                # Dynamic speech detection with peak tracking
                if smoothed_energy > active_threshold:
                    if not speech_started:
                        speech_candidate_chunks = locals().get("speech_candidate_chunks", 0) + 1
                        if speech_candidate_chunks >= 2:
                            speech_started = True
                            speech_start_time = now
                            speech_candidate_chunks = 0
                            print(f"[VAD] Speech started (energy={smoothed_energy:.4f}, noise_floor={running_noise_floor:.4f})")
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
                        # Dynamic silence cutoff above ambient noise floor
                        silence_cutoff = max(running_noise_floor * 1.25, min(active_threshold * 0.85, peak_speech_energy * 0.3))
                        if smoothed_energy <= silence_cutoff:
                            consecutive_silence_chunks += 1
                        else:
                            consecutive_silence_chunks = max(0, consecutive_silence_chunks - 2)

                        if consecutive_silence_chunks >= chunks_needed_for_silence:
                            print(f"[VAD] Natural spotting point silence detected ({consecutive_silence_chunks * chunk_duration:.2f}s, configurable) -> finishing recording")
                            break

                # Max speech burst cutoff (e.g. continuous sentence capped at 12s)
                if speech_started and (now - speech_start_time) >= 12.0:
                    print("[VAD] Maximum continuous speech burst (12s) reached -> finishing")
                    break

                # Max total record duration safety cutoff
                if elapsed >= self.max_record_seconds:
                    print(f"[VAD] Maximum record duration ({self.max_record_seconds}s) reached -> finishing")
                    break

                # If no speech at all after 5.0 seconds, exit gracefully
                if not speech_started and elapsed >= 5.0:
                    print("[VAD] No speech detected within 5.0s -> closing mic")
                    break

        if kb_listener is not None:
            try:
                kb_listener.stop()
            except Exception:
                pass

        if cancelled_by_user:
            recorded_frames.clear()

        if recorded_frames:
            full_audio = np.concatenate(recorded_frames, axis=0)
        else:
            full_audio = np.zeros(self.sample_rate, dtype=np.float32)

        # Save to temporary WAV file
        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_path = Path(temp_wav.name)
        temp_wav.close()

        sf.write(str(temp_path), full_audio, self.sample_rate)
        return full_audio, temp_path

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

        kb_listener = None
        try:
            from pynput import keyboard
            def _on_ptt_key(k):
                nonlocal cancelled_by_user
                vk = getattr(k, 'vk', None)
                if k == keyboard.Key.esc or vk == 53:
                    cancelled_by_user = True
                    from voicefi.tts.base import stop_all_speech
                    stop_all_speech()
                    self.stop_event.set()

            kb_listener = keyboard.Listener(on_press=_on_ptt_key)
            kb_listener.daemon = True
            kb_listener.start()
        except Exception:
            kb_listener = None

        chunk_duration = 0.05  # 50ms chunks
        chunk_size = int(self.sample_rate * chunk_duration)
        extra_chunks_after_stop = max(1, int((ptt_release_delay_ms / 1000.0) / chunk_duration))

        recorded_frames = []
        smoothed_energy = 0.0
        start_time = time.time()
        stop_signaled_count = 0

        is_paused = False
        cooldown_remaining_chunks = 0

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
            while True:
                chunk, overflowed = stream.read(chunk_size)
                audio_chunk = chunk.flatten()

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
                                recorded_frames = recorded_frames[:-5] if len(recorded_frames) > 5 else []
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

                # Compute RMS energy for UI level meter
                energy = float(np.sqrt(np.mean(audio_chunk ** 2)))
                smoothed_energy = 0.6 * smoothed_energy + 0.4 * energy

                if on_listening_tick:
                    on_listening_tick(smoothed_energy)

                if trigger_stop.is_set():
                    stop_signaled_count += 1
                    if stop_signaled_count >= extra_chunks_after_stop:
                        break

                # Max duration safety cutoff
                if (time.time() - start_time) >= self.max_record_seconds:
                    break

        if kb_listener is not None:
            try:
                kb_listener.stop()
            except Exception:
                pass

        if cancelled_by_user:
            recorded_frames.clear()

        if recorded_frames:
            full_audio = np.concatenate(recorded_frames, axis=0)
        else:
            full_audio = np.zeros(self.sample_rate, dtype=np.float32)

        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        temp_path = Path(temp_wav.name)
        temp_wav.close()

        sf.write(str(temp_path), full_audio, self.sample_rate)
        return full_audio, temp_path

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
