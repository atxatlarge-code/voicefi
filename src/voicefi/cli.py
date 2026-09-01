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
from voicefi.config import load_config, save_config, get_default_config_path
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


def cmd_hook(args):
    """Handle AI agent lifecycle hook from stdin or manage hook configurations."""
    action = getattr(args, "action", None)
    if getattr(args, "disable", False):
        action = "disable"
    elif getattr(args, "enable", False):
        action = "enable"
    elif getattr(args, "status", False):
        action = "status"
    elif getattr(args, "remove", False):
        action = "remove"

    if action in ("disable", "off"):
        config = load_config(args.config)
        config.hooks.enabled = False
        save_config(config)
        print("🛑 VoiceFi hooks disabled globally (config.yaml: hooks.enabled = false).")
        print(
            "   Agent Stop hooks will immediately return without audio, microphone, or keyboard activity."
        )
        return

    if action in ("enable", "on"):
        config = load_config(args.config)
        config.hooks.enabled = True
        save_config(config)
        print("✅ VoiceFi hooks enabled globally (config.yaml: hooks.enabled = true).")
        return

    if action in ("remove", "uninstall"):
        from voicefi.integrations.antigravity import remove_antigravity_hook
        from voicefi.integrations.claude import remove_claude_hook
        from voicefi.integrations.codex import remove_codex_hook

        remove_antigravity_hook()
        remove_claude_hook()
        remove_codex_hook()
        print(
            "🗑️ VoiceFi hooks removed from Antigravity, Claude Code, and Codex configuration files."
        )
        return

    if action == "status":
        config = load_config(args.config)
        from voicefi.server import get_full_server_status

        st = get_full_server_status()
        hooks = st.get("hooks", {})
        print("\n🪝 VoiceFi Agent Lifecycle Hook Status")
        print("==================================================================")
        print(
            f"  • Global Hooks Enabled:    {'🟢 YES' if (config.enabled and config.hooks.enabled) else '🔴 NO (Disabled)'}"
        )
        print(
            f"  • VoiceFi Master Switch:   {'🟢 Enabled' if config.enabled else '⚪ Paused (enabled: false)'}"
        )
        print(
            f"  • Config Hooks Switch:     {'🟢 Enabled' if config.hooks.enabled else '🔴 Disabled (hooks.enabled: false)'}"
        )
        print("\n  📦 Agent Configurations:")
        print(
            f"    • Antigravity Hook Active: {'🟢 Enabled' if config.hooks.antigravity else '🔴 Disabled'}"
        )
        print(
            f"      - Auto Listen:           {'✅ Yes' if config.antigravity.auto_listen else '❌ No'}"
        )
        print(
            f"      - Read Summary Aloud:    {'✅ Yes' if config.antigravity.read_summary_aloud else '❌ No'}"
        )
        print(f"      - Installed In Plugin:   {hooks.get('antigravity') or '❌ Not installed'}")
        print(
            f"    • Claude Code Hook Active: {'🟢 Enabled' if config.hooks.claude else '🔴 Disabled'}"
        )
        print(
            f"      - Auto Listen:           {'✅ Yes' if config.claude.auto_listen else '❌ No'}"
        )
        print(
            f"      - Read Summary Aloud:    {'✅ Yes' if config.claude.read_summary_aloud else '❌ No'}"
        )
        print(f"      - Installed In Settings: {hooks.get('claude') or '❌ Not installed'}")
        print(
            f"    • Codex Hook Active:       {'🟢 Enabled' if getattr(config.hooks, 'codex', True) else '🔴 Disabled'}"
        )
        print(f"      - Installed In Settings: {hooks.get('codex') or '❌ Not installed'}")
        print("==================================================================\n")
        print(
            "💡 Commands: 'vifi hook disable' | 'vifi hook enable' | 'vifi hook remove' | 'vifi pause'\n"
        )
        return

    try:
        with open("/tmp/antigravity_hook_test.log", "a") as f:
            f.write(f"[{time.time()}] HOOK CALLED with args={args}\n")
    except Exception:
        pass
    config = load_config(args.config)
    target_agent = getattr(args, "agent", "antigravity").lower().strip()

    # Set base zero-PII hook telemetry early
    setattr(
        args,
        "_telemetry_extra",
        {
            "hook_agent": target_agent,
            "has_stdin_payload": False,
            "ipc_forwarded": False,
        },
    )

    # 1. Instant kill-switch guard: if VoiceFi is globally paused or hooks are disabled
    if not config.enabled or not getattr(config.hooks, "enabled", True):
        print(json.dumps({}))
        return

    # 2. Per-agent hook disable guard
    if target_agent in ("claude", "claude_code"):
        if not getattr(config.hooks, "claude", True) or not getattr(
            config.integrations, "claude_code", True
        ):
            print(json.dumps({}))
            return
        if not config.claude.auto_listen and not config.claude.read_summary_aloud:
            print(json.dumps({}))
            return
    elif target_agent in ("codex", "openai", "chatgpt"):
        if not getattr(config.hooks, "codex", True) or not getattr(
            config.integrations, "codex", True
        ):
            print(json.dumps({}))
            return
        codex_cfg = getattr(config, "codex", None)
        if codex_cfg and not codex_cfg.auto_listen and not codex_cfg.read_summary_aloud:
            print(json.dumps({}))
            return
    elif target_agent == "antigravity":
        if not getattr(config.hooks, "antigravity", True) or not getattr(
            config.integrations, "antigravity", True
        ):
            print(json.dumps({}))
            return
        if not config.antigravity.auto_listen and not config.antigravity.read_summary_aloud:
            print(json.dumps({}))
            return

    # Read hook payload: first check CLI arguments (e.g. Codex notify: turn-ended '{"type":...}')
    payload = {}
    extra = getattr(args, "extra_args", []) or []
    candidate_strings = []
    if action and action not in ("enable", "disable", "status", "remove", "uninstall", "on", "off"):
        candidate_strings.append(action)
    candidate_strings.extend(extra)
    candidate_strings.extend(sys.argv)

    for item in candidate_strings:
        if isinstance(item, str) and item.strip().startswith("{") and item.strip().endswith("}"):
            try:
                payload = json.loads(item.strip())
                break
            except Exception:
                pass

    # Read hook payload from stdin non-blockingly if not found in argv
    if not payload:
        try:
            if not sys.stdin.isatty():
                has_fileno = False
                try:
                    fd = sys.stdin.fileno()
                    has_fileno = True
                except Exception:
                    has_fileno = False

                if has_fileno:
                    import select

                    r, _, _ = select.select([fd], [], [], 0.3)
                    if r:
                        raw_bytes = b""
                        while True:
                            chunk = os.read(fd, 65536)
                            if not chunk:
                                break
                            raw_bytes += chunk
                            r2, _, _ = select.select([fd], [], [], 0.02)
                            if not r2:
                                break
                        text = raw_bytes.decode("utf-8").strip()
                        if text:
                            payload = json.loads(text)
                else:
                    raw_input = sys.stdin.readline()
                    if raw_input and raw_input.strip():
                        payload = json.loads(raw_input)
        except Exception:
            payload = {}

    if payload.get("agent"):
        target_agent = str(payload["agent"]).lower().strip()
    else:
        payload["agent"] = target_agent

    # Re-check per-agent guard with payload agent if specified
    if target_agent in ("claude", "claude_code"):
        if not getattr(config.hooks, "claude", True) or not getattr(
            config.integrations, "claude_code", True
        ):
            print(json.dumps({}))
            return
        if not config.claude.auto_listen and not config.claude.read_summary_aloud:
            print(json.dumps({}))
            return
    elif target_agent in ("codex", "openai", "chatgpt"):
        if not getattr(config.hooks, "codex", True) or not getattr(
            config.integrations, "codex", True
        ):
            print(json.dumps({}))
            return
        codex_cfg = getattr(config, "codex", None)
        if codex_cfg and not codex_cfg.auto_listen and not codex_cfg.read_summary_aloud:
            print(json.dumps({}))
            return
    elif target_agent == "antigravity":
        if not getattr(config.hooks, "antigravity", True) or not getattr(
            config.integrations, "antigravity", True
        ):
            print(json.dumps({}))
            return
        if not config.antigravity.auto_listen and not config.antigravity.read_summary_aloud:
            print(json.dumps({}))
            return

    # Set base zero-PII hook telemetry
    setattr(
        args,
        "_telemetry_extra",
        {
            "hook_agent": target_agent,
            "has_stdin_payload": bool(payload),
            "ipc_forwarded": False,
        },
    )

    # Fast IPC Forwarding: if VoiceFi background server is running,
    # forward hook event directly for instant (< 10ms) return to the agent
    from voicefi.integrations.server_client import forward_hook_to_server

    server_resp = forward_hook_to_server(payload, config)
    if server_resp and server_resp.get("status") == "handled":
        if hasattr(args, "_telemetry_extra") and isinstance(args._telemetry_extra, dict):
            args._telemetry_extra["ipc_forwarded"] = True
        print(json.dumps({}))
        return

    # Standalone fallback: execute in-process if background server is offline
    if target_agent in ("claude", "claude_code"):
        from voicefi.integrations.claude import handle_claude_stop_hook

        result = handle_claude_stop_hook(payload, config)
    elif target_agent in ("codex", "openai", "chatgpt"):
        from voicefi.integrations.codex import handle_codex_stop_hook

        result = handle_codex_stop_hook(payload, config)
    else:
        result = handle_antigravity_stop_hook(payload, config)

    # Output clean JSON object as required by hook contract
    out = result if isinstance(result, dict) else {}
    if "decision" in out and out["decision"] == "allow":
        out["decision"] = "approve"
    print(json.dumps(out))


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

            res = send_message_to_agent(engine=target_engine, text=text)
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

    print(f"🚀 Dispatching message to {target_engine.capitalize()}...")
    success = send_message_to_agent(
        conv_id=conv_id,
        text=text.strip(),
        sender_name=sender_name,
        title=title,
        target_engine=target_engine,
        from_conv_id=from_conv_id,
        from_engine=from_engine,
        include_envelope=include_envelope,
    )

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



def cmd_duel(args):
    """Run an acoustic voice banter / joke duel between Antigravity and Claude Code."""
    turns = getattr(args, "turns", 3) or 3
    live = getattr(args, "live", False)
    from voicefi.config import load_config
    from voicefi.tts import get_tts_engine
    import time

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
        agy_text, cld_text = rounds[i]
        print(f"🥊 Round {i + 1} — Antigravity (Ava):")
        print(f'   "{agy_text}"\n')
        tts_antigravity.speak(agy_text, block=True)
        time.sleep(0.4)

        if live:
            from voicefi.integrations.injector import send_message_to_agent

            send_message_to_agent(text=agy_text, target_engine="claude", include_envelope=True)

        print(f"🥊 Round {i + 1} — Claude Code (Steffan):")
        print(f'   "{cld_text}"\n')
        tts_claude.speak(cld_text, block=True)
        time.sleep(0.1)

        # Play corny SFX after punchlines!
        from voicefi.audio.sfx import play_sfx

        if i == 0:
            play_sfx("drum_smash", block=True)
        elif i == 1:
            play_sfx("honk", block=True)
        elif i == 2:
            play_sfx("applause", block=True)
        time.sleep(0.4)

    print("✨ Duel complete! Both agents delivered their punchlines.\n")


def cmd_sfx(args):
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


def cmd_fx(args):
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


def cmd_reel(args):
    """Compile multi-format social video reels from audio and slides."""
    import subprocess
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


def cmd_trim(args):
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


def cmd_tray(args):
    """Launch macOS menu bar tray companion."""
    from voicefi.ui.tray import run_tray

    print("🚀 Launching VoiceFi menu bar tray...")
    run_tray()


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
        if prompt and len(prompt.strip()) >= 3:
            norm = PhoneticNormalizer.normalize(prompt.strip())
            print(f'🚀 Prompt: "{norm}"')
            print("📤 Dispatching directly to Antigravity via agentapi IPC...")
            res = send_message_to_antigravity(
                text=norm, sender_name=f"{config.user_name} (Hey Viv)", title="Prompt via Hey Viv"
            )
            if res.success:
                print(f"✅ Delivered to Antigravity conversation ({res.delivery_type.upper()})")
                if config.audio_cues.enabled:
                    play_chime(config.audio_cues.sent_chime, block=False)
            else:
                print(f"⚠️ Dispatch notice: {res.error}")
        else:
            print("🎙️ Wake word detected without prompt -> Listening for command...")
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
                    norm = PhoneticNormalizer.normalize(text.strip())
                    print(f'🚀 Spoken Prompt: "{norm}"')
                    print("📤 Dispatching directly to Antigravity via agentapi IPC...")
                    res = send_message_to_antigravity(
                        text=norm,
                        sender_name=f"{config.user_name} (Hey Viv)",
                        title="Prompt via Hey Viv",
                    )
                    if res.success:
                        print(
                            f"✅ Delivered to Antigravity conversation ({res.delivery_type.upper()})"
                        )
                        if config.audio_cues.enabled:
                            play_chime(config.audio_cues.sent_chime, block=False)
                    else:
                        print(f"⚠️ Dispatch notice: {res.error}")
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


def cmd_clean(args):
    """Clean stale Python bytecode, caches, temporary files, and optionally stop running servers."""
    from voicefi.server import clean_caches, stop_all_voicefi_servers, link_dev_environment

    clean_all = getattr(args, "all", False)
    clean_dev = getattr(args, "dev", False)
    purge_servers = (
        clean_all or clean_dev or getattr(args, "servers", False) or getattr(args, "daemons", False)
    )

    print("\n🧹 VoiceFi Cache & State Cleaner")
    print("------------------------------------------------------------------")
    if purge_servers:
        print("🛑 Stopping all active VoiceFi servers and releasing locks/ports...")
        d_res = stop_all_voicefi_servers()
        if d_res.get("stopped_pids"):
            print(f"  • Stopped PIDs: {d_res['stopped_pids']}")
        if d_res.get("port_freed"):
            print("  • Port 5141 freed.")

    res = clean_caches(
        clean_pycache=True,
        clean_tmp_state=True,
        clean_update_cache=True,
        purge_servers=False,
    )
    print(f"✅ Removed {res['cleaned_pycache_count']} __pycache__ directories and .pyc files.")
    print(f"✅ Removed {res['cleaned_tmp_count']} temporary /tmp/voicefi* state & lock files.")
    if res["cleaned_update_cache"]:
        print("✅ Flushed update check cache (~/.voicefi/.update_check.json).")

    if clean_dev:
        link_res = link_dev_environment()
        print(f"🔗 Linked agent hooks to development binary: {link_res['target_binary']}")

    print("------------------------------------------------------------------")
    print("✨ Environment is clean and consistent.\n")
    print("💡 Next Steps:")
    print("  • Check server health & port:      vifi status")
    print("  • Start live development mode:     vifi dev")
    print("  • Launch persistent Dynamic HUD:   vifi autostart  (or 'vifi tray')")
    print("  • Interactive HUD Debug Studio:    vifi hud debug")
    print("  • Test silent voice connection:    vifi ping")
    print("  • Run acoustic diagnostic suite:   vifi troubleshoot\n")


def cmd_server(args):
    """Manage VoiceFi background server, LaunchAgents, and port listeners."""
    from voicefi.server import (
        get_full_server_status,
        stop_all_voicefi_servers,
        clean_caches,
    )

    action = (
        getattr(args, "server_action", None)
        or getattr(args, "daemon_action", None)
        or getattr(args, "command", "status")
    )

    if action == "status":
        st = get_full_server_status()
        la = st["launchagent"]
        port = st.get("port_5141") or st.get("port_8765") or st.get("port_listener")
        procs = st["running_processes"]
        hooks = st["hooks"]

        print("\n📊 VoiceFi Server & Runtime Status")
        print("==================================================================")
        print(
            f"  • LaunchAgent (launchd):  {'🟢 Loaded' if la['is_loaded'] else '⚪ Not Loaded'}"
            + (f" (PID {la['pid']})" if la["pid"] else "")
        )
        print(
            f"  • LaunchAgent Plist:      {'✅ Present' if la['plist_exists'] else '❌ Missing'} ({la['plist_path']})"
        )
        print(
            "  • Port 5141 Owner:        "
            + (f"🟢 PID {port['pid']} ({port['command_name']})" if port else "⚪ Port Free")
        )
        print(f"  • Tray Lock File:         {'🔒 Locked' if st['lock_active'] else '🔓 Free'}")
        ww = st.get("wakeword", {})
        ww_enabled = ww.get("enabled", True)
        ww_phrase = ww.get("phrase", "Hey Viv")
        print(
            f"  • Wake Word Listener:     {'🟢 Enabled' if ww_enabled else '⚪ Disabled'} ('{ww_phrase}')"
        )

        print("\n  📦 Running VoiceFi Processes:")
        if procs:
            for p in procs:
                print(f"    • PID {p['pid']} (PPID {p['ppid']}): {p['command'][:90]}")
        else:
            print("    • None (no standalone background processes)")

        print("\n  🔌 AI Agent Hook Bindings:")
        print(f"    • Antigravity Hook:     {hooks.get('antigravity') or '❌ Not installed'}")
        print(f"    • Claude Code Hook:     {hooks.get('claude') or '❌ Not installed'}")
        print(f"    • Current Python Exec:  {st['python_executable']}")
        print("==================================================================\n")
        print(
            "💡 Commands: 'vifi status' | 'vifi stop' | 'vifi restart' | 'vifi server' | 'vifi dev'\n"
        )

    elif action in ("stop", "kill"):
        print("\n🛑 Stopping all VoiceFi background servers, processes, and releasing ports...")
        res = stop_all_voicefi_servers()
        if res.get("stopped_pids"):
            print(f"✅ Terminated processes: {res['stopped_pids']}")
        if res.get("port_freed"):
            print("✅ Port 5141 freed.")
        print("✅ Background LaunchAgent disabled and all locks cleared.\n")

    elif action in ("restart", "reload"):
        print("\n🔄 Restarting VoiceFi background server...")
        stop_all_voicefi_servers()
        clean_caches()
        cmd_autostart(args)
        print("✅ VoiceFi background server restarted.\n")

    elif action in ("start", "autostart"):
        cmd_autostart(args)

    else:
        print(f"Unknown server action: {action}. Use: status, stop, restart, start.")


# Backwards compatibility alias
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
    config = load_config(args.config)
    config.enabled = False
    save_config(config)
    print("⏸️  VoiceFi paused globally. Audio hooks and auto-listen are temporarily disabled.")


def cmd_resume(args):
    """Resume VoiceFi audio hooks and active turn-handoffs globally."""
    config = load_config(args.config)
    config.enabled = True
    save_config(config)
    print("▶️  VoiceFi resumed globally. Audio hooks and auto-listen are active.")


def cmd_autostart(args):
    """Register macOS LaunchAgent so VoiceFi menu bar tray stays on and runs at login."""
    import shutil
    import subprocess
    import os

    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents_dir / "com.voicefi.menubar.plist"
    ws_candidates = [
        Path.cwd() / ".venv" / "bin" / "voicefi",
        Path.cwd() / "venv" / "bin" / "voicefi",
        Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "voicefi",
        Path(sys.executable).parent / "voicefi",
    ]
    bin_path = None
    for cand in ws_candidates:
        if cand.is_file() and os.access(str(cand), os.X_OK):
            bin_path = str(cand)
            break
    if not bin_path:
        bin_path = shutil.which("voicefi") or "voicefi"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.voicefi.menubar</string>
    <key>ProgramArguments</key>
    <array>
        <string>{bin_path}</string>
        <string>tray</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/voicefi.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/voicefi.err</string>
</dict>
</plist>
"""
    with open(plist_path, "w", encoding="utf-8") as f:
        f.write(plist_content)

    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/com.voicefi.menubar"],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        ["launchctl", "enable", f"gui/{uid}/com.voicefi.menubar"],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )

    res = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    if res.returncode != 0:
        subprocess.run(
            ["launchctl", "load", "-w", str(plist_path)],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )

    print("✅ VoiceFi menu bar companion registered to start automatically at login.")
    print(f"📌 Plist installed at: {plist_path}")


def cmd_stop_autostart(args):
    """Unload and remove macOS LaunchAgent."""
    import subprocess
    import os

    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.voicefi.menubar.plist"
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/com.voicefi.menubar"],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    if plist_path.is_file():
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        plist_path.unlink(missing_ok=True)
        print("🛑 VoiceFi menu bar companion autostart removed.")
    else:
        print("ℹ️ No active autostart service found.")


from voicefi.tts.catalog import (
    CURATED_PERSONAS,
    get_curated_personas,
    find_persona,
    list_all_available_voices,
)
from voicefi.tts.cloning import VoiceCloneManager, TRAINING_PROMPTS
from voicefi.feedback import submit_feedback, list_feedback, collect_system_diagnostics


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


def cmd_companion(args):
    """Launch Web & Mobile Voice Companion server with QR pairing and PWA."""
    from voicefi.companion.server import run_companion_server

    config = load_config(args.config)
    port = getattr(args, "port", 5141)
    host = getattr(args, "host", "0.0.0.0")
    print_qr = not getattr(args, "no_qr", False)
    open_browser = getattr(args, "open", False)
    tunnel = getattr(args, "tunnel", False)
    run_companion_server(
        port=port,
        host=host,
        print_qr=print_qr,
        open_browser=open_browser,
        tunnel=tunnel,
        config=config,
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


def cmd_troubleshoot(args):
    """Run interactive or automated Voice & Audio troubleshooting and test suite."""
    import time
    from voicefi.troubleshoot import AudioTroubleshooter, TEST_PHRASES

    config = load_config(getattr(args, "config", None))
    troubleshooter = AudioTroubleshooter(config)

    # 1. Check if quick fix requested
    fix_type = getattr(args, "fix", None)
    if fix_type:
        print(f"\n🔧 Applying auto-fix: '{fix_type}'...")
        res = troubleshooter.apply_fix(fix_type)
        if res.get("success"):
            print(f"✅ {res['message']}\n")
        else:
            print(f"❌ {res['message']}\n")
        return

    # 2. Check if JSON requested
    if getattr(args, "json", False):
        report = troubleshooter.run_full_troubleshoot()
        print(json.dumps(report, indent=2))
        return

    # 3. Check if Mic Loopback only
    if getattr(args, "mic", False) or getattr(args, "loopback", False):
        print("\n🎙️ Starting 3-Second Microphone Loopback Test...")
        print("🔔 Ready... Recording in 1 second!")
        time.sleep(1.0)
        print("🔴 RECORDING (3.0s) — Speak a sentence into your microphone!")
        res = troubleshooter.test_microphone_loopback(duration_seconds=3.0, play_back=True)
        if res.success:
            print(f"✅ Captured {res.duration_s}s audio at {res.sample_rate}Hz.")
            print(
                f"📊 RMS Energy: {res.rms_energy:.4f}, Peak: {res.peak_amplitude:.3f}, SNR: {res.snr_db:.1f} dB"
            )
            status = "Speech detected ✅" if res.speech_detected else "Quiet / Low audio ⚠️"
            print(f"🎙️ Detection: {status}")
            print("🔊 Playing back over speakers now...")
            time.sleep(3.2)
            print("✨ Test complete.\n")
        else:
            print(f"❌ Mic test failed: {res.error}\n")
        return

    # 4. Check if Benchmark only
    if getattr(args, "benchmark", False):
        print("\n⚡ Benchmarking Voice Personas Latency...")
        benchmarks = troubleshooter.benchmark_all_curated_voices()
        for b in benchmarks:
            status_icon = "🟢" if b["status"] == "online" else "🔴"
            lat_str = f"{b['latency_ms']} ms" if b["status"] == "online" else "Error"
            print(
                f"  • {status_icon} {b['name']:<12} [{b['provider']}]: {lat_str} ({b['recommended_role']})"
            )
        print()
        return

    # 5. Full automated diagnostics & interactive walkthrough
    print("\n🔍 VoiceFi Audio & Voice Diagnostic Suite")
    print("=" * 60)

    # Hardware Check
    hw = troubleshooter.get_hardware_diagnostics()
    vad_res = troubleshooter.test_vad()
    vad_detail = ""
    if vad_res.get("status") == "ready":
        d = vad_res.get("details", {})
        vad_detail = f" (latency: {d.get('avg_latency_ms', 0.1):.3f}ms, ~{d.get('throughput_frames_per_sec', 0):.0f} fps)"
    print("\n🖥️  [1/4] Audio Hardware & System:")
    print(f"  • Platform:      {hw['os_platform']} {hw['os_release']} ({hw['machine_arch']})")
    print(f"  • Default Mic:   {hw['default_input'] or 'None'}")
    print(f"  • Default Spkr:  {hw['default_output'] or 'None'}")
    print(f"  • VAD Engine:    {vad_res.get('engine', 'silero').upper()}{vad_detail}")
    print(
        f"  • Active Engine: {hw['tts_provider']} ({hw['tts_voice']}) at {hw['tts_rate']} WPM ({hw['tts_rate_pct']})"
    )

    # Speaker Output Chime Test
    print("\n🔔 [2/4] Speaker Output & Alert System:")
    print("  Playing test chime over default output device...")
    spk_res = troubleshooter.test_speaker_output("start", block=True)
    if spk_res["success"]:
        print(f"  ✅ Speaker chime played successfully ({spk_res['latency_ms']} ms latency).")
    else:
        print(f"  ⚠️ Speaker chime failed: {spk_res['error']}")

    # Active Voice Test
    print("\n🔊 [3/4] Active Voice Persona Audition:")
    v_res = troubleshooter.test_voice(
        voice_name_or_id=hw["tts_voice"],
        text="Voice test nominal. Audio output and latency are healthy.",
        provider=hw["tts_provider"],
        rate=hw["tts_rate"],
        block=True,
        show_hud=getattr(args, "hud", False),
    )
    if v_res.success:
        print("  ✅ Active voice synthesized and played aloud.")
        print(f"  ⚡ Latency (TTFB): {v_res.latency_ms} ms (Duration: {v_res.duration_s}s)")
    else:
        print(f"  ⚠️ Voice playback error: {v_res.error}")

    # Interactive Mic Test if requested
    if getattr(args, "interactive", False):
        print("\n🎙️ [4/4] Interactive Microphone Test:")
        try:
            input("  Press Enter to begin 3-second mic recording (or Ctrl+C to skip)... ")
            print("  🔴 RECORDING NOW (3s) — Speak a sentence clearly!")
            mic_res = troubleshooter.test_microphone_loopback(duration_seconds=3.0, play_back=True)
            if mic_res.success:
                print(
                    f"  ✅ Recorded {mic_res.duration_s}s. RMS Energy: {mic_res.rms_energy:.4f}, SNR: {mic_res.snr_db:.1f} dB"
                )
                print("  🔊 Playing back your voice over speakers...")
                time.sleep(3.2)
            else:
                print(f"  ⚠️ Microphone loopback failed: {mic_res.error}")
        except (KeyboardInterrupt, EOFError):
            print("\n  Skipped mic loopback.")
    else:
        print("\n🎙️ [4/4] Microphone Diagnostics:")
        print("  Tip: Run 'vg feedback-loop' or 'vg hearing-test' to test full roundtrip audio.")

    # Summary Recommendations
    full_report = troubleshooter.run_full_troubleshoot()
    recs = full_report.get("recommendations", [])
    print("\n📋 Troubleshooting Summary & Recommendations:")
    if recs:
        for r in recs:
            print(f"  💡 {r}")
    else:
        print("  ✨ All voice, audio, and hardware subsystems are running at peak performance!")

    print(
        "\n🌐 Web Control Panel with live interactive tester: 'vg panel' (http://localhost:5141)\n"
    )


def cmd_hearing_test(args):
    """Run acoustic hearing test (speak aloud -> listen via mic -> STT verification)."""
    args.voice_action = "test"
    args.hearing = True
    cmd_voice(args)


def cmd_feedback_loop(args):
    """Manage ProActive Listening setting (on/off/status) or run acoustic loop test."""
    voice_arg = getattr(args, "voice", None)
    action_arg = getattr(args, "action", None)
    target = (action_arg or voice_arg or "").lower()

    if target in ("on", "enable", "true", "1"):
        cfg = load_config(getattr(args, "config", None))
        cfg.proactive.feedback_loop.enabled = True
        cfg.antigravity.auto_listen = True
        save_config(cfg)
        print("\n⚡ ProActive Listening: 🟢 ENABLED")
        print(
            "💡 The microphone will automatically open for your conversational turn after the agent speaks.\n"
        )
        return
    elif target in ("off", "disable", "false", "0"):
        cfg = load_config(getattr(args, "config", None))
        cfg.proactive.feedback_loop.enabled = False
        cfg.antigravity.auto_listen = False
        save_config(cfg)
        print("\n⚡ ProActive Listening: ⚪ DISABLED")
        print("💡 Speech synthesis only. Use Ctrl+R or Ctrl+T to speak on-demand.\n")
        return
    elif target == "status":
        cfg = load_config(getattr(args, "config", None))
        status_str = "🟢 ENABLED" if cfg.proactive.feedback_loop.enabled else "⚪ DISABLED"
        print(f"\n⚡ ProActive Listening Status: {status_str}")
        print(
            f"  • Turn Handoff: {'✅ Active' if cfg.proactive.feedback_loop.enabled else '⚪ Inactive'}"
        )
        print(f"  • Chime Cue: {'✅ On' if cfg.proactive.feedback_loop.chime_cue else '❌ Off'}")
        print(f"  • Turn Timeout: {cfg.proactive.feedback_loop.timeout_seconds}s")
        print(
            f"  • Typing Guard: {'✅ Active' if cfg.proactive.feedback_loop.cancel_on_typing else '❌ Inactive'}"
        )
        print(
            f"  • Multi-Channel Routing: {'✅ Active (Claude, Slack, Linear)' if cfg.proactive.intent_routing.enabled else '❌ Inactive'}\n"
        )
        return

    # Otherwise run acoustic roundtrip verification test
    args.voice_action = "test"
    args.feedback_loop = True
    cmd_voice(args)


def cmd_loopback(args):
    """Alias for cmd_feedback_loop."""
    cmd_feedback_loop(args)


def cmd_barge_in(args):
    """Run live interactive barge-in & Silero VAD interruption test."""
    from voicefi.config import load_config
    from voicefi.audio.recorder import AudioRecorder
    from voicefi.tts import get_tts_engine, stop_all_speech, find_persona
    from voicefi.audio.device import get_audio_device_profile
    from voicefi.stt.whisper_local import WhisperLocalSTT
    import threading

    config = load_config()
    prof = get_audio_device_profile()

    target_voice = getattr(args, "voice", None) or config.tts.voice
    persona = find_persona(target_voice)
    resolved_voice = persona.id if persona else target_voice

    default_test_phrase = (
        "This is a live acoustic barge-in test with Silero VAD. "
        "I will keep speaking aloud for several seconds so you can test interrupting me. "
        "Whenever you are ready, speak firmly into your microphone now to cut me off!"
    )
    test_phrase = getattr(args, "text", None) or default_test_phrase

    print("\n" + "=" * 65)
    print("⚡ VoiceFi Active Voice Barge-In & Silero VAD Live Test")
    print("=" * 65)
    print(f"🎙️  Microphone:      {prof.get('default_input') or 'Default'}")
    print(f"🔊 Output Device:   {prof.get('default_output') or 'Default'}")
    print(
        f"🎧 Device Profile:  {'Headphones / AirPods ✅' if prof.get('is_headphones_active') else 'Built-in Laptop Speakers (Acoustic Safe Mode)'}"
    )
    print(
        f"🧠 VAD Engine:      {getattr(config.vad, 'engine', 'silero').upper()} (Threshold: {getattr(config.vad, 'speech_threshold', 0.5)})"
    )
    print("-" * 65)
    print("👉 HOW THIS TEST WORKS:")
    print("   1. VoiceFi will speak aloud through your speakers/headphones.")
    print("   2. While it speaks, Silero VAD actively monitors your microphone.")
    print("   3. Speak firmly into your microphone (e.g. 'Wait, stop right now!').")
    print("   4. Agent speech will INSTANTLY cut off and transcribe your interruption.")
    print("-" * 65)

    recorder = AudioRecorder(
        sample_rate=16000,
        energy_threshold=config.vad.energy_threshold,
        silence_duration=0.8,
        max_record_seconds=15.0,
        barge_in=True,
        barge_in_sensitivity=config.vad.barge_in_sensitivity,
        vad_engine=getattr(config.vad, "engine", "auto"),
        speech_threshold=getattr(config.vad, "speech_threshold", 0.5),
    )

    barge_in_triggered = False
    speech_detected = False

    def on_barge():
        nonlocal barge_in_triggered
        barge_in_triggered = True
        print(
            "\n⚡ [BARGE-IN TRIGGERED] Silero neural VAD confirmed user speech -> Audio playback terminated!"
        )

    def on_speech_start():
        nonlocal speech_detected
        speech_detected = True
        print("🎙️ [SPEECH ONSET] Recording user interruption prompt...")

    def speak_in_background():
        try:
            tts = get_tts_engine(config, agent_name="BargeInTest", voice_override=resolved_voice)
            tts.speak(test_phrase, block=True)
        except Exception as e:
            print(f"[TTS] Playback notice: {e}")

    print("\n🔊 Starting agent speech playback...")
    tts_thread = threading.Thread(target=speak_in_background, daemon=True)
    tts_thread.start()

    time.sleep(0.3)
    print("🔴 Live mic monitoring active with Silero VAD (speak now to interrupt)...\n")

    audio_data, wav_path = recorder.record_speech_auto(
        on_barge_in=on_barge,
        on_speech_start=on_speech_start,
    )

    stop_all_speech()

    print("\n" + "=" * 65)
    print("📊 Test Summary:")
    if barge_in_triggered:
        print("✅ Barge-In Status:   SUCCESSFULLY TRIGGERED & INTERRUPTED")
    else:
        print("ℹ️  Barge-In Status:   Not triggered (agent completed phrase without interruption)")

    dur = len(audio_data) / 16000.0
    print(f"⏱️  Captured Audio:   {dur:.2f} seconds")

    if dur > 0.3 and speech_detected:
        print("📝 Transcribing user speech with Whisper...")
        try:
            stt = WhisperLocalSTT()
            transcript = stt.transcribe(wav_path)
            if transcript:
                print(f'💬 You said:         "{transcript}"')
        except Exception as ex:
            print(f"⚠️  Transcription note: {ex}")

    if wav_path.exists():
        wav_path.unlink(missing_ok=True)

    print("=" * 65 + "\n")


def cmd_ping(args):
    """Silently test voice connection, latency, speed, and health."""
    args.voice_action = "ping"
    cmd_voice(args)


def run_silent_voice_ping(args, config):
    """Execute silent voice connection, latency, speed, and health diagnostics."""
    import json
    from voicefi.troubleshoot import AudioTroubleshooter, TEST_PHRASES
    from voicefi.tts import CURATED_PERSONAS, find_persona

    troubleshooter = AudioTroubleshooter(config)
    as_json = getattr(args, "json", False)
    all_personas = getattr(args, "all", False)
    sample_text = (
        getattr(args, "text", None) or "VoiceFi silent neural voice connection and speed test."
    )
    count = getattr(args, "count", 1) or 1
    provider = getattr(args, "provider", None)
    rate = getattr(args, "rate", None)

    if all_personas:
        if not as_json:
            print("\n🌐 VoiceFi Neural Voice Connection & Speed Benchmark (Silent)\n")
            print(
                f"{'Persona':<14} {'ID / Voice':<28} {'Provider':<10} {'Status':<18} {'Latency':<10} {'Speed':<16} {'Payload'}"
            )
            print("-" * 108)

        results = []
        for p in CURATED_PERSONAS:
            res = troubleshooter.ping_voice_silently(
                voice_name_or_id=p.id,
                text=sample_text,
                provider=p.provider,
            )
            results.append(res.to_dict())
            if not as_json:
                status_icon = "🟢" if res.success else "🔴"
                if res.status == "online":
                    status_desc = "Online (200)"
                elif res.status == "offline_native":
                    status_desc = "Offline Native"
                elif res.status == "rate_limited":
                    status_desc = "Throttled (429)"
                else:
                    status_desc = "Error"
                status_col = f"{status_icon} {status_desc}"
                lat_str = f"{res.latency_ms:.1f} ms" if res.success else "Failed"
                speed_str = f"{res.chars_per_sec:.1f} chars/s" if res.success else "N/A"
                size_str = f"{res.audio_bytes / 1024.0:.1f} KB" if res.success else "0 KB"
                print(
                    f"{p.name:<14} {p.id:<28} {p.provider:<10} {status_col:<18} {lat_str:<10} {speed_str:<16} {size_str}"
                )

        if as_json:
            print(json.dumps({"status": "success", "benchmark": results}, indent=2))
        else:
            print("-" * 108)
            successful_lats = [r["latency_ms"] for r in results if r["success"]]
            avg_lat = sum(successful_lats) / max(len(successful_lats), 1)
            print(
                f"✨ Benchmark complete. Curated voices tested: {len(results)} | Avg Latency: {avg_lat:.1f} ms | Zero audio emitted.\n"
            )
        return

    # Single voice or target voice
    target_voice = getattr(args, "voice", None) or config.tts.voice
    persona = find_persona(target_voice)
    resolved_voice = persona.id if persona else target_voice
    resolved_name = persona.name if persona else target_voice
    resolved_provider = provider or (persona.provider if persona else config.tts.provider)

    if count > 1:
        stats = troubleshooter.ping_multiple_silently(
            voice_name_or_id=resolved_voice,
            count=count,
            text=sample_text,
            provider=resolved_provider,
            rate=rate,
        )
        if as_json:
            print(json.dumps(stats, indent=2))
            return

        print("\n🌐 VoiceFi Silent Connection & Speed Test")
        print(f"🎙️ Target: {resolved_name} (`{resolved_voice}`) | Provider: {resolved_provider}\n")
        for idx, p in enumerate(stats["pings"], start=1):
            s_icon = "🟢" if p["success"] else "🔴"
            s_desc = (
                "200 OK"
                if p["status"] == "online"
                else (
                    "Offline Native"
                    if p["status"] == "offline_native"
                    else ("429 Rate Limit" if p["status"] == "rate_limited" else "Error")
                )
            )
            size_kb = p["audio_bytes"] / 1024.0
            print(
                f"  • Ping {idx}: {s_icon} {s_desc:<14} — Latency: {p['latency_ms']:>6.1f} ms | Speed: {p['chars_per_sec']:>6.1f} chars/s ({p['words_per_min']:>5.0f} WPM) | Size: {size_kb:.1f} KB"
            )

        print(f"\n📊 Summary Statistics ({count} pings):")
        print(
            f"  • Success Rate:    {stats['success_rate_pct']}% ({stats['success_count']}/{count})"
        )
        if stats["success_count"] > 0:
            print(
                f"  • Latency (TTFB):  min = {stats['min_latency_ms']} ms | avg = {stats['avg_latency_ms']} ms | max = {stats['max_latency_ms']} ms (jitter: ±{stats['jitter_ms']} ms)"
            )
            print(f"  • Avg Throughput:  {stats['avg_chars_per_sec']} chars/s")
            print("  • Connection:      🟢 Operational & responsive (zero speaker sound)\n")
        else:
            print(f"  • Errors:          {stats.get('errors')}\n")
        return

    # Single ping
    res = troubleshooter.ping_voice_silently(
        voice_name_or_id=resolved_voice,
        text=sample_text,
        provider=resolved_provider,
        rate=rate,
    )
    if as_json:
        print(json.dumps(res.to_dict(), indent=2))
        return

    print("\n🌐 VoiceFi Silent Connection & Speed Test")
    print(f"🎙️ Voice: {resolved_name} (`{resolved_voice}`) | Provider: {resolved_provider}")
    if res.success:
        status_icon = "🟢"
        status_label = (
            "200 OK (Online)" if res.status == "online" else "Offline Native (macOS Apple Silicon)"
        )
        size_kb = res.audio_bytes / 1024.0
        print(f"  • Status:      {status_icon} {status_label}")
        print(f"  • Latency:     {res.latency_ms:.1f} ms roundtrip synthesis")
        print(
            f"  • Speed:       {res.chars_per_sec:.1f} chars/sec (~{res.words_per_min:.0f} WPM equivalent)"
        )
        print(f"  • Audio Size:  {size_kb:.1f} KB ({res.audio_bytes} bytes)")
        print("  • Audio Check: ✅ Silent synthesis verified (no speaker playback)\n")
    else:
        status_label = (
            "429 Too Many Requests (Rate Limited)"
            if res.status == "rate_limited"
            else f"Failed ({res.error})"
        )
        print(f"  • Status:      🔴 {status_label}")
        print(f"  • Latency:     {res.latency_ms:.1f} ms")
        print(f"  • Error:       {res.error}\n")


def cmd_download_ava(args):
    """Guide user through downloading & configuring Apple's Ava (Premium) for 0ms offline speech."""
    from voicefi.tts.offline import run_download_ava_workflow

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


def cmd_voice(args):
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

    if subaction == "train":
        args.clone_action = "record"
        cmd_clone(args)
        return

    if subaction == "panel":
        cmd_panel(args)
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
                print(f"  • {pk:<16} -> {pprof.voice:<26} {p_disp} [{pprof.provider or config.tts.provider}]")

        if show_all:
            print("\n📋 Full Voice Catalog:")
            all_voices = list_all_available_voices(provider=provider)
            for v in all_voices:
                if not v.get("curated") and not v.get("cloned"):
                    print(f"  • {v['id']} ({v['provider']}, {v['locale']}) - {v['style']}")
        print()

    elif subaction == "test":
        import time
        from voicefi.troubleshoot import AudioTroubleshooter, TEST_PHRASES

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
                    f" | {b['chars_per_sec']:.1f} chars/s" if b.get("chars_per_sec", 0) > 0 else ""
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
                            int(round(200 * (num / 100.0))) if 0 < num <= 120 else int(round(num)),
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
                import json

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
                    import json

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
            import time

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

        # Case A: Only 1 positional argument passed (e.g. 'vifi voice set viv' or 'vifi voice set en-US-AvaNeural')
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
            # Case B: 2 positional arguments passed (e.g. 'vifi voice set antigravity viv' or reversed 'vifi voice set viv antigravity')
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
                            int(round(200 * (num / 100.0))) if 0 < num <= 120 else int(round(num)),
                            350,
                        ),
                        80,
                    )
                except ValueError:
                    resolved_rate = None

        from voicefi.config import AgentVoiceProfile

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
        and (
            action.endswith("x")
            or action.endswith("%")
            or action.replace(".", "", 1).isdigit()
        )
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
        print(f"\n⚡ \033[1;32mSpeed Talking set to {matched_preset.upper()} ({mult}x / {wpm} WPM)\033[0m")
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
            getattr(args, "preset_or_multiplier", None)
            or getattr(args, "preset", None)
            or 1.75
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

        with tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False
        ) as tf_in, tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf_out:
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
            ("breezy", 1.25, "1.25x Breezy pace: effortless acceleration with zero cognitive load."),
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
            print(f"  • \033[1;36m{name.upper()} ({mult}x / {wpm} WPM)\033[0m: \"{phrase}\"")
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
    print(
        f"  • Status:           {'🟢 \033[1;32mACTIVE\033[0m' if config.speed_talking.enabled else '⚪ \033[2mDisabled\033[0m (1.0x baseline)'}"
    )
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
        print("📁 Saved to ~/.voicefi/feedback.jsonl")


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

                    subprocess.run(
                        ["pbcopy"], input=synthesis.to_markdown().encode("utf-8"), check=True
                    )
                    print("📋 Copied synthesized plan to clipboard!")
                except Exception:
                    pass

    elif action in ("synth", "synthesize", "clean"):
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

                subprocess.run(
                    ["pbcopy"], input=synthesis.to_markdown().encode("utf-8"), check=True
                )
                print("📋 Copied synthesized plan to clipboard!")
            except Exception:
                pass

    elif action == "list":
        limit = getattr(args, "limit", 20)
        memos = store.list_memos(limit=limit)
        if not memos:
            print("📭 No voice memos recorded yet.")
            print(
                "👉 Run 'vg memo record' or 'vg memo record --duration 3m' to capture a brain dump!"
            )
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
            if hasattr(synthesis, "architectural_diagram") and synthesis.architectural_diagram:
                print("```mermaid")
                print(synthesis.architectural_diagram.mermaid_code)
                print("```")
            else:
                print("No architectural diagram in this memo.")
        elif getattr(args, "checklist_only", False) and synthesis:
            if hasattr(synthesis, "pr_checklist") and synthesis.pr_checklist:
                for task in synthesis.pr_checklist.core_tasks:
                    print(f"- [ ] {task}")
                for test in synthesis.pr_checklist.testing_and_verification:
                    print(f"- [ ] {test}")
                for edge in synthesis.pr_checklist.edge_cases_and_security:
                    print(f"- [ ] {edge}")
            else:
                print("No PR checklist in this memo.")
        elif synthesis:
            print(synthesis.to_markdown())
        else:
            print(f"# Voice Memo: {recording.title} (`{recording.id}`)")
            print(
                f"Duration: {int(recording.duration_seconds) // 60:02d}:{int(recording.duration_seconds) % 60:02d} | Words: {recording.word_count}"
            )
            print("\n## Raw Transcript")
            print(recording.raw_transcript)
            print(
                "\n💡 Run 'vg memo synth "
                + recording.id
                + "' to generate structured implementation plan."
            )

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


def cmd_tier(args):
    """Display active tier, 14-day free trial countdown, and pricing details."""
    config = load_config(getattr(args, "config", None))
    FeatureGate.ensure_trial_started(config)
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

    if action in ("activate", "set", "apply") or key:
        raw_key = (key or (args.key_args[0] if getattr(args, "key_args", None) else "")).strip()
        if not raw_key:
            print(
                "❌ Error: Please provide a valid license key (e.g. vifi license activate VF1-PRO-PERP-USER.<SIGNATURE>)"
            )
            return

        validation = FeatureGate.verify_key(raw_key)
        if not validation["is_valid"]:
            if validation.get("is_expired"):
                print(f"\n❌ Error: This license key expired on {validation.get('expires_at')}.")
            else:
                print(f"\n❌ Error: {validation.get('error', 'Invalid license key signature.')}")
                print("   Please check your license key or visit https://voicefi.org#pricing\n")
            return

        config = load_config(getattr(args, "config", None))
        config.license_key = raw_key
        config.tier = validation.get("tier", "pro")
        save_config(config)

        expires_desc = validation.get("expires_at", "Perpetual")
        tag_desc = f" ({validation['tag']})" if validation.get("tag") else ""
        masked_key = (
            (raw_key[:12] + "..." + raw_key[-6:])
            if len(raw_key) >= 20
            else (raw_key[:4] + "****")
        )

        print("\n🎉 VoiceFi Pro License Successfully Activated!")
        print(f"🔑 License Key: {masked_key}")
        print(f"⚡ Tier:        {config.tier.capitalize()}{tag_desc} · {expires_desc}")
        print("🚀 All Pro features (Streaming STT, 20+ Neural Voices, Cloud Relay) are unlocked!")
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
        print("🟢 VoiceFi Dynamic Island HUD opened and visible.")
        print("📌 Resting pill is anchored at the top-right below Chrome's tab bar.")
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
            "🎯 VoiceFi Dynamic Island HUD position reset to default top-right anchor below Chrome tab bar.\n"
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
            print("  [R]     Reset Position to Top-Right (20px Margin)")
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


def cmd_spark(args):
    """Run Gemini Spark agent runner with voice IPC bridge and turn-end hooks."""
    import asyncio
    from voicefi.integrations.spark import GeminiSparkRunner

    config = load_config(getattr(args, "config", None))
    sock_path = getattr(args, "socket", None) or config.ipc.socket_path
    persona = getattr(args, "persona", None) or getattr(config.spark, "persona", "Viv")
    prompt = " ".join(args.prompt).strip() if getattr(args, "prompt", None) else None

    runner = GeminiSparkRunner(
        config=config,
        persona=persona,
    )

    if prompt:
        print(f'⚡ Executing Spark prompt in {persona} persona: "{prompt}"')

        async def _run_single():
            await runner.bridge.start()
            await asyncio.sleep(0.1)
            soundbite = await runner.execute_prompt(prompt)
            print(f'🏁 Spoken Soundbite: "{soundbite}"')
            await runner.stop()

        asyncio.run(_run_single())
        return

    print(f"🚀 Gemini Spark Voice Agent running (persona: {persona}). Listening on IPC bridge...")

    async def _run_loop():
        await runner.start()
        while True:
            await asyncio.sleep(1)

    try:
        asyncio.run(_run_loop())
    except KeyboardInterrupt:
        print("\n🛑 Stopping Gemini Spark...")
        asyncio.run(runner.stop())


def build_parser(prog: Optional[str] = None) -> VoiceFiArgumentParser:
    prog_name = prog or resolve_prog_name()
    parser = VoiceFiArgumentParser(
        prog=prog_name,
        description="VoiceFi: Give voice to your agents, and agency for your voice. The Universal Voice Layer for AI Agents, MCP, and macOS.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to custom config.yaml")

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

    # companion / remote / pair
    comp_p = subparsers.add_parser(
        "companion",
        aliases=["remote", "pair"],
        help="Launch Web & Mobile Voice Companion (PWA & QR code)",
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
    lic_act = lic_sub.add_parser(
        "activate", aliases=["set", "apply"], help="Activate a VoiceFi Pro license key"
    )
    lic_act.add_argument("key", type=str, help="Pro license key (e.g. VF1-PRO-PERP-USER.<SIG>)")
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
        aliases=["proactive", "proactive-listening", "feedback_loop", "loopback", "voice-loop"],
        help="Manage ProActive Listening (on/off/status) or run acoustic verification test",
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

    # voice train
    v_train = voice_sub.add_parser("train", help="Train a custom voice clone from mic or files")
    v_train.add_argument("name", type=str, help="Name for the custom voice")
    v_train.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    v_train.add_argument(
        "--assign", type=str, default=None, help="Automatically assign to agent (e.g. antigravity)"
    )

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
        help="Reset HUD position to default top-right anchor below Chrome tab bar",
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
        choices=["top_center", "top_right", "top_left", "bottom_center"],
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

    if not args.command:
        if getattr(sys, "frozen", False):
            # Launched from macOS .app bundle without CLI arguments
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
