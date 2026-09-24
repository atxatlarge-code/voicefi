"""
macOS Menu Bar Tray, Quick Prompt Bar, Welcome Window, and Dynamic Island HUD CLI subcommands.
"""

import os
import sys
import time
from pathlib import Path
from typing import Any

from voicefi.config import load_config, save_config, HUDConfig
from voicefi.cli_commands.server import cmd_autostart


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

        endpoint = (
            "http://127.0.0.1:5141/api/quick-bar/show"
            if clean_text
            else "http://127.0.0.1:5141/api/quick-bar/toggle"
        )
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


def cmd_hud(args):
    """Control, configure, and debug Unified Dynamic Island HUD on macOS."""
    action = getattr(args, "hud_action", "test")
    from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
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
        pos = (
            getattr(cfg.hud, "position", "bottom_right")
            if hasattr(cfg, "hud") and cfg.hud
            else "bottom_right"
        )
        pos_desc = (
            "the lower-right above the lower bar/dock"
            if pos == "bottom_right"
            else f"the {pos.replace('_', '-')}"
        )
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
