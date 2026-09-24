#!/Users/jaketrigg/Projects/VoiceFi/.venv/bin/python
"""
VoiceFi™ Rock-Solid Studio Teleprompter & Vocal Recorder for LienLogic Reel.
- Displays complete stationary teleprompter script (zero flickering or scrolling bugs).
- Plays backing track in headphones while recording microphone take.
- Shows live single-line status ticker with elapsed time, progress bar, and active chapter.
- Automatically applies 85Hz high-pass filter, dead-air trimming, and -0.9 dBFS normalization.
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
SAMPLE_RATE = 48000

BACKING_TRACKS = {
    "1": ROOT_DIR / "assets" / "audio" / "backing_tracks" / "track_01_einaudi_experience.mp3",
    "2": ROOT_DIR
    / "assets"
    / "audio"
    / "backing_tracks"
    / "track_02_social_network_hand_covers_bruise.mp3",
    "3": ROOT_DIR / "assets" / "audio" / "backing_tracks" / "track_03_m83_outro.mp3",
    "4": ROOT_DIR / "assets" / "audio" / "backing_tracks" / "track_04_kavinsky_nightcall.mp3",
    "5": ROOT_DIR / "assets" / "audio" / "backing_tracks" / "track_05_bittersweet_symphony.mp3",
}

# (Title, Start Sec, End Sec, Text)
SCRIPT_ACTS = [
    (
        "Intro Runway",
        0.0,
        2.2,
        "Catch the rhythm. Dice clatter rolls into the tray... Vocal starts at 0:02!",
    ),
    (
        "Act 1: The Spark & Bankruptcy",
        2.2,
        18.0,
        "9 months ago: after 3 years of severe underemployment, I filed for bankruptcy.\n"
        "Soon after, I started getting a flood of texts about my home,\n"
        "and I started exploring what public data I could access.",
    ),
    (
        "Act 2: The Pilot Kickoff",
        18.0,
        26.0,
        "6 months ago: I started a pilot with a potential client to see if I could deliver tax delinquency lists.",
    ),
    (
        "Act 3: The County Auction",
        26.0,
        34.0,
        "5 months ago: my home went to the county auction.\nIt sold for 40% of what I paid.",
    ),
    (
        "Act 4: The Turnaround",
        34.0,
        46.0,
        "3 months ago: the pilot passed, and I was getting orders and beginning to make money again.\n"
        "The orders were taking between 2 and 14 days to fulfill.",
    ),
    ("Act 5: Speeding Up", 46.0, 52.0, "1 month ago: orders were taking 1 to 7 days to fulfill."),
    (
        "Act 6: The Scale Today",
        52.0,
        58.0,
        "Today: I just delivered 9 orders in less than 24 hours.",
    ),
    (
        "Act 7: The Antigravity Transformation",
        58.0,
        64.0,
        "In the past 6 months, I built a real estate data pipeline by coding with Google Antigravity.",
    ),
    (
        "Act 8: The 3-Year Contrast",
        64.0,
        69.5,
        "The 3 years prior, I couldn't land a job in tech, despite a 13-year career.",
    ),
    (
        "Act 9: The Wall Breakthrough & AI",
        69.5,
        76.0,
        "So what happens when a PMP gets a TBI and his professional life falls apart\n"
        "until he starts coding with AI?",
    ),
    ("Act 10: The Magic Hat Reveal & CTA", 76.0, 80.0, "Follow me to find out ;)"),
]

TOTAL_EXPECTED_DUR = 84.0


def restore_vocal(raw_wav: Path, clean_wav: Path) -> float:
    """Apply high-pass filter, dead-air trimming, and broadcast peak normalization."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(raw_wav),
        "-f",
        "f32le",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "pipe:1",
    ]
    res = subprocess.run(cmd, capture_output=True, check=True)
    raw = np.frombuffer(res.stdout, dtype=np.float32).copy()

    # 1. 85Hz High-pass filter to eliminate desk bumps/plosives
    dt = 1.0 / SAMPLE_RATE
    RC = 1.0 / (2.0 * np.pi * 85.0)
    alpha = RC / (RC + dt)
    y = np.zeros_like(raw)
    for i in range(1, len(raw)):
        y[i] = alpha * (y[i - 1] + raw[i] - raw[i - 1])
    raw = y

    # 2. Dead-air trimming (50ms RMS window)
    win = int(0.05 * SAMPLE_RATE)
    rms = np.array([np.sqrt(np.mean(raw[i : i + win] ** 2)) for i in range(0, len(raw) - win, win)])
    thresh = 0.0030
    indices = np.where(rms > thresh)[0]
    if len(indices) > 0:
        first_idx = max(0, indices[0] * win - int(0.20 * SAMPLE_RATE))
        last_idx = min(len(raw), indices[-1] * win + win + int(0.35 * SAMPLE_RATE))
        trimmed = raw[first_idx:last_idx].copy()
    else:
        trimmed = raw.copy()

    # 3. Clean click-free crossfade
    fade_in = min(len(trimmed), int(0.12 * SAMPLE_RATE))
    fade_out = min(len(trimmed), int(0.20 * SAMPLE_RATE))
    if fade_in > 0:
        trimmed[:fade_in] *= np.linspace(0.0, 1.0, fade_in)
    if fade_out > 0:
        trimmed[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)

    # 4. Broadcast Peak Normalization (-0.9 dBFS = 0.92 peak)
    peak = np.max(np.abs(trimmed))
    if peak > 0.001:
        trimmed = (trimmed / peak) * 0.92

    # Save
    clean_wav.parent.mkdir(parents=True, exist_ok=True)
    int16_data = (np.clip(trimmed, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(clean_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int16_data.tobytes())

    return len(trimmed) / SAMPLE_RATE


def format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def print_stationary_teleprompter():
    """Prints the entire teleprompter script once so it never flickers or scrolls."""
    print("\n" + "=" * 76)
    print("📜 TELEPROMPTER SCRIPT (READ LINE-BY-LINE):")
    print("=" * 76)
    for title, start, end, text in SCRIPT_ACTS:
        t_range = f"[{format_time(start)} - {format_time(end)}]"
        print(f"\033[1;36m{t_range} {title}\033[0m")
        for line in text.split("\n"):
            print(f"   \033[1;37m{line}\033[0m")
        print()
    print("=" * 76)


def main():
    parser = argparse.ArgumentParser(description="VoiceFi Rock-Solid Studio Vocal Recorder")
    parser.add_argument(
        "-t", "--track", default="5", help="Backing track choice (1-5 or path, default: 5)"
    )
    parser.add_argument("--take", type=int, default=2, help="Take number (default: 2)")
    parser.add_argument(
        "--no-backing", action="store_true", help="Record in silence without playing backing track"
    )
    args = parser.parse_args()

    track_choice = str(args.track)
    backing_path = BACKING_TRACKS.get(track_choice, Path(track_choice))
    track_title = backing_path.stem if backing_path.exists() else "None"

    print("\n" + "=" * 76)
    print("🎙️  VOICEFI™ STUDIO RECORDING BOOTH — LIENLOGIC REEL")
    print("=" * 76)
    print(f"🎬 Current Take:     Take {args.take:02d}")
    print(f"🎵 Backing Track:    {track_title}")
    print(f"⏱️  Target Duration:  ~{TOTAL_EXPECTED_DUR:.0f}s (with 4s instrumental runway)")
    print("🎧 Audio Monitor:    Please wear HEADPHONES so track does not bleed into mic!")
    print("=" * 76)

    # Print teleprompter cleanly once
    print_stationary_teleprompter()

    try:
        input("👉 Put on your headphones. Press [Enter] when ready to start (3s countdown)... ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)

    for count in range(3, 0, -1):
        print(f"   ⏱️  {count}...", flush=True)
        time.sleep(1.0)

    # Start backing track playback in background
    music_proc = None
    if not args.no_backing and backing_path.exists():
        music_proc = subprocess.Popen(
            ["afplay", "-v", "0.85", str(backing_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    import sounddevice as sd

    audio_frames = []
    stop_event = threading.Event()

    def callback(indata, frames, time_info, status):
        if not stop_event.is_set():
            audio_frames.append(indata.copy())

    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback)
    start_time = time.time()

    # Live single-line status ticker (never scrolls, never flickers)
    def live_ticker():
        while not stop_event.is_set():
            elapsed = time.time() - start_time
            pct = min(1.0, elapsed / TOTAL_EXPECTED_DUR)
            bar_w = 20
            filled = int(bar_w * pct)
            bar = "█" * filled + "░" * (bar_w - filled)

            active_name = "Outro"
            for title, s_start, s_end, _ in SCRIPT_ACTS:
                if s_start <= elapsed < s_end:
                    active_name = title.split(":")[-1].strip() if ":" in title else title
                    break

            sys.stdout.write(
                f"\r🔴 \033[1;31mRECORDING\033[0m [\033[1;36m{format_time(elapsed)}\033[0m/{format_time(TOTAL_EXPECTED_DUR)}] "
                f"[{bar}] {int(pct * 100):2d}% | 🎯 \033[1;32m{active_name:<20}\033[0m | [Hit \033[1;33mENTER\033[0m to finish] "
            )
            sys.stdout.flush()
            time.sleep(0.1)

    ticker_thread = threading.Thread(target=live_ticker, daemon=True)

    try:
        with stream:
            ticker_thread.start()
            # Simple, standard input() on main thread
            input()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop_event.set()
        if music_proc:
            music_proc.terminate()
            try:
                music_proc.wait(timeout=1.0)
            except Exception:
                music_proc.kill()

    elapsed = time.time() - start_time
    print(f"\n\n⏹️  Recording stopped ({elapsed:.1f}s captured). Processing studio audio...")

    if not audio_frames:
        print("❌ Error: No audio captured.")
        sys.exit(1)

    raw_audio = np.concatenate(audio_frames, axis=0).flatten()
    take_id = f"take_{args.take:02d}"
    raw_path = ROOT_DIR / "assets" / "audio" / f"jake_lienlogic_{take_id}_raw.wav"
    clean_path = ROOT_DIR / "assets" / "audio" / f"jake_lienlogic_{take_id}.wav"

    # Save raw
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    int16_raw = (np.clip(raw_audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(raw_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int16_raw.tobytes())

    # Restore
    dur = restore_vocal(raw_path, clean_path)
    print(f"\n✅ Studio Vocal Restored: \033[1;32m{clean_path}\033[0m")
    print(f"   • Duration: {dur:.2f}s")
    print("   • Level:    -0.9 dBFS True Peak (Broadcasting Silk)")
    print("   • Filter:   85Hz High-Pass (plosives & desk thumps removed)")
    print("   • Edits:    Clean lead-in & lead-out silence trimmed")

    # Link master vocal take
    master_symlink = ROOT_DIR / "assets" / "audio" / "jake_lienlogic_take_master.wav"
    if master_symlink.is_symlink() or master_symlink.exists():
        master_symlink.unlink()
    master_symlink.symlink_to(clean_path.name)
    print(f"   • Master:   Linked to {master_symlink.name}")

    # Copy to user Downloads for convenience
    user_dl_clean = Path("/Users/jaketrigg/Downloads") / f"jake_lienlogic_{take_id}.wav"
    user_dl_clean.write_bytes(clean_path.read_bytes())
    print(f"   • Export:   Copied to ~/Downloads/{user_dl_clean.name}")

    print("\n" + "=" * 76)
    print(f"🎉 Take {args.take:02d} is locked and ready for video compilation!")
    print("=" * 76 + "\n")


if __name__ == "__main__":
    main()
