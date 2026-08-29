"""
Native macOS HUD Quick Controls Popover / Flyout.
Provides an Apple-style frosted glass panel anchored directly below the VoiceFi HUD
with instant segmented pill controls and toggles for:
- ⚡ ProActive Listening [ ON | OFF ]
- ✋ Active Barge-In [ AUTO | ON | OFF ]
- ⏱️ Pause Delay (Fibonacci: 1s, 2s, 3s, 5s, 8s, 11s)
- 🚀 Auto-Send Mode [ Auto | Review ✏️ ]
- 🔊 Spoken Summaries [ ON | MUTE 🔇 ]
- 🎭 Voice Persona (Dropdown)
- 🎚️ Mic & VAD Sensitivity + 1-Click Calibration
- 📌 HUD Preferences (Persistent, Fullscreen Overlay, Reset Position, Web Panel)
"""

import os
import subprocess
import threading
import time
from typing import Optional, Any, List

from voicefi.config import load_config, save_config, FIBONACCI_PAUSE_DELAYS

try:
    from AppKit import (
        NSApplication,
        NSPanel,
        NSWindowStyleMaskBorderless,
        NSWindowStyleMaskNonactivatingPanel,
        NSBackingStoreBuffered,
        NSRect,
        NSPoint,
        NSSize,
        NSTextField,
        NSTextAlignmentCenter,
        NSTextAlignmentLeft,
        NSTextAlignmentRight,
        NSButton,
        NSBezelStyleRounded,
        NSColor,
        NSFloatingWindowLevel,
        NSFont,
        NSScreen,
        NSView,
        NSVisualEffectView,
        NSVisualEffectMaterialHUDWindow,
        NSVisualEffectBlendingModeBehindWindow,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSSegmentedControl,
        NSSegmentStyleTexturedRounded,
        NSPopUpButton,
        NSBezierPath,
        NSWorkspace,
    )
    from Foundation import NSURL
    import objc
    from PyObjCTools import AppHelper
    HAS_APPKIT = True
except Exception:
    HAS_APPKIT = False
    objc = None


def is_headless() -> bool:
    """Return True if running in headless / testing mode where screen popups must be suppressed."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("VOICEFI_TESTING") == "1"
    )


if HAS_APPKIT:
    try:
        QuickControlsActionTarget = objc.lookUpClass("QuickControlsActionTarget")
    except objc.nosuchclass_error:
        class QuickControlsActionTarget(objc.lookUpClass("NSObject")):
            def initWithCallback_(self, callback):
                self = objc.super(QuickControlsActionTarget, self).init()
                if self is not None:
                    self.callback = callback
                return self

            def actionHandler_(self, sender):
                if self.callback:
                    self.callback(sender)


class HUDQuickControlsPanel:
    """
    Singleton Native Apple-Style Floating Quick Controls Panel.
    Appears directly beneath the Unified Dynamic Island HUD capsule.
    """

    _instance: Optional["HUDQuickControlsPanel"] = None
    _lock = threading.Lock()

    PANEL_WIDTH: float = 480.0
    PANEL_HEIGHT: float = 460.0

    @classmethod
    def get_instance(cls) -> "HUDQuickControlsPanel":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.config = load_config()
        self._panel: Optional[Any] = None
        self._targets: List[Any] = []
        self._is_visible: bool = False

        # UI References
        self.seg_proactive = None
        self.seg_barge_in = None
        self.seg_pause_delay = None
        self.seg_auto_send = None
        self.seg_spoken_summaries = None
        self.popup_persona = None
        self.lbl_mic_level = None
        self.btn_persistent = None
        self.btn_fullscreen = None

        if HAS_APPKIT and not is_headless():
            self._build_panel()

    def _build_panel(self):
        if not HAS_APPKIT:
            return

        w, h = self.PANEL_WIDTH, self.PANEL_HEIGHT
        rect = NSRect(NSPoint(1200, 500), NSSize(w, h))
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel

        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setLevel_(NSFloatingWindowLevel + 2)
        self._panel.setFloatingPanel_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCanHide_(False)
        self._panel.setWorksWhenModal_(True)
        self._panel.setBecomesKeyOnlyIfNeeded_(True)
        self._panel.setReleasedWhenClosed_(False)
        self._panel.setMovableByWindowBackground_(True)
        self._panel.setMovable_(True)
        self._panel.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces)

        # Root Visual Effect Frosted Glass Container
        root_view = NSVisualEffectView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(w, h)))
        root_view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        root_view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        root_view.setState_(1)
        root_view.setWantsLayer_(True)
        root_view.layer().setCornerRadius_(18.0)
        root_view.layer().setMasksToBounds_(True)
        root_view.layer().setBorderWidth_(1.2)
        root_view.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.22).CGColor()
        )

        def _make_lbl(text, x, y, width, height, font_size=11.5, bold=False, alpha=0.95, color=None):
            lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(x, y), NSSize(width, height)))
            lbl.setStringValue_(text)
            if bold:
                lbl.setFont_(NSFont.boldSystemFontOfSize_(font_size))
            else:
                lbl.setFont_(NSFont.systemFontOfSize_(font_size))
            if color:
                lbl.setTextColor_(color)
            else:
                lbl.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, alpha))
            lbl.setBezeled_(False)
            lbl.setDrawsBackground_(False)
            lbl.setEditable_(False)
            lbl.setSelectable_(False)
            root_view.addSubview_(lbl)
            return lbl

        # ---------------------------------------------------------------------
        # 1. Header Bar
        # ---------------------------------------------------------------------
        _make_lbl("🎙️ VoiceFi • Quick Controls", 18, h - 30, 300, 20, font_size=12.5, bold=True)

        close_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(w - 34, h - 30), NSSize(20, 20)))
        close_btn.setBordered_(False)
        close_btn.setTitle_("✕")
        close_btn.setFont_(NSFont.boldSystemFontOfSize_(11))
        target_close = QuickControlsActionTarget.alloc().initWithCallback_(lambda _: self.hide())
        self._targets.append(target_close)
        close_btn.setTarget_(target_close)
        close_btn.setAction_("actionHandler:")
        root_view.addSubview_(close_btn)

        cur_y = h - 68

        # ---------------------------------------------------------------------
        # 2. ⚡ ProActive Listening
        # ---------------------------------------------------------------------
        _make_lbl("⚡ ProActive Listening", 18, cur_y + 12, 230, 18, font_size=11.5, bold=True)
        _make_lbl("↳ Hands-free turn handoff when agent finishes speaking", 18, cur_y - 6, 290, 16, font_size=9.5, alpha=0.65)

        self.seg_proactive = NSSegmentedControl.alloc().initWithFrame_(
            NSRect(NSPoint(310, cur_y), NSSize(152, 24))
        )
        self.seg_proactive.setSegmentCount_(2)
        self.seg_proactive.setLabel_forSegment_("ON", 0)
        self.seg_proactive.setLabel_forSegment_("OFF", 1)
        self.seg_proactive.setSegmentStyle_(NSSegmentStyleTexturedRounded)
        is_proactive = getattr(getattr(self.config, "proactive", None), "feedback_loop", None)
        is_on = getattr(is_proactive, "enabled", True) if is_proactive else True
        self.seg_proactive.setSelectedSegment_(0 if is_on else 1)

        t_proactive = QuickControlsActionTarget.alloc().initWithCallback_(self._on_proactive_toggle)
        self._targets.append(t_proactive)
        self.seg_proactive.setTarget_(t_proactive)
        self.seg_proactive.setAction_("actionHandler:")
        root_view.addSubview_(self.seg_proactive)

        cur_y -= 50

        # ---------------------------------------------------------------------
        # 3. ✋ Active Barge-In
        # ---------------------------------------------------------------------
        _make_lbl("✋ Active Barge-In", 18, cur_y + 12, 230, 18, font_size=11.5, bold=True)
        _make_lbl("↳ Speak over the agent to interrupt immediately", 18, cur_y - 6, 290, 16, font_size=9.5, alpha=0.65)

        self.seg_barge_in = NSSegmentedControl.alloc().initWithFrame_(
            NSRect(NSPoint(290, cur_y), NSSize(172, 24))
        )
        self.seg_barge_in.setSegmentCount_(3)
        self.seg_barge_in.setLabel_forSegment_("AUTO", 0)
        self.seg_barge_in.setLabel_forSegment_("ON", 1)
        self.seg_barge_in.setLabel_forSegment_("OFF", 2)
        self.seg_barge_in.setSegmentStyle_(NSSegmentStyleTexturedRounded)

        cur_barge = getattr(self.config.vad, "barge_in", "auto")
        barge_idx = 0 if cur_barge == "auto" else 1 if cur_barge is True else 2
        self.seg_barge_in.setSelectedSegment_(barge_idx)

        t_barge = QuickControlsActionTarget.alloc().initWithCallback_(self._on_barge_in_toggle)
        self._targets.append(t_barge)
        self.seg_barge_in.setTarget_(t_barge)
        self.seg_barge_in.setAction_("actionHandler:")
        root_view.addSubview_(self.seg_barge_in)

        cur_y -= 50

        # ---------------------------------------------------------------------
        # 4. ⏱️ Pause Delay (Fibonacci Scale: 1s, 2s, 3s, 5s, 8s, 11s)
        # ---------------------------------------------------------------------
        _make_lbl("⏱️ Pause Delay", 18, cur_y + 12, 200, 18, font_size=11.5, bold=True)
        _make_lbl("↳ Silence duration before finalizing prompt", 18, cur_y - 6, 240, 16, font_size=9.5, alpha=0.65)

        self.seg_pause_delay = NSSegmentedControl.alloc().initWithFrame_(
            NSRect(NSPoint(220, cur_y), NSSize(242, 24))
        )
        self.seg_pause_delay.setSegmentCount_(len(FIBONACCI_PAUSE_DELAYS))
        for idx, val in enumerate(FIBONACCI_PAUSE_DELAYS):
            self.seg_pause_delay.setLabel_forSegment_(f"{int(val)}s", idx)
        self.seg_pause_delay.setSegmentStyle_(NSSegmentStyleTexturedRounded)

        cur_silence = float(getattr(self.config.vad, "silence_duration", 1.4))
        # Find closest fibonacci segment
        closest_idx = min(
            range(len(FIBONACCI_PAUSE_DELAYS)),
            key=lambda i: abs(FIBONACCI_PAUSE_DELAYS[i] - cur_silence),
        )
        self.seg_pause_delay.setSelectedSegment_(closest_idx)

        t_pause = QuickControlsActionTarget.alloc().initWithCallback_(self._on_pause_delay_toggle)
        self._targets.append(t_pause)
        self.seg_pause_delay.setTarget_(t_pause)
        self.seg_pause_delay.setAction_("actionHandler:")
        root_view.addSubview_(self.seg_pause_delay)

        cur_y -= 50

        # ---------------------------------------------------------------------
        # 5. 🚀 Auto-Send Mode
        # ---------------------------------------------------------------------
        _make_lbl("🚀 Auto-Send Mode", 18, cur_y + 12, 220, 18, font_size=11.5, bold=True)
        _make_lbl("↳ Instant dispatch vs. review & edit capsule before sending", 18, cur_y - 6, 290, 16, font_size=9.5, alpha=0.65)

        self.seg_auto_send = NSSegmentedControl.alloc().initWithFrame_(
            NSRect(NSPoint(290, cur_y), NSSize(172, 24))
        )
        self.seg_auto_send.setSegmentCount_(2)
        self.seg_auto_send.setLabel_forSegment_("Auto", 0)
        self.seg_auto_send.setLabel_forSegment_("Review ✏️", 1)
        self.seg_auto_send.setSegmentStyle_(NSSegmentStyleTexturedRounded)

        cur_auto_send = getattr(getattr(self.config, "hud", None), "auto_send", True)
        self.seg_auto_send.setSelectedSegment_(0 if cur_auto_send else 1)

        t_autosend = QuickControlsActionTarget.alloc().initWithCallback_(self._on_auto_send_toggle)
        self._targets.append(t_autosend)
        self.seg_auto_send.setTarget_(t_autosend)
        self.seg_auto_send.setAction_("actionHandler:")
        root_view.addSubview_(self.seg_auto_send)

        cur_y -= 50

        # ---------------------------------------------------------------------
        # 6. 🔊 Spoken Summaries
        # ---------------------------------------------------------------------
        _make_lbl("🔊 Spoken Summaries", 18, cur_y + 12, 230, 18, font_size=11.5, bold=True)
        _make_lbl("↳ Agent speaks audible soundbites (Mute keeps visual HUD)", 18, cur_y - 6, 290, 16, font_size=9.5, alpha=0.65)

        self.seg_spoken_summaries = NSSegmentedControl.alloc().initWithFrame_(
            NSRect(NSPoint(310, cur_y), NSSize(152, 24))
        )
        self.seg_spoken_summaries.setSegmentCount_(2)
        self.seg_spoken_summaries.setLabel_forSegment_("ON", 0)
        self.seg_spoken_summaries.setLabel_forSegment_("MUTE 🔇", 1)
        self.seg_spoken_summaries.setSegmentStyle_(NSSegmentStyleTexturedRounded)

        cur_spoken = getattr(getattr(self.config, "antigravity", None), "read_summary_aloud", True)
        self.seg_spoken_summaries.setSelectedSegment_(0 if cur_spoken else 1)

        t_spoken = QuickControlsActionTarget.alloc().initWithCallback_(self._on_spoken_summaries_toggle)
        self._targets.append(t_spoken)
        self.seg_spoken_summaries.setTarget_(t_spoken)
        self.seg_spoken_summaries.setAction_("actionHandler:")
        root_view.addSubview_(self.seg_spoken_summaries)

        cur_y -= 50

        # ---------------------------------------------------------------------
        # 7. 🎭 Voice Persona Dropdown
        # ---------------------------------------------------------------------
        _make_lbl("🎭 Voice Persona", 18, cur_y + 12, 230, 18, font_size=11.5, bold=True)
        _make_lbl("↳ Agent acoustic persona / local offline vs. cloud voices", 18, cur_y - 6, 260, 16, font_size=9.5, alpha=0.65)

        self.popup_persona = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSRect(NSPoint(260, cur_y), NSSize(202, 24)), False
        )
        personas = [
            ("Ava (0ms Offline)", "en-US-AvaNeural"),
            ("Steffan (Claude)", "en-US-SteffanNeural"),
            ("Samantha (Apple)", "Samantha"),
            ("Jenny (Cursor)", "en-US-JennyNeural"),
            ("Guy (Edge)", "en-US-GuyNeural"),
            ("Aoede (Gemini)", "Aoede"),
            ("Christopher (Deep)", "en-US-ChristopherNeural"),
        ]
        for label, _ in personas:
            self.popup_persona.addItemWithTitle_(label)

        t_persona = QuickControlsActionTarget.alloc().initWithCallback_(self._on_persona_change)
        self._targets.append(t_persona)
        self.popup_persona.setTarget_(t_persona)
        self.popup_persona.setAction_("actionHandler:")
        root_view.addSubview_(self.popup_persona)

        cur_y -= 50

        # ---------------------------------------------------------------------
        # 8. 🎚️ Mic & VAD Sensitivity + Calibrate
        # ---------------------------------------------------------------------
        _make_lbl("🎚️ Mic & VAD Sensitivity", 18, cur_y + 12, 230, 18, font_size=11.5, bold=True)
        _make_lbl("↳ 1-click ambient noise sample for room adaptation", 18, cur_y - 6, 260, 16, font_size=9.5, alpha=0.65)

        btn_cal = NSButton.alloc().initWithFrame_(NSRect(NSPoint(280, cur_y), NSSize(110, 24)))
        btn_cal.setTitle_("Calibrate 🎯")
        btn_cal.setBezelStyle_(NSBezelStyleRounded)
        t_cal = QuickControlsActionTarget.alloc().initWithCallback_(self._on_calibrate)
        self._targets.append(t_cal)
        btn_cal.setTarget_(t_cal)
        btn_cal.setAction_("actionHandler:")
        root_view.addSubview_(btn_cal)

        self.lbl_mic_level = _make_lbl(
            "||||| 58%", 396, cur_y + 2, 70, 20, font_size=11, bold=True,
            color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.9, 0.7, 0.95)
        )

        cur_y -= 45

        # ---------------------------------------------------------------------
        # 9. Footer Action Bar (Persistent, Fullscreen, Reset Pos, Web Panel)
        # ---------------------------------------------------------------------
        # Separator line
        sep = NSView.alloc().initWithFrame_(NSRect(NSPoint(14, cur_y + 35), NSSize(w - 28, 1)))
        sep.setWantsLayer_(True)
        sep.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.15).CGColor()
        )
        root_view.addSubview_(sep)

        # Persistent HUD Button
        self.btn_persistent = NSButton.alloc().initWithFrame_(NSRect(NSPoint(14, cur_y + 4), NSSize(100, 24)))
        is_pers = getattr(getattr(self.config, "hud", None), "persistent", True)
        self.btn_persistent.setTitle_(f"📌 HUD: {'ON' if is_pers else 'OFF'}")
        self.btn_persistent.setBezelStyle_(NSBezelStyleRounded)
        t_pers = QuickControlsActionTarget.alloc().initWithCallback_(self._on_persistent_toggle)
        self._targets.append(t_pers)
        self.btn_persistent.setTarget_(t_pers)
        self.btn_persistent.setAction_("actionHandler:")
        root_view.addSubview_(self.btn_persistent)

        # Fullscreen Overlay Button
        self.btn_fullscreen = NSButton.alloc().initWithFrame_(NSRect(NSPoint(118, cur_y + 4), NSSize(110, 24)))
        is_fs = getattr(getattr(self.config, "hud", None), "fullscreen_overlay", True)
        self.btn_fullscreen.setTitle_(f"🎮 Overlay: {'ON' if is_fs else 'OFF'}")
        self.btn_fullscreen.setBezelStyle_(NSBezelStyleRounded)
        t_fs = QuickControlsActionTarget.alloc().initWithCallback_(self._on_fullscreen_toggle)
        self._targets.append(t_fs)
        self.btn_fullscreen.setTarget_(t_fs)
        self.btn_fullscreen.setAction_("actionHandler:")
        root_view.addSubview_(self.btn_fullscreen)

        # Reset Pos Button
        btn_reset = NSButton.alloc().initWithFrame_(NSRect(NSPoint(232, cur_y + 4), NSSize(90, 24)))
        btn_reset.setTitle_("🎯 Reset Pos")
        btn_reset.setBezelStyle_(NSBezelStyleRounded)
        t_reset = QuickControlsActionTarget.alloc().initWithCallback_(self._on_reset_position)
        self._targets.append(t_reset)
        btn_reset.setTarget_(t_reset)
        btn_reset.setAction_("actionHandler:")
        root_view.addSubview_(btn_reset)

        # Web Panel Button
        btn_panel = NSButton.alloc().initWithFrame_(NSRect(NSPoint(326, cur_y + 4), NSSize(140, 24)))
        btn_panel.setTitle_("🎛️ Control Panel...")
        btn_panel.setBezelStyle_(NSBezelStyleRounded)
        t_panel = QuickControlsActionTarget.alloc().initWithCallback_(self._on_open_control_panel)
        self._targets.append(t_panel)
        btn_panel.setTarget_(t_panel)
        btn_panel.setAction_("actionHandler:")
        root_view.addSubview_(btn_panel)

        self._panel.setContentView_(root_view)

    # -------------------------------------------------------------------------
    # Control Actions & Config Sync
    # -------------------------------------------------------------------------

    def _on_proactive_toggle(self, sender):
        idx = sender.selectedSegment()
        enabled = (idx == 0)
        self.config = load_config()
        if not hasattr(self.config, "proactive") or self.config.proactive is None:
            from voicefi.config import ProActiveConfig
            self.config.proactive = ProActiveConfig()
        self.config.proactive.feedback_loop.enabled = enabled
        if hasattr(self.config, "antigravity"):
            self.config.antigravity.auto_listen = enabled
        if hasattr(self.config, "claude"):
            self.config.claude.auto_listen = enabled
        save_config(self.config)
        print(f"[QuickControls] ⚡ ProActive Listening: {'ON' if enabled else 'OFF'}")

    def _on_barge_in_toggle(self, sender):
        idx = sender.selectedSegment()
        val = "auto" if idx == 0 else True if idx == 1 else False
        self.config = load_config()
        self.config.vad.barge_in = val
        save_config(self.config)
        print(f"[QuickControls] ✋ Active Barge-In: {val}")

    def _on_pause_delay_toggle(self, sender):
        idx = sender.selectedSegment()
        if 0 <= idx < len(FIBONACCI_PAUSE_DELAYS):
            duration = FIBONACCI_PAUSE_DELAYS[idx]
            self.config = load_config()
            self.config.vad.silence_duration = float(duration)
            save_config(self.config)
            print(f"[QuickControls] ⏱️ Pause Delay set to Fibonacci {duration:.1f}s")

    def _on_auto_send_toggle(self, sender):
        idx = sender.selectedSegment()
        auto_send = (idx == 0)
        self.config = load_config()
        if hasattr(self.config, "hud") and self.config.hud:
            self.config.hud.auto_send = auto_send
        if hasattr(self.config, "antigravity"):
            self.config.antigravity.auto_send = auto_send
        save_config(self.config)
        try:
            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
            UnifiedDynamicIslandHUD.get_instance().set_auto_send(auto_send)
        except Exception:
            pass
        print(f"[QuickControls] 🚀 Auto-Send Mode: {'Instant' if auto_send else 'Review & Edit'}")

    def _on_spoken_summaries_toggle(self, sender):
        idx = sender.selectedSegment()
        spoken = (idx == 0)
        self.config = load_config()
        if hasattr(self.config, "antigravity"):
            self.config.antigravity.read_summary_aloud = spoken
        if hasattr(self.config, "claude"):
            self.config.claude.read_summary_aloud = spoken
        save_config(self.config)
        print(f"[QuickControls] 🔊 Spoken Summaries: {'ON' if spoken else 'MUTED'}")

    def _on_persona_change(self, sender):
        title = sender.titleOfSelectedItem()
        self.config = load_config()
        if "Ava" in title:
            self.config.tts.voice = "en-US-AvaNeural"
        elif "Steffan" in title:
            self.config.tts.voice = "en-US-SteffanNeural"
        elif "Samantha" in title:
            self.config.tts.voice = "Samantha"
            self.config.tts.provider = "mac_say"
        elif "Jenny" in title:
            self.config.tts.voice = "en-US-JennyNeural"
        elif "Guy" in title:
            self.config.tts.voice = "en-US-GuyNeural"
        elif "Aoede" in title:
            self.config.tts.voice = "Aoede"
            self.config.tts.provider = "gemini"
        elif "Christopher" in title:
            self.config.tts.voice = "en-US-ChristopherNeural"
        save_config(self.config)
        print(f"[QuickControls] 🎭 Voice Persona updated: {title}")

    def _on_calibrate(self, sender):
        if self.lbl_mic_level:
            self.lbl_mic_level.setStringValue_("Sampling...")
        try:
            from voicefi.troubleshoot import AudioTroubleshooter
            t = AudioTroubleshooter(self.config)
            def _cal():
                res = t.test_microphone_loopback(duration_seconds=1.5, play_back=False)
                if res.success:
                    suggested = max(min(res.rms_energy * 1.5, 0.02), 0.002)
                    def _update_ui():
                        self.config.vad.energy_threshold = round(suggested, 4)
                        save_config(self.config)
                        if self.lbl_mic_level:
                            self.lbl_mic_level.setStringValue_(f"RMS: {suggested:.4f}")
                    AppHelper.callAfter(_update_ui)
            threading.Thread(target=_cal, daemon=True).start()
        except Exception:
            pass

    def _on_persistent_toggle(self, sender):
        self.config = load_config()
        cur = getattr(getattr(self.config, "hud", None), "persistent", True)
        new_val = not cur
        if hasattr(self.config, "hud") and self.config.hud:
            self.config.hud.persistent = new_val
        save_config(self.config)
        if self.btn_persistent:
            self.btn_persistent.setTitle_(f"📌 HUD: {'ON' if new_val else 'OFF'}")
        try:
            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
            UnifiedDynamicIslandHUD.get_instance().set_persistent(new_val)
        except Exception:
            pass

    def _on_fullscreen_toggle(self, sender):
        self.config = load_config()
        cur = getattr(getattr(self.config, "hud", None), "fullscreen_overlay", True)
        new_val = not cur
        if hasattr(self.config, "hud") and self.config.hud:
            self.config.hud.fullscreen_overlay = new_val
        save_config(self.config)
        if self.btn_fullscreen:
            self.btn_fullscreen.setTitle_(f"🎮 Overlay: {'ON' if new_val else 'OFF'}")
        try:
            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
            UnifiedDynamicIslandHUD.get_instance().set_fullscreen_overlay(new_val)
        except Exception:
            pass

    def _on_reset_position(self, sender):
        try:
            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
            hud = UnifiedDynamicIslandHUD.get_instance()
            hud.reset_position()
            if self._panel and hud._panel:
                hud_frame = hud._panel.frame()
                x = hud_frame.origin.x + (hud_frame.size.width - self.PANEL_WIDTH) / 2.0
                y = hud_frame.origin.y - self.PANEL_HEIGHT - 10.0
                self._panel.setFrameOrigin_(NSPoint(x, y))
        except Exception as e:
            print(f"[QuickControls] Reset position error: {e}")

    def _on_open_control_panel(self, sender):
        try:
            port = getattr(getattr(self.config, "companion", None), "port", 5141)
            url = f"http://localhost:{port}"
            subprocess.Popen(["open", url])
            self.hide()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Presentation Handlers
    # -------------------------------------------------------------------------

    def show(self, relative_to_rect: Optional[Any] = None):
        if not HAS_APPKIT or is_headless() or not self._panel:
            self._is_visible = True
            return

        def _do_show():
            if relative_to_rect:
                x = relative_to_rect.origin.x + (relative_to_rect.size.width - self.PANEL_WIDTH) / 2.0
                y = relative_to_rect.origin.y - self.PANEL_HEIGHT - 10.0
                self._panel.setFrameOrigin_(NSPoint(x, y))

            self._panel.orderFrontRegardless()
            self._is_visible = True

        if threading.current_thread() is threading.main_thread():
            _do_show()
        else:
            AppHelper.callAfter(_do_show)

    def hide(self):
        if not HAS_APPKIT or not self._panel:
            self._is_visible = False
            return

        def _do_hide():
            self._panel.orderOut_(None)
            self._is_visible = False

        if threading.current_thread() is threading.main_thread():
            _do_hide()
        else:
            AppHelper.callAfter(_do_hide)

    def toggle(self, relative_to_rect: Optional[Any] = None):
        if self._is_visible:
            self.hide()
        else:
            self.show(relative_to_rect)
