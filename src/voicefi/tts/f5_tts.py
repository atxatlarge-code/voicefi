"""
F5-TTS Open-Source Zero-Shot Voice Cloning Provider for VoiceFi.
Enables running local, open-weights voice cloning models directly on Apple Silicon (MPS)
or CPU, synthesizing speech conditioned on a reference speaker sample (e.g. Angelica as Ava).
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

from voicefi.tts.base import (
    BaseTTS,
    set_agent_audio_playing,
    set_agent_speaking,
    speech_turn_lock,
    stop_all_speech,
    DuplicateSpeechSuppressed,
)


class F5TTS(BaseTTS):
    """
    Open-Source Zero-Shot Voice Cloning TTS Provider based on F5-TTS.
    Runs locally on Apple Silicon (MPS) or CPU without cloud APIs.
    """

    _model_cache = {}

    def __init__(
        self,
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        model_name: str = "F5TTS_v1_Base",
        device: Optional[str] = None,
        speed: float = 1.0,
    ):
        super().__init__()
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        self.model_name = model_name or "F5TTS_v1_Base"
        self.device = device
        self.speed = speed
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    @classmethod
    def get_f5_instance(cls, model_name: str = "F5TTS_v1_Base", device: Optional[str] = None):
        """Lazy-load and cache the F5TTS model instance."""
        target_device = device
        if target_device in (None, "auto"):
            try:
                import torch
                if torch.backends.mps.is_available():
                    target_device = "mps"
                elif torch.cuda.is_available():
                    target_device = "cuda"
                else:
                    target_device = "cpu"
            except Exception:
                target_device = "cpu"

        cache_key = (model_name, target_device)
        if cache_key in cls._model_cache:
            return cls._model_cache[cache_key]

        try:
            from f5_tts.api import F5TTS as F5TTSModel
            print(f"[F5-TTS] Loading local open-source model '{model_name}' on device '{target_device}'...")
            inst = F5TTSModel(model=model_name, device=target_device)
            cls._model_cache[cache_key] = inst
            return inst
        except ImportError:
            raise ImportError(
                "f5-tts is not installed. Install it with: 'uv pip install f5-tts' or 'pip install f5-tts'"
            )

    def _resolve_reference_audio(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Locate reference audio and transcription text for voice conditioning.
        If not explicitly set, checks cloned voices directory (~/.voicefi/cloned_voices).
        """
        if self.ref_audio and Path(self.ref_audio).exists():
            return str(Path(self.ref_audio).resolve()), self.ref_text

        # Check default clones directory
        clones_dir = Path.home() / ".voicefi" / "cloned_voices"
        if clones_dir.exists():
            # Check for ava or angelica or any trained profile
            for name in ["ava", "angelica", "default", "custom"]:
                p_dir = clones_dir / name
                prof_file = p_dir / "profile.json"
                if prof_file.is_file():
                    import json
                    try:
                        with open(prof_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        samples = data.get("sample_paths", [])
                        if samples and Path(samples[0]).exists():
                            ref_t = data.get("labels", {}).get("ref_text") or (
                                "Hey there! I am recording my voice so my AI coding agents can pair program and talk with me in real-time."
                            )
                            return str(Path(samples[0]).resolve()), ref_t
                    except Exception:
                        pass

        # Fallback to f5-tts bundled sample if available
        try:
            from importlib.resources import files
            bundled = str(files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav"))
            if Path(bundled).exists():
                return bundled, "Some call me nature, others call me mother nature."
        except Exception:
            pass

        return None, None

    def speak_to_file(self, text: str, output_path: Path) -> bool:
        """Synthesize speech conditioned on reference voice and write to audio file."""
        if not text or not text.strip():
            return False

        clean_text = text.strip()
        ref_file, ref_text = self._resolve_reference_audio()

        if not ref_file:
            print("[F5-TTS] Warning: No reference audio found. Record one with 'vifi clone record <name>'")
            return False

        try:
            f5_inst = self.get_f5_instance(self.model_name, self.device)
            if not ref_text:
                ref_text = f5_inst.transcribe(ref_file)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            f5_inst.infer(
                ref_file=ref_file,
                ref_text=ref_text,
                gen_text=clean_text,
                file_wave=str(output_path),
                speed=self.speed,
                remove_silence=True,
            )
            return output_path.exists() and output_path.stat().st_size > 0
        except Exception as e:
            print(f"[F5-TTS] Synthesis error: {e}")
            return False

    def speak(self, text: str, block: bool = True) -> None:
        """Synthesize speech using local F5-TTS and play aloud over macOS speakers."""
        if not text or not text.strip():
            return

        self._stop_requested = False
        turn_start_time = time.time()

        with speech_turn_lock(
            text=text,
            agent_name=getattr(self, "agent_name", "VoiceFi"),
            persona_name=getattr(self, "persona_name", "Custom Clone"),
        ):
            from voicefi.tts.base import is_speech_interrupted
            if self._stop_requested or is_speech_interrupted(turn_start_time):
                return

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                success = self.speak_to_file(text, tmp_path)
                if self._stop_requested or is_speech_interrupted(turn_start_time):
                    return
                if not success or not tmp_path.exists():
                    print("[F5-TTS] Failed to generate audio. Falling back to native macOS say.")
                    from voicefi.tts.mac_say import MacSayTTS
                    MacSayTTS().speak(text, block=block)
                    return

                # Play generated WAV via afplay
                set_agent_audio_playing(True)
                self._current_process = subprocess.Popen(
                    ["afplay", str(tmp_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                if block:
                    self._current_process.wait()
            finally:
                set_agent_audio_playing(False)
                set_agent_speaking(False)
                self._current_process = None
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def stop(self) -> None:
        """Interrupt playback."""
        self._stop_requested = True
        if self._current_process:
            try:
                self._current_process.terminate()
            except Exception:
                pass
            self._current_process = None
        stop_all_speech()
