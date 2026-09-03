"""
Microsoft Edge Neural TTS provider.
High-quality natural sounding AI speech synthesis (free, no API key required).
"""

import asyncio
import tempfile
import subprocess
import threading
import time
import sys
from pathlib import Path
from typing import Optional
from voicefi.tts.base import BaseTTS, speech_turn_lock, DuplicateSpeechSuppressed
from voicefi.audio.meeting_detection import is_user_on_call
from voicefi.tts.normalizer import normalize_tts_text


def normalize_edge_rate(rate: any) -> str:
    """
    Normalize rate input into an EdgeTTS rate string (e.g. '-25%', '+0%', '+10%').
    Handles:
      - Offset percentage int/float: -25 -> '-25%', +10 -> '+10%', 0 -> '+0%'
      - Speed percentage: 75 -> '-25%' (75% speed), 100 -> '+0%', 120 -> '+20%'
      - WPM values: 150 -> '-25%', 200 -> '+0%', 250 -> '+25%'
      - Strings: '-25%', '75%', '-25', '150', '150wpm'
    """
    if rate is None:
        return "+0%"

    if isinstance(rate, str):
        rate_str = rate.strip().lower()
        if rate_str.endswith("wpm"):
            try:
                rate = float(rate_str[:-3].strip())
            except ValueError:
                return "+0%"
        elif (rate_str.startswith("+") or rate_str.startswith("-")) and rate_str.endswith("%"):
            return rate_str
        elif rate_str.endswith("%"):
            try:
                val = float(rate_str[:-1].strip())
                offset = int(round(val - 100))
                return f"{offset:+d}%"
            except ValueError:
                return "+0%"
        else:
            try:
                rate = float(rate_str)
            except ValueError:
                return "+0%"

    if isinstance(rate, (int, float)):
        if rate == 0:
            return "+0%"
        # Direct negative offset e.g. -25 for -25%
        if -90 <= rate < 0:
            return f"{int(round(rate)):+d}%"
        # Direct small positive offset e.g. +5, +10, +25
        if 1 <= rate <= 45:
            return f"{int(round(rate)):+d}%"
        # Percentage of normal speed e.g. 50% - 120% (e.g. 75 for 75% speed)
        if 45 < rate <= 120:
            offset = int(round(rate - 100))
            return f"{offset:+d}%"
        # WPM (121 - 400 WPM, where 200 WPM is baseline 100% -> 150 WPM is 75% speed / -25%)
        if rate > 120:
            offset = int(round(((rate - 200.0) / 200.0) * 100))
            return f"{offset:+d}%"

    return "+0%"


class EdgeTTS(BaseTTS):
    """TTS engine using Edge TTS neural voices with reliable playback and turn queuing."""

    def __init__(
        self,
        voice: str = "en-US-AvaNeural",
        rate: any = 0,
        volume: any = 1.0,
        streaming: bool = True,
        agent_name: str = "VoiceFi",
        persona_name: Optional[str] = None,
        offline_fallback_voice: Optional[str] = "Ava (Premium)",
    ):
        super().__init__()
        self.voice = voice or "en-US-AvaNeural"
        self.rate = rate
        self.rate_str = normalize_edge_rate(rate)
        try:
            self.volume = float(volume) if volume is not None else 1.0
        except (ValueError, TypeError):
            self.volume = 1.0
        self.afplay_vol = str(max(self.volume * 1.6, 1.5))
        self.streaming = streaming
        self.agent_name = agent_name
        self.persona_name = persona_name or (
            "Viv" if ("Ava" in self.voice or "Viv" in self.voice) else self.voice
        )
        self.offline_fallback_voice = offline_fallback_voice or "Ava (Premium)"
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False
        self._audio_queue: Optional[any] = None

    def _safe_fallback(self, clean_text: str, turn_start_time: float = 0.0) -> None:
        try:
            self._fallback_speak_direct(clean_text, turn_start_time=turn_start_time)
        except TypeError:
            self._fallback_speak_direct(clean_text)

    def _fallback_speak_direct(self, clean_text: str, turn_start_time: float = 0.0) -> None:
        """Fallback speak directly using macOS say without re-acquiring lock (already inside speech_turn_lock)."""
        from voicefi.tts.base import (
            is_speech_interrupted,
            set_agent_audio_playing,
            is_agent_speaking,
        )

        if (
            not clean_text
            or not clean_text.strip()
            or self._stop_requested
            or is_speech_interrupted(turn_start_time)
        ):
            return
        try:
            from voicefi.tts.offline import is_voice_installed
            from voicefi.tts.mac_say import normalize_mac_rate

            fb_voice = self.offline_fallback_voice or "Ava (Premium)"
            try:
                has_fb, exact_fb = is_voice_installed(fb_voice)
                target_voice = (
                    exact_fb if (has_fb and exact_fb) else ("Ava" if has_fb else "Samantha")
                )
            except Exception:
                target_voice = "Samantha"

            rate_val = getattr(self, "rate", None)
            rate_arg = ["-r", str(normalize_mac_rate(rate_val))] if rate_val else []
            cmd = ["say", "-v", target_voice] + rate_arg + [clean_text]

            try:
                set_agent_audio_playing(True)
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._current_process = proc
                proc.wait()
            finally:
                set_agent_audio_playing(False)
                self._current_process = None
        except Exception as e:
            print(f"[EdgeTTS] Offline fallback error: {e}", file=sys.stderr)

    async def _generate_audio(self, text: str, output_path: str) -> None:
        import edge_tts

        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate_str)
        await communicate.save(output_path)

    def speak(self, text: str, block: bool = True) -> None:
        """Synthesize and play speech with zero-latency pipelining and offline fallback."""
        if not text or not text.strip():
            return

        if is_user_on_call():
            print("[EdgeTTS] User is on a call. Skipping speech synthesis.")
            return

        clean_text = normalize_tts_text(text)
        self._stop_requested = False
        turn_start_time = time.time()

        def _run():
            try:
                with speech_turn_lock(
                    text=clean_text,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name=getattr(self, "persona_name", getattr(self, "voice", "EdgeTTS")),
                ):
                    from voicefi.tts.base import (
                        set_agent_audio_playing,
                        is_agent_speaking,
                        is_speech_interrupted,
                    )

                    if (
                        self._stop_requested
                        or is_speech_interrupted(turn_start_time)
                        or not is_agent_speaking()
                    ):
                        return

                    import re

                    raw_sentences = [
                        s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_text) if s.strip()
                    ]
                    sentences = [s for s in raw_sentences if any(c.isalnum() for c in s)]
                    if not sentences:
                        sentences = [clean_text] if any(c.isalnum() for c in clean_text) else []

                    if not sentences:
                        return

                    if len(sentences) == 1 or not self.streaming:
                        temp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                        temp_path = temp_mp3.name
                        temp_mp3.close()
                        try:
                            asyncio.run(self._generate_audio(sentences[0], temp_path))
                            if (
                                not self._stop_requested
                                and not is_speech_interrupted(turn_start_time)
                                and is_agent_speaking()
                                and Path(temp_path).is_file()
                                and Path(temp_path).stat().st_size > 0
                            ):
                                set_agent_audio_playing(True)
                                proc = subprocess.Popen(
                                    ["afplay", "-v", self.afplay_vol, temp_path],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                )
                                self._current_process = proc
                                proc.wait()
                                was_interrupted = (
                                    self._stop_requested
                                    or is_speech_interrupted(turn_start_time)
                                    or (proc.returncode in (-9, -15, 137, 143))
                                )
                                if not was_interrupted and proc.returncode != 0:
                                    self._safe_fallback(clean_text, turn_start_time=turn_start_time)
                            elif (
                                not self._stop_requested
                                and not is_speech_interrupted(turn_start_time)
                                and is_agent_speaking()
                            ):
                                self._safe_fallback(clean_text, turn_start_time=turn_start_time)
                        except Exception as e:
                            print(
                                f"[EdgeTTS] Error generating audio ({e}); falling back to offline voice",
                                file=sys.stderr,
                            )
                            if (
                                not self._stop_requested
                                and not is_speech_interrupted(turn_start_time)
                                and is_agent_speaking()
                            ):
                                self._safe_fallback(clean_text, turn_start_time=turn_start_time)
                        finally:
                            set_agent_audio_playing(False)
                            self._current_process = None
                            Path(temp_path).unlink(missing_ok=True)
                        return

                    # Sentence-pipelined streaming: pre-fetch next sentence while playing current
                    import queue

                    audio_queue: queue.Queue = queue.Queue(maxsize=3)
                    self._audio_queue = audio_queue

                    def _fetcher():
                        for s in sentences:
                            if (
                                self._stop_requested
                                or is_speech_interrupted(turn_start_time)
                                or not is_agent_speaking()
                            ):
                                break
                            tf = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                            tp = tf.name
                            tf.close()
                            try:
                                async def _run_with_timeout(txt, out):
                                    try:
                                        await asyncio.wait_for(self._generate_audio(txt, out), timeout=15.0)
                                    except asyncio.TimeoutError:
                                        print(f"[EdgeTTS] Timeout generating chunk for '{txt}'", file=sys.stderr)
                                asyncio.run(_run_with_timeout(s, tp))
                                if Path(tp).is_file() and Path(tp).stat().st_size > 0:
                                    audio_queue.put(tp)
                                else:
                                    Path(tp).unlink(missing_ok=True)
                            except Exception as e:
                                print(
                                    f"[EdgeTTS] Chunk generation notice for '{s}': {e}",
                                    file=sys.stderr,
                                )
                                Path(tp).unlink(missing_ok=True)
                        audio_queue.put(None)

                    fetcher_thread = threading.Thread(target=_fetcher, daemon=True)
                    fetcher_thread.start()

                    played_chunks = 0
                    was_interrupted = False
                    try:
                        while (
                            not self._stop_requested
                            and not is_speech_interrupted(turn_start_time)
                            and is_agent_speaking()
                        ):
                            try:
                                chunk_path = audio_queue.get(timeout=10.0)
                            except Exception:
                                break
                            if chunk_path is None:
                                break
                            if (
                                self._stop_requested
                                or is_speech_interrupted(turn_start_time)
                                or not is_agent_speaking()
                            ):
                                if chunk_path and Path(chunk_path).is_file():
                                    Path(chunk_path).unlink(missing_ok=True)
                                was_interrupted = True
                                break
                            try:
                                if (
                                    not self._stop_requested
                                    and not is_speech_interrupted(turn_start_time)
                                    and is_agent_speaking()
                                    and Path(chunk_path).is_file()
                                    and Path(chunk_path).stat().st_size > 0
                                ):
                                    set_agent_audio_playing(True)
                                    proc = subprocess.Popen(
                                        ["afplay", "-v", self.afplay_vol, chunk_path],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                    )
                                    self._current_process = proc
                                    proc.wait()
                                    if (
                                        self._stop_requested
                                        or is_speech_interrupted(turn_start_time)
                                        or (proc.returncode in (-9, -15, 137, 143))
                                    ):
                                        was_interrupted = True
                                        break
                                    played_chunks += 1
                            finally:
                                set_agent_audio_playing(False)
                                self._current_process = None
                                Path(chunk_path).unlink(missing_ok=True)

                        if not was_interrupted:
                            was_interrupted = self._stop_requested or is_speech_interrupted(
                                turn_start_time
                            )
                        if not was_interrupted and is_agent_speaking():
                            if played_chunks == 0:
                                self._safe_fallback(clean_text, turn_start_time=turn_start_time)
                            elif played_chunks < len(sentences):
                                remaining_text = " ".join(sentences[played_chunks:])
                                self._safe_fallback(remaining_text, turn_start_time=turn_start_time)
                    finally:
                        self._audio_queue = None
                        while not audio_queue.empty():
                            try:
                                item = audio_queue.get_nowait()
                                if item and Path(item).is_file():
                                    Path(item).unlink(missing_ok=True)
                            except Exception:
                                break
            except DuplicateSpeechSuppressed:
                return

        if block:
            _run()
        else:
            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

    async def synthesize_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize text directly to an MP3 file asynchronously."""
        if not text or not text.strip():
            return False
        clean_text = normalize_tts_text(text)
        try:
            await self._generate_audio(clean_text, str(output_path))
            return Path(output_path).is_file() and Path(output_path).stat().st_size > 0
        except Exception as e:
            print(f"[EdgeTTS] Error synthesizing to file: {e}")
            return False

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize speech to an audio file synchronously."""
        try:
            return asyncio.run(self.synthesize_to_file(text, output_path))
        except Exception:
            return False

    def stream_speak(self, text: str, block: bool = True) -> None:
        """Explicit low-latency streaming entrypoint."""
        self.speak(text, block=block)

    def stop(self) -> None:
        """Stop current speech playback."""
        self._stop_requested = True
        if self._current_process and self._current_process.poll() is None:
            try:
                self._current_process.terminate()
            except Exception:
                pass
            self._current_process = None
        if self._audio_queue:
            while not self._audio_queue.empty():
                try:
                    item = self._audio_queue.get_nowait()
                    if item and Path(item).is_file():
                        Path(item).unlink(missing_ok=True)
                except Exception:
                    break
