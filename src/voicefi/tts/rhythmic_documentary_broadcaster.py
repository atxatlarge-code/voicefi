"""
VoiceFi™ Rhythmic Documentary Broadcaster Engine.
Synthesizes and aligns documentary broadcaster nature documentary narration
to standardized musical bar/beat grids (90 BPM 4/4 meter) with BBC Broadcast Silk
mastering and pure NumPy sample-accurate timeline placement.
"""

import os
import sys
import wave
import tempfile
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

# Ensure Homebrew library fallback on Apple Silicon
if sys.platform == "darwin" and "DYLD_FALLBACK_LIBRARY_PATH" not in os.environ:
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib"

from voicefi.audio.mastering import apply_broadcast_silk_mastering
from voicefi.audio.rhythmic_beat_engine import RhythmicGrid, SAMPLE_RATE


def load_wav_as_float32(
    path: Union[str, Path], target_sr: int = SAMPLE_RATE
) -> Tuple[np.ndarray, int]:
    """Reads a WAV file, converts to mono float32 (-1.0 to 1.0), and resamples if needed."""
    p = str(path)
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        p,
        "-ac",
        "1",
        "-ar",
        str(target_sr),
        "-f",
        "f32le",
        "-",
    ]
    raw = subprocess.check_output(cmd)
    audio = np.frombuffer(raw, dtype=np.float32)
    return audio, target_sr


def apply_edge_micro_fades(
    data: np.ndarray, sr: int = SAMPLE_RATE, fade_in_ms: float = 20.0, fade_out_ms: float = 40.0
) -> np.ndarray:
    """Applies linear micro-fades to start and end of stem to guarantee 0 zero-crossing clicks."""
    out = data.copy()
    n_in = int(sr * (fade_in_ms / 1000.0))
    n_out = int(sr * (fade_out_ms / 1000.0))

    if len(out) > n_in and n_in > 0:
        out[:n_in] *= np.linspace(0.0, 1.0, n_in, dtype=np.float32)
    if len(out) > n_out and n_out > 0:
        out[-n_out:] *= np.linspace(1.0, 0.0, n_out, dtype=np.float32)
    return out


class RhythmicDocumentaryBroadcasterEngine:
    """
    Rhythmic Documentary Broadcaster Synthesizer & Timeline Sequencer.
    Aligns spoken thoughts to musical bars and beats.
    """

    def __init__(
        self,
        grid: Optional[RhythmicGrid] = None,
        use_f5_neural: bool = True,
        device: str = "mps",
        persona_name: str = "documentary_broadcaster",
    ):
        self.grid = grid or RhythmicGrid(bpm=90.0, sample_rate=SAMPLE_RATE)
        self.use_f5_neural = use_f5_neural
        self.device = device
        self.persona_name = persona_name
        self._f5_engine = None

    def _get_f5_tts(self):
        if self._f5_engine is None and self.use_f5_neural:
            try:
                from voicefi.tts.f5_tts import F5TTS

                if F5TTS.is_available():
                    self._f5_engine = F5TTS(device=self.device)
                    self._f5_engine.persona_name = self.persona_name
            except Exception as e:
                print(
                    f"[RhythmicDocumentaryBroadcaster] F5TTS init notice: {e}. Falling back to EdgeTTS."
                )
                self._f5_engine = None
        return self._f5_engine

    def synthesize_clause(self, text: str, output_wav: Path) -> bool:
        """
        Synthesizes a single thought clause with documentary broadcaster prosody
        (no exclamation marks, deliberate breathing ellipses, BBC silk mastering).
        """
        clean_text = text.replace("!", "...").strip()
        f5 = self._get_f5_tts()

        temp_raw = output_wav.with_suffix(".raw.wav")

        if f5 is not None:
            try:
                f5.speed = 0.92
                f5.nfe_step = 32
                ok = f5.speak_to_file(clean_text, temp_raw)
                if ok and temp_raw.is_file() and temp_raw.stat().st_size > 500:
                    apply_broadcast_silk_mastering(temp_raw, output_wav)
                    if temp_raw.is_file():
                        temp_raw.unlink(missing_ok=True)
                    return True
            except Exception as ex:
                print(f"[RhythmicDocumentaryBroadcaster] Neural synthesis fallback: {ex}")

        # High-Fidelity EdgeTTS BBC Thomas fallback
        try:
            import asyncio
            import edge_tts

            async def _synth():
                communicate = edge_tts.Communicate(
                    text=clean_text,
                    voice="en-GB-ThomasNeural",
                    rate="-8%",
                    pitch="-2Hz",
                )
                await communicate.save(str(temp_raw))

            asyncio.run(_synth())
            if temp_raw.is_file() and temp_raw.stat().st_size > 500:
                apply_broadcast_silk_mastering(temp_raw, output_wav)
                if temp_raw.is_file():
                    temp_raw.unlink(missing_ok=True)
                return True
        except Exception as e:
            print(f"[RhythmicDocumentaryBroadcaster] EdgeTTS failed: {e}")

        return False

    def build_rhythmic_vocal_track(
        self,
        clauses: List[Dict[str, Any]],
        total_bars: float,
        temp_dir: Optional[Path] = None,
    ) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        """
        Synthesizes an array of rhythmic clauses, positioning each on the grid.
        Each clause is: {"bar": int, "beat": float, "text": str, "label": Optional[str]}

        Returns:
            (vocal_buffer, manifest_with_durations)
        """
        work_dir = temp_dir or Path(tempfile.mkdtemp(prefix="voicefi_rhythmic_doc_"))
        work_dir.mkdir(parents=True, exist_ok=True)

        total_samples = int(self.grid.get_bar_duration(total_bars) * self.grid.sample_rate)
        vocal_track = np.zeros(total_samples, dtype=np.float32)
        manifest = []

        for idx, item in enumerate(clauses):
            bar = item["bar"]
            beat = item.get("beat", 1.0)
            text = item["text"]
            label = item.get("label", f"clause_{idx + 1:02d}")

            stem_path = work_dir / f"{label}.wav"
            print(f'[RhythmicDocumentaryBroadcaster] Synthesizing [{bar}.{beat:.1f}]: "{text}"...')
            success = self.synthesize_clause(text, stem_path)

            if success and stem_path.is_file():
                audio, sr = load_wav_as_float32(stem_path, self.grid.sample_rate)
                audio = apply_edge_micro_fades(audio, sr)

                start_sec = self.grid.bar_beat_to_seconds(bar, beat)
                s_idx = int(start_sec * sr)
                dur_sec = len(audio) / sr

                # Place in master buffer
                end_idx = min(s_idx + len(audio), total_samples)
                actual_len = end_idx - s_idx
                if actual_len > 0:
                    vocal_track[s_idx:end_idx] += audio[:actual_len]

                manifest.append(
                    {
                        "label": label,
                        "bar": bar,
                        "beat": beat,
                        "start_sec": start_sec,
                        "end_sec": start_sec + dur_sec,
                        "duration_sec": dur_sec,
                        "text": text,
                        "stem_path": str(stem_path),
                    }
                )
            else:
                print(
                    f"[RhythmicDocumentaryBroadcaster] ⚠️ Warning: Failed to synthesize clause {idx + 1}"
                )

        return vocal_track, manifest


# Backwards compatibility alias
RhythmicAttenboroughEngine = RhythmicDocumentaryBroadcasterEngine
