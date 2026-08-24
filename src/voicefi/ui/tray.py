"""
macOS Menu Bar Companion App using rumps.
Provides visual status, live transcript watching, conversation jumping, targeted voice dictation,
and multi-agent tool integrations.
"""

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
import rumps

from voicefi.config import load_config, save_config, get_default_config_path
from voicefi.license import FeatureGate
from voicefi.tts import get_tts_engine, stop_all_speech
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.injector import (
    inject_text_to_active_app,
    focus_antigravity,
    open_accessibility_settings,
    send_message_to_antigravity,
)
from voicefi.integrations.watcher import TranscriptWatcher
from voicefi.integrations.discovery import AgentToolDetector
from voicefi.ui.hub import ConversationHubWindow
from voicefi.ui.dictation_hud import DictationHUD
from voicefi.ui.speech_hud import AgentSpeechHUD
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD


class VoiceFiTrayApp(rumps.App):
    """macOS Status Bar Menu Application for VoiceFi."""

    def __init__(self):
        super(VoiceFiTrayApp, self).__init__("VoiceFi", icon=None, title=None)
        self.title = None
        self.config = load_config()
        self._current_status = "idle"
        self.active_recorder: Optional[AudioRecorder] = None
        self._key_down_times: dict[int, float] = {}
        self._listen_lock = threading.Lock()

        # Main-thread timer to ensure macOS AppKit redraws the status bar reliably
        self._status_timer = rumps.Timer(self._update_status_ui, 0.2)
        self._status_timer.start()

        # Start live Antigravity transcript watcher with UI state callback
        self.watcher = TranscriptWatcher(
            self.config,
            on_state_change=self.handle_state_change,
        )
        self.watcher.start()

        # Companion Hub Window & Dictation Floating HUD & Speech HUD Pop-up & Unified Dynamic Island HUD
        self.hub = ConversationHubWindow.get_instance(
            self.watcher.tracker,
            on_switch=self.focus_specific_conversation,
            on_new_conversation=self.trigger_new_conversation,
        )
        self.dictation_hud = DictationHUD.get_instance()
        self.speech_hud = AgentSpeechHUD.get_instance()
        self.hud = UnifiedDynamicIslandHUD.get_instance()
        hud_cfg = getattr(self.config, "hud", None)
        if hud_cfg:
            self.hud.set_fullscreen_overlay(getattr(hud_cfg, "fullscreen_overlay", True))
        if getattr(hud_cfg, "persistent", True) and getattr(hud_cfg, "enabled", True):
            self.hud.set_idle()

        # Build Menu Items with explicit keyboard shortcut hints
        self.stop_speaking_item = rumps.MenuItem("🛑 Stop Talking (Esc)", callback=self.stop_speaking_now)
        self.new_conversation_item = rumps.MenuItem(
            "✨ New Conversation with Tools (⌘ + Shift + N)",
            callback=self.trigger_new_conversation,
        )
        self.talk_to_agent_item = rumps.MenuItem(
            "🎙️ Respond to Active Agent (Ctrl + R)",
            callback=self.trigger_talk_to_antigravity,
        )
        self.focus_agent_item = rumps.MenuItem("💬 Switch to Agent Window (Ctrl + J)", callback=self.trigger_focus_antigravity)
        self.hub_item = rumps.MenuItem("🪟 Activity Hub Window (Ctrl + Shift + J)", callback=self.toggle_hub)
        self.conversations_menu = rumps.MenuItem("💬 Conversations")
        self._build_conversations_submenu()

        self.listen_anywhere_item = rumps.MenuItem(
            "🎤 Dictate to Current Window (Ctrl + T)",
            callback=self.trigger_manual_listen,
        )

        # Multi-Agent Integrations Submenu
        self.integrations_menu = rumps.MenuItem("🔌 Integrations")
        self._build_integrations_submenu()

        self.auto_listen_item = rumps.MenuItem(
            "Auto-Listen on Agent Turn",
            callback=self.toggle_auto_listen,
        )
        self.auto_listen_item.state = 1 if self.config.antigravity.auto_listen else 0

        self.read_summary_item = rumps.MenuItem(
            "Read Agent Summaries Aloud",
            callback=self.toggle_read_summary,
        )
        self.read_summary_item.state = 1 if self.config.antigravity.read_summary_aloud else 0

        self.speech_popup_item = rumps.MenuItem(
            "Show Agent Speech Pop-up (HUD)",
            callback=self.toggle_speech_popup,
        )
        self.speech_popup_item.state = 1 if self.config.antigravity.show_speech_popup else 0

        self.barge_in_item = rumps.MenuItem(
            "Active Voice Barge-In (Interrupt Agent)",
            callback=self.toggle_barge_in,
        )
        self.barge_in_item.state = 1 if self.config.vad.barge_in in (True, "auto") else 0

        self.persistent_hud_item = rumps.MenuItem(
            "📌 Persistent Dynamic Island HUD",
            callback=self.toggle_persistent_hud,
        )
        self.persistent_hud_item.state = 1 if getattr(getattr(self.config, "hud", None), "persistent", True) else 0

        self.fullscreen_overlay_item = rumps.MenuItem(
            "🎮 Always on Top of Full-Screen Apps",
            callback=self.toggle_fullscreen_overlay,
        )
        self.fullscreen_overlay_item.state = 1 if getattr(getattr(self.config, "hud", None), "fullscreen_overlay", True) else 0

        self.auto_send_item = rumps.MenuItem(
            "⚡ Auto-Send Prompts (Instant)",
            callback=self.toggle_auto_send,
        )
        self.auto_send_item.state = 1 if getattr(getattr(self.config, "hud", None), "auto_send", True) else 0

        # Voice Control Panel & Mobile Companion
        self.panel_item = rumps.MenuItem("🎛️ Voice Control Panel...", callback=self.open_control_panel_ui)
        self.companion_item = rumps.MenuItem("📱 Mobile Companion (QR Code)...", callback=self.open_mobile_companion)

        # Voice Personas Submenu (Quick Selection)
        self.voice_personas_menu = rumps.MenuItem("🎭 A Voice For Every Agent")
        self._build_personas_submenu()

        # Troubleshooting Submenu
        self.troubleshoot_menu = rumps.MenuItem("🔊 Test & Troubleshoot Voice")
        self._build_troubleshoot_submenu()

        # Voice & VAD Capture Mode Submenu
        self.voice_mode_menu = rumps.MenuItem("🎙️ Capture Mode")
        self._build_voice_mode_submenu()

        # Voice Memo & Brain Dump Submenu
        self.voice_memo_menu = rumps.MenuItem("🧠 Voice Memo (Brain Dump)")
        self._build_memo_submenu()

        tier_info = FeatureGate.get_tier_summary(self.config)
        self.tier_item = rumps.MenuItem(f"Tier: {tier_info['tier']} (Patent Pending)", callback=None)

        # Self-updater item
        self.update_item = rumps.MenuItem("✨ Check for Updates...", callback=self.trigger_tray_update)

        self.menu = [
            self.update_item,
            self.stop_speaking_item,
            rumps.separator,
            self.new_conversation_item,
            self.talk_to_agent_item,
            self.focus_agent_item,
            self.hub_item,
            self.conversations_menu,
            self.listen_anywhere_item,
            self.voice_memo_menu,
            rumps.separator,
            self.companion_item,
            self.panel_item,
            self.voice_personas_menu,
            self.troubleshoot_menu,
            self.integrations_menu,
            self.voice_mode_menu,
            rumps.separator,
            self.persistent_hud_item,
            self.fullscreen_overlay_item,
            self.auto_send_item,
            self.auto_listen_item,
            self.read_summary_item,
            self.speech_popup_item,
            self.barge_in_item,
            rumps.separator,
            rumps.MenuItem("✨ Preview Speech Pop-up", callback=self.preview_speech_popup),
            rumps.MenuItem("🔐 Grant Permissions (Auto-Paste)", callback=self.open_permissions),
            rumps.MenuItem("⚙️ Open Config File", callback=self.open_config_file),
            self.tier_item,
            rumps.separator,
        ]

        # Start unified global hotkey listener
        self._start_global_hotkey_listener()
        self._start_update_checker_thread()

    def _start_update_checker_thread(self):
        """Periodically check for software updates and handle Pro auto-updates in background."""
        def _check():
            try:
                from voicefi.updater import check_for_updates, run_auto_update_if_enabled
                run_auto_update_if_enabled(self.config)
                is_avail, new_ver, _ = check_for_updates(force=False)
                if is_avail:
                    self.update_item.title = f"✨ Update Available (v{new_ver}) • Click to Update"
                else:
                    self.update_item.title = "✨ VoiceFi is Up to Date (v" + FeatureGate.get_tier_summary(self.config).get("tier", "") + ")"
            except Exception:
                pass
        threading.Thread(target=_check, daemon=True).start()

    def trigger_tray_update(self, _=None):
        """Execute 1-click update from Menu Bar."""
        def _run():
            try:
                rumps.notification("VoiceFi Updater", "Starting Update...", "Downloading latest build from GitHub")
                from voicefi.updater import perform_update
                res = perform_update(relink_hooks=True)
                if res.get("success"):
                    rumps.notification("VoiceFi Updated 🎉", res.get("message", "Upgraded successfully"), "All features are active.")
                    self.update_item.title = f"✅ Updated to {res.get('new_version', 'latest')}"
                else:
                    rumps.notification("VoiceFi Update Error ⚠️", "Update Failed", str(res.get("error", "Error")))
            except Exception as e:
                rumps.notification("VoiceFi Update Error ⚠️", "Update Failed", str(e))
        threading.Thread(target=_run, daemon=True).start()

    def _build_conversations_submenu(self):
        """Populate active and recent Antigravity conversations."""
        convs = self.watcher.tracker.get_all_conversations(limit=7)
        items = []

        if not convs:
            items.append(rumps.MenuItem("No active conversations found", callback=None))
        else:
            status_icons = {
                "waiting_for_user": "🟢",
                "agent_working": "⏳",
                "idle": "⚪",
            }
            active_conv = self.watcher.tracker.get_active_or_latest()
            active_id = active_conv.id if active_conv else None

            for c in convs:
                icon = status_icons.get(c.status, "⚪")
                is_active = (c.id == active_id)
                prefix = f"{icon} "
                title_label = c.title[:36] + ("..." if len(c.title) > 36 else "")
                active_suffix = " (Active)" if is_active else ""
                label = f"{prefix}{title_label}{active_suffix}"

                def _make_cb(cid, tpath, ctitle):
                    return lambda _: self.focus_specific_conversation(cid, transcript_path=tpath, title=ctitle)

                item = rumps.MenuItem(label, callback=_make_cb(c.id, c.transcript_path, c.title))
                item.state = 1 if is_active else 0
                items.append(item)

        items.append(rumps.separator)
        items.append(rumps.MenuItem("🔄 Refresh List", callback=lambda _: self._build_conversations_submenu()))
        self.conversations_menu.update(items)

    def focus_specific_conversation(self, conv_id: str, transcript_path: Optional[Path] = None, title: Optional[str] = None):
        """Bring Antigravity to the front and link active conversation."""
        print(f"[VoiceFi] 💬 Jump to Antigravity: {title} ({conv_id[:8]})")
        self.watcher.tracker.set_active_focus(conv_id, transcript_path=transcript_path, title=title)
        focus_antigravity(focus_input=True)
        self._build_conversations_submenu()
        if hasattr(self, "hub") and self.hub:
            self.hub.refresh()
        if title:
            try:
                rumps.notification("VoiceFi • Antigravity Linked", title[:45], "Select thread in sidebar to chat")
            except Exception:
                pass

    def _build_integrations_submenu(self):
        """Populate integrations submenu with detected agent tools."""
        detected = AgentToolDetector.get_all_detected_tools()
        
        antigravity_status = "Connected ✅" if detected["antigravity"]["detected"] else "Detected"
        self.item_antigravity = rumps.MenuItem(f"Antigravity ({antigravity_status})", callback=None)
        self.item_antigravity.state = 1 if self.config.integrations.antigravity else 0

        claude_status = "Connected ✅" if detected["claude_code"]["detected"] else "Available"
        self.item_claude = rumps.MenuItem(f"Claude Code ({claude_status})", callback=None)
        self.item_claude.state = 1 if self.config.integrations.claude_code else 0

        cursor_status = "Connected ✅" if detected["cursor"]["detected"] else "Available"
        self.item_cursor = rumps.MenuItem(f"Cursor Composer ({cursor_status})", callback=None)
        self.item_cursor.state = 1 if self.config.integrations.cursor else 0

        windsurf_status = "Connected ✅" if detected["windsurf"]["detected"] else "Available"
        self.item_windsurf = rumps.MenuItem(f"Windsurf Cascade ({windsurf_status})", callback=None)
        self.item_windsurf.state = 1 if self.config.integrations.windsurf else 0

        self.item_sys_dict = rumps.MenuItem("System-Wide Dictation (Ctrl+T)", callback=None)
        self.item_sys_dict.state = 1 if self.config.integrations.system_dictation else 0

        self.integrations_menu.update([
            self.item_antigravity,
            self.item_claude,
            self.item_cursor,
            self.item_windsurf,
            rumps.separator,
            self.item_sys_dict,
        ])

    def _build_voice_mode_submenu(self):
        """Populate capture mode submenu (Hybrid, Push-to-Talk, Auto-VAD)."""
        current_mode = self.config.vad.mode

        def _set_mode(m):
            def _cb(sender):
                self.config.vad.mode = m
                save_config(self.config)
                self._build_voice_mode_submenu()
                try:
                    mode_names = {"hybrid": "Hybrid (Tap=Auto / Hold=PTT)", "ptt": "Push-to-Talk Only", "auto": "Auto-VAD Only"}
                    rumps.notification("VoiceFi", "Capture Mode Updated", mode_names.get(m, m))
                except Exception:
                    pass
            return _cb

        item_hybrid = rumps.MenuItem("✨ Hybrid (Tap=Auto / Hold=PTT)", callback=_set_mode("hybrid"))
        item_hybrid.state = 1 if current_mode == "hybrid" else 0

        item_ptt = rumps.MenuItem("🔴 Push-to-Talk Only (Hold key)", callback=_set_mode("ptt"))
        item_ptt.state = 1 if current_mode == "ptt" else 0

        item_auto = rumps.MenuItem("🎙️ Auto-VAD Only (Silence Detection)", callback=_set_mode("auto"))
        item_auto.state = 1 if current_mode == "auto" else 0

        self.voice_mode_menu.update([item_hybrid, item_ptt, item_auto])

    def _build_memo_submenu(self):
        """Populate voice memo and brain dump actions."""
        from voicefi.memo import MemoStore, get_memos_dir

        def _launch_memo(duration_str: str):
            return lambda _: self.launch_terminal_memo(duration_str)

        items = [
            rumps.MenuItem("▶️ Start 3-Minute Voice Memo (Pacing Dump)", callback=_launch_memo("3m")),
            rumps.MenuItem("▶️ Start 5-Minute Voice Memo", callback=_launch_memo("5m")),
            rumps.MenuItem("▶️ Start 2-Minute Quick Memo", callback=_launch_memo("2m")),
            rumps.separator,
            rumps.MenuItem("📂 Open Saved Memos Folder...", callback=self.open_memos_folder),
        ]

        store = MemoStore()
        recent = store.list_memos(limit=5)
        if recent:
            items.append(rumps.separator)
            items.append(rumps.MenuItem("Recent Voice Memos:", callback=None))
            for m in recent:
                title = m.get("title", "Voice Memo")[:28]
                mid = m.get("id", "")
                dur = f"{int(m.get('duration_seconds', 0)) // 60:02d}:{int(m.get('duration_seconds', 0)) % 60:02d}"
                items.append(rumps.MenuItem(f"  • {title} ({dur})", callback=lambda _, id=mid: self.show_memo_plan(id)))

        self.voice_memo_menu.update(items)

    def launch_terminal_memo(self, duration: str = "3m"):
        """Launch interactive Voice Memo recording session in Terminal with elegant countdown timer."""
        import sys
        vg_bin = Path(sys.executable).parent / "voicefi"
        vg_cmd = f"'{vg_bin}' memo record -d {duration}" if vg_bin.is_file() else f"vg memo record -d {duration}"

        script = f'''
        tell application "Terminal"
            activate
            do script "{vg_cmd}"
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script])
        except Exception:
            pass

    def open_memos_folder(self, _=None):
        """Reveal saved voice memos in Finder."""
        from voicefi.memo import get_memos_dir
        subprocess.run(["open", str(get_memos_dir())])

    def show_memo_plan(self, memo_id: str):
        """Open synthesized memo plan markdown file in default editor."""
        from voicefi.memo import MemoStore
        store = MemoStore()
        res = store.get_memo(memo_id)
        if res:
            rec, synth = res
            md_path = store.root_dir / rec.id / "plan.md"
            if md_path.is_file():
                subprocess.run(["open", str(md_path)])

    def open_control_panel_ui(self, _=None):
        """Open the interactive Voice Control Panel."""
        from voicefi.ui.panel import open_control_panel
        open_control_panel(config=self.config)
        try:
            rumps.notification("VoiceFi", "Control Panel Opened", "Manage agent voices & speak voice commands")
        except Exception:
            pass

    def open_mobile_companion(self, _=None):
        """Open the Mobile Companion pairing page with QR code."""
        import webbrowser
        from voicefi.companion.qr import get_companion_urls
        urls = get_companion_urls(port=8765)
        self._ensure_companion_server_running()
        pair_url = urls["localhost_url"] + "/pair"
        webbrowser.open(pair_url)
        try:
            rumps.notification("VoiceFi Companion", "Mobile Pairing Ready", f"Scan QR code at {urls['ip_url']}")
        except Exception:
            pass

    def _ensure_companion_server_running(self):
        if getattr(self, "_companion_started", False):
            return
        self._companion_started = True

        def _run_server():
            from voicefi.companion.server import CompanionServer
            from aiohttp import web
            import asyncio
            server = CompanionServer(config=self.config, port=8765, host="0.0.0.0")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            server.loop = loop
            server._start_watcher_thread()
            app_runner = web.AppRunner(server.app)
            loop.run_until_complete(app_runner.setup())
            site = web.TCPSite(app_runner, "0.0.0.0", 8765)
            loop.run_until_complete(site.start())
            loop.run_forever()

        threading.Thread(target=_run_server, daemon=True).start()

    def _build_personas_submenu(self):
        """Populate quick voice personas selection submenu."""
        from voicefi.tts import CURATED_PERSONAS, find_persona
        from voicefi.config import AgentVoiceProfile

        # Find current active voice for Antigravity
        _, current_ag_voice, _ = self.config.resolve_voice("antigravity")
        items = []

        for p in CURATED_PERSONAS:
            is_active = (p.id.lower() == current_ag_voice.lower() or p.name.lower() == current_ag_voice.lower())
            label = f"{p.name} ({p.style[:24]}...)"

            def _make_set_cb(persona_obj):
                def _cb(sender):
                    self.config.agents["antigravity"] = AgentVoiceProfile(
                        voice=persona_obj.id,
                        provider=persona_obj.provider,
                        description=f"Assigned to antigravity",
                    )
                    save_config(self.config)
                    self._build_personas_submenu()
                    try:
                        rumps.notification("VoiceFi", "Voice Updated", f"Antigravity voice set to {persona_obj.name}")
                    except Exception:
                        pass
                return _cb

            item = rumps.MenuItem(label, callback=_make_set_cb(p))
            item.state = 1 if is_active else 0
            items.append(item)

        items.append(rumps.separator)
        items.append(rumps.MenuItem("🎛️ Open Full Control Panel...", callback=self.open_control_panel_ui))
        self.voice_personas_menu.update(items)

    def _build_troubleshoot_submenu(self):
        """Populate voice testing and audio troubleshooting actions."""
        from voicefi.troubleshoot import AudioTroubleshooter

        def _hear_active_voice(_):
            _, current_ag_voice, _ = self.config.resolve_voice("antigravity")
            AudioTroubleshooter(self.config).test_voice(
                voice_name_or_id=current_ag_voice,
                text="Voice test nominal. Audio output and latency are healthy.",
                block=False,
                show_hud=True,
            )

        def _run_full_diag(_):
            report = AudioTroubleshooter(self.config).run_full_troubleshoot()
            status_txt = "All audio & voice subsystems operational ✅" if report.get("status") == "healthy" else "Audio warnings detected ⚠️"
            recs = report.get("recommendations", [])
            detail_txt = recs[0] if recs else "Hardware, mic, and neural TTS are nominal."
            try:
                rumps.notification("VoiceFi Diagnostics", status_txt, detail_txt)
            except Exception:
                pass

        def _mic_loopback(_):
            try:
                rumps.notification("VoiceFi Mic Test", "Recording 3s...", "Speak clearly now to test your mic")
            except Exception:
                pass
            def _rec_thread():
                res = AudioTroubleshooter(self.config).test_microphone_loopback(duration_seconds=3.0, play_back=True)
                if res.success:
                    try:
                        rumps.notification("VoiceFi Mic Test", "Playback Active", f"RMS Energy: {res.rms_energy:.4f}, SNR: {res.snr_db:.1f} dB")
                    except Exception:
                        pass
                else:
                    try:
                        rumps.notification("VoiceFi Mic Test Error", "Failed", str(res.error))
                    except Exception:
                        pass
            threading.Thread(target=_rec_thread, daemon=True).start()

        def _test_chimes(_):
            AudioTroubleshooter(self.config).test_speaker_output("start", block=False)
            try:
                rumps.notification("VoiceFi Audio", "Speaker Output Test", "Played test notification chime")
            except Exception:
                pass

        def _run_feedback_loop(_):
            def _loop_thread():
                try:
                    rumps.notification("VoiceFi Feedback Loop", "Starting Feedback Loop Test...", "Speaking test phrase aloud & capturing response")
                except Exception:
                    pass
                res = AudioTroubleshooter(self.config).test_feedback_loop(
                    voice_name_or_id="Aria",
                    text="This is a test feedback loop",
                    send_to_conversation=True,
                )
                if res.get("success"):
                    try:
                        rumps.notification("VoiceFi Feedback Loop", "Feedback Loop Complete ✅", f"Match: {res.get('similarity_pct')}% — Delivered to conversation")
                    except Exception:
                        pass

            threading.Thread(target=_loop_thread, daemon=True).start()

        def _run_hearing_test(_):
            def _hearing_thread():
                try:
                    rumps.notification("VoiceFi Hearing Test", "Starting Hearing Test...", "Testing acoustic speaker & microphone reception")
                except Exception:
                    pass
                res = AudioTroubleshooter(self.config).test_hearing(
                    voice_name_or_id="Aria",
                    text="This is a hearing test",
                )
                if res.success:
                    try:
                        rumps.notification("VoiceFi Hearing Test", "Hearing Nominal ✅", f"Accuracy Match: {res.similarity_pct}%")
                    except Exception:
                        pass

            threading.Thread(target=_hearing_thread, daemon=True).start()

        items = [
            rumps.MenuItem("▶️ Hear Active Agent Voice", callback=_hear_active_voice),
            rumps.MenuItem("🔄 Run Feedback Loop Test", callback=_run_feedback_loop),
            rumps.MenuItem("👂 Run Hearing Test (Acoustic Check)", callback=_run_hearing_test),
            rumps.MenuItem("🎙️ Mic Loopback Test (Hear Yourself 3s)", callback=_mic_loopback),
            rumps.MenuItem("🔔 Test Speaker Chimes", callback=_test_chimes),
            rumps.separator,
            rumps.MenuItem("⚡ Run Audio & Voice Diagnostics", callback=_run_full_diag),
            rumps.MenuItem("🎛️ Open Voice Troubleshooter Web Panel...", callback=self.open_control_panel_ui),
        ]
        self.troubleshoot_menu.update(items)

    def _update_status_ui(self, _):
        """Called on macOS main runloop every 200ms to redraw menu bar icon."""
        status_map = {
            "speaking": "speaker.wave.2.fill",
            "listening": "mic.fill",
            "hearing": "waveform.circle.fill",
            "transcribing": "ellipsis.bubble",
            "thinking": "sparkles",
            "working": "gearshape.fill",
            "ptt_listening": "mic.fill",
            "paused_agent_speaking": "pause.fill",
            "paused": "pause.fill",
        }
        
        symbol_name = "wifi"

        if self._current_status in status_map:
            symbol_name = status_map[self._current_status]
        else:
            active_conv = self.watcher.tracker.get_active_or_latest() if getattr(self, 'watcher', None) else None
            if active_conv and active_conv.status == "waiting_for_user":
                symbol_name = "mic"
            elif active_conv and active_conv.status == "agent_working":
                symbol_name = "sparkles"
            else:
                symbol_name = "wifi"

        if self.title is not None and self.title != "":
            self.title = None

        current_symbol = getattr(self, "_current_symbol", None)
        if current_symbol != symbol_name:
            self._current_symbol = symbol_name
            try:
                import AppKit
                from pathlib import Path
                
                image = None
                if symbol_name == "wifi":
                    # Load the main .org logo for the default/idle state
                    assets_dir = Path(__file__).resolve().parent.parent.parent.parent / "assets"
                    logo_path = assets_dir / "voicefi-menu-bar-icon.svg"
                    
                    if logo_path.exists():
                        image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(logo_path))
                        if image:
                            image.setTemplate_(True)
                            
                            # Only scale down if necessary
                            thickness = AppKit.NSStatusBar.systemStatusBar().thickness()
                            # 22 is standard, but some modern Macs with notch might be slightly different.
                            # We leave a small margin (e.g. 4 points) so it fits nicely like a standard icon
                            target_height = thickness - 4
                            if target_height <= 0:
                                target_height = 18.0
                                
                            if image.size().height > target_height:
                                ratio = target_height / image.size().height
                                new_size = AppKit.NSMakeSize(image.size().width * ratio, target_height)
                                image.setSize_(new_size)
                
                if image is None:
                    # Fallback to system symbol
                    image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol_name, None)
                    if image:
                        image.setTemplate_(True)
                
                if image:
                    self._icon_nsimage = image
                    if hasattr(self, '_nsapp'):
                        self._nsapp.setStatusBarIcon()
            except Exception as e:
                print(f"[VoiceFi] Error updating menu bar icon: {e}")
                pass

    def handle_state_change(self, state: str):
        """Thread-safe state change handler."""
        self._current_status = state
        if hasattr(self, "hub") and self.hub:
            self.hub.refresh()
        try:
            hud = UnifiedDynamicIslandHUD.get_instance()
            if state == "idle":
                hud.set_idle(linger=1.5)
            elif state in ("listening", "ptt_listening"):
                hud.set_listening(user_name=getattr(self.config, "user_name", "Jake"))
            elif state == "thinking":
                hud.set_thinking(agent_name="Antigravity", detail="Thinking...")
            elif state == "working":
                hud.set_working(agent_name="Antigravity", tool_action="Running tools...")
            elif state == "transcribing":
                hud.show_transcribing()
        except Exception:
            pass

    def toggle_hub(self, _=None):
        """Toggle the floating Companion Activity Hub window (debounced)."""
        now = time.time()
        if hasattr(self, "_last_hub_toggle_time") and (now - self._last_hub_toggle_time) < 0.4:
            return
        self._last_hub_toggle_time = now
        if hasattr(self, "hub") and self.hub:
            self.hub.toggle()

    def finish_active_recording(self):
        """Immediately stop recording and trigger transcription (e.g. Enter pressed or PTT key released)."""
        print("[VoiceFi] 🛑 finish_active_recording invoked")
        if hasattr(self, "_ptt_stop_event") and self._ptt_stop_event:
            self._ptt_stop_event.set()
        if self.active_recorder:
            self.active_recorder.stop()
        if self.watcher:
            self.watcher.finish_listening()

    def stop_speaking_now(self, _=None):
        """Instantly stop speech synthesis or cancel recording."""
        stop_all_speech()
        if hasattr(self, "speech_hud") and self.speech_hud:
            self.speech_hud.hide()
        if hasattr(self, "dictation_hud") and self.dictation_hud:
            self.dictation_hud.hide()
        if hasattr(self, "_ptt_stop_event") and self._ptt_stop_event:
            self._ptt_stop_event.set()
        if self.active_recorder:
            self.active_recorder.stop()
        if self.watcher:
            self.watcher.interrupt()
        self._current_status = "idle"

    def open_permissions(self, _=None):
        """Open macOS Accessibility settings pane."""
        open_accessibility_settings()

    def trigger_focus_antigravity(self, _=None):
        """Switch frontmost window to Antigravity and focus input (debounced)."""
        now = time.time()
        if hasattr(self, "_last_focus_time") and (now - self._last_focus_time) < 0.4:
            return
        self._last_focus_time = now
        print("[VoiceFi] 💬 Triggered Jump to Antigravity (Ctrl+J / Cmd+J)")
        def _worker():
            time.sleep(0.05)
            active_conv = self.watcher.tracker.get_active_or_latest() if self.watcher else None
            success = focus_antigravity(focus_input=True)
            print(f"[VoiceFi] Focus Antigravity result: {success}")
            if active_conv:
                try:
                    title = active_conv.title[:38] + ("..." if len(active_conv.title) > 38 else "")
                    rumps.notification("VoiceFi • Agent Focused", title, "Hit Ctrl + R to speak or type prompt")
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def trigger_talk_to_antigravity(self, ptt_mode: bool = False):
        """Record voice prompt for active Antigravity conversation without stealing window focus."""
        with self._listen_lock:
            if self._current_status in ("listening", "hearing", "transcribing", "ptt_listening", "paused_agent_speaking"):
                return
            self._current_status = "ptt_listening" if ptt_mode else "listening"

        print("[VoiceFi] 🎙️ Triggered Talk to Active Agent (keeping current window focus)")
        stop_all_speech()
        if self.watcher:
            self.watcher.interrupt()

        hud = UnifiedDynamicIslandHUD.get_instance()
        hud.set_listening(user_name=getattr(self.config, "user_name", "Jake"))

        self._ptt_stop_event = threading.Event()

        def _worker():
            temp_wav = None
            try:
                active_conv = self.watcher.tracker.get_active_or_latest() if self.watcher else None
                if self.config.audio_cues.enabled:
                    play_chime("start", block=False)
                time.sleep(0.25)

                recorder = AudioRecorder(
                    sample_rate=self.config.vad.sample_rate,
                    energy_threshold=self.config.vad.energy_threshold,
                    silence_duration=self.config.vad.silence_duration,
                )
                self.active_recorder = recorder

                def _on_pause(is_paused: bool):
                    if is_paused:
                        self._current_status = "paused_agent_speaking"
                        hud.show_paused("⏸️ Agent Speaking (Paused)...")
                    else:
                        self._current_status = "ptt_listening" if ptt_mode else "listening"
                        hud.set_listening(user_name=getattr(self.config, "user_name", "Jake"))

                def _on_live(txt: str):
                    hud.update_live_transcription(txt, user_name=getattr(self.config, "user_name", "Jake"))

                if ptt_mode:
                    audio_data, temp_wav = recorder.record_push_to_talk(
                        stop_event=self._ptt_stop_event,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        ptt_release_delay_ms=self.config.vad.ptt_release_delay_ms,
                    )
                else:
                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=lambda: setattr(self, "_current_status", "hearing"),
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        stop_event=self._ptt_stop_event,
                    )

                self.active_recorder = None
                self._current_status = "transcribing"
                hud.show_transcribing()

                stt = get_stt_engine(self.config)
                text = stt.transcribe(temp_wav)
                if text and text.strip():
                    conv_id = active_conv.id if active_conv else None
                    is_auto_send = getattr(getattr(self.config, "hud", None), "auto_send", True) and getattr(self.config.antigravity, "auto_send", True)

                    def _send_action(payload_text: str):
                        send_message_to_antigravity(conv_id=conv_id, text=payload_text, sender_name=self.config.user_name)
                        if self.config.audio_cues.enabled:
                            play_chime(self.config.audio_cues.sent_chime, block=False)
                        try:
                            title = active_conv.title if active_conv else "Active Agent"
                            rumps.notification(f"VoiceFi • {title[:30]}", "Prompt Sent", payload_text[:80])
                        except Exception:
                            pass

                    if is_auto_send:
                        _send_action(text)
                        hud.show_done(preview_text=text[:20])
                    else:
                        target_name = active_conv.title[:20] if (active_conv and active_conv.title) else "Antigravity"
                        hud.set_editing(text, on_submit=_send_action, target_name=target_name)
                else:
                    if hud.persistent:
                        hud.set_idle()
                    else:
                        hud.hide()
            except Exception as e:
                print(f"[VoiceFi] Error during agent voice capture: {e}")
                if hud.persistent:
                    hud.set_idle()
                else:
                    hud.hide()
            finally:
                if temp_wav and isinstance(temp_wav, Path):
                    temp_wav.unlink(missing_ok=True)
                self.active_recorder = None
                self._current_status = "idle"
                self._key_down_times.clear()
                self._build_conversations_submenu()

        threading.Thread(target=_worker, daemon=True).start()

    def trigger_new_conversation(self, ptt_mode: bool = False, prompt_text: Optional[str] = None):
        """Start a brand new Antigravity agent conversation equipped with connected tools."""
        with self._listen_lock:
            if self._current_status in ("listening", "hearing", "transcribing", "ptt_listening", "paused_agent_speaking", "new_conversation"):
                return
            self._current_status = "new_conversation"

        print("[VoiceFi] ✨ Triggered Start New Conversation with Connected Tools (⌘⇧N)")
        stop_all_speech()
        if self.watcher:
            self.watcher.interrupt()

        hud = UnifiedDynamicIslandHUD.get_instance()
        hud.set_new_conversation(user_name=getattr(self.config, "user_name", "Jake"))

        if prompt_text and prompt_text.strip():
            def _direct_action(text: str):
                from voicefi.integrations.injector import create_new_antigravity_conversation
                new_id = create_new_antigravity_conversation(prompt=text)
                if new_id and self.watcher:
                    self.watcher.tracker.set_active_focus(new_id)
                hud.show_done(preview_text=text[:20])
                if self.config.audio_cues.enabled:
                    play_chime(self.config.audio_cues.sent_chime, block=False)
                try:
                    rumps.notification("VoiceFi", "New Conversation Started", text[:80])
                except Exception:
                    pass
                self._current_status = "idle"
                self._build_conversations_submenu()
            _direct_action(prompt_text.strip())
            return

        self._ptt_stop_event = threading.Event()

        def _worker():
            temp_wav = None
            try:
                if self.config.audio_cues.enabled:
                    play_chime("start", block=False)
                time.sleep(0.25)

                recorder = AudioRecorder(
                    sample_rate=self.config.vad.sample_rate,
                    energy_threshold=self.config.vad.energy_threshold,
                    silence_duration=self.config.vad.silence_duration,
                )
                self.active_recorder = recorder

                def _on_pause(is_paused: bool):
                    if is_paused:
                        self._current_status = "paused_agent_speaking"
                        hud.show_paused("⏸️ Agent Speaking (Paused)...")
                    else:
                        self._current_status = "new_conversation"
                        hud.set_new_conversation(user_name=getattr(self.config, "user_name", "Jake"))

                def _on_live(txt: str):
                    hud.update_live_transcription(txt, user_name=getattr(self.config, "user_name", "Jake"), is_new_conversation=True)

                if ptt_mode:
                    audio_data, temp_wav = recorder.record_push_to_talk(
                        stop_event=self._ptt_stop_event,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        ptt_release_delay_ms=self.config.vad.ptt_release_delay_ms,
                    )
                else:
                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=lambda: setattr(self, "_current_status", "hearing"),
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        stop_event=self._ptt_stop_event,
                    )

                self.active_recorder = None
                self._current_status = "transcribing"
                hud.show_transcribing()

                stt = get_stt_engine(self.config)
                text = stt.transcribe(temp_wav)
                if text and text.strip():
                    is_auto_send = getattr(getattr(self.config, "hud", None), "auto_send", True) and getattr(self.config.antigravity, "auto_send", True)

                    def _create_action(payload_text: str):
                        from voicefi.integrations.injector import create_new_antigravity_conversation
                        new_id = create_new_antigravity_conversation(prompt=payload_text)
                        if new_id and self.watcher:
                            self.watcher.tracker.set_active_focus(new_id)
                        hud.show_done(preview_text=payload_text[:20])
                        if self.config.audio_cues.enabled:
                            play_chime(self.config.audio_cues.sent_chime, block=False)
                        try:
                            rumps.notification("VoiceFi • New Session", "Conversation Initialized", payload_text[:80])
                        except Exception:
                            pass

                    if is_auto_send:
                        _create_action(text)
                    else:
                        hud.start_new_conversation_dialog(on_submit=_create_action, initial_text=text)
                else:
                    if hud.persistent:
                        hud.set_idle()
                    else:
                        hud.hide()
            except Exception as e:
                print(f"[VoiceFi] Error starting new conversation: {e}")
                if hud.persistent:
                    hud.set_idle()
                else:
                    hud.hide()
            finally:
                if temp_wav and isinstance(temp_wav, Path):
                    temp_wav.unlink(missing_ok=True)
                self.active_recorder = None
                self._current_status = "idle"
                self._key_down_times.clear()
                self._build_conversations_submenu()

        threading.Thread(target=_worker, daemon=True).start()

    def _setup_cocoa_hotkeys(self):
        """Compatibility stub for tests."""
        pass

    def _start_global_hotkey_listener(self):
        """Unified global hotkey listener using pynput with macOS virtual key codes and ASCII control support."""
        try:
            import ApplicationServices
            options = {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
            if not ApplicationServices.AXIsProcessTrustedWithOptions(options):
                print("[VoiceFi] ⚠️ Missing Accessibility permissions. Please grant them in the macOS popup.")
        except Exception:
            pass

        def _run_pynput():
            try:
                from pynput import keyboard
                from pynput.keyboard import Key

                modifiers = set()
                last_triggers = {}

                def _debounce(action_name: str, interval: float = 0.35) -> bool:
                    now = time.time()
                    last = last_triggers.get(action_name, 0.0)
                    if (now - last) < interval:
                        return False
                    last_triggers[action_name] = now
                    return True

                def on_press(key):
                    try:
                        # 0. Track modifier keys
                        if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
                            modifiers.add('ctrl')
                        elif key in (Key.cmd, Key.cmd_l, Key.cmd_r):
                            modifiers.add('cmd')
                        elif key in (Key.shift, Key.shift_l, Key.shift_r):
                            modifiers.add('shift')
                        elif key in (Key.alt, Key.alt_l, Key.alt_r):
                            modifiers.add('alt')

                        vk = getattr(key, 'vk', None)
                        char = getattr(key, 'char', None)
                        ctrl = 'ctrl' in modifiers
                        cmd = 'cmd' in modifiers
                        shift = 'shift' in modifiers
                        mod = ctrl or cmd

                        # 1. Enter or Space while recording -> finish immediately
                        is_rec = (
                            self._current_status in ("listening", "hearing", "ptt_listening", "new_conversation")
                            or self.active_recorder is not None
                            or (self.watcher and self.watcher.active_recorder is not None)
                        )
                        if is_rec and (key in (Key.enter, Key.space) or vk in (36, 76, 49)):
                            self.finish_active_recording()
                            return

                        # 2. Escape: stop speech or cancel recording
                        if key == Key.esc or vk == 53:
                            self.stop_speaking_now()
                            return

                        # 3. New Conversation with Connected Tools (Cmd+Shift+N or Ctrl+Shift+N)
                        if mod and shift and (vk == 45 or char in ('n', 'N', '\x0e')):
                            if self.config.global_hotkey.enabled and _debounce('new_conv'):
                                is_ptt = (self.config.vad.mode in ("ptt", "hybrid"))
                                self.trigger_new_conversation(ptt_mode=is_ptt)
                            return

                        # 4. Companion Activity Hub (Ctrl+Shift+J or Cmd+Shift+J)
                        if mod and shift and (vk == 38 or char in ('j', 'J', '\n')):
                            if _debounce('hub'):
                                self.toggle_hub()
                            return

                        # 5. Jump to Antigravity (Ctrl+J or Cmd+J)
                        if mod and not shift and (vk == 38 or char in ('j', '\n')):
                            if _debounce('jump'):
                                self.trigger_focus_antigravity()
                            return

                        # 6. Universal Dictation (Ctrl+T)
                        if ctrl and (vk == 17 or char in ('t', '\x14')):
                            if _debounce('dictate'):
                                is_ptt = (self.config.vad.mode in ("ptt", "hybrid"))
                                self.trigger_manual_listen(ptt_mode=is_ptt)
                            return

                        # 7. Respond to Agent (Ctrl+R)
                        if ctrl and (vk == 15 or char in ('r', '\x12')):
                            if self.config.global_hotkey.enabled and _debounce('respond'):
                                is_ptt = (self.config.vad.mode in ("ptt", "hybrid"))
                                self.trigger_talk_to_antigravity(ptt_mode=is_ptt)
                            return
                    except Exception as e:
                        print(f"[Tray] Hotkey press notice: {e}")

                def on_release(key):
                    try:
                        if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
                            modifiers.discard('ctrl')
                        elif key in (Key.cmd, Key.cmd_l, Key.cmd_r):
                            modifiers.discard('cmd')
                        elif key in (Key.shift, Key.shift_l, Key.shift_r):
                            modifiers.discard('shift')
                        elif key in (Key.alt, Key.alt_l, Key.alt_r):
                            modifiers.discard('alt')

                        vk = getattr(key, 'vk', None)
                        if self.config.vad.mode == "ptt" and vk in (15, 17, 45):
                            self.finish_active_recording()
                    except Exception as e:
                        print(f"[Tray] Hotkey release notice: {e}")

                listener = keyboard.Listener(on_press=on_press, on_release=on_release)
                listener.daemon = True
                listener.start()
                print("[VoiceFi] ⌨️ Unified global hotkeys active: Cmd+Shift+N (New Conv), Ctrl+R (Respond), Ctrl+J / Cmd+J (Jump), Ctrl+T (Dictate), Ctrl+Shift+J (Hub)")
            except Exception as e:
                print(f"[Tray] Hotkey listener notice: {e}")

        threading.Thread(target=_run_pynput, daemon=True).start()

    def toggle_persistent_hud(self, sender):
        hud = UnifiedDynamicIslandHUD.get_instance()
        new_val = not getattr(getattr(self.config, "hud", None), "persistent", True)
        if not hasattr(self.config, "hud") or self.config.hud is None:
            from voicefi.config import HUDConfig
            self.config.hud = HUDConfig()
        self.config.hud.persistent = new_val
        self.config.antigravity.persistent_hud = new_val
        sender.state = 1 if new_val else 0
        hud.set_persistent(new_val)
        save_config(self.config)

    def toggle_fullscreen_overlay(self, sender):
        hud = UnifiedDynamicIslandHUD.get_instance()
        new_val = not getattr(getattr(self.config, "hud", None), "fullscreen_overlay", True)
        if not hasattr(self.config, "hud") or self.config.hud is None:
            from voicefi.config import HUDConfig
            self.config.hud = HUDConfig()
        self.config.hud.fullscreen_overlay = new_val
        sender.state = 1 if new_val else 0
        hud.set_fullscreen_overlay(new_val)
        save_config(self.config)

    def toggle_auto_send(self, sender):
        new_val = not getattr(getattr(self.config, "hud", None), "auto_send", True)
        if not hasattr(self.config, "hud") or self.config.hud is None:
            from voicefi.config import HUDConfig
            self.config.hud = HUDConfig()
        self.config.hud.auto_send = new_val
        self.config.antigravity.auto_send = new_val
        sender.state = 1 if new_val else 0
        hud = UnifiedDynamicIslandHUD.get_instance()
        hud.set_auto_send(new_val)
        save_config(self.config)

    def toggle_auto_listen(self, sender):
        self.config.antigravity.auto_listen = not self.config.antigravity.auto_listen
        sender.state = 1 if self.config.antigravity.auto_listen else 0
        save_config(self.config)

    def toggle_read_summary(self, sender):
        self.config.antigravity.read_summary_aloud = not self.config.antigravity.read_summary_aloud
        sender.state = 1 if self.config.antigravity.read_summary_aloud else 0
        save_config(self.config)

    def toggle_speech_popup(self, sender):
        self.config.antigravity.show_speech_popup = not self.config.antigravity.show_speech_popup
        sender.state = 1 if self.config.antigravity.show_speech_popup else 0
        save_config(self.config)

    def preview_speech_popup(self, _=None):
        """Display a preview of the Native Agent Speech Pop-up."""
        if hasattr(self, "speech_hud") and self.speech_hud:
            _, resolved_voice, _ = self.config.resolve_voice("antigravity")
            from voicefi.tts import find_persona
            persona = find_persona(resolved_voice)
            pname = persona.name if persona else resolved_voice
            self.speech_hud.show_speech(
                "Hello! This is your live agent speech pop-up HUD. It displays what the agent is saying in real-time.",
                agent_name="Antigravity",
                persona_name=pname,
                is_speaking=True,
                position=getattr(self.config.antigravity, "speech_popup_position", "top_center"),
            )
            # Finish after 3.5 seconds
            def _finish():
                time.sleep(3.5)
                self.speech_hud.finish_speech(linger_seconds=3.0)
            threading.Thread(target=_finish, daemon=True).start()

    def toggle_barge_in(self, sender):
        from voicefi.ui.notifications import show_notification
        if self.config.vad.barge_in in (True, "auto"):
            self.config.vad.barge_in = False
            show_notification(
                "VoiceFi Active Barge-In",
                "Barge-In Disabled",
                "AI agents will speak responses completely uninterrupted.",
            )
        else:
            self.config.vad.barge_in = "auto"
            from voicefi.audio.device import is_headphone_or_headset_active
            if is_headphone_or_headset_active():
                show_notification(
                    "VoiceFi Active Barge-In",
                    "Barge-In Enabled ⚡",
                    "Hands-free voice interruption active with headphones.",
                )
            else:
                show_notification(
                    "VoiceFi Active Barge-In",
                    "⚠️ Headphones Recommended",
                    "Barge-in works best with headphones. On laptop speakers, acoustic bleed may cause voice cutoffs.",
                )
        sender.state = 1 if self.config.vad.barge_in in (True, "auto") else 0
        save_config(self.config)

    def open_config_file(self, _):
        path = get_default_config_path()
        if not path.is_file():
            save_config(self.config)
        subprocess.run(["open", str(path)])

    def trigger_manual_listen(self, ptt_mode: bool = False):
        with self._listen_lock:
            if self._current_status in ("listening", "hearing", "transcribing", "ptt_listening", "paused_agent_speaking"):
                return
            self._current_status = "ptt_listening" if ptt_mode else "listening"

        hud = UnifiedDynamicIslandHUD.get_instance()
        if self.config.global_hotkey.show_dictation_hud:
            hud.set_listening(user_name=getattr(self.config, "user_name", "Jake"))

        stop_all_speech()
        if self.watcher:
            self.watcher.interrupt()

        self._ptt_stop_event = threading.Event()

        def _worker():
            temp_wav = None
            try:
                if self.config.audio_cues.enabled:
                    play_chime("start", block=False)
                time.sleep(0.25)

                recorder = AudioRecorder(
                    sample_rate=self.config.vad.sample_rate,
                    energy_threshold=self.config.vad.energy_threshold,
                    silence_duration=self.config.vad.silence_duration,
                )
                self.active_recorder = recorder

                def _on_pause(is_paused: bool):
                    if is_paused:
                        self._current_status = "paused_agent_speaking"
                        hud.show_paused("⏸️ Agent Speaking (Paused)...")
                    else:
                        self._current_status = "ptt_listening" if ptt_mode else "listening"
                        hud.set_listening(user_name=getattr(self.config, "user_name", "Jake"))

                def _on_live(txt: str):
                    hud.update_live_transcription(txt, user_name=getattr(self.config, "user_name", "Jake"))

                if ptt_mode:
                    audio_data, temp_wav = recorder.record_push_to_talk(
                        stop_event=self._ptt_stop_event,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        ptt_release_delay_ms=self.config.vad.ptt_release_delay_ms,
                    )
                else:
                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=lambda: setattr(self, "_current_status", "hearing"),
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        stop_event=self._ptt_stop_event,
                    )

                self.active_recorder = None
                self._current_status = "transcribing"
                hud.show_transcribing()

                stt = get_stt_engine(self.config)
                text = stt.transcribe(temp_wav)
                if text and text.strip():
                    is_auto_send = getattr(getattr(self.config, "hud", None), "auto_send", True)

                    def _inject_action(payload_text: str):
                        injected = inject_text_to_active_app(
                            payload_text,
                            submit_enter=False,
                            preserve_clipboard=self.config.global_hotkey.preserve_clipboard,
                        )
                        if injected:
                            hud.show_done(preview_text=payload_text[:20])
                            if self.config.audio_cues.enabled:
                                play_chime(self.config.audio_cues.sent_chime, block=False)
                            try:
                                rumps.notification("VoiceFi", "Transcribed", payload_text[:80])
                            except Exception:
                                pass

                    if is_auto_send:
                        _inject_action(text)
                    else:
                        hud.set_editing(text, on_submit=_inject_action, target_name="Universal Dictation")
                else:
                    if hud.persistent:
                        hud.set_idle()
                    else:
                        hud.hide()
            except Exception as e:
                print(f"[VoiceFi] Error in manual listen: {e}")
                if hud.persistent:
                    hud.set_idle()
                else:
                    hud.hide()
            finally:
                if temp_wav and isinstance(temp_wav, Path):
                    temp_wav.unlink(missing_ok=True)
                self.active_recorder = None
                self._current_status = "idle"
                self._key_down_times.clear()

        threading.Thread(target=_worker, daemon=True).start()


_lock_file = None


def run_tray():
    """Launch the macOS Tray application (ensuring a single instance)."""
    global _lock_file
    import fcntl
    import sys
    lock_file_path = "/tmp/voicefi_tray.lock"
    try:
        _lock_file = open(lock_file_path, "w")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, BlockingIOError):
        print("⚠️ VoiceFi tray companion is already running.")
        sys.exit(0)

    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

    app = VoiceFiTrayApp()
    app.run()
