#!/usr/bin/env python3
"""
MusicFX Master & Ducking Utility.
Applies broadcast loudness normalization (-16 LUFS) and sidechain ducking under voice tracks.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

def master_music(input_music: str, output_path: str, duration: float = None, fade_out: float = 0.4):
    """Normalize and trim MusicFX audio to broadcast specifications."""
    filters = []
    if fade_out and duration:
        fade_start = max(0.0, duration - fade_out)
        filters.append(f"afade=t=in:ss=0:d=0.05,afade=t=out:st={fade_start:.2f}:d={fade_out:.2f}")
    filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    filter_str = ",".join(filters)

    cmd = ["ffmpeg", "-y", "-i", input_music]
    if duration:
        cmd.extend(["-t", str(duration)])
    cmd.extend(["-af", filter_str, "-b:a", "192k", output_path])

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"✅ Mastered music written to: {output_path}")

def mix_with_voice(voice_path: str, music_path: str, output_path: str, duck_volume: float = 0.85):
    """Mix voice track over music with sidechain ducking."""
    filter_complex = (
        f"[1:a]volume={duck_volume}[music];"
        f"[music][0:a]sidechaincompress=threshold=0.08:ratio=4:attack=20:release=250[ducked];"
        f"[ducked][0:a]amix=inputs=2:duration=longest:dropout_transition=2"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", voice_path,
        "-i", music_path,
        "-filter_complex", filter_complex,
        "-b:a", "192k",
        output_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"✅ Mastered vocal mix written to: {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Master MusicFX tracks and mix with VoiceFi voice acting.")
    parser.add_argument("-m", "--music", required=True, help="Path to input MusicFX audio file (.wav/.mp3)")
    parser.add_argument("-v", "--voice", help="Optional path to voice audio file to mix with ducking")
    parser.add_argument("-d", "--duration", type=float, help="Optional duration to trim music (in seconds)")
    parser.add_argument("-o", "--output", required=True, help="Output destination file (.mp3)")

    args = parser.parse_args()

    if not os.path.isfile(args.music):
        print(f"❌ Music file not found: {args.music}", file=sys.stderr)
        sys.exit(1)

    if args.voice:
        if not os.path.isfile(args.voice):
            print(f"❌ Voice file not found: {args.voice}", file=sys.stderr)
            sys.exit(1)
        mix_with_voice(args.voice, args.music, args.output)
    else:
        master_music(args.music, args.output, duration=args.duration)

if __name__ == "__main__":
    main()
