#!/usr/bin/env python3
"""
Simple interactive mic recorder for voice intros.
Records 48kHz stereo/mono audio and saves to assets/jake_intro.wav.
"""

import sys
import time
import wave
import numpy as np
import sounddevice as sd
from pathlib import Path

SAMPLE_RATE = 48000
CHANNELS = 1
OUT_FILE = Path(__file__).resolve().parent.parent / "assets" / "jake_intro.wav"
OUT_FILE.parent.mkdir(parents=True, exist_ok=True)


def record_audio(duration: float = 8.0):
    print("\n" + "=" * 60)
    print("🎙️  VoiceFi™ Live Voice Note Recorder")
    print("=" * 60)
    print(f"👉 Target File: {OUT_FILE}")
    print(f"👉 Max Duration: {duration}s (or press Ctrl+C to stop early)")
    print("\nGet ready... Recording starts in:")
    for i in range(3, 0, -1):
        print(f"   {i}...", flush=True)
        time.sleep(1)

    print("\n🔴 RECORDING NOW! (Speak into your mic)...", flush=True)

    try:
        recording = sd.rec(
            int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16"
        )
        for elapsed in range(int(duration)):
            time.sleep(1)
            bar = "█" * (elapsed + 1) + "░" * (int(duration) - elapsed - 1)
            print(f"\r[{bar}] {elapsed + 1}s / {int(duration)}s", end="", flush=True)
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
        print("\n\n⏹️  Stopped by user.")

    print("\n\n💾 Saving audio...")
    with wave.open(str(OUT_FILE), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(recording.tobytes())

    print(f"✅ Saved clean voice track to: {OUT_FILE}")
    print(f"   Duration: {len(recording) / SAMPLE_RATE:.2f}s")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
    record_audio(dur)
