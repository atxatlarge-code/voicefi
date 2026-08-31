"""
Native macOS Apple Hardware VoiceProcessingIO (VPIO) Audio Capture Stream.

Leverages Apple CoreAudio / AVAudioEngine AUVoiceProcessing hardware DSP:
- Real-time Acoustic Echo Cancellation (AEC): cancels speaker audio output from microphone buffers in hardware.
- Automatic Gain Control (AGC) & speech enhancement.
- Dynamic decimation/resampling to target 16kHz float32 audio.
"""

import sys
import time
import ctypes
import queue
import threading
import warnings
from typing import Optional, Tuple
import numpy as np

try:
    import objc

    if hasattr(objc, "ObjCPointerWarning"):
        warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)
except Exception:
    pass

_VPIO_INITIALIZED = False
_VPIO_SUPPORTED = False
AVAudioEngine = None
AVAudioNode = None
AVAudioPCMBuffer = None


def is_vpio_supported() -> bool:
    """Check if macOS Apple Hardware VoiceProcessingIO is available on this system."""
    global _VPIO_INITIALIZED, _VPIO_SUPPORTED, AVAudioEngine, AVAudioNode, AVAudioPCMBuffer
    if _VPIO_INITIALIZED:
        return _VPIO_SUPPORTED

    _VPIO_INITIALIZED = True
    if sys.platform != "darwin":
        _VPIO_SUPPORTED = False
        return False

    try:
        import objc

        objc.loadBundle(
            "AVFoundation",
            globals(),
            bundle_path="/System/Library/Frameworks/AVFoundation.framework",
        )
        objc.registerMetaDataForSelector(
            b"AVAudioNode",
            b"installTapOnBus:bufferSize:format:block:",
            {
                "arguments": {
                    5: {
                        "callable": {
                            "retval": {"type": b"v"},
                            "arguments": {
                                0: {"type": b"^v"},
                                1: {"type": b"@"},
                                2: {"type": b"@"},
                            },
                        }
                    }
                }
            },
        )
        objc.registerMetaDataForSelector(
            b"AVAudioPCMBuffer",
            b"floatChannelData",
            {
                "retval": {"type": b"^^f"},
            },
        )

        AVAudioEngine = objc.lookUpClass("AVAudioEngine")
        AVAudioNode = objc.lookUpClass("AVAudioNode")
        AVAudioPCMBuffer = objc.lookUpClass("AVAudioPCMBuffer")

        # Verify instance and method availability
        test_engine = AVAudioEngine.alloc().init()
        input_node = test_engine.inputNode()
        if hasattr(input_node, "setVoiceProcessingEnabled_error_"):
            _VPIO_SUPPORTED = True
        else:
            _VPIO_SUPPORTED = False
    except Exception:
        _VPIO_SUPPORTED = False

    return _VPIO_SUPPORTED


class NativeVoiceProcessingStream:
    """
    Real-time macOS Audio Stream utilizing Apple CoreAudio AUVoiceProcessing.
    Provides hardware-level Acoustic Echo Cancellation and voice isolation.
    """

    def __init__(self, target_sample_rate: int = 16000, buffer_size: int = 1024):
        self.target_sample_rate = target_sample_rate
        self.buffer_size = buffer_size
        self._engine = None
        self._input_node = None
        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._is_running = False
        self._native_sample_rate = 48000
        self._buffer_remainder = np.array([], dtype=np.float32)
        self._lock = threading.Lock()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def start(self):
        """Start the hardware echo-cancelled audio stream."""
        if not is_vpio_supported():
            raise RuntimeError("Apple VoiceProcessingIO is not supported on this platform.")

        with self._lock:
            if self._is_running:
                return

            self._engine = AVAudioEngine.alloc().init()
            self._input_node = self._engine.inputNode()

            # Enable Hardware Voice Processing (Echo Cancellation + AGC)
            try:
                self._input_node.setVoiceProcessingEnabled_error_(True, None)
                if hasattr(self._input_node, "setVoiceProcessingAGCEnabled_"):
                    self._input_node.setVoiceProcessingAGCEnabled_(True)
                if hasattr(self._input_node, "setVoiceProcessingOtherAudioDuckingConfiguration_"):
                    # Disable ducking of system/TTS audio playback
                    self._input_node.setVoiceProcessingOtherAudioDuckingConfiguration_((False, 0))
            except Exception as e:
                print(f"[VPIO] Warning setting VoiceProcessing options: {e}")

            format = self._input_node.inputFormatForBus_(0)
            self._native_sample_rate = int(format.sampleRate()) if format else 48000
            self._queue = queue.Queue()
            self._buffer_remainder = np.array([], dtype=np.float32)

            native_sr = self._native_sample_rate
            target_sr = self.target_sample_rate
            q = self._queue

            def _tap_callback(buffer, when):
                try:
                    length = buffer.frameLength()
                    if length <= 0:
                        return
                    fcd = buffer.floatChannelData()
                    ptr_val = fcd.pointerAsInteger
                    c_ptr = ctypes.cast(ptr_val, ctypes.POINTER(ctypes.POINTER(ctypes.c_float)))
                    ptr0 = c_ptr[0]
                    raw_arr = np.ctypeslib.as_array(ptr0, shape=(length,)).copy()

                    # Resample / decimate to target sample rate
                    if native_sr == target_sr:
                        processed = raw_arr
                    elif native_sr == 48000 and target_sr == 16000:
                        processed = raw_arr[::3].copy()
                    elif native_sr == 44100 and target_sr == 16000:
                        import scipy.signal

                        processed = scipy.signal.resample_poly(raw_arr, 160, 441).astype(np.float32)
                    else:
                        import scipy.signal

                        processed = scipy.signal.resample_poly(
                            raw_arr, target_sr, native_sr
                        ).astype(np.float32)

                    q.put(processed)
                except Exception:
                    pass

            self._input_node.installTapOnBus_bufferSize_format_block_(
                0,
                self.buffer_size,
                format,
                _tap_callback,
            )

            started = self._engine.startAndReturnError_(None)
            if not started:
                raise RuntimeError("Failed to start AVAudioEngine VoiceProcessingIO stream.")

            self._is_running = True

    def read(self, num_frames: int, timeout: float = 0.5) -> Tuple[np.ndarray, bool]:
        """
        Read exactly num_frames from the stream.
        Returns (audio_chunk, overflowed).
        """
        with self._lock:
            if not self._is_running:
                return np.zeros(num_frames, dtype=np.float32), False

        collected = [self._buffer_remainder] if len(self._buffer_remainder) > 0 else []
        current_len = len(self._buffer_remainder)
        self._buffer_remainder = np.array([], dtype=np.float32)

        deadline = time.time() + timeout
        while current_len < num_frames:
            rem_time = max(0.01, deadline - time.time())
            try:
                chunk = self._queue.get(timeout=rem_time)
                collected.append(chunk)
                current_len += len(chunk)
            except queue.Empty:
                break

        if not collected:
            return np.zeros(num_frames, dtype=np.float32), False

        merged = np.concatenate(collected)
        if len(merged) >= num_frames:
            result = merged[:num_frames]
            self._buffer_remainder = merged[num_frames:]
            return result, False
        else:
            # Pad with zeroes if needed
            pad_len = num_frames - len(merged)
            result = np.pad(merged, (0, pad_len), mode="constant")
            return result, False

    def stop(self):
        """Stop and tear down the audio engine and tap."""
        with self._lock:
            if not self._is_running:
                return
            self._is_running = False

            if self._input_node:
                try:
                    self._input_node.removeTapOnBus_(0)
                except Exception:
                    pass

            if self._engine:
                try:
                    self._engine.stop()
                except Exception:
                    pass

            self._engine = None
            self._input_node = None
            self._buffer_remainder = np.array([], dtype=np.float32)
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
