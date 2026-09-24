"""
Full-Duplex Live Audio Streaming Engine for Gemini Live.

Handles simultaneous 16kHz microphone capture and 24kHz low-latency speaker playback
with instant barge-in flushing, remainder buffer preservation, SIMD RMS calculation,
and hardware-aware acoustic safe mode.
"""

import asyncio
import collections
import logging
import math
import queue
import struct
import threading
import time
from typing import Optional, Callable, Tuple

try:
    import sounddevice as sd
    import numpy as np
except ImportError:
    sd = None
    np = None

from voicefi.audio.device import is_using_builtin_speakers, is_headphone_or_headset_active

logger = logging.getLogger("voicefi.audio.live_stream")

MIC_SAMPLE_RATE = 16000  # Gemini Live native input format
SPEAKER_SAMPLE_RATE = 24000  # Gemini Live native output format
CHUNK_MS = 20  # 20ms low-latency chunking
MIC_BLOCK_SIZE = int(MIC_SAMPLE_RATE * CHUNK_MS / 1000)  # 320 samples = 640 bytes
SPEAKER_BLOCK_SIZE = int(SPEAKER_SAMPLE_RATE * CHUNK_MS / 1000)  # 480 samples = 960 bytes


def calculate_rms(pcm_bytes: bytes) -> float:
    """Calculate normalized Root-Mean-Square (RMS) energy from 16-bit PCM bytes with SIMD acceleration."""
    if not pcm_bytes:
        return 0.0
    if np is not None:
        try:
            arr = np.frombuffer(pcm_bytes, dtype=np.int16)
            if len(arr) == 0:
                return 0.0
            mean_sq = np.mean(arr.astype(np.float32) ** 2)
            return float(np.sqrt(mean_sq)) / 32768.0
        except Exception:
            pass
    count = len(pcm_bytes) // 2
    if count == 0:
        return 0.0
    try:
        shorts = struct.unpack(f"<{count}h", pcm_bytes)
        sum_squares = sum(s * s for s in shorts)
        mean = sum_squares / count
        return math.sqrt(mean) / 32768.0
    except Exception:
        return 0.0


class LiveAudioStream:
    """
    Full-duplex audio I/O stream for real-time speech-to-speech interaction.
    Features 20ms chunking, persistent residual playback preservation,
    and hardware-aware acoustic safe mode.
    """

    def __init__(
        self,
        on_barge_in: Optional[Callable[[], None]] = None,
        barge_in_threshold: float = 0.018,
    ):
        if sd is None:
            raise ImportError(
                "sounddevice is required for LiveAudioStream. Install with: pip install sounddevice"
            )

        self.on_barge_in = on_barge_in
        self.barge_in_threshold = barge_in_threshold

        self._in_stream: Optional[sd.RawInputStream] = None
        self._out_stream: Optional[sd.RawOutputStream] = None

        self._mic_queue: asyncio.Queue = asyncio.Queue(maxsize=150)
        self._speaker_queue: queue.Queue = queue.Queue()

        # Persistent playback residual buffer to prevent audio truncation
        self._out_remainder = bytearray()
        self._out_lock = threading.Lock()

        # Onset pre-roll ring buffer (300ms = 15 chunks @ 20ms)
        self._pre_roll = collections.deque(maxlen=15)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.is_running = False
        self.is_speaking = False
        self._last_barge_in_time = 0.0

        # Hardware sensing: adapt threshold if playing over built-in speakers without headphones
        self.is_builtin = is_using_builtin_speakers()
        self.is_headphones = is_headphone_or_headset_active()
        self.effective_threshold = (
            self.barge_in_threshold * 2.5
            if (self.is_builtin and not self.is_headphones)
            else self.barge_in_threshold
        )
        self._barge_in_candidate_frames = 0
        self._required_barge_frames = 3 if (self.is_builtin and not self.is_headphones) else 1

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start both microphone input and speaker output streams."""
        self._loop = loop or asyncio.get_event_loop()
        self.is_running = True
        with self._out_lock:
            self._out_remainder.clear()

        def in_callback(indata, frames, time_info, status):
            if status and status.input_overflow:
                logger.debug("Mic buffer overflow")
            raw_bytes = bytes(indata)
            energy = calculate_rms(raw_bytes)

            self._pre_roll.append(raw_bytes)

            # Check for user barge-in while model is speaking aloud
            if self.is_speaking:
                if energy > self.effective_threshold:
                    self._barge_in_candidate_frames += 1
                else:
                    self._barge_in_candidate_frames = max(0, self._barge_in_candidate_frames - 1)

                if self._barge_in_candidate_frames >= self._required_barge_frames:
                    now = time.time()
                    if now - self._last_barge_in_time > 0.4:
                        self._last_barge_in_time = now
                        self._barge_in_candidate_frames = 0
                        logger.info(
                            "⚡ User Barge-in detected! (RMS: %.4f > %.4f)",
                            energy,
                            self.effective_threshold,
                        )
                        self.flush_speaker()
                        if self.on_barge_in and self._loop and self._loop.is_running():
                            self._loop.call_soon_threadsafe(self.on_barge_in)

            # Put to mic queue with drop-oldest protection
            if self._loop and self._loop.is_running():
                try:
                    self._mic_queue.put_nowait(raw_bytes)
                except asyncio.QueueFull:
                    try:
                        self._mic_queue.get_nowait()
                        self._mic_queue.put_nowait(raw_bytes)
                    except Exception:
                        pass

        def out_callback(outdata, frames, time_info, status):
            bytes_needed = frames * 2  # 16-bit mono = 2 bytes per frame
            with self._out_lock:
                while len(self._out_remainder) < bytes_needed:
                    try:
                        chunk = self._speaker_queue.get_nowait()
                        self._out_remainder.extend(chunk)
                    except queue.Empty:
                        break

                if len(self._out_remainder) >= bytes_needed:
                    # Deliver exact slice and preserve remainder for next block
                    outdata[:] = bytes(self._out_remainder[:bytes_needed])
                    del self._out_remainder[:bytes_needed]
                    self.is_speaking = True
                else:
                    # Buffer under-run: output available remainder, pad with silence
                    available = len(self._out_remainder)
                    if available > 0:
                        outdata[:available] = bytes(self._out_remainder)
                        self._out_remainder.clear()
                    outdata[available:bytes_needed] = b"\x00" * (bytes_needed - available)

                    # Only mark speaking False after buffer fully drains
                    if self._speaker_queue.empty() and len(self._out_remainder) == 0:
                        self.is_speaking = False

        # Open non-blocking streams
        self._in_stream = sd.RawInputStream(
            samplerate=MIC_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=MIC_BLOCK_SIZE,
            callback=in_callback,
        )
        self._out_stream = sd.RawOutputStream(
            samplerate=SPEAKER_SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=SPEAKER_BLOCK_SIZE,
            callback=out_callback,
        )

        self._in_stream.start()
        self._out_stream.start()
        logger.debug("LiveAudioStream started (20ms chunks: 16kHz in, 24kHz out)")

    async def get_mic_chunk(self) -> bytes:
        """Asynchronously get the next 20ms 16kHz PCM audio chunk from microphone."""
        return await self._mic_queue.get()

    def play_audio_chunk(self, chunk: bytes):
        """Enqueue 24kHz audio chunk for low-latency playback."""
        if chunk:
            self._speaker_queue.put_nowait(chunk)
            self.is_speaking = True

    def flush_speaker(self):
        """Immediately drop all buffered speaker audio for instant barge-in cut-off."""
        with self._out_lock:
            self._out_remainder.clear()
            dropped_chunks = 0
            while not self._speaker_queue.empty():
                try:
                    self._speaker_queue.get_nowait()
                    dropped_chunks += 1
                except queue.Empty:
                    break
            self.is_speaking = False
            self._barge_in_candidate_frames = 0
            logger.debug("Flushed %d speaker audio chunks", dropped_chunks)

    def stop(self):
        """Stop and close all audio streams."""
        self.is_running = False
        self.flush_speaker()
        if self._in_stream:
            try:
                self._in_stream.stop()
                self._in_stream.close()
            except Exception:
                pass
            self._in_stream = None

        if self._out_stream:
            try:
                self._out_stream.stop()
                self._out_stream.close()
            except Exception:
                pass
            self._out_stream = None
        logger.debug("LiveAudioStream stopped")
