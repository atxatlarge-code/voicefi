"""
CLI commands for voice management: auditioning, listing, rate setting, Ava download, and cloning.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from voicefi.config import load_config, save_config, AgentVoiceProfile
from voicefi.tts import get_tts_engine
from voicefi.tts.catalog import (
    get_curated_personas,
    list_all_available_voices,
    find_persona,
    CURATED_PERSONAS,
)
from voicefi.tts.cloning import VoiceCloneManager, TRAINING_PROMPTS
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.tts.offline import run_download_ava_workflow
from voicefi.troubleshoot import AudioTroubleshooter, TEST_PHRASES
from voicefi.cli_commands.troubleshoot import (
    run_silent_voice_ping,
    cmd_troubleshoot,
    cmd_barge_in,
)
from voicefi.cli_commands.speed_talk import cmd_speed_talk

logger = logging.getLogger(__name__)


def cmd_download_ava(args: Any) -> None:
    """Guide user through downloading & configuring Apple's Ava (Premium) for 0ms offline speech."""
    auto_poll = not (getattr(args, "no_wait", False) or getattr(args, "no_poll", False))
    timeout = getattr(args, "timeout", 300)
    silent = getattr(args, "silent", False) or getattr(args, "quiet", False)
    check_only = getattr(args, "check", False)

    result = run_download_ava_workflow(
        auto_poll=auto_poll,
        timeout_seconds=timeout,
        silent=silent,
        check_only=check_only,
    )
    if check_only:
        print(result.get("message", ""))


def cmd_clone(args: Any) -> None:
    """Train, record, import, test, assign, and manage custom cloned voices."""
    manager = VoiceCloneManager()
    config = load_config(args.config)
    subaction = getattr(args, "clone_action", None)

    # If no explicit subcommand was provided, check direct flags (e.g. from `vifi voice clone ...`)
    if not subaction or subaction in ("clone", "train"):
        raw_name = getattr(args, "name", None)
        target_val = getattr(args, "target", None)
        if raw_name and str(raw_name).lower().strip() in ("list", "ls"):
            subaction = "list"
            args.name = None
        elif raw_name and str(raw_name).lower().strip() in ("delete", "rm", "del"):
            subaction = "delete"
            args.name = target_val or None
        elif raw_name and str(raw_name).lower().strip() in ("test", "audition"):
            subaction = "test"
            args.name = target_val or None
        elif getattr(args, "list", False) is True:
            subaction = "list"
        elif getattr(args, "test", False) is True:
            subaction = "test"
        elif getattr(args, "delete", False) is True:
            subaction = "delete"
        elif getattr(args, "audio_files", None) or (
            isinstance(getattr(args, "files", None), (list, tuple)) and args.files
        ):
            subaction = "import"
            if not getattr(args, "files", None):
                args.files = args.audio_files
        elif getattr(args, "record", False) is True:
            subaction = "record"
        elif getattr(args, "name", None) and not subaction:
            if getattr(args, "audio_files", None):
                subaction = "import"
                args.files = args.audio_files
            else:
                subaction = "record"
        elif not subaction:
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
            print(f"[{i + 1}/{len(TRAINING_PROMPTS)}] {p['title']}:")
            print(f'👉 "{p["text"]}"')
            try:
                input("Press [ENTER] when ready to speak...")
            except EOFError:
                pass

            if config.audio_cues.enabled:
                play_chime("start", block=False)
            print("🔴 Recording... (speak the phrase and pause)")
            _, wav_path = recorder.record_speech_auto()
            recorded_files.append(wav_path)
            print(f"✅ Sample {i + 1} captured.\n")
            time.sleep(0.3)

        api_key = getattr(args, "api_key", None) or config.tts.elevenlabs_api_key
        prov_pref = getattr(args, "provider", None)
        if prov_pref == "auto":
            prov_pref = None

        print("🧠 Processing acoustic features and training voice profile...")
        try:
            profile = manager.train_voice(
                name=name,
                sample_paths=recorded_files,
                api_key=api_key,
                description=getattr(args, "description", "") or f"Voice clone of {name}",
                provider_preference=prov_pref,
            )
            print("\n✨ Voice Training Complete!")
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

            print("\nTest your voice with:  vifi voice test " + profile.name)
            print("Assign to agent with: vifi voice set antigravity " + profile.name + "\n")
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
        prov_pref = getattr(args, "provider", None)
        if prov_pref == "auto":
            prov_pref = None

        print(f"\n📥 Importing {len(valid_files)} audio samples for voice: '{name}'...")
        profile = manager.train_voice(
            name=name,
            sample_paths=valid_files,
            api_key=api_key,
            description=getattr(args, "description", "") or f"Imported voice of {name}",
            provider_preference=prov_pref,
        )
        print(f"✅ Successfully trained cloned voice: '{profile.name}' ({profile.provider})")
        print(f"  • ID:          {profile.id}")
        print(f"  • Vocal Range: {profile.acoustic_metrics.get('vocal_range', 'Unknown')}")
        target_agent = getattr(args, "assign", None)
        if target_agent:
            manager.assign_to_agent(profile.name, target_agent, config)
            print(f"  • Assigned to: {target_agent}")

        print("\nTest your voice with:  vifi voice test " + profile.name)
        print("Assign to agent with: vifi voice set antigravity " + profile.name + "\n")

    elif subaction == "list":
        clones = manager.list_cloned_voices()
        if not clones:
            print("\nℹ️ No custom cloned voices found.")
            print("Clone one now with: 'vifi voice clone <name> --audio <file.wav>'")
            print("                or: 'vifi voice clone <name> --record'\n")
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
        text = (
            getattr(args, "text", None)
            or f"Hey there! This is {name}, speaking with my custom trained voice."
        )
        if profile:
            print(f"\n🔊 Auditioning custom cloned voice: '{profile.name}' ({profile.provider})")
            engine = get_tts_engine(
                config, voice_override=profile.id, provider_override=profile.provider
            )
        else:
            persona = find_persona(name)
            if persona:
                print(f"\n🔊 Auditioning voice: '{persona.name}' ({persona.provider})")
                engine = get_tts_engine(
                    config, voice_override=persona.id, provider_override=persona.provider
                )
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
        success = manager.delete_cloned_voice(
            name, delete_from_elevenlabs=from_provider, api_key=api_key
        )
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

    elif subaction == "studio":
        print("\n🎛️ Launching Open-Source Voice Cloning Web Studio (F5-TTS)...")
        try:
            from f5_tts.infer.infer_gradio import app

            app.launch(share=False)
        except Exception as e:
            print(f"[Studio] Notice: {e}. Opening VoiceFi Web Panel...")
            from voicefi.ui.panel import run_panel_server

            run_panel_server()
    else:
        print("Use: vg clone [record|import|list|test|assign|delete|prompt|studio] --help")


def cmd_voice(args: Any) -> None:
    """Handle voice inspection, testing, auditioning, assignment, and voice commands."""
    subaction = getattr(args, "voice_action", None)
    config = load_config(args.config)

    if subaction in (
        "download-ava",
        "install-ava",
        "setup-ava",
        "get-ava",
        "download_ava",
        "setup-offline",
        "offline",
    ):
        cmd_download_ava(args)
        return

    if subaction in ("ping", "check", "speed-test"):
        run_silent_voice_ping(args, config)
        return

    if subaction in ("train", "clone"):
        cmd_clone(args)
        return

    if subaction == "panel":
        from voicefi.companion.server import run_companion_server

        run_companion_server(config)
        return

    if subaction == "troubleshoot":
        cmd_troubleshoot(args)
        return

    if subaction == "command":
        from voicefi.ui.panel import parse_voice_command

        cmd_text = (
            " ".join(args.command_text)
            if isinstance(args.command_text, list)
            else str(args.command_text)
        )
        result = parse_voice_command(cmd_text, config)
        print(f'\n🗣️ Voice Command: "{cmd_text}"')
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
            print(
                f"{p.name:<14} {p.id:<28} {p.gender:<8} {p.locale:<8} {p.style} ({p.recommended_role})"
            )

        # Cloned voices
        manager = VoiceCloneManager()
        clones = manager.list_cloned_voices()
        if clones:
            print("\n🎙️ Custom Trained Voice Clones:")
            for cv in clones:
                v_range = cv.acoustic_metrics.get("vocal_range", "Custom Clone")
                assigned = (
                    f" -> assigned to: {', '.join(cv.assigned_agents)}"
                    if cv.assigned_agents
                    else ""
                )
                print(f"  • {cv.name:<12} [{cv.id}] ({cv.provider}) - {v_range}{assigned}")

        if config.projects:
            print("\n📁 Project-Specific Assigned Voices:")
            for pk, pprof in config.projects.items():
                p_obj = find_persona(pprof.voice)
                p_disp = f"({p_obj.name})" if p_obj else ""
                print(
                    f"  • {pk:<16} -> {pprof.voice:<26} {p_disp} [{pprof.provider or config.tts.provider}]"
                )

        if show_all:
            print("\n📋 Full Voice Catalog:")
            all_voices = list_all_available_voices(provider=provider)
            for v in all_voices:
                if not v.get("curated") and not v.get("cloned"):
                    print(f"  • {v['id']} ({v['provider']}, {v['locale']}) - {v['style']}")
        print()

    elif subaction == "test":
        # Silent mode requested on test command
        if getattr(args, "silent", False):
            run_silent_voice_ping(args, config)
            return

        # 1. Benchmark only (silent measurement by default)
        if getattr(args, "benchmark", False):
            troubleshooter = AudioTroubleshooter(config)
            print("\n⚡ Benchmarking Voice Personas Latency & Speed (Silent)...")
            benchmarks = troubleshooter.benchmark_all_curated_voices(silent=True)
            for b in benchmarks:
                status_icon = "🟢" if b["status"] in ("online", "offline_native") else "🔴"
                lat_str = (
                    f"{b['latency_ms']} ms"
                    if b["status"] in ("online", "offline_native")
                    else "Error"
                )
                speed_str = (
                    f" | {b['chars_per_sec']:.1f} chars/s"
                    if b.get("chars_per_sec", 0) > 0
                    else ""
                )
                print(
                    f"  • {status_icon} {b['name']:<12} [{b['provider']}]: {lat_str}{speed_str} ({b['recommended_role']})"
                )
            print()
            return

        # 2. Audition all personas
        if getattr(args, "all", False):
            print("\n🎬 Auditioning All Curated Personas...")
            troubleshooter = AudioTroubleshooter(config)
            for p in CURATED_PERSONAS:
                print(f"\n🎙️ Voice: {p.name} ({p.id}) — Role: {p.recommended_role}")
                print(f'   "{p.sample_text}"')
                res = troubleshooter.test_voice(
                    p.id, text=p.sample_text, provider=p.provider, block=True
                )
                if res.success:
                    print(f"   ✅ Latency: {res.latency_ms} ms (Duration: {res.duration_s}s)")
                else:
                    print(f"   ❌ Error: {res.error}")
                time.sleep(0.3)
            print("\n✨ Auditions complete.\n")
            return

        # 3. Resolve target voice, text, provider, rate
        voice_id = getattr(args, "voice", None)
        target_voice = voice_id or config.tts.voice
        persona = find_persona(target_voice)
        resolved_voice = persona.id if persona else target_voice
        sample_text = args.text
        if not sample_text:
            phrase_key = getattr(args, "phrase", None)
            if phrase_key and phrase_key in TEST_PHRASES:
                sample_text = TEST_PHRASES[phrase_key]
            else:
                sample_text = (
                    persona.sample_text
                    if persona
                    else f"Testing voice {target_voice} with VoiceFi."
                )

        provider = args.provider or (persona.provider if persona else config.tts.provider)
        rate_override = getattr(args, "rate", None)
        resolved_rate = None
        if rate_override is not None:
            val_s = str(rate_override).strip().lower()
            if val_s.endswith("%"):
                try:
                    pct = float(val_s[:-1])
                    resolved_rate = max(min(int(round(200 * (pct / 100.0))), 350), 80)
                except ValueError:
                    resolved_rate = 150
            else:
                try:
                    num = float(val_s)
                    resolved_rate = max(
                        min(
                            int(round(200 * (num / 100.0)))
                            if 0 < num <= 120
                            else int(round(num)),
                            350,
                        ),
                        80,
                    )
                except ValueError:
                    resolved_rate = None

        # 4. Hearing test (Acoustic verification)
        if getattr(args, "hearing", False) or getattr(args, "hearing_test", False):
            troubleshooter = AudioTroubleshooter(config)
            as_json = getattr(args, "json", False)
            show_hud = getattr(args, "hud", False)
            if not as_json:
                print("\n👂 Running Hearing Test (Acoustic Reception & STT Check)...")
                print(f"🎙️ Playing test voice '{resolved_voice}' aloud over speakers...")
                print(f'💬 Test Phrase: "{sample_text}"\n')
            res = troubleshooter.test_hearing(
                voice_name_or_id=resolved_voice,
                text=sample_text,
                provider=provider,
                rate=resolved_rate,
                show_hud=show_hud,
            )
            if as_json:
                print(json.dumps(res.to_dict(), indent=2))
                return
            if res.success:
                print("=================================================================")
                print("👂 Hearing Test Results:")
                print(f'  • Spoken Phrase:  "{res.sent_text}"')
                print(f'  • Heard via Mic:  "{res.heard_text}"')
                print(f"  • Reception Match: {res.similarity_pct}%")
                print(f"  • Audio Latency:  {res.latency_ms} ms (RMS Energy: {res.rms_energy})")
                print("=================================================================\n")
            else:
                print(f"❌ Hearing test failed: {res.error}\n")
            return

        # 5. Feedback loop test (Speak -> Listen -> Transcribe -> Send)
        if (
            getattr(args, "feedback_loop", False)
            or getattr(args, "loopback", False)
            or getattr(args, "full_loop", False)
            or getattr(args, "verify", False)
        ):
            troubleshooter = AudioTroubleshooter(config)
            if (
                args.text
                or getattr(args, "phrase", None)
                or getattr(args, "voice", None)
                or getattr(args, "verify", False)
                or getattr(args, "feedback_loop", False)
            ):
                as_json = getattr(args, "json", False)
                show_hud = getattr(args, "hud", False)
                no_send = getattr(args, "no_send", False)
                target_cid = getattr(args, "conv_id", None)
                if not as_json:
                    print(
                        "\n🔄 Running Feedback Loop Test (Speak -> Listen -> Transcribe -> Send)..."
                    )
                    print(f"🎙️ Step 1: Speaking aloud as '{resolved_voice}' over speakers...")
                    print(f'💬 Outbound Message: "{sample_text}"\n')
                res = troubleshooter.test_feedback_loop(
                    voice_name_or_id=resolved_voice,
                    text=sample_text,
                    provider=provider,
                    rate=resolved_rate,
                    send_to_conversation=(not no_send),
                    conv_id=target_cid,
                    show_hud=show_hud,
                )
                if as_json:
                    print(json.dumps(res, indent=2))
                    return
                print("=================================================================")
                print("🎙️ Feedback Loop Test Results:")
                print(f'  • Sent Message:   "{res.get("sent_text")}"')
                print(f'  • Heard via Mic:  "{res.get("heard_text")}"')
                print(f"  • Accuracy Match: {res.get('similarity_pct')}%")
                print(
                    f"  • Audio Latency:  {res.get('latency_ms')} ms (RMS: {res.get('rms_energy')})"
                )
                if no_send:
                    delivered_str = "Dry-run / No send (--no-send) 🔍"
                else:
                    delivered_str = (
                        "Delivered to chat conversation ✅"
                        if res.get("sent_to_agent")
                        else "Printed to terminal ✅"
                    )
                print(f"  • Dispatch:       {delivered_str}")
                print("=================================================================\n")
                return

            print("\n🎙️ Running Microphone Loopback Test...")
            print("🔔 Ready... Recording begins in 1 second!")
            time.sleep(1.0)
            print("🔴 RECORDING NOW (4.0s) — Speak a sentence clearly into your microphone!")
            res = troubleshooter.test_microphone_loopback(duration_seconds=4.0, play_back=True)
            if res.success:
                print(f"✅ Captured {res.duration_s}s audio at {res.sample_rate}Hz.")
                print(
                    f"📊 RMS Energy: {res.rms_energy:.4f}, Peak: {res.peak_amplitude:.3f}, SNR: {res.snr_db:.1f} dB"
                )
                status = "Speech detected ✅" if res.speech_detected else "Quiet / Low audio ⚠️"
                print(f"🎙️ Detection: {status}")
                print("🔊 Playing your voice back over speakers now...")
                time.sleep(4.2)
                print("✨ Loopback playback complete.\n")
            else:
                print(f"❌ Microphone test failed: {res.error}\n")
            return

        # Barge-in interactive test
        if getattr(args, "barge_in", False) or getattr(args, "test_barge_in", False):
            cmd_barge_in(args)
            return

        # 6. Standard voice audition
        print(f"\n🔊 Auditioning voice: '{target_voice}' (Provider: {provider})")
        print(f'💬 Sample: "{sample_text}"')

        troubleshooter = AudioTroubleshooter(config)
        res = troubleshooter.test_voice(
            voice_name_or_id=resolved_voice,
            text=sample_text,
            provider=provider,
            rate=resolved_rate,
            block=True,
            show_hud=getattr(args, "hud", False),
        )
        if res.success:
            print(
                f"✅ Audition finished. Latency: {res.latency_ms} ms, Duration: {res.duration_s}s.\n"
            )
        else:
            print(f"❌ Audition failed: {res.error}\n")

    elif subaction == "audition":
        print("\n🎬 Starting VoiceFi Multi-Agent Voice Audition Showcase...\n")
        audition_cast = [
            (
                "Viv",
                "en-US-AvaNeural",
                "edge_tts",
                "Antigravity Primary Agent",
                "Hey! I'm Viv. Expressive, natural, and conversational tone, great for pair programming and deep focus.",
            ),
            (
                "Christopher",
                "en-US-ChristopherNeural",
                "edge_tts",
                "Architect / Deep Focus",
                "Hey! I'm Christopher. My calm, low-latency neural tone is great for deep focus and long coding sessions.",
            ),
            (
                "Aria",
                "en-US-EmmaNeural",
                "edge_tts",
                "Second Voice (Obsidian / Knowledge Vault)",
                "Hello! I'm Aria. I'm quick, expressive, and connected directly to your Obsidian knowledge vault.",
            ),
            (
                "Sonia",
                "en-GB-SoniaNeural",
                "edge_tts",
                "Researcher Subagent",
                "Greetings. I am Sonia. My clear British delivery is well suited for code audits and architecture reviews.",
            ),
            (
                "Guy",
                "en-US-GuyNeural",
                "edge_tts",
                "Conversational Pair",
                "Hey there! I'm Guy. I've got a casual, conversational delivery that feels like pair programming with a friend.",
            ),
        ]

        for name, vid, prov, role, text in audition_cast:
            print(f"🎙️ Playing Persona: {name} [{vid}] — Recommended for: {role}")
            print(f'   "{text}"')
            try:
                eng = get_tts_engine(config, voice_override=vid, provider_override=prov)
                eng.speak(text, block=True)
            except Exception as e:
                print(f"   ⚠️ Could not speak {name}: {e}")
            time.sleep(0.3)

        print(
            "\n✨ Audition showcase complete! Assign a voice using: 'vg voice set <agent> <voice_name>'\n"
        )

    elif subaction == "set":
        agent_raw = args.agent.strip() if args.agent else ""
        voice_raw = args.voice.strip() if getattr(args, "voice", None) else None

        known_agent_names = {
            "antigravity",
            "claude",
            "cursor",
            "windsurf",
            "obsidian",
            "vault",
            "researcher",
            "debugger",
            "architect",
            "tester",
            "writer",
            "analyst",
            "default",
            "global",
            "all",
        }

        # Case A: Only 1 positional argument passed
        if not voice_raw:
            p = find_persona(agent_raw)
            if p:
                target = "default"
                voice_id = p.id
                persona = p
            elif agent_raw.lower() in ("default", "global", "all"):
                print("⚠️ Please specify a voice to assign. Example: 'vg voice set default viv'")
                return
            elif agent_raw.lower() in known_agent_names or agent_raw.lower().startswith("subagent"):
                print(
                    f"⚠️ Please specify a voice to assign to '{agent_raw}'. Example: 'vg voice set {agent_raw} viv'"
                )
                return
            else:
                target = "default"
                voice_id = agent_raw
                persona = find_persona(voice_id)
        else:
            # Case B: 2 positional arguments passed
            p_first = find_persona(agent_raw)
            if p_first and voice_raw.lower() in known_agent_names:
                target = voice_raw.lower().strip()
                voice_id = agent_raw
                persona = p_first
            else:
                target = agent_raw.lower().strip()
                voice_id = voice_raw
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
                    resolved_rate = max(
                        min(
                            int(round(200 * (num / 100.0)))
                            if 0 < num <= 120
                            else int(round(num)),
                            350,
                        ),
                        80,
                    )
                except ValueError:
                    resolved_rate = None

        profile = AgentVoiceProfile(
            voice=resolved_voice,
            provider=resolved_provider,
            rate=resolved_rate,
            description=f"Assigned to {target}",
        )

        is_project = getattr(args, "project", False) is True
        subagent_roles = {"researcher", "debugger", "architect", "tester", "writer", "analyst"}
        if is_project or target.startswith("project.") or target.startswith("project_"):
            clean_proj = target.replace("project.", "").replace("project_", "").lower().strip()
            config.projects[clean_proj] = profile
            target_desc = f"project '{clean_proj}'"
        elif target in subagent_roles or target.startswith("subagent"):
            clean_role = target.replace("subagent.", "").replace("subagent_", "")
            config.subagents[clean_role] = profile
            target_desc = f"subagent '{clean_role}'"
        elif target in ("default", "global", "all"):
            config.tts.voice = resolved_voice
            config.tts.provider = resolved_provider
            if resolved_rate:
                config.tts.rate = resolved_rate
            config.agents["antigravity"] = AgentVoiceProfile(
                voice=resolved_voice,
                provider=resolved_provider,
                rate=resolved_rate,
                description="Assigned to antigravity (default)",
            )
            target_desc = "global default & primary agent (antigravity)"
        elif target in config.projects:
            config.projects[target.lower().strip()] = profile
            target_desc = f"project '{target}'"
        else:
            config.agents[target] = profile
            target_desc = f"agent '{target}'"

        save_config(config)
        rate_info = f" at {resolved_rate} WPM" if resolved_rate else ""
        print(
            f"✅ Successfully assigned {target_desc} to voice: '{resolved_voice}' ({resolved_provider}){rate_info}"
        )

        # Speak confirmation greeting aloud in the assigned voice
        if not getattr(args, "quiet", False) and not getattr(args, "silent", False):
            display_name = persona.name if persona else resolved_voice
            if "-" in display_name and "Neural" in display_name:
                display_name = display_name.split("-")[-1].replace("Neural", "")
            elif "(" in display_name:
                display_name = display_name.split("(")[0].strip()

            user_name = getattr(config, "user_name", "")
            agent_display = target.replace("_", " ").title()
            custom_phrase = getattr(args, "text", None)

            if custom_phrase:
                phrase = custom_phrase
            elif is_project or target in config.projects:
                clean_p_name = target.replace("project.", "").replace("project_", "").title()
                if user_name:
                    phrase = (
                        f"Hi {user_name}! I'm {display_name}, and I'm ready to speak for project {clean_p_name}."
                    )
                else:
                    phrase = f"Hi! I'm {display_name}, and I'm ready to speak for project {clean_p_name}."
            elif target in ("default", "global", "all"):
                if user_name:
                    phrase = (
                        f"Hi {user_name}! I'm {display_name}, and I'm ready as your default voice."
                    )
                else:
                    phrase = f"Hi! I'm {display_name}, and I'm ready as your default voice."
            elif user_name:
                phrase = f"Hi {user_name}! I'm {display_name}, and I'm ready to speak for {agent_display}."
            else:
                phrase = f"Hi! I'm {display_name}, and I'm ready to speak for {agent_display}."

            print(f'🔊 Playing confirmation: "{phrase}"')
            try:
                eng = get_tts_engine(
                    config,
                    agent_name="antigravity" if target in ("default", "global", "all") else target,
                    voice_override=resolved_voice,
                    provider_override=resolved_provider,
                    rate_override=resolved_rate,
                )
                eng.speak(phrase, block=True)
            except Exception as e:
                print(f"⚠️ Could not play spoken confirmation: {e}")

    elif subaction in ("rate", "speed"):
        raw_val = getattr(args, "value", None)
        if not raw_val:
            print(
                f"\n🎙️ Current Speech Rate: {config.tts.rate} WPM ({int(round((config.tts.rate / 200.0) * 100))}% speed)"
            )
            if "antigravity" in config.agents and config.agents["antigravity"].rate:
                ag_rate = config.agents["antigravity"].rate
                print(
                    f"  • Antigravity Rate: {ag_rate} WPM ({int(round((ag_rate / 200.0) * 100))}% speed)"
                )
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
        print(
            f"  • Global Default: {config.tts.voice} ({config.tts.provider}) - Rate: {config.tts.rate} WPM ({int(round((config.tts.rate / 200.0) * 100))}%)"
        )
        if config.agents:
            print("\n  Agents:")
            for a_name, a_prof in config.agents.items():
                a_rate = a_prof.rate or config.tts.rate
                print(
                    f"    - {a_name}: {a_prof.voice} ({a_prof.provider or config.tts.provider}) - Rate: {a_rate} WPM ({int(round((a_rate / 200.0) * 100))}%)"
                )
        if config.subagents:
            print("\n  Subagents:")
            for s_name, s_prof in config.subagents.items():
                s_rate = s_prof.rate or config.tts.rate
                print(
                    f"    - {s_name}: {s_prof.voice} ({s_prof.provider or config.tts.provider}) - Rate: {s_rate} WPM ({int(round((s_rate / 200.0) * 100))}%)"
                )
        if config.projects:
            print("\n  Projects:")
            for p_name, p_prof in config.projects.items():
                p_rate = p_prof.rate or config.tts.rate
                print(
                    f"    - {p_name}: {p_prof.voice} ({p_prof.provider or config.tts.provider}) - Rate: {p_rate} WPM ({int(round((p_rate / 200.0) * 100))}%)"
                )
        print()
    elif subaction in ("speed-talk", "speedtalk", "speed_talk"):
        cmd_speed_talk(args)
        return
    else:
        print("Use: vg voice [list|test|audition|set|get|rate|speed|speed-talk|train] --help")
