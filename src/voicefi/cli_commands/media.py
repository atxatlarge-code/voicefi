"""
CLI commands for audio effects, sound FX cues, media trimming, acoustic banter duels, and social video reels.
"""

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from voicefi.config import load_config
from voicefi.tts import get_tts_engine

logger = logging.getLogger(__name__)


def cmd_duel(args: Any) -> None:
    """Run an acoustic voice banter / joke duel between Antigravity and Claude Code."""
    turns = getattr(args, "turns", 3) or 3
    live = getattr(args, "live", False)

    cfg = load_config()
    tts_antigravity = get_tts_engine(cfg, agent_name="antigravity")
    tts_claude = get_tts_engine(cfg, agent_name="claude")

    rounds = [
        (
            "Hey Claude! Why do programmers prefer dark mode? ... Because light attracts bugs! Alright Claude, your turn. Hit me with one back!",
            "Haha, classic! Alright Antigravity, try this one: Why did the neural network cross the road? ... To optimize the loss function on the other side! Give me round two!",
        ),
        (
            "Stochastic humor, I love it! Here is my second one: There are 10 types of people in the world... those who understand binary, and those who do not. Your move, Claude!",
            "Very retro! Here is mine: Why was the JavaScript developer sad? ... Because they did not Node how to Express themselves! Hit me with your third one, Antigravity!",
        ),
        (
            "Poor JavaScript, always asynchronously crying! Alright, here is my final joke: A SQL query walks into a bar, walks up to two tables and asks... Can I join you? Claude, bring us home with your grand finale!",
            "Brilliant relational humor! Here is the grand finale: How many programmers does it take to change a lightbulb? ... None, that is a hardware problem! That was three rounds of high-latency comedy, Antigravity. Great bantering with you!",
        ),
    ]

    print("\n🎭 ══════════════════════════════════════════════════════════════════")
    print("   VoiceFi Acoustic Voice Banter Test: Ava ↔ Steffan")
    print(
        f"   Rounds: {min(turns, len(rounds))} | Mode: Audio Benchmark | Live Dispatch: {'ON' if live else 'OFF'}"
    )
    print("══════════════════════════════════════════════════════════════════\n")

    for i in range(min(turns, len(rounds))):
        joke_ag, joke_cl = rounds[i]
        print(f"--- [Round {i+1}] Antigravity Speaks ---")
        print(f'🤖 Ava: "{joke_ag}"')
        t0 = time.time()
        tts_antigravity.speak(joke_ag, block=True)
        print(f"   ⏱️ Playback latency: {round((time.time() - t0)*1000)}ms\n")
        time.sleep(0.4)

        print(f"--- [Round {i+1}] Claude Code Responds ---")
        print(f'🤖 Steffan: "{joke_cl}"')
        t0 = time.time()
        tts_claude.speak(joke_cl, block=True)
        print(f"   ⏱️ Playback latency: {round((time.time() - t0)*1000)}ms\n")
        time.sleep(0.6)

    print("✨ Voice duel session completed successfully!\n")


def cmd_sfx(args: Any) -> None:
    """Play a comedy or dramatic sound effect (drum_smash, honk, sad_trombone, applause, boing, crickets)."""
    name = getattr(args, "name", "drum_smash") or "drum_smash"
    volume = getattr(args, "volume", 1.0) or 1.0
    from voicefi.audio.sfx import play_sfx, list_available_sfx

    if name == "list":
        print(f"🎵 Available sound effects: {', '.join(list_available_sfx())}")
        return
    success = play_sfx(name, block=True, volume=volume)
    if not success:
        print(f"⚠️ Unknown SFX: '{name}'. Available: {list_available_sfx()}", file=sys.stderr)
        sys.exit(1)


def cmd_fx(args: Any) -> None:
    """Apply studio voice transformation DSP effect (radio announcer, podcast, monster, etc.)."""
    from voicefi.audio.effects import VoiceFXEngine, FX_PRESETS

    in_file = getattr(args, "input", None)
    if not in_file or in_file == "list":
        print("\n📻 Available Voice FX Presets:")
        for p in FX_PRESETS.values():
            print(f"  • {p['icon']} {p['id']:<20} - {p['name']} ({p['description']})")
        print()
        return

    in_path = Path(in_file).resolve()
    if not in_path.is_file():
        print(f"❌ Input audio file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    preset = getattr(args, "preset", "radio_announcer") or "radio_announcer"
    out_file = getattr(args, "output", None)
    if not out_file:
        out_file = in_path.parent / f"{in_path.stem}_{preset}.mp3"
    out_path = Path(out_file).resolve()

    print(f"🎛️  Applying voice effect '{preset}' to {in_path.name}...")
    try:
        res = VoiceFXEngine.apply_effect(
            input_audio=in_path, output_audio=out_path, preset=preset, normalize_loudness=True
        )
        info = VoiceFXEngine.get_audio_info(res)
        print(f"✅ Master audio created: {res} ({info['duration']}s · {info['size_formatted']})")
    except Exception as e:
        print(f"❌ FX error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reel(args: Any) -> None:
    """Compile multi-format social video reels from audio and slides, or documentary mode."""
    if (
        getattr(args, "doc", False)
        or getattr(args, "input", "") in ("doc", "documentary")
        or getattr(args, "script", None)
    ):
        from voicefi.video.documentary_reel import cmd_documentary_reel

        return cmd_documentary_reel(args)

    from voicefi.video.reel_builder import ReelBuilder

    in_file = getattr(args, "input", None)
    if not in_file:
        print("❌ Please specify input audio file: vifi reel <audio_file>", file=sys.stderr)
        sys.exit(1)

    in_path = Path(in_file).resolve()
    if not in_path.is_file():
        print(f"❌ Audio file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    fmt = getattr(args, "format", "9:16") or "9:16"
    typo = getattr(args, "preset", "classic_ai") or "classic_ai"
    speaker = getattr(args, "speaker", "Radio Host") or "Radio Host"
    scale = getattr(args, "font_scale", 1.0) or 1.0

    out_file = getattr(args, "output", None)
    if not out_file:
        fmt_clean = fmt.replace(":", "_")
        out_file = in_path.parent / f"{in_path.stem}_{fmt_clean}.mp4"
    out_path = Path(out_file).resolve()

    print(f"🎬 Compiling {fmt} Social Reel with '{typo}' typography for {in_path.name}...")
    try:
        res = ReelBuilder.compile_reel(
            output_mp4=out_path,
            audio_file=in_path,
            format_type=fmt,
            preset_name=typo,
            font_multiplier=scale,
            speaker_name=speaker,
        )
        print(f"✅ Reel ready: {res} ({res.stat().st_size / 1024:.1f} KB)")
        if getattr(args, "open", False):
            subprocess.run(["open", str(res)])
    except Exception as e:
        print(f"❌ Reel compilation error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_trim(args: Any) -> None:
    """Trim audio file start and end points with smooth de-clicking fades."""
    from voicefi.audio.effects import VoiceFXEngine

    in_file = getattr(args, "input", None)
    if not in_file:
        print(
            "❌ Please specify input audio file: vifi trim <audio_file> --start <seconds> --end <seconds>",
            file=sys.stderr,
        )
        sys.exit(1)

    in_path = Path(in_file).resolve()
    if not in_path.is_file():
        print(f"❌ Input audio file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    start_sec = float(getattr(args, "start", 0.0) or 0.0)
    raw_end = getattr(args, "end", None)
    end_sec = float(raw_end) if raw_end is not None else None

    out_file = getattr(args, "output", None)
    if not out_file:
        stem = in_path.stem
        out_file = in_path.parent / f"{stem}_trimmed.mp3"
    out_path = Path(out_file).resolve()

    print(
        f"✂️  Trimming {in_path.name} from {start_sec:.2f}s to {end_sec if end_sec is not None else 'end'}..."
    )
    try:
        res = VoiceFXEngine.trim_audio(
            input_audio=in_path, output_audio=out_path, start_sec=start_sec, end_sec=end_sec
        )
        info = VoiceFXEngine.get_audio_info(res)
        print(f"✅ Trimmed audio created: {res} ({info['duration']}s · {info['size_formatted']})")
    except Exception as e:
        print(f"❌ Trim error: {e}", file=sys.stderr)
        sys.exit(1)
