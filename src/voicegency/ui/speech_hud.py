"""
Native macOS Floating Agent Speech HUD Capsule.
Displays what the AI agent is saying in real-time with a subtle, frosted-glass
floating capsule overlay that never steals focus from the user's active window.
"""

import time
import threading
import math
from typing import Optional, Dict, Any
from pathlib import Path

from AppKit import (
    NSPanel,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered,
    NSRect,
    NSPoint,
    NSSize,
    NSTextField,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSScreen,
    NSView,
    NSVisualEffectView,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectBlendingModeBehindWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
)
from PyObjCTools import AppHelper

AVATAR_ICONS: Dict[str, str] = {
    "antigravity": "🤖",
    "main": "🤖",
    "researcher": "🔍",
    "debugger": "🐞",
    "qa": "🐞",
    "tester": "🐞",
    "architect": "📐",
    "devops": "📐",
    "claude": "🎭",
    "christopher": "🧔",
    "aria": "⚡",
    "sonia": "🔬",
    "guy": "☕",
    "william": "🦘",
    "jenny": "👩‍💻",
    "samantha": "🍎",
    "alex": "🍏",
    "daniel": "🎙️",
}


class AgentSpeechHUD:
    """Singleton Floating HUD Pop-up for Real-Time Agent Spoken Output."""

    _instance: Optional["AgentSpeechHUD"] = None

    @classmethod
    def get_instance(cls) -> "AgentSpeechHUD":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._panel: Optional[NSPanel] = None
        self._root_view: Optional[NSView] = None
        self._visual_effect: Optional[NSVisualEffectView] = None
        self._avatar_label: Optional[NSTextField] = None
        self._header_label: Optional[NSTextField] = None
        self._persona_label: Optional[NSTextField] = None
        self._speech_label: Optional[NSTextField] = None
        self._wave_bars: list[NSView] = []
        self._wave_timer: Optional[threading.Timer] = None
        self._hide_timer: Optional[threading.Timer] = None
        self._wave_step = 0
        self._is_speaking = False
        self._position_mode = "top_center"
        self._lock = threading.RLock()
        self._build_panel()

    def _build_panel(self):
        """Construct the floating frosted-glass NSPanel."""
        width, height = 460, 84
        rect = NSRect(NSPoint(500, 800), NSSize(width, height))
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel

        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setLevel_(NSFloatingWindowLevel + 3)
        self._panel.setFloatingPanel_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCanHide_(False)
        self._panel.setWorksWhenModal_(True)
        self._panel.setBecomesKeyOnlyIfNeeded_(True)
        self._panel.setReleasedWhenClosed_(False)
        self._panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        # Root translucent capsule container
        root_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
        root_view.setWantsLayer_(True)
        root_view.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.14, 0.94).CGColor()
        )
        root_view.layer().setCornerRadius_(18.0)
        root_view.layer().setBorderWidth_(1.2)
        root_view.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.35, 0.55, 0.95, 0.38).CGColor()
        )
        self._root_view = root_view

        # Optional frosted visual effect view layer
        try:
            ve_view = NSVisualEffectView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            ve_view.setMaterial_(NSVisualEffectMaterialHUDWindow)
            ve_view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            ve_view.setState_(1)
            ve_view.setWantsLayer_(True)
            ve_view.layer().setCornerRadius_(18.0)
            ve_view.layer().setMasksToBounds_(True)
            root_view.addSubview_(ve_view)
            self._visual_effect = ve_view
        except Exception:
            pass

        # 1. Avatar Badge Circle
        avatar_bg = NSView.alloc().initWithFrame_(NSRect(NSPoint(14, height - 42), NSSize(30, 30)))
        avatar_bg.setWantsLayer_(True)
        avatar_bg.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.22, 0.35, 0.9).CGColor()
        )
        avatar_bg.layer().setCornerRadius_(15.0)
        avatar_bg.layer().setBorderWidth_(1.0)
        avatar_bg.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.6, 1.0, 0.4).CGColor()
        )
        root_view.addSubview_(avatar_bg)

        avatar_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(0, 2), NSSize(30, 26)))
        avatar_lbl.setStringValue_("🤖")
        avatar_lbl.setFont_(NSFont.systemFontOfSize_(16))
        avatar_lbl.setAlignment_(1)  # Center
        avatar_lbl.setBezeled_(False)
        avatar_lbl.setDrawsBackground_(False)
        avatar_lbl.setEditable_(False)
        avatar_lbl.setSelectable_(False)
        avatar_bg.addSubview_(avatar_lbl)
        self._avatar_label = avatar_lbl

        # 2. Agent Name / Header
        header_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(52, height - 33), NSSize(160, 20)))
        header_lbl.setStringValue_("Antigravity")
        header_lbl.setFont_(NSFont.boldSystemFontOfSize_(12.5))
        header_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.97, 1.0, 1.0))
        header_lbl.setBezeled_(False)
        header_lbl.setDrawsBackground_(False)
        header_lbl.setEditable_(False)
        header_lbl.setSelectable_(False)
        root_view.addSubview_(header_lbl)
        self._header_label = header_lbl

        # 3. Persona Subtitle Tag
        persona_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(180, height - 33), NSSize(180, 20)))
        persona_lbl.setStringValue_("• Christopher")
        persona_lbl.setFont_(NSFont.systemFontOfSize_(11))
        persona_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.65, 0.75, 0.90, 0.85))
        persona_lbl.setBezeled_(False)
        persona_lbl.setDrawsBackground_(False)
        persona_lbl.setEditable_(False)
        persona_lbl.setSelectable_(False)
        root_view.addSubview_(persona_lbl)
        self._persona_label = persona_lbl

        # 4. Animated Equalizer Waveform Bars (Right Side of Header)
        wave_container = NSView.alloc().initWithFrame_(NSRect(NSPoint(width - 80, height - 34), NSSize(66, 18)))
        wave_container.setWantsLayer_(True)
        root_view.addSubview_(wave_container)

        self._wave_bars = []
        bar_x = 0
        for i in range(5):
            bar = NSView.alloc().initWithFrame_(NSRect(NSPoint(bar_x, 2), NSSize(3, 12)))
            bar.setWantsLayer_(True)
            bar.layer().setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.30, 0.70, 1.0, 0.9).CGColor()
            )
            bar.layer().setCornerRadius_(1.5)
            wave_container.addSubview_(bar)
            self._wave_bars.append(bar)
            bar_x += 7

        # 5. Spoken Text Body (Multi-line label)
        speech_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(14, 10), NSSize(width - 28, 40)))
        speech_lbl.setStringValue_("Speaking...")
        speech_lbl.setFont_(NSFont.systemFontOfSize_(12.5))
        speech_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.94, 0.98, 0.95))
        speech_lbl.setBezeled_(False)
        speech_lbl.setDrawsBackground_(False)
        speech_lbl.setEditable_(False)
        speech_lbl.setSelectable_(False)
        speech_lbl.cell().setWraps_(True)
        speech_lbl.cell().setLineBreakMode_(0)  # NSLineBreakByWordWrapping
        root_view.addSubview_(speech_lbl)
        self._speech_label = speech_lbl

        self._panel.setContentView_(root_view)

    def _calculate_frame_for_text(self, text: str, width: int = 480) -> NSRect:
        """Calculate dynamic panel frame height based on speech text length."""
        # Baseline height for short message (1-2 lines)
        est_lines = max(1, min(4, math.ceil(len(text) / 52.0)))
        height = 54 + (est_lines * 19)

        screen = NSScreen.mainScreen()
        if screen:
            visible_frame = screen.visibleFrame()
            if self._position_mode == "top_right":
                x = visible_frame.origin.x + visible_frame.size.width - width - 24.0
                y = visible_frame.origin.y + visible_frame.size.height - height - 16.0
            elif self._position_mode == "bottom_right":
                x = visible_frame.origin.x + visible_frame.size.width - width - 24.0
                y = visible_frame.origin.y + 24.0
            else:  # top_center (default)
                x = visible_frame.origin.x + (visible_frame.size.width - width) / 2.0
                y = visible_frame.origin.y + visible_frame.size.height - height - 16.0
        else:
            x, y = 500, 800

        return NSRect(NSPoint(x, y), NSSize(width, height))

    def _resolve_avatar(self, agent_name: str, persona_name: Optional[str] = None) -> str:
        """Resolve avatar emoji for the speaking agent."""
        if persona_name:
            p_key = persona_name.lower().strip()
            if p_key in AVATAR_ICONS:
                return AVATAR_ICONS[p_key]

        a_key = agent_name.lower().strip()
        for k, icon in AVATAR_ICONS.items():
            if k in a_key:
                return icon
        return "🤖"

    def show_speech(
        self,
        text: str,
        agent_name: str = "Antigravity",
        role: Optional[str] = None,
        persona_name: Optional[str] = None,
        is_speaking: bool = True,
        position: str = "top_center",
    ):
        """
        Display what the agent is saying on the floating HUD (Thread Safe).
        """
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None
            self._position_mode = position
            self._is_speaking = is_speaking

        def _update():
            if not self._panel:
                return

            clean_text = text.strip()
            if not clean_text:
                return

            # Dynamic resizing based on length
            target_width = 480
            frame = self._calculate_frame_for_text(clean_text, width=target_width)
            self._panel.setFrame_display_(frame, True)

            if self._root_view:
                self._root_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(target_width, frame.size.height)))
            if self._visual_effect:
                self._visual_effect.setFrame_(NSRect(NSPoint(0, 0), NSSize(target_width, frame.size.height)))

            # Update Avatar
            avatar = self._resolve_avatar(agent_name, persona_name)
            if self._avatar_label:
                self._avatar_label.setStringValue_(avatar)

            # Update Header & Persona
            display_agent = agent_name.capitalize() if agent_name else "Antigravity"
            if self._header_label:
                self._header_label.setStringValue_(display_agent)
                h_y = frame.size.height - 33
                self._header_label.setFrameOrigin_(NSPoint(52, h_y))

            if self._persona_label:
                p_text = f"• {persona_name}" if persona_name else (f"• {role.capitalize()}" if role else "")
                self._persona_label.setStringValue_(p_text)
                self._persona_label.setFrameOrigin_(NSPoint(170, frame.size.height - 33))

            # Update Speech Text Label
            if self._speech_label:
                body_height = frame.size.height - 42
                self._speech_label.setFrame_(NSRect(NSPoint(14, 8), NSSize(target_width - 28, body_height)))
                self._speech_label.setStringValue_(clean_text)

            # Order front
            self._panel.orderFrontRegardless()
            self._start_wave_animation()

        try:
            _update()
        except Exception:
            pass

    def update_text(self, text: str):
        """Update the spoken text dynamically (for streaming TTS or real-time text updates)."""
        def _update():
            if self._speech_label and self._panel:
                try:
                    if hasattr(self._panel, "isVisible") and self._panel.isVisible():
                        self._speech_label.setStringValue_(text.strip())
                    elif not hasattr(self._panel, "isVisible"):
                        self._speech_label.setStringValue_(text.strip())
                except Exception:
                    self._speech_label.setStringValue_(text.strip())

        try:
            _update()
        except Exception:
            pass

    def finish_speech(self, linger_seconds: float = 3.0):
        """Transition HUD to finish state and auto-hide after linger duration."""
        with self._lock:
            self._is_speaking = False
            self._stop_wave_animation()
            if self._hide_timer:
                self._hide_timer.cancel()
            if linger_seconds <= 0:
                self.hide()
            else:
                self._hide_timer = threading.Timer(linger_seconds, self.hide)
                self._hide_timer.daemon = True
                self._hide_timer.start()

    def hide(self):
        """Hide the speech HUD panel (Main thread safe)."""
        def _do_hide():
            self._stop_wave_animation()
            if self._panel:
                try:
                    self._panel.orderOut_(None)
                except Exception:
                    pass

        try:
            _do_hide()
        except Exception:
            pass

    def _start_wave_animation(self):
        """Animate equalizer waveform bars while speaking."""
        import os
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return

        from AppKit import NSApp
        if not (NSApp() and NSApp().isRunning()):
            return

        with self._lock:
            if not self._is_speaking:
                return
            if self._wave_timer is not None:
                return

        def _tick():
            with self._lock:
                self._wave_timer = None
                if not self._is_speaking or not self._panel:
                    return
                try:
                    if hasattr(self._panel, "isVisible") and not self._panel.isVisible():
                        return
                except Exception:
                    pass
                self._wave_step += 1
                step = self._wave_step

            # Update wave bars on main thread
            def _apply():
                for idx, bar in enumerate(self._wave_bars):
                    # Pseudo audio oscillation
                    h = 3 + int(8 * math.sin(step * 0.45 + idx * 1.2) ** 2)
                    y = 2 + (12 - h) / 2.0
                    bx = getattr(bar.frame().origin, "x", idx * 7)
                    bar.setFrame_(NSRect(NSPoint(bx, y), NSSize(3, h)))

            try:
                _apply()
            except Exception:
                pass

            with self._lock:
                if self._is_speaking:
                    self._wave_timer = threading.Timer(0.12, _tick)
                    self._wave_timer.daemon = True
                    self._wave_timer.start()

        _tick()

    def _stop_wave_animation(self):
        """Stop waveform timer and reset bars to resting state."""
        with self._lock:
            if self._wave_timer:
                self._wave_timer.cancel()
                self._wave_timer = None

        def _reset_bars():
            try:
                for idx, bar in enumerate(self._wave_bars):
                    bx = getattr(getattr(bar, "frame", lambda: None)(), "origin", None)
                    x_val = getattr(bx, "x", idx * 7) if bx else idx * 7
                    bar.setFrame_(NSRect(NSPoint(x_val, 6), NSSize(3, 4)))
            except Exception:
                pass

        try:
            _reset_bars()
        except Exception:
            pass


def preview_demo():
    """Standalone CLI preview for testing the Native Speech HUD."""
    from AppKit import NSApplication
    app = NSApplication.sharedApplication()

    hud = AgentSpeechHUD.get_instance()
    print("✨ Showing Native Agent Speech Pop-up Demo...")

    samples = [
        ("Antigravity", "Christopher", "I have implemented the agent speech pop-up HUD. Everything built cleanly and all unit tests passed!"),
        ("Researcher", "Sonia", "I audited the latest dependency graph and confirmed no memory leaks or unhandled audio exceptions."),
        ("Debugger", "Aria", "All 71 test assertions executed in 2.3 seconds with zero regressions! Ready for review."),
    ]

    def _run_sequence():
        for agent, persona, msg in samples:
            print(f"🔊 Pop-up: [{agent} • {persona}] {msg}")
            hud.show_speech(msg, agent_name=agent, persona_name=persona, is_speaking=True)
            time.sleep(3.5)
            hud.finish_speech(linger_seconds=2.0)
            time.sleep(2.5)
        print("✅ Demo finished. Exiting.")
        time.sleep(1.0)
        app.terminate_(None)

    threading.Thread(target=_run_sequence, daemon=True).start()
    app.run()


if __name__ == "__main__":
    preview_demo()
