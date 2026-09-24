#!/usr/bin/env python3
"""
Interactive punch-in recording utility for VoiceFi reels.
Records 48kHz high-fidelity vocal punch-ins with audio beeps and instant playback.
"""

import os
import sys
import time
import subprocess
import numpy as np
import sounddevice as sd
import soundfile as sf

TARGET_DIR = "/tmp/voicefi_reel_punchins"
os.makedirs(TARGET_DIR, exist_ok=True)

SAMPLE_RATE = 48000
CHANNELS = 1


def play_beep():
    """Plays system audio ping to signal start of recording."""
    beep_path = "/System/Library/Sounds/Tink.aiff"
    if os.path.exists(beep_path):
        subprocess.run(["afplay", beep_path], capture_output=True)


def play_audio(filepath):
    """Plays back an audio file."""
    subprocess.run(["afplay", filepath], capture_output=True)


def record_take(prompt_text, duration=3.0, filename="take.wav"):
    filepath = os.path.join(TARGET_DIR, filename)
    print("\n" + "=" * 60)
    print(f'🎙️  NEXT PHRASE TO SAY:  "{prompt_text}"')
    print("=" * 60)
    input("Press [Enter] when ready to record...")

    print("Get ready...")
    for i in range(3, 0, -1):
        print(f"  {i}...")
        play_beep()
        time.sleep(0.6)

    print("🔴 RECORDING NOW! SPEAK CLEARLY!")
    play_beep()

    # Record
    audio = sd.rec(
        int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32"
    )
    sd.wait()
    print("⏹️ Done recording!")

    audio = audio.flatten()

    # Simple silence trimming (energy > threshold)
    energy = np.abs(audio)
    threshold = 0.015
    voiced_indices = np.where(energy > threshold)[0]

    if len(voiced_indices) > 0:
        start_idx = max(0, voiced_indices[0] - int(0.08 * SAMPLE_RATE))
        end_idx = min(len(audio), voiced_indices[-1] + int(0.08 * SAMPLE_RATE))
        audio_trimmed = audio[start_idx:end_idx]
    else:
        audio_trimmed = audio

    # Normalize to -24 dBFS RMS (matches original video speech level)
    rms = np.sqrt(np.mean(audio_trimmed**2)) + 1e-9
    target_rms = 10 ** (-24.0 / 20.0)
    gain = target_rms / rms
    # Prevent extreme digital clipping
    if np.max(np.abs(audio_trimmed * gain)) > 0.95:
        gain = 0.95 / np.max(np.abs(audio_trimmed))

    normalized_audio = audio_trimmed * gain
    sf.write(filepath, normalized_audio, SAMPLE_RATE)

    print(f'\n🔊 Playing back your recording of: "{prompt_text}"...')
    play_audio(filepath)

    choice = input("\nHappy with this take? ([y]/r to re-record): ").strip().lower()
    if choice == "r":
        return record_take(prompt_text, duration, filename)

    print(f"✅ Saved to {filepath}")
    return filepath


def main():
    print("\n🎬 VoiceFi Punch-In Recorder for Terminal Demo Reel")
    print("--------------------------------------------------")
    print("We will record 2 quick punch-ins to replace 'David Attenborough':")
    print("  1. \"a broadcaster voice\"      (replaces 'a David Attenborough voice' at 0:04)")
    print("  2. \"this broadcaster voice\"   (replaces 'this David Attenborough voice' at 1:02)")
    print('  3. "broadcaster voice"        (standalone backup take)')
    print("--------------------------------------------------")

    t1 = record_take(
        "a broadcaster voice", duration=2.5, filename="punchin_1_a_broadcaster_voice.wav"
    )
    t2 = record_take(
        "this broadcaster voice", duration=2.5, filename="punchin_2_this_broadcaster_voice.wav"
    )
    t3 = record_take("broadcaster voice", duration=2.2, filename="punchin_3_broadcaster_voice.wav")

    print("\n🎉 All punch-in takes recorded successfully!")
    print(f"Files saved in: {TARGET_DIR}")


if __name__ == "__main__":
    main()
