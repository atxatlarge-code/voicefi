#!/usr/bin/env python3
"""
Setup helper to register the VoiceFi hook into ~/.gemini/config/hooks.json.
"""

import sys
from pathlib import Path

# Add src to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir / "src"))

from voicefi.cli import cmd_setup
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default=None)
    args = parser.parse_args()
    cmd_setup(args)
