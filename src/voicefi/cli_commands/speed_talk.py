"""
Speed Talking acceleration, preset configuration, testing, and analytics subcommands.
"""

import time
from pathlib import Path
from typing import Any
from voicefi.config import load_config, save_config
from voicefi.tts import get_tts_engine


def cmd_speed_talk(args):
    """Handle Speed Talking acceleration, preset configuration, testing, and analytics."""
    config = load_config(getattr(args, "config", None))
    from voicefi.audio.speed_talk import (
        SPEED_PRESETS,
        resolve_speed_multiplier,
        multiplier_to_wpm,
        multiplier_to_edge_rate,
        calculate_time_saved,
    )
    from voicefi.analytics.queries import get_speed_talking_analytics

    action = getattr(args, "action", None)
    if action:
        action = action.lower().strip()

    # Direct flag overrides
    if getattr(args, "enable", False) or getattr(args, "on", False):
        action = "on"
    elif getattr(args, "disable", False) or getattr(args, "off", False):
        action = "off"
    elif getattr(args, "stats", False):
        action = "stats"
    elif getattr(args, "demo", False):
        action = "demo"
    elif getattr(args, "ramp", False):
        action = "ramp"
    elif getattr(args, "test", False):
        action = "test"

    # If first argument is a preset name or multiplier e.g. 'vifi speed-talk fast' or 'vifi speed-talk 1.75x'
    if action in SPEED_PRESETS or (
        action
        and (action.endswith("x") or action.endswith("%") or action.replace(".", "", 1).isdigit())
    ):
        target_preset = action
        action = "set"
        args.preset_or_multiplier = target_preset

    if action in ("on", "enable", "start"):
        config.speed_talking.enabled = True
        val = getattr(args, "preset_or_multiplier", None) or getattr(args, "preset", None)
        if val:
            mult = resolve_speed_multiplier(val)
            config.speed_talking.multiplier = mult
            matched_preset = "fast"
            for pk, pv in SPEED_PRESETS.items():
                if abs(pv["multiplier"] - mult) < 0.05:
                    matched_preset = pk
                    break
            config.speed_talking.preset = matched_preset

        save_config(config)
        wpm = multiplier_to_wpm(config.speed_talking.multiplier)
        print("\n⚡ \033[1;32mSpeed Talking Enabled!\033[0m")
        print(f"  • Multiplier: \033[1;36m{config.speed_talking.multiplier}x\033[0m ({wpm} WPM)")
        print(f"  • Preset:     \033[1m{config.speed_talking.preset.title()}\033[0m")
        print(
            f"  • Pauses:     {'Tight Micro-Compression (150ms)' if config.speed_talking.compress_pauses else 'Standard'}"
        )
        print("  All agent responses and turn summaries will now stream at high velocity.\n")

        if not getattr(args, "silent", False) and not getattr(args, "quiet", False):
            try:
                eng = get_tts_engine(config, speed_override=config.speed_talking.multiplier)
                eng.speak(
                    f"Speed talking is active at {config.speed_talking.multiplier}x speed.",
                    block=True,
                )
            except Exception:
                pass
        return

    if action in ("off", "disable", "stop"):
        config.speed_talking.enabled = False
        save_config(config)
        print("\n🛑 \033[1;33mSpeed Talking Disabled.\033[0m")
        print("  Speech rate restored to baseline 1.0x (200 WPM).\n")
        return

    if action in ("set", "preset"):
        val = getattr(args, "preset_or_multiplier", None) or getattr(args, "preset", None)
        if not val:
            print(
                "⚠️ Please specify a speed preset or multiplier (e.g. 'vifi speed-talk set turbo' or 'vifi speed-talk 1.75x')."
            )
            return
        mult = resolve_speed_multiplier(val)
        config.speed_talking.multiplier = mult
        config.speed_talking.enabled = True
        matched_preset = "fast"
        for pk, pv in SPEED_PRESETS.items():
            if abs(pv["multiplier"] - mult) < 0.05:
                matched_preset = pk
                break
        config.speed_talking.preset = matched_preset
        save_config(config)
        wpm = multiplier_to_wpm(mult)
        print(
            f"\n⚡ \033[1;32mSpeed Talking set to {matched_preset.upper()} ({mult}x / {wpm} WPM)\033[0m"
        )
        print("  Configuration saved to ~/.voicefi/config.yaml.\n")
        if not getattr(args, "silent", False) and not getattr(args, "quiet", False):
            try:
                eng = get_tts_engine(config, speed_override=mult)
                eng.speak(f"Speed set to {mult}x velocity.", block=True)
            except Exception:
                pass
        return

    if action in ("list", "presets"):
        print("\n⚡ Curated Speed Talking Presets:")
        print(f"{'Preset':<14} {'Multiplier':<12} {'WPM':<10} {'Edge Rate':<12} {'Description'}")
        print("-" * 80)
        for pk, pv in SPEED_PRESETS.items():
            active_marker = (
                " 👈 ACTIVE"
                if (
                    config.speed_talking.enabled
                    and abs(config.speed_talking.multiplier - pv["multiplier"]) < 0.05
                )
                else ""
            )
            print(
                f"{pv['icon']} {pk:<12} {pv['multiplier']:<12.2f} {pv['wpm']:<10} {pv['edge_rate']:<12} {pv['description']}{active_marker}"
            )
        print()
        return

    if action == "test":
        target_val = (
            getattr(args, "preset_or_multiplier", None)
            or getattr(args, "preset", None)
            or config.speed_talking.multiplier
        )
        mult = resolve_speed_multiplier(target_val)
        wpm = multiplier_to_wpm(mult)
        sample_text = (
            getattr(args, "text", None)
            or f"Testing VoiceFi speed talking at {mult}x velocity. Consonants remain crisp, natural, and highly intelligible."
        )
        print(f"\n🎙️ Testing Speed Talking: \033[1;36m{mult}x\033[0m ({wpm} WPM)")
        print(f'💬 Phrase: "{sample_text}"\n')
        eng = get_tts_engine(config, speed_override=mult)
        eng.speak(sample_text, block=True)
        return

    if action == "ramp":
        target_val = (
            getattr(args, "preset_or_multiplier", None) or getattr(args, "preset", None) or 1.75
        )
        target_mult = resolve_speed_multiplier(target_val)
        sample_text = getattr(args, "text", None) or (
            "This phrase demonstrates dynamic speed ramping in VoiceFi. "
            "We start at normal conversational pace so your ears tune in easily, "
            "and smoothly escalate into high velocity turbo playback without losing any syllable clarity."
        )
        print(f"\n🚀 Auditioning Dynamic Speed Ramping (1.0x ➔ {target_mult}x)...")
        print(f'💬 Phrase: "{sample_text}"\n')
        from voicefi.audio.speed_talk import dynamic_ramp_audio
        import tempfile
        import subprocess

        with (
            tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf_in,
            tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf_out,
        ):
            in_p = Path(tf_in.name)
            out_p = Path(tf_out.name)
        try:
            eng = get_tts_engine(config, speed_override=1.0)
            if hasattr(eng, "speak_to_file") and eng.speak_to_file(sample_text, in_p):
                dynamic_ramp_audio(
                    in_p,
                    out_p,
                    start_multiplier=1.0,
                    target_multiplier=target_mult,
                    ramp_duration_s=2.5,
                )
                subprocess.run(["afplay", str(out_p)], check=True)
            else:
                eng_fast = get_tts_engine(config, speed_override=target_mult)
                eng_fast.speak(sample_text, block=True)
        finally:
            in_p.unlink(missing_ok=True)
            out_p.unlink(missing_ok=True)
        return

    if action == "demo":
        print("\n🎬 \033[1mVoiceFi Speed Talking Multi-Velocity Showcase\033[0m")
        print("Escalating across speed presets to demonstrate intelligibility:\n")
        demo_steps = [
            ("normal", 1.0, "1.0x Normal baseline: standard conversational delivery."),
            (
                "breezy",
                1.25,
                "1.25x Breezy pace: effortless acceleration with zero cognitive load.",
            ),
            (
                "fast",
                1.5,
                "1.5x Developer fast: the recommended sweet spot saving thirty-three percent time.",
            ),
            (
                "turbo",
                1.75,
                "1.75x Turbo velocity: high-speed response streaming with full clarity.",
            ),
            (
                "sonic",
                2.0,
                "2.0x Double speed sonic: cutting your audio listening duration strictly in half.",
            ),
            (
                "warp",
                2.5,
                "2.5x Warp speed: ultra-rapid soundbite delivery for power developers.",
            ),
        ]
        for name, mult, phrase in demo_steps:
            wpm = multiplier_to_wpm(mult)
            print(f'  • \033[1;36m{name.upper()} ({mult}x / {wpm} WPM)\033[0m: "{phrase}"')
            try:
                eng = get_tts_engine(config, speed_override=mult)
                eng.speak(phrase, block=True)
            except Exception as e:
                print(f"    ⚠️ Playback error: {e}")
            import time

            time.sleep(0.3)
        print("\n✨ Speed Talking showcase complete!\n")
        return

    if action == "stats":
        analytics = get_speed_talking_analytics(days=30)
        print("\n⚡ \033[1mVoiceFi Speed Talking Analytics (Last 30 Days)\033[0m")
        print("==================================================================")
        print(
            f"  • Active Status:          {'🟢 Enabled' if config.speed_talking.enabled else '⚪ Disabled'}"
        )
        print(
            f"  • Configured Multiplier:  {config.speed_talking.multiplier}x ({multiplier_to_wpm(config.speed_talking.multiplier)} WPM)"
        )
        print(f"  • Active Preset:          {config.speed_talking.preset.title()}")
        print(f"  • Total Accelerated Turns:{analytics['total_speed_turns']}")
        print(f"  • Average Speed Used:     {analytics['avg_multiplier']}x")
        print(
            f"  • Cumulative Time Saved:  \033[1;32m{analytics['total_minutes_saved']} minutes\033[0m ({analytics['total_hours_saved']} hours)"
        )
        print("==================================================================\n")
        return

    # Default: Show Speed Talking status overview card
    analytics = get_speed_talking_analytics(days=30)
    wpm = multiplier_to_wpm(config.speed_talking.multiplier)
    print("\n╭" + "─" * 66 + "╮")
    print("│ ⚡ \033[1mVoiceFi Speed Talking • Productivity Voice Engine\033[0m            │")
    print("╰" + "─" * 66 + "╯")
    status_label = (
        "🟢 \033[1;32mACTIVE\033[0m"
        if config.speed_talking.enabled
        else "⚪ \033[2mDisabled\033[0m (1.0x baseline)"
    )
    print(f"  • Status:           {status_label}")
    print(
        f"  • Speed Multiplier: \033[1;36m{config.speed_talking.multiplier}x\033[0m ({wpm} WPM / {multiplier_to_edge_rate(config.speed_talking.multiplier)})"
    )
    print(f"  • Preset:           \033[1m{config.speed_talking.preset.title()}\033[0m")
    print(
        f"  • Pause Reduction:  {'Tight Micro-Compression (150ms)' if config.speed_talking.compress_pauses else 'Disabled'}"
    )
    print(
        f"  • Clarity Boost:    {'High-Frequency Consonant Presence EQ' if config.speed_talking.enhance_clarity else 'Off'}"
    )
    print(
        f"  • 30-Day Time Saved:\033[1;32m+{analytics['total_minutes_saved']} mins\033[0m ({analytics['total_hours_saved']} hrs saved)"
    )
    print("\n👉 \033[1mQuick Commands:\033[0m")
    print("   • \033[1;36mvifi speed-talk on\033[0m           Enable speed talking globally")
    print(
        "   • \033[1;36mvifi speed-talk set turbo\033[0m    Set preset (normal, breezy, fast, turbo, sonic, warp)"
    )
    print("   • \033[1;36mvifi speed-talk 1.75x\033[0m        Set exact speed multiplier")
    print("   • \033[1;36mvifi speed-talk test\033[0m         Audition at current speed")
    print("   • \033[1;36mvifi speed-talk demo\033[0m         Play multi-speed showcase")
    print("   • \033[1;36mvifi speed-talk off\033[0m          Restore standard 1.0x speed\n")
