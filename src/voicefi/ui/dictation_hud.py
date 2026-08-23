"""
Native macOS Floating Dictation HUD Capsule.
Provides a non-intrusive, floating status pill indicator at the top of the screen
during universal dictation (Ctrl + T) without stealing focus from the active app.
"""

import time
import threading
from typing import Optional
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
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
)
from PyObjCTools import AppHelper


class DictationHUD:
    """Singleton Floating HUD Capsule for Universal Dictation."""

    _instance: Optional["DictationHUD"] = None

    @classmethod
    def get_instance(cls) -> "DictationHUD":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._panel: Optional[NSPanel] = None
        self._label: Optional[NSTextField] = None
        self._root_view: Optional[NSView] = None
        self._hide_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._build_panel()

    def _position_top_center(self):
        if not self._panel:
            return
        screen = NSScreen.mainScreen()
        if screen:
            visible_frame = screen.visibleFrame()
            panel_frame = self._panel.frame()
            x = visible_frame.origin.x + (visible_frame.size.width - panel_frame.size.width) / 2.0
            y = visible_frame.origin.y + visible_frame.size.height - panel_frame.size.height - 18.0
            self._panel.setFrameOrigin_(NSPoint(x, y))

    def _build_panel(self):
        width, height = 240, 40
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
        self._panel.setLevel_(NSFloatingWindowLevel + 2)
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

        root_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
        root_view.setWantsLayer_(True)
        root_view.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.12, 0.15, 0.92).CGColor()
        )
        root_view.layer().setCornerRadius_(20.0)
        root_view.layer().setBorderWidth_(1.0)
        root_view.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.18).CGColor()
        )
        self._root_view = root_view

        label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(10, 8), NSSize(width - 20, 24)))
        label.setStringValue_("🎙️ Listening...")
        label.setFont_(NSFont.boldSystemFontOfSize_(13))
        label.setTextColor_(NSColor.whiteColor())
        label.setAlignment_(1)  # Center aligned (NSTextAlignmentCenter)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        root_view.addSubview_(label)
        self._label = label

        self._panel.setContentView_(root_view)

    def show_listening(self):
        """Display listening state on the main thread."""
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

        def _update():
            if self._label:
                self._label.setStringValue_("🔴 Listening... (Speak)")
                self._label.setTextColor_(NSColor.systemRedColor())
            if self._panel:
                self._position_top_center()
                self._panel.orderFrontRegardless()

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    def show_paused(self, message: str = "⏸️ Agent Speaking (Paused)..."):
        """Display paused state when an AI agent is speaking."""
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

        def _update():
            if self._label:
                self._label.setStringValue_(message)
                self._label.setTextColor_(NSColor.systemOrangeColor())
            if self._panel:
                self._position_top_center()
                self._panel.orderFrontRegardless()

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    def show_transcribing(self):
        """Display transcribing state on the main thread."""
        def _update():
            if self._label:
                self._label.setStringValue_("⏳ Transcribing...")
                self._label.setTextColor_(NSColor.systemYellowColor())
            if self._panel:
                self._position_top_center()
                self._panel.orderFrontRegardless()

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    def show_done(self, preview_text: str = ""):
        """Display success and auto-hide after brief delay."""
        def _update():
            if self._label:
                disp = f"✅ {preview_text[:20]}..." if preview_text else "✅ Transcribed"
                self._label.setStringValue_(disp)
                self._label.setTextColor_(NSColor.systemGreenColor())
            if self._panel:
                self._panel.orderFrontRegardless()

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
            self._hide_timer = threading.Timer(0.7, self.hide)
            self._hide_timer.daemon = True
            self._hide_timer.start()

    def hide(self):
        """Hide the HUD panel."""
        def _do_hide():
            if self._panel and self._panel.isVisible():
                self._panel.orderOut_(None)

        if threading.current_thread() is threading.main_thread():
            _do_hide()
        else:
            AppHelper.callAfter(_do_hide)
