"""
CLI interface for VoiceFi.
Supports Antigravity hook integration, one-shot voice dictation, background server loop, and setup.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from voicefi import __version__
from voicefi.cli_format import VoiceFiArgumentParser, resolve_prog_name, render_categorized_help
from voicefi.config import load_config, save_config, get_default_config_path, VALID_GEMINI_LIVE_VOICES
from voicefi.license import FeatureGate
from voicefi.tts import (
    get_tts_engine,
    MacSayTTS,
    set_cross_process_hud_state,
    clear_cross_process_hud_state,
)
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.antigravity import handle_antigravity_stop_hook
from voicefi.integrations.injector import inject_text_to_active_app
from voicefi.memo import (
    MemoBufferRecorder,
    MemoSynthesizer,
    MemoStore,
    MemoRecording,
)


from voicefi.cli_commands.hooks import cmd_hook as _cmd_hook


def cmd_hook(args):
    """Handle AI agent lifecycle hook from stdin or manage hook configurations."""
    return _cmd_hook(args)


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
    speed_override = getattr(args, "speed", None) or getattr(args, "speed_talk", None)
    if getattr(args, "fast", False) and not speed_override:
        speed_override = "fast"
    tts = get_tts_engine(
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


def cmd_new(args):
    """Start a brand new Antigravity conversation with connected tools."""
    from voicefi.integrations.injector import create_new_antigravity_conversation

    config = load_config(args.config)
    prompt = " ".join(args.prompt) if getattr(args, "prompt", None) else "Hello"
    title = getattr(args, "title", None)
    model = getattr(args, "model", None)

    print("✨ Initializing new Antigravity conversation with connected tools...")
    cid = create_new_antigravity_conversation(prompt=prompt, title=title, model=model)
    if cid:
        print(f"✅ New conversation created and focused: {cid}")
        if config.audio_cues.enabled:
            play_chime("start", block=False)
    else:
        print("🚀 New conversation command dispatched to Antigravity.")


def cmd_send(args):
    """Send a message/task across agents (Antigravity ↔ Claude Code) or across peer Macs."""
    text = " ".join(args.text) if isinstance(args.text, list) else str(args.text or "")
    if not text.strip():
        print("❌ Error: message text cannot be empty.", file=sys.stderr)
        sys.exit(1)

    target_engine = getattr(args, "to", "claude") or "claude"
    conv_id = getattr(args, "conv_id", None)
    if getattr(args, "reply", False):
        conv_id = "reply"

    from_conv_id = getattr(args, "from_conv_id", None)
    from_engine = getattr(args, "from_engine", "antigravity")
    sender_name = getattr(args, "sender_name", None)
    title = getattr(args, "title", None)
    include_envelope = not getattr(args, "no_envelope", False)

    # 1. Check if target is a remote peer Mac on the local Wi-Fi / LAN
    local_engines = {"claude", "antigravity", "gemini", "chatgpt", "codex"}
    from voicefi.network.peers import PeerDiscoveryEngine, PeerClient

    peer_match = None
    if target_engine.lower() not in local_engines:
        peer_match = PeerDiscoveryEngine.resolve_target(target_engine)

    if peer_match:
        print(f"🚀 Dispatching cross-machine task to {peer_match.friendly_name} ({peer_match.ip})...")
        res = PeerClient.send_task(
            peer=peer_match,
            text=text.strip(),
            target_engine=getattr(args, "engine", "auto") or "auto",
            sender_name=sender_name,
            reply=getattr(args, "reply", False),
            from_conv_id=from_conv_id,
        )
        if res.get("success") or res.get("delivered"):
            print(f"✅ Delivered successfully to {peer_match.friendly_name}!")
            return
        else:
            print(f"❌ Could not deliver to {peer_match.friendly_name}: {res.get('error', 'unknown error')}", file=sys.stderr)
            sys.exit(1)

    # 2. Local Agent Dispatch
    from voicefi.integrations.injector import send_message_to_agent

    use_headless = getattr(args, "headless", None)
    print(f"🚀 Dispatching message to {target_engine.capitalize()}...")
    send_kwargs = {
        "conv_id": conv_id,
        "text": text.strip(),
        "sender_name": sender_name,
        "title": title,
        "target_engine": target_engine,
        "from_conv_id": from_conv_id,
        "from_engine": from_engine,
        "include_envelope": include_envelope,
    }
    if use_headless is not None:
        send_kwargs["use_headless"] = use_headless
    success = send_message_to_agent(**send_kwargs)

    if success:
        print(f"✅ Delivered successfully to {target_engine.capitalize()}.")
    else:
        print(f"⚠️ Could not deliver directly to {target_engine.capitalize()}.", file=sys.stderr)

    try:
        from voicefi.telemetry import capture_agent_dispatch

        capture_agent_dispatch(
            source_engine=from_engine,
            target_engine=target_engine,
            is_reply=getattr(args, "reply", False),
            char_count=len(text.strip()),
            success=success,
        )
    except Exception:
        pass

    if not success:
        sys.exit(1)


def cmd_peers(args):
    """Discover VoiceFi peers on local network."""
    import asyncio
    from voicefi.network.peers import PeerDiscoveryEngine

    print("\n🔍 Scanning local Wi-Fi network for VoiceFi Macs...")
    loop = asyncio.new_event_loop()
    try:
        peers = loop.run_until_complete(PeerDiscoveryEngine.discover_all(timeout=1.2))
    finally:
        loop.close()

    print("\n" + "=" * 65)
    print(" 📡 VoiceFi Local Network Peers & Vandelay Handoff")
    print("=" * 65)

    if not peers:
        print("  ⚠️ No peer Macs found on local network yet.")
        print("  💡 Start VoiceFi server on your other Mac with: vifi start")
    else:
        for p in peers:
            local_badge = " (This Mac)" if p.is_local else ""
            agents_str = ", ".join(a.capitalize() for a in p.agents) if p.agents else "Companion"
            print(f" • \033[1;36m{p.friendly_name}\033[0m{local_badge}")
            print(f"   ├─ Host:    {p.ip}:{p.port} ({p.hostname}) · {p.latency_ms}ms")
            print(f"   ├─ OS/Tier: {p.os_info} · \033[1;32m{p.tier}\033[0m")
            print(f"   └─ Agents:  {agents_str}")
            print()

    print("⚡ Quick Commands:")
    print("  • Send task:      vifi send \"<prompt>\" --to <peer-name>")
    print("  • Push clipboard: vifi clip push <peer-name>")
    print("  • Pull clipboard: vifi clip pull <peer-name>")
    print("  • Vandelay mode:  vifi vandelay")
    print("=" * 65 + "\n")


def cmd_vandelay(args):
    """Vandelay Industries: Importers & Exporters of code, prompts & clipboards."""
    subaction = getattr(args, "action", None)
    if subaction in ["import", "in"]:
        target = getattr(args, "target", None)
        if target:
            from voicefi.network.peers import PeerDiscoveryEngine, PeerClient
            peer = PeerDiscoveryEngine.resolve_target(target)
            if not peer:
                print(f"❌ Error: Peer '{target}' not found on local network.", file=sys.stderr)
                sys.exit(1)
            print(f"📦 Vandelay Industries: Importing clipboard from {peer.friendly_name} ({peer.ip})...")
            res = PeerClient.pull_clipboard(peer)
            if res.get("success") and "text" in res:
                import subprocess
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
                p.communicate(input=res["text"])
                print(f"✅ Imported {res.get('chars', len(res['text']))} chars into local clipboard!")
            else:
                print(f"⚠️ Failed to import: {res.get('error', 'unknown error')}", file=sys.stderr)
                sys.exit(1)
            return

    elif subaction in ["export", "out"]:
        target = getattr(args, "target", None)
        if target:
            from voicefi.network.peers import PeerDiscoveryEngine, PeerClient
            import subprocess
            res = subprocess.run(["pbpaste"], capture_output=True, text=True)
            clip_text = res.stdout if res.returncode == 0 else ""
            if not clip_text:
                print("⚠️ Local clipboard is empty.", file=sys.stderr)
                return
            peer = PeerDiscoveryEngine.resolve_target(target)
            if not peer:
                print(f"❌ Error: Peer '{target}' not found on local network.", file=sys.stderr)
                sys.exit(1)
            print(f"📦 Vandelay Industries: Exporting clipboard to {peer.friendly_name} ({peer.ip})...")
            res = PeerClient.push_clipboard(peer, clip_text)
            if res.get("success"):
                print(f"✅ Exported {len(clip_text)} chars to {peer.friendly_name} clipboard!")
            else:
                print(f"⚠️ Failed to export: {res.get('error')}", file=sys.stderr)
                sys.exit(1)
            return

    print("\n" + "=" * 65)
    print(" 🏢 Vandelay Industries — Importers & Exporters of Fine Code")
    print("=" * 65)
    cmd_peers(args)


def cmd_clip(args):
    """Push or pull clipboard snippets across peer Macs."""
    action = getattr(args, "action", "push") or "push"
    target = getattr(args, "target", None)
    if not target:
        print("❌ Error: Target peer name or IP required (e.g. 'vifi clip push mba' or 'vifi clip pull pro').", file=sys.stderr)
        sys.exit(1)

    from voicefi.network.peers import PeerDiscoveryEngine, PeerClient
    peer = PeerDiscoveryEngine.resolve_target(target)
    if not peer:
        print(f"❌ Error: Could not find peer '{target}' on local Wi-Fi network.", file=sys.stderr)
        print("💡 Run 'vifi peers' to scan and list available Macs.", file=sys.stderr)
        sys.exit(1)

    if action in ["push", "send", "set"]:
        import subprocess
        res = subprocess.run(["pbpaste"], capture_output=True, text=True)
        clip_text = res.stdout if res.returncode == 0 else ""
        if not clip_text:
            print("⚠️ Local clipboard is empty.", file=sys.stderr)
            return
        print(f"📋 Pushing {len(clip_text)} chars to {peer.friendly_name} ({peer.ip})...")
        resp = PeerClient.push_clipboard(peer, clip_text)
        if resp.get("success"):
            print(f"✅ Copied to {peer.friendly_name} clipboard successfully!")
        else:
            print(f"❌ Failed: {resp.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif action in ["pull", "get", "fetch"]:
        print(f"📋 Pulling clipboard from {peer.friendly_name} ({peer.ip})...")
        resp = PeerClient.pull_clipboard(peer)
        if resp.get("success") and "text" in resp:
            import subprocess
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            p.communicate(input=resp["text"])
            print(f"✅ Pulled {len(resp['text'])} chars into local clipboard!")
        else:
            print(f"❌ Failed: {resp.get('error')}", file=sys.stderr)
            sys.exit(1)



from voicefi.cli_commands.media import (
    cmd_duel as _cmd_duel,
    cmd_sfx as _cmd_sfx,
    cmd_fx as _cmd_fx,
    cmd_reel as _cmd_reel,
    cmd_trim as _cmd_trim,
)


def cmd_duel(args):
    """Run an acoustic voice banter / joke duel between Antigravity and Claude Code."""
    return _cmd_duel(args)


def cmd_sfx(args):
    """Play a comedy or dramatic sound effect (drum_smash, honk, sad_trombone, applause, boing, crickets)."""
    return _cmd_sfx(args)


def cmd_fx(args):
    """Apply studio voice transformation DSP effect (radio announcer, podcast, monster, etc.)."""
    return _cmd_fx(args)


def cmd_reel(args):
    """Compile multi-format social video reels from audio and slides, or documentary mode."""
    return _cmd_reel(args)


def cmd_trim(args):
    """Trim audio file start and end points with smooth de-clicking fades."""
    return _cmd_trim(args)


def cmd_tray(args):
    """Launch macOS menu bar tray companion."""
    from voicefi.ui.tray import run_tray

    print("🚀 Launching VoiceFi menu bar tray...")
    run_tray()


def cmd_quick_bar(args):
    """Launch or toggle native macOS Quick Prompt Bar (Control+Space)."""
    raw_text = getattr(args, "text", None)
    initial_text = " ".join(raw_text) if isinstance(raw_text, list) else str(raw_text or "")
    clean_text = initial_text.strip()

    # Try communicating with running background daemon first
    try:
        import urllib.request
        import json

        endpoint = "http://127.0.0.1:5141/api/quick-bar/show" if clean_text else "http://127.0.0.1:5141/api/quick-bar/toggle"
        payload = json.dumps({"text": clean_text}).encode("utf-8") if clean_text else b"{}"
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                print("✨ Quick Prompt Bar summoned on active display.")
                return
    except Exception:
        pass

    import AppKit
    from PyObjCTools import AppHelper
    from voicefi.ui.quick_bar import QuickPromptBarWindow

    print("✨ Launching VoiceFi Quick Prompt Bar (Control+Space)...")
    app = AppKit.NSApplication.sharedApplication()
    AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    bar = QuickPromptBarWindow.get_instance()
    bar.show(initial_text=clean_text or None)
    AppHelper.runEventLoop()


def cmd_welcome(args):
    """Launch native macOS Welcome & License Activation Window."""
    import AppKit
    from PyObjCTools import AppHelper
    from voicefi.ui.welcome import VoiceFiWelcomeWindow

    print("👋 Launching VoiceFi Welcome & License Activation Window...")
    app = AppKit.NSApplication.sharedApplication()
    AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    VoiceFiWelcomeWindow.show_window()
    AppHelper.runEventLoop()


def cmd_dev(args):
    """Launch VoiceFi in foreground development mode with live console logs and auto-takeover."""
    from voicefi.server import stop_all_voicefi_servers, clean_caches, get_launchagent_status
    from voicefi.ui.tray import run_tray

    print("\n🛠️  Preparing VoiceFi DEV Environment...")
    la_status = get_launchagent_status()
    if la_status.get("is_loaded") or la_status.get("pid"):
        print(
            "⏸️  Temporarily stopping background LaunchAgent server to prevent port/lock conflicts..."
        )
        stop_all_voicefi_servers(disable_launchagent=True, timeout_seconds=2.0)
    else:
        # Stop any orphaned processes
        stop_all_voicefi_servers(disable_launchagent=False, timeout_seconds=1.0)

    # Clean stale bytecode and temporary locks
    clean_caches(clean_pycache=True, clean_tmp_state=True, clean_update_cache=True)
    print("🧹 Stale caches and locks cleared.")
    print("🚀 Launching VoiceFi in DEV mode (live logs active, Ctrl+C to exit)...\n")
    try:
        run_tray(force=True)
    except KeyboardInterrupt:
        print("\n👋 VoiceFi DEV mode stopped cleanly.")


def cmd_wake(args):
    """Run interactive foreground 'Hey Viv' wake-word listener with live console logs."""
    import time
    from voicefi.config import load_config
    from voicefi.audio.wakeword import WakeWordListener
    from voicefi.audio.recorder import AudioRecorder
    from voicefi.audio.chimes import play_chime
    from voicefi.stt import get_stt_engine
    from voicefi.integrations.injector import send_message_to_antigravity
    from voicefi.stt.biasing import PhoneticNormalizer

    config = load_config(getattr(args, "config", None))
    aliases = list(getattr(config.wakeword, "aliases", ["hey viv", "viv", "hey vifi"]))
    phrase = getattr(config.wakeword, "phrase", "Hey Viv")

    print("\n🎙️  VoiceFi 'Hey Viv' Wake-Word Studio")
    print("==================================================================")
    print(f"  • Primary Trigger:   '{phrase}'")
    print(f"  • Active Aliases:    {', '.join(aliases)}")
    print("  • Target Channel:    Antigravity (agentapi IPC)")
    print(f"  • Acoustic Chime:    {'Enabled' if config.wakeword.chime else 'Disabled'}")
    print("==================================================================")
    print("👉 Say 'Hey Viv' or 'Hey Viv, <your command>' aloud (Ctrl+C to exit)...\n")

    def _on_wake(matched_phrase: str, prompt: str):
        print(f"\n⚡ [WAKE TRIGGERED] Matched '{matched_phrase}'")
        phrase_lower = matched_phrase.lower().strip()
        is_claude = "claude" in phrase_lower or any(
            k in phrase_lower for k in ("claud", "clod", "clawed", "glenn", "hague")
        )
        target_engine = "claude" if is_claude else "antigravity"
        agent_name = "Claude Code" if is_claude else "Antigravity"

        def _dispatch_prompt(raw_text: str):
            norm = PhoneticNormalizer.normalize(raw_text.strip())
            print(f'🚀 Prompt: "{norm}"')

            # Check if on-device intent routing is enabled
            if getattr(getattr(config, "local_model", None), "intent_routing", False):
                from voicefi.local.intent import LocalIntentRouter
                router = LocalIntentRouter(config=config)
                route = router.route_prompt(norm)

                if route.get("status") == "handled_local":
                    spoken = route.get("spoken_response", "")
                    print(f"⚡ [Local Action Handled] {spoken}")
                    from voicefi.tts import get_tts_engine
                    tts = get_tts_engine(config)
                    tts.speak(spoken, block=False)
                    return
                elif route.get("status") == "routed_obsidian":
                    spoken = route.get("spoken_response", "")
                    print(f"💎 [Obsidian Routed] {spoken}")
                    from voicefi.tts import get_tts_engine
                    tts = get_tts_engine(config)
                    tts.speak(spoken, block=False)
                    return
                elif route.get("target") in ("codex", "claude", "antigravity"):
                    routed_engine = route.get("target")
                    active_agent_name = (
                        "ChatGPT / Codex" if routed_engine == "codex"
                        else "Claude Code" if routed_engine == "claude"
                        else "Antigravity"
                    )
                    print(f"📤 Dispatching to {active_agent_name}...")
                    res = send_message_to_agent(
                        text=norm,
                        sender_name=f"{config.user_name} ({matched_phrase})",
                        title=f"Prompt via {matched_phrase}",
                        target_engine=routed_engine,
                        use_headless=True if routed_engine == "claude" else None,
                    )
                    if res.success:
                        print(f"✅ Delivered to {active_agent_name} conversation ({res.delivery_type.upper()})")
                        if config.audio_cues.enabled:
                            play_chime(config.audio_cues.sent_chime, block=False)
                    else:
                        print(f"⚠️ Dispatch notice: {res.error}")
                    return

            # Default routing
            print(f"📤 Dispatching to {agent_name}...")
            res = send_message_to_agent(
                text=norm,
                sender_name=f"{config.user_name} ({matched_phrase})",
                title=f"Prompt via {matched_phrase}",
                target_engine=target_engine,
                use_headless=True if is_claude else None,
            )
            if res.success:
                print(f"✅ Delivered to {agent_name} conversation ({res.delivery_type.upper()})")
                if config.audio_cues.enabled:
                    play_chime(config.audio_cues.sent_chime, block=False)
            else:
                print(f"⚠️ Dispatch notice: {res.error}")

        if prompt and len(prompt.strip()) >= 3:
            _dispatch_prompt(prompt)
        else:
            print(f"🎙️ Wake word detected for {agent_name} without prompt -> Listening for command...")
            if config.audio_cues.enabled:
                play_chime("start", block=False)
            recorder = AudioRecorder(
                sample_rate=config.vad.sample_rate,
                energy_threshold=config.vad.energy_threshold,
                silence_duration=config.vad.silence_duration,
            )
            _, temp_wav = recorder.record_speech_auto()
            try:
                stt = get_stt_engine(config)
                text = stt.transcribe(temp_wav)
                if text and text.strip():
                    _dispatch_prompt(text)
            finally:
                if temp_wav:
                    try:
                        temp_wav.unlink(missing_ok=True)
                    except Exception:
                        pass
        print("\n👂 Resumed listening for 'Hey Viv'...")

    listener = WakeWordListener(
        config=config,
        on_wake=_on_wake,
    )
    listener.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n👋 'Hey Viv' wake listener stopped.")
        listener.stop()


from voicefi.cli_commands.server import (
    cmd_clean as _cmd_clean,
    cmd_server as _cmd_server,
    cmd_autostart as _cmd_autostart,
    cmd_stop_autostart as _cmd_stop_autostart,
    cmd_pause as _cmd_pause,
    cmd_resume as _cmd_resume,
)


def cmd_clean(args):
    """Clean stale Python bytecode, caches, temporary files, and optionally stop running servers."""
    return _cmd_clean(args)


def cmd_server(args):
    """Manage VoiceFi background server, LaunchAgents, and port listeners."""
    return _cmd_server(args)


cmd_daemon = cmd_server


def cmd_onboarding(args):
    """Run interactive First-Time User Experience onboarding flow."""
    from voicefi.onboarding import run_onboarding

    run_onboarding()


def cmd_permissions(args):
    """Open macOS Accessibility and Input Monitoring security settings."""
    from voicefi.integrations.injector import open_accessibility_settings

    try:
        import ApplicationServices

        options = {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
        trusted = ApplicationServices.AXIsProcessTrustedWithOptions(options)
    except Exception:
        trusted = False

    print("\n🔐 macOS Accessibility & Hotkey Permissions")
    print("------------------------------------------------------------------")
    if trusted:
        print("✅ Accessibility permissions are granted and active!")
    else:
        print("⚠️  Accessibility permission is not yet enabled for this terminal/app.")
        print("👉 Opening macOS System Settings...")
        open_accessibility_settings()
        print("Please toggle Terminal / iTerm / Antigravity to ON in the list.")
    print("------------------------------------------------------------------\n")


def cmd_mcp(args):
    """Run native Stdio JSON-RPC 2.0 Model Context Protocol (MCP) Server for VoiceFi."""
    if getattr(args, "test", False) or getattr(args, "ping", False) or getattr(args, "check", False):
        from voicefi.mcp_server import test_posthog_mcp_analytics
        import json

        result = test_posthog_mcp_analytics()
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
            return

        print("\n" + "=" * 60)
        print("  📊 PostHog MCP Analytics — Diagnostics & Egress Test")
        print("=" * 60)
        if result.get("success"):
            print(f"  ✅ Status:           Connected & Delivering ({result.get('status', 'ok')})")
            print(f"  🔑 API Key:          {result.get('api_key_masked')}")
            print(f"  🌐 Ingestion Host:   {result.get('host')}")
            print(f"  👤 Distinct ID:      {result.get('distinct_id')}")
            print(f"  ⚡ Roundtrip Latency: {result.get('latency_ms')} ms")
            print("  📦 Events Emitted:")
            for evt in result.get("events_captured", []):
                print(f"     • {evt}")
            print("\n  👉 Events successfully captured and verified on PostHog dashboard.")
        else:
            print(f"  ❌ Error:            {result.get('error')}")
            print(f"  🌐 Ingestion Host:   {result.get('host')}")
            print(f"  👤 Distinct ID:      {result.get('distinct_id')}")
        print("=" * 60 + "\n")
        return

    from voicefi.mcp_server import run_mcp_server

    run_mcp_server()


def cmd_setup(args):
    """Automatically register VoiceFi lifecycle hooks and MCP server with AI agents (Antigravity, Claude Code, Claude Desktop)."""
    import shutil
    from voicefi.integrations.claude import install_claude_hook, install_claude_desktop_mcp
    from voicefi.integrations.discovery import AgentToolDetector

    setup_all = getattr(args, "all", False)
    setup_claude = getattr(args, "claude", False) or setup_all
    setup_antigravity = getattr(args, "antigravity", False) or setup_all
    is_dev = getattr(args, "dev", False)

    if getattr(args, "remove_hooks", False):
        from voicefi.integrations.antigravity import remove_antigravity_hook
        from voicefi.integrations.claude import remove_claude_hook

        remove_antigravity_hook()
        remove_claude_hook()
        print("🗑️ VoiceFi hooks removed from Antigravity and Claude Code configuration files.")
        return

    # If no explicit agent flags are specified, auto-detect active systems
    if (
        not getattr(args, "claude", False)
        and not getattr(args, "antigravity", False)
        and not setup_all
    ):
        setup_antigravity = True
        if AgentToolDetector.detect_claude_code():
            setup_claude = True

    # Resolution logic: if --dev, prioritize project venv
    bin_path = None
    if is_dev:
        ws_candidates = [
            Path.cwd() / ".venv" / "bin" / "voicefi",
            Path.cwd() / "venv" / "bin" / "voicefi",
            Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "voicefi",
        ]
        for cand in ws_candidates:
            if cand.is_file() and os.access(str(cand), os.X_OK):
                bin_path = str(cand)
                break

    if not bin_path:
        venv_bin = Path(sys.executable).parent / "voicefi"
        if venv_bin.exists():
            bin_path = str(venv_bin)
        else:
            bin_path = shutil.which("voicefi") or shutil.which("vifi") or "voicefi"

    if setup_antigravity:
        hook_command = f"{bin_path} hook"
        hooks_data = {
            "voicefi-voice-layer": {
                "enabled": True,
                "Stop": [
                    {
                        "type": "command",
                        "command": hook_command,
                        "timeout": 60,
                    }
                ],
            }
        }

        plugin_dir = Path.home() / ".gemini" / "config" / "plugins" / "voicefi-plugin"
        plugin_dir.mkdir(parents=True, exist_ok=True)

        mcp_server_entry = {
            "command": bin_path,
            "args": ["mcp"],
        }

        # Install as standard Antigravity plugin in ~/.gemini/config/plugins/voicefi-plugin
        try:
            plugin_json_path = plugin_dir / "plugin.json"
            plugin_manifest = {
                "name": "voicefi-plugin",
                "version": "1.0.0",
                "description": "VoiceFi Voice Layer lifecycle hooks, skills, and MCP tools for Antigravity AI coding agent.",
                "author": {"name": "VoiceFi"},
                "keywords": ["voice", "voicefi", "tts", "stt", "vad", "mcp"],
            }
            with open(plugin_json_path, "w", encoding="utf-8") as f:
                json.dump(plugin_manifest, f, indent=2)

            plugin_hooks_path = plugin_dir / "hooks.json"
            with open(plugin_hooks_path, "w", encoding="utf-8") as f:
                json.dump(hooks_data, f, indent=2)

            # Register plugin MCP config
            plugin_mcp_path = plugin_dir / "mcp_config.json"
            plugin_mcp_data = {"mcpServers": {"voicefi": mcp_server_entry}}
            with open(plugin_mcp_path, "w", encoding="utf-8") as f:
                json.dump(plugin_mcp_data, f, indent=2)

            # Sync bundled skills into plugin directory
            skills_src_dir = Path(__file__).resolve().parent.parent.parent / ".agents" / "skills"
            if not skills_src_dir.is_dir():
                skills_src_dir = Path.cwd() / ".agents" / "skills"
            if skills_src_dir.is_dir():
                plugin_skills_dir = plugin_dir / "skills"
                plugin_skills_dir.mkdir(parents=True, exist_ok=True)
                for skill_sub in skills_src_dir.iterdir():
                    if skill_sub.is_dir():
                        target_sub = plugin_skills_dir / skill_sub.name
                        target_sub.mkdir(parents=True, exist_ok=True)
                        for s_file in skill_sub.glob("*"):
                            if s_file.is_file():
                                shutil.copy2(s_file, target_sub / s_file.name)

            # Sync rules (AGENTS.md) into plugin directory
            agents_rule_src = Path(__file__).resolve().parent.parent.parent / "AGENTS.md"
            if not agents_rule_src.is_file():
                agents_rule_src = Path.cwd() / "AGENTS.md"
            if agents_rule_src.is_file():
                plugin_rules_dir = plugin_dir / "rules"
                plugin_rules_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(agents_rule_src, plugin_rules_dir / "AGENTS.md")

            # Register in ~/.gemini/config/config.json
            global_config_json = Path.home() / ".gemini" / "config" / "config.json"
            if global_config_json.is_file():
                try:
                    c_data = json.loads(global_config_json.read_text(encoding="utf-8")) or {}
                    if "plugins" not in c_data:
                        c_data["plugins"] = {}
                    c_data["plugins"]["voicefi-plugin"] = {"enabled": True}
                    global_config_json.write_text(json.dumps(c_data, indent=2), encoding="utf-8")
                except Exception:
                    pass

            # Clean duplicate global hook in ~/.gemini/config/hooks.json to prevent double-firing
            global_hooks_path = Path.home() / ".gemini" / "config" / "hooks.json"
            if global_hooks_path.is_file():
                try:
                    with open(global_hooks_path, "r", encoding="utf-8") as f:
                        gh = json.load(f) or {}
                    if "voicefi-voice-layer" in gh:
                        del gh["voicefi-voice-layer"]
                        with open(global_hooks_path, "w", encoding="utf-8") as f:
                            json.dump(gh, f, indent=2)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ Notice creating plugin registration: {e}")

        # Also register in global ~/.gemini/config/mcp_config.json
        try:
            global_mcp_path = Path.home() / ".gemini" / "config" / "mcp_config.json"
            global_mcp_data = {}
            if global_mcp_path.is_file():
                try:
                    with open(global_mcp_path, "r", encoding="utf-8") as f:
                        global_mcp_data = json.load(f) or {}
                except Exception:
                    global_mcp_data = {}
            if "mcpServers" not in global_mcp_data:
                global_mcp_data["mcpServers"] = {}
            global_mcp_data["mcpServers"]["voicefi"] = mcp_server_entry
            with open(global_mcp_path, "w", encoding="utf-8") as f:
                json.dump(global_mcp_data, f, indent=2)
            print(f"✅ Antigravity MCP server registered: {global_mcp_path}")
        except Exception as e:
            print(f"⚠️ Notice updating global MCP config: {e}")

        print(f"✅ Antigravity plugin & hook installed: {plugin_dir}")

        # Also update workspace-level .agents/mcp_config.json if present
        ws_agents_dir = Path.cwd() / ".agents"
        if ws_agents_dir.is_dir():
            ws_agents_hook = ws_agents_dir / "hooks.json"
            if ws_agents_hook.is_file():
                try:
                    with open(ws_agents_hook, "r", encoding="utf-8") as f:
                        wsh = json.load(f) or {}
                    if "voicefi-voice-layer" in wsh:
                        del wsh["voicefi-voice-layer"]
                        with open(ws_agents_hook, "w", encoding="utf-8") as f:
                            json.dump(wsh, f, indent=2)
                except Exception:
                    pass

            ws_agents_mcp = ws_agents_dir / "mcp_config.json"
            try:
                ws_mcp_data = {}
                if ws_agents_mcp.is_file():
                    try:
                        with open(ws_agents_mcp, "r", encoding="utf-8") as f:
                            ws_mcp_data = json.load(f) or {}
                    except Exception:
                        ws_mcp_data = {}
                if "mcpServers" not in ws_mcp_data:
                    ws_mcp_data["mcpServers"] = {}
                ws_mcp_data["mcpServers"]["voicefi"] = mcp_server_entry
                with open(ws_agents_mcp, "w", encoding="utf-8") as f:
                    json.dump(ws_mcp_data, f, indent=2)
                print(f"✅ Workspace Antigravity MCP config updated: {ws_agents_mcp}")
            except Exception as e:
                print(f"⚠️ Could not update workspace MCP config: {e}")

    if setup_claude:
        try:
            claude_settings = install_claude_hook(bin_path=bin_path)
            print(f"✅ Claude Code hook installed: {claude_settings}")
        except Exception as e:
            print(f"⚠️ Could not install Claude Code hook: {e}")
        try:
            claude_desktop_cfg = install_claude_desktop_mcp(bin_path=bin_path)
            if claude_desktop_cfg:
                print(f"✅ Claude Desktop MCP server registered: {claude_desktop_cfg}")
        except Exception as e:
            print(f"⚠️ Could not register Claude Desktop MCP server: {e}")

    # Auto-register Codex & ChatGPT Desktop MCP when detected
    if AgentToolDetector.detect_codex() or setup_all:
        try:
            from voicefi.integrations.codex import install_codex_mcp, install_codex_hook

            if install_codex_mcp(bin_path=bin_path):
                print("✅ OpenAI Codex MCP server registered: ~/.codex/config.toml")
            codex_hook_path = install_codex_hook(bin_path=bin_path)
            if codex_hook_path:
                print(f"✅ OpenAI Codex hook installed: {codex_hook_path}")
        except Exception as e:
            print(f"⚠️ Could not configure OpenAI Codex integration: {e}")

    # Ensure config file exists and defaults to Viv for overall and antigravity
    config_path = get_default_config_path()
    config = load_config()
    changed = False
    if not config_path.is_file():
        save_config(config)
    else:
        if not config.tts.voice or config.tts.voice in (
            "Samantha",
            "en-US-ChristopherNeural",
            "Christopher",
            "christopher",
        ):
            config.tts.voice = "en-US-AvaNeural"
            config.tts.provider = "edge_tts"
            changed = True
        if "antigravity" not in config.agents or config.agents["antigravity"].voice in (
            "en-US-ChristopherNeural",
            "Christopher",
            "christopher",
            None,
            "",
        ):
            from voicefi.config import AgentVoiceProfile

            config.agents["antigravity"] = AgentVoiceProfile(
                voice="en-US-AvaNeural",
                provider="edge_tts",
                offline_voice="Ava (Premium)",
                description="Antigravity Primary Agent",
            )
            changed = True
        if changed:
            save_config(config)

    print(f"⚙️ Configuration saved at: {config_path}")


def cmd_pause(args):
    """Pause VoiceFi audio hooks and active turn-handoffs globally."""
    return _cmd_pause(args)


def cmd_resume(args):
    """Resume VoiceFi audio hooks and active turn-handoffs globally."""
    return _cmd_resume(args)


def cmd_autostart(args):
    """Register macOS LaunchAgent so VoiceFi menu bar tray stays on and runs at login."""
    return _cmd_autostart(args)


def cmd_stop_autostart(args):
    """Unload and remove macOS LaunchAgent."""
    return _cmd_stop_autostart(args)

from voicefi.tts.catalog import (
    CURATED_PERSONAS,
    get_curated_personas,
    find_persona,
    list_all_available_voices,
)
from voicefi.tts.cloning import VoiceCloneManager, TRAINING_PROMPTS
from voicefi.feedback import submit_feedback, list_feedback, collect_system_diagnostics


from voicefi.cli_commands.voice import cmd_clone as _cmd_clone


def cmd_clone(args):
    """Train, record, import, test, assign, and manage custom cloned voices."""
    return _cmd_clone(args)


def cmd_companion(args):
    """Launch Web & Mobile Voice Companion server with QR pairing and PWA."""
    from voicefi.companion.server import run_companion_server

    config = load_config(args.config)
    port = getattr(args, "port", 5141)
    host = getattr(args, "host", "0.0.0.0")
    print_qr = not getattr(args, "no_qr", False)
    open_browser = getattr(args, "open", False)
    tunnel = getattr(args, "tunnel", False)
    action = getattr(args, "action", None)
    is_sheet = (getattr(args, "sheet", False) is True) or (
        isinstance(action, str)
        and action.lower() in ("sheet", "spicewood", "lead-sheet", "leadsheet", "track")
    )
    if is_sheet:
        open_browser = True
    initial_path = "/companion?tab=downloads&reel=spicewood" if is_sheet else "/companion"
    run_companion_server(
        port=port,
        host=host,
        print_qr=print_qr,
        open_browser=open_browser,
        tunnel=tunnel,
        config=config,
        initial_path=initial_path,
    )


def cmd_panel(args):
    """Launch interactive Voice Control Panel web dashboard."""
    import time
    import webbrowser
    from voicefi.ui.panel import open_control_panel

    port = getattr(args, "port", 5141)
    no_browser = getattr(args, "no_browser", False)
    is_claude = getattr(args, "claude", False) is True
    config = load_config(args.config)
    print(f"\n🎙️ Launching Voice Control Panel on port {port}...")
    url = open_control_panel(
        port=port, open_browser=not no_browser and not is_claude, config=config
    )
    actual_port = url.split(":")[-1]
    if is_claude and not no_browser:
        claude_url = f"http://localhost:{actual_port}/claude"
        try:
            webbrowser.open(claude_url)
        except Exception:
            pass
        print(f"🌐 Claude Contenders Studio running at: {claude_url}")
    else:
        print(f"🌐 Control Panel running at: {url}")
        print(f"🎭 Claude Contenders Studio available at: http://localhost:{actual_port}/claude")
    print("💡 Control via web UI or speak commands ('Audition Ryan', 'Switch to Thomas').")
    print("Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Voice Control Panel closed.")


def cmd_update(args):
    """Check for and install VoiceFi software upgrades."""
    from voicefi.updater import check_for_updates, perform_update, get_local_version

    current_ver = get_local_version()

    if getattr(args, "check", False):
        print(f"\n🔍 Checking for VoiceFi updates (current: v{current_ver})...")
        is_avail, latest_ver, url = check_for_updates(force=True)
        if is_avail:
            print(f"✨ Update available: v{current_ver} -> v{latest_ver}")
            print("👉 Run 'vifi update' to upgrade now.")
            if url:
                print(f"🔗 Release: {url}\n")
        else:
            print(f"✅ VoiceFi is up to date (v{current_ver})!\n")
        return

    # Perform update
    print(f"\n🚀 Updating VoiceFi (current: v{current_ver})...")
    custom_repo = getattr(args, "repo", None)
    res = perform_update(repo_url=custom_repo)
    if res.get("success"):
        print(f"\n✅ {res['message']}\n")
    else:
        print(f"\n❌ {res['message']}\n")
        if res.get("error"):
            print(f"Details: {res['error']}\n")


from voicefi.cli_commands.troubleshoot import (
    cmd_troubleshoot as _cmd_troubleshoot,
    cmd_hearing_test as _cmd_hearing_test,
    cmd_feedback_loop as _cmd_feedback_loop,
    cmd_loopback as _cmd_loopback,
    cmd_barge_in as _cmd_barge_in,
    cmd_ping as _cmd_ping,
    run_silent_voice_ping as _run_silent_voice_ping,
)


def cmd_troubleshoot(args):
    """Run interactive or automated Voice & Audio troubleshooting and test suite."""
    return _cmd_troubleshoot(args)


def cmd_hearing_test(args):
    """Run acoustic hearing test (speak aloud -> listen via mic -> STT verification)."""
    return _cmd_hearing_test(args)


def cmd_feedback_loop(args):
    """Manage ProActive Feedback Loop setting (on/off/status) or run acoustic loop test."""
    return _cmd_feedback_loop(args)


def cmd_loopback(args):
    """Alias for cmd_feedback_loop."""
    return _cmd_loopback(args)


def cmd_barge_in(args):
    """Run live interactive barge-in & Silero VAD interruption test."""
    return _cmd_barge_in(args)


def cmd_ping(args):
    """Silently test voice connection, latency, speed, and health."""
    return _cmd_ping(args)


def run_silent_voice_ping(args, config):
    """Execute silent voice connection, latency, speed, and health diagnostics."""
from voicefi.cli_commands.voice import cmd_download_ava as _cmd_download_ava
from voicefi.cli_commands.voice import cmd_voice as _cmd_voice


def cmd_download_ava(args):
    """Guide user through downloading & configuring Apple's Ava (Premium) for 0ms offline speech."""
    return _cmd_download_ava(args)


def cmd_voice(args):
    """Handle voice inspection, testing, auditioning, assignment, and voice commands."""
    return _cmd_voice(args)


from voicefi.cli_commands.speed_talk import cmd_speed_talk as _cmd_speed_talk


def cmd_speed_talk(args):
    """Handle Speed Talking acceleration, preset configuration, testing, and analytics."""
    return _cmd_speed_talk(args)
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
            print(
                f"  [{it.get('category', 'general').upper()}] {it.get('title')} ({it.get('timestamp', '')[:19]}) - ID: {it.get('id')}"
            )
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
        print(f"✅ Feedback logged successfully (ID: {record['id']}).")
        print("📁 Saved to ~/.voicefi/feedback.jsonl")
        print("⭐ Thank you for helping build VoiceFi! Drop a star on GitHub: https://github.com/atxatlarge-code/voicefi")


def cmd_record(args):
    """Record studio voice note directly from microphone."""
    import time
    import wave
    import sounddevice as sd
    from pathlib import Path

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


from voicefi.cli_commands.memo import cmd_memo as _cmd_memo


def cmd_memo(args):
    """Handle voice memo buffer recording, synthesis, and management."""
    return _cmd_memo(args)
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


def cmd_ambient(args):
    """Ambient background listening & proactive meeting co-pilot."""
    import time
    import datetime

    action = getattr(args, "ambient_action", "start") or "start"

    from voicefi.integrations.meeting import MeetingNoteTaker, ActionStatus

    note_taker = MeetingNoteTaker.get_instance()

    if action == "start":
        from voicefi.audio.ambient import AmbientAudioStream
        from voicefi.stt import get_stt_engine

        config = load_config(getattr(args, "config", None))
        stt = get_stt_engine(config)

        title = getattr(args, "title", None)
        output_path = getattr(args, "output", None)
        speaker = getattr(args, "speaker", None)
        auto_exec = getattr(args, "auto_execute", True)

        session = note_taker.start_session(
            title=title,
            output_path=output_path,
            auto_execute_actions=auto_exec,
            speaker_name=speaker,
        )

        print("\n🎙️ Starting VoiceFi ProActive Meeting Note Taker...")
        print(f"📋 Title: {session.title}")
        print(f"📄 Notes File: {session.markdown_path}")
        print(f"⚡ Auto-Execute Actions: {'✅ Enabled' if auto_exec else '❌ Disabled'}")
        print("💡 Listening in the background. Press Ctrl+C to finalize & save meeting notes.\n")

        def _on_utterance(audio_data, sample_rate):
            text = stt.transcribe(audio_data, sample_rate=sample_rate)
            if text:
                utt = note_taker.record_utterance(text, speaker_name=speaker)
                action_badge = " ⚡ [Action Triggered]" if utt.is_actionable else ""
                print(f'📝 `[{utt.timestamp_str}]` {utt.speaker}: "{utt.text}"{action_badge}')

                if utt.is_actionable and session.action_items:
                    latest_action = session.action_items[-1]
                    res_str = latest_action.result_summary or latest_action.title
                    print(f"   👉 [{latest_action.category.value}] {res_str}")

        stream = AmbientAudioStream(
            sample_rate=config.vad.sample_rate,
            energy_threshold=config.proactive.meeting_assistant.energy_threshold,
            silence_duration=config.proactive.meeting_assistant.silence_duration,
            max_utterance_duration=config.proactive.meeting_assistant.max_utterance_seconds,
            on_utterance=_on_utterance,
        )
        stream.start()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            stream.stop()
            final_session = note_taker.stop_session()
            print("\n" + "=" * 60)
            print("🏁 Meeting Session Finalized!")
            print(
                f"📄 Notes saved to: {final_session.markdown_path if final_session else session.markdown_path}"
            )
            if final_session and final_session.action_items:
                print("\n⚡ Actions Executed Along The Way:")
                for a in final_session.action_items:
                    print(
                        f"  • [{a.category.value}] {a.title} -> {a.result_summary or a.status.value}"
                    )
            print("=" * 60 + "\n")

    elif action == "stop":
        session = note_taker.stop_session()
        if session:
            print(f"\n✅ Meeting '{session.title}' finalized.")
            print(f"📄 Notes saved to: {session.markdown_path}")
            print(f"⏱️ Total Duration: {session.duration_formatted}")
            print(f"📝 Spoken Turns: {len(session.utterances)}")
            print(f"⚡ Actions Recorded: {len(session.action_items)}\n")
        else:
            print("\n⚪ No active meeting session found to stop.\n")

    elif action == "status":
        session = note_taker.active_session
        if session and session.status == "active":
            print(f"\n🟢 Active Meeting Session: {session.title}")
            print(f"  • Elapsed Duration: {session.duration_formatted}")
            print(f"  • Spoken Turns: {len(session.utterances)}")
            print(f"  • Decisions Recorded: {len(session.decisions)}")
            print(
                f"  • Actions Executed: {len([a for a in session.action_items if a.status == ActionStatus.COMPLETED])}"
            )
            print(f"  • Notes File: {session.markdown_path}\n")
        else:
            config = load_config(getattr(args, "config", None))
            print("\n⚪ ProActive Meeting Assistant: Standing by")
            print(f"  • Storage Directory: {config.proactive.meeting_assistant.notes_dir}")
            print(
                f"  • Auto-Execute Actions: {'✅ Enabled' if config.proactive.meeting_assistant.auto_execute_actions else '❌ Disabled'}"
            )
            print("  • Start on-demand with: 'vifi meeting start'\n")

    elif action == "list":
        files = note_taker.list_saved_sessions()
        if not files:
            print("\n📂 No saved meeting notes found yet.\n")
        else:
            print(f"\n📂 Saved Meeting Notes ({len(files)} sessions):")
            for f in files[:15]:
                dt = datetime.datetime.fromtimestamp(f["modified_at"]).strftime("%Y-%m-%d %H:%M")
                print(f"  • [{dt}] {f['title']} ({f['filename']})")
            print()

    elif action == "show":
        files = note_taker.list_saved_sessions()
        if not files:
            print("\n📂 No saved meeting notes found.\n")
            return
        target_id = getattr(args, "target", "latest") or "latest"
        target_file = files[0]["filepath"]
        if target_id != "latest":
            matched = [
                f["filepath"]
                for f in files
                if target_id in f["filename"] or target_id in f["title"]
            ]
            if matched:
                target_file = matched[0]

        with open(target_file, "r", encoding="utf-8") as f:
            print("\n" + f.read() + "\n")

    elif action in ("test", "simulate"):
        interactive = getattr(args, "interactive", False)
        import importlib.util
        from pathlib import Path

        qa_path = (
            Path(__file__).resolve().parent.parent.parent / "scripts" / "qa_meeting_simulation.py"
        )
        spec = importlib.util.spec_from_file_location("qa_meeting_simulation", str(qa_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        suite = mod.MeetingQASuite(verbose=True)
        if interactive:
            suite.run_interactive_tester()
        else:
            success = suite.run_automated_simulation()
            if not success:
                import sys

                sys.exit(1)


cmd_meeting = cmd_ambient


def cmd_obsidian(args):
    """Manage and install VoiceFi plugin into Obsidian vaults."""
    from voicefi.integrations.obsidian import (
        is_obsidian_installed,
        install_obsidian_app,
        find_obsidian_vaults,
        install_plugin_to_vault,
        create_starter_vault,
    )

    action = getattr(args, "obsidian_action", None) or "install"

    if action == "list":
        if not is_obsidian_installed():
            print("\n⚠️  Obsidian is not installed on this Mac.")
            print("   Run 'vifi obsidian install' to automatically download and configure it!\n")

        vaults = find_obsidian_vaults()
        if not vaults:
            print("\n🔍 No registered Obsidian vaults found on this machine.")
            print("   Default location: ~/Documents/Obsidian Vault\n")
            return

        print(f"\n📚 Discovered Obsidian Vaults ({len(vaults)} found):")
        for i, v in enumerate(vaults, 1):
            status = "🟢 (Active / Open)" if v["open"] else "⚪"
            print(f"   {i}. {status} {v['name']}")
            print(f"      Path: {v['path']}")
        print()
        return

    elif action == "install":
        target_vault = getattr(args, "vault", None)
        install_all = getattr(args, "all", False)

        print("\n🎙️  VoiceFi Obsidian Plugin Installer")
        print("   'Second Brain, Second Voice • The vocal cords for your vault.'\n")

        # 1. Check if Obsidian app itself is installed
        if not is_obsidian_installed():
            print("⚠️  Obsidian.app is not currently installed on your Mac.")
            install_app = getattr(args, "install_app", False)
            if install_app or input(
                "👉 Would you like VoiceFi to install Obsidian for you now? [Y/n]: "
            ).strip().lower() in ("", "y", "yes"):
                install_obsidian_app()
            else:
                print("💡 You can download Obsidian anytime from https://obsidian.md/download\n")

        # 2. Discover or create vault
        if target_vault:
            targets = [Path(target_vault)]
        else:
            discovered = find_obsidian_vaults()
            if not discovered:
                print(
                    "📁 No existing vaults found. Creating a new starter Obsidian Vault at ~/Documents/Obsidian Vault..."
                )
                starter_path = create_starter_vault()
                targets = [starter_path]
            elif install_all:
                targets = [v["path"] for v in discovered]
            else:
                targets = [discovered[0]["path"]]

        installed_count = 0
        for vault_p in targets:
            try:
                print(f"📦 Installing VoiceFi plugin to: {vault_p.name} ({vault_p})...")
                install_plugin_to_vault(vault_p)
                print(f"   ✅ Plugin bundle copied to: {vault_p}/.obsidian/plugins/voicefi")
                print("   🚀 Enabled in community-plugins.json")
                installed_count += 1
            except Exception as e:
                print(f"   ❌ Error installing to {vault_p}: {e}")

        if installed_count > 0:
            print(f"\n🎉 Successfully installed VoiceFi into {installed_count} vault(s)!")
            print("💡 Next Step: Open Obsidian and press Cmd+R (or restart Obsidian) to activate.")
            print(
                "🎙️ Look for the Microphone icon in your left sidebar and the status bar at the bottom!\n"
            )

    elif action == "status":
        from voicefi.integrations.obsidian import (
            is_obsidian_installed,
            find_obsidian_vaults,
            get_primary_vault,
            get_daily_note_path,
            is_plugin_installed,
        )
        print("\n💎 Obsidian Integration Status:")
        print(f"   App Installed:   {'✅ Yes' if is_obsidian_installed() else '❌ No'}")
        pv = get_primary_vault()
        if pv:
            print(f"   Primary Vault:   {pv.name} ({pv})")
            dn = get_daily_note_path(pv)
            print(f"   Today's Note:    {dn.name} ({'✅ Exists' if dn.is_file() else '⚪ Not created yet'})")
            print(f"   VoiceFi Plugin:  {'✅ Installed' if is_plugin_installed(pv) else '⚪ Not installed (run vifi obsidian install)'}")
        else:
            print("   Primary Vault:   None found")
        vaults = find_obsidian_vaults()
        print(f"   Total Vaults:    {len(vaults)}\n")
        return

    elif action == "today":
        from voicefi.integrations.obsidian import get_today_note_content
        res = get_today_note_content()
        if res.get("status") == "ok":
            print(f"\n💎 Obsidian Daily Note ({res['file_name']}) in '{res['vault_name']}':")
            print("─" * 60)
            print(res.get("content", ""))
            print("─" * 60 + "\n")
        else:
            print(f"❌ Error reading daily note: {res.get('error')}\n")
        return

    elif action == "capture":
        return cmd_capture(args)

    elif action == "launch":
        engine = getattr(args, "engine", "antigravity") or "antigravity"
        from voicefi.integrations.obsidian import launch_agent_in_vault
        res = launch_agent_in_vault(engine=engine)
        if res.get("status") == "ok":
            print(f"\n🚀 {res.get('message')}\n")
        else:
            print(f"\n❌ Error launching agent: {res.get('error')}\n")
        return


def cmd_capture(args):
    """Direct quick voice capture into Obsidian daily note (100% offline, 0-latency, 0-tokens)."""
    from voicefi.integrations.obsidian import append_quick_capture_to_vault, get_primary_vault
    from pathlib import Path

    raw_text = getattr(args, "text", None)
    if isinstance(raw_text, list):
        text = " ".join(raw_text).strip()
    elif isinstance(raw_text, str):
        text = raw_text.strip()
    else:
        text = ""

    vault_str = getattr(args, "vault", None)
    vp = Path(vault_str) if vault_str else None

    if not text:
        print("\n🎙️  VoiceFi Quick Capture")
        print("   Listening from microphone... Speak your note, pause when finished.")
        try:
            from voicefi.audio.recorder import AudioRecorder
            from voicefi.stt import get_stt_engine
            cfg = load_config()
            recorder = AudioRecorder(cfg)
            print("🔴 Recording... (speak now)")
            audio_data = recorder.record_speech_auto(timeout=15.0)
            if audio_data is not None and len(audio_data) > 0:
                print("⚡ Transcribing locally with Whisper...")
                stt = get_stt_engine(cfg)
                text = stt.transcribe(audio_data).strip()
        except Exception as e:
            print(f"❌ Recording error: {e}")
            return

    if not text:
        print("⚠️  No speech or text captured.\n")
        return

    res = append_quick_capture_to_vault(text, vault_path=vp)
    if res.get("status") == "ok":
        print(f"\n✅ Appended to Obsidian ({res['vault_name']}/{res['daily_note_name']}) at {res['time']}:")
        print(f"   {res['entry']}\n")
    else:
        print(f"\n❌ Error appending to vault: {res.get('error')}\n")



def cmd_tier(args):
    """Display active tier, 14-day free trial countdown, and pricing details."""
    config = load_config(getattr(args, "config", None))
    FeatureGate.ensure_trial_started(config)
    FeatureGate.sync_cloud_license(config)
    summary = FeatureGate.get_tier_summary(config)

    print("\n================ VoiceFi Tier & Licensing ================")
    print(f"Status:        {summary['status_text']}")

    if summary["is_licensed"]:
        lic_info = summary.get("license_info", {})
        tag = f" ({lic_info['tag']})" if lic_info.get("tag") else ""
        expires = lic_info.get("expires_at", "Perpetual")
        masked_key = (
            (config.license_key[:12] + "..." + config.license_key[-6:])
            if len(config.license_key) >= 20
            else (config.license_key[:4] + "****")
        )
        print(f"Tier:          {summary['tier']}{tag}")
        print(f"Validity:      {expires}")
        print(f"License Key:   {masked_key}")
        print("Capabilities:  All Pro Features Unlocked")
    elif summary["is_trial"]:
        print(f"Tier:          {summary['tier']}")
        days = summary["trial_days_remaining"]
        hours = summary["trial_hours_remaining"]
        print(f"Free Trial:    🟢 ACTIVE — {days} days remaining ({hours}h total)")
        print(f"Expires At:    {summary['trial_expires_at']}")
        print("Features:      ✓ 20+ Curated Neural & Local Voices")
        print("               ✓ Ultra-Fast Cloud & Groq STT/TTS Relay")
        print("               ✓ Streaming Realtime STT")
        print("               ✓ Mobile & Web Pacing Companion")
        print("               ✓ Multi-Agent Audio Turn Routing")
        print("----------------------------------------------------------")
        print("Upgrade to Pro:")
        print("  • Monthly:         $9 / month (lowest in market, cancel anytime)")
        print(
            "  • Annual Special:  $69 / year (1-Time payment for 1 full year · Save 36% · ~$5.75/mo)"
        )
        print("  • Upgrade URL:     https://voicefi.org#pricing")
        print("  • Activate Key:    vifi license activate <LICENSE_KEY>")
    elif summary["trial_expired"]:
        print(f"Tier:          {summary['tier']}")
        print("Free Trial:    🔴 EXPIRED — Running in Community Mode ($0)")
        print("Features:      ✓ 100% Local Apple Silicon TTS (0ms)")
        print("               ✓ Local Whisper STT & Faster-Whisper")
        print("               ✓ Native Stdio MCP Server & CLI")
        print("----------------------------------------------------------")
        print("Unlock Pro Features ($9/mo or $69/year 1-Time Special):")
        print("  • Upgrade URL:     https://voicefi.org#pricing")
        print("  • Activate Key:    vifi license activate <LICENSE_KEY>")
    else:
        print(f"Tier:          {summary['tier']}")
        print("Community:     $0 / Open-Source Tier")
        print("Upgrade URL:   https://voicefi.org#pricing")

    print("==========================================================\n")


def cmd_license(args):
    """Manage VoiceFi license keys and Pro tier activation."""
    action = getattr(args, "license_action", "status")
    key = getattr(args, "key", None)

    if action in ("help", "where", "find", "recover", "lost"):
        print("\n==========================================================")
        print("🔑 Finding or Recovering Your VoiceFi License Key")
        print("==========================================================")
        print("1. Polar Receipt Email:")
        print("   If you purchased Pro, your cryptographic key was emailed from")
        print("   Polar (notifications@polar.sh) and VoiceFi (talktome@voicefi.org)")
        print("   with the subject 'Your VoiceFi Pro License'.")
        print("\n2. Format of Genuine License Keys:")
        print("   Keys begin with 'VF1-PRO-' followed by expiration and signature:")
        print("   e.g. VF1-PRO-<EXPIRATION>-<ID>.<ED25519_SIGNATURE>")
        print("\n3. 14-Day Free Pro Trial (No Key Required):")
        print("   Testing VoiceFi? You do NOT need a license key or credit card!")
        print("   Run: vifi tier (or start from the AppKit Welcome Window)")
        print("\n4. Lost Key Recovery:")
        print("   Visit your Polar Customer Portal with your checkout email:")
        print("   👉 https://polar.sh/purchases")
        print("   Or contact: support@voicefi.org")
        print("\n5. Activate on This Machine:")
        print("   vifi license activate <YOUR_LICENSE_KEY>")
        print("==========================================================\n")
        return

    if action in ("activate", "set", "apply") or key:
        raw_key = (key or (args.key_args[0] if getattr(args, "key_args", None) else "")).strip()
        if not raw_key:
            print(
                "❌ Error: Please provide a valid license key (e.g. vifi license activate VF1-PRO-<KEY>)"
            )
            return

        config = load_config(getattr(args, "config", None))
        result = FeatureGate.activate_license(raw_key, config=config)
        if not result.get("success"):
            if result.get("is_expired"):
                print(f"\n❌ Error: This license key expired on {result.get('expires_at')}.")
            else:
                print(f"\n❌ Error: {result.get('error', 'Invalid license key signature.')}")
                print("   Please check your license key or visit https://voicefi.org#pricing\n")
            return

        expires_desc = result.get("expires_at", "Perpetual")
        tag_desc = f" ({result['tag']})" if result.get("tag") else ""
        masked_key = (
            (raw_key[:12] + "..." + raw_key[-6:])
            if len(raw_key) >= 20
            else (raw_key[:4] + "****")
        )

        print("\n🎉 VoiceFi Pro License Successfully Activated!")
        print(f"🔑 License Key: {masked_key}")
        print(f"⚡ Tier:        {result.get('tier', 'pro').capitalize()}{tag_desc} · {expires_desc}")
        print("🚀 All Pro features (Streaming STT, 20+ Neural Voices, Cloud Relay) are unlocked!")
        return
    if action in ("generate", "create", "mint", "new"):
        from voicefi.license import generate_license_key
        tier = getattr(args, "tier", "PRO") or "PRO"
        expires = getattr(args, "expires", "PERP") or "PERP"
        tag = getattr(args, "tag", "TESTER") or "TESTER"
        try:
            new_key = generate_license_key(tier=tier, expires=expires, tag=tag)
            print("\n✨ VoiceFi License Key Generated Successfully:")
            print(f"🔑 Key:    {new_key}")
            print(f"⚡ Tier:   {tier.upper()}")
            print(f"⏱️ Exp:    {expires.upper()}")
            print(f"🏷️ Tag:    {tag.upper()}")
            print(f"\n👉 To activate on any machine:")
            print(f"   vifi license activate {new_key}\n")
            return
        except Exception as e:
            print(f"\n❌ Error generating license key: {e}\n")
            return

    # Default to showing status
    cmd_tier(args)


def cmd_learn(args):
    """Inspect and manage recursive phonetic and brevity self-learning memory."""
    from voicefi.learning.phonetic import PhoneticLearner
    from voicefi.learning.brevity import BrevityLearner
    from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine
    from voicefi.config import load_config
    from pathlib import Path
    import time

    phonetic = PhoneticLearner.get_instance()
    brevity = BrevityLearner.get_instance()
    cfg = load_config(getattr(args, "config", None))
    gem = GeminiIntelligenceEngine(cfg)
    subaction = getattr(args, "learn_action", None) or "status"

    if subaction == "teach":
        spoken = getattr(args, "spoken", "")
        canonical = getattr(args, "canonical", "")
        if not spoken or not canonical:
            print('❌ Usage: vifi learn teach "<spoken phrase>" "<canonical command/code>"')
            return
        phonetic.record_correction(spoken, canonical)
        print("\n✅ Learned phonetic mapping:")
        print(f"   Spoken:    '{spoken}'")
        print(f"   Canonical: '{canonical}'")
        print("   Saved to:  ~/.voicefi/phonetic_memory.json\n")
        return

    elif subaction == "scan":
        target_dir = Path(getattr(args, "path", None) or Path.cwd())
        print(f"\n🔍 Scanning workspace for code symbols: {target_dir}...")
        found = phonetic.scan_workspace(target_dir)
        print(f"✅ Indexed {found} project symbols into phonetic self-learning memory.\n")
        return

    elif subaction == "test":
        raw_text = getattr(args, "text", "")
        if not raw_text:
            print('❌ Usage: vifi learn test "<agent output or markdown text>"')
            return
        target_words = brevity.get_optimal_max_words()
        print(f"\n🧪 Distilling Spoken Soundbite (Target: <{target_words} words)...")
        t0 = time.time()
        distilled = gem.distill_spoken_soundbite(
            raw_text, max_words=target_words, fallback_to_heuristics=True
        )
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        provider = gem.get_active_provider()
        
        print("\n================= Distillation Benchmark =================")
        print(f"Provider:        {provider.upper()} ({gem.model if provider == 'gemini' else gem.local_llm_model})")
        print(f"Latency:         {elapsed_ms}ms")
        print(f"Raw Words:       {len(raw_text.split())} words")
        print(f"Distilled Words: {len(distilled.split()) if distilled else 0} words")
        print("---------------------------------------------------------")
        print(f"Output: \"{distilled or 'No distillation produced'}\"")
        print("=========================================================\n")
        return

    elif subaction == "reset":
        phonetic.reset()
        brevity.reset()
        print("\n🗑️  Reset all recursive phonetic and cognitive brevity memory files.\n")
        return

    # Default status view
    p_status = phonetic.get_status()
    b_status = brevity.get_status()
    active_provider = gem.get_active_provider()
    active_stt = getattr(cfg.stt, "provider", "whisper_local")

    print("\n============== VoiceFi Recursive Self-Learning ==============")
    print(
        f"Intelligence Engine: {active_provider.upper()} ({'Gemini Free Tier' if active_provider == 'gemini' else 'Local Ollama' if active_provider == 'ollama' else 'Regex Heuristics (0ms)'})"
    )
    print(
        f"Speech Recognition:  {active_stt.upper()} ({getattr(cfg.stt, 'model_size', 'base.en') if active_stt == 'whisper_local' else 'Cloud'})"
    )
    print(
        f"Phonetic Memory:     {p_status['total_learned_corrections']} learned rules, {p_status['total_project_symbols']} project symbols"
    )
    print(
        f"Spoken Brevity:      {b_status['learned_max_words']} words/turn limit (Interruption rate: {b_status['interruption_rate_pct']}%)"
    )
    print(
        f"Turn Telemetry:      {b_status['total_turns']} total turns ({b_status['total_interruptions']} barge-in interruptions)"
    )
    print("-------------------------------------------------------------")
    if p_status.get("top_corrections"):
        print("Top Learned Phonetic Mappings:")
        for c in p_status["top_corrections"][:5]:
            print(f"  • '{c['spoken']}' -> '{c['canonical']}' ({c['count']} uses)")
    else:
        print("Top Learned Phonetic Mappings: (Built-ins active: pytest, vifi, kubectl, .tsx, .py)")
    print("-------------------------------------------------------------")
    print("Commands:")
    print("  • Scan repository:   vifi learn scan [path]")
    print('  • Test distillation: vifi learn test "<agent text>"')
    print('  • Teach mapping:     vifi learn teach "<spoken>" "<canonical>"')
    print("  • Reset memory:      vifi learn reset")
    print("=============================================================\n")


def cmd_info(args):
    """Display active configuration and system capabilities."""
    from voicefi.server import get_full_server_status

    config = load_config(args.config)
    FeatureGate.ensure_trial_started(config)
    tier_info = FeatureGate.get_tier_summary(config)
    st = get_full_server_status()
    la = st["launchagent"]
    port = st.get("port_5141") or st.get("port_8765") or st.get("port_listener")

    print(f"\n================ VoiceFi v{__version__} ================")
    print("  'Give voice to your agents, and agency for your voice.'")
    print(f"Tier:          {tier_info['status_text']}")
    print(f"TTS Provider:  {config.tts.provider} (Default Voice: {config.tts.voice})")
    print(f"STT Provider:  {config.stt.provider} (Model: {config.stt.model_size})")
    print(f"VAD Silence:   {config.vad.silence_duration}s")
    print(f"Auto-Listen:   {config.antigravity.auto_listen}")
    print(f"Read Aloud:    {config.antigravity.read_summary_aloud}")
    if config.agents:
        print(f"Agents:        {', '.join(config.agents.keys())}")
    if config.subagents:
        print(f"Subagents:     {', '.join(config.subagents.keys())}")
    print("----------------------------------------------------")
    print(
        f"LaunchAgent:   {'🟢 Active' if la['is_loaded'] else '⚪ Inactive'}"
        + (f" (PID {la['pid']})" if la["pid"] else "")
    )
    print(
        "Port 5141:     "
        + (f"🟢 PID {port['pid']} ({port['command_name']})" if port else "⚪ Free")
    )
    print(f"Python Exec:   {st['python_executable']}")
    print(f"Antigravity:   {st['hooks'].get('antigravity') or '❌ Not installed'}")
    print(f"Claude Code:   {st['hooks'].get('claude') or '❌ Not installed'}")
    print("====================================================\n")

    print("Curated Personas: Viv, Christopher, Aria, Sonia, Guy, William, Samantha, Alex")
    print(
        "Run 'vifi ping --all' to test connection & speeds, or 'vifi dev' for live development.\n"
    )


def cmd_stats(args):
    """View local developer activity, tool usage, time saved, and acoustic latency benchmarks."""
    from voicefi.analytics import (
        print_stats_dashboard,
        export_events_json,
        export_events_csv,
        clean_analytics_data,
        reset_analytics_data,
    )

    if getattr(args, "reset", False):
        if getattr(args, "force", False) or input(
            "⚠️ Are you sure you want to wipe all local analytics data? [y/N] "
        ).strip().lower() in ("y", "yes"):
            reset_analytics_data()
            print("✅ Successfully wiped local analytics database (~/.voicefi/analytics.db).")
            return
        else:
            print("Operation cancelled.")
            return

    clean_days = getattr(args, "clean", None)
    if clean_days is not None:
        try:
            days_val = max(0, int(clean_days))
        except (ValueError, TypeError):
            days_val = 30
        pruned = clean_analytics_data(retention_days=days_val)
        if days_val == 0:
            print(
                f"✅ Cleaned local analytics: {pruned} records purged (all-time retention reset)."
            )
        else:
            print(
                f"✅ Cleaned local analytics: {pruned} records older than {days_val} days purged."
            )
        return

    days = 7
    if getattr(args, "today", False):
        days = 1
    elif getattr(args, "all", False):
        days = 0
    elif getattr(args, "days", None) is not None:
        try:
            days = int(args.days)
        except (ValueError, TypeError):
            days = 7

    export_fmt = getattr(args, "export", None)
    try:
        if export_fmt:
            if str(export_fmt).lower() == "csv":
                print(export_events_csv(days=days))
            else:
                print(export_events_json(days=days))
            return

        print_stats_dashboard(days=days)
    except BrokenPipeError:
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, sys.stdout.fileno())
            except Exception:
                pass
        return


def cmd_hud(args):
    """Control, configure, and debug Unified Dynamic Island HUD on macOS."""
    action = getattr(args, "hud_action", "test")
    import time
    from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
    from voicefi.config import load_config, save_config, HUDConfig
    from AppKit import NSRunLoop, NSDate

    cfg = load_config()
    hud = UnifiedDynamicIslandHUD.get_instance()

    def _pump(duration: float):
        start = time.time()
        while time.time() - start < duration:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.04))

    if action in ("on", "enable", "open", "start", "launch"):
        if not hasattr(cfg, "hud") or cfg.hud is None:
            cfg.hud = HUDConfig()
        cfg.hud.enabled = True
        cfg.hud.persistent = True
        save_config(cfg)

        # Check if background LaunchAgent server is running
        import subprocess
        import shutil
        import os

        res = subprocess.run(
            ["launchctl", "list", "com.voicefi.menubar"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        is_running = res.returncode == 0

        if not is_running:
            print("🚀 Launching VoiceFi background companion server (autostart)...")
            cmd_autostart(args)

        hud.set_persistent(True)
        hud.set_idle()
        _pump(0.5)
        pos = getattr(cfg.hud, "position", "bottom_right") if hasattr(cfg, "hud") and cfg.hud else "bottom_right"
        pos_desc = "the lower-right above the lower bar/dock" if pos == "bottom_right" else f"the {pos.replace('_', '-')}"
        print(f"📌 Resting pill is anchored at {pos_desc}.")
        print(
            "💡 Use 'vifi hud status' to inspect, 'vifi hud debug' to test all states, or 'vifi hud off' / 'vifi hud close' to disable.\n"
        )
    elif action in ("off", "disable", "close", "stop", "hide"):
        if not hasattr(cfg, "hud") or cfg.hud is None:
            cfg.hud = HUDConfig()
        cfg.hud.enabled = False
        save_config(cfg)
        hud.force_hide()
        _pump(0.3)
        print("⚪ VoiceFi Dynamic Island HUD disabled and hidden.")
        print(
            "💡 Use 'vifi hud open' or 'vifi hud on' to re-enable persistent Dynamic Island HUD.\n"
        )
    elif action in ("reset", "reset-position"):
        hud.reset_position()
        hud.set_idle()
        _pump(0.5)
        print(
            "🎯 VoiceFi Dynamic Island HUD position reset to default bottom-right anchor above lower bar.\n"
        )
    elif action == "status":
        hud_cfg = getattr(cfg, "hud", None) or HUDConfig()
        print("\n📊 VoiceFi Dynamic Island HUD Status:")
        print(f"  • HUD Layer:          {'🟢 Active' if hud_cfg.enabled else '⚪ Disabled'}")
        print(f"  • Current State:      {hud._current_state.upper()}")
        print(
            f"  • Persistent:         {'Always Visible (Resting Pill)' if hud.persistent else 'Auto-Hide'}"
        )
        print(
            f"  • Full-Screen Overlay:{'🎮 Always on Top of Full Screen Apps' if getattr(hud_cfg, 'fullscreen_overlay', True) else '⚪ Allow Full-Screen Overlap / Hide Behind'}"
        )
        print(
            f"  • Prompt Mode:        {'⚡ Instant Auto-Send' if hud.auto_send else '✏️ Interactive Review & Edit'}"
        )
        print(
            f"  • Live Typing:        {'🟢 Enabled' if hud_cfg.show_live_transcript else '⚪ Disabled'}"
        )
        print(f"  • Position:           📍 {hud_cfg.position}")
        print(f"  • Linger Time:        ⏱️ {hud_cfg.linger_seconds}s\n")
    elif action == "fullscreen":
        hud_cfg = getattr(cfg, "hud", None) or HUDConfig()
        target = getattr(args, "fullscreen_state", "toggle")
        if target == "on":
            hud_cfg.fullscreen_overlay = True
        elif target == "off":
            hud_cfg.fullscreen_overlay = False
        elif target == "status":
            pass
        else:  # toggle
            hud_cfg.fullscreen_overlay = not getattr(hud_cfg, "fullscreen_overlay", True)

        if target != "status":
            cfg.hud = hud_cfg
            save_config(cfg)
            hud.set_fullscreen_overlay(hud_cfg.fullscreen_overlay)
            print(
                f"🎮 Full-Screen Overlay: {'ON (Always on Top of Full-Screen Games & Apps)' if hud_cfg.fullscreen_overlay else 'OFF (Allow Full Screen to Overlap / Hide Behind)'}"
            )
        else:
            print(
                f"🎮 Full-Screen Overlay Status: {'ON (Always on Top)' if getattr(hud_cfg, 'fullscreen_overlay', True) else 'OFF (Allow Full Screen Overlap)'}"
            )
    elif action == "config":
        hud_cfg = getattr(cfg, "hud", None) or HUDConfig()
        modified = False
        if getattr(args, "persistent", None) is not None:
            hud_cfg.persistent = args.persistent.lower() in ("true", "1", "yes", "on")
            cfg.antigravity.persistent_hud = hud_cfg.persistent
            hud.set_persistent(hud_cfg.persistent)
            modified = True
        if getattr(args, "fullscreen_overlay", None) is not None:
            hud_cfg.fullscreen_overlay = args.fullscreen_overlay.lower() in (
                "true",
                "1",
                "yes",
                "on",
            )
            hud.set_fullscreen_overlay(hud_cfg.fullscreen_overlay)
            modified = True
        if getattr(args, "auto_send", None) is not None:
            hud_cfg.auto_send = args.auto_send.lower() in ("true", "1", "yes", "on")
            cfg.antigravity.auto_send = hud_cfg.auto_send
            hud.set_auto_send(hud_cfg.auto_send)
            modified = True
        if getattr(args, "live_transcript", None) is not None:
            hud_cfg.show_live_transcript = args.live_transcript.lower() in (
                "true",
                "1",
                "yes",
                "on",
            )
            modified = True
        if getattr(args, "position", None) is not None:
            hud_cfg.position = args.position
            modified = True
        if getattr(args, "linger", None) is not None:
            hud_cfg.linger_seconds = float(args.linger)
            modified = True
        if getattr(args, "enabled", None) is not None:
            hud_cfg.enabled = args.enabled.lower() in ("true", "1", "yes", "on")
            modified = True

        if modified:
            cfg.hud = hud_cfg
            save_config(cfg)
            print("✅ VoiceFi HUD configuration updated successfully!\n")

        print("🎛️  VoiceFi HUD Configuration:")
        print(f"  • Enabled:                {'✅ True' if hud_cfg.enabled else '❌ False'}")
        print(
            f"  • Persistent Pill:        {'✅ True (Always Visible)' if hud_cfg.persistent else '❌ False (Auto-Hide)'}"
        )
        print(
            f"  • Full-Screen Overlay:    {'🎮 True (Always on Top of Games/Apps)' if getattr(hud_cfg, 'fullscreen_overlay', True) else '❌ False (Allow Full Screen Overlap)'}"
        )
        print(
            f"  • Auto-Send Prompts:      {'⚡ True (Instant Send)' if hud_cfg.auto_send else '✏️ False (Review & Edit Mode)'}"
        )
        print(
            f"  • Live Transcript Typing: {'✅ True' if hud_cfg.show_live_transcript else '❌ False'}"
        )
        print(f"  • Position:               📍 {hud_cfg.position}")
        print(f"  • Linger Time:            ⏱️ {hud_cfg.linger_seconds}s\n")
    elif action == "debug":
        import sys
        import select
        import tty
        import termios

        active_state = 1
        auto_cycle = False
        last_cycle_time = time.time()

        def _render_menu():
            print("\033[H\033[J", end="")  # Clear terminal
            print("🎛️  VoiceFi Dynamic Island HUD • Interactive Debug Studio")
            print("────────────────────────────────────────────────────────────")
            states_info = [
                (1, "Idle (Persistent Resting Pill)"),
                (2, "Thinking (Antigravity Reasoning)"),
                (3, "Working (Running pytest suite)"),
                (4, "Speaking (Viv Subtitles)"),
                (5, "Listening (Live Mic + Real-Time Typing)"),
                (6, "Editing (Interactive Review Capsule)"),
                (7, "New Session (Connected Tools)"),
            ]
            for idx, name in states_info:
                active_tag = "  \033[1;32m[ACTIVE 🟢]\033[0m" if idx == active_state else ""
                print(f"  [{idx}] State: {name:<42}{active_tag}")

            print("────────────────────────────────────────────────────────────")
            demo_tag = "\033[1;36m[RUNNING ▶️]\033[0m" if auto_cycle else "\033[90m[OFF]\033[0m"
            print(f"  [SPACE] Auto-Cycle Demo Mode              {demo_tag}")
            print("  [T]     Simulate Real-Time Speech Typing Stream")
            print(
                f"  [P]     Toggle Persistent Mode            (Current: {'ON' if hud.persistent else 'OFF'})"
            )
            print(
                f"  [A]     Toggle Auto-Send Mode             (Current: {'ON' if hud.auto_send else 'OFF'})"
            )
            print(
                f"  [F]     Toggle Fullscreen Overlay (Games) (Current: {'ON' if getattr(hud, 'fullscreen_overlay', True) else 'OFF'})"
            )
            print("  [R]     Reset Position to Bottom-Right (Above Dock)")
            print("  [C]     Clear / Force Hide HUD")
            print("  [Q]     Exit Debug Studio")
            print("────────────────────────────────────────────────────────────")
            print("👉 Press any key [1-7, SPACE, T, P, A, F, R, C, Q] to trigger live state:\n")

        def _apply_debug_state(state_idx: int):
            nonlocal active_state
            active_state = state_idx
            if state_idx == 1:
                hud.set_idle(linger=None)
            elif state_idx == 2:
                hud.set_thinking("Antigravity", "Reasoning over AST & planning architecture...")
            elif state_idx == 3:
                hud.set_working("Antigravity", "Executing pytest tests/ (208 passed)")
            elif state_idx == 4:
                hud.set_speaking(
                    "VoiceFi Dynamic Island HUD is running natively on macOS.",
                    persona_name="Viv",
                    linger=None,
                )
            elif state_idx == 5:
                hud.set_listening(
                    prompt_preview="Add live typing to HUD",
                    user_name=getattr(hud.config, "user_name", "Jake"),
                    live_stream=True,
                )
            elif state_idx == 6:
                hud.set_editing(
                    "Add live typing to the listening phase of HUD",
                    on_submit=lambda val: print(f"\n[Debug] ✅ Submitted prompt: '{val}'\n"),
                    on_cancel=lambda: print("\n[Debug] ✕ Cancelled edit\n"),
                    target_name="Antigravity",
                )
            elif state_idx == 7:
                hud.set_new_conversation(
                    prompt_preview="Build dynamic island HUD for Claude",
                    user_name=getattr(hud.config, "user_name", "Jake"),
                    live_stream=True,
                )
            _render_menu()

        def _simulate_live_typing():
            phrases = [
                "Add",
                "Add live typing",
                "Add live typing to the",
                "Add live typing to the listening phase of HUD",
            ]
            hud.set_listening(user_name=getattr(hud.config, "user_name", "Jake"), live_stream=True)
            for phrase in phrases:
                hud.update_live_transcription(
                    phrase, user_name=getattr(hud.config, "user_name", "Jake")
                )
                _pump(0.35)
            _pump(0.5)
            if hud.auto_send:
                hud.show_done(preview_text="Prompt Sent")
                _pump(1.2)
                if hud.persistent:
                    hud.set_idle(linger=None)
                else:
                    hud.force_hide()
            else:
                hud.set_editing(
                    "Add live typing to the listening phase of HUD",
                    on_submit=lambda val: print(f"\n[Debug] ✅ Submitted prompt: '{val}'\n"),
                    on_cancel=lambda: print("\n[Debug] ✕ Cancelled edit\n"),
                    target_name="Antigravity",
                )
            _render_menu()

        is_tty = sys.stdin.isatty()
        old_settings = None
        if is_tty:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            tty.setcbreak(fd)

        try:
            _apply_debug_state(1)
            running = True
            while running:
                NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.04))
                if auto_cycle and time.time() - last_cycle_time > 2.2:
                    next_s = (active_state % 7) + 1
                    _apply_debug_state(next_s)
                    last_cycle_time = time.time()

                if is_tty:
                    rlist, _, _ = select.select([sys.stdin], [], [], 0)
                    if rlist:
                        ch = sys.stdin.read(1)
                        if ch in ("q", "Q", "\x03"):
                            running = False
                        elif ch == " ":
                            auto_cycle = not auto_cycle
                            last_cycle_time = time.time()
                            _render_menu()
                        elif ch in ("1", "2", "3", "4", "5", "6", "7"):
                            auto_cycle = False
                            _apply_debug_state(int(ch))
                        elif ch in ("t", "T"):
                            auto_cycle = False
                            _simulate_live_typing()
                        elif ch in ("p", "P"):
                            new_p = not hud.persistent
                            hud.set_persistent(new_p)
                            if not hasattr(cfg, "hud") or cfg.hud is None:
                                cfg.hud = HUDConfig()
                            cfg.hud.persistent = new_p
                            save_config(cfg)
                            if new_p:
                                _apply_debug_state(1)
                            else:
                                hud.force_hide()
                                _render_menu()
                        elif ch in ("a", "A"):
                            new_a = not hud.auto_send
                            hud.set_auto_send(new_a)
                            if not hasattr(cfg, "hud") or cfg.hud is None:
                                cfg.hud = HUDConfig()
                            cfg.hud.auto_send = new_a
                            save_config(cfg)
                            _render_menu()
                        elif ch in ("f", "F"):
                            new_f = not getattr(hud, "fullscreen_overlay", True)
                            hud.set_fullscreen_overlay(new_f)
                            if not hasattr(cfg, "hud") or cfg.hud is None:
                                cfg.hud = HUDConfig()
                            cfg.hud.fullscreen_overlay = new_f
                            save_config(cfg)
                            _render_menu()
                        elif ch in ("r", "R"):
                            hud.reset_position()
                            _apply_debug_state(active_state)
                        elif ch in ("c", "C"):
                            auto_cycle = False
                            hud.force_hide()
                            active_state = 0
                            _render_menu()
                else:
                    running = False
        finally:
            if is_tty and old_settings:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            hud.force_hide()
            print("\n👋 Exited HUD Debug Studio.\n")
    elif action == "test":
        print("\n🍏 Running Unified Dynamic Island HUD Showcase (Pure Native macOS)...")
        print("  1/6 💤 State: Idle (Compact Persistent Pill)")
        hud.set_idle()
        _pump(1.8)

        print("  2/6 State: Thinking (Antigravity)")
        hud.set_thinking("Antigravity", "Reasoning over architecture & dependencies...")
        _pump(2.0)

        print("  3/6 State: Working (Tool Action)")
        hud.set_working("Antigravity", "Executing pytest tests/ -v (164 passed)")
        _pump(2.0)

        print("  4/6 State: Speaking (Live Subtitles)")
        hud.set_speaking(
            "Hey Jake! All 164 test suites passed cleanly with zero regressions.",
            persona_name="Viv",
        )
        _pump(2.8)

        print("  5/6 State: Listening (Real-Time Live Typing Stream)")
        hud.set_listening(user_name=getattr(hud.config, "user_name", "Jake"))
        _pump(1.0)
        phrases = [
            "Add",
            "Add live typing",
            "Add live typing to the listening",
            "Add live typing to the listening phase of HUD",
        ]
        for phrase in phrases:
            hud.update_live_transcription(
                phrase, user_name=getattr(hud.config, "user_name", "Jake")
            )
            _pump(0.6)
        _pump(1.2)

        print("  6/6 State: Review & Edit (Interactive Capsule)")

        def _dummy_submit(val):
            print(f"[CLI] Submitted prompt from HUD: '{val}'")

        def _dummy_cancel():
            print("[CLI] Cancelled edit in HUD")

        hud.set_editing(
            "Add live typing to the listening phase of HUD",
            on_submit=_dummy_submit,
            on_cancel=_dummy_cancel,
            target_name="Antigravity",
        )
        _pump(3.2)

        hud.show_done(preview_text="Prompt Confirmed")
        _pump(1.5)
        hud.force_hide()
        print("Unified Dynamic Island HUD showcase completed successfully!\n")
    elif action == "persistent":
        sub = getattr(args, "persistent_state", "toggle")
        current = getattr(getattr(cfg, "hud", None), "persistent", True)
        if sub == "on":
            new_val = True
        elif sub == "off":
            new_val = False
        else:
            new_val = not current
        if not hasattr(cfg, "hud") or cfg.hud is None:
            cfg.hud = HUDConfig()
        cfg.hud.persistent = new_val
        cfg.antigravity.persistent_hud = new_val
        save_config(cfg)
        hud.set_persistent(new_val)
        print(
            f"HUD Persistent Mode: {'ENABLED (Always Visible)' if new_val else 'DISABLED (Auto-Hide)'}"
        )
    elif action == "auto-send":
        sub = getattr(args, "auto_send_state", "toggle")
        current = getattr(getattr(cfg, "hud", None), "auto_send", True)
        if sub == "on":
            new_val = True
        elif sub == "off":
            new_val = False
        else:
            new_val = not current
        if not hasattr(cfg, "hud") or cfg.hud is None:
            cfg.hud = HUDConfig()
        cfg.hud.auto_send = new_val
        cfg.antigravity.auto_send = new_val
        save_config(cfg)
        hud.set_auto_send(new_val)
        print(
            f"HUD Auto-Send Mode: {'ENABLED (Instant Send)' if new_val else 'DISABLED (Interactive Review Mode)'}"
        )
    elif action == "show":
        state = getattr(args, "state", "idle")
        custom_text = getattr(args, "text", "")
        if state == "idle":
            hud.set_idle()
        elif state == "thinking":
            hud.set_thinking(agent_name="Antigravity", detail=custom_text or "Reasoning...")
        elif state == "working":
            hud.set_working(agent_name="Antigravity", tool_action=custom_text or "Running tools...")
        elif state == "speaking":
            hud.set_speaking(custom_text or "Speech subtitle active.", persona_name="Viv")
        elif state == "listening":
            hud.set_listening(
                prompt_preview=custom_text,
                user_name=getattr(hud.config, "user_name", "Jake"),
                live_stream=bool(custom_text),
            )
        elif state == "editing":
            hud.set_editing(
                custom_text or "Sample prompt to review and edit",
                on_submit=lambda x: print(f"Submitted: {x}"),
                target_name="Antigravity",
            )
        _pump(float(getattr(args, "duration", 4.0)))
        hud.force_hide()


def extract_cli_metadata(args: argparse.Namespace) -> dict:
    """
    Extract sanitized, zero-PII metadata from CLI arguments.
    Strictly allowlisted: excludes all free-form user text, prompts, transcripts, audio, and paths.
    """
    cmd = getattr(args, "command", "unknown") or "unknown"
    props: dict = {"command": cmd, "$is_server": True}

    # 1. Subcommands / Actions (Strictly allowlisted strings)
    subcommand = None
    if hasattr(args, "server_action") and args.server_action:
        subcommand = str(args.server_action)
    elif hasattr(args, "daemon_action") and args.daemon_action:
        subcommand = str(args.daemon_action)
    elif hasattr(args, "voice_action") and args.voice_action:
        subcommand = str(args.voice_action)
    elif hasattr(args, "hud_action") and args.hud_action:
        subcommand = str(args.hud_action)
    elif hasattr(args, "clone_action") and args.clone_action:
        subcommand = str(args.clone_action)
    elif hasattr(args, "memo_action") and args.memo_action:
        subcommand = str(args.memo_action)
    elif hasattr(args, "ambient_action") and args.ambient_action:
        subcommand = str(args.ambient_action)
    elif hasattr(args, "feedback_action") and args.feedback_action:
        subcommand = str(args.feedback_action)
    elif hasattr(args, "obsidian_action") and args.obsidian_action:
        subcommand = str(args.obsidian_action)
    elif hasattr(args, "hook_action") and args.hook_action:
        subcommand = str(args.hook_action)
    elif hasattr(args, "setup_action") and args.setup_action:
        subcommand = str(args.setup_action)
    elif cmd in (
        "download-ava",
        "ping",
        "feedback-loop",
        "hearing-test",
        "barge-in",
        "troubleshoot",
        "kill",
        "autostart",
        "stop-autostart",
        "pause",
        "resume",
        "permissions",
        "mcp",
        "onboarding",
        "panel",
        "companion",
        "info",
        "update",
        "status",
        "stop",
        "start",
        "restart",
        "server",
        "setup",
    ):
        subcommand = cmd

    if subcommand:
        props["subcommand"] = subcommand

    # 2. Agent / Persona metadata (Allowlisted clean identifiers only)
    agent = getattr(args, "agent", None)
    if agent and isinstance(agent, str):
        clean_agent = agent.lower().strip()
        if re.match(r"^[a-z0-9_-]{1,32}$", clean_agent):
            props["agent"] = clean_agent

    # 3. Voice & Provider metadata (Allowlisted clean identifiers only)
    voice = getattr(args, "voice", None)
    if voice and isinstance(voice, str):
        clean_voice = voice.strip()
        if "/" not in clean_voice and "\\" not in clean_voice:
            props["voice"] = clean_voice[:40]

    provider = getattr(args, "provider", None)
    if provider and isinstance(provider, str):
        clean_provider = provider.strip().lower()
        if re.match(r"^[a-z0-9_-]{1,30}$", clean_provider):
            props["provider"] = clean_provider

    # 4. Safe scrubbed args/flags (Allowlisted flags only — ZERO user data/paths)
    flags = []
    flag_map = [
        ("dev", "--dev"),
        ("all", "--all"),
        ("silent", "--silent"),
        ("quiet", "--quiet"),
        ("json", "--json"),
        ("interactive", "--interactive"),
        ("benchmark", "--benchmark"),
        ("mic_loopback", "--mic"),
        ("loopback", "--loopback"),
        ("hearing", "--hearing"),
        ("feedback_loop", "--feedback-loop"),
        ("verify", "--verify"),
        ("check", "--check"),
        ("no_wait", "--no-wait"),
        ("no_qr", "--no-qr"),
        ("no_browser", "--no-browser"),
        ("claude", "--claude"),
        ("antigravity", "--antigravity"),
        ("mcp", "--mcp"),
        ("servers", "--servers"),
        ("daemons", "--daemons"),
        ("clipboard", "--clipboard"),
        ("no_synth", "--no-synth"),
        ("global_install", "--global"),
    ]
    for flag_attr, flag_name in flag_map:
        val = getattr(args, flag_attr, None)
        if val is True:
            flags.append(flag_name)

    if getattr(args, "inject", None) is False:
        flags.append("--no-inject")
    if getattr(args, "enter", None) is False:
        flags.append("--no-enter")

    props["args"] = flags
    props["flags"] = flags

    # 5. Command-specific safe enums
    if cmd == "hud" and hasattr(args, "state") and args.state:
        props["hud_state"] = str(args.state)

    if cmd in ("troubleshoot", "voice") and getattr(args, "fix", None):
        clean_fix = str(args.fix).strip().lower()
        if re.match(r"^[a-z0-9_-]{1,40}$", clean_fix):
            props["fix_target"] = clean_fix

    return props


def cmd_bridge(args):
    """Run or manage the VoiceFi local IPC bridge service."""
    import asyncio
    from voicefi.ipc import VoiceFiIPCBridge, VoiceFiIPCServer

    config = load_config(getattr(args, "config", None))
    sock_path = getattr(args, "socket", None) or config.ipc.socket_path
    ws_port = getattr(args, "ws_port", None) or config.ipc.ws_port
    agent_name = getattr(args, "agent", None) or "Spark"
    persona = getattr(args, "persona", None) or getattr(config.spark, "persona", "Viv")

    if getattr(args, "server", False):
        print(f"🚀 Starting VoiceFi IPC Server at {sock_path} (WS: ws://127.0.0.1:{ws_port})...")
        server = VoiceFiIPCServer(
            socket_path=sock_path,
            ws_port=ws_port,
            config=config,
        )

        async def _run_srv():
            await server.start()
            while server.is_running:
                await asyncio.sleep(1)

        try:
            asyncio.run(_run_srv())
        except KeyboardInterrupt:
            print("\n🛑 Stopping IPC Server...")
            asyncio.run(server.stop())
        return

    print(f"🔗 Starting VoiceFi IPC Bridge for {agent_name} ({persona} persona) -> {sock_path}...")
    bridge = VoiceFiIPCBridge(
        socket_path=sock_path,
        ws_url=f"ws://127.0.0.1:{ws_port}/ws",
        agent_name=agent_name,
        persona=persona,
        config=config,
    )

    async def _run():
        await bridge.start()
        print("✅ IPC Bridge connected and listening for spoken prompts. Press Ctrl+C to exit.")
        while True:
            await asyncio.sleep(1)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n🛑 Disconnecting IPC Bridge...")
        asyncio.run(bridge.stop())


from voicefi.cli_commands.local import (
    cmd_spark as _cmd_spark,
    cmd_scout as _cmd_scout,
    cmd_benchmark as _cmd_benchmark,
    cmd_local as _cmd_local,
)


def cmd_spark(args):
    """Run Gemini Spark agent runner with voice IPC bridge and turn-end hooks."""
    return _cmd_spark(args)


def cmd_scout(args):
    """Run on-device Recon Scout to pre-digest logs, code, or directories."""
    return _cmd_scout(args)


def cmd_benchmark(args):
    """Run on-device model and latency benchmark suite."""
    return _cmd_benchmark(args)


def cmd_local(args):
    """Inspect and manage on-device LiteRT and Gemma models."""
    return _cmd_local(args)


from voicefi.cli_commands.live import cmd_live as _cmd_live


def cmd_live(args):
    """Run real-time Gemini 3.8 Live voice/comedy session."""
    return _cmd_live(args)



def build_parser(prog: Optional[str] = None) -> VoiceFiArgumentParser:
    prog_name = prog or resolve_prog_name()
    parser = VoiceFiArgumentParser(
        prog=prog_name,
        description="VoiceFi: Give voice to your agents, and agency for your voice. The Universal Voice Layer for AI Agents, MCP, and macOS.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to custom config.yaml")
    parser.add_argument(
        "-l",
        "--live",
        dest="root_live",
        action="store_true",
        help="Start Gemini 3.8 Live interactive full-duplex speech-to-speech studio",
    )

    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", help="Available subcommands"
    )

    # hook
    hook_p = subparsers.add_parser(
        "hook",
        aliases=["hooks"],
        help="Manage or run AI agent lifecycle hooks (Antigravity, Claude Code, Codex)",
    )
    hook_p.add_argument(
        "action",
        nargs="?",
        default=None,
        help="Hook management action (enable, disable, status, remove) or event name",
    )
    hook_p.add_argument(
        "extra_args", nargs="*", default=[], help="Additional hook event arguments or JSON payload"
    )
    hook_p.add_argument(
        "-a",
        "--agent",
        type=str,
        default="antigravity",
        help="Target agent name (antigravity, claude, codex)",
    )
    hook_p.add_argument(
        "-v",
        "--voice",
        type=str,
        default=None,
        help="Voice persona or provider voice to speak this hook with (e.g. Steffan, Ryan, Emma, Ava)",
    )
    hook_p.add_argument(
        "--enable", action="store_true", help="Enable agent lifecycle hooks in configuration"
    )
    hook_p.add_argument(
        "--disable", action="store_true", help="Disable agent lifecycle hooks in configuration"
    )
    hook_p.add_argument(
        "--status", action="store_true", help="Show hook installation and configuration status"
    )
    hook_p.add_argument(
        "--remove", action="store_true", help="Remove hook definitions from agent settings"
    )

    # speak
    speak_p = subparsers.add_parser("speak", help="Speak text aloud")
    speak_p.add_argument("text", nargs="+", help="Text to speak")
    speak_p.add_argument(
        "-a",
        "--agent",
        type=str,
        default=None,
        help="Agent profile to speak as (e.g. antigravity, claude, researcher, debugger)",
    )
    speak_p.add_argument("-v", "--voice", type=str, default=None, help="Voice name or ID override")
    speak_p.add_argument(
        "-p",
        "--provider",
        type=str,
        default=None,
        help="TTS provider override (mac_say, edge_tts, elevenlabs)",
    )
    speak_p.add_argument(
        "-r",
        "--rate",
        type=str,
        default=None,
        help="Speech rate / speed override (e.g. 75%%, 150, -25%%)",
    )
    speak_p.add_argument(
        "-s",
        "--speed",
        "--speed-talk",
        dest="speed",
        type=str,
        default=None,
        help="Speed talking multiplier or preset (e.g. 1.5x, turbo, 2.0x, fast)",
    )
    speak_p.add_argument(
        "--fast",
        action="store_true",
        help="Speak in fast speed talking mode (1.5x / 300 WPM)",
    )

    # setup
    setup_p = subparsers.add_parser(
        "setup",
        help="Auto-configure agent lifecycle hooks & MCP servers (Antigravity, Claude Code)",
    )
    setup_p.add_argument("--all", action="store_true", help="Setup all agents globally")
    setup_p.add_argument("--claude", action="store_true", help="Setup Claude Code")
    setup_p.add_argument("--antigravity", action="store_true", help="Setup Antigravity")
    setup_p.add_argument(
        "--mcp", action="store_true", help="Setup Model Context Protocol (MCP) server configuration"
    )
    setup_p.add_argument(
        "--dev", action="store_true", help="Link agent hooks to current repository local .venv"
    )
    setup_p.add_argument(
        "--remove-hooks",
        "--uninstall-hooks",
        dest="remove_hooks",
        action="store_true",
        help="Remove VoiceFi hooks from agent configurations",
    )

    # mcp
    mcp_p = subparsers.add_parser(
        "mcp", aliases=["mcp-server"], help="Start native Model Context Protocol (MCP) stdio server"
    )
    mcp_p.add_argument(
        "--test",
        "--check",
        "--ping",
        dest="test",
        action="store_true",
        help="Test live PostHog MCP Analytics event emission and connectivity",
    )
    mcp_p.add_argument(
        "--json",
        action="store_true",
        help="Output diagnostics in JSON format",
    )

    ob_p = subparsers.add_parser(
        "onboarding", help="Run interactive First-Time User Experience onboarding flow"
    )
    ob_p.set_defaults(
        func=lambda args: __import__("voicefi.onboarding", fromlist=[""]).run_onboarding()
    )

    # listen
    listen_p = subparsers.add_parser("listen", help="Listen from microphone and transcribe")
    listen_p.add_argument(
        "--to",
        choices=["active", "antigravity", "claude"],
        default="active",
        help="Target agent or app for zero-focus background IPC dispatch (default: active)",
    )
    listen_p.add_argument(
        "--no-inject",
        dest="inject",
        action="store_false",
        default=True,
        help="Do not inject into active app",
    )
    listen_p.add_argument(
        "--no-enter",
        dest="enter",
        action="store_false",
        default=True,
        help="Do not press Enter after pasting",
    )
    listen_p.add_argument(
        "-q", "--quiet", action="store_true", help="Disable audio feedback chimes"
    )

    # loop
    loop_p = subparsers.add_parser("loop", help="Start continuous voice loop")
    loop_p.add_argument("--no-inject", dest="inject", action="store_false", default=True)
    loop_p.add_argument("--no-enter", dest="enter", action="store_false", default=True)
    loop_p.add_argument("-q", "--quiet", action="store_true")

    # wake / wakeword / hey-viv
    wake_p = subparsers.add_parser(
        "wake",
        aliases=["wakeword", "hey-viv"],
        help="Run interactive 'Hey Viv' wake word listener and dispatcher",
    )
    wake_p.add_argument("--phrase", help="Override primary wake phrase (default: 'Hey Viv')")

    # tray / dev
    subparsers.add_parser("tray", help="Launch macOS menu bar companion")
    subparsers.add_parser(
        "dev", help="Launch in foreground dev mode with live console logs and auto-takeover"
    )

    # clean / purge
    clean_p = subparsers.add_parser(
        "clean",
        aliases=["purge", "reset-cache"],
        help="Clean stale Python bytecode, caches, locks, and servers",
    )
    clean_p.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Stop all background servers and clean all caches & locks",
    )
    clean_p.add_argument(
        "--dev",
        "-d",
        action="store_true",
        help="Clean caches, stop servers, and re-link hooks to local repository .venv",
    )
    clean_p.add_argument(
        "--servers",
        "--daemons",
        action="store_true",
        dest="servers",
        help="Stop and terminate running VoiceFi background servers",
    )

    # status / stop / start / restart shortcuts
    subparsers.add_parser(
        "status", help="Show VoiceFi server status, active devices, and port listeners"
    )
    subparsers.add_parser("stop", help="Stop VoiceFi background server and free port 5141")
    subparsers.add_parser("start", help="Start VoiceFi background server (LaunchAgent)")
    subparsers.add_parser("restart", help="Restart VoiceFi background server and reload config")

    # server / daemon / service / kill
    server_p = subparsers.add_parser(
        "server",
        aliases=["daemon", "service"],
        help="Inspect and manage background server, LaunchAgents, and port listeners",
    )
    server_p.add_argument(
        "server_action",
        nargs="?",
        default="status",
        choices=["status", "stop", "kill", "restart", "start", "reload"],
        help="Server action (default: status)",
    )
    subparsers.add_parser(
        "kill", help="Immediately stop all VoiceFi background servers and free port 5141"
    )

    # pause / resume
    subparsers.add_parser(
        "pause", help="Pause VoiceFi audio hooks and active turn-handoffs globally"
    )
    subparsers.add_parser(
        "resume", help="Resume VoiceFi audio hooks and active turn-handoffs globally"
    )
    subparsers.add_parser(
        "permissions", help="Check and open macOS Accessibility & Input Monitoring settings"
    )

    # autostart
    subparsers.add_parser(
        "autostart", help="Register macOS LaunchAgent to keep menu bar icon persistent"
    )
    subparsers.add_parser("stop-autostart", help="Remove macOS LaunchAgent autostart")

    # companion / remote / pair / rc
    comp_p = subparsers.add_parser(
        "companion",
        aliases=["remote", "pair", "rc", "RC"],
        help="Launch Web & Mobile Voice Companion (PWA & QR code)",
    )
    comp_p.add_argument(
        "action",
        nargs="?",
        default=None,
        help="Optional companion action or target view (e.g. 'sheet', 'spicewood')",
    )
    comp_p.add_argument(
        "--port", type=int, default=5141, help="Port to run companion server (default: 5141)"
    )
    comp_p.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)"
    )
    comp_p.add_argument("--no-qr", action="store_true", help="Do not print terminal QR code")
    comp_p.add_argument(
        "--open", action="store_true", help="Open local companion in default browser"
    )
    comp_p.add_argument(
        "--sheet",
        action="store_true",
        help="Open Spicewood Texas lead sheet directly in companion",
    )
    comp_p.add_argument(
        "--tunnel",
        action="store_true",
        help="Start trusted HTTPS Cloudflare tunnel for remote / mobile LTE/5G access anywhere",
    )

    # panel
    panel_p = subparsers.add_parser("panel", help="Launch interactive Voice Control Panel")
    panel_p.add_argument(
        "--port", type=int, default=5141, help="Port to run web control panel (default: 5141)"
    )
    panel_p.add_argument(
        "--no-browser", action="store_true", help="Do not open browser automatically"
    )
    panel_p.add_argument(
        "--claude", action="store_true", help="Directly open Claude Voice Contenders Studio"
    )

    # bar / prompt / quick
    bar_p = subparsers.add_parser(
        "bar",
        aliases=["prompt", "quick"],
        help="Launch or toggle native macOS Quick Prompt Bar (Control+Space)",
    )
    bar_p.add_argument(
        "text",
        nargs="*",
        default=None,
        help="Optional initial prompt text to populate in the bar",
    )

    # info
    subparsers.add_parser("info", help="Show system status and voices")

    # tier / pricing / trial
    subparsers.add_parser(
        "tier",
        aliases=["pricing", "trial", "plan"],
        help="Display active tier, 14-day free trial countdown, and pricing plans",
    )
    lic_p = subparsers.add_parser(
        "license", help="View license status or activate VoiceFi Pro license key"
    )
    lic_sub = lic_p.add_subparsers(
        dest="license_action", metavar="<action>", help="License action (status, activate)"
    )
    lic_sub.add_parser("status", help="Show active license and 14-day free trial status")
    lic_sub.add_parser(
        "where",
        aliases=["help", "find", "recover", "lost"],
        help="Where to find or recover your license key (Polar email, portal, or trial)",
    )
    lic_act = lic_sub.add_parser(
        "activate", aliases=["set", "apply"], help="Activate a VoiceFi Pro license key"
    )
    lic_act.add_argument("key", type=str, help="Pro license key (e.g. VF1-PRO-...)")
    lic_gen = lic_sub.add_parser(
        "generate",
        aliases=["create", "mint", "new"],
        help="Generate an unforgeable VoiceFi license key (requires admin key)",
    )
    lic_gen.add_argument("--tier", default="PRO", help="License tier (PRO, ORG, ENTERPRISE, VIP)")
    lic_gen.add_argument("--expires", default="PERP", help="Expiration (PERP or YYYYMMDD)")
    lic_gen.add_argument("--tag", default="TESTER", help="Recipient tag or promo name")

    # learn / learning (recursive phonetic and brevity self-learning)
    learn_p = subparsers.add_parser(
        "learn",
        aliases=["learning"],
        help="Inspect and manage recursive phonetic and brevity self-learning memory",
    )
    learn_sub = learn_p.add_subparsers(
        dest="learn_action", metavar="<action>", help="Learning action (status, scan, teach, reset)"
    )
    learn_sub.add_parser(
        "status", help="Show recursive phonetic memory and cognitive brevity metrics"
    )
    l_scan = learn_sub.add_parser(
        "scan", help="Scan active repository to index project symbols into phonetic memory"
    )
    l_scan.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Directory path to scan (defaults to current directory)",
    )
    l_teach = learn_sub.add_parser(
        "teach", help="Manually teach VoiceFi a spoken-to-canonical phonetic mapping"
    )
    l_teach.add_argument("spoken", type=str, help="Spoken phrase (e.g. 'wifi tier')")
    l_teach.add_argument("canonical", type=str, help="Canonical code / command (e.g. 'vifi tier')")
    l_test = learn_sub.add_parser(
        "test", help="Test and benchmark spoken turn summary distillation"
    )
    l_test.add_argument("text", type=str, help="Raw agent text or markdown output to distill")
    learn_sub.add_parser("reset", help="Reset learned phonetic and brevity memory files")

    # voice
    voice_p = subparsers.add_parser("voice", help="Manage and audition agent voices")
    voice_sub = voice_p.add_subparsers(dest="voice_action", metavar="<action>", help="Voice action")

    # voice download-ava (Apple Ava Premium 0ms offline speech)
    v_ava = voice_sub.add_parser(
        "download-ava",
        aliases=["install-ava", "setup-ava", "get-ava", "download_ava", "setup-offline", "offline"],
        help="Download and configure Apple's Ava (Premium) neural voice for 0ms offline speech",
    )
    v_ava.add_argument(
        "--check", action="store_true", help="Check if Ava is installed without opening settings"
    )
    v_ava.add_argument(
        "--no-wait",
        "--no-poll",
        dest="no_wait",
        action="store_true",
        help="Open System Settings without waiting loop",
    )
    v_ava.add_argument(
        "--timeout", type=int, default=300, help="Polling timeout in seconds (default: 300)"
    )
    v_ava.add_argument(
        "-s", "--silent", "-q", "--quiet", dest="silent", action="store_true", help="Silent mode"
    )

    # voice panel
    vp_panel = voice_sub.add_parser("panel", help="Launch interactive Voice Control Panel")
    vp_panel.add_argument("--port", type=int, default=5141)
    vp_panel.add_argument("--no-browser", action="store_true")
    vp_panel.add_argument(
        "--claude", action="store_true", help="Directly open Claude Voice Contenders Studio"
    )

    # voice command
    vp_cmd = voice_sub.add_parser("command", help="Execute a natural voice command")
    vp_cmd.add_argument(
        "command_text",
        nargs="+",
        help="Command phrase to execute (e.g. 'audition Viv', 'switch to Aria')",
    )

    # voice list
    v_list = voice_sub.add_parser("list", help="List curated and system voices")
    v_list.add_argument(
        "--provider", type=str, default=None, help="Filter by provider (edge_tts, mac_say)"
    )
    v_list.add_argument("-a", "--all", action="store_true", help="Include uncurated system voices")

    # voice test
    v_test = voice_sub.add_parser(
        "test", help="Audition / test a single voice or run feedback loop"
    )
    v_test.add_argument(
        "voice",
        nargs="?",
        default=None,
        help="Voice name or ID (e.g. Viv, Christopher, Aria, en-US-AvaNeural)",
    )
    v_test.add_argument("-t", "--text", type=str, default=None, help="Custom text sample to speak")
    v_test.add_argument(
        "-s",
        "--silent",
        action="store_true",
        help="Silently test connection and speed without playing audio over speakers",
    )
    v_test.add_argument(
        "--phrase",
        type=str,
        default=None,
        choices=["greeting", "code_review", "qa_alert", "punctuation", "architecture"],
        help="Preset test phrase",
    )
    v_test.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    v_test.add_argument(
        "-r", "--rate", type=str, default=None, help="Speech rate / speed override (e.g. 75%%, 150)"
    )
    v_test.add_argument(
        "-m",
        "--mic",
        "--mic-loopback",
        dest="mic_loopback",
        action="store_true",
        help="Record and hear 3s microphone loopback test",
    )
    v_test.add_argument(
        "--hearing",
        "--hearing-test",
        dest="hearing",
        action="store_true",
        help="Hearing test: Speak test phrase and verify mic reception via STT",
    )
    v_test.add_argument(
        "--feedback-loop",
        "--loopback",
        dest="feedback_loop",
        action="store_true",
        help="Feedback Loop test: Speak aloud, capture via mic, transcribe, and send",
    )
    v_test.add_argument(
        "--no-send",
        "--dry-run",
        dest="no_send",
        action="store_true",
        help="Do not dispatch transcribed text to conversation",
    )
    v_test.add_argument(
        "-c",
        "--conv-id",
        "--cid",
        dest="conv_id",
        type=str,
        default=None,
        help="Target conversation ID for message delivery",
    )
    v_test.add_argument(
        "--verify",
        "--stt-loopback",
        dest="verify",
        action="store_true",
        help="Acoustic STT verification",
    )
    v_test.add_argument(
        "-b", "--benchmark", action="store_true", help="Benchmark latency of all curated voices"
    )
    v_test.add_argument("-a", "--all", action="store_true", help="Audition all curated personas")
    v_test.add_argument(
        "--hud",
        action="store_true",
        help="Display visual Dynamic Island HUD popup during test (default: headless)",
    )
    v_test.add_argument("--json", action="store_true", help="Output results in JSON format")

    # voice ping (silent connection, speed, and latency test)
    v_ping = voice_sub.add_parser(
        "ping",
        aliases=["check", "speed-test"],
        help="Silently test connection, latency, speed, and health of neural voices",
    )
    v_ping.add_argument(
        "voice",
        nargs="?",
        default=None,
        help="Voice name or ID to ping (e.g. Viv, Andrew, Christopher, Aria). Defaults to active voice.",
    )
    v_ping.add_argument(
        "-t", "--text", type=str, default=None, help="Custom text sample for speed synthesis test"
    )
    v_ping.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Number of pings to measure avg latency and jitter",
    )
    v_ping.add_argument(
        "-a", "--all", action="store_true", help="Ping and benchmark all curated personas"
    )
    v_ping.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    v_ping.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override")
    v_ping.add_argument("--json", action="store_true", help="Output ping results in JSON format")

    # ping top-level
    ping_p = subparsers.add_parser(
        "ping",
        aliases=["speed-test", "check-voice"],
        help="Silently test voice connection, latency, and throughput speed",
    )
    ping_p.add_argument(
        "voice", nargs="?", default=None, help="Voice name or ID to ping. Defaults to active voice."
    )
    ping_p.add_argument(
        "-t", "--text", type=str, default=None, help="Custom text sample for speed synthesis test"
    )
    ping_p.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Number of pings to measure avg latency and jitter",
    )
    ping_p.add_argument(
        "-a", "--all", action="store_true", help="Ping and benchmark all curated personas"
    )
    ping_p.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    ping_p.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override")
    ping_p.add_argument("--json", action="store_true", help="Output ping results in JSON format")

    # feedback-loop / proactive top-level
    fb_p = subparsers.add_parser(
        "feedback-loop",
        aliases=[
            "proactive",
            "proactive-feedback-loop",
            "proactive-listening",
            "feedback_loop",
            "loopback",
            "voice-loop",
        ],
        help="Manage ProActive Feedback Loop (on/off/status) or run acoustic verification test",
    )
    fb_p.add_argument("voice", nargs="?", default="Aria", help="Voice to speak")
    fb_p.add_argument(
        "-t",
        "--text",
        type=str,
        default="This is a test feedback loop",
        help="Phrase to speak and verify",
    )
    fb_p.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    fb_p.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override")
    fb_p.add_argument(
        "--no-send",
        "--dry-run",
        dest="no_send",
        action="store_true",
        help="Do not dispatch transcribed text to conversation",
    )
    fb_p.add_argument(
        "-c",
        "--conv-id",
        "--cid",
        dest="conv_id",
        type=str,
        default=None,
        help="Target conversation ID for message delivery",
    )
    fb_p.add_argument(
        "--hud", action="store_true", help="Display visual Dynamic Island HUD during verification"
    )
    fb_p.add_argument(
        "--json", action="store_true", help="Output feedback loop results in JSON format"
    )

    # hearing-test top-level
    ht_p = subparsers.add_parser(
        "hearing-test",
        aliases=["hearing"],
        help="Hearing test: Speak phrase and verify microphone & STT reception from speakers",
    )
    ht_p.add_argument("voice", nargs="?", default="Aria", help="Voice to test")
    ht_p.add_argument(
        "-t",
        "--text",
        type=str,
        default="This is a hearing test",
        help="Phrase to speak and verify",
    )
    ht_p.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    ht_p.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override")
    ht_p.add_argument(
        "--hud", action="store_true", help="Display visual Dynamic Island HUD during verification"
    )
    ht_p.add_argument(
        "--json", action="store_true", help="Output hearing test results in JSON format"
    )

    # barge-in top-level
    barge_p = subparsers.add_parser(
        "barge-in",
        aliases=["test-barge-in", "barge_in"],
        help="Live Active Barge-In test: speaks phrase aloud and tests mid-sentence voice interruption with Silero VAD",
    )
    barge_p.add_argument("voice", nargs="?", default=None, help="Voice to speak during test")
    barge_p.add_argument(
        "-t", "--text", type=str, default=None, help="Phrase to speak and interrupt"
    )

    # voice troubleshoot
    v_tr = voice_sub.add_parser(
        "troubleshoot", help="Run comprehensive audio & voice troubleshooting diagnostic suite"
    )
    v_tr.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive guided troubleshooting wizard",
    )
    v_tr.add_argument(
        "-m",
        "--mic",
        "--loopback",
        dest="loopback",
        action="store_true",
        help="Microphone loopback test",
    )
    v_tr.add_argument("--hearing", action="store_true", help="Run acoustic hearing test")
    v_tr.add_argument("--verify", action="store_true", help="Acoustic STT verification")
    v_tr.add_argument(
        "-b",
        "--benchmark",
        "--tts-only",
        dest="benchmark",
        action="store_true",
        help="Benchmark TTS latency only",
    )
    v_tr.add_argument("-v", "--voice", type=str, default=None, help="Specific voice to test")
    v_tr.add_argument(
        "--hud",
        action="store_true",
        help="Display visual Dynamic Island HUD popup during test (default: headless)",
    )
    v_tr.add_argument(
        "--fix",
        type=str,
        default=None,
        help="Apply auto-fix (reset_defaults, set_offline_fallback, calibrate_mic)",
    )
    v_tr.add_argument("--json", action="store_true", help="Output diagnostic report in JSON")

    # troubleshoot top-level
    tr_top = subparsers.add_parser(
        "troubleshoot",
        aliases=["test"],
        help="Run comprehensive audio & voice troubleshooting diagnostic suite",
    )
    tr_top.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive guided troubleshooting wizard",
    )
    tr_top.add_argument(
        "-m",
        "--mic",
        "--loopback",
        dest="loopback",
        action="store_true",
        help="Microphone loopback test",
    )
    tr_top.add_argument(
        "-b",
        "--benchmark",
        "--tts-only",
        dest="benchmark",
        action="store_true",
        help="Benchmark TTS latency only",
    )
    tr_top.add_argument("-v", "--voice", type=str, default=None, help="Specific voice to test")
    tr_top.add_argument(
        "--hud",
        action="store_true",
        help="Display visual Dynamic Island HUD popup during test (default: headless)",
    )
    tr_top.add_argument("--fix", type=str, default=None, help="Apply auto-fix")
    tr_top.add_argument("--json", action="store_true", help="Output diagnostic report in JSON")

    # voice audition
    voice_sub.add_parser("audition", help="Play live multi-agent voice showcase across speakers")

    # vad top-level
    vad_p = subparsers.add_parser("vad", help="Open the Expert VAD & Acoustic Inspector Panel")

    # voice rate / speed
    v_rate = voice_sub.add_parser(
        "rate", help="Get or set speech rate / speed (e.g. 75%%, 150, faster, slower)"
    )
    v_rate.add_argument(
        "value",
        nargs="?",
        default=None,
        help="Speed value (e.g. '75%%', '150', 'faster', 'slower', 'reset')",
    )
    v_rate.add_argument(
        "-a", "--agent", type=str, default=None, help="Target specific agent or subagent"
    )

    v_speed = voice_sub.add_parser("speed", help="Alias for 'vg voice rate'")
    v_speed.add_argument(
        "value",
        nargs="?",
        default=None,
        help="Speed value (e.g. '75%%', '150', 'faster', 'slower', 'reset')",
    )
    v_speed.add_argument(
        "-a", "--agent", type=str, default=None, help="Target specific agent or subagent"
    )

    v_st = voice_sub.add_parser(
        "speed-talk",
        aliases=["speedtalk", "speed_talk"],
        help="Enable, configure, audition, or benchmark Speed Talking (1.25x - 3.0x)",
    )
    v_st.add_argument(
        "action",
        nargs="?",
        default=None,
        help="Action or preset (on, off, set, turbo, fast, sonic, warp, test, ramp, demo, stats)",
    )
    v_st.add_argument(
        "preset_or_multiplier",
        nargs="?",
        default=None,
        help="Speed preset or multiplier (e.g. 'turbo', '1.75x', '2.0')",
    )
    v_st.add_argument("-t", "--text", type=str, default=None, help="Custom text to speak")


    # voice set
    v_set = voice_sub.add_parser(
        "set", help="Assign a voice to an agent, project, or subagent and play acoustic confirmation"
    )
    v_set.add_argument(
        "agent", type=str, help="Agent, project, or voice name (e.g. viv, antigravity, claude, lienlogic, default)"
    )
    v_set.add_argument(
        "voice",
        type=str,
        nargs="?",
        default=None,
        help="Voice name or ID (e.g. Viv, Guy, Christopher, Aria) if agent or project was specified first",
    )
    v_set.add_argument(
        "--project",
        action="store_true",
        help="Assign as project-specific voice profile",
    )
    v_set.add_argument(
        "-t", "--text", type=str, default=None, help="Custom confirmation phrase to speak"
    )
    v_set.add_argument(
        "-q",
        "--quiet",
        "--silent",
        dest="quiet",
        action="store_true",
        help="Silently assign voice without playing confirmation speech",
    )
    v_set.add_argument("-p", "--provider", type=str, default=None)
    v_set.add_argument(
        "-r", "--rate", type=str, default=None, help="Speech rate / speed (e.g. 75%%, 150, -25%%)"
    )

    # voice get
    voice_sub.add_parser("get", help="Show active voice mappings")

    # voice clone
    v_clone = voice_sub.add_parser(
        "clone",
        aliases=["train"],
        help="Clone, record, import, test, and manage custom voice profiles",
    )
    v_clone.add_argument("name", nargs="?", default=None, help="Name for the custom cloned voice (or action: list, delete, test)")
    v_clone.add_argument("target", nargs="?", default=None, help="Target voice name when action is specified (e.g. 'vifi voice clone delete MyVoice')")
    v_clone.add_argument(
        "--audio",
        "-a",
        nargs="+",
        dest="audio_files",
        default=None,
        help="Audio file(s) to clone from (.wav, .mp3, .m4a)",
    )
    v_clone.add_argument(
        "--record",
        "-r",
        action="store_true",
        help="Launch interactive 4-prompt microphone recording wizard",
    )
    v_clone.add_argument(
        "--assign",
        type=str,
        default=None,
        help="Assign directly to agent upon completion (e.g. antigravity, claude)",
    )
    v_clone.add_argument(
        "--provider",
        type=str,
        default="auto",
        choices=["auto", "kokoro", "local_clone", "f5_tts", "elevenlabs", "edge_tts"],
        help="TTS engine provider for voice cloning",
    )
    v_clone.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    v_clone.add_argument("--description", type=str, default="", help="Voice description")
    v_clone.add_argument("-l", "--list", action="store_true", help="List all custom cloned voices")
    v_clone.add_argument("-t", "--test", action="store_true", help="Audition the cloned voice")
    v_clone.add_argument("--text", type=str, default=None, help="Sample text to speak for audition")
    v_clone.add_argument("-d", "--delete", action="store_true", help="Delete a cloned voice profile")

    # clone
    clone_p = subparsers.add_parser("clone", help="Train and manage custom voice clones")
    clone_sub = clone_p.add_subparsers(dest="clone_action", metavar="<action>", help="Clone action")

    # clone record
    c_rec = clone_sub.add_parser("record", help="Record voice samples via mic wizard")
    c_rec.add_argument("name", type=str, help="Name for the custom cloned voice")
    c_rec.add_argument(
        "--provider",
        type=str,
        default="auto",
        choices=["auto", "f5_tts", "elevenlabs", "edge_tts"],
        help="TTS engine provider for voice cloning",
    )
    c_rec.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    c_rec.add_argument("--description", type=str, default="", help="Voice description")
    c_rec.add_argument(
        "--assign", type=str, default=None, help="Assign directly to agent upon completion"
    )

    # clone import
    c_imp = clone_sub.add_parser("import", help="Train voice from existing audio files")
    c_imp.add_argument("name", type=str, help="Name for the custom cloned voice")
    c_imp.add_argument("files", nargs="+", help="Audio files (.wav, .mp3, .m4a)")
    c_imp.add_argument(
        "--provider",
        type=str,
        default="auto",
        choices=["auto", "f5_tts", "elevenlabs", "edge_tts"],
        help="TTS engine provider for voice cloning",
    )
    c_imp.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    c_imp.add_argument("--description", type=str, default="", help="Voice description")
    c_imp.add_argument(
        "--assign", type=str, default=None, help="Assign directly to agent upon completion"
    )

    # clone studio
    clone_sub.add_parser(
        "studio", help="Launch local open-source voice cloning web studio (F5-TTS)"
    )

    # clone list
    clone_sub.add_parser("list", help="List all custom trained voices")

    # clone test
    c_test = clone_sub.add_parser("test", help="Audition / test a custom cloned voice")
    c_test.add_argument("name", type=str, help="Name of custom voice to audition")
    c_test.add_argument("-t", "--text", type=str, default=None, help="Text to speak")

    # clone assign
    c_assign = clone_sub.add_parser("assign", help="Assign cloned voice to an agent")
    c_assign.add_argument("name", type=str, help="Name of custom voice")
    c_assign.add_argument(
        "agent", type=str, help="Target agent (antigravity, claude, researcher, debugger, default)"
    )

    # clone delete
    c_del = clone_sub.add_parser("delete", help="Delete a cloned voice profile")
    c_del.add_argument("name", type=str, help="Name of voice to delete")
    c_del.add_argument(
        "--from-provider", action="store_true", help="Also delete from ElevenLabs API"
    )

    # clone prompt
    c_prompt = clone_sub.add_parser("prompt", help="View AI persona style prompt for cloned voice")
    c_prompt.add_argument("name", type=str, help="Name of custom voice")

    # feedback
    fb_p = subparsers.add_parser("feedback", help="Submit feedback, bug reports, or requests")
    fb_sub = fb_p.add_subparsers(dest="feedback_action", metavar="<action>", help="Feedback action")

    fb_submit = fb_sub.add_parser("submit", help="Submit feedback or bug report")
    fb_submit.add_argument("title", nargs="+", help="Feedback title or summary")
    fb_submit.add_argument("-d", "--details", type=str, default="", help="Detailed explanation")
    fb_submit.add_argument(
        "-c",
        "--category",
        type=str,
        default="general",
        choices=["bug", "feature", "voice_quality", "latency", "general"],
    )
    fb_submit.add_argument("--agent-id", type=str, default=None, help="Submitting agent name")
    fb_submit.add_argument(
        "--no-diagnostics", action="store_true", help="Exclude environment diagnostics"
    )

    fb_list = fb_sub.add_parser("list", help="List recent feedback submissions")
    fb_list.add_argument("-n", "--limit", type=int, default=10)

    # memo / buffer
    memo_p = subparsers.add_parser(
        "memo",
        aliases=["buffer"],
        help="Voice memo buffer: capture long rambles & synthesize to code",
    )
    memo_sub = memo_p.add_subparsers(
        dest="memo_action", metavar="<action>", help="Voice memo action"
    )

    # memo record
    m_rec = memo_sub.add_parser(
        "record", help="Record a 2-5 min voice memo with elegant countdown timer"
    )
    m_rec.add_argument(
        "-d",
        "--duration",
        type=str,
        default=None,
        help="Target recording duration (e.g. '3m', '5m', '180')",
    )
    m_rec.add_argument("-t", "--title", type=str, default=None, help="Title for the voice memo")
    m_rec.add_argument(
        "-o", "--out", type=str, default=None, help="Export synthesized plan to markdown file"
    )
    m_rec.add_argument(
        "-c", "--clipboard", action="store_true", help="Copy synthesized plan to clipboard"
    )
    m_rec.add_argument("--no-synth", action="store_true", help="Skip automatic thought synthesis")

    # memo synth
    m_synth = memo_sub.add_parser(
        "synth",
        aliases=["synthesize"],
        help="Synthesize stream-of-consciousness thoughts into code plan",
    )
    m_synth.add_argument("memo_id", nargs="?", default=None, help="Memo ID to synthesize")
    m_synth.add_argument(
        "-t", "--text", nargs="+", default=None, help="Raw speech text to synthesize"
    )
    m_synth.add_argument(
        "-f", "--file", type=str, default=None, help="Text or transcript file to synthesize"
    )
    m_synth.add_argument("--title", type=str, default=None, help="Custom title for generated plan")
    m_synth.add_argument(
        "-o", "--out", type=str, default=None, help="Export path for generated markdown"
    )
    m_synth.add_argument(
        "-c", "--clipboard", action="store_true", help="Copy generated plan to clipboard"
    )

    # memo list
    m_list = memo_sub.add_parser("list", help="List stored voice memos and brain dumps")
    m_list.add_argument("-n", "--limit", type=int, default=20, help="Max memos to list")

    # memo show
    m_show = memo_sub.add_parser("show", help="Display full synthesized plan or transcript")
    m_show.add_argument("memo_id", type=str, help="Memo ID")
    m_show.add_argument(
        "--transcript", dest="transcript_only", action="store_true", help="Show raw transcript only"
    )
    m_show.add_argument(
        "--diagram", dest="diagram_only", action="store_true", help="Show Mermaid diagram only"
    )
    m_show.add_argument(
        "--checklist", dest="checklist_only", action="store_true", help="Show PR checklist only"
    )

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

    # ambient listener & proactive meeting co-pilot
    amb_p = subparsers.add_parser(
        "ambient",
        aliases=["meeting"],
        help="ProActive Meeting Assistant & ambient background co-pilot",
    )
    amb_sub = amb_p.add_subparsers(
        dest="ambient_action",
        metavar="<action>",
        help="Meeting / Ambient action (start, stop, status, list, show)",
    )

    amb_start = amb_sub.add_parser("start", help="Start background meeting assistant session")
    amb_start.add_argument(
        "-t", "--title", type=str, default=None, help="Title for the meeting session"
    )
    amb_start.add_argument(
        "-o", "--output", type=str, default=None, help="Custom output markdown file path"
    )
    amb_start.add_argument("-s", "--speaker", type=str, default=None, help="Primary speaker name")
    amb_start.add_argument(
        "--source", choices=["mic", "loopback"], default="mic", help="Audio capture source"
    )
    amb_start.add_argument(
        "--auto-execute",
        action="store_true",
        default=True,
        help="Auto-execute detected Linear tickets, Slack updates, branch scaffolds",
    )
    amb_start.add_argument(
        "--no-auto-execute",
        dest="auto_execute",
        action="store_false",
        help="Stage action items without auto-executing",
    )

    amb_sub.add_parser("stop", help="Finalize active meeting session and save notes")
    amb_sub.add_parser("status", help="Show active meeting assistant status and action logs")
    amb_sub.add_parser("list", help="List saved meeting notes and sessions")

    amb_show = amb_sub.add_parser("show", help="Display full meeting notes")
    amb_show.add_argument(
        "target", nargs="?", default="latest", help="Meeting ID, keyword, or 'latest'"
    )

    amb_test = amb_sub.add_parser(
        "test",
        aliases=["simulate"],
        help="Run comprehensive automated QA simulation or interactive utterance tester",
    )
    amb_test.add_argument(
        "-i", "--interactive", action="store_true", help="Launch interactive utterance tester"
    )

    # STT biasing & phonetic normalizer
    bias_p = subparsers.add_parser(
        "bias", help="Inspect active STT vocabulary biasing or test phonetic normalization"
    )
    bias_p.add_argument("text", nargs="*", default=None, help="Spoken developer input to normalize")

    # obsidian
    obs_p = subparsers.add_parser(
        "obsidian", help="Manage and install VoiceFi plugin for Obsidian vaults"
    )
    obs_sub = obs_p.add_subparsers(dest="obsidian_action", metavar="<action>")
    inst_p = obs_sub.add_parser(
        "install", help="Install and enable VoiceFi plugin into Obsidian vault(s)"
    )
    inst_p.add_argument(
        "-v", "--vault", type=str, default=None, help="Target specific Obsidian vault directory"
    )
    inst_p.add_argument(
        "-a", "--all", action="store_true", help="Install into all registered vaults"
    )
    obs_sub.add_parser("list", help="List registered Obsidian vaults on this machine")
    obs_sub.add_parser("status", help="Show Obsidian installation, vault discovery, and daily note status")
    obs_sub.add_parser("today", help="Display today's daily note content from active Obsidian vault")
    obs_cap_p = obs_sub.add_parser("capture", help="Quick capture text directly into today's daily note")
    obs_cap_p.add_argument("text", nargs="*", default=None, help="Text to append to today's daily note")
    obs_cap_p.add_argument("-v", "--vault", type=str, default=None, help="Target specific Obsidian vault directory")
    obs_launch_p = obs_sub.add_parser("launch", help="Launch or pair AI agent (Antigravity or Claude Code) into vault")
    obs_launch_p.add_argument("--engine", choices=["antigravity", "claude"], default="antigravity", help="Agent engine to launch")

    # capture (top-level shortcut for direct voice-to-vault)
    cap_top_p = subparsers.add_parser(
        "capture", help="Direct voice or text capture into today's Obsidian daily note"
    )
    cap_top_p.add_argument("text", nargs="*", default=None, help="Text to append to today's daily note")
    cap_top_p.add_argument("-v", "--vault", type=str, default=None, help="Target specific Obsidian vault directory")

    # hud
    hud_p = subparsers.add_parser(
        "hud", help="Control, configure, and debug Unified Dynamic Island HUD"
    )
    hud_sub = hud_p.add_subparsers(
        dest="hud_action",
        metavar="<action>",
        help="HUD action (open, close, reset, debug, config, test, show, on, off, status, persistent, auto-send)",
    )
    hud_sub.add_parser(
        "open", aliases=["start", "launch"], help="Open and show persistent Dynamic Island HUD"
    )
    hud_sub.add_parser("close", aliases=["stop", "hide"], help="Close and hide Dynamic Island HUD")
    hud_sub.add_parser("on", aliases=["enable"], help="Enable and show persistent HUD")
    hud_sub.add_parser("off", aliases=["disable"], help="Disable and hide HUD")
    hud_sub.add_parser(
        "reset",
        aliases=["reset-position"],
        help="Reset HUD position to default bottom-right anchor above lower bar",
    )
    hud_sub.add_parser(
        "debug",
        help="Launch interactive terminal HUD Debug Studio with real-time keystroke controls",
    )
    hud_sub.add_parser("test", help="Run automated 6-state HUD showcase")
    hud_sub.add_parser("status", help="Display current HUD status and active settings")

    cfg_p = hud_sub.add_parser("config", help="View or update HUD configuration")
    cfg_p.add_argument(
        "--enabled",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Enable/disable HUD",
    )
    cfg_p.add_argument(
        "--persistent",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Enable/disable persistent resting pill",
    )
    cfg_p.add_argument(
        "--fullscreen-overlay",
        dest="fullscreen_overlay",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Always stay on top of full-screen games/apps",
    )
    cfg_p.add_argument(
        "--auto-send",
        dest="auto_send",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Enable instant auto-send or review mode",
    )
    cfg_p.add_argument(
        "--live-transcript",
        dest="live_transcript",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Stream live transcription typing",
    )
    cfg_p.add_argument(
        "--position",
        type=str,
        default=None,
        choices=["bottom_right", "top_center", "top_right", "top_left", "bottom_center"],
        help="HUD screen position",
    )
    cfg_p.add_argument(
        "--linger", type=float, default=None, help="Linger seconds after done/speaking"
    )

    show_p = hud_sub.add_parser("show", help="Display specific HUD state")
    show_p.add_argument(
        "--state",
        type=str,
        default="idle",
        choices=["idle", "thinking", "working", "speaking", "listening", "editing"],
        help="Target state",
    )
    show_p.add_argument("--text", type=str, default="", help="Custom subtitle / transcription text")
    show_p.add_argument("--duration", type=float, default=4.0, help="Display duration in seconds")

    pers_p = hud_sub.add_parser("persistent", help="Toggle or set persistent HUD mode")
    pers_p.add_argument(
        "persistent_state",
        nargs="?",
        default="toggle",
        choices=["on", "off", "toggle", "status"],
        help="Enable/disable persistent HUD",
    )

    fs_p = hud_sub.add_parser(
        "fullscreen",
        help="Toggle or set full-screen overlay mode (always on top of full screen apps/games)",
    )
    fs_p.add_argument(
        "fullscreen_state",
        nargs="?",
        default="toggle",
        choices=["on", "off", "toggle", "status"],
        help="Enable/disable full screen overlay",
    )

    as_p = hud_sub.add_parser("auto-send", help="Toggle or set auto-send prompt mode")
    as_p.add_argument(
        "auto_send_state",
        nargs="?",
        default="toggle",
        choices=["on", "off", "toggle", "status"],
        help="Enable/disable auto-send mode",
    )

    # new conversation
    new_p = subparsers.add_parser(
        "new", aliases=["new-conversation"], help="Start a new AI conversation with connected tools"
    )
    new_p.add_argument("prompt", nargs="*", default=["Hello"], help="Initial prompt message")
    new_p.add_argument("-t", "--title", type=str, default=None, help="Custom title")
    new_p.add_argument(
        "-m",
        "--model",
        type=str,
        default=None,
        choices=["flash_lite", "flash", "pro"],
        help="Model selection",
    )

    # update / upgrade
    up_p = subparsers.add_parser(
        "update", aliases=["upgrade"], help="Check for and install latest VoiceFi updates"
    )
    up_p.add_argument("--check", action="store_true", help="Check for updates without installing")
    up_p.add_argument("--repo", default=None, help="Custom git repository URL to upgrade from")

    # download-ava top-level (Apple Ava Premium 0ms offline speech)
    ava_top = subparsers.add_parser(
        "download-ava",
        aliases=["install-ava", "setup-ava", "get-ava", "setup-offline", "offline-ava"],
        help="Download and configure Apple's Ava (Premium) neural voice for 0ms offline speech",
    )
    ava_top.add_argument(
        "--check", action="store_true", help="Check if Ava is installed without opening settings"
    )
    ava_top.add_argument(
        "--no-wait",
        "--no-poll",
        dest="no_wait",
        action="store_true",
        help="Open System Settings without waiting loop",
    )
    ava_top.add_argument(
        "--timeout", type=int, default=300, help="Polling timeout in seconds (default: 300)"
    )
    ava_top.add_argument(
        "-s", "--silent", "-q", "--quiet", dest="silent", action="store_true", help="Silent mode"
    )

    # stats / analytics / insights
    stats_p = subparsers.add_parser(
        "stats",
        aliases=["analytics", "insights"],
        help="View local developer activity, tool usage, time saved, and acoustic latency benchmarks",
    )
    stats_p.add_argument(
        "-d", "--days", type=int, default=7, help="Number of days to analyze (default: 7)"
    )
    stats_p.add_argument("--today", action="store_true", help="Show only today's activity")
    stats_p.add_argument("--all", action="store_true", help="Show all-time activity")
    stats_p.add_argument(
        "--export",
        choices=["json", "csv"],
        default=None,
        help="Export local analytics event log as JSON or CSV",
    )
    stats_p.add_argument(
        "--clean",
        type=int,
        nargs="?",
        const=30,
        default=None,
        help="Purge local records older than N days (default: 30)",
    )
    stats_p.add_argument(
        "--reset",
        action="store_true",
        help="Completely wipe local analytics database (~/.voicefi/analytics.db)",
    )
    stats_p.add_argument(
        "--force", action="store_true", help="Bypass confirmation prompt for reset"
    )

    # speed-talk top-level
    speed_talk_p = subparsers.add_parser(
        "speed-talk",
        aliases=["speedtalk", "speed_talk", "fast", "turbo"],
        help="Enable, configure, audition, or benchmark Speed Talking (1.25x - 3.0x)",
    )
    speed_talk_p.add_argument(
        "action",
        nargs="?",
        default=None,
        help="Action or preset (on, off, set, turbo, fast, sonic, warp, test, ramp, demo, stats, list)",
    )
    speed_talk_p.add_argument(
        "preset_or_multiplier",
        nargs="?",
        default=None,
        help="Speed preset or multiplier (e.g. 'turbo', '1.75x', '2.0')",
    )
    speed_talk_p.add_argument("-t", "--text", type=str, default=None, help="Custom text to speak")
    speed_talk_p.add_argument(
        "--on", "--enable", dest="enable", action="store_true", help="Enable speed talking"
    )
    speed_talk_p.add_argument(
        "--off", "--disable", dest="disable", action="store_true", help="Disable speed talking"
    )
    speed_talk_p.add_argument(
        "--stats", action="store_true", help="Show speed talking time saved metrics"
    )
    speed_talk_p.add_argument(
        "--demo", action="store_true", help="Run multi-speed escalating showcase"
    )
    speed_talk_p.add_argument(
        "--ramp", action="store_true", help="Audition dynamic speed ramping"
    )
    speed_talk_p.add_argument(
        "-s",
        "--silent",
        "-q",
        "--quiet",
        dest="silent",
        action="store_true",
        help="Silent mode without audio playback",
    )

    # send / dispatch
    send_p = subparsers.add_parser(
        "send",
        aliases=["dispatch"],
        help="Send message/task across agents or peer Macs on LAN (Antigravity ↔ Claude Code ↔ Peer Macs)",
    )
    send_p.add_argument("text", nargs="+", help="Message or prompt to send")
    send_p.add_argument(
        "--to",
        type=str,
        default="claude",
        help="Target agent engine (claude, antigravity, gemini) or peer Mac name/IP (e.g. mba, pro, 192.168.1.50)",
    )
    send_p.add_argument(
        "--engine",
        type=str,
        default="auto",
        choices=["auto", "antigravity", "claude", "gemini", "chatgpt"],
        help="Target agent engine on remote peer Mac (default: auto)",
    )

    # peers / network discovery
    peers_p = subparsers.add_parser(
        "peers",
        aliases=["peer", "discover"],
        help="Discover VoiceFi instances and active AI coding agents across local Wi-Fi / LAN",
    )
    peers_p.add_argument("--port", type=int, default=5141, help="Peer discovery port (default: 5141)")

    # vandelay industries / import export
    vandelay_p = subparsers.add_parser(
        "vandelay",
        help="Vandelay Industries: Importers & Exporters of fine code, prompts & clipboards across Macs",
    )
    vandelay_p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "import", "in", "export", "out"],
        help="Vandelay action (list, import, export)",
    )
    vandelay_p.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target peer Mac name or IP (e.g. 'mba', 'pro', '192.168.1.80')",
    )

    # clip / clipboard sync
    clip_p = subparsers.add_parser(
        "clip",
        aliases=["clipboard"],
        help="Push or pull clipboard snippets across peer Macs on local Wi-Fi",
    )
    clip_p.add_argument(
        "action",
        choices=["push", "pull", "get", "send", "set"],
        help="Clipboard action: 'push' (send to remote Mac) or 'pull' (fetch from remote Mac)",
    )
    clip_p.add_argument(
        "target",
        help="Target peer Mac name or IP (e.g. 'mba', 'jakes-mbp', '192.168.1.80')",
    )
    send_p.add_argument(
        "--conv-id",
        "--id",
        dest="conv_id",
        type=str,
        default=None,
        help="Target conversation ID (default: active conversation)",
    )
    send_p.add_argument(
        "--reply", action="store_true", help="Reply directly to the originating conversation ID"
    )
    send_p.add_argument(
        "--from-conv-id",
        "--from",
        dest="from_conv_id",
        type=str,
        default=None,
        help="Originating conversation ID",
    )
    send_p.add_argument(
        "--from-engine", type=str, default="antigravity", help="Originating agent engine"
    )
    send_p.add_argument("--title", type=str, default=None, help="Message title / heading")
    send_p.add_argument(
        "--sender",
        dest="sender_name",
        type=str,
        default=None,
        help="Sender attribution (e.g. Claude, Antigravity)",
    )
    send_p.add_argument(
        "--no-envelope", action="store_true", help="Do not include provenance metadata header"
    )
    send_p.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="Execute via background headless CLI without window focus changes",
    )

    # duel / banter
    duel_p = subparsers.add_parser(
        "duel",
        aliases=["banter", "acoustic-test"],
        help="Run acoustic banter & voice benchmark test (Ava ↔ Steffan personas)",
    )
    duel_p.add_argument("--turns", type=int, default=3, help="Number of joke turns (default: 3)")
    duel_p.add_argument("--topic", type=str, default="programming jokes", help="Duel topic")
    duel_p.add_argument(
        "--live", action="store_true", help="Live dispatch prompts to Claude Code terminal session"
    )

    # fx / audio effects
    fx_p = subparsers.add_parser(
        "fx",
        aliases=["voice-fx", "effects"],
        help="Transform voice audio using studio DSP effects (radio announcer, podcast, monster, etc.)",
    )
    fx_p.add_argument(
        "input", nargs="?", default=None, help="Input audio file path or 'list' to show presets"
    )
    fx_p.add_argument(
        "-p",
        "--preset",
        default="radio_announcer",
        help="Voice effect preset (radio_announcer, studio_podcast, stadium_announcer, am_radio, cyber_robot, deep_monster, helium_chipmunk, ethereal_space)",
    )
    fx_p.add_argument(
        "-o", "--output", default=None, help="Output master audio file path (.mp3, .wav, .m4a)"
    )

    # reel / video reel compiler
    reel_p = subparsers.add_parser(
        "reel",
        aliases=["video", "compile-reel"],
        help="Compile multi-format social video reels (9:16, 1:1, 4:5, 16:9)",
    )
    reel_p.add_argument("input", nargs="?", default=None, help="Input master audio file path")
    reel_p.add_argument(
        "-f",
        "--format",
        default="9:16",
        choices=["9:16", "1:1", "4:5", "16:9"],
        help="Video aspect ratio preset",
    )
    reel_p.add_argument("-p", "--preset", default="classic_ai", help="Typography preset pairing")
    reel_p.add_argument(
        "-s", "--speaker", default="Radio Host", help="Speaker name / avatar attribution"
    )
    reel_p.add_argument(
        "--scale",
        "--font-scale",
        dest="font_scale",
        type=float,
        default=1.0,
        help="Typography sizing multiplier",
    )
    reel_p.add_argument("-o", "--output", default=None, help="Output MP4 file path")
    reel_p.add_argument(
        "--open", action="store_true", help="Automatically open video after compilation"
    )
    reel_p.add_argument(
        "--doc",
        "--documentary",
        action="store_true",
        help="Enable Documentary Mode (documentary broadcaster narration, Baskerville subtitles, BBC mastering)",
    )
    reel_p.add_argument("--script", default=None, help="Narrative script text to synthesize in documentary mode")
    reel_p.add_argument(
        "--persona", default="documentary_broadcaster", help="Voice persona for documentary narration (default: documentary_broadcaster)"
    )
    reel_p.add_argument(
        "--score", default="beatdrop", choices=["beatdrop", "classical", "none"], help="Soundtrack score style"
    )
    reel_p.add_argument(
        "--punchline", default=None, help="Punchline phrase for comedic dead-air tape-stop mute"
    )

    # trim / audio cutter
    trim_p = subparsers.add_parser(
        "trim",
        aliases=["cut", "slice"],
        help="Trim audio start and end timestamps with de-clicking fades",
    )
    trim_p.add_argument("input", nargs="?", default=None, help="Input audio file path")
    trim_p.add_argument(
        "--start", "-s", type=float, default=0.0, help="Start timestamp in seconds (default: 0.0)"
    )
    trim_p.add_argument(
        "--end",
        "-e",
        type=float,
        default=None,
        help="End timestamp in seconds (default: end of audio)",
    )
    trim_p.add_argument(
        "-o", "--output", default=None, help="Output trimmed audio file path (.mp3, .wav, .m4a)"
    )

    # sfx / sound cues
    sfx_p = subparsers.add_parser(
        "sfx",
        aliases=["sound"],
        help="Play comedy or dramatic audio cues (drum_smash, honk, sad_trombone, applause)",
    )
    sfx_p.add_argument(
        "name",
        nargs="?",
        default="drum_smash",
        help="Sound effect name (drum_smash, honk, sad_trombone, applause, boing, crickets, list)",
    )
    sfx_p.add_argument(
        "--volume", "-v", type=float, default=1.0, help="Playback volume (0.1 - 2.0)"
    )

    # bridge / ipc
    bridge_p = subparsers.add_parser(
        "bridge",
        aliases=["ipc-bridge", "ipc"],
        help="Run or manage VoiceFi Local IPC daemon bridge service",
    )
    bridge_p.add_argument(
        "--server", "-s", action="store_true", help="Run local IPC daemon socket server"
    )
    bridge_p.add_argument(
        "--socket",
        type=str,
        default=None,
        help="Path to Unix domain socket (default: /tmp/voicefi.sock)",
    )
    bridge_p.add_argument(
        "--ws-port", type=int, default=None, help="Fallback WebSocket port (default: 8765)"
    )
    bridge_p.add_argument(
        "-a", "--agent", type=str, default="Spark", help="Target agent identifier"
    )
    bridge_p.add_argument(
        "-p", "--persona", type=str, default=None, help="Voice persona (Viv, Christopher, etc.)"
    )

    # spark / gemini runner
    spark_p = subparsers.add_parser(
        "spark", help="Run Gemini Spark agent runner with voice bridge and turn-end hooks"
    )
    spark_p.add_argument("prompt", nargs="*", default=None, help="Optional prompt to execute once")
    spark_p.add_argument(
        "-p", "--persona", type=str, default=None, help="Spoken persona (Viv, Christopher, etc.)"
    )
    spark_p.add_argument("--socket", type=str, default=None, help="Path to Unix domain socket")

    # live / gemini 3.8 live runner
    live_p = subparsers.add_parser(
        "live",
        aliases=["comedy", "gemini-live"],
        help="Run real-time Gemini 3.8 Live voice/comedy session with co-timed sound effects",
    )
    live_p.add_argument("prompt", nargs="*", default=None, help="Prompt or joke topic to execute once")
    live_p.add_argument(
        "--model",
        default="gemini-2.5-flash-native-audio-latest",
        choices=["gemini-2.5-flash-native-audio-latest", "gemini-3.8-live", "gemini-3.8-live-extended-thinking"],
        help="Live model ID (default: gemini-2.5-flash-native-audio-latest for native audio speech)",
    )
    live_p.add_argument(
        "-v",
        "--voice",
        default="Puck",
        choices=sorted(list(VALID_GEMINI_LIVE_VOICES)),
        help="Voice persona (default: Puck)",
    )
    live_p.add_argument(
        "-m",
        "--mode",
        default="comedy",
        choices=["comedy", "roast", "banter", "assistant"],
        help="Persona mode (default: comedy)",
    )
    live_p.add_argument(
        "-t",
        "--thinking",
        action="store_true",
        help="Use Gemini 3.8 Live Extended Thinking model",
    )
    live_p.add_argument(
        "--thinking-level",
        default="LOW",
        choices=["MINIMAL", "LOW", "MEDIUM", "HIGH"],
        help="Thinking level for extended thinking (default: LOW)",
    )
    live_p.add_argument(
        "--no-sfx",
        action="store_true",
        help="Disable synchronized punchline sound effects",
    )
    live_p.add_argument(
        "--no-play",
        action="store_true",
        help="Do not play audio aloud through speakers",
    )
    live_p.add_argument(
        "-l",
        "--direct",
        dest="direct_live",
        action="store_true",
        help="Start direct microphone-to-speaker full-duplex speech loop",
    )
    live_p.add_argument(
        "--tools",
        action="store_true",
        default=True,
        help="Enable background tools while speaking (code reading, shell checks, sfx)",
    )
    live_p.add_argument(
        "--no-tools",
        dest="tools",
        action="store_false",
        help="Disable background tools",
    )

    # record / voice note recorder
    record_p = subparsers.add_parser(
        "record",
        aliases=["voice-note", "mic-record"],
        help="Record clean studio voice note from microphone",
    )
    record_p.add_argument(
        "-d",
        "--duration",
        type=float,
        default=8.0,
        help="Recording duration in seconds (default: 8.0)",
    )
    record_p.add_argument(
        "-o",
        "--output",
        "--out",
        default="assets/jake_intro.wav",
        help="Output audio file path (.wav)",
    )

    # welcome / onboarding window
    subparsers.add_parser(
        "welcome",
        aliases=["welcome-gui", "license-gui", "activate-gui"],
        help="Launch native macOS Welcome & License Activation Window",
    )

    # scout / recon
    scout_p = subparsers.add_parser(
        "scout",
        aliases=["recon"],
        help="Run on-device Recon Scout to pre-digest logs/files and save context tokens",
    )
    scout_p.add_argument(
        "target",
        nargs="?",
        default=".",
        help="File or directory path to scout (default: current directory)",
    )
    scout_p.add_argument("-q", "--query", default=None, help="Query or anomaly detection objective")
    scout_p.add_argument(
        "--max-bytes",
        type=int,
        default=500_000,
        help="Maximum bytes to scan (default: 500,000)",
    )

    # benchmark
    bench_p = subparsers.add_parser(
        "benchmark",
        aliases=["bench"],
        help="Measure on-device model throughput (tok/s), TTFB latency, and context efficiency",
    )
    bench_p.add_argument("prompt", nargs="*", default=None, help="Custom prompt to benchmark")
    bench_p.add_argument("--name", default="CLI Benchmark", help="Benchmark run label")
    bench_p.add_argument(
        "--history", action="store_true", help="Display previous benchmark scorecard history"
    )
    bench_p.add_argument(
        "-c",
        "--compare",
        action="store_true",
        help="Run empirical Time on Task (ToT) Benchmark: Local vs All-Cloud",
    )
    bench_p.add_argument(
        "-t",
        "--target",
        type=str,
        default="src/voicefi/local/engine.py",
        help="Target file or directory to benchmark",
    )
    bench_p.add_argument(
        "--turns", type=int, default=3, help="Number of multi-turn interactions (1-5, default: 3)"
    )
    bench_p.add_argument(
        "--cloud",
        type=str,
        default="gemini",
        choices=["gemini", "claude"],
        help="Cloud provider to compare against (default: gemini)",
    )
    bench_p.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON comparison profile"
    )

    # eval (direct alias for benchmark --compare)
    eval_p = subparsers.add_parser(
        "eval",
        help="Run empirical Time on Task (ToT) Benchmark comparing Local vs All-Cloud",
    )
    eval_p.add_argument("prompt", nargs="*", default=None, help="Custom prompt or diagnostic query")
    eval_p.add_argument(
        "-t",
        "--target",
        type=str,
        default="src/voicefi/local/engine.py",
        help="Target file or directory to benchmark",
    )
    eval_p.add_argument(
        "--turns", type=int, default=3, help="Number of multi-turn interactions (1-5, default: 3)"
    )
    eval_p.add_argument(
        "--cloud",
        type=str,
        default="gemini",
        choices=["gemini", "claude"],
        help="Cloud provider to compare against (default: gemini)",
    )
    eval_p.add_argument(
        "--history", action="store_true", help="Display previous ToT scorecard history"
    )
    eval_p.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON comparison profile"
    )

    # local model management
    local_p = subparsers.add_parser(
        "local",
        aliases=["litert", "gemma"],
        help="Inspect and manage on-device LiteRT and Gemma models",
    )
    local_p.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["status", "list", "download"],
        help="Action (status, list, download)",
    )

    # help
    subparsers.add_parser("help", help="Display help and command usage")

    return parser


def main():
    try:
        from voicefi.telemetry import init_telemetry

        init_telemetry()
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "root_live", False):
        cmd_live(args)
        return

    if not args.command:
        if getattr(sys, "frozen", False):
            # Launched from macOS .app bundle without CLI arguments
            try:
                from voicefi.ui.translocation import check_and_prompt_move_to_applications

                check_and_prompt_move_to_applications()
            except Exception:
                pass
            cmd_tray(args)
            return
        parser.print_help()
        sys.exit(0)

    commands = {
        "fx": cmd_fx,
        "voice-fx": cmd_fx,
        "effects": cmd_fx,
        "trim": cmd_trim,
        "cut": cmd_trim,
        "slice": cmd_trim,
        "reel": cmd_reel,
        "video": cmd_reel,
        "compile-reel": cmd_reel,
        "bridge": cmd_bridge,
        "ipc-bridge": cmd_bridge,
        "ipc": cmd_bridge,
        "spark": cmd_spark,
        "live": cmd_live,
        "comedy": cmd_live,
        "gemini-live": cmd_live,
        "sfx": cmd_sfx,
        "sound": cmd_sfx,
        "duel": cmd_duel,
        "banter": cmd_duel,
        "stats": cmd_stats,
        "analytics": cmd_stats,
        "insights": cmd_stats,
        "send": cmd_send,
        "dispatch": cmd_send,
        "peers": cmd_peers,
        "peer": cmd_peers,
        "discover": cmd_peers,
        "vandelay": cmd_vandelay,
        "clip": cmd_clip,
        "clipboard": cmd_clip,
        "update": cmd_update,
        "upgrade": cmd_update,
        "download-ava": cmd_download_ava,
        "install-ava": cmd_download_ava,
        "setup-ava": cmd_download_ava,
        "get-ava": cmd_download_ava,
        "setup-offline": cmd_download_ava,
        "offline-ava": cmd_download_ava,
        "scout": cmd_scout,
        "recon": cmd_scout,
        "benchmark": cmd_benchmark,
        "bench": cmd_benchmark,
        "eval": cmd_benchmark,
        "local": cmd_local,
        "litert": cmd_local,
        "gemma": cmd_local,
        "help": lambda a: parser.print_help(),
        "new": cmd_new,
        "new-conversation": cmd_new,
        "hook": cmd_hook,
        "speak": cmd_speak,
        "listen": cmd_listen,
        "loop": cmd_loop,
        "tray": cmd_tray,
        "dev": cmd_dev,
        "setup": cmd_setup,
        "onboarding": cmd_onboarding,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "permissions": cmd_permissions,
        "autostart": cmd_autostart,
        "stop-autostart": cmd_stop_autostart,
        "companion": cmd_companion,
        "remote": cmd_companion,
        "pair": cmd_companion,
        "rc": cmd_companion,
        "RC": cmd_companion,
        "panel": cmd_panel,
        "info": cmd_info,
        "tier": cmd_tier,
        "pricing": cmd_tier,
        "trial": cmd_tier,
        "plan": cmd_tier,
        "license": cmd_license,
        "learn": cmd_learn,
        "learning": cmd_learn,
        "obsidian": cmd_obsidian,
        "capture": cmd_capture,
        "voice": cmd_voice,
        "speed-talk": cmd_speed_talk,
        "speedtalk": cmd_speed_talk,
        "speed_talk": cmd_speed_talk,
        "fast": cmd_speed_talk,
        "turbo": cmd_speed_talk,
        "ping": cmd_ping,
        "speed-test": cmd_ping,
        "check-voice": cmd_ping,
        "hud": cmd_hud,
        "hearing-test": cmd_hearing_test,
        "hearing": cmd_hearing_test,
        "feedback": cmd_feedback,
        "feedback-loop": cmd_feedback_loop,
        "feedback_loop": cmd_feedback_loop,
        "voice-loop": cmd_feedback_loop,
        "loopback": cmd_loopback,
        "barge-in": cmd_barge_in,
        "barge_in": cmd_barge_in,
        "test-barge-in": cmd_barge_in,
        "troubleshoot": cmd_troubleshoot,
        "test": cmd_troubleshoot,
        "clone": cmd_clone,
        "clean": cmd_clean,
        "purge": cmd_clean,
        "reset-cache": cmd_clean,
        "server": cmd_server,
        "service": cmd_server,
        "daemon": cmd_server,
        "status": lambda a: cmd_server(
            argparse.Namespace(server_action="status", config=getattr(a, "config", None))
        ),
        "stop": lambda a: cmd_server(
            argparse.Namespace(server_action="stop", config=getattr(a, "config", None))
        ),
        "start": lambda a: cmd_server(
            argparse.Namespace(server_action="start", config=getattr(a, "config", None))
        ),
        "restart": lambda a: cmd_server(
            argparse.Namespace(server_action="restart", config=getattr(a, "config", None))
        ),
        "kill": lambda a: cmd_server(
            argparse.Namespace(server_action="stop", config=getattr(a, "config", None))
        ),
        "memo": cmd_memo,
        "buffer": cmd_memo,
        "record": cmd_record,
        "voice-note": cmd_record,
        "mic-record": cmd_record,
        "wake": cmd_wake,
        "wakeword": cmd_wake,
        "hey-viv": cmd_wake,
        "bar": cmd_quick_bar,
        "prompt": cmd_quick_bar,
        "quick": cmd_quick_bar,
        "welcome": cmd_welcome,
        "welcome-gui": cmd_welcome,
        "license-gui": cmd_welcome,
        "activate-gui": cmd_welcome,
        "ambient": cmd_ambient,
        "meeting": cmd_meeting,
        "feedbackloop": cmd_feedback_loop,
        "bias": cmd_bias,
        "vad": cmd_vad,
        "mcp": cmd_mcp,
        "mcp-server": cmd_mcp,
    }

    # Asynchronously trigger background update check
    try:
        from voicefi.updater import trigger_background_update_check

        trigger_background_update_check()
    except Exception:
        pass

    handler = commands.get(args.command)
    if handler:
        props = extract_cli_metadata(args)
        try:
            from voicefi.telemetry import set_active_command

            set_active_command(args.command)
        except Exception:
            pass
        start_time = time.time()
        success = True
        exit_code = 0
        error_type = None

        try:
            handler(args)
        except SystemExit as se:
            exit_code = se.code if isinstance(se.code, int) else (0 if se.code is None else 1)
            success = exit_code == 0
            raise
        except KeyboardInterrupt:
            success = False
            exit_code = 130
            error_type = "KeyboardInterrupt"
            raise
        except BrokenPipeError:
            exit_code = 0
            success = True
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                try:
                    devnull = os.open(os.devnull, os.O_WRONLY)
                    os.dup2(devnull, sys.stdout.fileno())
                except Exception:
                    pass
            sys.exit(0)
        except Exception as e:
            success = False
            exit_code = 1
            error_type = type(e).__name__
            raise
        finally:
            duration_ms = int((time.time() - start_time) * 1000)
            props["duration_ms"] = duration_ms
            props["success"] = success
            props["exit_code"] = exit_code
            if error_type:
                props["error_type"] = error_type

            # Enrich with hook/runtime details if attached to args
            if hasattr(args, "_telemetry_extra") and isinstance(args._telemetry_extra, dict):
                props.update(args._telemetry_extra)

            try:
                from voicefi.telemetry import capture_event

                capture_event("cli_command", props)
            except Exception:
                pass


if __name__ == "__main__":
    main()
