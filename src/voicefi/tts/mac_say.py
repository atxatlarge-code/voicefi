"""
Native macOS 'say' TTS provider.
Zero-setup, lightning fast, offline, and supports all system installed voices.
"""

import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, List
from voicefi.tts.base import BaseTTS, speech_turn_lock, DuplicateSpeechSuppressed
from voicefi.audio.meeting_detection import is_user_on_call
from voicefi.tts.normalizer import normalize_tts_text


def normalize_mac_rate(rate: any) -> int:
    """
    Normalize rate into words-per-minute (WPM) for macOS `say -r <rate>`.
    Baseline normal speed is 200 WPM.
    Supports:
      - WPM integers: 150, 200, 250
      - Percentage speeds: 75 -> 150 WPM, 100 -> 200 WPM
      - Percentage offsets: -25 -> 150 WPM, +25 -> 250 WPM
      - Strings: '75%', '-25%', '150', '150wpm'
    """
    if rate is None:
        return 200

    if isinstance(rate, str):
        rate_str = rate.strip().lower()
        if rate_str.endswith("wpm"):
            try:
                rate = float(rate_str[:-3].strip())
            except ValueError:
                return 200
        elif (rate_str.startswith("+") or rate_str.startswith("-")) and rate_str.endswith("%"):
            try:
                offset_pct = float(rate_str[:-1])
                return max(min(int(round(200 * (1.0 + offset_pct / 100.0))), 650), 60)
            except ValueError:
                return 200
        elif rate_str.endswith("%"):
            try:
                pct = float(rate_str[:-1])
                return max(min(int(round(200 * (pct / 100.0))), 650), 60)
            except ValueError:
                return 200
        else:
            try:
                rate = float(rate_str)
            except ValueError:
                return 200

    if isinstance(rate, (int, float)):
        if rate == 0:
            return 200
        if rate < -90:
            return 60
        if -90 <= rate < 0:
            return max(min(int(round(200 * (1.0 + rate / 100.0))), 650), 60)
        if 1 <= rate <= 45:
            return max(min(int(round(200 * (1.0 + rate / 100.0))), 650), 60)
        if 45 < rate <= 120:
            return max(min(int(round(200 * (rate / 100.0))), 650), 60)
        if rate > 120:
            return max(min(int(round(rate)), 650), 60)

    return 200


import tempfile


class MacSayTTS(BaseTTS):
    """TTS engine powered by macOS native `say` command with amplified CoreAudio playback."""

    def __init__(self, voice: str = "Samantha", rate: any = 200, volume: float = 1.0):
        super().__init__()
        self.voice = voice
        self.rate = normalize_mac_rate(rate)
        self.volume = float(volume) if volume is not None else 1.0
        self.afplay_vol = str(max(self.volume * 1.6, 1.5))
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    def stop(self) -> None:
        """Interrupt any ongoing speech playback."""
        self._stop_requested = True
        proc = self._current_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
            self._current_process = None

    def speak(self, text: str, block: bool = True) -> None:
        """Speak text aloud using macOS say synthesized to AIFF and played via amplified afplay."""
        if not text or not text.strip():
            return

        if is_user_on_call():
            print("[MacSayTTS] User is on a call. Skipping speech synthesis.")
            return

        clean_text = normalize_tts_text(text)
        self._stop_requested = False
        turn_start_time = time.time()

        def _run():
            try:
                with speech_turn_lock(
                    text=clean_text,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name=getattr(self, "persona_name", getattr(self, "voice", "Samantha")),
                ):
                    from voicefi.tts.base import is_speech_interrupted, set_agent_audio_playing

                    if self._stop_requested or is_speech_interrupted(turn_start_time):
                        return

                    temp_aiff = tempfile.NamedTemporaryFile(suffix=".aiff", delete=False)
                    temp_path = Path(temp_aiff.name)
                    temp_aiff.close()

                    try:
                        # 1. Synthesize to temporary AIFF file
                        cmd_synth = [
                            "say",
                            "-v",
                            self.voice,
                            "-r",
                            str(self.rate),
                            "-o",
                            str(temp_path),
                            "--",
                            clean_text,
                        ]
                        res = subprocess.run(
                            cmd_synth, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                        if res.returncode != 0:
                            # Fallback without voice flag
                            subprocess.run(
                                ["say", "-r", str(self.rate), "-o", str(temp_path), "--", clean_text],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )

                        if (
                            not self._stop_requested
                            and not is_speech_interrupted(turn_start_time)
                            and temp_path.is_file()
                            and temp_path.stat().st_size > 0
                        ):
                            # 2. Play cleanly and loudly via afplay
                            set_agent_audio_playing(True)
                            proc = subprocess.Popen(
                                ["afplay", "-v", self.afplay_vol, str(temp_path)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            self._current_process = proc
                            proc.wait()
                    except Exception as e:
                        print(f"[MacSayTTS] Error speaking: {e}")
                    finally:
                        set_agent_audio_playing(False)
                        self._current_process = None
                        temp_path.unlink(missing_ok=True)
            except DuplicateSpeechSuppressed:
                return

        if block:
            _run()
        else:
            thread = threading.Thread(target=_run, daemon=True)
            thread.start()

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize speech to an audio file using macOS say."""
        if not text or not text.strip():
            return False
        clean_text = normalize_tts_text(text)
        try:
            out_p = Path(output_path)
            cmd = [
                "say",
                "-v",
                self.voice,
                "-r",
                str(self.rate),
                "-o",
                str(out_p),
                "--",
                clean_text,
            ]
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if res.returncode != 0:
                fallback = subprocess.run(
                    ["say", "-o", str(out_p), "--", clean_text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return fallback.returncode == 0
            return out_p.is_file()
        except Exception as e:
            print(f"[MacSayTTS] Error saving speech to file: {e}")
            return False

    @staticmethod
    def list_available_voices() -> List[str]:
        """List all voices available on the current macOS system."""
        try:
            output = subprocess.check_output(["say", "-v", "?"], text=True)
            voices = []
            for line in output.strip().split("\n"):
                if line:
                    voice_name = line.split()[0]
                    voices.append(voice_name)
            return voices
        except Exception:
            return ["Samantha", "Alex", "Victoria", "Daniel"]
