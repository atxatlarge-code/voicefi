"""
Interactive Voice Memo Buffer Recorder with Elegant Timer & Dynamic Extension UX.
Designed for 2-5+ minutes of continuous stream-of-consciousness thought capture.
"""

import os
import sys
import time
import select
import tempfile
import threading
from pathlib import Path
from typing import Optional, Tuple, Callable, List
import numpy as np
import sounddevice as sd
import soundfile as sf

from voicefi.audio.chimes import play_chime
from voicefi.memo.models import MemoRecording, MemoChunk


class MemoBufferRecorder:
    """
    High-capacity audio buffer recorder for stream-of-consciousness developer rambles.
    Features:
    - Elegant countdown timer with live audio energy meter
    - Seamless start, pause/resume, and early finish (Enter key)
    - Dynamic extend flow (+1m, +2m, +5m) when timer lands
    - Pause tolerance: never prematurely cuts off during pacing/thinking pauses
    """

    def __init__(
        self,
        target_duration_seconds: float = 180.0,
        sample_rate: int = 16000,
        energy_threshold: float = 0.003,
        auto_extend_seconds: float = 60.0,
    ):
        self.target_duration_seconds = float(target_duration_seconds)
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.auto_extend_seconds = float(auto_extend_seconds)
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self._extension_lock = threading.Lock()
        self._pending_extension_seconds: float = 0.0

    def extend(self, seconds: float):
        """Dynamically add seconds to active recording target duration."""
        with self._extension_lock:
            self._pending_extension_seconds += float(seconds)

    def finish(self):
        """Signal recording to stop early and save."""
        self.stop_event.set()

    def toggle_pause(self) -> bool:
        """Toggle paused state. Returns True if now paused, False if resumed."""
        if self.pause_event.is_set():
            self.pause_event.clear()
            return False
        else:
            self.pause_event.set()
            return True

    def pause(self):
        """Pause recording."""
        self.pause_event.set()

    def resume(self):
        """Resume recording."""
        self.pause_event.clear()

    def format_time(self, seconds: float) -> str:
        """Format seconds into MM:SS string."""
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{mins:02d}:{secs:02d}"

    def render_meter(self, energy: float, width: int = 10) -> str:
        """Render a clean visual energy level meter."""
        scaled = min(1.0, max(0.0, (energy - 0.001) / 0.04))
        filled = int(scaled * width)
        return "▰" * filled + "▱" * (width - filled)

    def record_memo_session(
        self,
        interactive: bool = True,
        on_tick: Optional[Callable[[float, float, float], None]] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        on_extension_prompt: Optional[Callable[[], None]] = None,
    ) -> Tuple[np.ndarray, Path, float]:
        """
        Record a long-form voice memo session with live countdown and timer landing extend logic.

        Args:
            interactive: Whether to listen for terminal keypresses (Enter to stop, Space to pause).
            on_tick: Optional callback(elapsed_sec, remaining_sec, energy_level).
            on_state_change: Optional callback(state_str) like 'recording', 'paused', 'timer_landed'.

        Returns:
            Tuple of (audio_numpy_array, wav_file_path, actual_duration_seconds)
        """
        self.stop_event.clear()
        self.pause_event.clear()

        chunk_duration = 0.05  # 50ms audio chunks
        chunk_size = int(self.sample_rate * chunk_duration)
        recorded_frames: List[np.ndarray] = []

        total_target_duration = self.target_duration_seconds
        start_time = time.time()
        paused_duration = 0.0
        last_pause_start = 0.0
        smoothed_energy = 0.0
        timer_landed_handled = False

        if interactive and sys.stdin.isatty():
            # Setup background key listener thread
            key_thread = threading.Thread(
                target=self._keyboard_listener,
                args=(lambda: total_target_duration,),
                daemon=True,
            )
            key_thread.start()

        play_chime("start", block=False)

        if on_state_change:
            on_state_change("recording")

        # Visual banner for terminal
        if interactive:
            print("\n" + "─" * 68)
            print(f"🎙️  VOICE MEMO BUFFER  │  Target: {self.format_time(total_target_duration)}  │  Speak freely & pace")
            print("⌨️   [Enter] Finish & Save  │  [Space] Pause  │  [Ctrl+C] Cancel")
            print("─" * 68 + "\n")

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32") as stream:
            while not self.stop_event.is_set():
                now = time.time()

                # Process any remote dynamic extensions
                with self._extension_lock:
                    if self._pending_extension_seconds > 0:
                        total_target_duration += self._pending_extension_seconds
                        self._pending_extension_seconds = 0.0
                        timer_landed_handled = False
                        if on_state_change:
                            on_state_change("recording")

                # Handle pause state
                if self.pause_event.is_set():
                    if last_pause_start == 0.0:
                        last_pause_start = now
                        if on_state_change:
                            on_state_change("paused")
                    time.sleep(0.05)
                    continue
                else:
                    if last_pause_start > 0.0:
                        paused_duration += (now - last_pause_start)
                        last_pause_start = 0.0
                        if on_state_change:
                            on_state_change("recording")

                chunk, _ = stream.read(chunk_size)
                if self.stop_event.is_set():
                    break

                audio_chunk = chunk.flatten()
                recorded_frames.append(audio_chunk)

                # Energy calculations
                energy = float(np.sqrt(np.mean(audio_chunk ** 2)))
                smoothed_energy = 0.3 * smoothed_energy + 0.7 * energy

                elapsed = (now - start_time) - paused_duration
                remaining = max(0.0, total_target_duration - elapsed)

                if on_tick:
                    on_tick(elapsed, remaining, smoothed_energy)

                # Render terminal timer line
                if interactive:
                    meter = self.render_meter(smoothed_energy)
                    pct = min(100, int((elapsed / total_target_duration) * 100)) if total_target_duration > 0 else 100
                    status_text = f"\r⏱️  [{self.format_time(elapsed)} / {self.format_time(total_target_duration)}] ({pct:2d}%)  Level: {meter}  "
                    sys.stdout.write(status_text)
                    sys.stdout.flush()

                # Check if timer has landed (reached 0:00)
                if elapsed >= total_target_duration and not timer_landed_handled:
                    timer_landed_handled = True
                    play_chime("sent", block=False)
                    if on_state_change:
                        on_state_change("timer_landed")
                    if on_extension_prompt:
                        try:
                            on_extension_prompt()
                        except Exception:
                            pass

                    if interactive:
                        sys.stdout.write("\n\n" + "─" * 68 + "\n")
                        sys.stdout.write(f"⏰  TIMER REACHED ({self.format_time(total_target_duration)})!\n")
                        sys.stdout.write("Extend recording?  [1] +1 min   [2] +2 min   [3] +5 min   [Enter] Wrap up\n")
                        sys.stdout.write("─" * 68 + "\n")
                        sys.stdout.flush()

                        # Read quick choice with 5-second graceful window or user selection
                        extended_sec = self._prompt_extension(timeout_sec=8.0)
                        if extended_sec > 0:
                            total_target_duration += extended_sec
                            timer_landed_handled = False
                            sys.stdout.write(f"⏳ Extended by +{int(extended_sec//60)} min! Total target: {self.format_time(total_target_duration)}\n\n")
                            sys.stdout.flush()
                        else:
                            sys.stdout.write("✨ Finalizing voice memo...\n")
                            sys.stdout.flush()
                            self.stop_event.set()
                            break
                    else:
                        # In non-interactive or remote mode, give a 6-second window for remote extension
                        wait_start = time.time()
                        while time.time() - wait_start < 6.0 and not self.stop_event.is_set():
                            with self._extension_lock:
                                if self._pending_extension_seconds > 0:
                                    total_target_duration += self._pending_extension_seconds
                                    self._pending_extension_seconds = 0.0
                                    timer_landed_handled = False
                                    if on_state_change:
                                        on_state_change("recording")
                                    break
                            time.sleep(0.1)
                        if timer_landed_handled:
                            self.stop_event.set()
                            break

        # Finished recording
        actual_duration = max(0.1, (time.time() - start_time) - paused_duration)

        if not recorded_frames:
            audio_array = np.zeros(int(self.sample_rate * 0.1), dtype="float32")
        else:
            audio_array = np.concatenate(recorded_frames)

        # Write to temporary WAV file
        temp_dir = Path(tempfile.gettempdir()) / "voicefi_memos"
        temp_dir.mkdir(parents=True, exist_ok=True)
        wav_path = temp_dir / f"memo_{int(time.time())}.wav"
        sf.write(str(wav_path), audio_array, self.sample_rate)

        play_chime("done", block=False)

        if interactive:
            print(f"\n\n🎉 Recording captured: {self.format_time(actual_duration)} ({len(audio_array)} samples)")

        return audio_array, wav_path, actual_duration

    def _prompt_extension(self, timeout_sec: float = 8.0) -> float:
        """Prompt the user whether to extend when the timer lands with a timeout."""
        if not sys.stdin.isatty():
            return 0.0

        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            start = time.time()
            while time.time() - start < timeout_sec:
                r, _, _ = select.select([sys.stdin], [], [], 0.2)
                if r:
                    ch = sys.stdin.read(1)
                    if ch == '1':
                        return 60.0
                    elif ch == '2':
                        return 120.0
                    elif ch == '3':
                        return 300.0
                    elif ch in ('\n', '\r', ' '):
                        return 0.0
                    elif ch == 'q':
                        return 0.0
        except Exception:
            return 0.0
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        return 0.0

    def _keyboard_listener(self, get_total_duration: Callable[[], float]):
        """Background thread monitoring keyboard for instant Stop or Pause."""
        if not sys.stdin.isatty():
            return

        import termios
        import tty

        fd = sys.stdin.fileno()
        try:
            # We don't hijack entire tty here to avoid blocking stdout,
            # but monitor raw inputs
            while not self.stop_event.is_set():
                r, _, _ = select.select([sys.stdin], [], [], 0.1)
                if r:
                    line = sys.stdin.readline()
                    # Any newline / enter triggers finish
                    self.stop_event.set()
                    break
        except Exception:
            pass
