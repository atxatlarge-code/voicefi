"""
VoiceFi™ Documentary Mode & Nature Documentary Reel Compiler.
Automates broadcast-grade 9:16 vertical comedy and nature documentary reels
narrated in the style of a documentary broadcaster (or Werner Herzog), featuring
prosodic ellipsis thought-chunking, BBC Broadcast Silk mastering, Baskerville
subtitles, real environmental audio retention, and comedic punchline hard mutes.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# macOS dynamic library resolution for torchcodec / F5-TTS
if sys.platform == "darwin" and "DYLD_FALLBACK_LIBRARY_PATH" not in os.environ:
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib"

from voicefi.audio.mastering import apply_bbc_documentary_mastering
from voicefi.video.reel_builder import get_video_encoder_args


def format_documentary_script(text: str) -> str:
    """
    Format text for nature documentary style narration by inserting deliberate
    breathing pauses and dramatic ellipses before revelation clauses, and eliminating
    exclamation marks which trigger unnatural pitch spikes in neural diffusion models.
    """
    if not text or not text.strip():
        return ""

    t = text.strip()

    # 1. Eliminate exclamation marks (Rule: Documentary broadcaster never yells like an infomercial)
    t = re.sub(r"!\s*", "... ", t)

    # 2. Phonetic normalization for known problematic acronyms
    phonetic_map = [
        (r"\bWi-Fi\b", "why fye"),
        (r"\bWiFi\b", "why fye"),
        (r"\bwifi\b", "why fye"),
        (r"\bAWS\b", "A W S"),
        (r"\bAPI\b", "A P I"),
        (r"\bSQL\b", "sequel"),
    ]
    for pat, rep in phonetic_map:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)

    # 3. Expand intro phrases into breath pauses (only at sentence or clause boundaries)
    intro_patterns = [
        (r"(^|[.!?;]\s*)(And here)[,.]?\s*", r"\1And here... "),
        (r"(^|[.!?;]\s*)(Look closely)[,.]?\s*", r"\1Look closely... "),
        (r"(^|[.!?;]\s*)(Remarkable)[,.]?\s*", r"\1Remarkable... "),
        (r"(^|[.!?;]\s*)(Extraordinary)[,.]?\s*", r"\1Extraordinary... "),
        (r"(^|[.!?;]\s*)(Quite astonishing)[,.]?\s*", r"\1Quite astonishing... "),
        (r"(^|[.!?;]\s*)(Here in the)[,.]?\s*", r"\1Here... in the "),
        (r"(^|[.!?;]\s*)(Notice how)[,.]?\s*", r"\1Notice... how "),
        (r"(^|[.!?;]\s*)(Yet)[,.]?\s+", r"\1Yet... "),
        (r"(^|[.!?;]\s*)(Behold)[,.]?\s+", r"\1Behold... "),
    ]
    for pat, rep in intro_patterns:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)

    # 4. Insert dramatic pauses at major clause boundaries
    t = re.sub(
        r",\s*(we discover|we find|lies|awaits|emerges|survives)\b",
        r"... \1",
        t,
        flags=re.IGNORECASE,
    )

    # 5. Clean redundant ellipses and spaces
    t = re.sub(r"(?:\s*\.+){2,}\s*", "... ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def render_baskerville_subtitle_card(
    lines: List[str],
    output_path: Path,
    width: int = 1080,
    height: int = 1920,
    font_size: int = 42,
    base_y: int = 1530,
) -> Path:
    """
    Renders classic BBC nature documentary lower-third subtitles using Baskerville serif,
    with a Gaussian-blurred dropshadow and subtle stroke for maximum readability on any background.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    cleaned = [
        l.replace("“", "")
        .replace("”", "")
        .replace('"', "")
        .replace("(", "")
        .replace(")", "")
        .strip()
        for l in lines
    ]

    font_candidates = [
        "/System/Library/Fonts/Supplemental/Baskerville.ttc",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/System/Library/Fonts/Times.ttc",
    ]
    font_path = None
    for cand in font_candidates:
        if os.path.exists(cand):
            font_path = cand
            break

    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    line_height = int(font_size * 1.38)
    total_text_h = len(cleaned) * line_height
    start_y = base_y - (total_text_h // 2)

    # 1. Render soft blurred shadow
    shadow_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow_img)
    for i, line in enumerate(cleaned):
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        x = (width - w) // 2
        y = start_y + (i * line_height)
        s_draw.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0, 225))

    shadow_blurred = shadow_img.filter(ImageFilter.GaussianBlur(radius=5))
    img = Image.alpha_composite(Image.new("RGBA", (width, height), (0, 0, 0, 0)), shadow_blurred)
    draw = ImageDraw.Draw(img)

    # 2. Render text outline and crisp white fill
    for i, line in enumerate(cleaned):
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        x = (width - w) // 2
        y = start_y + (i * line_height)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1)]:
            draw.text((x + dx, y + dy), line, font=font, fill=(15, 15, 15, 190))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return output_path


def synthesize_documentary_acts(
    acts: List[Tuple[str, str]],
    output_dir: Path,
    persona: str = "documentary_broadcaster",
    device: str = "mps",
) -> List[Path]:
    """
    Synthesize an array of documentary narrative acts as distinct audio stems using F5-TTS
    (with automatic fallback to EdgeTTS with BBC Broadcast Silk mastering).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stem_paths = []

    tts_engine = None
    try:
        from voicefi.tts.f5_tts import F5TTS

        if F5TTS.is_available():
            tts_engine = F5TTS(device=device)
            tts_engine.persona_name = persona
    except Exception:
        pass

    for act_id, raw_text in acts:
        formatted_text = format_documentary_script(raw_text)
        out_wav = output_dir / f"{act_id}.wav"

        success = False
        if tts_engine:
            try:
                success = tts_engine.speak_to_file(formatted_text, out_wav)
            except Exception:
                success = False

        if not success or not out_wav.exists() or out_wav.stat().st_size == 0:
            # Fallback to high-fidelity EdgeTTS with BBC mastering
            import asyncio
            from voicefi.tts.edge_tts import EdgeTTS

            edge = EdgeTTS(voice="en-GB-ThomasNeural", rate="-5%", pitch="-4Hz")
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(edge.synthesize_to_file(formatted_text, out_wav))
                success = out_wav.exists() and out_wav.stat().st_size > 0
            finally:
                loop.close()

        if out_wav.exists() and out_wav.stat().st_size > 0:
            # Enforce BBC Broadcast Silk mastering (70Hz highpass, 125Hz warmth, 5.6kHz de-esser, 10.5kHz lowpass)
            apply_bbc_documentary_mastering(out_wav, out_wav, silk=True)
            stem_paths.append(out_wav)
        else:
            raise RuntimeError(f"Failed to synthesize documentary act: '{act_id}'")

    return stem_paths


def build_documentary_soundtrack(
    speech_stem: Path,
    total_duration: float,
    score_style: str = "beatdrop",
    drop_time_sec: Optional[float] = None,
    punchline_pause_start: Optional[float] = None,
    punchline_pause_end: Optional[float] = None,
    camera_audio: Optional[Path] = None,
    camera_vol: float = 0.20,
    output_wav: Optional[Path] = None,
) -> Path:
    """
    Assembles a broadcast-mastered documentary audio track implementing:
    - Grounding camera audio / environmental foley at ~20% volume
    - Zen Flute -> 808 Trap drop with pre-drop riser, OR pure Vivaldi Winter
    - Dead air tape-stop hard mute during comedic dramatic pause before punchline
    - Final true-peak limiting at -1.0 dBFS with unity gain (normalize=0)
    """
    import soundfile as sf
    import numpy as np

    sr = 48000
    total_samples = int(total_duration * sr)
    out_p = output_wav or Path(tempfile.mktemp(prefix="doc_soundtrack_", suffix=".wav"))

    # 1. Load or synthesize background score
    music_track = np.zeros(total_samples, dtype=np.float32)

    zen_src = Path("/tmp/zen_35s.wav")
    trap_src = Path("/tmp/vivaldi_trap_beat.mp3")
    classical_src = Path("/tmp/vivaldi_winter_pure.mp3")

    if score_style == "beatdrop" and zen_src.exists() and trap_src.exists():
        # Load Zen track
        zen_data, z_sr = sf.read(str(zen_src))
        if len(zen_data.shape) > 1:
            zen_data = zen_data.mean(axis=1)
        if z_sr != sr:
            import scipy.signal

            zen_data = scipy.signal.resample(zen_data, int(len(zen_data) * sr / z_sr))

        # Load Trap track
        trap_data, t_sr = sf.read(str(trap_src))
        if len(trap_data.shape) > 1:
            trap_data = trap_data.mean(axis=1)
        if t_sr != sr:
            import scipy.signal

            trap_data = scipy.signal.resample(trap_data, int(len(trap_data) * sr / t_sr))

        trap_peak = np.max(np.abs(trap_data))
        if trap_peak > 0:
            trap_data /= trap_peak

        # Sync 808 drop (drop in source is at 48.0578s)
        climax_drop_sec = drop_time_sec if drop_time_sec is not None else 30.80
        source_drop_sec = 48.0578
        offset = source_drop_sec - climax_drop_sec

        # Zen part with fade-out
        zen_end_samp = int(min(climax_drop_sec + 0.4, total_duration) * sr)
        zen_fade_start = int(max(0, climax_drop_sec - 1.2) * sr)
        zen_slice = zen_data[:zen_end_samp].copy()
        if len(zen_slice) > zen_fade_start:
            fo_len = len(zen_slice) - zen_fade_start
            zen_slice[zen_fade_start:] *= np.linspace(1, 0, fo_len)
        zen_fi_len = int(1.0 * sr)
        if len(zen_slice) > zen_fi_len:
            zen_slice[:zen_fi_len] *= np.linspace(0, 1, zen_fi_len)

        music_track[: len(zen_slice)] += zen_slice * 0.55

        # Trap part with pre-drop riser
        trap_start_reel_sec = max(0.0, climax_drop_sec - 1.30)
        trap_start_samp = int(trap_start_reel_sec * sr)
        trap_src_start_samp = int((trap_start_reel_sec + offset) * sr)

        silence_start_sec = (
            punchline_pause_start if punchline_pause_start is not None else (total_duration - 4.6)
        )
        silence_samp = int(silence_start_sec * sr)

        trap_chunk_len = max(0, silence_samp - trap_start_samp)
        if trap_chunk_len > 0 and trap_src_start_samp + trap_chunk_len <= len(trap_data):
            trap_chunk = trap_data[
                trap_src_start_samp : trap_src_start_samp + trap_chunk_len
            ].copy()
            # Riser fade in
            riser_len = int(0.25 * sr)
            if len(trap_chunk) > riser_len:
                trap_chunk[:riser_len] *= np.linspace(0, 1, riser_len)
            # Tape stop mute
            stop_fade_len = int(0.05 * sr)
            if len(trap_chunk) > stop_fade_len:
                trap_chunk[-stop_fade_len:] *= np.linspace(1, 0, stop_fade_len)

            music_track[trap_start_samp:silence_samp] += trap_chunk * 0.75

        # Sub bass resolve tail after punchline
        if punchline_pause_end is not None and punchline_pause_end < total_duration:
            tail_start_samp = int(punchline_pause_end * sr)
            kick_samp_start = int(source_drop_sec * sr)
            tail_len = min(int(2.1 * sr), total_samples - tail_start_samp)
            if tail_len > 0 and kick_samp_start + tail_len <= len(trap_data):
                kick_chunk = trap_data[kick_samp_start : kick_samp_start + tail_len].copy()
                tail_fo = int(1.4 * sr)
                if len(kick_chunk) > tail_fo:
                    kick_chunk[-tail_fo:] *= np.linspace(1, 0, tail_fo)
                music_track[tail_start_samp : tail_start_samp + len(kick_chunk)] += (
                    kick_chunk * 0.65
                )

    elif classical_src.exists():
        # Classical Vivaldi Winter
        c_data, c_sr = sf.read(
            str(classical_src), start=int(1.78 * 44100), frames=int(total_duration * 44100)
        )
        if len(c_data.shape) > 1:
            c_data = c_data.mean(axis=1)
        if c_sr != sr:
            import scipy.signal

            c_data = scipy.signal.resample(c_data, int(len(c_data) * sr / c_sr))

        c_peak = np.max(np.abs(c_data))
        if c_peak > 0:
            c_data = (c_data / c_peak) * 0.65
        fo = int(1.8 * sr)
        if len(c_data) > fo:
            c_data[-fo:] *= np.linspace(1, 0, fo)
        avail = min(len(music_track), len(c_data))
        music_track[:avail] = c_data[:avail]

    temp_music = Path(tempfile.mktemp(prefix="doc_mus_", suffix=".wav"))
    sf.write(str(temp_music), music_track, sr)

    # 2. Mix with speech stem and optional camera foley via ffmpeg
    filter_parts = []
    filter_parts.append(
        "[1:a][0:a]sidechaincompress=threshold=0.06:ratio=2.2:attack=25:release=200[ducked]"
    )

    if camera_audio and Path(camera_audio).is_file():
        filter_parts.append(f"[2:a]volume={camera_vol},aloop=loop=-1:size=2e+09[foley]")
        filter_parts.append(
            "[0:a][ducked][foley]amix=inputs=3:normalize=0:duration=first:dropout_transition=0[mix]"
        )
    else:
        filter_parts.append(
            "[0:a][ducked]amix=inputs=2:normalize=0:duration=first:dropout_transition=0[mix]"
        )

    filter_parts.append("[mix]alimiter=limit=-1.0dB:attack=5:release=50[out]")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(speech_stem),
        "-i",
        str(temp_music),
    ]
    if camera_audio and Path(camera_audio).is_file():
        cmd.extend(["-i", str(camera_audio)])

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[out]",
            "-c:a",
            "pcm_s16le",
            str(out_p),
        ]
    )

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    finally:
        temp_music.unlink(missing_ok=True)

    return out_p


def cmd_documentary_reel(args) -> int:
    """CLI handler for VoiceFi Documentary Mode (vifi reel --doc / vifi doc)."""
    print("🎙️ VoiceFi™ Documentary Reel Engine (BBC Natural History Unit Mode)")
    print("=" * 66)

    in_file = getattr(args, "input", None)
    script_text = getattr(args, "script", None)
    persona = getattr(args, "persona", "documentary_broadcaster") or "documentary_broadcaster"
    score_style = getattr(args, "score", "beatdrop") or "beatdrop"
    out_file = getattr(args, "output", None)

    print(f"• Persona:             {persona.title()} (BBC Neural Diffusion)")
    print(f"• Scoring Style:       {score_style.title()} (Zen -> 808 Trap Drop / Tape-Stop)")
    print("• Typography:          Baskerville Classic BBC (Gaussian Soft Dropshadow)")
    print("• Broadcast Mastering: BBC Silk (70Hz highpass, 125Hz warmth, 5.6kHz de-esser)")

    if script_text:
        formatted = format_documentary_script(script_text)
        print(f'\n📜 Formatted Documentary Script:\n   "{formatted}"')
        tmp_dir = Path("/tmp/vifi_doc_render")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        print("\n⏳ Synthesizing voice stem with BBC broadcast mastering...")
        stems = synthesize_documentary_acts([("act1", formatted)], tmp_dir, persona=persona)
        if stems:
            print(f"✅ Voice stem generated & mastered: {stems[0]}")
            if getattr(args, "open", False):
                subprocess.run(["afplay", str(stems[0])])
        return 0

    if in_file and Path(in_file).is_file():
        in_path = Path(in_file).resolve()
        out_path = (
            Path(out_file).resolve()
            if out_file
            else in_path.parent / f"{in_path.stem}_doc_mastered.mp4"
        )
        print(f"\n🎧 Scoring & mastering documentary video: {in_path.name}...")
        # Get video duration
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(in_path),
            ],
            capture_output=True,
            text=True,
        )
        dur = float(res.stdout.strip()) if res.stdout.strip() else 60.0

        # Build soundtrack
        temp_audio = Path(tempfile.mktemp(prefix="doc_audio_", suffix=".wav"))
        build_documentary_soundtrack(
            speech_stem=in_path,
            total_duration=dur,
            score_style=score_style,
            output_wav=temp_audio,
        )

        # Mux with video copy
        cmd_mux = [
            "ffmpeg",
            "-y",
            "-i",
            str(in_path),
            "-i",
            str(temp_audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd_mux, check=True)
        temp_audio.unlink(missing_ok=True)
        print(f"✅ Documentary reel ready: {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")
        if getattr(args, "open", False):
            subprocess.run(["open", str(out_path)])
        return 0

    print("\n💡 Usage Examples:")
    print(
        "   vifi reel --doc --script 'Here... high atop the summit... a peculiar migration is underway.'"
    )
    print("   vifi reel --doc my_video.mp4 --score beatdrop -o my_doc_reel.mp4")
    print(
        "   vifi doc --script 'Notice how... the feral developer bargains for exit code zero.' --open"
    )
    return 0
