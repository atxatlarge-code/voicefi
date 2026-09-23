"""
Server lifecycle, LaunchAgent management, status, clean, pause, and resume CLI subcommands.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Any

from voicefi.config import load_config, save_config


def cmd_clean(args: Any) -> None:
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


def cmd_autostart(args: Any) -> None:
    """Register macOS LaunchAgent so VoiceFi menu bar tray stays on and runs at login."""
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


def cmd_stop_autostart(args: Any) -> None:
    """Unload and remove macOS LaunchAgent."""
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


def cmd_server(args: Any) -> None:
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


cmd_daemon = cmd_server


def cmd_pause(args: Any) -> None:
    """Pause VoiceFi audio hooks and active turn-handoffs globally."""
    config = load_config(args.config)
    config.enabled = False
    save_config(config)
    print("⏸️  VoiceFi paused globally. Audio hooks and auto-listen are temporarily disabled.")


def cmd_resume(args: Any) -> None:
    """Resume VoiceFi audio hooks and active turn-handoffs globally."""
    config = load_config(args.config)
    config.enabled = True
    save_config(config)
    print("▶️  VoiceFi resumed globally. Audio hooks and auto-listen are active.")
