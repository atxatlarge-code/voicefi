"""
Microphone audio capture with Voice Activity Detection (VAD).
Detects speech start and automatic silence cutoff for hands-free interactions.
"""

import time
import tempfile
import threading
from pathlib import Path
from typing import Optional, Tuple, Callable
import numpy as np
import sounddevice as sd
import soundfile as sf


class AudioRecorder:
    """Records audio from default input device with energy-based VAD."""

    def __init__(
        self,
        sample_rate: int = 16000,
        energy_threshold: float = 0.015,
        silence_duration: float = 1.5,
        max_record_seconds: float = 45.0,
    ):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.silence_duration = silence_duration
        self.max_record_seconds = max_record_seconds

    def record_speech_auto(
        self,
        on_speech_start: Optional[Callable[[], None]] = None,
        on_listening_tick: Optional[Callable[[float], None]] = None,
    ) -> Tuple[np.ndarray, Path]:
        """
        Record audio from mic until speech is detected and followed by silence.
        
        Returns:
            Tuple of (audio_numpy_array, path_to_temporary_wav_file)
        """
        chunk_duration = 0.1  # 100ms chunks
        chunk_size = int(self.sample_rate * chunk_duration)
        
        recorded_frames = []
        speech_started = False
        silence_start_time: Optional[float] = None
        start_time = time.time()
        speech_start_notified = False

        # Use an event to allow graceful abort if needed
        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
            while True:
                chunk, overflowed = stream.read(chunk_size)
                audio_chunk = chunk.flatten()
                recorded_frames.append(audio_chunk)

                # Compute RMS energy
                energy = float(np.sqrt(np.mean(audio_chunk ** 2)))

                now = time.time()
                elapsed = now - start_time

                if on_listening_tick:
                    on_listening_tick(energy)

                # Check speech activation
                if energy > self.energy_threshold:
                    if not speech_started:
                        speech_started = True
                        if on_speech_start and not speech_start_notified:
                            on_speech_start()
                            speech_start_notified = True
                    silence_start_time = None
                else:
                    if speech_started:
                        if silence_start_time is None:
                            silence_start_time = now
                        elif (now - silence_start_time) >= self.silence_duration:
                            # Silence timeout after speech -> complete
                            break

                # Max duration safety cutoff
                if elapsed >= self.max_record_seconds:
                    break

                # If no speech at all after 25 seconds, exit to avoid hanging forever
                if not speech_started and elapsed >= 25.0:
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
