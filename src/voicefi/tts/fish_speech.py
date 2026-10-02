"""
Fish Speech & Discrete Neural Audio Codec Provider for VoiceFi.
Provides fully local, highly expressive, actor-like speech synthesis
with natural language performance bracket tags (e.g. [laughing dryly], [shouting command])
running on Apple Silicon Metal GPU (MLX / MPS).
"""

import logging
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from voicefi.tts.base import (
    BaseTTS,
    set_agent_audio_playing,
    set_agent_speaking,
    speech_turn_lock,
    stop_all_speech,
    DuplicateSpeechSuppressed,
    safe_terminate_process,
)
from voicefi.tts.director import TheatricalDirector, DirectedPerformance, CANONICAL_PERSONAS

logger = logging.getLogger("voicefi.tts.fish_speech")

# Standard Fish Audio local server endpoint (e.g. fish-speech API or MLX Talk provider)
FISH_SPEECH_HTTP_URL = os.environ.get("FISH_SPEECH_URL", "http://127.0.0.1:8080/v1/tts")


class FishSpeechTTS(BaseTTS):
    """
    Autoregressive Audio Codec TTS Provider (Fish Speech S2 Pro / 1.5).
    Translates character acting directives and natural language bracket tags
    into expressive local acoustic performances.
    """

    _mlx_model = None

    def __init__(
        self,
        persona_name: Optional[str] = "deadpan_ironist",
        speaker: Optional[str] = None,
        model_name: str = "fishaudio-s2-pro",
        device: Optional[str] = None,
        speed: float = 1.0,
        enable_director: bool = True,
        apply_silk_mastering: bool = True,
    ):
        super().__init__()
        self.provider = "fish_speech"
        self.persona_name = persona_name or "deadpan_ironist"
        self.speaker = speaker
        self.model_name = model_name
        self.device = device or "mps"
        self.speed = speed
        self.enable_director = enable_director
        self.apply_silk_mastering = apply_silk_mastering
        self.director = TheatricalDirector()
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    @classmethod
    def get_models_dir(cls) -> Path:
        """Directory where local weights and speaker embeddings live."""
        d = Path.home() / ".voicefi" / "models" / "fish_speech"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def is_available(cls) -> bool:
        """Check if local fish-speech package, MLX model, or HTTP service is accessible."""
        if os.environ.get("VOICEFI_MOCK_AUDIO") == "1" or os.environ.get("VOICEFI_TESTING") == "1":
            return True

        # 1. Check if local HTTP daemon is listening
        try:
            import urllib.request
            req = urllib.request.Request(FISH_SPEECH_HTTP_URL.replace("/v1/tts", "/v1/models"))
            with urllib.request.urlopen(req, timeout=0.5):
                return True
        except Exception:
            pass

        # 2. Check if mlx or fish_speech python module is importable
        try:
            import mlx.core  # noqa: F401
            return True
        except ImportError:
            pass

        try:
            import fish_speech  # noqa: F401
            return True
        except ImportError:
            pass

        return False

    def _resolve_speaker_reference(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Locate reference audio and transcript for the target persona/speaker.
        """
        clones_dir = Path.home() / ".voicefi" / "cloned_voices"
        cand_keys = [self.speaker, self.persona_name, "documentary_broadcaster"]
        for k in cand_keys:
            if not k:
                continue
            cand_p = clones_dir / k / "samples" / "sample_01.wav"
            txt_p = clones_dir / k / "samples" / "sample_01.txt"
            if cand_p.exists():
                ref_txt = txt_p.read_text(encoding="utf-8").strip() if txt_p.exists() else None
                return str(cand_p.resolve()), ref_txt

        return None, None

    def direct_text(self, text: str) -> DirectedPerformance:
        """
        Pass text through the Theatrical Director to inject natural language performance brackets
        if none are already present in the script.
        """
        has_brackets = bool(re.search(r"\[.*?\]", text))
        if has_brackets:
            # Already directed by author
            tags = re.findall(r"\[(.*?)\]", text)
            return DirectedPerformance(
                raw_text=text,
                directed_text=text,
                character_key=self.persona_name,
                primary_emotion="custom_directed",
                speed=self.speed,
                pitch_shift="0st",
                bracket_tags=tags,
                director_model="user-prompt",
            )

        if not self.enable_director:
            return self.director.direct_rule_based(text, self.persona_name)

        # Run heuristic/fast director
        return self.director.direct_rule_based(text, self.persona_name)

    def apply_broadcast_silk(self, input_wav: Path, output_wav: Path) -> bool:
        """
        Apply BBC Broadcast Silk mastering to eliminate neural codec floor hash
        and warm up chest resonance.
        """
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_wav),
            "-af",
            (
                "afftdn=nr=10:nf=-35,"
                "lowpass=f=10500,"
                "equalizer=f=6000:width_type=q:width=2.0:g=-2.0,"
                "equalizer=f=125:width_type=q:width=1.0:g=2.5,"
                "volume=-0.5dB"
            ),
            str(output_wav),
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return res.returncode == 0
        except Exception as e:
            logger.warning(f"Broadcast Silk mastering failed: {e}")
            return False

    def speak_to_file(self, text: str, output_path: Union[str, Path]) -> bool:
        """
        Synthesize text with theatrical bracket acting tags into an output WAV file.
        """
        if not text or not text.strip():
            return False

        out_p = Path(output_path).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        # 1. Direct text with emotional tags
        directed = self.direct_text(text)
        prompt_with_acting = directed.directed_text
        ref_audio, ref_text = self._resolve_speaker_reference()

        # Mock / Testing Fast Path
        if os.environ.get("VOICEFI_MOCK_AUDIO") == "1" or os.environ.get("VOICEFI_TESTING") == "1":
            import wave
            with wave.open(str(out_p), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(b"\x00" * 4800)
            return True

        # 2. Try HTTP Server (Fast local daemon)
        try:
            import urllib.request
            import json

            payload = {
                "text": prompt_with_acting,
                "speaker": self.speaker or self.persona_name,
                "reference_audio": ref_audio,
                "reference_text": ref_text,
                "speed": directed.speed or self.speed,
            }
            req = urllib.request.Request(
                FISH_SPEECH_HTTP_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as raw_tmp:
                    raw_tmp.write(resp.read())
                    raw_tmp_path = Path(raw_tmp.name)

                if self.apply_silk_mastering:
                    ok = self.apply_broadcast_silk(raw_tmp_path, out_p)
                    raw_tmp_path.unlink(missing_ok=True)
                    return ok
                else:
                    raw_tmp_path.replace(out_p)
                    return True
        except Exception as e:
            logger.debug(f"Fish speech HTTP endpoint unavailable ({e}), trying fallback pipeline.")

        # 3. Fallback: Pipe to F5-TTS Multi-Emotion Engine
        try:
            from voicefi.tts.f5_tts import F5TTS

            f5 = F5TTS(
                persona_name=self.persona_name,
                speed=directed.speed or self.speed,
                ref_audio=ref_audio,
                ref_text=ref_text,
                emotion=directed.primary_emotion,
            )
            return f5.speak_to_file(directed.raw_text, out_p)
        except Exception as e:
            logger.error(f"FishSpeech fallback to F5-TTS failed: {e}")
            return False

    def speak(self, text: str, block: bool = True) -> bool:
        """
        Synthesize and immediately play audio on macOS CoreAudio.
        """
        if not text or not text.strip():
            return False

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_f:
            tmp_path = Path(tmp_f.name)

        ok = self.speak_to_file(text, tmp_path)
        if not ok or not tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
            return False

        try:
            with speech_turn_lock:
                stop_all_speech()
                set_agent_speaking(True)
                set_agent_audio_playing(True)

                self._current_process = subprocess.Popen(
                    ["afplay", str(tmp_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

            if block:
                self._current_process.wait()
                return self._current_process.returncode == 0
            return True
        finally:
            if block:
                set_agent_speaking(False)
                set_agent_audio_playing(False)
                tmp_path.unlink(missing_ok=True)

    def stop(self) -> None:
        """Stop active playback process immediately."""
        self._stop_requested = True
        if self._current_process:
            safe_terminate_process(self._current_process)
            self._current_process = None
        set_agent_speaking(False)
        set_agent_audio_playing(False)
