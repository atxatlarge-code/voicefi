"""
Cross-agent prompt dispatch, peer Mac discovery, clipboard sync, companion, and panel CLI subcommands.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any

from voicefi.config import load_config
from voicefi.audio.chimes import play_chime


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

    if getattr(args, "dry_run", False):
        target_desc = (
            f"{peer_match.friendly_name} ({peer_match.ip})"
            if peer_match
            else target_engine.capitalize()
        )
        print(
            f"🔍 [Dry-Run] Target: {target_desc} | ConvID: {conv_id or 'active'} | Envelope: {include_envelope}"
        )
        print(f"📝 Payload ({len(text.strip())} chars): {text.strip()}")
        return

    if peer_match:
        print(
            f"🚀 Dispatching cross-machine task to {peer_match.friendly_name} ({peer_match.ip})..."
        )
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
            print(
                f"❌ Could not deliver to {peer_match.friendly_name}: {res.get('error', 'unknown error')}",
                file=sys.stderr,
            )
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
    print('  • Send task:      vifi send "<prompt>" --to <peer-name>')
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
            print(
                f"📦 Vandelay Industries: Importing clipboard from {peer.friendly_name} ({peer.ip})..."
            )
            res = PeerClient.pull_clipboard(peer)
            if res.get("success") and "text" in res:
                import subprocess

                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
                p.communicate(input=res["text"])
                print(
                    f"✅ Imported {res.get('chars', len(res['text']))} chars into local clipboard!"
                )
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
            print(
                f"📦 Vandelay Industries: Exporting clipboard to {peer.friendly_name} ({peer.ip})..."
            )
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
        print(
            "❌ Error: Target peer name or IP required (e.g. 'vifi clip push mba' or 'vifi clip pull pro').",
            file=sys.stderr,
        )
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
