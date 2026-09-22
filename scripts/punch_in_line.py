#!/usr/bin/env python3
"""
VoiceFi™ Studio Punch-In Recorder:
Allows punching in a single line (e.g. "In the past 6 months...") into Jake's
crystal-clean Take 02 vocal track without re-recording the whole 84-second reel.
"""

import argparse
import subprocess
import sys
import time
import wave
from pathlib import Path
import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
SAMPLE_RATE = 48000

PUNCH_TARGETS = {
    "1": {
        "title": "Scene 9: Google Antigravity & AI Pipeline",
        "text": "In the past 6 months, I built a real estate data pipeline by coding with Google Antigravity.",
        "take02_start": 61.8,
        "take02_end": 67.2,
        "pre_roll": 56.0,
    },
    "2": {
        "title": "Scene 11: The Wall Breakthrough / Question",
        "text": "So what happens when a PMP gets a TBI and his professional life falls apart until he starts coding with AI?",
        "take02_start": 73.2,
        "take02_end": 78.8,
        "pre_roll": 68.0,
    }
}

def main():
    parser = argparse.ArgumentParser(description="VoiceFi Studio Vocal Punch-In Tool")
    parser.add_argument("-l", "--line", default="1", choices=["1", "2"], help="Line to punch in (1=Antigravity 6mo, 2=PMP/TBI question)")
    parser.add_argument("-i", "--input-wav", type=str, default=None, help="Optional pre-recorded WAV file to splice in directly")
    args = parser.parse_args()

    target = PUNCH_TARGETS[args.line]
    take02_path = ROOT_DIR / "assets" / "audio" / "jake_lienlogic_take_02_crystal_clean.wav"
    music_path = ROOT_DIR / "assets" / "audio" / "backing_tracks" / "track_05_bittersweet_symphony.mp3"
    out_take03_path = ROOT_DIR / "assets" / "audio" / "jake_lienlogic_take_03_crystal_clean.wav"

    print("\n" + "=" * 76)
    print("🎙️  VOICEFI™ STUDIO VOCAL PUNCH-IN")
    print("=" * 76)
    print(f"🎯 Target: {target['title']}")
    print(f"📝 Script:")
    print(f"\n   \033[1;32m\"{target['text']}\"\033[0m\n")
    print("=" * 76)

    if args.input_wav:
        punch_wav = Path(args.input_wav)
        if not punch_wav.exists():
            print(f"❌ Error: {punch_wav} not found.")
            sys.exit(1)
        print(f"📥 Loading pre-recorded punch: {punch_wav.name}")
    else:
        print("👉 Put on headphones.")
        print(f"   We will play ~5s of the backing track lead-in ({target['pre_roll']:.1f}s) to catch the groove.")
        print("   Then hit the line on beat!")
        input("\nPress [Enter] when ready to start punch-in... ")

        music_proc = subprocess.Popen(
            ["afplay", "-v", "0.85", "-ss", str(target["pre_roll"]), str(music_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        import sounddevice as sd
        lead_in_dur = target["take02_start"] - target["pre_roll"]
        
        t0 = time.time()
        while time.time() - t0 < lead_in_dur:
            rem = lead_in_dur - (time.time() - t0)
            sys.stdout.write(f"\r⏳ Backing track cueing up... Speak in {rem:.1f}s   ")
            sys.stdout.flush()
            time.sleep(0.05)

        print("\n\n🔴 \033[1;31mRECORDING NOW — SPEAK THE LINE!\033[0m")
        print(f"   \033[1;32m\"{target['text']}\"\033[0m\n")

        audio_frames = []
        stop_event = False

        def callback(indata, frames, time_info, status):
            if not stop_event:
                audio_frames.append(indata.copy())

        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback)
        with stream:
            input("Hit [Enter] as soon as you finish the line... ")
            stop_event = True

        music_proc.terminate()

        if not audio_frames:
            print("❌ No audio recorded.")
            sys.exit(1)

        raw = np.concatenate(audio_frames, axis=0).flatten()
        punch_wav = ROOT_DIR / "assets" / "audio" / "punch_temp_raw.wav"
        int16_raw = (np.clip(raw, -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(str(punch_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(int16_raw.tobytes())

    cleaned_punch = ROOT_DIR / "assets" / "audio" / "punch_cleaned.wav"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(punch_wav),
        "-af", "highpass=f=85,silenceremove=start_periods=1:start_threshold=-40dB:start_silence=0.05",
        "-ar", str(SAMPLE_RATE), "-ac", "1",
        str(cleaned_punch)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def read_wav(p):
        cmd = ["ffmpeg", "-i", str(p), "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"]
        res = subprocess.run(cmd, capture_output=True, check=True)
        return np.frombuffer(res.stdout, dtype=np.float32)

    vox_orig = read_wav(take02_path).copy()
    vox_punch = read_wav(cleaned_punch).copy()

    # Trim trailing silence (typically speech finishes by 6.1s)
    # Check where speech actually finishes
    punch_peak = np.max(np.abs(vox_punch))
    if punch_peak > 0:
        vox_punch = (vox_punch / punch_peak) * 0.90

    idx_cut_start = int(target["take02_start"] * SAMPLE_RATE)
    idx_cut_end = int(target["take02_end"] * SAMPLE_RATE)

    part1 = vox_orig[:idx_cut_start]
    part2 = vox_punch
    pause = np.zeros(int(0.25 * SAMPLE_RATE), dtype=np.float32)
    part3 = vox_orig[idx_cut_end:]

    composite = np.concatenate([part1, part2, pause, part3])

    int16_comp = (np.clip(composite, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(out_take03_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int16_comp.tobytes())

    user_dl = Path("/Users/jaketrigg/Downloads/jake_lienlogic_take_03_crystal_clean.wav")
    user_dl.write_bytes(out_take03_path.read_bytes())

    print(f"\n✅ Spliced Punch-In Successfully!")
    print(f"   • Output Master Vocal: {out_take03_path}")
    print(f"   • Exported to:         ~/Downloads/{user_dl.name}")
    print("=" * 76 + "\n")

if __name__ == "__main__":
    main()
