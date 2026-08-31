"""
Real-time streaming audio player for VoiceFi.
Streams incoming audio chunks to the audio output device with low latency.
"""

import queue
import threading
import time
from typing import Optional
import numpy as np
import sounddevice as sd


class StreamingAudioPlayer:
    """Streams float32/int16 PCM audio chunks to sounddevice output with minimal buffer latency."""

    def __init__(self, sample_rate: int = 24000, channels: int = 1, blocksize: int = 1024):
        self.sample_rate = sample_rate
        self.channels = channels
        self.blocksize = blocksize
        self.audio_queue: queue.Queue = queue.Queue(maxsize=100)
        self.is_playing = False
        self._stream: Optional[sd.OutputStream] = None
        self._stop_event = threading.Event()
        self._drained_event = threading.Event()
        self._drained_event.set()
        self._outstanding_samples = 0
        self._samples_lock = threading.Lock()
        self._leftover: Optional[np.ndarray] = None

    def start(self):
        """Open the audio output stream."""
        if self.is_playing:
            return
        self.is_playing = True
        self._stop_event.clear()
        self._drained_event.set()

        def callback(outdata, frames, time_info, status):
            if self._stop_event.is_set():
                outdata[:] = 0
                return

            written = 0
            while written < frames:
                # Use leftover from previous chunk if available
                if self._leftover is not None and len(self._leftover) > 0:
                    needed = frames - written
                    if len(self._leftover) <= needed:
                        chunk_to_write = self._leftover
                        self._leftover = None
                    else:
                        chunk_to_write = self._leftover[:needed]
                        self._leftover = self._leftover[needed:]
                    n = len(chunk_to_write)
                    outdata[written : written + n] = chunk_to_write.reshape(-1, self.channels)
                    written += n
                    with self._samples_lock:
                        self._outstanding_samples = max(0, self._outstanding_samples - n)
                    continue

                try:
                    data = self.audio_queue.get_nowait()
                    data = data.reshape(-1, self.channels)
                    needed = frames - written
                    if len(data) <= needed:
                        outdata[written : written + len(data)] = data
                        written += len(data)
                        with self._samples_lock:
                            self._outstanding_samples = max(
                                0, self._outstanding_samples - len(data)
                            )
                    else:
                        outdata[written:frames] = data[:needed]
                        self._leftover = data[needed:]
                        written = frames
                        with self._samples_lock:
                            self._outstanding_samples = max(0, self._outstanding_samples - needed)
                except queue.Empty:
                    outdata[written:] = 0
                    break

            with self._samples_lock:
                if (
                    self._outstanding_samples == 0
                    and self.audio_queue.empty()
                    and self._leftover is None
                ):
                    self._drained_event.set()

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=callback,
            blocksize=self.blocksize,
        )
        self._stream.start()

    def feed(self, audio_chunk: np.ndarray):
        """Feed a numpy float32 chunk into playback buffer."""
        if not self.is_playing:
            self.start()

        chunk_frames = len(audio_chunk.reshape(-1, self.channels))
        with self._samples_lock:
            self._outstanding_samples += chunk_frames
            self._drained_event.clear()

        try:
            self.audio_queue.put(audio_chunk, timeout=0.5)
        except queue.Full:
            with self._samples_lock:
                self._outstanding_samples = max(0, self._outstanding_samples - chunk_frames)

    def wait_until_drained(self, timeout: float = 30.0) -> bool:
        """Wait until all queued audio has completely played through the output stream."""
        if not self.is_playing:
            return True
        success = self._drained_event.wait(timeout=timeout)
        # Tail latency: allow final blocksize buffer to clear physical audio device
        if success:
            tail_sec = self.blocksize / float(self.sample_rate) + 0.05
            time.sleep(tail_sec)
        return success

    def close_after_drain(self, timeout: float = 30.0):
        """Wait for audio to drain cleanly, then stop and close output stream."""
        self.wait_until_drained(timeout=timeout)
        self.stop()

    def stop(self):
        """Immediately stop playback and discard queue (for instant barge-in)."""
        self._stop_event.set()
        self.is_playing = False
        with self._samples_lock:
            self._outstanding_samples = 0
            self._leftover = None
            self._drained_event.set()
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break
