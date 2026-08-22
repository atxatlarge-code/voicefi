"""
CLI interface for Voicegency.
Supports Antigravity hook integration, one-shot voice dictation, daemon loop, and setup.
"""

import argparse
import json
import sys
from pathlib import Path

from voicegency import __version__
from voicegency.config import load_config, save_config, get_default_config_path
from voicegency.license import FeatureGate
from voicegency.tts import get_tts_engine, MacSayTTS
from voicegency.stt import get_stt_engine
from voicegency.audio.recorder import AudioRecorder
from voicegency.audio.chimes import play_chime
from voicegency.integrations.antigravity import handle_antigravity_stop_hook
from voicegency.integrations.injector import inject_text_to_active_app
from voicegency.memo import (
    MemoBufferRecorder,
    MemoSynthesizer,
    MemoStore,
    MemoRecording,
)


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
    agent = getattr(args, "agent", None)
    # Default to antigravity if agent not specified but antigravity is configured
    if agent is None and "antigravity" in config.agents:
        agent = "antigravity"
    voice_override = getattr(args, "voice", None)
    provider_override = getattr(args, "provider", None)
    rate_override = getattr(args, "rate", None)
    tts = get_tts_engine(
        config,
        agent_name=agent,
        voice_override=voice_override,
        provider_override=provider_override,
        rate_override=rate_override,
    )
    text = " ".join(args.text)
    print(f"🔊 Speaking ({tts.voice}): {text}")
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

    def _on_pause(paused: bool):
        if paused:
            print("⏸️ Agent speaking aloud -> listening paused...")
        else:
            print("🎙️ Agent finished -> listening resumed...")

    audio_data, temp_wav = recorder.record_speech_auto(
        on_speech_start=lambda: print("🗣️ Speech detected..."),
        on_pause_change=_on_pause,
    )

    print("⏳ Transcribing...")
    stt = get_stt_engine(config)
    try:
        text = stt.transcribe(temp_wav)
    finally:
        temp_wav.unlink(missing_ok=True)

    if text:
        print(f"\n📝 Transcribed: {text}\n")

        if args.inject:
            inject_text_to_active_app(text, submit_enter=args.enter)
            print("🚀 Injected into active window.")

        if config.audio_cues.enabled and not args.quiet:
            play_chime(config.audio_cues.sent_chime, block=False)
    else:
        print("⚠️ No speech detected.")


def cmd_loop(args):
    """Interactive continuous voice loop."""
    config = load_config(args.config)
    print("🔁 Starting Voicegency continuous loop. Press Ctrl+C to exit.\n")
    try:
        while True:
            cmd_listen(args)
    except KeyboardInterrupt:
        print("\n👋 Voicegency loop stopped.")


def cmd_tray(args):
    """Launch macOS menu bar tray companion."""
    from voicegency.ui.tray import run_tray
    print("🚀 Launching Voicegency menu bar tray...")
    run_tray()


def cmd_dev(args):
    """Launch Voicegency in foreground development mode with live console logs."""
    from voicegency.ui.tray import run_tray
    print("🚀 Launching Voicegency in DEV mode (live logs active, Ctrl+C to exit)...")
    run_tray()


def cmd_setup(args):
    """Automatically register Voicegency hook with Antigravity."""
    import shutil
    global_hooks_path = Path.home() / ".gemini" / "config" / "hooks.json"
    global_hooks_path.parent.mkdir(parents=True, exist_ok=True)

    hooks_data = {}
    if global_hooks_path.is_file():
        try:
            with open(global_hooks_path, "r", encoding="utf-8") as f:
                hooks_data = json.load(f) or {}
        except Exception:
            hooks_data = {}

    # Prefer current venv executable path for reliable invocation
    venv_bin = Path(sys.executable).parent / "voicegency"
    if venv_bin.exists():
        bin_path = str(venv_bin)
    else:
        bin_path = shutil.which("voicegency") or "voicegency"

    hook_command = f"{bin_path} hook"
    hooks_data["voicegency-voice-layer"] = {
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

    print(f"✅ Voicegency hook successfully installed into: {global_hooks_path}")
    print(f"⚙️ Configuration saved at: {config_path}")


def cmd_autostart(args):
    """Register macOS LaunchAgent so Voicegency menu bar tray stays on and runs at login."""
    import shutil
    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents_dir / "com.voicegency.menubar.plist"

    venv_bin = Path(sys.executable).parent / "voicegency"
    bin_path = str(venv_bin) if venv_bin.exists() else (shutil.which("voicegency") or "voicegency")

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.voicegency.menubar</string>
    <key>ProgramArguments</key>
    <array>
        <string>{bin_path}</string>
        <string>tray</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/voicegency.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/voicegency.err</string>
</dict>
</plist>
"""
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(plist_content)

    import subprocess
    subprocess.run(["launchctl", "unload", str(plist_path)], stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "load", str(plist_path)])

    print(f"✅ Voicegency menu bar companion registered to start automatically at login.")
    print(f"📌 Plist installed at: {plist_path}")


def cmd_stop_autostart(args):
    """Unload and remove macOS LaunchAgent."""
    import subprocess
    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.voicegency.menubar.plist"
    if plist_path.is_file():
        subprocess.run(["launchctl", "unload", str(plist_path)], stderr=subprocess.DEVNULL)
        plist_path.unlink(missing_ok=True)
        print("🛑 Voicegency menu bar companion autostart removed.")
    else:
        print("ℹ️ No active autostart service found.")


from voicegency.tts.catalog import (
    CURATED_PERSONAS,
    get_curated_personas,
    find_persona,
    list_all_available_voices,
)
from voicegency.tts.cloning import VoiceCloneManager, TRAINING_PROMPTS
from voicegency.feedback import submit_feedback, list_feedback, collect_system_diagnostics


def cmd_clone(args):
    """Train, record, import, test, assign, and manage custom cloned voices."""
    import time
    manager = VoiceCloneManager()
    config = load_config(args.config)
    subaction = getattr(args, "clone_action", None)

    if not subaction:
        # Default to listing if no subaction provided
        subaction = "list"

    if subaction == "record":
        name = args.name.strip()
        print(f"\n🎙️ Starting Voice Training Session for: '{name}'")
        print("=" * 65)
        print("We will record phonetically balanced sample phrases to capture your")
        print("vocal timbre, pitch range, tempo, and natural cadence.\n")

        recorder = AudioRecorder(sample_rate=16000, energy_threshold=0.004, silence_duration=1.2)
        recorded_files = []

        for i, p in enumerate(TRAINING_PROMPTS):
            print(f"[{i+1}/{len(TRAINING_PROMPTS)}] {p['title']}:")
            print(f"👉 \"{p['text']}\"")
            try:
                input("Press [ENTER] when ready to speak...")
            except EOFError:
                pass

            if config.audio_cues.enabled:
                play_chime("start", block=False)
            print("🔴 Recording... (speak the phrase and pause)")
            _, wav_path = recorder.record_speech_auto()
            recorded_files.append(wav_path)
            print(f"✅ Sample {i+1} captured.\n")
            time.sleep(0.3)

        api_key = getattr(args, "api_key", None) or config.tts.elevenlabs_api_key
        print("🧠 Processing acoustic features and training voice profile...")
        try:
            profile = manager.train_voice(
                name=name,
                sample_paths=recorded_files,
                api_key=api_key,
                description=getattr(args, "description", "") or f"Voice clone of {name}",
            )
            print(f"\n✨ Voice Training Complete!")
            print(f"  • Voice Name:    {profile.name}")
            print(f"  • Voice ID:      {profile.id}")
            print(f"  • Provider:      {profile.provider}")
            print(f"  • Vocal Range:   {profile.acoustic_metrics.get('vocal_range', 'Unknown')}")
            print(f"  • Avg Pitch:     {profile.acoustic_metrics.get('avg_pitch_hz')} Hz")
            print(f"  • Total Audio:   {profile.acoustic_metrics.get('total_duration_seconds')}s")

            target_agent = getattr(args, "assign", None)
            if target_agent:
                manager.assign_to_agent(profile.name, target_agent, config)
                print(f"  • Assigned to:   {target_agent}")

            print("\nTest your voice with:  vg clone test " + profile.name)
            print("Assign to agent with: vg clone assign " + profile.name + " antigravity\n")
        finally:
            for wf in recorded_files:
                try:
                    wf.unlink(missing_ok=True)
                except Exception:
                    pass

    elif subaction == "import":
        name = args.name.strip()
        files = [Path(f) for f in args.files]
        valid_files = [f for f in files if f.exists()]
        if not valid_files:
            print("❌ Error: No valid audio files found.")
            return

        api_key = getattr(args, "api_key", None) or config.tts.elevenlabs_api_key
        print(f"\n📥 Importing {len(valid_files)} audio samples for voice: '{name}'...")
        profile = manager.train_voice(
            name=name,
            sample_paths=valid_files,
            api_key=api_key,
            description=getattr(args, "description", "") or f"Imported voice of {name}",
        )
        print(f"✅ Successfully trained cloned voice: '{profile.name}' ({profile.provider})")
        print(f"  • ID:          {profile.id}")
        print(f"  • Vocal Range: {profile.acoustic_metrics.get('vocal_range', 'Unknown')}")
        target_agent = getattr(args, "assign", None)
        if target_agent:
            manager.assign_to_agent(profile.name, target_agent, config)
            print(f"  • Assigned to: {target_agent}")
        print()

    elif subaction == "list":
        clones = manager.list_cloned_voices()
        if not clones:
            print("\nℹ️ No custom cloned voices found.")
            print("Train one now with: 'vg clone record <your_name>'\n")
            return

        print(f"\n🎙️ Trained Custom Voices ({len(clones)}):")
        print(f"{'Name':<16} {'Voice ID':<26} {'Provider':<12} {'Vocal Range':<18} {'Assigned To'}")
        print("-" * 85)
        for cv in clones:
            v_range = cv.acoustic_metrics.get("vocal_range", "Trained")
            assigned = ", ".join(cv.assigned_agents) if cv.assigned_agents else "None"
            print(f"{cv.name:<16} {cv.id:<26} {cv.provider:<12} {v_range:<18} {assigned}")
        print()

    elif subaction == "test":
        name = args.name.strip()
        profile = manager.get_cloned_voice(name)
        text = getattr(args, "text", None) or f"Hey there! This is {name}, speaking with my custom trained voice."
        if profile:
            print(f"\n🔊 Auditioning custom cloned voice: '{profile.name}' ({profile.provider})")
            engine = get_tts_engine(config, voice_override=profile.id, provider_override=profile.provider)
        else:
            persona = find_persona(name)
            if persona:
                print(f"\n🔊 Auditioning voice: '{persona.name}' ({persona.provider})")
                engine = get_tts_engine(config, voice_override=persona.id, provider_override=persona.provider)
            else:
                print(f"❌ Error: Voice '{name}' not found.")
                return
        engine.speak(text, block=True)
        print("✅ Audition finished.\n")

    elif subaction == "assign":
        name = args.name.strip()
        target = args.agent.strip()
        try:
            tgt, vid = manager.assign_to_agent(name, target, config)
            print(f"✅ Successfully assigned {tgt} to cloned voice: '{name}' [{vid}]")
        except Exception as e:
            print(f"❌ Assignment failed: {e}")

    elif subaction == "delete":
        name = args.name.strip()
        api_key = config.tts.elevenlabs_api_key
        from_provider = getattr(args, "from_provider", False)
        success = manager.delete_cloned_voice(name, delete_from_elevenlabs=from_provider, api_key=api_key)
        if success:
            print(f"✅ Successfully deleted cloned voice: '{name}'")
        else:
            print(f"❌ Error: Could not find or delete voice '{name}'")

    elif subaction == "prompt":
        name = args.name.strip()
        profile = manager.get_cloned_voice(name)
        if not profile:
            print(f"❌ Voice '{name}' not found.")
            return
        print(f"\n--- AI Persona Style Prompt for '{profile.name}' ---")
        print(profile.persona_prompt)
        print("----------------------------------------------------\n")
    else:
        print("Use: vg clone [record|import|list|test|assign|delete|prompt] --help")


def cmd_companion(args):
    """Launch Web & Mobile Voice Companion server with QR pairing and PWA."""
    from voicegency.companion.server import run_companion_server
    config = load_config(args.config)
    port = getattr(args, "port", 8765)
    host = getattr(args, "host", "0.0.0.0")
    print_qr = not getattr(args, "no_qr", False)
    open_browser = getattr(args, "open", False)
    run_companion_server(
        port=port,
        host=host,
        print_qr=print_qr,
        open_browser=open_browser,
        config=config,
    )


def cmd_panel(args):
    """Launch interactive Voice Control Panel web dashboard."""
    import time
    from voicegency.ui.panel import open_control_panel
    port = getattr(args, "port", 8765)
    no_browser = getattr(args, "no_browser", False)
    config = load_config(args.config)
    print(f"\n🎙️ Launching Voice Control Panel on port {port}...")
    url = open_control_panel(port=port, open_browser=not no_browser, config=config)
    print(f"🌐 Control Panel running at: {url}")
    print("💡 Control via web UI or speak commands ('Audition Christopher', 'Switch to Aria').")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Voice Control Panel closed.")


def cmd_voice(args):
    """Handle voice inspection, testing, auditioning, assignment, and voice commands."""
    subaction = getattr(args, "voice_action", None)
    config = load_config(args.config)

    if subaction == "train":
        args.clone_action = "record"
        cmd_clone(args)
        return

    if subaction == "panel":
        cmd_panel(args)
        return

    if subaction == "command":
        from voicegency.ui.panel import parse_voice_command
        cmd_text = " ".join(args.command_text) if isinstance(args.command_text, list) else str(args.command_text)
        result = parse_voice_command(cmd_text, config)
        print(f"\n🗣️ Voice Command: \"{cmd_text}\"")
        print(f"📋 Result: {result.get('message', 'Done')}")
        if result.get("action") == "audition":
            vid = result.get("voice_id", result.get("voice"))
            prov = result.get("provider", "edge_tts")
            stext = result.get("sample_text", "Auditioning.")
            eng = get_tts_engine(config, voice_override=vid, provider_override=prov)
            eng.speak(stext, block=True)
        elif result.get("speech_feedback"):
            target_agent = result.get("target", "antigravity")
            vid = result.get("voice_id") or result.get("voice")
            prov = result.get("provider")
            eng = get_tts_engine(
                config,
                agent_name=target_agent,
                voice_override=vid,
                provider_override=prov,
            )
            eng.speak(result["speech_feedback"], block=True)
        print()
        return

    if subaction == "list":
        provider = getattr(args, "provider", None)
        show_all = getattr(args, "all", False)
        print("\n🎭 Curated Agent Voice Personas:")
        print(f"{'Persona':<14} {'ID / Voice':<28} {'Gender':<8} {'Locale':<8} {'Style / Role'}")
        print("-" * 80)
        personas = get_curated_personas(provider=provider)
        for p in personas:
            print(f"{p.name:<14} {p.id:<28} {p.gender:<8} {p.locale:<8} {p.style} ({p.recommended_role})")

        # Cloned voices
        manager = VoiceCloneManager()
        clones = manager.list_cloned_voices()
        if clones:
            print("\n🎙️ Custom Trained Voice Clones:")
            for cv in clones:
                v_range = cv.acoustic_metrics.get("vocal_range", "Custom Clone")
                assigned = f" -> assigned to: {', '.join(cv.assigned_agents)}" if cv.assigned_agents else ""
                print(f"  • {cv.name:<12} [{cv.id}] ({cv.provider}) - {v_range}{assigned}")

        if show_all:
            print("\n📋 Full Voice Catalog:")
            all_voices = list_all_available_voices(provider=provider)
            for v in all_voices:
                if not v.get("curated") and not v.get("cloned"):
                    print(f"  • {v['id']} ({v['provider']}, {v['locale']}) - {v['style']}")
        print()

    elif subaction == "test":
        voice_id = args.voice
        persona = find_persona(voice_id)
        resolved_voice = persona.id if persona else voice_id
        sample_text = args.text
        if not sample_text:
            sample_text = persona.sample_text if persona else f"Testing voice {voice_id} with Voicegency."

        provider = args.provider or (persona.provider if persona else config.tts.provider)
        rate_override = getattr(args, "rate", None)
        print(f"\n🔊 Auditioning voice: '{voice_id}' (Provider: {provider})")
        print(f"💬 Sample: \"{sample_text}\"")

        engine = get_tts_engine(config, voice_override=resolved_voice, provider_override=provider, rate_override=rate_override)
        engine.speak(sample_text, block=True)
        print("✅ Audition finished.\n")

    elif subaction == "audition":
        print("\n🎬 Starting Voicegency Multi-Agent Voice Audition Showcase...\n")
        audition_cast = [
            ("Christopher", "en-US-ChristopherNeural", "edge_tts", "Main Agent / Planner", "Hey! I'm Christopher. My calm, low-latency neural tone is great for deep focus and long coding sessions."),
            ("Aria", "en-US-AriaNeural", "edge_tts", "Debugger / QA Alerting", "Hello! I'm Aria. I'm quick, energetic, and expressive, perfect for test announcements, git actions, and build alerts."),
            ("Sonia", "en-GB-SoniaNeural", "edge_tts", "Researcher Subagent", "Greetings. I am Sonia. My clear British delivery is well suited for code audits and architecture reviews."),
            ("Guy", "en-US-GuyNeural", "edge_tts", "Conversational Pair", "Hey there! I'm Guy. I've got a casual, conversational delivery that feels like pair programming with a friend."),
        ]

        for name, vid, prov, role, text in audition_cast:
            print(f"🎙️ Playing Persona: {name} [{vid}] — Recommended for: {role}")
            print(f"   \"{text}\"")
            try:
                eng = get_tts_engine(config, voice_override=vid, provider_override=prov)
                eng.speak(text, block=True)
            except Exception as e:
                print(f"   ⚠️ Could not speak {name}: {e}")
            import time
            time.sleep(0.3)

        print("\n✨ Audition showcase complete! Assign a voice using: 'vg voice set <agent> <voice_name>'\n")

    elif subaction == "set":
        target = args.agent.lower().strip()
        voice_id = args.voice
        persona = find_persona(voice_id)
        resolved_voice = persona.id if persona else voice_id
        resolved_provider = args.provider or (persona.provider if persona else "edge_tts")
        rate_arg = getattr(args, "rate", None)
        resolved_rate = None
        if rate_arg is not None:
            val_s = str(rate_arg).strip().lower()
            if val_s.endswith("%"):
                try:
                    pct = float(val_s[:-1])
                    resolved_rate = max(min(int(round(200 * (pct / 100.0))), 350), 80)
                except ValueError:
                    resolved_rate = 150
            else:
                try:
                    num = float(val_s)
                    resolved_rate = max(min(int(round(200 * (num / 100.0))) if 0 < num <= 120 else int(round(num)), 350), 80)
                except ValueError:
                    resolved_rate = None

        from voicegency.config import AgentVoiceProfile
        profile = AgentVoiceProfile(
            voice=resolved_voice,
            provider=resolved_provider,
            rate=resolved_rate,
            description=f"Assigned to {target}",
        )

        subagent_roles = {"researcher", "debugger", "architect", "tester", "writer", "analyst"}
        if target in subagent_roles or target.startswith("subagent"):
            clean_role = target.replace("subagent.", "").replace("subagent_", "")
            config.subagents[clean_role] = profile
            target_desc = f"subagent '{clean_role}'"
        else:
            config.agents[target] = profile
            target_desc = f"agent '{target}'"

        save_config(config)
        rate_info = f" at {resolved_rate} WPM" if resolved_rate else ""
        print(f"✅ Successfully assigned {target_desc} to voice: '{resolved_voice}' ({resolved_provider}){rate_info}")

    elif subaction in ("rate", "speed"):
        raw_val = getattr(args, "value", None)
        if not raw_val:
            print(f"\n🎙️ Current Speech Rate: {config.tts.rate} WPM ({int(round((config.tts.rate / 200.0) * 100))}% speed)")
            if "antigravity" in config.agents and config.agents["antigravity"].rate:
                ag_rate = config.agents["antigravity"].rate
                print(f"  • Antigravity Rate: {ag_rate} WPM ({int(round((ag_rate / 200.0) * 100))}% speed)")
            print("To change speed: vg voice speed 75%  (or vg voice rate 150)\n")
            return

        agent_target = getattr(args, "agent", None)
        val_str = str(raw_val).strip().lower()
        if val_str in ("reset", "default", "normal"):
            new_rate = 200
            desc = "100% (200 WPM)"
        elif val_str in ("faster", "speedup"):
            new_rate = min(config.tts.rate + 25, 350)
            desc = f"{new_rate} WPM ({int(round((new_rate / 200.0) * 100))}%)"
        elif val_str in ("slower", "slowdown"):
            new_rate = max(config.tts.rate - 25, 100)
            desc = f"{new_rate} WPM ({int(round((new_rate / 200.0) * 100))}%)"
        elif val_str.endswith("%"):
            try:
                pct = float(val_str[:-1])
                if val_str.startswith(("+", "-")):
                    new_rate = max(min(int(round(200 * (1.0 + pct / 100.0))), 350), 80)
                    desc = f"{val_str} ({new_rate} WPM)"
                else:
                    new_rate = max(min(int(round(200 * (pct / 100.0))), 350), 80)
                    desc = f"{int(pct)}% ({new_rate} WPM)"
            except ValueError:
                new_rate = 150
                desc = "75% (150 WPM)"
        else:
            try:
                num = float(val_str)
                if num <= 120 and num > 0:
                    new_rate = max(min(int(round(200 * (num / 100.0))), 350), 80)
                    desc = f"{int(num)}% ({new_rate} WPM)"
                elif num < 0:
                    new_rate = max(min(int(round(200 * (1.0 + num / 100.0))), 350), 80)
                    desc = f"{int(num)}% ({new_rate} WPM)"
                else:
                    new_rate = max(min(int(round(num)), 350), 80)
                    desc = f"{new_rate} WPM ({int(round((new_rate / 200.0) * 100))}%)"
            except ValueError:
                print(f"⚠️ Invalid rate value: {raw_val}. Example: '75%', '150', 'faster'")
                return

        if agent_target:
            target = agent_target.lower().strip()
            if target in config.agents:
                config.agents[target].rate = new_rate
            elif target in config.subagents:
                config.subagents[target].rate = new_rate
            else:
                config.agents[target] = AgentVoiceProfile(rate=new_rate)
            print(f"✅ Set voice speed for '{target}' to {desc}")
        else:
            config.tts.rate = new_rate
            if "antigravity" in config.agents:
                config.agents["antigravity"].rate = new_rate
            print(f"✅ Set global voice speed to {desc}")

        save_config(config)

    elif subaction == "get":
        print("\n🎙️ Active Voice Assignments:")
        print(f"  • Global Default: {config.tts.voice} ({config.tts.provider}) - Rate: {config.tts.rate} WPM ({int(round((config.tts.rate / 200.0) * 100))}%)")
        if config.agents:
            print("\n  Agents:")
            for a_name, a_prof in config.agents.items():
                a_rate = a_prof.rate or config.tts.rate
                print(f"    - {a_name}: {a_prof.voice} ({a_prof.provider or config.tts.provider}) - Rate: {a_rate} WPM ({int(round((a_rate / 200.0) * 100))}%)")
        if config.subagents:
            print("\n  Subagents:")
            for s_name, s_prof in config.subagents.items():
                s_rate = s_prof.rate or config.tts.rate
                print(f"    - {s_name}: {s_prof.voice} ({s_prof.provider or config.tts.provider}) - Rate: {s_rate} WPM ({int(round((s_rate / 200.0) * 100))}%)")
        print()
    else:
        print("Use: vg voice [list|test|audition|set|get|rate|speed|train] --help")


def cmd_feedback(args):
    """Handle feedback, bug reports, and diagnostic submissions."""
    subaction = getattr(args, "feedback_action", "submit")
    if subaction == "list":
        items = list_feedback(limit=getattr(args, "limit", 10))
        if not items:
            print("ℹ️ No feedback submissions recorded yet.")
            return
        print(f"\n📬 Recent Feedback Items ({len(items)}):")
        for it in items:
            print(f"  [{it.get('category', 'general').upper()}] {it.get('title')} ({it.get('timestamp', '')[:19]}) - ID: {it.get('id')}")
            if it.get("details"):
                print(f"     Details: {it.get('details')}")
        print()
    else:
        title = " ".join(args.title) if isinstance(args.title, list) else str(args.title)
        details = getattr(args, "details", "") or ""
        category = getattr(args, "category", "general") or "general"
        agent_id = getattr(args, "agent_id", None)
        record = submit_feedback(
            title=title,
            details=details,
            category=category,
            agent_id=agent_id,
            include_diagnostics=not getattr(args, "no_diagnostics", False),
        )
        print(f"✅ Feedback logged successfully with ID: {record['id']}")
        print("📁 Saved to ~/.voicegency/feedback.jsonl")


def cmd_memo(args):
    """Handle voice memo buffer recording, synthesis, and management."""
    config = load_config(args.config)
    store = MemoStore()
    action = getattr(args, "memo_action", None) or "record"

    if action == "record":
        duration_arg = getattr(args, "duration", None)
        if duration_arg is not None:
            duration_str = str(duration_arg).strip().lower()
            if duration_str.endswith("m"):
                duration = float(duration_str[:-1]) * 60
            elif duration_str.endswith("s"):
                duration = float(duration_str[:-1])
            else:
                duration = float(duration_str)
        else:
            duration = config.memo.default_duration_seconds

        title = getattr(args, "title", None) or "Voice Memo"
        no_synth = getattr(args, "no_synth", False)
        out_path = getattr(args, "out", None)
        clipboard = getattr(args, "clipboard", False) or config.memo.export_to_clipboard

        recorder = MemoBufferRecorder(
            target_duration_seconds=duration,
            sample_rate=config.vad.sample_rate,
            energy_threshold=config.memo.energy_threshold,
            auto_extend_seconds=config.memo.auto_extend_seconds,
        )

        audio_data, temp_wav, actual_duration = recorder.record_memo_session(interactive=True)

        print("\n⏳ Transcribing developer stream of consciousness...")
        stt = get_stt_engine(config)
        raw_transcript = ""
        try:
            raw_transcript = stt.transcribe(temp_wav)
        except Exception as e:
            print(f"❌ Transcription error: {e}")
            return

        if not raw_transcript.strip():
            print("⚠️ No speech detected in recorded audio.")
            return

        word_count = len(raw_transcript.split())
        recording = MemoRecording(
            title=title,
            duration_seconds=actual_duration,
            target_duration_seconds=duration,
            audio_path=str(temp_wav),
            raw_transcript=raw_transcript,
            word_count=word_count,
        )

        synthesis = None
        if not no_synth and config.memo.auto_synthesize:
            print("🧠 Synthesizing Implementation Plan, Mermaid Diagram, and PR Checklist...\n")
            synthesizer = MemoSynthesizer(config)
            synthesis = synthesizer.synthesize(
                raw_speech=raw_transcript,
                memo_id=recording.id,
                custom_title=title if title != "Voice Memo" else None,
            )
            recording.title = synthesis.title

        memo_dir = store.save_memo(recording, synthesis)
        print(f"💾 Saved Voice Memo `{recording.id}` ({recording.title}) to {memo_dir}")

        if synthesis:
            print("\n" + "=" * 70)
            print(synthesis.to_markdown())
            print("=" * 70 + "\n")

            if out_path:
                dest = Path(out_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(synthesis.to_markdown(), encoding="utf-8")
                print(f"📄 Exported plan to {dest}")

            if clipboard:
                try:
                    import subprocess
                    subprocess.run(["pbcopy"], input=synthesis.to_markdown().encode("utf-8"), check=True)
                    print("📋 Copied synthesized plan to clipboard!")
                except Exception:
                    pass

    elif action in ("synth", "synthesize"):
        memo_id = getattr(args, "memo_id", None)
        text_arg = getattr(args, "text", None)
        file_arg = getattr(args, "file", None)
        title = getattr(args, "title", None)
        out_path = getattr(args, "out", None)
        clipboard = getattr(args, "clipboard", False) or config.memo.export_to_clipboard

        raw_speech = ""
        recording = None

        if text_arg:
            raw_speech = " ".join(text_arg) if isinstance(text_arg, list) else str(text_arg)
        elif file_arg:
            f_path = Path(file_arg)
            if not f_path.is_file():
                print(f"❌ File not found: {file_arg}")
                return
            raw_speech = f_path.read_text(encoding="utf-8")
        elif memo_id:
            res = store.get_memo(memo_id)
            if not res:
                print(f"❌ Memo `{memo_id}` not found.")
                return
            recording, _ = res
            raw_speech = recording.raw_transcript
            if not title:
                title = recording.title
        else:
            print("❌ Please specify a memo ID, --text '...', or --file <path> to synthesize.")
            return

        if not raw_speech.strip():
            print("❌ No speech text to synthesize.")
            return

        print("🧠 Synthesizing Implementation Plan, Architectural Diagram, and PR Checklist...\n")
        synthesizer = MemoSynthesizer(config)
        mid = recording.id if recording else None
        synthesis = synthesizer.synthesize(raw_speech=raw_speech, memo_id=mid, custom_title=title)

        if recording:
            recording.title = synthesis.title
            store.save_memo(recording, synthesis)
        else:
            recording = MemoRecording(
                id=synthesis.memo_id,
                title=synthesis.title,
                duration_seconds=0.0,
                target_duration_seconds=180.0,
                raw_transcript=raw_speech,
                word_count=len(raw_speech.split()),
            )
            store.save_memo(recording, synthesis)

        print("=" * 70)
        print(synthesis.to_markdown())
        print("=" * 70 + "\n")

        if out_path:
            dest = Path(out_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(synthesis.to_markdown(), encoding="utf-8")
            print(f"📄 Exported plan to {dest}")

        if clipboard:
            try:
                import subprocess
                subprocess.run(["pbcopy"], input=synthesis.to_markdown().encode("utf-8"), check=True)
                print("📋 Copied synthesized plan to clipboard!")
            except Exception:
                pass

    elif action == "list":
        limit = getattr(args, "limit", 20)
        memos = store.list_memos(limit=limit)
        if not memos:
            print("📭 No voice memos recorded yet.")
            print("👉 Run 'vg memo record' or 'vg memo record --duration 3m' to capture a brain dump!")
            return

        print(f"\n{'ID':<10} {'CREATED':<20} {'DURATION':<10} {'WORDS':<8} {'SYNTH':<7} {'TITLE'}")
        print("─" * 78)
        for m in memos:
            created = m.get("created_at", "")[:19].replace("T", " ")
            dur = f"{int(m.get('duration_seconds', 0)) // 60:02d}:{int(m.get('duration_seconds', 0)) % 60:02d}"
            synth_icon = "✅ Yes" if m.get("has_synthesis") else "❌ No"
            words = str(m.get("word_count", 0))
            title = m.get("title", "Voice Memo")[:25]
            mid = m.get("id", "")
            print(f"{mid:<10} {created:<20} {dur:<10} {words:<8} {synth_icon:<7} {title}")
        print("─" * 78 + "\n")

    elif action == "show":
        memo_id = args.memo_id
        res = store.get_memo(memo_id)
        if not res:
            print(f"❌ Memo `{memo_id}` not found.")
            return
        recording, synthesis = res

        if getattr(args, "transcript_only", False):
            print(recording.raw_transcript)
        elif getattr(args, "diagram_only", False) and synthesis:
            print("```mermaid")
            print(synthesis.architectural_diagram.mermaid_code)
            print("```")
        elif getattr(args, "checklist_only", False) and synthesis:
            for task in synthesis.pr_checklist.core_tasks:
                print(f"- [ ] {task}")
            for test in synthesis.pr_checklist.testing_and_verification:
                print(f"- [ ] {test}")
            for edge in synthesis.pr_checklist.edge_cases_and_security:
                print(f"- [ ] {edge}")
        elif synthesis:
            print(synthesis.to_markdown())
        else:
            print(f"# Voice Memo: {recording.title} (`{recording.id}`)")
            print(f"Duration: {int(recording.duration_seconds)//60:02d}:{int(recording.duration_seconds)%60:02d} | Words: {recording.word_count}")
            print("\n## Raw Transcript")
            print(recording.raw_transcript)
            print("\n💡 Run 'vg memo synth " + recording.id + "' to generate structured implementation plan.")

    elif action == "export":
        memo_id = args.memo_id
        res = store.get_memo(memo_id)
        if not res:
            print(f"❌ Memo `{memo_id}` not found.")
            return
        recording, synthesis = res
        content = synthesis.to_markdown() if synthesis else recording.raw_transcript

        out_path = getattr(args, "out", None)
        if out_path:
            dest = Path(out_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            print(f"📄 Exported memo `{memo_id}` to {dest}")

        if getattr(args, "clipboard", False) or not out_path:
            try:
                import subprocess
                subprocess.run(["pbcopy"], input=content.encode("utf-8"), check=True)
                print(f"📋 Copied memo `{memo_id}` to clipboard!")
            except Exception:
                pass

    elif action == "import":
        file_path = Path(args.file)
        if not file_path.is_file():
            print(f"❌ File not found: {file_path}")
            return

        title = getattr(args, "title", None) or file_path.stem.replace("_", " ").title()
        print(f"📥 Importing {file_path.name}...")

        is_audio = file_path.suffix.lower() in (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".aac")
        if is_audio:
            print("⏳ Transcribing imported audio...")
            stt = get_stt_engine(config)
            raw_speech = stt.transcribe(file_path)
        else:
            raw_speech = file_path.read_text(encoding="utf-8")

        if not raw_speech.strip():
            print("❌ No speech or text content found in file.")
            return

        print("🧠 Synthesizing Implementation Plan, Mermaid Diagram, and PR Checklist...\n")
        synthesizer = MemoSynthesizer(config)
        synthesis = synthesizer.synthesize(raw_speech=raw_speech, custom_title=title)

        recording = MemoRecording(
            id=synthesis.memo_id,
            title=synthesis.title,
            duration_seconds=0.0,
            target_duration_seconds=180.0,
            audio_path=str(file_path) if is_audio else None,
            raw_transcript=raw_speech,
            word_count=len(raw_speech.split()),
        )
        memo_dir = store.save_memo(recording, synthesis)
        print(f"💾 Imported and saved memo `{recording.id}` ({recording.title}) to {memo_dir}")
        print("\n" + "=" * 70)
        print(synthesis.to_markdown())
        print("=" * 70 + "\n")

    elif action == "delete":
        memo_id = args.memo_id
        if store.delete_memo(memo_id):
            print(f"🗑️ Deleted voice memo `{memo_id}`.")
        else:
            print(f"❌ Memo `{memo_id}` not found.")


def cmd_bias(args):
    """Test and inspect developer STT vocabulary biasing and phonetic normalization."""
    from voicegency.stt.biasing import ProjectContextExtractor, PhoneticNormalizer

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
        print(f"\n📋 Full Whisper / Groq Bias Prompt:\n\"{prompt}\"\n")


def cmd_ambient(args):
    """Ambient background listening & proactive triage co-pilot."""
    import time
    action = getattr(args, "ambient_action", "start") or "start"

    if action == "start":
        from voicegency.audio.ambient import AmbientAudioStream
        from voicegency.integrations.proactive import ProactiveDispatcher
        from voicegency.stt import get_stt_engine

        config = load_config(args.config)
        dispatcher = ProactiveDispatcher()
        stt = get_stt_engine(config)

        print("\n🎙️ Starting Voicegency Ambient Listener & Proactive Co-Pilot...")
        print("💡 Listening in the background. Press Ctrl+C to stop.\n")

        def _on_utterance(audio_data, sample_rate):
            text = stt.transcribe(audio_data, sample_rate=sample_rate)
            if text:
                print(f"📝 Heard: \"{text}\"")
                task = dispatcher.process_utterance(text)
                if task:
                    print(f"⚡ [Proactive Triage] Detected {task.category.value}: {task.summary}")
                    print(f"   👉 Workspace Mode: {task.suggested_workspace} (isolated sandbox)")
                    print(f"   👉 Action Prompt: {task.action_prompt}\n")

        stream = AmbientAudioStream(
            sample_rate=config.vad.sample_rate,
            energy_threshold=config.ambient.energy_threshold,
            silence_duration=config.ambient.silence_duration,
            max_utterance_duration=config.ambient.max_utterance_seconds,
            on_utterance=_on_utterance,
        )
        stream.start()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            stream.stop()
            print("\n👋 Ambient listener stopped.")

    elif action == "status":
        print("\n📊 Voicegency Ambient Listener Status:")
        print("   • Status: Ready")
        print("   • Mode: Real-time STT + Proactive Triage Engine")
        print("   • Sandbox Isolation: Enabled (Workspace=\"branch\")\n")


def cmd_info(args):
    """Display active configuration and system capabilities."""
    config = load_config(args.config)
    tier_info = FeatureGate.get_tier_summary(config)

    print(f"\n================ Voicegency v{__version__} ================")
    print("  'Give a voice to your agents, and agency to your voice.'")
    print(f"Tier:          {tier_info['tier']}")
    print(f"TTS Provider:  {config.tts.provider} (Default Voice: {config.tts.voice})")
    print(f"STT Provider:  {config.stt.provider} (Model: {config.stt.model_size})")
    print(f"VAD Silence:   {config.vad.silence_duration}s")
    print(f"Auto-Listen:   {config.antigravity.auto_listen}")
    print(f"Read Aloud:    {config.antigravity.read_summary_aloud}")
    if config.agents:
        print(f"Agents:        {', '.join(config.agents.keys())}")
    if config.subagents:
        print(f"Subagents:     {', '.join(config.subagents.keys())}")
    print("====================================================\n")

    print("Curated Personas: Christopher, Aria, Sonia, Guy, William, Samantha, Alex")
    print("Run 'vg voice audition' to test them over your speakers!\n")


def main():
    parser = argparse.ArgumentParser(
        prog="voicegency",
        description="Voicegency: Give a voice to your agents, and agency to your voice. The Universal Ambient Voice Layer for AI Agents & macOS.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to custom config.yaml")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # hook
    subparsers.add_parser("hook", help="Run as Antigravity lifecycle hook")

    # speak
    speak_p = subparsers.add_parser("speak", help="Speak text aloud")
    speak_p.add_argument("text", nargs="+", help="Text to speak")
    speak_p.add_argument("-a", "--agent", type=str, default=None, help="Agent profile to speak as (e.g. antigravity, researcher, debugger)")
    speak_p.add_argument("-v", "--voice", type=str, default=None, help="Voice name or ID override")
    speak_p.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override (mac_say, edge_tts, elevenlabs)")
    speak_p.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override (e.g. 75%, 150, -25%)")

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

    # tray / dev
    subparsers.add_parser("tray", help="Launch macOS menu bar companion")
    subparsers.add_parser("dev", help="Launch in foreground dev mode with live console logs")

    # setup
    subparsers.add_parser("setup", help="Auto-configure Antigravity lifecycle hooks")

    # autostart
    subparsers.add_parser("autostart", help="Register macOS LaunchAgent to keep menu bar icon persistent")
    subparsers.add_parser("stop-autostart", help="Remove macOS LaunchAgent autostart")

    # companion / remote
    comp_p = subparsers.add_parser("companion", aliases=["remote"], help="Launch Web & Mobile Voice Companion (PWA & QR code)")
    comp_p.add_argument("--port", type=int, default=8765, help="Port to run companion server (default: 8765)")
    comp_p.add_argument("--host", type=str, default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    comp_p.add_argument("--no-qr", action="store_true", help="Do not print terminal QR code")
    comp_p.add_argument("--open", action="store_true", help="Open local companion in default browser")

    # panel
    panel_p = subparsers.add_parser("panel", help="Launch interactive Voice Control Panel")
    panel_p.add_argument("--port", type=int, default=8765, help="Port to run web control panel (default: 8765)")
    panel_p.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")

    # info
    subparsers.add_parser("info", help="Show system status and voices")

    # voice
    voice_p = subparsers.add_parser("voice", help="Manage and audition agent voices")
    voice_sub = voice_p.add_subparsers(dest="voice_action", help="Voice action")
    
    # voice panel
    vp_panel = voice_sub.add_parser("panel", help="Launch interactive Voice Control Panel")
    vp_panel.add_argument("--port", type=int, default=8765)
    vp_panel.add_argument("--no-browser", action="store_true")

    # voice command
    vp_cmd = voice_sub.add_parser("command", help="Execute a natural voice command")
    vp_cmd.add_argument("command_text", nargs="+", help="Command phrase to execute (e.g. 'audition Christopher', 'switch to Aria')")

    # voice list
    v_list = voice_sub.add_parser("list", help="List curated and system voices")
    v_list.add_argument("--provider", type=str, default=None, help="Filter by provider (edge_tts, mac_say)")
    v_list.add_argument("-a", "--all", action="store_true", help="Include uncurated system voices")

    # voice test
    v_test = voice_sub.add_parser("test", help="Audition / test a single voice")
    v_test.add_argument("voice", type=str, help="Voice name or ID (e.g. Christopher, Aria, en-US-ChristopherNeural)")
    v_test.add_argument("-t", "--text", type=str, default=None, help="Custom text sample to speak")
    v_test.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    v_test.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override (e.g. 75%, 150)")

    # voice audition
    voice_sub.add_parser("audition", help="Play live multi-agent voice showcase across speakers")

    # voice rate / speed
    v_rate = voice_sub.add_parser("rate", help="Get or set speech rate / speed (e.g. 75%, 150, faster, slower)")
    v_rate.add_argument("value", nargs="?", default=None, help="Speed value (e.g. '75%', '150', 'faster', 'slower', 'reset')")
    v_rate.add_argument("-a", "--agent", type=str, default=None, help="Target specific agent or subagent")

    v_speed = voice_sub.add_parser("speed", help="Alias for 'vg voice rate'")
    v_speed.add_argument("value", nargs="?", default=None, help="Speed value (e.g. '75%', '150', 'faster', 'slower', 'reset')")
    v_speed.add_argument("-a", "--agent", type=str, default=None, help="Target specific agent or subagent")

    # voice train
    v_train = voice_sub.add_parser("train", help="Train a custom voice clone from mic or files")
    v_train.add_argument("name", type=str, help="Name for the custom voice")
    v_train.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    v_train.add_argument("--assign", type=str, default=None, help="Automatically assign to agent (e.g. antigravity)")

    # voice set
    v_set = voice_sub.add_parser("set", help="Assign a voice to an agent or subagent")
    v_set.add_argument("agent", type=str, help="Agent or subagent name (e.g. antigravity, claude, researcher, debugger)")
    v_set.add_argument("voice", type=str, help="Voice name or ID")
    v_set.add_argument("-p", "--provider", type=str, default=None)
    v_set.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed (e.g. 75%, 150, -25%)")

    # voice get
    voice_sub.add_parser("get", help="Show active voice mappings")

    # clone
    clone_p = subparsers.add_parser("clone", help="Train and manage custom voice clones")
    clone_sub = clone_p.add_subparsers(dest="clone_action", help="Clone action")

    # clone record
    c_rec = clone_sub.add_parser("record", help="Record voice samples via mic wizard")
    c_rec.add_argument("name", type=str, help="Name for the custom cloned voice")
    c_rec.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    c_rec.add_argument("--description", type=str, default="", help="Voice description")
    c_rec.add_argument("--assign", type=str, default=None, help="Assign directly to agent upon completion")

    # clone import
    c_imp = clone_sub.add_parser("import", help="Train voice from existing audio files")
    c_imp.add_argument("name", type=str, help="Name for the custom cloned voice")
    c_imp.add_argument("files", nargs="+", help="Audio files (.wav, .mp3, .m4a)")
    c_imp.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    c_imp.add_argument("--description", type=str, default="", help="Voice description")
    c_imp.add_argument("--assign", type=str, default=None, help="Assign directly to agent upon completion")

    # clone list
    clone_sub.add_parser("list", help="List all custom trained voices")

    # clone test
    c_test = clone_sub.add_parser("test", help="Audition / test a custom cloned voice")
    c_test.add_argument("name", type=str, help="Name of custom voice to audition")
    c_test.add_argument("-t", "--text", type=str, default=None, help="Text to speak")

    # clone assign
    c_assign = clone_sub.add_parser("assign", help="Assign cloned voice to an agent")
    c_assign.add_argument("name", type=str, help="Name of custom voice")
    c_assign.add_argument("agent", type=str, help="Target agent (antigravity, claude, researcher, debugger, default)")

    # clone delete
    c_del = clone_sub.add_parser("delete", help="Delete a cloned voice profile")
    c_del.add_argument("name", type=str, help="Name of voice to delete")
    c_del.add_argument("--from-provider", action="store_true", help="Also delete from ElevenLabs API")

    # clone prompt
    c_prompt = clone_sub.add_parser("prompt", help="View AI persona style prompt for cloned voice")
    c_prompt.add_argument("name", type=str, help="Name of custom voice")

    # feedback
    fb_p = subparsers.add_parser("feedback", help="Submit feedback, bug reports, or requests")
    fb_sub = fb_p.add_subparsers(dest="feedback_action", help="Feedback action")
    
    fb_submit = fb_sub.add_parser("submit", help="Submit feedback or bug report")
    fb_submit.add_argument("title", nargs="+", help="Feedback title or summary")
    fb_submit.add_argument("-d", "--details", type=str, default="", help="Detailed explanation")
    fb_submit.add_argument("-c", "--category", type=str, default="general", choices=["bug", "feature", "voice_quality", "latency", "general"])
    fb_submit.add_argument("--agent-id", type=str, default=None, help="Submitting agent name")
    fb_submit.add_argument("--no-diagnostics", action="store_true", help="Exclude environment diagnostics")

    fb_list = fb_sub.add_parser("list", help="List recent feedback submissions")
    fb_list.add_argument("-n", "--limit", type=int, default=10)

    # memo / buffer
    memo_p = subparsers.add_parser("memo", aliases=["buffer"], help="Voice memo buffer: capture long rambles & synthesize to code")
    memo_sub = memo_p.add_subparsers(dest="memo_action", help="Voice memo action")

    # memo record
    m_rec = memo_sub.add_parser("record", help="Record a 2-5 min voice memo with elegant countdown timer")
    m_rec.add_argument("-d", "--duration", type=str, default=None, help="Target recording duration (e.g. '3m', '5m', '180')")
    m_rec.add_argument("-t", "--title", type=str, default=None, help="Title for the voice memo")
    m_rec.add_argument("-o", "--out", type=str, default=None, help="Export synthesized plan to markdown file")
    m_rec.add_argument("-c", "--clipboard", action="store_true", help="Copy synthesized plan to clipboard")
    m_rec.add_argument("--no-synth", action="store_true", help="Skip automatic thought synthesis")

    # memo synth
    m_synth = memo_sub.add_parser("synth", aliases=["synthesize"], help="Synthesize stream-of-consciousness thoughts into code plan")
    m_synth.add_argument("memo_id", nargs="?", default=None, help="Memo ID to synthesize")
    m_synth.add_argument("-t", "--text", nargs="+", default=None, help="Raw speech text to synthesize")
    m_synth.add_argument("-f", "--file", type=str, default=None, help="Text or transcript file to synthesize")
    m_synth.add_argument("--title", type=str, default=None, help="Custom title for generated plan")
    m_synth.add_argument("-o", "--out", type=str, default=None, help="Export path for generated markdown")
    m_synth.add_argument("-c", "--clipboard", action="store_true", help="Copy generated plan to clipboard")

    # memo list
    m_list = memo_sub.add_parser("list", help="List stored voice memos and brain dumps")
    m_list.add_argument("-n", "--limit", type=int, default=20, help="Max memos to list")

    # memo show
    m_show = memo_sub.add_parser("show", help="Display full synthesized plan or transcript")
    m_show.add_argument("memo_id", type=str, help="Memo ID")
    m_show.add_argument("--transcript", dest="transcript_only", action="store_true", help="Show raw transcript only")
    m_show.add_argument("--diagram", dest="diagram_only", action="store_true", help="Show Mermaid diagram only")
    m_show.add_argument("--checklist", dest="checklist_only", action="store_true", help="Show PR checklist only")

    # memo export
    m_exp = memo_sub.add_parser("export", help="Export synthesized plan to markdown or clipboard")
    m_exp.add_argument("memo_id", type=str, help="Memo ID to export")
    m_exp.add_argument("-o", "--out", type=str, default=None, help="Output markdown file path")
    m_exp.add_argument("-c", "--clipboard", action="store_true", help="Copy to clipboard")

    # memo import
    m_imp = memo_sub.add_parser("import", help="Import an audio recording or text note")
    m_imp.add_argument("file", type=str, help="Path to audio file (.wav, .mp3, .m4a) or text file")
    m_imp.add_argument("-t", "--title", type=str, default=None, help="Title for the imported memo")

    # memo delete
    m_del = memo_sub.add_parser("delete", help="Delete a stored voice memo")
    m_del.add_argument("memo_id", type=str, help="Memo ID to delete")

    # ambient listener & proactive co-pilot
    amb_p = subparsers.add_parser("ambient", help="Ambient background listening & proactive triage co-pilot")
    amb_sub = amb_p.add_subparsers(dest="ambient_action", help="Ambient action")
    amb_start = amb_sub.add_parser("start", help="Start background ambient listener")
    amb_start.add_argument("--source", choices=["mic", "loopback"], default="mic", help="Audio capture source")
    amb_sub.add_parser("status", help="Show ambient listener status")

    # STT biasing & phonetic normalizer
    bias_p = subparsers.add_parser("bias", help="Inspect active STT vocabulary biasing or test phonetic normalization")
    bias_p.add_argument("text", nargs="*", default=None, help="Spoken developer input to normalize")

    args = parser.parse_args()

    if not args.command:
        if getattr(sys, "frozen", False):
            # Launched from macOS .app bundle without CLI arguments
            cmd_tray(args)
            return
        parser.print_help()
        sys.exit(0)

    commands = {
        "hook": cmd_hook,
        "speak": cmd_speak,
        "listen": cmd_listen,
        "loop": cmd_loop,
        "tray": cmd_tray,
        "dev": cmd_dev,
        "setup": cmd_setup,
        "autostart": cmd_autostart,
        "stop-autostart": cmd_stop_autostart,
        "companion": cmd_companion,
        "remote": cmd_companion,
        "panel": cmd_panel,
        "info": cmd_info,
        "voice": cmd_voice,
        "clone": cmd_clone,
        "feedback": cmd_feedback,
        "memo": cmd_memo,
        "buffer": cmd_memo,
        "ambient": cmd_ambient,
        "bias": cmd_bias,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)


if __name__ == "__main__":
    main()


