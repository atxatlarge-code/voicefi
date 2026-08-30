"""
Audio DSP Effects Engine & Voice Transformer for VoiceFi.
Provides studio voice transformations (Booming Radio Announcer, Studio Podcast,
Stadium Announcer, Vintage AM Radio, Cyber Robot, Monster, Chipmunk, etc.),
sound effect layering, background music mixing, and waveform extraction.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

import numpy as np

# Ensure standard system and Homebrew binary search paths are available
_EXTRA_PATHS = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin")]
_CURRENT_PATHS = os.environ.get("PATH", "").split(os.pathsep)
for _p in _EXTRA_PATHS:
    if _p not in _CURRENT_PATHS and os.path.isdir(_p):
        _CURRENT_PATHS.insert(0, _p)
os.environ["PATH"] = os.pathsep.join(_CURRENT_PATHS)


def _get_bin(binary_name: str) -> str:
    """Resolve executable path (ffmpeg, ffprobe) with Homebrew and system fallback."""
    found = shutil.which(binary_name)
    if found:
        return found
    for candidate in [
        f"/opt/homebrew/bin/{binary_name}",
        f"/usr/local/bin/{binary_name}",
        f"{Path.home()}/.local/bin/{binary_name}",
        f"/usr/bin/{binary_name}",
        f"/bin/{binary_name}"
    ]:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return binary_name


# Presets definition with ffmpeg audio filter chains
FX_PRESETS: Dict[str, Dict[str, Any]] = {
    "radio_announcer": {
        "id": "radio_announcer",
        "name": "Booming Radio Announcer",
        "icon": "📻",
        "description": "Deep proximity bass boost, warm mid presence, broadcast limiter and punchy radio compression.",
        "category": "broadcast",
        "filter": (
            "highpass=f=45,"
            "equalizer=f=85:width_type=o:width=1.5:g=9.0,"
            "equalizer=f=220:width_type=o:width=1.2:g=3.5,"
            "equalizer=f=650:width_type=o:width=1.0:g=-2.5,"
            "equalizer=f=4500:width_type=o:width=1.5:g=4.5,"
            "highshelf=f=10000:g=3.0,"
            "acompressor=threshold=-20dB:ratio=6:attack=8:release=100:makeup=7dB:knee=3dB,"
            "alimiter=limit=-0.5dB:attack=5:release=50,"
            "volume=1.15"
        )
    },
    "studio_podcast": {
        "id": "studio_podcast",
        "name": "Studio Podcast Master",
        "icon": "🎙️",
        "description": "Pristine acoustic vocal warmth, smooth opto-compression, de-essing, and proximity depth.",
        "category": "broadcast",
        "filter": (
            "highpass=f=60,"
            "equalizer=f=120:width_type=o:width=1.2:g=3.5,"
            "equalizer=f=3000:width_type=o:width=1.5:g=2.5,"
            "equalizer=f=6800:width_type=q:width=3.0:g=-4.0,"
            "highshelf=f=12000:g=2.0,"
            "acompressor=threshold=-16dB:ratio=3.5:attack=15:release=180:makeup=4dB:knee=4dB,"
            "alimiter=limit=-1.0dB:attack=5:release=50"
        )
    },
    "stadium_announcer": {
        "id": "stadium_announcer",
        "name": "Stadium Arena Announcer",
        "icon": "🏟️",
        "description": "Massive booming resonance with slapback echo and giant sports arena acoustics.",
        "category": "spatial",
        "filter": (
            "highpass=f=50,"
            "equalizer=f=95:width_type=o:width=1.5:g=7.5,"
            "equalizer=f=3500:width_type=o:width=1.5:g=4.0,"
            "acompressor=threshold=-18dB:ratio=5:attack=10:release=120:makeup=6dB,"
            "aecho=0.8:0.88:70|190:0.42|0.25,"
            "alimiter=limit=-0.5dB"
        )
    },
    "am_radio": {
        "id": "am_radio",
        "name": "Vintage AM Radio / Walkie",
        "icon": "📻",
        "description": "Narrow bandpass telephone resonance (400Hz-3.4kHz), analog grit, and heavy squelch compression.",
        "category": "vintage",
        "filter": (
            "highpass=f=400,"
            "lowpass=f=3400,"
            "equalizer=f=1200:width_type=o:width=1.0:g=4.0,"
            "equalizer=f=2400:width_type=o:width=1.2:g=3.0,"
            "acompressor=threshold=-24dB:ratio=8:attack=4:release=60:makeup=9dB,"
            "volume=1.35"
        )
    },
    "cyber_robot": {
        "id": "cyber_robot",
        "name": "Cyber Robot / Vocoder",
        "icon": "🤖",
        "description": "Robotic metallic ring modulation, chorus modulation, and cybernetic resonance.",
        "category": "creative",
        "filter": (
            "flanger=delay=3:depth=2:regen=55:width=80:speed=0.6,"
            "tremolo=f=45:d=0.65,"
            "equalizer=f=2000:width_type=q:width=4.0:g=6.0,"
            "equalizer=f=500:width_type=q:width=3.0:g=4.0,"
            "acompressor=threshold=-16dB:ratio=4:attack=10:release=100:makeup=5dB"
        )
    },
    "deep_monster": {
        "id": "deep_monster",
        "name": "Deep Titan / Monster",
        "icon": "👹",
        "description": "Sub-octave downward pitch transpose, thunderous bass presence, and dark chamber reverb.",
        "category": "creative",
        "filter": (
            "asetrate=44100*0.82,"
            "atempo=1/0.82,"
            "equalizer=f=80:width_type=o:width=1.5:g=10.0,"
            "equalizer=f=180:width_type=o:width=1.2:g=5.0,"
            "aecho=0.8:0.75:120:0.3,"
            "acompressor=threshold=-20dB:ratio=5:attack=12:release=140:makeup=6dB,"
            "alimiter=limit=-0.8dB"
        )
    },
    "helium_chipmunk": {
        "id": "helium_chipmunk",
        "name": "Helium / Chipmunk",
        "icon": "🐿️",
        "description": "Upward pitch transpose (+5 semitones) with ultra-bright treble sparkle.",
        "category": "creative",
        "filter": (
            "asetrate=44100*1.38,"
            "atempo=1/1.38,"
            "highshelf=f=6000:g=4.0,"
            "highpass=f=200,"
            "acompressor=threshold=-15dB:ratio=3:attack=10:release=100:makeup=3dB"
        )
    },
    "ethereal_space": {
        "id": "ethereal_space",
        "name": "Ethereal Dream Space",
        "icon": "🌌",
        "description": "Lush shimmering chorus, wide ping-pong stereo delay, and expansive ambient atmosphere.",
        "category": "spatial",
        "filter": (
            "chorus=0.7:0.9:55:0.4:0.25:2,"
            "aecho=0.8:0.8:280|560:0.32|0.18,"
            "highshelf=f=8000:g=3.0,"
            "acompressor=threshold=-16dB:ratio=3:attack=20:release=200:makeup=3dB"
        )
    }
}


class VoiceFXEngine:
    """High-fidelity Audio DSP engine using FFmpeg filtergraphs."""

    @staticmethod
    def list_presets() -> List[Dict[str, Any]]:
        """Return list of available voice FX presets."""
        return [
            {
                "id": p["id"],
                "name": p["name"],
                "icon": p["icon"],
                "description": p["description"],
                "category": p["category"]
            }
            for p in FX_PRESETS.values()
        ]

    @staticmethod
    def get_audio_info(file_path: Union[str, Path]) -> Dict[str, Any]:
        """Extract duration, format, sample rate, channels, and waveform peak data from audio file."""
        p = Path(file_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Audio file not found: {p}")

        # Run ffprobe for metadata
        cmd = [
            _get_bin("ffprobe"), "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(p)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        meta = {}
        if res.returncode == 0 and res.stdout:
            try:
                meta = json.loads(res.stdout)
            except Exception:
                pass

        format_info = meta.get("format", {})
        duration = float(format_info.get("duration", 0.0))
        size_bytes = int(format_info.get("size", p.stat().st_size))
        bit_rate = int(format_info.get("bit_rate", 0))

        audio_stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), {})
        sample_rate = int(audio_stream.get("sample_rate", 44100))
        channels = int(audio_stream.get("channels", 2))
        codec_name = audio_stream.get("codec_name", p.suffix.lstrip("."))

        # Generate normalized waveform peaks (100 bars) for UI visualizer
        peaks = VoiceFXEngine._extract_waveform_peaks(p, num_points=100)

        return {
            "file_path": str(p),
            "filename": p.name,
            "duration": round(duration, 3),
            "size_bytes": size_bytes,
            "size_formatted": f"{size_bytes / (1024 * 1024):.2f} MB" if size_bytes > 1024 * 1024 else f"{size_bytes / 1024:.1f} KB",
            "sample_rate": sample_rate,
            "channels": channels,
            "codec": codec_name,
            "peaks": peaks
        }

    @staticmethod
    def _extract_waveform_peaks(file_path: Path, num_points: int = 100) -> List[float]:
        """Extract RMS / peak envelope points using ffmpeg raw PCM decode."""
        try:
            cmd = [
                _get_bin("ffmpeg"), "-v", "quiet",
                "-i", str(file_path),
                "-f", "s16le",
                "-ac", "1",
                "-ar", "8000",
                "-"
            ]
            proc = subprocess.run(cmd, capture_output=True)
            if proc.returncode != 0 or len(proc.stdout) < 100:
                return [0.1] * num_points

            samples = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
            if len(samples) == 0:
                return [0.0] * num_points

            chunk_size = max(1, len(samples) // num_points)
            peaks = []
            for i in range(num_points):
                start = i * chunk_size
                end = min(len(samples), (i + 1) * chunk_size)
                if start >= len(samples):
                    peaks.append(0.0)
                else:
                    chunk = samples[start:end]
                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    peaks.append(round(min(1.0, rms * 3.5), 3))
            return peaks
        except Exception:
            return [0.2] * num_points

    @staticmethod
    def trim_audio(
        input_audio: Union[str, Path],
        output_audio: Union[str, Path],
        start_sec: float = 0.0,
        end_sec: Optional[float] = None,
        fade_edges_sec: float = 0.05
    ) -> Path:
        """
        Trim audio between start_sec and end_sec with optional boundary de-clicking fades.
        """
        in_p = Path(input_audio).resolve()
        out_p = Path(output_audio).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        if not in_p.is_file():
            raise FileNotFoundError(f"Input audio file not found: {in_p}")

        info = VoiceFXEngine.get_audio_info(in_p)
        total_dur = info["duration"]
        start = max(0.0, float(start_sec))
        end = min(total_dur, float(end_sec)) if end_sec is not None and float(end_sec) > 0 else total_dur

        if end <= start:
            raise ValueError(f"Invalid trim range: start ({start:.2f}s) must be less than end ({end:.2f}s)")

        trimmed_dur = end - start

        # Construct filter with fades to prevent clicks/pops
        filters = []
        if fade_edges_sec > 0 and trimmed_dur > (fade_edges_sec * 2):
            fade_in = f"afade=t=in:ss=0:d={fade_edges_sec:.3f}"
            fade_out = f"afade=t=out:st={trimmed_dur - fade_edges_sec:.3f}:d={fade_edges_sec:.3f}"
            filters.append(f"{fade_in},{fade_out}")

        cmd = [_get_bin("ffmpeg"), "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(in_p)]
        if filters:
            cmd.extend(["-af", ",".join(filters)])

        # Audio encoding quality
        ext = out_p.suffix.lower()
        if ext == ".mp3":
            cmd.extend(["-c:a", "libmp3lame", "-b:a", "256k"])
        elif ext in (".m4a", ".aac"):
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        elif ext == ".wav":
            cmd.extend(["-c:a", "pcm_s16le", "-ar", "44100"])

        cmd.append(str(out_p))

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFmpeg trim error: {res.stderr}")

        return out_p

    @staticmethod
    def build_custom_filter(
        pitch_semitones: float = 0.0,
        bass_boost_db: float = 0.0,
        treble_boost_db: float = 0.0,
        compression: float = 0.0,
        reverb: float = 0.0,
        volume_gain: float = 1.0,
    ) -> str:
        """Construct an FFmpeg audio filter chain from custom parameter sliders."""
        filters = []

        # 1. Pitch shift (asetrate + atempo)
        if abs(pitch_semitones) > 0.01:
            ratio = 2.0 ** (pitch_semitones / 12.0)
            target_rate = int(44100 * ratio)
            tempo = 1.0 / ratio
            filters.append(f"asetrate={target_rate}")
            # FFmpeg atempo requires 0.5 <= tempo <= 2.0
            if tempo < 0.5:
                filters.append("atempo=0.5,atempo=" + str(tempo / 0.5))
            elif tempo > 2.0:
                filters.append("atempo=2.0,atempo=" + str(tempo / 2.0))
            else:
                filters.append(f"atempo={tempo:.4f}")
            filters.append("aresample=44100")

        # 2. Bass Boost
        if abs(bass_boost_db) > 0.1:
            filters.append(f"equalizer=f=85:width_type=o:width=1.5:g={bass_boost_db:.1f}")
            if bass_boost_db > 3.0:
                filters.append(f"equalizer=f=200:width_type=o:width=1.2:g={(bass_boost_db * 0.4):.1f}")

        # 3. Treble / Presence Boost
        if abs(treble_boost_db) > 0.1:
            filters.append(f"equalizer=f=4500:width_type=o:width=1.5:g={treble_boost_db:.1f}")
            filters.append(f"highshelf=f=10000:g={(treble_boost_db * 0.7):.1f}")

        # 4. Compression (0.0 to 1.0)
        if compression > 0.05:
            thresh_db = -12.0 - (compression * 16.0) # -12dB to -28dB
            ratio = 2.0 + (compression * 6.0)       # 2:1 to 8:1
            makeup_db = compression * 8.0           # 0 to 8dB
            filters.append(f"acompressor=threshold={thresh_db:.1f}dB:ratio={ratio:.1f}:attack=8:release=120:makeup={makeup_db:.1f}dB:knee=3dB")

        # 5. Reverb / Echo (0.0 to 1.0)
        if reverb > 0.05:
            echo_in = 0.8
            echo_out = 0.8 * (1.0 - reverb * 0.2)
            delays = f"{int(60 + reverb * 140)}|{int(120 + reverb * 300)}"
            decays = f"{0.2 + reverb * 0.3:.2f}|{0.1 + reverb * 0.2:.2f}"
            filters.append(f"aecho={echo_in}:{echo_out}:{delays}:{decays}")

        # 6. Volume Gain & Limiter
        if abs(volume_gain - 1.0) > 0.02:
            filters.append(f"volume={volume_gain:.2f}")

        filters.append("alimiter=limit=-0.5dB:attack=5:release=50")
        return ",".join(filters)

    @classmethod
    def apply_effect(
        cls,
        input_audio: Union[str, Path],
        output_audio: Union[str, Path],
        preset: Optional[str] = "radio_announcer",
        custom_params: Optional[Dict[str, float]] = None,
        sfx_cues: Optional[List[Dict[str, Any]]] = None,
        bg_music_path: Optional[Union[str, Path]] = None,
        bg_music_volume: float = 0.15,
        normalize_loudness: bool = True,
    ) -> Path:
        """
        Apply voice transformation effect, overlay sound effects, and export to master audio.
        Supports .wav, .mp3, .m4a.
        """
        in_path = Path(input_audio).resolve()
        out_path = Path(output_audio).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not in_path.is_file():
            raise FileNotFoundError(f"Input audio file not found: {in_path}")

        # Determine filter string
        filter_str = ""
        if custom_params:
            filter_str = cls.build_custom_filter(
                pitch_semitones=custom_params.get("pitch_semitones", 0.0),
                bass_boost_db=custom_params.get("bass_boost_db", 0.0),
                treble_boost_db=custom_params.get("treble_boost_db", 0.0),
                compression=custom_params.get("compression", 0.0),
                reverb=custom_params.get("reverb", 0.0),
                volume_gain=custom_params.get("volume_gain", 1.0),
            )
        elif preset and preset in FX_PRESETS:
            filter_str = FX_PRESETS[preset]["filter"]
        else:
            filter_str = "volume=1.0"

        # Check if we need complex filtergraph for SFX overlays or background music
        has_sfx = bool(sfx_cues and len(sfx_cues) > 0)
        has_bg_music = bool(bg_music_path and Path(bg_music_path).is_file())

        tmp_dir = Path(tempfile.mkdtemp(prefix="vifi_fx_"))

        try:
            # 1. Apply primary voice effect to intermediate voice file
            fx_voice_wav = tmp_dir / "voice_fx.wav"
            cmd_voice = [
                _get_bin("ffmpeg"), "-y",
                "-i", str(in_path),
                "-af", filter_str,
                "-ar", "44100",
                "-ac", "2",
                str(fx_voice_wav)
            ]
            res = subprocess.run(cmd_voice, capture_output=True, text=True)
            if res.returncode != 0 or not fx_voice_wav.is_file():
                raise RuntimeError(f"FFmpeg voice FX failed: {res.stderr}")

            # 2. If no overlays, encode to final output format
            if not has_sfx and not has_bg_music:
                cls._encode_final_audio(fx_voice_wav, out_path, normalize_loudness=normalize_loudness)
                return out_path

            # 3. Handle SFX and background music mixing
            mixed_wav = tmp_dir / "mixed_master.wav"
            cls._mix_overlays(
                fx_voice_wav=fx_voice_wav,
                output_wav=mixed_wav,
                sfx_cues=sfx_cues or [],
                bg_music_path=bg_music_path,
                bg_music_volume=bg_music_volume
            )

            # 4. Final encode with loudness mastering
            cls._encode_final_audio(mixed_wav, out_path, normalize_loudness=normalize_loudness)
            return out_path

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @classmethod
    def _mix_overlays(
        cls,
        fx_voice_wav: Path,
        output_wav: Path,
        sfx_cues: List[Dict[str, Any]],
        bg_music_path: Optional[Union[str, Path]],
        bg_music_volume: float = 0.15
    ):
        """Mix voice track with timed sound effects and ducked background music."""
        from voicefi.audio.sfx import get_sfx_path

        inputs = ["-i", str(fx_voice_wav)]
        filter_complex = []
        input_count = 1

        # Process SFX cues: [{"name": "drum_smash", "start_sec": 4.5, "volume": 0.8}]
        sfx_labels = []
        for cue in sfx_cues:
            sfx_name = cue.get("name", "drum_smash")
            start_sec = max(0.0, float(cue.get("start_sec", 0.0)))
            vol = max(0.1, min(2.0, float(cue.get("volume", 0.9))))
            
            sfx_file = get_sfx_path(sfx_name)
            if sfx_file and sfx_file.is_file():
                inputs.extend(["-i", str(sfx_file)])
                delay_ms = int(start_sec * 1000)
                lbl = f"[sfx_{input_count}]"
                filter_complex.append(f"[{input_count}:a]volume={vol:.2f},adelay={delay_ms}|{delay_ms}{lbl}")
                sfx_labels.append(lbl)
                input_count += 1

        # Process Background Music if provided
        bg_label = None
        if bg_music_path and Path(bg_music_path).is_file():
            inputs.extend(["-i", str(bg_music_path)])
            bg_label = f"[bg_{input_count}]"
            filter_complex.append(f"[{input_count}:a]volume={bg_music_volume:.3f}{bg_label}")
            input_count += 1

        # Combine all audio streams with amix
        mix_inputs = ["[0:a]"] + sfx_labels
        if bg_label:
            mix_inputs.append(bg_label)

        mix_filter = "".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=2[aout]"
        filter_complex.append(mix_filter)

        cmd = [
            _get_bin("ffmpeg"), "-y",
            *inputs,
            "-filter_complex", ";".join(filter_complex),
            "-map", "[aout]",
            "-ar", "44100",
            "-ac", "2",
            str(output_wav)
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not output_wav.is_file():
            # Fallback to pure voice file if complex mixing encountered error
            shutil.copy(fx_voice_wav, output_wav)

    @classmethod
    def _encode_final_audio(cls, in_wav: Path, out_path: Path, normalize_loudness: bool = True):
        """Encode to target format with optional EBU R128 loudness normalization."""
        af_opts = []
        if normalize_loudness:
            af_opts.append("loudnorm=I=-16:TP=-1.5:LRA=11")

        cmd = [_get_bin("ffmpeg"), "-y", "-i", str(in_wav)]
        if af_opts:
            cmd.extend(["-af", ",".join(af_opts)])

        ext = out_path.suffix.lower()
        if ext == ".mp3":
            cmd.extend(["-c:a", "libmp3lame", "-b:a", "256k"])
        elif ext in (".m4a", ".aac"):
            cmd.extend(["-c:a", "aac", "-b:a", "256k"])
        elif ext == ".ogg":
            cmd.extend(["-c:a", "libvorbis", "-q:a", "6"])
        elif ext == ".flac":
            cmd.extend(["-c:a", "flac"])
        else: # .wav
            cmd.extend(["-c:a", "pcm_s16le", "-ar", "44100"])

        cmd.append(str(out_path))
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 or not out_path.is_file():
            raise RuntimeError(f"FFmpeg encoding failed for {out_path}: {res.stderr}")
