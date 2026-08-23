"""
Microphone audio capture with Adaptive Voice Activity Detection (VAD).
Uses smoothed energy tracking and robust 0.8s silence cutoff to prevent background noise hangs.
Supports instant manual completion via Enter key / stop_event.
"""

import time
import tempfile
import threading
from pathlib import Path
from typing import Optional, Tuple, Callable
import numpy as np
import sounddevice as sd
import soundfile as sf


from voicefi.tts.base import is_agent_speaking


class AudioRecorder:
    """Records audio from default input device with robust, snappy energy VAD and Active Barge-In."""

    def __init__(
        self,
        sample_rate: int = 16000,
        energy_threshold: float = 0.004,
        silence_duration: float = 2.0,
        max_record_seconds: float = 45.0,
        barge_in: bool = True,
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
        stop_event: Optional[threading.Event] = None,
    ) -> Tuple[np.ndarray, Path]:
        """
        Record audio from mic until speech is detected and followed by natural silence.
        When barge_in is True: actively monitors microphone during agent speech playback.
        If user speaks, immediately kills agent speech output and captures user prompt seamlessly.
        When barge_in is False: pauses and discards incoming audio when an AI agent is speaking.
        Can be terminated immediately via Enter key / stop_event.
        """
        self.stop_event.clear()
        trigger_stop = stop_event or self.stop_event

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
                    if self.barge_in:
                        # Active Barge-In: monitor energy during agent playback
                        energy = float(np.sqrt(np.mean(audio_chunk ** 2)))
                        smoothed_energy = 0.35 * smoothed_energy + 0.65 * energy

                        # Dynamic acoustic threshold requiring definitive vocal burst over speaker bleed
                        barge_in_threshold = max(
                            self.energy_threshold * 2.8,
                            (running_noise_floor * 2.5 + 0.015),
                        ) / self.barge_in_sensitivity

                        agent_speaking_pre_roll.append(audio_chunk)
                        if len(agent_speaking_pre_roll) > 3:
                            agent_speaking_pre_roll.pop(0)

                        if smoothed_energy > barge_in_threshold:
                            barge_in_candidate_chunks += 1
                            # Require at least 4 chunks (~200ms) of sustained loud speech to barge in
                            if barge_in_candidate_chunks >= 4:
                                # User spoke over agent speech -> BARGE IN!
                                print(f"[VAD] 🛑 Barge-In detected (energy={smoothed_energy:.4f}, thresh={barge_in_threshold:.4f}) -> killing agent speech")
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
                                if on_speech_start and not speech_start_notified:
                                    on_speech_start()
                                    speech_start_notified = True
                                continue
                        else:
                            barge_in_candidate_chunks = max(0, barge_in_candidate_chunks - 1)

                        if not is_paused:
                            is_paused = True
                            print("[VAD] ⏸️ Agent is speaking aloud -> active barge-in monitoring listening...")
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
                            print("[VAD] ⏸️ Agent is speaking aloud -> pausing mic capture & purging audio bleed")
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
                    agent_speaking_pre_roll.clear()
                    recorded_frames.clear()
                    print("[VAD] ▶️ Agent finished speaking -> cooling down & resuming mic capture")
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
                        speech_started = True
                        speech_start_time = now
                        print(f"[VAD] 🎙️ Speech started (energy={smoothed_energy:.4f}, noise_floor={running_noise_floor:.4f})")
                        if on_speech_start and not speech_start_notified:
                            on_speech_start()
                            speech_start_notified = True
                    peak_speech_energy = max(peak_speech_energy, smoothed_energy)
                    consecutive_silence_chunks = max(0, consecutive_silence_chunks - 3)
                else:
                    if speech_started:
                        # Dynamic silence cutoff above ambient noise floor
                        silence_cutoff = max(running_noise_floor * 1.25, min(active_threshold * 0.85, peak_speech_energy * 0.3))
                        if smoothed_energy <= silence_cutoff:
                            consecutive_silence_chunks += 1
                        else:
                            consecutive_silence_chunks = max(0, consecutive_silence_chunks - 2)

                        if consecutive_silence_chunks >= chunks_needed_for_silence:
                            print(f"[VAD] 🛑 Natural silence pause detected ({consecutive_silence_chunks * chunk_duration:.2f}s) -> finishing recording")
                            break

                # Max speech burst cutoff (e.g. continuous sentence capped at 12s)
                if speech_started and (now - speech_start_time) >= 12.0:
                    print("[VAD] ⏱️ Maximum continuous speech burst (12s) reached -> finishing")
                    break

                # Max total record duration safety cutoff
                if elapsed >= self.max_record_seconds:
                    print(f"[VAD] ⏱️ Maximum record duration ({self.max_record_seconds}s) reached -> finishing")
                    break

                # If no speech at all after 5.0 seconds, exit gracefully
                if not speech_started and elapsed >= 5.0:
                    print("[VAD] ⏱️ No speech detected within 5.0s -> closing mic")
                    break

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
                    if self.barge_in:
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
