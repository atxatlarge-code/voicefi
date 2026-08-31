"""
Speed Talking Audio Engine & DSP Acceleration for VoiceFi.
Provides formant-preserving speed acceleration (1.25x - 3.0x), smart micro-pause compression,
dynamic speed ramping, and developer time-saved analytics.
"""

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union


# Standard speed talking preset definitions
SPEED_PRESETS: Dict[str, Dict[str, Any]] = {
    "normal": {
        "id": "normal",
        "name": "Normal Baseline",
        "multiplier": 1.0,
        "wpm": 200,
        "edge_rate": "+0%",
        "icon": "🟢",
        "description": "Standard natural conversational speed (200 WPM / 1.0x).",
    },
    "breezy": {
        "id": "breezy",
        "name": "Breezy Pace",
        "multiplier": 1.25,
        "wpm": 250,
        "edge_rate": "+25%",
        "icon": "🍃",
        "description": "Light 1.25x acceleration (250 WPM) — effortless listening with zero cognitive load.",
    },
    "fast": {
        "id": "fast",
        "name": "Developer Fast",
        "multiplier": 1.5,
        "wpm": 300,
        "edge_rate": "+50%",
        "icon": "⚡",
        "description": "The developer sweet spot (300 WPM / 1.5x) — saves 33% time with 100% clarity.",
    },
    "turbo": {
        "id": "turbo",
        "name": "Turbo Velocity",
        "multiplier": 1.75,
        "wpm": 350,
        "edge_rate": "+75%",
        "icon": "🚀",
        "description": "High velocity (350 WPM / 1.75x) for rapid turn notifications and quick summaries.",
    },
    "sonic": {
        "id": "sonic",
        "name": "Sonic / Auctioneer",
        "multiplier": 2.0,
        "wpm": 400,
        "edge_rate": "+100%",
        "icon": "🏎️",
        "description": "2.0x double speed (400 WPM) — cuts turn listening duration in half.",
    },
    "auctioneer": {
        "id": "auctioneer",
        "name": "Auctioneer",
        "multiplier": 2.0,
        "wpm": 400,
        "edge_rate": "+100%",
        "icon": "🗣️",
        "description": "Rapid-fire 2.0x cadence (400 WPM) with compressed inter-sentence pauses.",
    },
    "warp": {
        "id": "warp",
        "name": "Warp Speed",
        "multiplier": 2.5,
        "wpm": 500,
        "edge_rate": "+150%",
        "icon": "🌌",
        "description": "Ultra-fast 2.5x stream (500 WPM) for high-bandwidth soundbite absorption.",
    },
    "ludicrous": {
        "id": "ludicrous",
        "name": "Ludicrous Speed",
        "multiplier": 2.5,
        "wpm": 500,
        "edge_rate": "+150%",
        "icon": "💥",
        "description": "Ludicrous 2.5x speed (500 WPM) for speed listening enthusiasts.",
    },
    "supersonic": {
        "id": "supersonic",
        "name": "Supersonic",
        "multiplier": 3.0,
        "wpm": 600,
        "edge_rate": "+200%",
        "icon": "🌠",
        "description": "Extreme 3.0x velocity (600 WPM) with aggressive clarity boost.",
    },
}


def _get_ffmpeg_bin() -> str:
    """Find ffmpeg binary from PATH or common macOS Homebrew locations."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        str(Path.home() / ".local/bin/ffmpeg"),
        "/usr/bin/ffmpeg",
    ]:
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return "ffmpeg"


def resolve_speed_multiplier(val: Any) -> float:
    """
    Parse any input format into a normalized float speed multiplier (e.g. 1.0 to 4.0).
    Supports:
      - Named presets: 'fast' -> 1.5, 'turbo' -> 1.75, 'sonic' -> 2.0, 'warp' -> 2.5
      - Multiplier strings: '1.5x', '1.5X', '1.5' -> 1.5
      - Percentage strings: '150%', '175%' -> 1.5, 1.75
      - Percentage offsets: '+50%', '+100%' -> 1.5, 2.0
      - WPM values: '300wpm', '300', 300 -> 1.5 (baseline 200 WPM)
      - Raw floats / ints: 1.5, 2 -> 1.5, 2.0
    """
    if val is None:
        return 1.0

    if isinstance(val, (int, float)):
        # If passed as WPM value > 20 (e.g. 150 - 600)
        if val > 20:
            if val <= 100:
                # Percentage of 100 (e.g. 75 -> 0.75, 100 -> 1.0)
                return max(min(round(float(val) / 100.0, 2), 4.0), 0.5)
            # WPM (200 WPM = 1.0x)
            return max(min(round(float(val) / 200.0, 2), 4.0), 0.5)
        # Direct multiplier (0.5 to 4.0)
        return max(min(round(float(val), 2), 4.0), 0.5)

    val_str = str(val).strip().lower()
    if not val_str:
        return 1.0

    # 1. Preset names
    if val_str in SPEED_PRESETS:
        return SPEED_PRESETS[val_str]["multiplier"]

    # Common aliases
    preset_aliases = {
        "standard": 1.0,
        "default": 1.0,
        "medium": 1.25,
        "moderate": 1.25,
        "high": 1.75,
        "double": 2.0,
        "triple": 3.0,
        "max": 3.0,
    }
    if val_str in preset_aliases:
        return preset_aliases[val_str]

    # 2. Suffix 'x' (e.g. '1.5x', '2x')
    if val_str.endswith("x"):
        try:
            return max(min(round(float(val_str[:-1].strip()), 2), 4.0), 0.5)
        except ValueError:
            pass

    # 3. Suffix 'wpm' (e.g. '300wpm')
    if val_str.endswith("wpm"):
        try:
            wpm = float(val_str[:-3].strip())
            return max(min(round(wpm / 200.0, 2), 4.0), 0.5)
        except ValueError:
            pass

    # 4. Suffix '%' (e.g. '150%', '+50%', '-25%')
    if val_str.endswith("%"):
        try:
            num = float(val_str[:-1].strip())
            if val_str.startswith(("+", "-")):
                # Offset percentage: +50% -> 1.5, +100% -> 2.0, -25% -> 0.75
                return max(min(round(1.0 + (num / 100.0), 2), 4.0), 0.5)
            else:
                # Percentage of normal speed: 150% -> 1.5, 75% -> 0.75
                return max(min(round(num / 100.0, 2), 4.0), 0.5)
        except ValueError:
            pass

    # 5. Raw number as string
    try:
        num = float(val_str)
        if num > 20:
            if num <= 100:
                return max(min(round(num / 100.0, 2), 4.0), 0.5)
            return max(min(round(num / 200.0, 2), 4.0), 0.5)
        return max(min(round(num, 2), 4.0), 0.5)
    except ValueError:
        pass

    return 1.0


def multiplier_to_wpm(multiplier: float) -> int:
    """Convert float speed multiplier to words-per-minute (baseline 200 WPM = 1.0x)."""
    return max(min(int(round(multiplier * 200)), 800), 100)


def multiplier_to_edge_rate(multiplier: float) -> str:
    """Convert float speed multiplier to EdgeTTS rate string (e.g. '+50%', '+100%')."""
    offset_pct = int(round((multiplier - 1.0) * 100))
    return f"{offset_pct:+d}%"


def calculate_time_saved(
    char_count: int,
    multiplier: float,
    baseline_wpm: int = 200,
    chars_per_word: float = 5.0,
) -> Dict[str, float]:
    """
    Calculate estimated listening time saved for a given character count and speed multiplier.
    Returns:
        - baseline_seconds: Estimated duration at 1.0x
        - accelerated_seconds: Estimated duration at target speed
        - seconds_saved: Time saved in seconds
        - time_saved_pct: Percentage of time saved (e.g. 33.3% at 1.5x, 50% at 2.0x)
    """
    words = max(char_count / chars_per_word, 1.0)
    baseline_seconds = (words / baseline_wpm) * 60.0
    mult = max(multiplier, 0.1)
    accelerated_seconds = baseline_seconds / mult
    seconds_saved = max(baseline_seconds - accelerated_seconds, 0.0)
    time_saved_pct = ((baseline_seconds - accelerated_seconds) / baseline_seconds) * 100.0 if baseline_seconds > 0 else 0.0

    return {
        "char_count": char_count,
        "multiplier": multiplier,
        "baseline_seconds": round(baseline_seconds, 2),
        "accelerated_seconds": round(accelerated_seconds, 2),
        "seconds_saved": round(seconds_saved, 2),
        "time_saved_pct": round(time_saved_pct, 1),
    }


def build_atempo_filter_chain(multiplier: float) -> str:
    """
    Construct chained FFmpeg `atempo` filters for arbitrary multipliers.
    FFmpeg's `atempo` filter is strictly bounded to 0.5 <= atempo <= 2.0.
    For speeds > 2.0x or < 0.5x, filters must be chained in series.
    e.g. 3.0x -> 'atempo=2.0,atempo=1.5'
    """
    mult = max(min(multiplier, 4.0), 0.25)
    filters = []

    rem = mult
    while rem > 2.0:
        filters.append("atempo=2.0")
        rem /= 2.0
    while rem < 0.5:
        filters.append("atempo=0.5")
        rem /= 0.5

    filters.append(f"atempo={rem:.4f}")
    return ",".join(filters)


def build_intelligibility_filter_chain(
    speed_multiplier: float,
    enhance_clarity: bool = True,
    compress_pauses: bool = True,
    max_pause_ms: int = 150,
) -> str:
    """
    Build a comprehensive DSP filter chain for high-speed speech:
    1. Micro-pause silence compression (optional)
    2. Formant-preserving time stretching (atempo chain)
    3. Consonant presence boost (3.5kHz peaking EQ) for fast speech clarity
    4. Soft opto-compression and brickwall limiter to prevent clipping
    """
    filter_parts = []

    # 1. Micro-pause silence removal
    if compress_pauses and max_pause_ms > 0:
        pause_s = max(max_pause_ms / 1000.0, 0.05)
        # silenceremove: trim silence durations longer than pause_s to tight cadence
        filter_parts.append(
            f"silenceremove=stop_periods=-1:stop_duration={pause_s:.3f}:stop_threshold=-40dB:leave_silence={pause_s/2.0:.3f}"
        )

    # 2. Time stretch (atempo)
    if abs(speed_multiplier - 1.0) > 0.01:
        filter_parts.append(build_atempo_filter_chain(speed_multiplier))

    # 3. High-frequency presence boost for consonant intelligibility at fast speeds
    if enhance_clarity and speed_multiplier >= 1.25:
        presence_db = min((speed_multiplier - 1.0) * 3.5, 4.5)  # +1.5dB to +4.5dB
        filter_parts.append(
            f"equalizer=f=3500:width_type=o:width=1.5:g={presence_db:.1f}"
        )
        filter_parts.append(
            f"highshelf=f=8000:g={min(presence_db * 0.6, 2.5):.1f}"
        )

    # 4. Level compression and peak limiter
    if speed_multiplier >= 1.25:
        filter_parts.append(
            "acompressor=threshold=-18dB:ratio=3:attack=10:release=80:makeup=2dB"
        )
    filter_parts.append("alimiter=limit=-0.5dB:attack=5:release=50")

    return ",".join(filter_parts)


def accelerate_audio(
    input_path: Union[str, Path],
    output_path: Union[str, Path],
    speed_multiplier: float = 1.5,
    enhance_clarity: bool = True,
    compress_pauses: bool = True,
    max_pause_ms: int = 150,
) -> Path:
    """
    Accelerate an audio file with formant-preserved time stretching and intelligibility enhancement.
    Supports .mp3, .wav, .m4a, .ogg.
    """
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if not in_p.is_file():
        raise FileNotFoundError(f"Input audio file not found: {in_p}")

    # If speed is 1.0 and no pause compression or clarity boost is requested, copy directly
    if (
        abs(speed_multiplier - 1.0) <= 0.01
        and not compress_pauses
        and not enhance_clarity
    ):
        shutil.copyfile(str(in_p), str(out_p))
        return out_p

    filter_str = build_intelligibility_filter_chain(
        speed_multiplier=speed_multiplier,
        enhance_clarity=enhance_clarity,
        compress_pauses=compress_pauses,
        max_pause_ms=max_pause_ms,
    )

    ffmpeg_bin = _get_ffmpeg_bin()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(in_p),
        "-af",
        filter_str,
        "-ar",
        "44100",
        "-b:a",
        "192k",
        str(out_p),
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # If silenceremove fails on exotic audio formats, fallback to pure atempo
        fallback_filter = build_atempo_filter_chain(speed_multiplier)
        cmd_fallback = [
            ffmpeg_bin,
            "-y",
            "-i",
            str(in_p),
            "-af",
            fallback_filter,
            str(out_p),
        ]
        res_fb = subprocess.run(cmd_fallback, capture_output=True, text=True)
        if res_fb.returncode != 0:
            raise RuntimeError(f"FFmpeg audio acceleration failed: {res.stderr or res_fb.stderr}")

    return out_p


def compress_speech_silence(
    input_path: Union[str, Path],
    output_path: Union[str, Path],
    max_pause_ms: int = 150,
) -> Path:
    """Trim dead silence and long micro-pauses from speech audio."""
    return accelerate_audio(
        input_path=input_path,
        output_path=output_path,
        speed_multiplier=1.0,
        enhance_clarity=False,
        compress_pauses=True,
        max_pause_ms=max_pause_ms,
    )


def dynamic_ramp_audio(
    input_path: Union[str, Path],
    output_path: Union[str, Path],
    start_multiplier: float = 1.0,
    target_multiplier: float = 1.75,
    ramp_duration_s: float = 2.5,
) -> Path:
    """
    Create dynamic speed ramping across an audio file:
    Starts playback at `start_multiplier` (e.g. 1.0x) and gradually escalates to
    `target_multiplier` (e.g. 1.75x) over `ramp_duration_s` seconds, letting developer ears adjust smoothly.
    """
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if not in_p.is_file():
        raise FileNotFoundError(f"Input audio file not found: {in_p}")

    # If start and target are virtually identical, run standard acceleration
    if abs(start_multiplier - target_multiplier) <= 0.05:
        return accelerate_audio(
            in_p,
            out_p,
            speed_multiplier=target_multiplier,
            enhance_clarity=True,
        )

    ffmpeg_bin = _get_ffmpeg_bin()

    # Step 1: Probe audio duration
    ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
    probe_cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(in_p),
    ]
    try:
        dur_res = subprocess.run(probe_cmd, capture_output=True, text=True)
        total_duration = float(dur_res.stdout.strip())
    except Exception:
        total_duration = 10.0

    # If audio is shorter than ramp duration, ramp over the first 50%
    actual_ramp_s = min(ramp_duration_s, total_duration * 0.5)

    # Segment into 3 parts: intro ramp 1, intro ramp 2, and target speed body
    mid_multiplier = (start_multiplier + target_multiplier) / 2.0
    seg1_dur = actual_ramp_s * 0.5
    seg2_dur = actual_ramp_s * 0.5

    with tempfile.TemporaryDirectory(prefix="voicefi_ramp_") as tmp_dir:
        tmp_p = Path(tmp_dir)
        seg1_in = tmp_p / "seg1.wav"
        seg2_in = tmp_p / "seg2.wav"
        seg3_in = tmp_p / "seg3.wav"

        seg1_out = tmp_p / "seg1_fast.wav"
        seg2_out = tmp_p / "seg2_fast.wav"
        seg3_out = tmp_p / "seg3_fast.wav"

        # Slice segments
        subprocess.run(
            [ffmpeg_bin, "-y", "-ss", "0", "-t", str(seg1_dur), "-i", str(in_p), str(seg1_in)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-ss",
                str(seg1_dur),
                "-t",
                str(seg2_dur),
                "-i",
                str(in_p),
                str(seg2_in),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-ss",
                str(seg1_dur + seg2_dur),
                "-i",
                str(in_p),
                str(seg3_in),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Accelerate each segment with its respective multiplier
        if seg1_in.is_file() and seg1_in.stat().st_size > 0:
            accelerate_audio(seg1_in, seg1_out, speed_multiplier=start_multiplier)
        if seg2_in.is_file() and seg2_in.stat().st_size > 0:
            accelerate_audio(seg2_in, seg2_out, speed_multiplier=mid_multiplier)
        if seg3_in.is_file() and seg3_in.stat().st_size > 0:
            accelerate_audio(seg3_in, seg3_out, speed_multiplier=target_multiplier)

        # Concatenate segments using concat filter
        valid_segs = [s for s in (seg1_out, seg2_out, seg3_out) if s.is_file() and s.stat().st_size > 0]
        if not valid_segs:
            return accelerate_audio(in_p, out_p, speed_multiplier=target_multiplier)

        inputs = []
        filter_inputs = []
        for i, s in enumerate(valid_segs):
            inputs.extend(["-i", str(s)])
            filter_inputs.append(f"[{i}:a]")

        concat_filter = f"{''.join(filter_inputs)}concat=n={len(valid_segs)}:v=0:a=1[outa]"
        concat_cmd = [
            ffmpeg_bin,
            "-y",
            *inputs,
            "-filter_complex",
            concat_filter,
            "-map",
            "[outa]",
            "-ar",
            "44100",
            str(out_p),
        ]
        res = subprocess.run(concat_cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return accelerate_audio(in_p, out_p, speed_multiplier=target_multiplier)

    return out_p
