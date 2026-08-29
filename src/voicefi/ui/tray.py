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
from voicefi.tts.base import is_agent_speaking, is_system_audio_playing
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.injector import (
    inject_text_to_active_app,
    focus_antigravity,
    open_accessibility_settings,
    send_message_to_antigravity,
    send_message_to_agent,
)
from voicefi.integrations.watcher import TranscriptWatcher
from voicefi.integrations.discovery import AgentToolDetector
from voicefi.ui.hub import ConversationHubWindow
from voicefi.ui.dictation_hud import DictationHUD
from voicefi.ui.speech_hud import AgentSpeechHUD
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

VOICEFI_MENU_BAR_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="90 20 332 440" width="100%" height="100%">
  <!-- VoiceFi Master Mark: macOS Menu Bar Template Icon -->
  <g transform="translate(0, 15)">
    <!-- 1. ELECTRIC WI-FI BROADCAST HAT -->
    <g fill="none" stroke="#000000" stroke-linecap="round">
      <path d="M 152 145 A 120 120 0 0 1 360 145" stroke-width="22" />
      <path d="M 184 180 A 80 80 0 0 1 328 180" stroke-width="20" />
      <path d="M 216 215 A 42 42 0 0 1 296 215" stroke-width="18" />
    </g>

    <!-- 2. MINIMALIST CYBER FACE -->
    <g stroke="#000000" stroke-linecap="round">
      <line x1="202" y1="262" x2="234" y2="262" stroke-width="12" />
      <line x1="278" y1="262" x2="310" y2="262" stroke-width="12" />
    </g>

    <!-- 3. USB-C PORT NOSE -->
    <g>
      <rect x="238" y="278" width="36" height="15" rx="7.5" fill="none" stroke="#000000" stroke-width="5" />
      <line x1="246" y1="285.5" x2="266" y2="285.5" stroke="#000000" stroke-width="4.5" stroke-linecap="round" />
    </g>

    <!-- WAVEFORM SMILE -->
    <path d="M 230 320 Q 256 342 282 320" fill="none" stroke="#000000" stroke-width="8" stroke-linecap="round" />

    <!-- 4. CRADLE & PLUG BASE -->
    <path d="M 124 220 C 124 350, 175 385, 256 385 C 337 385, 388 350, 388 220" 
          fill="none" 
          stroke="#000000" 
          stroke-width="18" 
          stroke-linecap="round" />

    <!-- PLUG PRONGS -->
    <g>
      <rect x="110" y="205" width="28" height="30" rx="6" fill="none" stroke="#000000" stroke-width="5" />
      <circle cx="124" cy="220" r="4.5" fill="#000000" />

      <rect x="374" y="205" width="28" height="30" rx="6" fill="none" stroke="#000000" stroke-width="5" />
      <circle cx="388" cy="220" r="4.5" fill="#000000" />
    </g>

    <!-- STEM & FOOT BASE -->
    <line x1="256" y1="385" x2="256" y2="430" stroke="#000000" stroke-width="18" stroke-linecap="round" />
    <line x1="190" y1="430" x2="322" y2="430" stroke="#000000" stroke-width="18" stroke-linecap="round" />
  </g>
</svg>"""


def get_voicefi_tray_image():
    """Load and return an NSImage of the VoiceFi master mark sized for the macOS menu bar."""
    try:
        import AppKit
        from pathlib import Path

        search_paths = [
            Path(__file__).resolve().parent.parent.parent.parent / "assets" / "voicefi-menu-bar-icon.svg",
            Path(__file__).resolve().parent.parent / "assets" / "voicefi-menu-bar-icon.svg",
            Path.home() / ".voicefi" / "assets" / "voicefi-menu-bar-icon.svg",
        ]

        image = None
        for p in search_paths:
            if p.is_file():
                try:
                    image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(p))
                    if image and image.isValid():
                        break
                except Exception:
                    pass

        if image is None or not image.isValid():
            svg_bytes = VOICEFI_MENU_BAR_ICON_SVG.encode("utf-8")
            data = AppKit.NSData.dataWithBytes_length_(svg_bytes, len(svg_bytes))
            image = AppKit.NSImage.alloc().initWithData_(data)

        if image:
            image.setTemplate_(True)
            thickness = AppKit.NSStatusBar.systemStatusBar().thickness()
            target_height = thickness - 4
            if target_height <= 0:
                target_height = 18.0
            if image.size().height > target_height:
                ratio = target_height / image.size().height
                new_size = AppKit.NSMakeSize(image.size().width * ratio, target_height)
                image.setSize_(new_size)

        return image
    except Exception as e:
        print(f"[VoiceFi] Error creating menu bar image: {e}")
        return None


class VoiceFiTrayApp(rumps.App):
    """macOS Status Bar Menu Application for VoiceFi."""

    def __init__(self):
        super(VoiceFiTrayApp, self).__init__("VoiceFi", icon=None, title="")
        self.title = ""
        default_img = get_voicefi_tray_image()
        if default_img:
            self._icon_nsimage = default_img
            self._current_symbol = "wifi"
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

        # Start Native Antigravity Mic / Input Observer if enabled
        try:
            from voicefi.integrations.input_observer import NativeAntigravityInputObserver
            self.input_observer = NativeAntigravityInputObserver(self.config)
            self.input_observer.start()
        except Exception as e:
            print(f"[Tray] Antigravity input observer failed to start: {e}")

        # Start companion server if enabled
        companion_cfg = getattr(self.config, "companion", None)
        if getattr(companion_cfg, "enabled", True):
            self._ensure_companion_server_running()

        # Pre-warm STT in background thread for instant sub-300ms transcription
        def _warm_stt_bg():
            try:
                import numpy as np
                from voicefi.stt import get_stt_engine
                stt_eng = get_stt_engine(self.config)
                stt_eng.transcribe(np.zeros(1600, dtype=np.float32))
            except Exception:
                pass
        threading.Thread(target=_warm_stt_bg, daemon=True, name="STTWarmup").start()

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
            
        try:
            from voicefi.audio.monitor import LiveVADMonitor
            LiveVADMonitor.get_instance().start()
        except ImportError as e:
            print(f"[Tray] LiveVADMonitor failed to start: {e}")

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

        self.quick_controls_item = rumps.MenuItem("⚙️ HUD Quick Controls...", callback=self.open_quick_controls_ui)

        self.auto_listen_item = rumps.MenuItem(
            "⚡ ProActive Listening (Auto Turn-Taking)",
            callback=self.toggle_auto_listen,
        )
        self.auto_listen_item.state = 1 if self.config.proactive.feedback_loop.enabled else 0

        # Fibonacci Pause Delay Submenu
        self.pause_delay_menu = rumps.MenuItem("⏱️ Pause Delay (Fibonacci)")
        self._build_pause_delay_submenu()

        self.meeting_item = rumps.MenuItem(
            "👥 ProActive Meeting Assistant...",
            callback=self.toggle_meeting_assistant,
        )
        self.meeting_item.state = 1 if self.config.proactive.meeting_assistant.enabled else 0

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
        self._update_barge_in_menu_item()

        # Voice Control Panel & Mobile Companion
        self.panel_item = rumps.MenuItem("🎛️ Voice Control Panel...", callback=self.open_control_panel_ui)
        self.companion_item = rumps.MenuItem("📱 Mobile Companion (QR Code)...", callback=self.open_mobile_companion)

        # Voice Personas Submenu (Quick Selection)
        self.voice_personas_menu = rumps.MenuItem("🎭 A Voice For Every Agent")
        self._build_personas_submenu()

        # Dynamic Island HUD Submenu
        self.hud_menu = rumps.MenuItem("🏝️ Dynamic Island HUD")
        self._build_hud_submenu()

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
        if tier_info.get("is_licensed"):
            self.tier_item = rumps.MenuItem("⚡ Tier: Pro (Licensed)", callback=self.open_pricing_page)
        elif tier_info.get("is_trial"):
            days = tier_info.get("trial_days_remaining", 14)
            self.tier_item = rumps.MenuItem(f"✨ Pro Trial: {days}d left (Upgrade $9/mo · $69/yr)", callback=self.open_pricing_page)
        elif tier_info.get("trial_expired"):
            self.tier_item = rumps.MenuItem("⚪ Tier: Community ($0) • Upgrade to Pro...", callback=self.open_pricing_page)
        else:
            self.tier_item = rumps.MenuItem(f"Tier: {tier_info['tier']}", callback=self.open_pricing_page)

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
            self.quick_controls_item,
            self.voice_personas_menu,
            self.hud_menu,
            self.pause_delay_menu,
            self.troubleshoot_menu,
            self.integrations_menu,
            self.voice_mode_menu,
            rumps.separator,
            self.auto_listen_item,
            self.read_summary_item,
            self.barge_in_item,
            rumps.separator,
            rumps.MenuItem("🔐 Grant Permissions (Auto-Paste)", callback=self.open_permissions),
            rumps.MenuItem("⚙️ Open Config File", callback=self.open_config_file),
            self.tier_item,
            rumps.separator,
        ]

        self._update_barge_in_menu_item()

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
        if threading.current_thread() is not threading.main_thread():
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(self._build_conversations_submenu)
            except Exception:
                pass
            return

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

        chatgpt_status = "Connected ✅" if detected["chatgpt"]["detected"] else "Available"
        self.item_chatgpt = rumps.MenuItem(f"ChatGPT for Mac ({chatgpt_status})", callback=None)
        self.item_chatgpt.state = 1 if getattr(self.config.integrations, "chatgpt", True) else 0

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
            self.item_chatgpt,
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

    def _build_pause_delay_submenu(self):
        """Populate Fibonacci Pause Delay presets (1s, 2s, 3s, 5s, 8s, 11s)."""
        from voicefi.config import FIBONACCI_PAUSE_DELAYS
        current = float(getattr(self.config.vad, "silence_duration", 1.4))
        presets = [
            (1.0, "1s (Snappy Rapid-Fire)"),
            (2.0, "2s (Conversational)"),
            (3.0, "3s (Deliberate)"),
            (5.0, "5s (Deep Thinker)"),
            (8.0, "8s (Pacing & Brainstorming)"),
            (11.0, "11s (Monologue / Memo)"),
        ]
        items = []
        for val, label in presets:
            def _make_cb(v):
                def _cb(_):
                    self.config.vad.silence_duration = v
                    save_config(self.config)
                    self._build_pause_delay_submenu()
                    try:
                        rumps.notification("VoiceFi", "Pause Delay Updated", f"Cadence set to {int(v)}s")
                    except Exception:
                        pass
                return _cb
            item = rumps.MenuItem(label, callback=_make_cb(val))
            item.state = 1 if abs(current - val) < 0.35 else 0
            items.append(item)
        self.pause_delay_menu.update(items)

    def open_quick_controls_ui(self, _=None):
        """Open native HUD Quick Controls panel."""
        try:
            from voicefi.ui.quick_controls import HUDQuickControlsPanel
            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
            hud = UnifiedDynamicIslandHUD.get_instance()
            hud_rect = hud._panel.frame() if hud._panel else None
            HUDQuickControlsPanel.get_instance().toggle(relative_to_rect=hud_rect)
        except Exception as e:
            print(f"[Tray] Error opening quick controls: {e}")

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
        port = getattr(getattr(self, "config", None), "companion", None) and self.config.companion.port or 5141
        urls = get_companion_urls(port=port)
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
            from voicefi.companion.relay_client import RelayClient, RelaySessionCredentials
            from aiohttp import web
            import asyncio
            port = getattr(getattr(self, "config", None), "companion", None) and self.config.companion.port or 5141
            try:
                server = CompanionServer(config=self.config, port=port, host="0.0.0.0")
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                server.loop = loop
                server._start_watcher_thread()

                # Connect to Cloudflare Durable Objects WebSocket Relay
                creds = RelaySessionCredentials.load_or_create()
                relay_client = RelayClient(credentials=creds, relay_url="wss://companion.voicefi.app/v1/relay", local_port=port)
                server.relay_client = relay_client
                loop.run_until_complete(relay_client.start())

                app_runner = web.AppRunner(server.app)
                loop.run_until_complete(app_runner.setup())
                site = web.TCPSite(app_runner, "0.0.0.0", port)
                loop.run_until_complete(site.start())
                loop.run_forever()
            except OSError as e:
                # Port already bound by another process; attach relay client
                try:
                    creds = RelaySessionCredentials.load_or_create()
                    relay_client = RelayClient(credentials=creds, relay_url="wss://companion.voicefi.app/v1/relay", local_port=port)
                    relay_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(relay_loop)
                    relay_loop.run_until_complete(relay_client.start())
                    relay_loop.run_forever()
                except Exception:
                    pass
            except Exception as e:
                print(f"[TrayApp] Companion server notice: {e}")

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
                    self.config.tts.voice = persona_obj.id
                    self.config.tts.provider = persona_obj.provider
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
        items.append(rumps.MenuItem("⚡ Download Ava (0ms Offline Speech)...", callback=self.trigger_download_ava))
        items.append(rumps.MenuItem("🎛️ Open Full Control Panel...", callback=self.open_control_panel_ui))
        self.voice_personas_menu.update(items)

    def trigger_download_ava(self, _):
        """Open macOS Spoken Content settings to download Apple's Ava (Premium) neural voice."""
        from voicefi.tts.offline import open_spoken_content_settings
        open_spoken_content_settings()
        try:
            rumps.notification(
                "VoiceFi",
                "Download Ava (0ms Offline)",
                "Opened System Settings > Spoken Content. Click 'Manage Voices...' and download Ava (Premium).",
            )
        except Exception:
            pass

    def _build_hud_submenu(self):
        """Populate dedicated Dynamic Island HUD submenu with controls, position presets, and state previews."""
        hud_cfg = getattr(self.config, "hud", None)
        if hud_cfg is None:
            from voicefi.config import HUDConfig
            hud_cfg = HUDConfig()
            self.config.hud = hud_cfg

        items = []

        # 1. Main Enable Toggle
        item_enabled = rumps.MenuItem(
            "🟢 Enable Dynamic Island HUD",
            callback=self.toggle_hud_enabled,
        )
        item_enabled.state = 1 if hud_cfg.enabled else 0
        items.append(item_enabled)

        # 2. Persistent Mode (Always Visible Resting Pill)
        item_persistent = rumps.MenuItem(
            "📌 Persistent Resting Pill (Always Visible)",
            callback=self.toggle_persistent_hud,
        )
        item_persistent.state = 1 if hud_cfg.persistent else 0
        items.append(item_persistent)

        # 3. Prompt Delivery Mode (Instant Auto-Send vs Review & Edit)
        item_auto_send = rumps.MenuItem(
            "⚡ Auto-Send Prompts (Instant)",
            callback=self.toggle_auto_send,
        )
        item_auto_send.state = 1 if hud_cfg.auto_send else 0
        items.append(item_auto_send)

        # 4. Full-Screen Overlay
        item_fs = rumps.MenuItem(
            "🎮 Always on Top of Full-Screen Apps",
            callback=self.toggle_fullscreen_overlay,
        )
        item_fs.state = 1 if getattr(hud_cfg, "fullscreen_overlay", True) else 0
        items.append(item_fs)

        # 5. Live Typing Stream
        item_typing = rumps.MenuItem(
            "✍️ Live Dictation Typing Stream",
            callback=self.toggle_live_transcript,
        )
        item_typing.state = 1 if getattr(hud_cfg, "show_live_transcript", True) else 0
        items.append(item_typing)

        # 6. Speech Subtitles Pop-up
        item_speech = rumps.MenuItem(
            "🔊 Show Speech Subtitles & Waveforms",
            callback=self.toggle_speech_popup,
        )
        item_speech.state = 1 if getattr(self.config.antigravity, "show_speech_popup", True) else 0
        items.append(item_speech)

        items.append(rumps.separator)

        # 7. Screen Positioning Submenu
        pos_menu = rumps.MenuItem("📍 Screen Position")
        cur_pos = getattr(hud_cfg, "position", "top_right")

        def _make_pos_cb(pos_key):
            def _cb(_):
                if not hasattr(self.config, "hud") or self.config.hud is None:
                    from voicefi.config import HUDConfig
                    self.config.hud = HUDConfig()
                self.config.hud.position = pos_key
                save_config(self.config)
                hud = UnifiedDynamicIslandHUD.get_instance()
                if hasattr(hud, "set_position"):
                    hud.set_position(pos_key)
                else:
                    hud.reset_position()
                self._build_hud_submenu()
                try:
                    labels = {"top_right": "Top Right", "top_center": "Top Center (Notch)", "bottom_right": "Bottom Right"}
                    rumps.notification("VoiceFi HUD", "Position Updated", f"Anchored to {labels.get(pos_key, pos_key)}")
                except Exception:
                    pass
            return _cb

        pos_tr = rumps.MenuItem("📍 Top Right (Default • Clears Chrome Tabs)", callback=_make_pos_cb("top_right"))
        pos_tr.state = 1 if cur_pos == "top_right" else 0
        pos_tc = rumps.MenuItem("📍 Top Center (MacBook Camera Notch)", callback=_make_pos_cb("top_center"))
        pos_tc.state = 1 if cur_pos == "top_center" else 0
        pos_br = rumps.MenuItem("📍 Bottom Right", callback=_make_pos_cb("bottom_right"))
        pos_br.state = 1 if cur_pos == "bottom_right" else 0

        pos_menu.update([
            pos_tr,
            pos_tc,
            pos_br,
            rumps.separator,
            rumps.MenuItem("🎯 Reset Position to Default", callback=self.reset_hud_position),
        ])
        items.append(pos_menu)

        items.append(rumps.separator)

        # 8. Interactive State Previews (Audit / Test)
        preview_menu = rumps.MenuItem("✨ Test & Preview States")

        def _make_preview_cb(state_name):
            return lambda _: self.preview_hud_state(state_name)

        preview_menu.update([
            rumps.MenuItem("🟢 Preview Idle Resting Pill (155×34)", callback=_make_preview_cb("idle")),
            rumps.MenuItem("🧠 Preview Thinking Aura (Purple)", callback=_make_preview_cb("thinking")),
            rumps.MenuItem("⚡ Preview Tool Execution (Blue)", callback=_make_preview_cb("working")),
            rumps.MenuItem("🔊 Preview Speaking Subtitles (Cyan)", callback=_make_preview_cb("speaking")),
            rumps.MenuItem("👂 Preview Listening VAD (Emerald)", callback=_make_preview_cb("listening")),
            rumps.MenuItem("✏️ Preview Review & Edit Modal", callback=_make_preview_cb("editing")),
        ])
        items.append(preview_menu)

        items.append(rumps.separator)

        # 9. Debug Studio & Reset
        items.append(rumps.MenuItem("🎯 Reset HUD Position", callback=self.reset_hud_position))
        items.append(rumps.MenuItem("🛠️ Launch HUD Debug Studio (Terminal)...", callback=self.launch_hud_debug_studio))

        self.hud_menu.update(items)

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

        def _toggle_expert_vad(_):
            try:
                from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
                UnifiedDynamicIslandHUD.get_instance().toggle_expert_vad()
            except Exception as e:
                print(f"Error toggling Expert VAD: {e}")

        items = [
            rumps.MenuItem("🎛️ Expert VAD Inspector...", callback=_toggle_expert_vad),
            rumps.separator,
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
        """Called on macOS main runloop every 200ms to redraw menu bar icon and sync HUD state."""
        from voicefi.tts.base import get_agent_speaking_info, get_cross_process_hud_state
        speaking_info = get_agent_speaking_info()
        hud_state = get_cross_process_hud_state()
        is_speaking = bool(speaking_info or (hud_state and hud_state.get("state") == "speaking"))
        was_speaking = getattr(self, "_cross_process_speaking", False)

        if is_speaking:
            self._current_status = "speaking"
            info = speaking_info or (hud_state if (hud_state and hud_state.get("state") == "speaking") else {})
            current_pid = info.get("pid")
            last_pid = getattr(self, "_last_spoken_pid", None)
            if not was_speaking or last_pid != current_pid:
                self._cross_process_speaking = True
                self._last_spoken_pid = current_pid
                hud_cfg = getattr(self.config, "hud", None)
                show_speaking = getattr(self.config.antigravity, "show_speech_popup", True) or getattr(hud_cfg, "enabled", True)
                if show_speaking:
                    self.hud.set_speaking(
                        text=info.get("text", "") or "Speaking aloud...",
                        agent_name=info.get("agent_name", "VoiceFi"),
                        persona_name=info.get("persona_name") or "Viv",
                        linger=None,
                    )
        elif was_speaking and not is_speaking:
            self._cross_process_speaking = False
            self._last_spoken_pid = None
            if self._current_status == "speaking":
                self._current_status = "idle"
            hud_cfg = getattr(self.config, "hud", None)
            show_speaking = getattr(self.config.antigravity, "show_speech_popup", True) or getattr(hud_cfg, "enabled", True)
            if show_speaking:
                linger = getattr(self.config.antigravity, "speech_popup_linger_seconds", 1.5)
                self.hud.finish_speech(linger_seconds=linger)
        elif hud_state and not is_speaking:
            ext_state = hud_state.get("state")
            ext_pid = hud_state.get("pid")
            last_ext_sig = getattr(self, "_last_ext_hud_sig", None)
            current_ext_sig = f"{ext_pid}:{ext_state}:{hud_state.get('text', '')}:{hud_state.get('detail', '')}"
            if last_ext_sig != current_ext_sig:
                self._last_ext_hud_sig = current_ext_sig
                self._current_status = ext_state
                hud_cfg = getattr(self.config, "hud", None)
                if getattr(hud_cfg, "enabled", True):
                    self.handle_state_change(
                        ext_state,
                        text=hud_state.get("text", ""),
                        detail=hud_state.get("detail", ""),
                        tool_action=hud_state.get("tool_action", ""),
                        tag_text=hud_state.get("tag_text"),
                        agent_name=hud_state.get("agent_name", "Antigravity"),
                        persona_name=hud_state.get("persona_name"),
                        user_name=hud_state.get("user_name", getattr(self.config, "user_name", "Jake")),
                        live_stream=hud_state.get("live_stream", False),
                    )
        elif not hud_state and getattr(self, "_last_ext_hud_sig", None) is not None:
            self._last_ext_hud_sig = None
            if self._current_status not in ("idle", "speaking"):
                self.handle_state_change("idle")

        status_map = {
            "speaking": "speaker.wave.2.fill",
            "listening": "mic.fill",
            "hearing": "waveform.circle.fill",
            "transcribing": "ellipsis.bubble",
            "ptt_listening": "mic.fill",
            "paused_agent_speaking": "pause.fill",
            "paused": "pause.fill",
        }
        
        symbol_name = "voicefi"

        if self._current_status in status_map:
            symbol_name = status_map[self._current_status]
        else:
            symbol_name = "voicefi"

        # Ensure no text title appears next to the menu bar icon
        if hasattr(self, '_nsapp') and hasattr(self._nsapp, 'nsstatusitem'):
            try:
                if self._nsapp.nsstatusitem.title():
                    self._nsapp.nsstatusitem.setTitle_("")
            except Exception:
                pass

        current_symbol = getattr(self, "_current_symbol", None)
        if current_symbol != symbol_name:
            self._current_symbol = symbol_name
            try:
                import AppKit
                
                image = None
                if symbol_name in ("wifi", "voicefi"):
                    image = get_voicefi_tray_image()
                
                if image is None:
                    # Fallback to system symbol
                    image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(symbol_name, None)
                    if image:
                        image.setTemplate_(True)
                
                if image:
                    self._icon_nsimage = image
                    if hasattr(self, '_nsapp'):
                        self._nsapp.setStatusBarIcon()
                        if hasattr(self._nsapp, 'nsstatusitem'):
                            self._nsapp.nsstatusitem.setTitle_("")
            except Exception as e:
                print(f"[VoiceFi] Error updating menu bar icon: {e}")
                pass

        # Periodically reload config if changed externally
        self._check_config_reload()

    def _check_config_reload(self):
        """Periodically check config file mtime and reload configuration dynamically."""
        try:
            cfg_path = get_default_config_path()
            if not cfg_path.is_file():
                return
            mtime = cfg_path.stat().st_mtime
            last_mtime = getattr(self, "_last_config_mtime", None)
            if last_mtime is None:
                self._last_config_mtime = mtime
                return
            if mtime > last_mtime:
                self._last_config_mtime = mtime
                self.config = load_config()
                self.hud.config = self.config
                hud_cfg = getattr(self.config, "hud", None)
                if hud_cfg:
                    self.hud.set_fullscreen_overlay(getattr(hud_cfg, "fullscreen_overlay", True))
                    self.hud.set_auto_send(getattr(hud_cfg, "auto_send", True))
                    is_enabled = getattr(hud_cfg, "enabled", True)
                    is_persistent = getattr(hud_cfg, "persistent", True)
                    self.hud.persistent = is_persistent
                    if self.hud._user_dragged_center_x is None:
                        self.hud._position_top_right()
                    if is_enabled and is_persistent:
                        if self.hud._current_state == "idle" or not self.hud._is_visible:
                            self.hud.set_idle()
                    elif not is_enabled:
                        self.hud.force_hide()
                    elif not is_persistent and self.hud._current_state == "idle":
                        self.hud.force_hide()

                if hasattr(self, "persistent_hud_item") and hud_cfg:
                    self.persistent_hud_item.state = 1 if getattr(hud_cfg, "persistent", True) else 0
                if hasattr(self, "fullscreen_overlay_item") and hud_cfg:
                    self.fullscreen_overlay_item.state = 1 if getattr(hud_cfg, "fullscreen_overlay", True) else 0
                if hasattr(self, "auto_send_item") and hud_cfg:
                    self.auto_send_item.state = 1 if getattr(hud_cfg, "auto_send", True) else 0
                if hasattr(self, "auto_listen_item"):
                    self.auto_listen_item.state = 1 if self.config.antigravity.auto_listen else 0
                if hasattr(self, "read_summary_item"):
                    self.read_summary_item.state = 1 if self.config.antigravity.read_summary_aloud else 0
                if hasattr(self, "speech_popup_item"):
                    self.speech_popup_item.state = 1 if self.config.antigravity.show_speech_popup else 0
                self._update_barge_in_menu_item()
        except Exception:
            pass

    def _update_barge_in_menu_item(self):
        """Update barge-in menu item label with live device-aware status."""
        try:
            from voicefi.audio.device import is_headphone_or_headset_active
            from voicefi.audio.recorder import resolve_barge_in_mode
            barge_setting = getattr(self.config.vad, "barge_in", "auto")
            is_active, is_safe = resolve_barge_in_mode(barge_setting)

            if not hasattr(self, "barge_in_item") or not self.barge_in_item:
                return

            if barge_setting == "auto":
                if is_headphone_or_headset_active():
                    self.barge_in_item.title = "🎧 Voice Barge-In (Auto • Active on Headphones)"
                    self.barge_in_item.state = 1
                else:
                    self.barge_in_item.title = "🔇 Voice Barge-In (Auto • Paused on Laptop Speakers)"
                    self.barge_in_item.state = 0
            elif barge_setting is True:
                self.barge_in_item.title = "⚡ Voice Barge-In (Forced ON • Active)"
                self.barge_in_item.state = 1
            else:
                self.barge_in_item.title = "⚪ Voice Barge-In (Disabled)"
                self.barge_in_item.state = 0
        except Exception:
            pass

    def handle_state_change(self, state: str, **kwargs):
        """Thread-safe state change handler."""
        self._current_status = state
        if hasattr(self, "hub") and self.hub:
            self.hub.refresh()
        try:
            hud = UnifiedDynamicIslandHUD.get_instance()
            if state == "idle":
                hud.set_idle(linger=kwargs.get("linger", 1.5))
            elif state in ("listening", "ptt_listening"):
                hud.set_listening(
                    prompt_preview=kwargs.get("text", ""),
                    user_name=kwargs.get("user_name", getattr(self.config, "user_name", "Jake")),
                    live_stream=kwargs.get("live_stream", False),
                )
            elif state == "hearing":
                hud.set_hearing(
                    prompt_preview=kwargs.get("text", ""),
                    user_name=kwargs.get("user_name", getattr(self.config, "user_name", "Jake")),
                )
            elif state == "speaking":
                hud.set_speaking(
                    text=kwargs.get("text", "") or "Speaking aloud...",
                    agent_name=kwargs.get("agent_name", "Antigravity"),
                    persona_name=kwargs.get("persona_name"),
                    linger=kwargs.get("linger"),
                )
            elif state == "thinking":
                hud.set_thinking(
                    agent_name=kwargs.get("agent_name", "Antigravity"),
                    detail=kwargs.get("detail", "Thinking..."),
                )
            elif state == "working":
                hud.set_working(
                    agent_name=kwargs.get("agent_name", "Antigravity"),
                    tool_action=kwargs.get("tool_action", "Running tools..."),
                    tag_text=kwargs.get("tag_text"),
                )
            elif state == "user_prompt":
                hud.set_user_prompt(
                    prompt=kwargs.get("prompt", ""),
                    user_name=kwargs.get("user_name", getattr(self.config, "user_name", "Jake")),
                    source=kwargs.get("source", "Antigravity (⌃M)"),
                    linger=kwargs.get("linger", 1.8),
                )
            elif state in ("paused", "paused_agent_speaking"):
                hud.show_paused(kwargs.get("message", "Agent Speaking (Paused)..."))
            elif state == "transcribing":
                hud.show_transcribing()
            elif state == "done":
                hud.show_done(preview_text=kwargs.get("text", ""))
            elif state == "new_conversation":
                hud.set_new_conversation(
                    prompt_preview=kwargs.get("text", ""),
                    user_name=kwargs.get("user_name", getattr(self.config, "user_name", "Jake")),
                    agent_name=kwargs.get("agent_name", "Antigravity"),
                    live_stream=kwargs.get("live_stream", False),
                )
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

    def handle_escape_press(self, _=None):
        """
        Handle Escape key press.
        If an AI agent is currently speaking aloud:
          - Stops speech synthesis immediately.
          - If auto_listen is ON (antigravity/claude), triggers/opens the microphone immediately for user reply.
          - If auto_listen is OFF, resets to idle.
        If the microphone was actively recording user speech (or in dictation/PTT):
          - Cancels recording, discards captured audio, and returns to idle.
        """
        speaking = is_agent_speaking() or is_system_audio_playing()
        auto_listen_enabled = getattr(self.config.antigravity, "auto_listen", True)

        if speaking:
            print("[VoiceFi] ⏹️ Escape pressed while agent is speaking: stopping speech")
            stop_all_speech()
            if hasattr(self, "speech_hud") and self.speech_hud:
                self.speech_hud.hide()

            if auto_listen_enabled:
                print("[VoiceFi] 🎙️ Auto-listen is ON: opening microphone immediately for user response")
                from voicefi.tts.base import get_cross_process_hud_state
                hud_st = get_cross_process_hud_state()
                has_active_turn = bool(
                    (self.watcher and self.watcher._is_handling_turn)
                    or (hud_st and hud_st.get("state") in ("speaking", "listening", "hearing"))
                )
                if has_active_turn:
                    # The active turn worker (CLI hook or watcher) will automatically transition
                    # to microphone listening now that stop_all_speech() unblocked speech synthesis.
                    pass
                else:
                    is_ptt = (self.config.vad.mode == "ptt")
                    self.trigger_talk_to_antigravity(ptt_mode=is_ptt)
            else:
                if self.watcher:
                    self.watcher.interrupt()
                self._current_status = "idle"
        else:
            print("[VoiceFi] ⏹️ Escape pressed: cancelling recording")
            self.stop_speaking_now()

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
            if self._current_status in ("listening", "hearing", "ptt_listening"):
                self.finish_active_recording()
                return
            if self._current_status in ("transcribing", "paused_agent_speaking"):
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

                def _on_speech_start():
                    self._current_status = "hearing"
                    hud.set_hearing(user_name=getattr(self.config, "user_name", "Jake"))

                def _on_live(txt: str):
                    hud.update_live_transcription(txt, user_name=getattr(self.config, "user_name", "Jake"))

                def _on_tick(energy: float, conf: float = 0.0, is_spk: bool = False):
                    hud.update_audio_level(energy, conf, is_spk)

                if ptt_mode:
                    audio_data, temp_wav = recorder.record_push_to_talk(
                        stop_event=self._ptt_stop_event,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        on_listening_tick=_on_tick,
                        ptt_release_delay_ms=self.config.vad.ptt_release_delay_ms,
                    )
                else:
                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=_on_speech_start,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        on_listening_tick=_on_tick,
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
                        send_message_to_agent(conv_id=conv_id, text=payload_text, sender_name=self.config.user_name)
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
            if self._current_status in ("listening", "hearing", "ptt_listening", "new_conversation"):
                self.finish_active_recording()
                return
            if self._current_status in ("transcribing", "paused_agent_speaking"):
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

                def _on_speech_start():
                    self._current_status = "hearing"
                    hud.set_hearing(user_name=getattr(self.config, "user_name", "Jake"))

                def _on_live(txt: str):
                    hud.update_live_transcription(txt, user_name=getattr(self.config, "user_name", "Jake"), is_new_conversation=True)

                def _on_tick(energy: float, conf: float = 0.0, is_spk: bool = False):
                    hud.update_audio_level(energy, conf, is_spk)

                if ptt_mode:
                    audio_data, temp_wav = recorder.record_push_to_talk(
                        stop_event=self._ptt_stop_event,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        on_listening_tick=_on_tick,
                        ptt_release_delay_ms=self.config.vad.ptt_release_delay_ms,
                    )
                else:
                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=_on_speech_start,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        on_listening_tick=_on_tick,
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

                        # 1. Escape: stop speech (and open mic if auto_listen is ON) or cancel recording
                        from voicefi.tts.base import is_escape_key
                        if is_escape_key(key):
                            self.handle_escape_press()
                            return

                        # 2. Enter while recording: finish active recording immediately
                        is_recording = (
                            self._current_status in ("listening", "hearing", "ptt_listening", "new_conversation")
                            or self.active_recorder is not None
                        )
                        if is_recording and (key == Key.enter or vk in (36, 76)):
                            self.finish_active_recording()
                            return

                        # 3. New Conversation with Connected Tools (Cmd+Shift+N or Ctrl+Shift+N)
                        if mod and shift and (vk == 45 or char in ('n', 'N', '\x0e')):
                            if self.config.global_hotkey.enabled and _debounce('new_conv'):
                                self._key_down_times['new_conv'] = time.time()
                                is_ptt = (self.config.vad.mode == "ptt")
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
                        if ctrl and not shift and (vk == 17 or char in ('t', 'T', '\x14')):
                            if self.config.global_hotkey.enabled and _debounce('dictate'):
                                self._key_down_times['dictate'] = time.time()
                                is_ptt = (self.config.vad.mode == "ptt")
                                self.trigger_manual_listen(ptt_mode=is_ptt)
                            return

                        # 7. Respond to Agent (Ctrl+R)
                        if ctrl and not shift and (vk == 15 or char in ('r', 'R', '\x12')):
                            if self.config.global_hotkey.enabled and _debounce('respond'):
                                self._key_down_times['respond'] = time.time()
                                is_ptt = (self.config.vad.mode == "ptt")
                                self.trigger_talk_to_antigravity(ptt_mode=is_ptt)
                            return
                    except Exception as e:
                        print(f"[Tray] Hotkey press notice: {e}")

                def on_release(key):
                    try:
                        is_ctrl = key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r)
                        is_cmd = key in (Key.cmd, Key.cmd_l, Key.cmd_r)
                        is_shift = key in (Key.shift, Key.shift_l, Key.shift_r)
                        is_alt = key in (Key.alt, Key.alt_l, Key.alt_r)

                        if is_ctrl:
                            modifiers.discard('ctrl')
                        elif is_cmd:
                            modifiers.discard('cmd')
                        elif is_shift:
                            modifiers.discard('shift')
                        elif is_alt:
                            modifiers.discard('alt')

                        vk = getattr(key, 'vk', None)
                        char = getattr(key, 'char', None)

                        is_respond_key = (vk == 15 or char in ('r', 'R', '\x12'))
                        is_dictate_key = (vk == 17 or char in ('t', 'T', '\x14'))
                        is_new_conv_key = (vk == 45 or char in ('n', 'N', '\x0e'))
                        is_action_key = is_respond_key or is_dictate_key or is_new_conv_key
                        is_modifier_release = is_ctrl or is_cmd

                        is_active_recording = (
                            self._current_status in ("listening", "hearing", "ptt_listening", "new_conversation")
                            or self.active_recorder is not None
                        )

                        if is_active_recording:
                            # If pure PTT mode: any release of the trigger key or modifier stops recording
                            if self.config.vad.mode == "ptt" and (is_action_key or is_modifier_release):
                                self.finish_active_recording()
                            # If hybrid mode (Tap=Auto / Hold=PTT):
                            elif self.config.vad.mode == "hybrid" and (is_action_key or is_modifier_release):
                                down_time = None
                                for act in ('respond', 'dictate', 'new_conv'):
                                    if act in self._key_down_times:
                                        down_time = self._key_down_times.get(act)
                                        break

                                # If held down longer than 350ms (hold gesture), treat as PTT release
                                if down_time and (time.time() - down_time) >= 0.35:
                                    self.finish_active_recording()
                                # If released quickly (<350ms), it's a tap -> leave Auto-VAD running!

                        if is_action_key or is_modifier_release:
                            self._key_down_times.clear()
                    except Exception as e:
                        print(f"[Tray] Hotkey release notice: {e}")

                listener = keyboard.Listener(on_press=on_press, on_release=on_release)
                listener.daemon = True
                listener.start()
                print("[VoiceFi] ⌨️ Unified global hotkeys active: Cmd+Shift+N (New Conv), Ctrl+R (Respond), Ctrl+J / Cmd+J (Jump), Ctrl+T (Dictate), Ctrl+Shift+J (Hub)")
            except Exception as e:
                print(f"[Tray] Hotkey listener notice: {e}")

        threading.Thread(target=_run_pynput, daemon=True).start()

    def toggle_hud_enabled(self, sender=None):
        hud = UnifiedDynamicIslandHUD.get_instance()
        if not hasattr(self.config, "hud") or self.config.hud is None:
            from voicefi.config import HUDConfig
            self.config.hud = HUDConfig()
        new_val = not self.config.hud.enabled
        self.config.hud.enabled = new_val
        save_config(self.config)
        if new_val:
            hud.set_persistent(self.config.hud.persistent)
            hud.set_idle()
        else:
            hud.force_hide()
        self._build_hud_submenu()

    def toggle_persistent_hud(self, sender=None):
        hud = UnifiedDynamicIslandHUD.get_instance()
        new_val = not getattr(getattr(self.config, "hud", None), "persistent", True)
        if not hasattr(self.config, "hud") or self.config.hud is None:
            from voicefi.config import HUDConfig
            self.config.hud = HUDConfig()
        self.config.hud.persistent = new_val
        self.config.antigravity.persistent_hud = new_val
        if sender and hasattr(sender, "state"):
            sender.state = 1 if new_val else 0
        hud.set_persistent(new_val)
        save_config(self.config)
        self._build_hud_submenu()

    def toggle_fullscreen_overlay(self, sender=None):
        hud = UnifiedDynamicIslandHUD.get_instance()
        new_val = not getattr(getattr(self.config, "hud", None), "fullscreen_overlay", True)
        if not hasattr(self.config, "hud") or self.config.hud is None:
            from voicefi.config import HUDConfig
            self.config.hud = HUDConfig()
        self.config.hud.fullscreen_overlay = new_val
        if sender and hasattr(sender, "state"):
            sender.state = 1 if new_val else 0
        hud.set_fullscreen_overlay(new_val)
        save_config(self.config)
        self._build_hud_submenu()

    def toggle_auto_send(self, sender=None):
        new_val = not getattr(getattr(self.config, "hud", None), "auto_send", True)
        if not hasattr(self.config, "hud") or self.config.hud is None:
            from voicefi.config import HUDConfig
            self.config.hud = HUDConfig()
        self.config.hud.auto_send = new_val
        self.config.antigravity.auto_send = new_val
        if sender and hasattr(sender, "state"):
            sender.state = 1 if new_val else 0
        hud = UnifiedDynamicIslandHUD.get_instance()
        hud.set_auto_send(new_val)
        save_config(self.config)
        self._build_hud_submenu()

    def toggle_live_transcript(self, sender=None):
        if not hasattr(self.config, "hud") or self.config.hud is None:
            from voicefi.config import HUDConfig
            self.config.hud = HUDConfig()
        new_val = not getattr(self.config.hud, "show_live_transcript", True)
        self.config.hud.show_live_transcript = new_val
        if sender and hasattr(sender, "state"):
            sender.state = 1 if new_val else 0
        save_config(self.config)
        self._build_hud_submenu()

    def reset_hud_position(self, sender=None):
        """Reset HUD position back to default anchor below Chrome top bar."""
        hud = UnifiedDynamicIslandHUD.get_instance()
        hud.reset_position()
        self._build_hud_submenu()
        try:
            rumps.notification("VoiceFi HUD", "Position Reset", "Restored default top-right anchor.")
        except Exception:
            pass

    def preview_hud_state(self, state_name: str):
        """Preview any of the 6 dynamic HUD states directly on the macOS screen."""
        hud = UnifiedDynamicIslandHUD.get_instance()
        _, resolved_voice, _ = self.config.resolve_voice("antigravity")
        from voicefi.tts import find_persona
        persona = find_persona(resolved_voice)
        pname = persona.name if persona else resolved_voice

        if state_name == "idle":
            hud.set_idle()
        elif state_name == "thinking":
            hud.set_thinking(agent_name="Antigravity", detail="Reasoning over code architecture & test suite...")
        elif state_name == "working":
            hud.set_working(agent_name="Antigravity", tool_action="Running pytest tests/ -v (All 12 passing)")
        elif state_name == "speaking":
            hud.set_speaking(
                text="Dynamic Island HUD is operational with real-time audio waveforms.",
                agent_name="Antigravity",
                persona_name=pname,
            )
        elif state_name == "listening":
            hud.set_listening(
                prompt_preview="Ship the refactored VoiceFi build to production",
                user_name=getattr(self.config, "user_name", "Jake"),
                live_stream=True,
            )
        elif state_name == "editing":
            hud.set_editing(
                initial_text="Ship the refactored VoiceFi build to production",
                on_submit=lambda txt: None,
                on_cancel=lambda: None,
                target_name="Antigravity",
            )

        if state_name != "idle":
            def _return_to_idle():
                time.sleep(3.5)
                hud_cfg = getattr(self.config, "hud", None)
                if getattr(hud_cfg, "persistent", True) and getattr(hud_cfg, "enabled", True):
                    hud.set_idle()
                else:
                    hud.finish_speech(linger_seconds=1.0)
            threading.Thread(target=_return_to_idle, daemon=True).start()

    def launch_hud_debug_studio(self, _=None):
        """Launch interactive Terminal HUD Debug Studio with real-time keystroke triggers."""
        import sys
        vg_bin = Path(sys.executable).parent / "voicefi"
        vg_cmd = f"'{vg_bin}' hud debug" if vg_bin.is_file() else "vg hud debug"
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

    def toggle_auto_listen(self, sender):
        new_val = not self.config.proactive.feedback_loop.enabled
        self.config.proactive.feedback_loop.enabled = new_val
        self.config.antigravity.auto_listen = new_val
        self.config.claude.auto_listen = new_val
        sender.state = 1 if new_val else 0
        save_config(self.config)

    def toggle_meeting_assistant(self, sender):
        from voicefi.ui.notifications import show_notification
        new_val = not self.config.proactive.meeting_assistant.enabled
        self.config.proactive.meeting_assistant.enabled = new_val
        self.config.ambient.enabled = new_val
        sender.state = 1 if new_val else 0
        save_config(self.config)
        if new_val:
            show_notification("ProActive Meeting Assistant", "Session Started", "Ambient listener active in background.")
        else:
            show_notification("ProActive Meeting Assistant", "Session Stopped", "Meeting notes and ambient listener stopped.")

    def toggle_read_summary(self, sender):
        self.config.antigravity.read_summary_aloud = not self.config.antigravity.read_summary_aloud
        sender.state = 1 if self.config.antigravity.read_summary_aloud else 0
        save_config(self.config)

    def toggle_speech_popup(self, sender=None):
        self.config.antigravity.show_speech_popup = not self.config.antigravity.show_speech_popup
        if sender and hasattr(sender, "state"):
            sender.state = 1 if self.config.antigravity.show_speech_popup else 0
        save_config(self.config)
        self._build_hud_submenu()

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
        self._update_barge_in_menu_item()

    def open_config_file(self, _):
        path = get_default_config_path()
        if not path.is_file():
            save_config(self.config)
        subprocess.run(["open", str(path)])

    def open_pricing_page(self, _=None):
        import webbrowser
        webbrowser.open("https://voicefi.org#pricing")

    def trigger_manual_listen(self, ptt_mode: bool = False):
        with self._listen_lock:
            if self._current_status in ("listening", "hearing", "ptt_listening"):
                self.finish_active_recording()
                return
            if self._current_status in ("transcribing", "paused_agent_speaking"):
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

                def _on_speech_start():
                    self._current_status = "hearing"
                    hud.set_hearing(user_name=getattr(self.config, "user_name", "Jake"))

                def _on_live(txt: str):
                    hud.update_live_transcription(txt, user_name=getattr(self.config, "user_name", "Jake"))

                def _on_tick(energy: float, conf: float = 0.0, is_spk: bool = False):
                    hud.update_audio_level(energy, conf, is_spk)

                if ptt_mode:
                    audio_data, temp_wav = recorder.record_push_to_talk(
                        stop_event=self._ptt_stop_event,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        on_listening_tick=_on_tick,
                        ptt_release_delay_ms=self.config.vad.ptt_release_delay_ms,
                    )
                else:
                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=_on_speech_start,
                        on_pause_change=_on_pause,
                        on_live_transcript=_on_live,
                        on_listening_tick=_on_tick,
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


def run_tray(force: bool = False):
    """Launch the macOS Tray application (ensuring a single instance with PID-aware recovery)."""
    global _lock_file
    import fcntl
    import sys
    import json
    import atexit
    import signal

    lock_file_path = Path("/tmp/voicefi_tray.lock")
    pid_file_path = Path("/tmp/voicefi_tray.pid")

    # Helper to check if PID is alive
    def _is_alive(p: int) -> bool:
        if p <= 0:
            return False
        try:
            os.kill(p, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    # Read existing PID if present
    existing_pid = None
    if pid_file_path.is_file():
        try:
            data = json.loads(pid_file_path.read_text(encoding="utf-8"))
            existing_pid = data.get("pid")
        except Exception:
            try:
                existing_pid = int(pid_file_path.read_text().strip())
            except Exception:
                existing_pid = None

    if force and existing_pid and existing_pid != os.getpid() and _is_alive(existing_pid):
        print(f"🔄 Terminating existing VoiceFi process (PID {existing_pid}) for clean takeover...")
        try:
            os.kill(existing_pid, signal.SIGTERM)
            time.sleep(0.5)
            if _is_alive(existing_pid):
                os.kill(existing_pid, signal.SIGKILL)
        except Exception:
            pass

    # If previous process is dead, clean stale lock
    if existing_pid and not _is_alive(existing_pid):
        lock_file_path.unlink(missing_ok=True)
        pid_file_path.unlink(missing_ok=True)

    try:
        _lock_file = open(str(lock_file_path), "w")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write PID metadata
        pid_file_path.write_text(
            json.dumps({
                "pid": os.getpid(),
                "binary": sys.executable,
                "started_at": time.time(),
            }, indent=2),
            encoding="utf-8",
        )
    except (IOError, BlockingIOError):
        # Inspect existing PID again
        if existing_pid and _is_alive(existing_pid):
            print(f"⚠️ VoiceFi tray companion is already running (PID {existing_pid}).")
            print("💡 Use 'vifi dev' for foreground dev mode, 'vifi daemon stop' to kill background daemons, or 'vifi clean' to reset.")
        else:
            # Stale lock: remove and retry once
            lock_file_path.unlink(missing_ok=True)
            pid_file_path.unlink(missing_ok=True)
            try:
                _lock_file = open(str(lock_file_path), "w")
                fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                pid_file_path.write_text(
                    json.dumps({
                        "pid": os.getpid(),
                        "binary": sys.executable,
                        "started_at": time.time(),
                    }, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                print("⚠️ VoiceFi tray companion is already running.")
                sys.exit(0)

    # Register exit cleanup
    def _cleanup():
        global _lock_file
        try:
            if _lock_file:
                fcntl.flock(_lock_file, fcntl.LOCK_UN)
                _lock_file.close()
                _lock_file = None
        except Exception:
            pass
        lock_file_path.unlink(missing_ok=True)
        pid_file_path.unlink(missing_ok=True)

    atexit.register(_cleanup)

    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception:
        pass

    try:
        app = VoiceFiTrayApp()
        app.run()
    finally:
        _cleanup()

