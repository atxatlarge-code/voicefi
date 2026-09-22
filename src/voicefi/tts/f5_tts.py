"""
F5-TTS Open-Source Zero-Shot Voice Cloning Provider for VoiceFi.
Enables running local, open-weights voice cloning models directly on Apple Silicon (MPS)
or CPU, synthesizing speech conditioned on a reference speaker sample (e.g. Reference Speaker Sample as Ava).
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


def normalize_f5_model_name(model_name: Optional[str]) -> str:
    """Map user-facing aliases (e.g. F5-TTS) to the exact YAML config name."""
    if not model_name:
        return "F5TTS_v1_Base"
    m = str(model_name).strip()
    if m in ("F5-TTS", "F5_TTS", "f5_tts", "F5TTS", "f5-tts", "f5tts"):
        return "F5TTS_v1_Base"
    if m in ("E2-TTS", "E2_TTS", "e2_tts", "E2TTS", "e2-tts", "e2tts"):
        return "E2TTS_Base"
    return m


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
        nfe_step: int = 32,
        persona_name: Optional[str] = None,
    ):
        super().__init__()
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        self.model_name = normalize_f5_model_name(model_name)
        self.device = device
        self.speed = speed
        self.nfe_step = nfe_step or 32
        self.persona_name = persona_name
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    @classmethod
    def is_available(cls) -> bool:
        """Check if f5_tts and torchcodec packages are installed and functional."""
        try:
            import f5_tts  # noqa: F401
            import torchcodec  # noqa: F401
            return True
        except ImportError:
            return False
        except Exception:
            return False

    @classmethod
    def get_f5_instance(cls, model_name: str = "F5TTS_v1_Base", device: Optional[str] = None):
        """Lazy-load and cache the F5TTS model instance."""
        target_model = normalize_f5_model_name(model_name)
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

        cache_key = (target_model, target_device)
        if cache_key in cls._model_cache:
            return cls._model_cache[cache_key]

        try:
            from f5_tts.api import F5TTS as F5TTSModel

            # Patch f5_tts.infer.utils_infer.ThreadPoolExecutor to use max_workers=1 on Apple Silicon MPS.
            # PyTorch MPS Metal command queues are not thread-safe and crash with SIGSEGV on concurrent threads.
            try:
                import f5_tts.infer.utils_infer as ui
                from concurrent.futures import ThreadPoolExecutor as StdThreadPoolExecutor

                class SafeMPSThreadPoolExecutor(StdThreadPoolExecutor):
                    def __init__(self, *args, **kwargs):
                        if target_device == "mps":
                            kwargs["max_workers"] = 1
                        super().__init__(*args, **kwargs)

                ui.ThreadPoolExecutor = SafeMPSThreadPoolExecutor
            except Exception:
                pass

            inst = F5TTSModel(model=target_model, device=target_device)
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

        # 1. Check VoiceCloneManager for active persona/voice
        try:
            from voicefi.tts.cloning import VoiceCloneManager

            vcm = VoiceCloneManager()
            for cand in [
                getattr(self, "persona_name", None),
                getattr(self, "voice", None),
                "documentary_broadcaster",
                "attenborough",
            ]:
                if cand:
                    c_prof = vcm.get_cloned_voice(cand)
                    if c_prof and c_prof.sample_paths:
                        s_path = Path(c_prof.sample_paths[0])
                        if s_path.exists():
                            r_text = c_prof.labels.get("ref_text") if c_prof.labels else None
                            return str(s_path.resolve()), r_text
        except Exception:
            pass

        # 2. Check default clones directory
        clones_dir = Path.home() / ".voicefi" / "cloned_voices"
        if clones_dir.exists():
            for p_dir in clones_dir.iterdir():
                if not p_dir.is_dir():
                    continue
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

        # 3. Fallback to f5-tts bundled sample if available
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
            print(
                "[F5-TTS] Warning: No reference audio found. Record one with 'vifi clone record <name>'"
            )
            return False

        try:
            from voicefi.tts.normalizer import inject_documentary_breathing_pauses
            from voicefi.audio.mastering import apply_bbc_documentary_mastering

            # Apply breathing pauses if this is a documentary narrator profile
            is_doc_narrator = any(
                k in str(ref_file).lower() or k in str(getattr(self, "persona_name", "")).lower()
                for k in ("documentary", "broadcaster", "attenborough")
            )
            if is_doc_narrator:
                clean_text = inject_documentary_breathing_pauses(clean_text)

            f5_inst = self.get_f5_instance(self.model_name, self.device)
            if not ref_text:
                ref_text = f5_inst.transcribe(ref_file)

            import random
            safe_seed = random.randint(0, 4294967295)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            f5_inst.infer(
                ref_file=ref_file,
                ref_text=ref_text,
                gen_text=clean_text,
                file_wave=str(output_path),
                speed=self.speed,
                remove_silence=True,
                seed=safe_seed,
                nfe_step=self.nfe_step,
            )

            # Ensure PYTHONHASHSEED is valid 32-bit unsigned int or pop it
            if "PYTHONHASHSEED" in os.environ:
                try:
                    val = int(os.environ["PYTHONHASHSEED"])
                    if val < 0 or val > 4294967295:
                        os.environ.pop("PYTHONHASHSEED", None)
                except ValueError:
                    if os.environ.get("PYTHONHASHSEED") != "random":
                        os.environ.pop("PYTHONHASHSEED", None)

            if output_path.exists() and output_path.stat().st_size > 0:
                # Apply BBC studio broadcast mastering chain
                apply_bbc_documentary_mastering(output_path, output_path)
                return True
            return False
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
                    from voicefi.tts.cloning import VoiceCloneManager
                    from voicefi.tts.edge_tts import EdgeTTS
                    from voicefi.tts.mac_say import MacSayTTS

                    vcm = VoiceCloneManager()
                    c_prof = vcm.get_cloned_voice(getattr(self, "persona_name", "documentary_broadcaster")) or vcm.get_cloned_voice("attenborough")
                    if c_prof and c_prof.calibrated_voice and "Neural" in str(c_prof.calibrated_voice):
                        print(
                            f"[F5-TTS] Notice: Falling back to calibrated neural voice '{c_prof.calibrated_voice}' with BBC studio mastering."
                        )
                        eng = EdgeTTS(
                            voice=c_prof.calibrated_voice,
                            rate=f"{c_prof.calibrated_rate or 148}wpm",
                            pitch=getattr(c_prof, "calibrated_pitch", "-5Hz") or "-5Hz",
                        )
                        eng.speak(text, block=block)
                    else:
                        print("[F5-TTS] Failed to generate audio. Falling back to native macOS say.")
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
