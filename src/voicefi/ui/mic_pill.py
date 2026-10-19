"""
Native macOS Top-Bar / Menu-Bar Orange Microphone Indicator Pill for VoiceFi.

Renders a sleek, non-activating Apple Control Center / Dynamic Island style orange
microphone indicator pill at the top of the primary display (right alongside the menu bar / notch)
whenever VoiceFi's microphone is actively listening or hearing speech—whether triggered by
a wake word ('Hey Viv', 'Hey Brok', 'Hey Pal', 'Hey Claude', 'Hey Antigravity') or hotkey.

Visual anatomy:
- Frosted dark obsidian capsule (height 26px, corner radius 13px)
- Vibrant Apple System Orange (#FF9500) circular/pill mic badge on the left with white 'mic.fill' icon
- Crisp SF Pro Bold target label in the center ('VoiceFi', 'Brok', 'Pal', 'Claude', 'Antigravity', etc.)
- 4-bar real-time reactive mini waveform on the right
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
from typing import Any, Callable, Optional

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSPanel,
    NSPoint,
    NSRect,
    NSScreen,
    NSSize,
    NSStatusWindowLevel,
    NSString,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from PyObjCTools import AppHelper


def is_headless() -> bool:
    """Return True if running in headless or automated test environment."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("VOICEFI_TESTING") == "1"
        or "pytest" in sys.modules
    )


try:
    TopBarMicPillView = objc.lookUpClass("TopBarMicPillView")
except objc.nosuchclass_error:

    class TopBarMicPillView(NSView):
        """Custom hardware-accelerated NSView rendering the macOS Orange Mic Indicator Pill."""

        def initWithFrame_(self, frame: NSRect):
            self = objc.super(TopBarMicPillView, self).initWithFrame_(frame)
            if self is not None:
                self._target_label = "VoiceFi"
                self._state = "listening"
                self._levels = [0.22, 0.35, 0.28, 0.20]
                self._multipliers = [0.75, 1.35, 1.15, 0.80]
                self._phase = 0.0
                self._is_speech = False
                self._speech_prob = 0.0
                self._on_click: Optional[Callable[[], None]] = None
            return self

        def acceptsFirstMouse_(self, event) -> bool:
            return True

        def mouseDown_(self, event) -> None:
            if self._on_click:
                try:
                    self._on_click()
                except Exception:
                    pass

        def setState_label_(self, state: str, label: str) -> None:
            self._state = state or "listening"
            self._target_label = (label or "VoiceFi").strip()
            self.setNeedsDisplay_(True)

        def setAudioLevel_prob_speech_(
            self, level: float, prob: float, is_speech: bool
        ) -> None:
            loudness = min(1.0, max(0.0, math.sqrt(max(0.0, float(level))) * 4.0))
            self._speech_prob = float(prob)
            self._is_speech = bool(is_speech or prob >= 0.40)
            self._phase = (self._phase + 0.45) % (2.0 * math.pi)

            for i, mult in enumerate(self._multipliers):
                osc = 0.82 + 0.18 * math.sin(self._phase + i * 1.3)
                tgt = max(0.18, min(1.0, loudness * mult * osc))
                if tgt > self._levels[i]:
                    self._levels[i] = 0.75 * tgt + 0.25 * self._levels[i]
                else:
                    self._levels[i] = 0.38 * tgt + 0.62 * self._levels[i]

            self.setNeedsDisplay_(True)

        def resetLevels(self) -> None:
            self._levels = [0.22, 0.30, 0.25, 0.20]
            self._is_speech = False
            self._speech_prob = 0.0
            self.setNeedsDisplay_(True)

        def drawRect_(self, dirtyRect: NSRect) -> None:
            bounds = self.bounds()
            w = float(bounds.size.width)
            h = float(bounds.size.height)
            if w <= 10 or h <= 10:
                return

            radius = h / 2.0

            # 1. Outer Pill Capsule Background (Deep Apple Menu-Bar Obsidian)
            bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                bounds, radius, radius
            )
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                0.08, 0.08, 0.10, 0.95
            ).setFill()
            bg_path.fill()

            # Subtle border glow (brightens when hearing active voice)
            is_active_voice = self._is_speech or self._state == "hearing"
            border_alpha = 0.88 if is_active_voice else 0.50
            if self._state == "transcribing":
                border_col = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.80, 0.20, 0.80
                )
            else:
                # Apple System Mic Orange (#FF9500)
                border_col = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.584, 0.0, border_alpha
                )
            inset_rect = NSRect(NSPoint(0.75, 0.75), NSSize(w - 1.5, h - 1.5))
            border_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                inset_rect, radius - 0.75, radius - 0.75
            )
            border_path.setLineWidth_(1.2 if is_active_voice else 1.0)
            border_col.setStroke()
            border_path.stroke()

            # 2. Left Apple System Orange Mic Circle Badge
            badge_size = h - 6.0  # 20px inside 26px pill
            badge_x = 3.0
            badge_y = 3.0
            badge_rect = NSRect(NSPoint(badge_x, badge_y), NSSize(badge_size, badge_size))
            badge_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                badge_rect, badge_size / 2.0, badge_size / 2.0
            )
            if self._state == "transcribing":
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.98, 0.72, 0.12, 1.0
                ).setFill()
            else:
                # Signature macOS Control Center Mic Orange (#FF9500)
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.584, 0.0, 1.0
                ).setFill()
            badge_path.fill()

            # Draw white microphone symbol inside the orange badge
            drawn_symbol = False
            try:
                sym_name = (
                    "ellipsis"
                    if self._state == "transcribing"
                    else "mic.fill"
                )
                img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    sym_name, None
                )
                if img:
                    # Render white template or fallback glyph
                    pass
            except Exception:
                pass

            if not drawn_symbol:
                # Draw crisp vector microphone capsule + stem in pure white inside the orange badge
                cx = badge_x + badge_size / 2.0
                cy = badge_y + badge_size / 2.0
                NSColor.whiteColor().setFill()
                NSColor.whiteColor().setStroke()

                # Mic capsule head
                cap_w = 4.6
                cap_h = 7.6
                cap_rect = NSRect(
                    NSPoint(cx - cap_w / 2.0, cy - 0.8),
                    NSSize(cap_w, cap_h),
                )
                cap_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    cap_rect, cap_w / 2.0, cap_w / 2.0
                )
                cap_path.fill()

                # Mic cradle arc + base stem
                cradle = NSBezierPath.bezierPath()
                cradle.setLineWidth_(1.35)
                cradle.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
                    NSPoint(cx, cy + 1.2), 4.2, 195.0, 345.0
                )
                cradle.stroke()

                stem = NSBezierPath.bezierPath()
                stem.setLineWidth_(1.35)
                stem.moveToPoint_(NSPoint(cx, cy - 3.0))
                stem.lineToPoint_(NSPoint(cx, cy - 5.2))
                stem.moveToPoint_(NSPoint(cx - 2.4, cy - 5.2))
                stem.lineToPoint_(NSPoint(cx + 2.4, cy - 5.2))
                stem.stroke()

            # 3. Center Target App / Agent Label (e.g., "Antigravity", "VoiceFi", "Brok", "Pal", "Claude")
            text_x = badge_x + badge_size + 7.0
            font = NSFont.boldSystemFontOfSize_(11.5)
            attrs = {
                NSFontAttributeName: font,
                NSForegroundColorAttributeName: NSColor.whiteColor(),
            }
            ns_label = NSString.stringWithString_(self._target_label)
            text_size = ns_label.sizeWithAttributes_(attrs)
            text_y = (h - float(text_size.height)) / 2.0
            ns_label.drawAtPoint_withAttributes_(NSPoint(text_x, text_y), attrs)

            # 4. Right 4-Bar Reactive Mini Waveform
            num_bars = len(self._levels)
            bar_w = 2.4
            bar_gap = 1.8
            bars_total_w = num_bars * bar_w + (num_bars - 1) * bar_gap
            bars_start_x = w - bars_total_w - 8.5

            if is_active_voice:
                # Vibrant Apple System Orange / Coral glow when speaking
                bar_col = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.62, 0.08, 0.98
                )
            else:
                bar_col = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.584, 0.0, 0.65
                )
            bar_col.setFill()

            min_bh = 3.2
            max_bh = h - 10.0
            for i, lvl in enumerate(self._levels):
                bh = min_bh + (max_bh - min_bh) * float(lvl)
                bx = bars_start_x + i * (bar_w + bar_gap)
                by = (h - bh) / 2.0
                b_rect = NSRect(NSPoint(bx, by), NSSize(bar_w, bh))
                b_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    b_rect, bar_w / 2.0, bar_w / 2.0
                )
                b_path.fill()


class TopBarMicIndicatorPill:
    """
    Singleton Native macOS Top-Bar Orange Microphone Indicator Pill.
    Pops up at the top of the screen (menu bar / notch region) whenever VoiceFi's
    microphone is active, displaying the orange mic badge + target name ('VoiceFi',
    'Brok', 'Pal', 'Claude', 'Antigravity', or active app) + live voice equalizer.
    """

    _INSTANCE: Optional["TopBarMicIndicatorPill"] = None
    _LOCK = threading.Lock()

    PILL_HEIGHT: float = 26.0

    @classmethod
    def get_instance(cls) -> "TopBarMicIndicatorPill":
        with cls._LOCK:
            if cls._INSTANCE is None:
                cls._INSTANCE = cls()
            return cls._INSTANCE

    def __init__(self):
        self._panel: Optional[NSPanel] = None
        self._view: Optional[Any] = None
        self._is_visible: bool = False
        self._current_label: str = "VoiceFi"
        self._current_state: str = "idle"

        if not is_headless():
            if threading.current_thread() is threading.main_thread():
                self._init_window()
            else:
                AppHelper.callAfter(self._init_window)

    def _compute_pill_frame(self, label: str) -> NSRect:
        """Compute top-bar pill width and position right alongside the macOS menu bar / notch."""
        try:
            font = NSFont.boldSystemFontOfSize_(11.5)
            attrs = {NSFontAttributeName: font}
            s = NSString.stringWithString_(label or "VoiceFi")
            tw = float(s.sizeWithAttributes_(attrs).width)
        except Exception:
            tw = len(label or "VoiceFi") * 7.2

        # Left badge (26px) + text + right waveform (26px) + padding
        width = max(112.0, min(240.0, 32.0 + tw + 34.0))
        height = self.PILL_HEIGHT

        screen = NSScreen.mainScreen()
        if screen:
            sf = screen.frame()
            vf = screen.visibleFrame()
            # Position just to the right of the center notch (or top-center-right) inside/just below menu bar
            x = float(sf.origin.x) + (float(sf.size.width) / 2.0) + 115.0
            # Ensure it sits right at the top menu bar edge
            menu_bar_bottom = float(vf.origin.y) + float(vf.size.height)
            screen_top = float(sf.origin.y) + float(sf.size.height)
            if (screen_top - menu_bar_bottom) >= 22.0:
                # Sit vertically centered inside the menu bar band
                y = screen_top - ((screen_top - menu_bar_bottom + height) / 2.0)
            else:
                y = screen_top - height - 4.0
        else:
            x, y = 840.0, 860.0

        return NSRect(NSPoint(x, y), NSSize(width, height))

    def _init_window(self) -> None:
        if is_headless() or self._panel is not None:
            return
        try:
            frame = self._compute_pill_frame(self._current_label)
            style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                frame, style, NSBackingStoreBuffered, False
            )
            panel.setLevel_(NSStatusWindowLevel + 2)
            panel.setOpaque_(False)
            panel.setBackgroundColor_(NSColor.clearColor())
            panel.setHasShadow_(True)
            panel.setIgnoresMouseEvents_(False)
            panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )

            view_frame = NSRect(NSPoint(0.0, 0.0), frame.size)
            view = TopBarMicPillView.alloc().initWithFrame_(view_frame)
            panel.setContentView_(view)
            self._panel = panel
            self._view = view
        except Exception:
            self._panel = None
            self._view = None

    @staticmethod
    def resolve_display_label(
        app_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        source: Optional[str] = None,
        user_name: Optional[str] = None,
    ) -> str:
        """
        Resolve a clean, human-readable target name for VoiceFi
        (e.g., 'Antigravity', 'VoiceFi', 'Brok', 'Pal', 'Claude', 'Codex').
        """
        candidates = [agent_name, app_name, source, user_name]
        for c in candidates:
            if not c:
                continue
            cl = c.lower().strip()
            if "brok" in cl or "brock" in cl:
                return "Brok"
            if "pal" in cl:
                return "Pal"
            if "claude" in cl:
                return "Claude"
            if "codex" in cl or "chatgpt" in cl or "openai" in cl:
                return "Codex"
            if "cursor" in cl:
                return "Cursor"
            if "windsurf" in cl:
                return "Windsurf"
            if "obsidian" in cl:
                return "Obsidian"
            if "viv" in cl or "vifi" in cl or "vi-fi" in cl or "voicefi" in cl:
                if app_name and app_name.lower().strip() not in (
                    "voicefi",
                    "vifi",
                    "viv",
                    "antigravity",
                ):
                    return f"VoiceFi • {app_name.strip().title()}"
                return "VoiceFi"
            if "antigravity" in cl or "anti-gravity" in cl:
                return "Antigravity"

        if app_name and app_name.strip():
            clean_app = app_name.strip()
            if clean_app.lower() not in ("main", "active agent", "jake", "developer"):
                return clean_app[:18]

        return "VoiceFi"

    def show(
        self,
        state: str = "listening",
        label: Optional[str] = None,
        app_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        source: Optional[str] = None,
        user_name: Optional[str] = None,
    ) -> None:
        """Show the top-bar orange mic indicator pill with the resolved target label."""
        resolved_label = label or self.resolve_display_label(
            app_name=app_name,
            agent_name=agent_name,
            source=source,
            user_name=user_name,
        )
        self._current_label = resolved_label
        self._current_state = state
        if is_headless():
            self._is_visible = False
            return

        def _do():
            if self._panel is None:
                self._init_window()
            if self._panel is None or self._view is None:
                return
            frame = self._compute_pill_frame(resolved_label)
            self._panel.setFrame_display_(frame, True)
            self._view.setFrame_(NSRect(NSPoint(0.0, 0.0), frame.size))
            self._view.setState_label_(state, resolved_label)
            self._panel.orderFrontRegardless()
            self._is_visible = True

        if threading.current_thread() is threading.main_thread():
            _do()
        else:
            AppHelper.callAfter(_do)

    def update_audio_level(
        self, energy: float, prob: float = 0.0, is_speech: bool = False
    ) -> None:
        """Update the 4-bar waveform inside the top-bar mic pill."""
        if is_headless() or not self._is_visible or self._view is None:
            return

        def _do():
            if self._view is not None and self._is_visible:
                self._view.setAudioLevel_prob_speech_(energy, prob, is_speech)

        if threading.current_thread() is threading.main_thread():
            _do()
        else:
            AppHelper.callAfter(_do)

    def hide(self) -> None:
        """Hide the top-bar orange mic indicator pill."""
        self._current_state = "idle"
        self._is_visible = False
        if is_headless() or self._panel is None:
            return

        def _do():
            if self._view is not None:
                self._view.resetLevels()
            if self._panel is not None:
                try:
                    self._panel.orderOut_(None)
                except Exception:
                    pass

        if threading.current_thread() is threading.main_thread():
            _do()
        else:
            AppHelper.callAfter(_do)

