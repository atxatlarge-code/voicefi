"""
Audio, speech synthesis, listening, continuous loop, VAD panel, and recording CLI subcommands.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any

from voicefi.config import load_config
from voicefi.tts import (
    get_tts_engine,
    set_cross_process_hud_state,
    clear_cross_process_hud_state,
)
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.antigravity import handle_antigravity_stop_hook
from voicefi.integrations.injector import inject_text_to_active_app


def _resolve_load_config(*args, **kwargs):
    cli_mod = sys.modules.get("voicefi.cli")
    fn = getattr(cli_mod, "load_config", load_config) if cli_mod else load_config
    return fn(*args, **kwargs)


def _resolve_get_tts_engine(*args, **kwargs):
    cli_mod = sys.modules.get("voicefi.cli")
    fn = getattr(cli_mod, "get_tts_engine", get_tts_engine) if cli_mod else get_tts_engine
    return fn(*args, **kwargs)


def cmd_speak(args):
    """Speak text aloud using the configured TTS provider."""
    config = _resolve_load_config(args.config)
    agent = getattr(args, "agent", None)
    # Default to antigravity if agent not specified but antigravity is configured
    if agent is None and "antigravity" in config.agents:
        agent = "antigravity"
    voice_override = getattr(args, "voice", None)
    provider_override = getattr(args, "provider", None)
    rate_override = getattr(args, "rate", None)
    speed_override = getattr(args, "speed", None) or getattr(args, "speed_talk", None)
    if getattr(args, "fast", False) and not speed_override:
        speed_override = "fast"
    tts = _resolve_get_tts_engine(
        config,
        agent_name=agent,
        voice_override=voice_override,
        provider_override=provider_override,
        rate_override=rate_override,
        speed_override=speed_override,
    )
    text = " ".join(args.text)
    try:
        from voicefi.integrations.conversations import claim_active_conversation_turn

        claim_active_conversation_turn(text)
    except Exception:
        pass
    print(f"🔊 Speaking ({tts.voice}): {text}")
    start_speak = time.time()
    err = None
    try:
        tts.speak(text, block=True)
    except Exception as e:
        err = type(e).__name__
        raise
    finally:
        dur_ms = int((time.time() - start_speak) * 1000)
        try:
            from voicefi.telemetry import capture_voice_interaction

            capture_voice_interaction(
                trigger="speak",
                duration_ms=dur_ms,
                success=(err is None),
                agent=agent,
                voice=tts.voice,
                provider=getattr(tts, "provider", None),
                chars_count=len(text) if text else 0,
                error_type=err,
            )
        except Exception:
            pass


def cmd_listen(args):
    """Record speech from mic until silence and transcribe."""
    config = load_config(args.config)

    if config.audio_cues.enabled and not args.quiet:
        play_chime("start", block=False)

    print("🎙️ Listening... (speak and then pause)")
    set_cross_process_hud_state("listening", user_name=config.user_name)
    recorder = AudioRecorder(
        sample_rate=config.vad.sample_rate,
        energy_threshold=config.vad.energy_threshold,
        silence_duration=config.vad.silence_duration,
        max_record_seconds=config.vad.max_record_seconds,
        barge_in=False,
    )

    def _on_pause(paused: bool):
        if paused:
            print("⏸️ Agent speaking aloud -> listening paused...")
            set_cross_process_hud_state("paused_agent_speaking", text="Agent Speaking (Paused)...")
        else:
            print("🎙️ Agent finished -> listening resumed...")
            set_cross_process_hud_state("listening", user_name=config.user_name)

    def _on_speech_start():
        print("🗣️ Speech detected...")
        set_cross_process_hud_state("hearing", user_name=config.user_name)

    audio_data, temp_wav = recorder.record_speech_auto(
        on_speech_start=_on_speech_start,
        on_pause_change=_on_pause,
    )

    print("⏳ Transcribing...")
    set_cross_process_hud_state("transcribing")
    stt = get_stt_engine(config)
    try:
        text = stt.transcribe(temp_wav)
    finally:
        temp_wav.unlink(missing_ok=True)

    if text:
        print(f"\n📝 Transcribed: {text}\n")
        set_cross_process_hud_state("done", text=text[:20])

        target_engine = getattr(args, "to", "active")
        if target_engine in ("antigravity", "claude"):
            from voicefi.integrations.injector import send_message_to_agent

            res = send_message_to_agent(target_engine=target_engine, text=text)
            if res.success:
                print(
                    f"🚀 Sent directly to {target_engine.capitalize()} via background IPC (0 focus change)."
                )
            else:
                print(f"⚠️ IPC dispatch notice: {res.error} — falling back to active app injection.")
                if args.inject:
                    inject_text_to_active_app(text, submit_enter=args.enter)
        elif args.inject:
            if inject_text_to_active_app(text, submit_enter=args.enter):
                print("Sent to active conversation.")
            else:
                print("⚠️ Injection failed — text left on clipboard.")

        if config.audio_cues.enabled and not args.quiet:
            play_chime(config.audio_cues.sent_chime, block=False)
    else:
        print("⚠️ No speech detected.")

    clear_cross_process_hud_state()


def cmd_loop(args):
    """Interactive continuous voice loop."""
    config = load_config(args.config)
    print("🔁 Starting VoiceFi continuous loop. Press Ctrl+C to exit.\n")
    try:
        while True:
            cmd_listen(args)
    except KeyboardInterrupt:
        print("\n👋 VoiceFi loop stopped.")


def cmd_vad(args):
    """Open the Expert VAD & Acoustic Inspector Panel."""
    import AppKit
    from voicefi.ui.expert_vad import ExpertVADPanel
    from voicefi.audio.monitor import LiveVADMonitor

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    LiveVADMonitor.get_instance().start()

    panel = ExpertVADPanel.get_instance()
    panel.show()
    app.activateIgnoringOtherApps_(True)
    AppKit.NSApp.run()


def cmd_record(args):
    """Record studio voice note directly from microphone."""
    import time
    import wave
    import sounddevice as sd

    duration = float(getattr(args, "duration", 8.0) or 8.0)
    out_file = (
        getattr(args, "output", None) or getattr(args, "out", None) or "assets/jake_intro.wav"
    )
    out_path = Path(out_file).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48000

    print("\n" + "=" * 60)
    print("🎙️  VoiceFi™ Live Voice Note Recorder")
    print("=" * 60)
    print(f"👉 Target File: {out_path}")
    print(f"👉 Duration: {duration}s (Press Ctrl+C to stop early)")
    print("\nGet ready... Recording starts in:")
    for i in range(3, 0, -1):
        print(f"   {i}...", flush=True)
        time.sleep(1)

    print("\n🔴 RECORDING NOW! (Speak into your mic)...", flush=True)
    try:
        recording = sd.rec(
            int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype="int16"
        )
        for elapsed in range(int(duration)):
            time.sleep(1)
            bar = "█" * (elapsed + 1) + "░" * (int(duration) - elapsed - 1)
            print(f"\r[{bar}] {elapsed + 1}s / {int(duration)}s", end="", flush=True)
        sd.wait()
    except KeyboardInterrupt:
        sd.stop()
        print("\n\n⏹️  Stopped by user.")

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(recording.tobytes())

    print(f"\n\n💾 Saved voice track to: {out_path}")
    print("=" * 60 + "\n")


def cmd_bias(args):
    """Test and inspect developer STT vocabulary biasing and phonetic normalization."""
    from voicefi.stt.biasing import ProjectContextExtractor, PhoneticNormalizer

    extractor = ProjectContextExtractor()
    symbols = extractor.extract_symbols()
    prompt = extractor.get_bias_prompt()

    input_text = getattr(args, "text", None)
    if input_text:
        text_str = " ".join(input_text) if isinstance(input_text, list) else str(input_text)
        normalized = PhoneticNormalizer.normalize(text_str)
        print(f"\n🗣️ Spoken Input:      {text_str}")
        print(f"✨ Normalized Syntax: {normalized}\n")
    else:
        print("\n🧠 Active Developer STT Vocabulary Biasing:")
        print(f"📁 Project Root: {extractor.root_dir}")
        print(f"🔑 Extracted Symbols ({len(symbols)}): {', '.join(symbols[:20])}...")
        print(f'\n📋 Full Whisper / Groq Bias Prompt:\n"{prompt}"\n')
