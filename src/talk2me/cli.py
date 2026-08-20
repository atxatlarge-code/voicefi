"""
CLI interface for Talk 2 Me.
Supports Antigravity hook integration, one-shot voice dictation, daemon loop, and setup.
"""

import argparse
import json
import sys
from pathlib import Path

from talk2me import __version__
from talk2me.config import load_config, save_config, get_default_config_path
from talk2me.license import FeatureGate
from talk2me.tts import get_tts_engine, MacSayTTS
from talk2me.stt import get_stt_engine
from talk2me.audio.recorder import AudioRecorder
from talk2me.audio.chimes import play_chime
from talk2me.integrations.antigravity import handle_antigravity_stop_hook
from talk2me.integrations.injector import inject_text_to_active_app


def cmd_hook(args):
    """Handle Antigravity lifecycle hook from stdin."""
    config = load_config(args.config)

    # Read hook payload from stdin
    try:
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input) if raw_input.strip() else {}
    except Exception:
        payload = {}

    result = handle_antigravity_stop_hook(payload, config)
    # Output empty JSON object as required by hook contract
    print(json.dumps(result))


def cmd_speak(args):
    """Speak text aloud using the configured TTS provider."""
    config = load_config(args.config)
    tts = get_tts_engine(config)
    text = " ".join(args.text)
    print(f"🔊 Speaking: {text}")
    tts.speak(text, block=True)


def cmd_listen(args):
    """Record speech from mic until silence and transcribe."""
    config = load_config(args.config)

    if config.audio_cues.enabled and not args.quiet:
        play_chime("start", block=False)

    print("🎙️ Listening... (speak and then pause)")
    recorder = AudioRecorder(
        sample_rate=config.vad.sample_rate,
        energy_threshold=config.vad.energy_threshold,
        silence_duration=config.vad.silence_duration,
        max_record_seconds=config.vad.max_record_seconds,
    )

    audio_data, temp_wav = recorder.record_speech_auto(
        on_speech_start=lambda: print("🗣️ Speech detected...")
    )

    print("⏳ Transcribing...")
    stt = get_stt_engine(config)
    try:
        text = stt.transcribe(temp_wav)
    finally:
        temp_wav.unlink(missing_ok=True)

    if text:
        if config.audio_cues.enabled and not args.quiet:
            play_chime("done", block=False)
        print(f"\n📝 Transcribed: {text}\n")

        if args.inject:
            inject_text_to_active_app(text, submit_enter=args.enter)
            print("🚀 Injected into active window.")
    else:
        print("⚠️ No speech detected.")


def cmd_loop(args):
    """Interactive continuous voice loop."""
    config = load_config(args.config)
    print("🔁 Starting Talk 2 Me continuous loop. Press Ctrl+C to exit.\n")
    try:
        while True:
            cmd_listen(args)
    except KeyboardInterrupt:
        print("\n👋 Talk 2 Me loop stopped.")


def cmd_tray(args):
    """Launch macOS menu bar tray companion."""
    from talk2me.ui.tray import run_tray
    print("🚀 Launching Talk 2 Me menu bar tray...")
    run_tray()


def cmd_setup(args):
    """Automatically register Talk 2 Me hook with Antigravity."""
    global_hooks_path = Path.home() / ".gemini" / "config" / "hooks.json"
    global_hooks_path.parent.mkdir(parents=True, exist_ok=True)

    hooks_data = {}
    if global_hooks_path.is_file():
        try:
            with open(global_hooks_path, "r", encoding="utf-8") as f:
                hooks_data = json.load(f) or {}
        except Exception:
            hooks_data = {}

    hook_command = "talk2me hook"
    hooks_data["talk2me-voice-layer"] = {
        "enabled": True,
        "Stop": [
            {
                "type": "command",
                "command": hook_command,
                "timeout": 60,
            }
        ],
    }

    with open(global_hooks_path, "w", encoding="utf-8") as f:
        json.dump(hooks_data, f, indent=2)

    # Also save default config if missing
    config_path = get_default_config_path()
    if not config_path.is_file():
        save_config(load_config())

    print(f"✅ Talk 2 Me hook successfully installed into: {global_hooks_path}")
    print(f"⚙️ Configuration saved at: {config_path}")


def cmd_info(args):
    """Display active configuration and system capabilities."""
    config = load_config(args.config)
    tier_info = FeatureGate.get_tier_summary(config)

    print(f"\n================ Talk 2 Me v{__version__} ================")
    print(f"Tier:          {tier_info['tier']}")
    print(f"TTS Provider:  {config.tts.provider} (Voice: {config.tts.voice})")
    print(f"STT Provider:  {config.stt.provider} (Model: {config.stt.model_size})")
    print(f"VAD Silence:   {config.vad.silence_duration}s")
    print(f"Auto-Listen:   {config.antigravity.auto_listen}")
    print(f"Read Aloud:    {config.antigravity.read_summary_aloud}")
    print("====================================================\n")

    print("Available macOS Voices:")
    voices = MacSayTTS.list_available_voices()
    print(", ".join(voices[:12]) + ("..." if len(voices) > 12 else ""))
    print()


def main():
    parser = argparse.ArgumentParser(
        prog="talk2me",
        description="Hands-free voice layer for Antigravity and macOS desktop use.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to custom config.yaml")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # hook
    subparsers.add_parser("hook", help="Run as Antigravity lifecycle hook")

    # speak
    speak_p = subparsers.add_parser("speak", help="Speak text aloud")
    speak_p.add_argument("text", nargs="+", help="Text to speak")

    # listen
    listen_p = subparsers.add_parser("listen", help="Listen from microphone and transcribe")
    listen_p.add_argument("--no-inject", dest="inject", action="store_false", default=True, help="Do not inject into active app")
    listen_p.add_argument("--no-enter", dest="enter", action="store_false", default=True, help="Do not press Enter after pasting")
    listen_p.add_argument("-q", "--quiet", action="store_true", help="Disable audio feedback chimes")

    # loop
    loop_p = subparsers.add_parser("loop", help="Start continuous voice loop")
    loop_p.add_argument("--no-inject", dest="inject", action="store_false", default=True)
    loop_p.add_argument("--no-enter", dest="enter", action="store_false", default=True)
    loop_p.add_argument("-q", "--quiet", action="store_true")

    # tray
    subparsers.add_parser("tray", help="Launch macOS menu bar companion")

    # setup
    subparsers.add_parser("setup", help="Auto-configure Antigravity lifecycle hooks")

    # info
    subparsers.add_parser("info", help="Show system status and voices")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "hook": cmd_hook,
        "speak": cmd_speak,
        "listen": cmd_listen,
        "loop": cmd_loop,
        "tray": cmd_tray,
        "setup": cmd_setup,
        "info": cmd_info,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)


if __name__ == "__main__":
    main()
