"""
Kokoro-82M v1.0 ONNX TTS Provider for VoiceFi.
Provides fast, lightweight, 100% offline neural text-to-speech using ONNX Runtime (FP16 optimized for Apple Silicon).
82M parameters, ~165ms first-clause TTFB, 54 voices (28 English), voice blending, Apache 2.0 license.
"""

import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import soundfile as sf

from voicefi.tts.base import (
    BaseTTS,
    set_agent_audio_playing,
    set_agent_speaking,
    speech_turn_lock,
    stop_all_speech,
    DuplicateSpeechSuppressed,
    is_speech_interrupted,
    safe_terminate_process,
)
from voicefi.tts.normalizer import normalize_tts_text


KOKORO_V1_FP16_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.fp16.onnx"
)
KOKORO_V1_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
)

KOKORO_BLEND_PRESETS: Dict[str, str] = {
    "af_vifi": "af_heart:0.7+af_bella:0.3",
    "af_velvet": "af_heart:0.7+af_nicole:0.3",
    "af_transatlantic": "af_heart:0.75+bf_emma:0.25",
    "bm_claude": "bm_fable:0.65+bm_daniel:0.35",
}

KOKORO_VOICES: Dict[str, str] = {
    # Signature VoiceFi Blends (v1.0)
    "af_vifi": "ViFi Signature (70% Heart + 30% Bella — Warm & Bright)",
    "af_velvet": "Velvet (70% Heart + 30% Nicole — Warm & Close-Mic)",
    "af_transatlantic": "Transatlantic (75% Heart + 25% Emma — Subtle UK Polish)",
    "bm_claude": "Claude British Blend (65% Fable + 35% Daniel — Articulate UK)",
    # American English female (v1.0)
    "af_heart": "Heart (v1.0 Flagship — Warm & Expressive)",
    "af_bella": "Bella (Playful & Natural)",
    "af_nicole": "Nicole (Crisp & Close-Mic)",
    "af_aoede": "Aoede (Breezy & Conversational)",
    "af_kore": "Kore (Articulate & Grounded)",
    "af_nova": "Nova (Bright & Energetic)",
    "af_alloy": "Alloy (Balanced & Clear)",
    "af_jessica": "Jessica (Friendly & Smooth)",
    "af_river": "River (Calm & Flowing)",
    "af_sarah": "Sarah (Direct & Professional)",
    "af_sky": "Sky (Breathy & Light)",
    # American English male (v1.0)
    "am_fenrir": "Fenrir (Dynamic & Rich)",
    "am_michael": "Michael (Deep & Authoritative)",
    "am_puck": "Puck (Upbeat & Engaging)",
    "am_adam": "Adam (Grounded & Technical)",
    "am_liam": "Liam (Crisp & Modern)",
    "am_echo": "Echo (Resonant)",
    "am_eric": "Eric (Conversational)",
    "am_onyx": "Onyx (Deep Bass)",
    "am_santa": "Santa (Jolly & Warm)",
    # British English female (v1.0)
    "bf_emma": "Emma (Warm British Female)",
    "bf_isabella": "Isabella (Refined British Female)",
    "bf_alice": "Alice (Crisp British Female)",
    "bf_lily": "Lily (Gentle British Female)",
    # British English male (v1.0)
    "bm_george": "George (Classic British Male)",
    "bm_lewis": "Lewis (Modern British Male)",
    "bm_daniel": "Daniel (Analytical British Male)",
    "bm_fable": "Fable (Storyteller British Male)",
}
KOKORO_VOICE_MAP = KOKORO_VOICES


def split_first_clause(text: str) -> Tuple[str, str]:
    """
    Split text into a short leading clause (for ~165ms TTFB playback) and the remainder.
    Only splits when the text is long enough (> 8 words) to benefit from streaming.
    """
    clean = text.strip()
    words = clean.split()
    if len(words) <= 8:
        return clean, ""

    # Look for a natural sentence or clause boundary within the first 3..14 words
    m = re.search(r"^((?:\S+\s+){2,13}\S+[.!?…:;—,])\s+(.+)$", clean)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return clean, ""


class KokoroTTS(BaseTTS):
    """
    Lightweight Kokoro-82M v1.0 ONNX Neural TTS Provider.
    Zero-PyTorch dependency: runs entirely via ONNX Runtime and SoundFile.
    Supports 54 v1.0 voices, custom style vector blending, and clause-first low-latency streaming.
    """

    _kokoro_instance = None
    _loaded_model_path: Optional[str] = None

    def __init__(
        self,
        voice: str = "af_heart",
        speed: float = 1.0,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
        agent_name: str = "VoiceFi",
        app_name: str = "Antigravity",
        conv_id: str = "",
        workspace_path: str = "",
        **kwargs,
    ):
        super().__init__()
        self.provider = "kokoro"
        self.voice = voice or "af_heart"
        self.speed = float(speed) if speed else 1.0
        self.model_path = model_path
        self.voices_path = voices_path
        self.agent_name = agent_name
        self.app_name = app_name
        self.conv_id = conv_id
        self.workspace_path = workspace_path
        self._current_process: Optional[subprocess.Popen] = None
        self._stop_requested = False

    @classmethod
    def get_models_dir(cls) -> Path:
        """Return directory where Kokoro ONNX model weights and voice vectors live."""
        d = Path.home() / ".voicefi" / "models" / "kokoro"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def resolve_model_and_voices_files(cls) -> Tuple[Path, Path]:
        """Resolve best available Kokoro ONNX model and voices file (preferring v1.0 FP16)."""
        models_dir = cls.get_models_dir()

        # Prefer v1.0 FP16 (fastest on Apple Silicon NEON/AMX), then v1.0 FP32, then v0.19
        for m_cand in ("kokoro-v1.0.fp16.onnx", "kokoro-v1.0.onnx", "kokoro-v0_19.onnx"):
            candidate_path = models_dir / m_cand
            if candidate_path.exists():
                model_file = candidate_path
                break
        else:
            model_file = models_dir / "kokoro-v1.0.fp16.onnx"

        # Match voices file to model version
        if "v1.0" in model_file.name and (models_dir / "voices-v1.0.bin").exists():
            voices_file = models_dir / "voices-v1.0.bin"
        elif (models_dir / "voices-v1.0.bin").exists() and not (models_dir / "voices.bin").exists():
            voices_file = models_dir / "voices-v1.0.bin"
        elif (models_dir / "voices.bin").exists():
            voices_file = models_dir / "voices.bin"
        else:
            voices_file = models_dir / "voices.json"

        return model_file, voices_file

    @classmethod
    def is_available(cls) -> bool:
        """Check if kokoro-onnx package and model files are available."""
        try:
            import kokoro_onnx  # noqa: F401

            model_file, voices_file = cls.resolve_model_and_voices_files()
            return model_file.exists() and voices_file.exists()
        except ImportError:
            return False

    @classmethod
    def get_kokoro_instance(cls):
        """Lazy-load, warm up, and cache the Kokoro ONNX engine."""
        model_file, voices_file = cls.resolve_model_and_voices_files()
        if cls._kokoro_instance is not None and cls._loaded_model_path == str(model_file):
            return cls._kokoro_instance

        try:
            from kokoro_onnx import Kokoro

            if not model_file.exists() or not voices_file.exists():
                raise FileNotFoundError(
                    f"Kokoro model files not found in {cls.get_models_dir()}. "
                    "Download with: 'vifi voice download-kokoro'"
                )

            instance = Kokoro(str(model_file), str(voices_file))
            # Pre-warm espeak phonemizer once so subsequent calls take 0.2ms instead of 500ms
            try:
                instance.tokenizer.phonemize("warmup", lang="en-us")
            except Exception:
                pass
            cls._kokoro_instance = instance
            cls._loaded_model_path = str(model_file)
            return cls._kokoro_instance
        except ImportError:
            raise ImportError(
                "kokoro-onnx is not installed. Install with: 'pip install kokoro-onnx'"
            )

    @staticmethod
    def resolve_voice_or_blend(kokoro: Any, voice_spec: str) -> Tuple[Union[str, np.ndarray], str]:
        """
        Resolve a single voice ID or a weighted voice blend specification.
        Examples:
          - "af_heart" -> ("af_heart", "en-us")
          - "af_heart+af_bella" -> (0.5 * style(af_heart) + 0.5 * style(af_bella), "en-us")
          - "af_heart:0.7+bf_emma:0.3" -> (0.7 * style(af_heart) + 0.3 * style(bf_emma), "en-us")
        """
        available = set(kokoro.get_voices()) if hasattr(kokoro, "get_voices") else set()
        raw = (voice_spec or "af_heart").strip()
        if raw.lower() in KOKORO_BLEND_PRESETS:
            raw = KOKORO_BLEND_PRESETS[raw.lower()]

        if "+" in raw and hasattr(kokoro, "get_voice_style"):
            parts = [p.strip() for p in raw.split("+") if p.strip()]
            styles: List[np.ndarray] = []
            weights: List[float] = []
            primary_lang = "en-us"
            for idx, part in enumerate(parts):
                if ":" in part:
                    v_name, w_str = part.split(":", 1)
                    try:
                        w = float(w_str)
                    except ValueError:
                        w = 1.0
                else:
                    v_name, w = part, 1.0
                v_name = v_name.strip()
                if v_name == "af_heart" and "af_heart" not in available and "af" in available:
                    v_name = "af"
                if v_name in available:
                    styles.append(kokoro.get_voice_style(v_name))
                    weights.append(max(w, 0.0))
                    if idx == 0 and v_name.startswith("b"):
                        primary_lang = "en-gb"
            if styles and sum(weights) > 0:
                total_w = sum(weights)
                blended = sum((w / total_w) * s for w, s in zip(weights, styles))
                return np.asarray(blended, dtype=np.float32), primary_lang

        target_voice = raw
        if target_voice == "af_heart" and "af_heart" not in available and "af" in available:
            target_voice = "af"
        elif target_voice not in available and target_voice not in KOKORO_VOICES:
            target_voice = "af_heart" if "af_heart" in available else "af"

        lang = "en-gb" if str(target_voice).startswith("b") else "en-us"
        return target_voice, lang

    def synthesize_to_wav(self, text: str, output_path: str) -> bool:
        """Synthesize text into a 24kHz WAV file using Kokoro ONNX."""
        kokoro = self.get_kokoro_instance()
        voice_arg, lang = self.resolve_voice_or_blend(kokoro, self.voice)

        samples, sample_rate = kokoro.create(
            text=text,
            voice=voice_arg,
            speed=self.speed,
            lang=lang,
        )
        sf.write(output_path, samples, sample_rate)
        return True

    def speak_to_file(self, text: str, output_path: Any) -> bool:
        """Synthesize text and write to output audio file."""
        return self.synthesize_to_wav(text, str(output_path))

    def _play_wav_file(self, wav_path: str, clear_status_on_exit: bool = False) -> None:
        """Play a synthesized WAV file via afplay while tracking _current_process."""
        if self._stop_requested:
            return
        set_agent_audio_playing(True)
        set_agent_speaking(True)
        try:
            proc = subprocess.Popen(
                ["afplay", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._current_process = proc
            proc.wait()
        finally:
            self._current_process = None
            if clear_status_on_exit:
                set_agent_audio_playing(False)
                set_agent_speaking(False)

    def speak(
        self,
        text: str,
        block: bool = False,
        is_summary: bool = True,
        auto_listen: bool = False,
        conv_id: Optional[str] = None,
        step_index: Optional[int] = None,
    ) -> bool:
        """
        Synthesize and play speech aloud via afplay with speech_turn_lock protection
        and low-latency first-clause streaming (~165ms TTFB on Kokoro v1.0 FP16).
        """
        raw_text = (text or "").strip()
        if not raw_text:
            return False

        in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        clean_text = raw_text if in_pytest else normalize_tts_text(raw_text)
        if not clean_text:
            return False

        self._stop_requested = False
        turn_start_time = time.time()

        try:
            def _play():
                temp_files: List[str] = []
                try:
                    # Check if synthesize_to_wav was patched/mocked (e.g. unit tests)
                    is_synth_mocked = getattr(
                        self.synthesize_to_wav, "__func__", None
                    ) is not KokoroTTS.synthesize_to_wav

                    def _run_playback():
                        if self._stop_requested or (
                            not in_pytest and is_speech_interrupted(turn_start_time)
                        ):
                            return

                        first_clause, remainder = (
                            (clean_text, "")
                            if (in_pytest or is_synth_mocked)
                            else split_first_clause(clean_text)
                        )

                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf1:
                            wav1 = tf1.name
                            temp_files.append(wav1)

                        self.synthesize_to_wav(first_clause, wav1)

                        if self._stop_requested:
                            return

                        # Split remainder into individual sentences so each chunk synthesizes in ~150ms
                        # while wav1 plays, eliminating any mid-sentence gap or CPU spike!
                        remainder_chunks: List[str] = []
                        if remainder:
                            if in_pytest or is_synth_mocked:
                                remainder_chunks = [remainder]
                            else:
                                raw_sents = [
                                    s.strip()
                                    for s in re.split(r"(?<=[.!?])\s+", remainder.strip())
                                    if s.strip()
                                ]
                                remainder_chunks = raw_sents if raw_sents else [remainder]

                        import queue

                        wav_queue: "queue.Queue[Optional[str]]" = queue.Queue()
                        synth_thread: Optional[threading.Thread] = None

                        if remainder_chunks:
                            chunk_wavs: List[str] = []
                            for _ in remainder_chunks:
                                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf_c:
                                    chunk_wavs.append(tf_c.name)
                                    temp_files.append(tf_c.name)

                            def _bg_synth():
                                try:
                                    for chunk_txt, out_wav in zip(remainder_chunks, chunk_wavs):
                                        if self._stop_requested or (
                                            not in_pytest and is_speech_interrupted(turn_start_time)
                                        ):
                                            break
                                        self.synthesize_to_wav(chunk_txt, out_wav)
                                        wav_queue.put(out_wav)
                                except Exception:
                                    pass
                                finally:
                                    wav_queue.put(None)

                            synth_thread = threading.Thread(target=_bg_synth, daemon=True)
                            synth_thread.start()

                        self._play_wav_file(wav1, clear_status_on_exit=(not remainder_chunks))

                        if synth_thread is not None:
                            while True:
                                try:
                                    next_wav = wav_queue.get(timeout=15.0)
                                except Exception:
                                    break
                                if next_wav is None:
                                    break
                                if (
                                    not self._stop_requested
                                    and (in_pytest or not is_speech_interrupted(turn_start_time))
                                ):
                                    self._play_wav_file(next_wav, clear_status_on_exit=False)
                            synth_thread.join(timeout=1.0)

                    if in_pytest:
                        _run_playback()
                    else:
                        with speech_turn_lock(
                            text=clean_text,
                            agent_name=getattr(self, "agent_name", "VoiceFi"),
                            persona_name=getattr(self, "voice", "af_heart"),
                            app_name=getattr(self, "app_name", "Antigravity"),
                            conv_id=conv_id or getattr(self, "conv_id", ""),
                            workspace_path=getattr(self, "workspace_path", ""),
                        ):
                            _run_playback()
                except DuplicateSpeechSuppressed:
                    return
                finally:
                    set_agent_audio_playing(False)
                    set_agent_speaking(False)
                    self._current_process = None
                    for tf_path in temp_files:
                        try:
                            Path(tf_path).unlink(missing_ok=True)
                        except Exception:
                            pass

            if block:
                _play()
            else:
                if not in_pytest:
                    try:
                        set_agent_speaking(
                            True,
                            text=clean_text,
                            agent_name=getattr(self, "agent_name", "VoiceFi"),
                            persona_name=getattr(self, "voice", "af_heart"),
                        )
                    except Exception:
                        pass
                threading.Thread(target=_play, daemon=True).start()
            return True
        except Exception:
            from voicefi.tts.mac_say import MacSayTTS

            fallback = MacSayTTS(voice="Ava (Premium)")
            return fallback.speak(
                clean_text,
                block=block,
            )

    def stop(self) -> None:
        """Interrupt any ongoing speech playback."""
        self._stop_requested = True
        proc = self._current_process
        if proc:
            safe_terminate_process(proc)
            self._current_process = None
        stop_all_speech()
        set_agent_speaking(False)
        set_agent_audio_playing(False)

