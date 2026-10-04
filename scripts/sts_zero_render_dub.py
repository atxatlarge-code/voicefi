#!/usr/bin/env python3
"""
Zero-Render Speech-to-Speech (STS) Video Dubbing CLI — VoiceFi™

Dub any video's spoken dialogue into another voice (Christopher Walken, Drill Sergeant,
Game Show Host, Deadpan Ironist, etc.) while preserving 100% video frame quality,
original lip-sync timing, and 0.2s mux export speed.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure voicefi is in python path
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from voicefi.video.sts_dubber import ZeroRenderDubber


def main():
    parser = argparse.ArgumentParser(
        description="Zero-Render Speech-to-Speech (STS) Video Dubbing CLI — VoiceFi™"
    )
    parser.add_argument("video", type=str, help="Path to input video file (.mp4, .mov, etc.)")
    parser.add_argument(
        "-v",
        "--voice",
        type=str,
        default="christopher_walken",
        help="Target voice persona (e.g. christopher_walken, drill_sergeant, deadpan_ironist, game_show_host)",
    )
    parser.add_argument(
        "-p",
        "--provider",
        type=str,
        default="auto",
        choices=["auto", "voice_acting", "local_clone", "edge"],
        help="Voice generation provider",
    )
    parser.add_argument(
        "--instruct",
        type=str,
        default=None,
        help="Theatrical performance directive (e.g. 'Deadpan sarcastic software engineer')",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output destination for dubbed video",
    )
    parser.add_argument(
        "--text",
        type=str,
        default=None,
        help="Manual transcript override (skips ASR transcription)",
    )
    parser.add_argument(
        "--whisper-model",
        type=str,
        default="base.en",
        help="Faster-Whisper model size (tiny.en, base.en, small.en)",
    )
    parser.add_argument(
        "--web-compat",
        action="store_true",
        help="Encode to universal H.264 SDR (yuv420p) for 100% web browser and HTML5 player compatibility",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary WAV audio files for inspection",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    if not args.quiet:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        print("\n🎬 ══════════════════════════════════════════════════════════")
        print("   VoiceFi™ Zero-Render Speech-to-Speech Video Dubber")
        print("══════════════════════════════════════════════════════════")
        print(f"📹 Input Video : {args.video}")
        print(f"🎭 Target Voice: {args.voice}")
        if args.instruct:
            print(f'📜 Instruction : "{args.instruct}"')
        if args.web_compat:
            print("🌐 Web Compat  : H.264 SDR (yuv420p)")
        print("──────────────────────────────────────────────────────────\n")

    dubber = ZeroRenderDubber(whisper_model_size=args.whisper_model)
    report = dubber.dub_video(
        video_path=args.video,
        voice=args.voice,
        provider=args.provider,
        instruct=args.instruct,
        output_video=args.output,
        script_override=args.text,
        keep_temp=args.keep_temp,
        web_compat=args.web_compat,
    )

    if not args.quiet:
        print("✨ Dubbing Complete!")
        print(f'📝 Spoken Text : "{report["transcript"]}"')
        print(f"⏱️  Audio Timing: {report['source_duration_sec']}s (matched precisely)")
        print(f"⚡ Mux Time     : {report['remux_time_sec']}s (zero pixel re-rendering)")
        print(f"🚀 Total Time   : {report['total_time_sec']}s")
        print(f"🎉 Dubbed Video : {report['output_video']}\n")
    else:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
