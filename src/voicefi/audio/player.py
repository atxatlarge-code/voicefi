"""
Real-time streaming audio player for VoiceFi.
Streams incoming audio chunks to the audio output device with low latency.
"""

import queue
import threading
from typing import Optional
import numpy as np
import sounddevice as sd


class StreamingAudioPlayer:
    """Streams float32/int16 PCM audio chunks to sounddevice output with minimal buffer latency."""

    def __init__(self, sample_rate: int = 24000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.audio_queue: queue.Queue = queue.Queue(maxsize=100)
        self.is_playing = False
        self._stream: Optional[sd.OutputStream] = None
        self._stop_event = threading.Event()

    def start(self):
        """Open the audio output stream."""
        if self.is_playing:
            return
        self.is_playing = True
        self._stop_event.clear()

        def callback(outdata, frames, time_info, status):
            try:
                data = self.audio_queue.get_nowait()
                if len(data) < len(outdata):
                    outdata[:len(data)] = data.reshape(-1, self.channels)
                    outdata[len(data):] = 0
                else:
                    outdata[:] = data[:len(outdata)].reshape(-1, self.channels)
            except queue.Empty:
                outdata[:] = 0

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=callback,
            blocksize=1024,
        )
        self._stream.start()

    def feed(self, audio_chunk: np.ndarray):
        """Feed a numpy float32 chunk into playback buffer."""
        if not self.is_playing:
            self.start()
        try:
            self.audio_queue.put(audio_chunk, timeout=0.5)
        except queue.Full:
            pass

    def stop(self):
        """Stop playback and drain queue."""
        self._stop_event.set()
        self.is_playing = False
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
