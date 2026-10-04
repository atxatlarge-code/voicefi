"""
VoiceFi Voice Acting Engine.
High-expression, prompt-directed local voice acting powered by MLX neural audio models
on Apple Silicon Metal GPU (0.98x RTF).
Allows natural language theatrical direction, shouting, deadpan irony, and showmanship
with zero reference audio files.
"""

import logging
import os
import re
import subprocess
import tempfile
import threading
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
from voicefi.tts.director import TheatricalDirector, DirectedPerformance

logger = logging.getLogger("voicefi.tts.voice_acting")

# Default quantized MLX CustomVoice model (4-bit, 964MB)
DEFAULT_VOICE_ACTING_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-4bit"
# Default quantized MLX Base model for zero-shot voice cloning (4-bit, Apache 2.0)
DEFAULT_VOICE_CLONING_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"

# Theatrical Persona Presets for Voice Acting
VOICE_ACTING_PRESETS: Dict[str, Dict[str, Any]] = {
    "drill_sergeant": {
        "base_voice": "ryan",
        "default_instruct": (
            "Shouting aggressively with fierce military drill sergeant discipline, barking commands, "
            "loud projection, rapid cadence, and zero hesitation."
        ),
        "speed": 1.12,
    },
    "deadpan_ironist": {
        "base_voice": "vivian",
        "default_instruct": (
            "Speaking with deadpan condescension, flat monotone smirk, weary software engineer chuckling "
            "with dry Elizabethan irony and trailing vocal fry."
        ),
        "speed": 0.96,
    },
    "game_show_host": {
        "base_voice": "aiden",
        "default_instruct": (
            "Extravagant high-energy 1980s television game-show host holding a golden microphone on stage "
            "with explosive booming showmanship and glossy enthusiasm."
        ),
        "speed": 1.08,
    },
    "shakespearean": {
        "base_voice": "eric",
        "default_instruct": (
            "Elizabethan Shakespearean classical stage actor performing a high-stakes tragedy with immense "
            "theatrical gravitas, trembling pathos, and dark poetic weight."
        ),
        "speed": 0.92,
    },
    "conspiratorial_insider": {
        "base_voice": "sohee",
        "default_instruct": (
            "Underground hacker whispering forbidden operating system secrets in a dimly lit alley with "
            "hushed urgent paranoia, conspiratorial intimacy, and nervous tension."
        ),
        "speed": 0.95,
    },
    "documentary_broadcaster": {
        "base_voice": "eric",
        "default_instruct": (
            "Legendary natural history documentary broadcaster speaking with hushed contemplative wonder, "
            "deep chest warmth, measured cadence, and British RP diction."
        ),
        "speed": 0.88,
    },
    "christopher_walken": {
        "base_voice": "eric",
        "default_instruct": (
            "Idiosyncratic erratic staccato rhythm with unexpected dramatic pauses, "
            "sudden pitch spikes, and deadpan comedic intensity."
        ),
        "speed": 0.98,
    },
    "the_continental": {
        "base_voice": "eric",
        "default_instruct": (
            "Christopher Walken performing as The Continental in a velvet robe holding champagne. "
            "Suave absurdity, intimate breathy rasp, theatrical eccentric cadence, "
            "unexpected elongated pregnant pauses, lingering consonants, and seductive comedic charm."
        ),
        "speed": 0.92,
    },
}

CANONICAL_PERSONAS = VOICE_ACTING_PRESETS


class VoiceActingTTS(BaseTTS):
    """
    Apple Silicon Native Voice Acting Engine.
    Executes discrete neural audio token generation directed via natural language prompts.
    """

    _cached_model = None
    _cached_model_id = None

    def __init__(
        self,
        persona_name: Optional[str] = None,
        instruct: Optional[str] = None,
        base_voice: Optional[str] = None,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        model_name: Optional[str] = None,
        speed: Optional[float] = None,
        apply_silk_mastering: bool = False,
        intro_sfx: Optional[Union[str, Path]] = None,
        intro_sfx_volume: float = 0.25,
    ):
        super().__init__()
        self.provider = "voice_acting"
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        self.intro_sfx = str(intro_sfx) if intro_sfx else None
        self.intro_sfx_volume = float(intro_sfx_volume)

        if model_name:
            self.model_name = model_name
        elif self.ref_audio:
            self.model_name = DEFAULT_VOICE_CLONING_MODEL
        else:
            self.model_name = DEFAULT_VOICE_ACTING_MODEL

        raw_name = (
            (persona_name or ("custom_clone" if ref_audio else "drill_sergeant"))
            .lower()
            .strip()
            .replace(" ", "_")
        )
        if raw_name in ("the_continental", "walken_continental", "continental"):
            raw_name = "the_continental"
        self.persona_name = raw_name
        self.preset = VOICE_ACTING_PRESETS.get(
            self.persona_name, VOICE_ACTING_PRESETS["deadpan_ironist"]
        )
        self.base_voice = base_voice or self.preset.get("base_voice", "ryan")
        self.instruct = instruct or self.preset.get("default_instruct", "")
        self.speed = speed if speed is not None else self.preset.get("speed", 1.0)
        self.apply_silk_mastering = apply_silk_mastering
        self.director = TheatricalDirector()
        self._current_process: Optional[subprocess.Popen] = None
        self._current_player: Optional[Any] = None
        self._cached_ref_mx = None
        self._stop_requested = False

    def _get_ref_audio_input(self):
        """Return cached mx.array waveform if available, otherwise file path or None."""
        if not self.ref_audio:
            return None
        if self._cached_ref_mx is not None:
            return self._cached_ref_mx
        try:
            import mlx.core as mx
            from mlx_audio.audio_io import read as audio_read

            ref_p = Path(self.ref_audio).expanduser()
            if ref_p.exists():
                ref_np, _ = audio_read(str(ref_p))
                self._cached_ref_mx = mx.array(ref_np)
                return self._cached_ref_mx
        except Exception:
            pass
        return self.ref_audio

    @classmethod
    def is_available(cls) -> bool:
        """Check if mlx and mlx-audio are available."""
        if os.environ.get("VOICEFI_MOCK_AUDIO") == "1" or os.environ.get("VOICEFI_TESTING") == "1":
            return True
        try:
            import mlx.core  # noqa: F401
            import mlx_audio.tts.utils  # noqa: F401

            return True
        except ImportError:
            return False

    @classmethod
    def get_model(cls, model_id: str = DEFAULT_VOICE_ACTING_MODEL):
        """Lazy-load and cache the MLX model in memory for zero-lag subsequent takes."""
        if cls._cached_model is not None and cls._cached_model_id == model_id:
            return cls._cached_model

        from mlx_audio.tts.utils import load_model

        cls._cached_model = load_model(model_id)
        cls._cached_model_id = model_id
        return cls._cached_model

    def apply_broadcast_silk(self, input_wav: Path, output_wav: Path) -> bool:
        """Apply BBC Broadcast Silk mastering to smooth out harmonics."""
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_wav),
            "-af",
            (
                "afftdn=nr=8:nf=-35,"
                "lowpass=f=11000,"
                "equalizer=f=6000:width_type=q:width=2.0:g=-1.5,"
                "equalizer=f=125:width_type=q:width=1.0:g=2.0,"
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

    @staticmethod
    def mix_intro_sfx(
        speech_wav: Union[str, Path],
        sfx_wav: Union[str, Path],
        output_wav: Union[str, Path],
        volume: float = 0.25,
    ) -> bool:
        """
        Mix an intro SFX / cue at the start of a speech WAV file.
        Resamples SFX if necessary, scales by volume, and overlays smoothly
        without altering speech pitch or introducing vocoder distortion.
        """
        try:
            import numpy as np
            import soundfile as sf
            import scipy.signal

            speech_p = Path(speech_wav).expanduser()
            sfx_p = Path(sfx_wav).expanduser()
            out_p = Path(output_wav).expanduser()

            if not speech_p.exists() or not sfx_p.exists():
                return False

            v_data, v_sr = sf.read(str(speech_p))
            s_data, s_sr = sf.read(str(sfx_p))

            if len(s_data.shape) > 1:
                s_data = np.mean(s_data, axis=1)
            if len(v_data.shape) > 1:
                v_data = np.mean(v_data, axis=1)

            if s_sr != v_sr:
                gcd = np.gcd(s_sr, v_sr)
                up = v_sr // gcd
                down = s_sr // gcd
                s_data = scipy.signal.resample_poly(s_data, up, down)

            v_rms = (
                np.sqrt(np.mean(v_data[: min(len(v_data), v_sr)] ** 2)) if len(v_data) > 0 else 0.1
            )
            s_rms = (
                np.sqrt(np.mean(s_data[: min(len(s_data), v_sr)] ** 2)) if len(s_data) > 0 else 0.1
            )
            scale = (v_rms / (s_rms + 1e-6)) * volume
            s_scaled = s_data * scale

            mix_len = max(len(v_data), len(s_scaled))
            mixed = np.zeros(mix_len, dtype=np.float32)
            mixed[: len(v_data)] += v_data
            mixed[: len(s_scaled)] += s_scaled

            peak = np.max(np.abs(mixed))
            if peak > 0.95:
                mixed = mixed / peak * 0.95

            sf.write(str(out_p), mixed, v_sr)
            return True
        except Exception as e:
            logger.warning(f"Failed to mix intro SFX: {e}")
            return False

    def speak_to_file(self, text: str, output_path: Union[str, Path]) -> bool:
        """
        Synthesize speech with prompt-directed acting into an output WAV file.
        """
        if not text or not text.strip():
            return False

        out_p = Path(output_path).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        # Mock / Testing Fast Path
        if os.environ.get("VOICEFI_MOCK_AUDIO") == "1" or os.environ.get("VOICEFI_TESTING") == "1":
            import wave

            with wave.open(str(out_p), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(b"\x00" * 4800)
            return True

        # Clean prompt
        clean_text = text.strip()
        # If bracket tags exist in text, we can use them to enrich the instruction
        brackets = re.findall(r"\[(.*?)\]", clean_text)
        effective_instruct = self.instruct
        if brackets:
            bracket_desc = ", ".join(brackets)
            effective_instruct = f"{self.instruct}. Performance details: {bracket_desc}"
            # Strip brackets from spoken words
            clean_text = re.sub(r"\[.*?\]", "", clean_text).strip()

        try:
            from mlx_audio.audio_io import write as audio_write

            model = self.get_model(self.model_name)

            ref_input = self._get_ref_audio_input()
            if ref_input is not None:
                results = list(
                    model.generate(
                        text=clean_text,
                        ref_audio=ref_input,
                        ref_text=self.ref_text,
                        speed=float(self.speed),
                    )
                )
            else:
                results = list(
                    model.generate(
                        text=clean_text,
                        voice=self.base_voice,
                        instruct=effective_instruct,
                        speed=float(self.speed),
                    )
                )

            if not results:
                logger.error("Voice Acting model produced zero audio results.")
                return False

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as raw_tmp:
                raw_tmp_path = Path(raw_tmp.name)

            audio_write(str(raw_tmp_path), results[0].audio, model.sample_rate, format="wav")

            if self.apply_silk_mastering:
                ok = self.apply_broadcast_silk(raw_tmp_path, out_p)
                raw_tmp_path.unlink(missing_ok=True)
            else:
                raw_tmp_path.replace(out_p)
                ok = True

            if ok and self.intro_sfx and Path(self.intro_sfx).expanduser().exists():
                self.mix_intro_sfx(out_p, self.intro_sfx, out_p, volume=self.intro_sfx_volume)

            return ok

        except Exception as e:
            logger.error(f"Voice Acting generation failed: {e}", exc_info=True)
            try:
                from voicefi.telemetry import capture_exception

                capture_exception(
                    e,
                    component="voice_acting",
                    properties={
                        "model_name": getattr(self, "model_name", "unknown"),
                        "persona": getattr(self, "persona_name", "unknown"),
                        "has_ref_audio": bool(getattr(self, "ref_audio", None)),
                    },
                )
            except Exception:
                pass
            return False

    def speak(self, text: str, block: bool = True) -> bool:
        """
        Synthesize and immediately play acting audio on macOS CoreAudio with robust fallback.
        """
        if not text or not text.strip():
            return False

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_f:
            tmp_path = Path(tmp_f.name)

        try:
            ok = self.speak_to_file(text, tmp_path)
        except Exception as e:
            logger.error(f"VoiceActingTTS synthesis unhandled exception: {e}")
            ok = False

        if not ok or not tmp_path.exists() or tmp_path.stat().st_size == 0:
            tmp_path.unlink(missing_ok=True)
            logger.warning(
                "[VoiceActingTTS] Generation failed; cascading to EdgeTTS / MacSay fallback."
            )
            try:
                from voicefi.tts.base import set_cross_process_hud_state

                set_cross_process_hud_state(
                    "speaking",
                    text=text,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    tag_text="⚠️ Ava Fallback",
                )
            except Exception:
                pass
            try:
                from voicefi.tts.edge_tts import EdgeTTS

                edge = EdgeTTS(
                    voice="en-US-AvaNeural", agent_name=getattr(self, "agent_name", "VoiceFi")
                )
                edge.speak(text, block=block)
                return True
            except Exception:
                from voicefi.tts.mac_say import MacSayTTS

                MacSayTTS().speak(text, block=block)
                return True

        def _play():
            try:
                try:
                    from voicefi.tts.base import set_cross_process_hud_state

                    set_cross_process_hud_state(
                        "speaking",
                        text=text,
                        agent_name=getattr(self, "agent_name", "VoiceFi"),
                        persona_name=getattr(self, "persona_name", "the_continental"),
                        tag_text="⚡ Local Metal",
                    )
                except Exception:
                    pass
                with speech_turn_lock(
                    text=text,
                    agent_name=getattr(self, "agent_name", "VoiceFi"),
                    persona_name=getattr(self, "persona_name", "the_continental"),
                ):
                    set_agent_audio_playing(True)
                    self._current_process = subprocess.Popen(
                        ["afplay", str(tmp_path)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    self._current_process.wait()
                    return self._current_process.returncode == 0
            finally:
                set_agent_audio_playing(False)
                self._current_process = None
                tmp_path.unlink(missing_ok=True)

        if block:
            return _play()
        else:
            threading.Thread(target=_play, daemon=True).start()
            return True

    def stream_speak(self, text: str, block: bool = True) -> bool:
        """
        Synthesize and play audio with maximum acoustic fidelity.
        Uses full global vocoder decoding to guarantee 100% dry acoustic clarity
        without streaming chunk boundary clicks or phase distortion.
        """
        return self.speak(text, block=block)

    def stop(self) -> None:
        """Stop active playback process immediately."""
        self._stop_requested = True
        if self._current_process:
            safe_terminate_process(self._current_process)
            self._current_process = None
        set_agent_speaking(False)
        set_agent_audio_playing(False)


# Aliases for explicit Qwen model addressing
QwenTTS = VoiceActingTTS
QwenCloneTTS = VoiceActingTTS
