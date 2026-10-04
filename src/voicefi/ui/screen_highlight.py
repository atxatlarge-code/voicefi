"""
Pal Screen & Focused Window Highlight Overlay for VoiceFi.
Provides a native macOS-style glowing focus border around the active window or screen perimeter
when 'Hey Pal' is actively listening, training, or executing computer use actions.
100% click-through (non-blocking), hardware-accelerated with native NSBezierPath drawRect.
"""

import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

import AppKit
import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSFont,
    NSInsetRect,
    NSPanel,
    NSPoint,
    NSRect,
    NSScreen,
    NSSize,
    NSTextField,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
)
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXValueGetValue,
    kAXValueCGPointType,
    kAXValueCGSizeType,
)
from PyObjCTools import AppHelper


def is_headless() -> bool:
    """Return True if running in headless or automated test environment."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("VOICEFI_TESTING") == "1"
        or os.getenv("PYTEST_CURRENT_TEST")
    )


try:
    HighlightBorderView = objc.lookUpClass("HighlightBorderView")
except objc.nosuchclass_error:

    class HighlightBorderView(NSView):
        """Native custom view that renders a crisp, glowing brand red border around the screen."""

        def init(self):
            self = objc.super(HighlightBorderView, self).init()
            if self:
                self.border_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.94, 0.22, 0.24, 0.98)
                self.tint_color = None
            return self

        def setBorderColor_tintColor_(self, border_col, tint_col):
            self.border_color = border_col
            self.tint_color = tint_col
            self.setNeedsDisplay_(True)

        def drawRect_(self, rect):
            bounds = self.bounds()
            if bounds.size.width <= 10 or bounds.size.height <= 10:
                return

            # Inset by half stroke width (4.5 / 2 = 2.25) so stroke is fully visible inside bounds
            stroke_rect = NSInsetRect(bounds, 2.5, 2.5)
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(stroke_rect, 14.0, 14.0)

            # 1. Subtle inner ambient illumination tint (only when explicitly provided; None by default)
            if self.tint_color:
                self.tint_color.setFill()
                path.fill()

            # 2. Signature 4.5px VoiceFi Brand Red stroke
            path.setLineWidth_(4.5)
            if self.border_color:
                self.border_color.setStroke()
            path.stroke()


class PalHighlightOverlay:
    """
    Non-activating, click-through overlay window that draws a glowing halo
    around the currently focused window or the full-screen perimeter.
    """

    _INSTANCE: Optional["PalHighlightOverlay"] = None
    _LOCK = threading.Lock()

    # Color Palettes - Signature VoiceFi Brand Red (#EF4444 / #EA4335)
    # Interior tint is None so no wash/tint covers the screen content - pure border outline only
    COLORS = {
        "hearing": {
            "border": (0.94, 0.22, 0.24, 0.98),      # VoiceFi Brand Red (#EF4444)
            "tint": None,
            "badge_bg": (0.45, 0.08, 0.10, 0.92),
            "text": "🎙️ Pal Listening",
        },
        "training": {
            "border": (0.96, 0.16, 0.20, 0.98),      # Deep Vibrant Brand Red (#E0002A)
            "tint": None,
            "badge_bg": (0.50, 0.06, 0.10, 0.94),
            "text": "🔴 Pal Training",
        },
        "executing": {
            "border": (0.19, 0.82, 0.35, 0.95),     # Emerald Green (#30D158)
            "tint": None,
            "badge_bg": (0.10, 0.35, 0.18, 0.90),
            "text": "⚡ Pal Executing",
        },
        "screen": {
            "border": (0.94, 0.22, 0.24, 0.98),      # Brand Red Screen Perimeter
            "tint": None,
            "badge_bg": (0.45, 0.08, 0.10, 0.92),
            "text": "👁️ Pal Watching",
        },
    }

    @classmethod
    def get_instance(cls) -> "PalHighlightOverlay":
        with cls._LOCK:
            if cls._INSTANCE is None:
                cls._INSTANCE = cls()
            return cls._INSTANCE

    def __init__(self):
        self._panel: Optional[NSPanel] = None
        self._border_view: Optional[NSView] = None
        self._badge: Optional[NSTextField] = None
        self._current_mode = "focused_window"
        self._current_color_type = "hearing"
        self._is_visible = False
        self._track_timer: Optional[threading.Timer] = None

        if not is_headless():
            if threading.current_thread() is threading.main_thread():
                self._init_window()
            else:
                AppHelper.callAfter(self._init_window)

    def _init_window(self) -> None:
        """Construct the borderless click-through NSPanel on the main thread."""
        try:
            screen = NSScreen.mainScreen()
            initial_rect = screen.frame() if screen else NSRect(NSPoint(0, 0), NSSize(800, 600))

            self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                initial_rect,
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False,
            )
            self._panel.setOpaque_(False)
            self._panel.setBackgroundColor_(NSColor.clearColor())
            self._panel.setIgnoresMouseEvents_(True)  # 100% click-through!
            self._panel.setHasShadow_(False)
            self._panel.setHidesOnDeactivate_(False)

            # High floating window level above standard application windows
            status_level = AppKit.NSStatusWindowLevel + 2
            self._panel.setLevel_(status_level)

            self._panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )

            # Native Custom Border View with NSBezierPath
            self._border_view = HighlightBorderView.alloc().init()
            self._border_view.setFrame_(NSRect(NSPoint(0, 0), initial_rect.size))

            # Floating badge label (hidden by default so only clean screen border shows)
            self._badge = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(16.0, 16.0), NSSize(160.0, 26.0)))
            self._badge.setBezeled_(False)
            self._badge.setDrawsBackground_(True)
            self._badge.setEditable_(False)
            self._badge.setSelectable_(False)
            self._badge.setAlignment_(AppKit.NSTextAlignmentCenter)
            self._badge.setFont_(NSFont.boldSystemFontOfSize_(11.0))
            self._badge.setTextColor_(NSColor.whiteColor())
            self._badge.setWantsLayer_(True)
            self._badge.layer().setCornerRadius_(13.0)
            self._badge.layer().setMasksToBounds_(True)
            self._badge.setHidden_(True)

            self._border_view.addSubview_(self._badge)
            self._panel.setContentView_(self._border_view)
            self._panel.setAlphaValue_(0.0)
            self._panel.orderOut_(None)  # Keep completely unmapped from WindowServer until actively triggered
            print("[PalHighlightOverlay] Window successfully initialized on main thread.")
        except Exception as e:
            print(f"[PalHighlightOverlay] Init failed: {e}")

    def show_for_focused_window(
        self,
        color_type: str = "hearing",
        badge_text: Optional[str] = None,
    ) -> None:
        """
        Highlight the frontmost application's active window with a glowing halo
        and follow focus changes in real-time.
        """
        self._current_mode = "focused_window"
        self._current_color_type = color_type

        def _present():
            if not self._panel:
                self._init_window()

            self._apply_style(color_type, badge_text)
            rect = self._query_focused_window_frame()
            if rect:
                self._update_panel_frame(rect)
                print(f"[PalHighlightOverlay] Showing Brand Red halo for focused window: ({rect.origin.x}, {rect.origin.y}, {rect.size.width}x{rect.size.height})")
            else:
                self._fallback_to_screen()
                print("[PalHighlightOverlay] Showing Brand Red halo for full screen perimeter.")

            if self._panel:
                self._panel.orderFrontRegardless()
                self._panel.setAlphaValue_(1.0)
                self._is_visible = True
            self._start_tracking_loop()

        if threading.current_thread() is threading.main_thread():
            _present()
        else:
            AppHelper.callAfter(_present)

    def show_screen_perimeter(
        self,
        color_type: str = "screen",
        badge_text: Optional[str] = None,
    ) -> None:
        """Draw an edge-glow highlight around the entire active display perimeter."""
        self._current_mode = "screen"
        self._current_color_type = color_type

        def _present():
            if not self._panel:
                self._init_window()

            self._apply_style(color_type, badge_text)
            self._fallback_to_screen()
            if self._panel:
                self._panel.orderFrontRegardless()
                self._panel.setAlphaValue_(1.0)
                self._is_visible = True

        if threading.current_thread() is threading.main_thread():
            _present()
        else:
            AppHelper.callAfter(_present)

    def hide(self) -> None:
        """Conceal the highlight halo."""
        self._stop_tracking_loop()
        self._is_visible = False

        def _hide():
            if self._panel:
                self._panel.orderOut_(None)
                self._panel.setAlphaValue_(0.0)

        if threading.current_thread() is threading.main_thread():
            _hide()
        else:
            AppHelper.callAfter(_hide)

    def _apply_style(self, color_type: str, badge_text: Optional[str] = None) -> None:
        palette = self.COLORS.get(color_type, self.COLORS["hearing"])
        r, g, b, a = palette["border"]
        border_col = NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)

        tint_col = None
        if palette.get("tint"):
            tr, tg, tb, ta = palette["tint"]
            tint_col = NSColor.colorWithCalibratedRed_green_blue_alpha_(tr, tg, tb, ta)

        if self._border_view and hasattr(self._border_view, "setBorderColor_tintColor_"):
            self._border_view.setBorderColor_tintColor_(border_col, tint_col)

        if self._badge:
            text = badge_text or palette.get("text", "")
            self._badge.setStringValue_(text)
            if palette.get("badge_bg"):
                br, bg_g, bb, ba = palette["badge_bg"]
                badge_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(br, bg_g, bb, ba)
                self._badge.setBackgroundColor_(badge_bg)
            # Only display badge if explicit badge_text was provided, otherwise keep hidden
            self._badge.setHidden_(not bool(badge_text))

    def _query_focused_window_frame(self) -> Optional[NSRect]:
        """
        Query frontmost application's focused window frame in ~0.07ms via AXUIElement.
        Converts Quartz top-left coordinates to Cocoa bottom-left coordinates.
        """
        try:
            ws = NSWorkspace.sharedWorkspace()
            front = ws.frontmostApplication()
            if not front:
                return None

            pid = front.processIdentifier()
            app_ax = AXUIElementCreateApplication(pid)
            err, win = AXUIElementCopyAttributeValue(app_ax, "AXFocusedWindow", None)
            if err != 0 or not win:
                return None

            _, pos_val = AXUIElementCopyAttributeValue(win, "AXPosition", None)
            _, size_val = AXUIElementCopyAttributeValue(win, "AXSize", None)
            if not pos_val or not size_val:
                return None

            ok1, pt = AXValueGetValue(pos_val, kAXValueCGPointType, None)
            ok2, sz = AXValueGetValue(size_val, kAXValueCGSizeType, None)
            if not ok1 or not ok2 or sz.width < 50 or sz.height < 50:
                return None

            screens = NSScreen.screens()
            if not screens:
                return None
            screen_h = screens[0].frame().size.height

            # Outset by 4px so border sits gracefully right around the window edge
            padding = 4.0
            cocoa_x = pt.x - padding
            cocoa_y = (screen_h - (pt.y + sz.height)) - padding
            cocoa_w = sz.width + (padding * 2.0)
            cocoa_h = sz.height + (padding * 2.0)

            return NSRect(NSPoint(cocoa_x, cocoa_y), NSSize(cocoa_w, cocoa_h))
        except Exception:
            return None

    def _update_panel_frame(self, target_rect: NSRect) -> None:
        """Update window position and geometry smoothly."""
        if not self._panel or not self._border_view:
            return

        self._panel.setFrame_display_(target_rect, True)
        self._border_view.setFrame_(NSRect(NSPoint(0, 0), target_rect.size))
        self._border_view.setNeedsDisplay_(True)

        # Position badge at top-right inside the window halo
        if self._badge:
            badge_w = 140.0
            badge_h = 24.0
            bx = target_rect.size.width - badge_w - 18.0
            by = target_rect.size.height - badge_h - 10.0
            self._badge.setFrame_(NSRect(NSPoint(max(10.0, bx), max(10.0, by)), NSSize(badge_w, badge_h)))

    def _fallback_to_screen(self) -> None:
        """Set halo to the main screen perimeter."""
        screen = NSScreen.mainScreen()
        if not screen or not self._panel or not self._border_view:
            return
        frame = screen.frame()
        inset = 3.0
        rect = NSRect(
            NSPoint(frame.origin.x + inset, frame.origin.y + inset),
            NSSize(frame.size.width - (inset * 2.0), frame.size.height - (inset * 2.0)),
        )
        self._panel.setFrame_display_(rect, True)
        self._border_view.setFrame_(NSRect(NSPoint(0, 0), rect.size))
        self._border_view.setNeedsDisplay_(True)
        if self._badge:
            bx = rect.size.width - 150.0
            by = rect.size.height - 35.0
            self._badge.setFrame_(NSRect(NSPoint(bx, by), NSSize(140.0, 24.0)))

    def _start_tracking_loop(self) -> None:
        """Poll focused window every 150ms while active to follow window movements."""
        self._stop_tracking_loop()
        if not self._is_visible or self._current_mode != "focused_window":
            return

        def _tick():
            if not self._is_visible:
                return
            rect = self._query_focused_window_frame()
            if rect:
                AppHelper.callAfter(self._update_panel_frame, rect)
            self._track_timer = threading.Timer(0.18, _tick)
            self._track_timer.daemon = True
            self._track_timer.start()

        self._track_timer = threading.Timer(0.18, _tick)
        self._track_timer.daemon = True
        self._track_timer.start()

    def _stop_tracking_loop(self) -> None:
        if self._track_timer:
            self._track_timer.cancel()
            self._track_timer = None
