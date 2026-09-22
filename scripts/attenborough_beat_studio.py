#!/usr/bin/env python3
"""
VoiceFi™ Attenborough Beat Studio CLI
Audition, generate, and swap musical backing tracks for beat-synced
Sir David Attenborough nature documentary reels.
"""

import os
import sys
import argparse
from pathlib import Path

# Add voicefi to path
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Ensure Homebrew dylibs for Apple Silicon
if sys.platform == "darwin" and "DYLD_FALLBACK_LIBRARY_PATH" not in os.environ:
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = "/opt/homebrew/lib"


def main():
    parser = argparse.ArgumentParser(
        description="VoiceFi Attenborough Beat Studio: Line up Attenborough narration to musical beats with swappable tracks."
    )
    parser.add_argument(
        "--video",
        type=str,
        default=str(Path.home() / "Downloads" / "PXL_20260614_151620684 (1).mp4"),
        help="Path to source video footage (defaults to Armadillo clip)",
    )
    parser.add_argument(
        "--style",
        choices=["boombap", "chillhop", "acoustic", "lofi", "trap", "dub"],
        default="boombap",
        help="Musical style of backing track (default: boombap)",
    )
    parser.add_argument(
        "--duration",
        choices=["9s", "6s"],
        default="9s",
        help="Reel duration target (9s viral short or 6s micro-loop)",
    )
    parser.add_argument(
        "--drop-style",
        choices=["mute", "808"],
        default="mute",
        help="Punchline beat drop behavior ('mute' for deadpan silence, '808' for explosive sub drop)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Destination path for compiled MP4",
    )
    args = parser.parse_args()

    # Delegate to the reel generator
    vifi_script = Path("/Users/jaketrigg/Projects/vifi.co/marketing/social/armadillo_beat_reel.py")
    if not vifi_script.exists():
        print(f"Error: Reel script not found at {vifi_script}")
        sys.exit(1)

    cmd = [
        sys.executable,
        str(vifi_script),
        "--style", args.style,
        "--duration", args.duration,
        "--drop-style", args.drop_style,
    ]
    if args.output:
        cmd.extend(["--output", args.output])

    import subprocess
    sys.exit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
