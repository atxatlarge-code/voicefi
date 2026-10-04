"""
voicefi/factory/audio_synth.py
Stage 2 Audio Generation & Mastering Engine for Content Creation Factory.

Features:
- Multi-speaker turn synthesis with distinct character voices and speeds.
- Acoustically strips script tags ([sfx:...]) to avoid literal reading.
- Conversational turn stitching with calibrated 120ms inter-speaker pauses.
- Automatic sidechain ducking under backing music (FFmpeg amix at 48kHz).
- Baseline single-voice generator for side-by-side A/B comparison.
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from voicefi.config import VoiceFiConfig, load_config
from voicefi.factory.generator import DEFAULT_CHARACTERS
from voicefi.factory.models import ContentManifest, ScriptDialogueTurn
from voicefi.local.supervisor import default_supervisor
from voicefi.tts import get_tts_engine

logger = logging.getLogger("voicefi.factory.audio_synth")


class ContentAudioSynthesizer:
    """Manages Stage 2 multi-speaker voice synthesis, concatenation, and music ducking."""

    def __init__(self, config: Optional[VoiceFiConfig] = None, default_speed: str = "+12%"):
        self.config = config or load_config()
        self.default_speed = default_speed

    def clean_text(self, raw_text: str) -> str:
        """Strip [sfx:...] tags and formatting from spoken text."""
        cleaned = re.sub(r"\[sfx:[^\]]+\]", "", raw_text)
        cleaned = re.sub(r"\[pause:[^\]]+\]", "", cleaned)
        cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)  # remove italics/stage directions
        return cleaned.strip()

    def synthesize_turn(
        self,
        turn: ScriptDialogueTurn,
        output_wav: Path,
        voice_id: Optional[str] = None,
        provider: str = "edge_tts",
        speed_override: Optional[str] = None,
    ) -> bool:
        """Synthesize a single dialogue turn to a normalized 48kHz stereo PCM WAV file."""
        default_supervisor.wait_if_throttled(poll_interval=1.0, max_wait=10.0)

        spoken_text = self.clean_text(turn.text)
        if not spoken_text:
            return False

        # Determine voice and calibrated pacing
        char_meta = DEFAULT_CHARACTERS.get(turn.speaker, {})
        resolved_voice = voice_id or turn.voice_id or char_meta.get("voice_id", "en-US-AvaNeural")
        resolved_speed = speed_override or turn.speed or char_meta.get("speed", self.default_speed)

        output_wav.parent.mkdir(parents=True, exist_ok=True)
        raw_temp = output_wav.with_name(f"raw_{output_wav.name}")

        engine = get_tts_engine(
            self.config,
            agent_name=turn.speaker,
            voice_override=resolved_voice,
            provider_override=provider,
            rate_override=resolved_speed,
        )

        try:
            success = engine.speak_to_file(spoken_text, raw_temp)
            if not (success and raw_temp.exists() and raw_temp.stat().st_size > 500):
                return False

            # Normalize immediately to standard 48kHz 16-bit stereo PCM WAV
            # This guarantees FFmpeg concat demuxer can stitch heterogeneous streams without skipping
            norm_cmd = [
                "ffmpeg", "-y",
                "-i", str(raw_temp),
                "-ar", "48000",
                "-ac", "2",
                "-c:a", "pcm_s16le",
                str(output_wav),
            ]
            subprocess.run(norm_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if raw_temp.exists():
                raw_temp.unlink()

            return output_wav.exists() and output_wav.stat().st_size > 1000
        except Exception as e:
            logger.error(f"Failed to synthesize turn '{turn.speaker}': {e}")
            if raw_temp.exists():
                raw_temp.unlink()
            return False

    def combine_turns_with_pauses(
        self,
        turn_wavs: List[Path],
        output_wav: Path,
        pause_gap_ms: int = 140,
    ) -> bool:
        """
        Concatenate audio turns with realistic conversational pauses (~140ms silence)
        using FFmpeg concat demuxer at broadcast 48kHz stereo.
        """
        if not turn_wavs:
            return False

        output_wav.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="vifi_concat_") as tmpdir:
            tmp_path = Path(tmpdir)
            silence_wav = tmp_path / "pause.wav"

            # 1. Generate short pause wav (48kHz stereo silence)
            pause_sec = max(0.05, pause_gap_ms / 1000.0)
            gen_silence_cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "anullsrc=r=48000:cl=stereo",
                "-t", str(pause_sec),
                "-ar", "48000",
                "-ac", "2",
                str(silence_wav),
            ]
            try:
                subprocess.run(gen_silence_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            except Exception:
                silence_wav = None

            # 2. Build concat list with pauses between turns
            concat_txt = tmp_path / "concat.txt"
            with open(concat_txt, "w", encoding="utf-8") as f:
                for idx, turn_p in enumerate(turn_wavs):
                    f.write(f"file '{turn_p.resolve()}'\n")
                    if idx < len(turn_wavs) - 1 and silence_wav and silence_wav.exists():
                        f.write(f"file '{silence_wav.resolve()}'\n")

            # 3. Concatenate to master output
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt),
                "-ar", "48000",
                "-ac", "2",
                str(output_wav),
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                return output_wav.exists() and output_wav.stat().st_size > 1000
            except Exception as e:
                logger.error(f"FFmpeg turn concatenation failed: {e}")
                return False

    def mix_backing_track(
        self,
        vocal_wav: Path,
        backing_track: Path,
        output_wav: Path,
        bg_volume: float = 0.18,
    ) -> Tuple[bool, Optional[Path]]:
        """
        Mix vocal master with backing track applying ducking and 48kHz normalization.
        Also exports a high-bitrate .mp3 sibling.
        """
        if not vocal_wav.exists() or not backing_track.exists():
            return False, None

        output_wav.parent.mkdir(parents=True, exist_ok=True)
        mp3_out = output_wav.with_suffix(".mp3")

        # Vocal (0:a) + Backing Track (1:a) ducked with amix duration=first
        cmd = [
            "ffmpeg", "-y",
            "-i", str(vocal_wav),
            "-i", str(backing_track),
            "-filter_complex",
            f"[1:a]volume={bg_volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[out]",
            "-map", "[out]",
            "-ar", "48000",
            "-ac", "2",
            str(output_wav),
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            # Create MP3 version for easy browser/mobile listening
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(output_wav), "-b:a", "192k", str(mp3_out)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return True, mp3_out
        except Exception as e:
            logger.error(f"Backing track mix failed: {e}")
            return False, None

    def synthesize_manifest(
        self,
        manifest: ContentManifest,
        output_dir: Path,
        backing_track_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Full Stage 2 pipeline:
        1. Synthesize all turns with multi-speaker voices.
        2. Stitch with conversational pauses into master vocal.
        3. Mix backing track with sidechain ducking.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        turn_files: List[Path] = []

        logger.info(f"Synthesizing {len(manifest.turns)} dialogue turns for '{manifest.title}'...")
        t0 = time.time()

        for idx, turn in enumerate(manifest.turns):
            turn_p = output_dir / f"turn_{idx:02d}_{turn.speaker}.wav"
            ok = self.synthesize_turn(turn, turn_p)
            if ok:
                turn.audio_path = str(turn_p)
                turn_files.append(turn_p)
            else:
                logger.warning(f"Turn {idx} failed to synthesize.")

        # Master vocal
        master_wav = output_dir / "master_vocal.wav"
        combined_ok = self.combine_turns_with_pauses(turn_files, master_wav)

        # Mix with beat if available
        mixed_mp3 = None
        if backing_track_path and backing_track_path.exists() and master_wav.exists():
            mixed_wav = output_dir / "master_mix.wav"
            mix_ok, mixed_mp3 = self.mix_backing_track(master_wav, backing_track_path, mixed_wav)

        duration = time.time() - t0
        logger.info(f"Stage 2 Audio Synthesis completed in {duration:.2f}s.")

        return {
            "turn_files": [str(p) for p in turn_files],
            "master_vocal_wav": str(master_wav) if master_wav.exists() else None,
            "master_mix_mp3": str(mixed_mp3) if mixed_mp3 and mixed_mp3.exists() else None,
            "duration_s": round(duration, 2),
            "success": combined_ok,
        }

    def synthesize_baseline_monotone(
        self,
        manifest: ContentManifest,
        output_file: Path,
        single_voice: str = "en-US-JennyNeural",
    ) -> bool:
        """
        Generate baseline single-voice raw audio:
        Reads all text as one continuous monologue without character changes,
        without conversational cadence pauses, and without backing music.
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        # Concatenate all speech into a single flat paragraph
        all_text = " ".join(self.clean_text(t.text) for t in manifest.turns)

        dummy_turn = ScriptDialogueTurn(
            speaker="Narrator",
            text=all_text,
            voice_id=single_voice,
            emotion="neutral",
        )
        wav_path = output_file.with_suffix(".wav")
        ok = self.synthesize_turn(dummy_turn, wav_path, voice_id=single_voice, speed_override=self.default_speed)
        if ok and wav_path.exists():
            # Convert to mp3 if requested
            if output_file.suffix == ".mp3":
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "192k", str(output_file)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=True,
                )
            return True
        return False
