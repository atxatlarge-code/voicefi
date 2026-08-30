#!/usr/bin/env python3
"""
Interactive Studio Vocal Recorder & Vocal Restoration Engine for VoiceFi Reels.
1. Records high-fidelity microphone audio from the default Mac microphone.
2. Applies studio restoration (dead-air trimming, zero-pop crossfading, peak normalization).
3. Plays back the cleaned audio for verification.
4. Re-compiles the reel with the user's real voice inserted.
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100


def record_from_microphone(output_wav: Path, max_seconds: float = 30.0) -> bool:
    """Record microphone audio interactively using sounddevice or ffmpeg avfoundation."""
    print("\n" + "=" * 60)
    print("🎙️  VoiceFi™ Interactive Studio Vocal Recorder")
    print("=" * 60)
    print("\nGet ready to speak your line!")
    print("Example lines:")
    print(" • “Look, I just wanted to pace around my room and talk to my code without typing all day!”")
    print(" • “For years, coding was silent. Staring at terminal logs. So we gave our agents a real voice.”")
    print(" • “Once you start pair-programming with your agents by voice, you can never go back.”\n")

    input("👉 Press [Enter] when ready to record (3s countdown will begin)... ")

    for count in range(3, 0, -1):
        print(f"   ⏱️  {count}...")
        time.sleep(1.0)

    print("\n🔴  *** RECORDING NOW! (Speak into your mic. Press Ctrl+C or Enter when finished) ***\n")

    try:
        import sounddevice as sd
        import soundfile as sf

        audio_frames = []
        stop_recording = False

        def callback(indata, frames, time_info, status):
            if not stop_recording:
                audio_frames.append(indata.copy())

        # Start stream
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='float32', callback=callback)
        with stream:
            try:
                # Wait for enter in background or timeout
                input("👉 Press [Enter] to STOP recording...\n")
            except (KeyboardInterrupt, EOFError):
                pass
            finally:
                stop_recording = True

        if not audio_frames:
            print("⚠️ No audio frames captured.")
            return False

        recorded_audio = np.concatenate(audio_frames, axis=0).flatten()

    except Exception as e:
        print(f"Using FFmpeg fallback recorder (sounddevice notice: {e})...")
        cmd = [
            "ffmpeg", "-y",
            "-f", "avfoundation",
            "-i", ":0",
            "-t", str(max_seconds),
            "-ar", str(SAMPLE_RATE),
            "-ac", "1",
            str(output_wav)
        ]
        print("Recording via macOS AVFoundation... (Press Ctrl+C to stop)")
        try:
            subprocess.run(cmd, check=True)
            return True
        except KeyboardInterrupt:
            pass

    # Save initial capture
    import wave
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    int16_data = (np.clip(recorded_audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(output_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int16_data.tobytes())

    return True


def restore_user_vocal(input_audio_path: Path, output_wav: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Apply the 4-step Golden Studio Restoration Formula."""
    print("\n[Restoration] 🎛️ Applying Studio Vocal Restoration...")

    # 1. Load raw audio array
    res = subprocess.run([
        "ffmpeg", "-y", "-i", str(input_audio_path),
        "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "pipe:1"
    ], capture_output=True, check=True)
    raw = np.frombuffer(res.stdout, dtype=np.float32).copy()

    # 2. Intelligent Dead-Air & Mic Turn-On Trimming (50ms RMS window)
    win = int(0.05 * sample_rate)
    rms = np.array([np.sqrt(np.mean(raw[i:i+win]**2)) for i in range(0, len(raw)-win, win)])
    thresh = 0.0035
    speech_indices = np.where(rms > thresh)[0]

    if len(speech_indices) > 0:
        first_idx = max(0, speech_indices[0] * win - int(0.18 * sample_rate))  # 180ms lead-in
        last_idx = min(len(raw), speech_indices[-1] * win + win + int(0.30 * sample_rate))  # 300ms lead-out
        trimmed = raw[first_idx:last_idx].copy()
    else:
        trimmed = raw.copy()

    # 3. Smooth, Click-Free Crossfades
    fade_in = min(len(trimmed), int(0.15 * sample_rate))   # 150ms smooth fade in
    fade_out = min(len(trimmed), int(0.25 * sample_rate))  # 250ms smooth fade out
    if fade_in > 0:
        trimmed[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
    if fade_out > 0:
        trimmed[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)

    # 4. Pumping-Free Clean Peak Normalization (-0.9 dBFS)
    peak = np.max(np.abs(trimmed))
    if peak > 0.0001:
        trimmed = (trimmed / peak) * 0.90

    # Save restored file
    import wave
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    int16_data = (np.clip(trimmed, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(output_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int16_data.tobytes())

    dur = len(trimmed) / sample_rate
    print(f"✅ Restored audio saved: {output_wav} ({dur:.2f}s, Peak: -0.9 dBFS, Dead-air trimmed)")
    return trimmed


def playback_audio(audio_path: Path):
    """Play audio aloud using macOS afplay."""
    print(f"\n[Playback] 🔊 Playing back restored vocal: {audio_path.name}")
    try:
        subprocess.run(["afplay", str(audio_path)], check=True)
    except Exception as e:
        print(f"Playback note: {e}")


def main():
    parser = argparse.ArgumentParser(description="Record user vocal note for VoiceFi reel")
    parser.add_argument("-i", "--input", type=str, help="Path to existing audio file (skips mic recording)")
    parser.add_argument("-o", "--output", type=str, default="assets/jake_voice.wav", help="Output restored WAV path")
    parser.add_argument("--no-play", action="store_true", help="Skip playback check")

    args = parser.parse_args()
    root_dir = Path(__file__).resolve().parent.parent
    output_wav = (root_dir / args.output).resolve()

    if args.input:
        in_path = Path(args.input).resolve()
        if not in_path.is_file():
            print(f"❌ Error: File not found: {in_path}")
            sys.exit(1)
        restore_user_vocal(in_path, output_wav)
    else:
        raw_tmp = root_dir / "assets" / "jake_voice_raw.wav"
        success = record_from_microphone(raw_tmp)
        if not success or not raw_tmp.is_file():
            print("❌ Recording failed or was aborted.")
            sys.exit(1)
        restore_user_vocal(raw_tmp, output_wav)

    if not args.no_play:
        playback_audio(output_wav)

    print("\n" + "=" * 60)
    print(f"🎉 Ready to integrate! Restored vocal: {output_wav}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
