"""
Native macOS Floating Activity Hub and Conversation Switcher.
Provides a floating panel displaying active agent conversations, real-time statuses,
and one-click / shortcut jumping.
"""

from typing import List, Callable, Optional
from pathlib import Path
from AppKit import (
    NSPanel,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskUtilityWindow,
    NSBackingStoreBuffered,
    NSRect,
    NSPoint,
    NSSize,
    NSTextField,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSBezelStyleRounded,
    NSView,
    NSScreen,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorMoveToActiveSpace,
)
import objc
from voicefi.integrations.conversations import ConversationInfo, ConversationTracker
from voicefi.integrations.injector import focus_antigravity


import time
import threading
from PyObjCTools import AppHelper
from AppKit import NSApp


try:
    HubActionTarget = objc.lookUpClass("HubActionTarget")
except objc.nosuchclass_error:
    class HubActionTarget(objc.lookUpClass("NSObject")):
        """Objective-C target wrapper for NSButton clicks."""

        def initWithCallback_(self, callback):
            self = objc.super(HubActionTarget, self).init()
            if self is not None:
                self.callback = callback
            return self

        def buttonClicked_(self, sender):
            if self.callback:
                self.callback()


class ConversationHubWindow:
    """Floating Activity Hub window for VoiceFi."""

    _instance: Optional["ConversationHubWindow"] = None

    @classmethod
    def get_instance(cls, tracker: ConversationTracker, on_switch: Optional[Callable] = None, on_talk: Optional[Callable] = None) -> "ConversationHubWindow":
        if cls._instance is None:
            cls._instance = cls(tracker, on_switch, on_talk)
        return cls._instance

    def __init__(
        self,
        tracker: ConversationTracker,
        on_switch: Optional[Callable[[str, Optional[Path], Optional[str]], None]] = None,
        on_talk: Optional[Callable[[str], None]] = None,
    ):
        self.tracker = tracker
        self.on_switch = on_switch
        self.on_talk = on_talk
        self._targets: List[HubActionTarget] = []
        self._panel: Optional[NSPanel] = None
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._last_toggle_time = 0.0
        self._build_panel()

    def _position_top_right(self):
        """Position the panel at the top right of the primary screen with standard margin."""
        if not self._panel:
            return
        screen = NSScreen.mainScreen()
        if screen:
            visible_frame = screen.visibleFrame()
            panel_frame = self._panel.frame()
            margin = 20.0
            x = visible_frame.origin.x + visible_frame.size.width - panel_frame.size.width - margin
            y = visible_frame.origin.y + visible_frame.size.height - panel_frame.size.height - margin
            self._panel.setFrameOrigin_(NSPoint(x, y))

    def _build_panel(self):
        """Construct the native NSPanel floating persistent utility window."""
        width, height = 520, 420
        screen = NSScreen.mainScreen()
        if screen:
            visible_frame = screen.visibleFrame()
            margin = 20.0
            init_x = visible_frame.origin.x + visible_frame.size.width - width - margin
            init_y = visible_frame.origin.y + visible_frame.size.height - height - margin
        else:
            init_x, init_y = 1200, 700

        rect = NSRect(NSPoint(init_x, init_y), NSSize(width, height))
        style_mask = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskResizable
            | NSWindowStyleMaskUtilityWindow
        )
        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        self._panel.setTitle_("VoiceFi • Activity Hub (Persistent HUD)")
        self._panel.setLevel_(NSFloatingWindowLevel)
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

    def _start_auto_refresh(self):
        with self._lock:
            if self._timer is None:
                self._timer = threading.Timer(1.5, self._timer_tick)
                self._timer.daemon = True
                self._timer.start()

    def _stop_auto_refresh(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _timer_tick(self):
        with self._lock:
            self._timer = None
        if self._panel and self._panel.isVisible():
            self.refresh()
            self._start_auto_refresh()

    def show(self):
        """Refresh contents and display the panel persistently on screen (Main Thread safe)."""
        def _do_show():
            self._refresh_ui()
            if self._panel:
                if not self._panel.isVisible():
                    self._position_top_right()
                NSApp.activateIgnoringOtherApps_(True)
                self._panel.orderFrontRegardless()
                self._panel.makeKeyAndOrderFront_(None)
                self._start_auto_refresh()

        if threading.current_thread() is threading.main_thread():
            _do_show()
        else:
            AppHelper.callAfter(_do_show)

    def hide(self):
        """Hide the hub panel (Main Thread safe)."""
        def _do_hide():
            self._stop_auto_refresh()
            if self._panel and self._panel.isVisible():
                self._panel.orderOut_(None)

        if threading.current_thread() is threading.main_thread():
            _do_hide()
        else:
            AppHelper.callAfter(_do_hide)

    def toggle(self):
        """Toggle hub visibility (Main Thread safe with debounce)."""
        with self._lock:
            now = time.time()
            if (now - self._last_toggle_time) < 0.4:
                return
            self._last_toggle_time = now

        def _do_toggle():
            if self._panel and self._panel.isVisible():
                self.hide()
            else:
                self.show()

        if threading.current_thread() is threading.main_thread():
            _do_toggle()
        else:
            AppHelper.callAfter(_do_toggle)

    def refresh(self, force: bool = False):
        """Trigger UI refresh (Main Thread safe)."""
        def _do_refresh():
            self._refresh_ui(force=force)

        if threading.current_thread() is threading.main_thread():
            _do_refresh()
        else:
            AppHelper.callAfter(_do_refresh)

    def _refresh_ui(self, force: bool = False):
        """Populate the conversation list on the main thread."""
        if not self._panel:
            return

        convs = self.tracker.get_all_conversations(limit=7)
        active_conv = self.tracker.get_active_or_latest()
        active_id = active_conv.id if active_conv else None

        current_sig = (active_id, tuple((c.id, c.status, c.mtime, c.title) for c in convs))
        if (
            not force
            and hasattr(self, "_last_ui_sig")
            and self._last_ui_sig == current_sig
            and self._panel.contentView() is not None
            and len(self._panel.contentView().subviews()) > 0
        ):
            return

        self._last_ui_sig = current_sig
        self._targets.clear()

        bounds = self._panel.contentView().bounds()
        root_view = NSView.alloc().initWithFrame_(bounds)
        root_view.setWantsLayer_(True)

        # Header Title
        header = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(20, bounds.size.height - 40), NSSize(165, 26)))
        header.setStringValue_("Agent Status (HUD)")
        header.setFont_(NSFont.boldSystemFontOfSize_(14))
        header.setBezeled_(False)
        header.setDrawsBackground_(False)
        header.setEditable_(False)
        header.setSelectable_(False)
        header.setWantsLayer_(True)
        root_view.addSubview_(header)

        # Jump to Antigravity Button
        def _jump_ag():
            focus_antigravity(focus_input=True)

        jump_ag_target = HubActionTarget.alloc().initWithCallback_(_jump_ag)
        self._targets.append(jump_ag_target)

        jump_ag_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(190, bounds.size.height - 42), NSSize(125, 26)))
        jump_ag_btn.setTitle_("💬 Antigravity")
        jump_ag_btn.setBezelStyle_(NSBezelStyleRounded)
        jump_ag_btn.setTarget_(jump_ag_target)
        jump_ag_btn.setAction_(objc.selector(jump_ag_target.buttonClicked_, signature=b"v@:@"))
        jump_ag_btn.setWantsLayer_(True)
        root_view.addSubview_(jump_ag_btn)

        # Refresh List Button
        refresh_target = HubActionTarget.alloc().initWithCallback_(self.refresh)
        self._targets.append(refresh_target)

        refresh_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(320, bounds.size.height - 42), NSSize(85, 26)))
        refresh_btn.setTitle_("🔄 Refresh")
        refresh_btn.setBezelStyle_(NSBezelStyleRounded)
        refresh_btn.setTarget_(refresh_target)
        refresh_btn.setAction_(objc.selector(refresh_target.buttonClicked_, signature=b"v@:@"))
        refresh_btn.setWantsLayer_(True)
        root_view.addSubview_(refresh_btn)

        # Voice Control Panel Button
        def _open_panel():
            from voicefi.ui.panel import open_control_panel
            open_control_panel()

        panel_target = HubActionTarget.alloc().initWithCallback_(_open_panel)
        self._targets.append(panel_target)

        panel_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(410, bounds.size.height - 42), NSSize(90, 26)))
        panel_btn.setTitle_("🎛️ Panel")
        panel_btn.setBezelStyle_(NSBezelStyleRounded)
        panel_btn.setTarget_(panel_target)
        panel_btn.setAction_(objc.selector(panel_target.buttonClicked_, signature=b"v@:@"))
        panel_btn.setWantsLayer_(True)
        root_view.addSubview_(panel_btn)

        # Instructions / Shortcut note
        hint = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(20, bounds.size.height - 66), NSSize(475, 18)))
        hint.setStringValue_("Ctrl + R to respond • Ctrl + J to switch window • Persistent Activity HUD")
        hint.setFont_(NSFont.systemFontOfSize_(11))
        hint.setTextColor_(NSColor.secondaryLabelColor())
        hint.setBezeled_(False)
        hint.setDrawsBackground_(False)
        hint.setEditable_(False)
        hint.setSelectable_(False)
        hint.setWantsLayer_(True)
        root_view.addSubview_(hint)

        y_pos = int(bounds.size.height - 116)
        status_icons = {
            "waiting_for_user": "🟢 Waiting for you",
            "agent_working": "⏳ Agent working",
            "idle": "⚪ Idle",
        }

        if not convs:
            empty_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(20, y_pos), NSSize(470, 24)))
            empty_lbl.setStringValue_("No recent Antigravity conversations found.")
            empty_lbl.setFont_(NSFont.systemFontOfSize_(13))
            empty_lbl.setBezeled_(False)
            empty_lbl.setDrawsBackground_(False)
            empty_lbl.setEditable_(False)
            empty_lbl.setWantsLayer_(True)
            root_view.addSubview_(empty_lbl)
        else:
            for i, c in enumerate(convs[:6]):
                is_active = (c.id == active_id)
                status_text = status_icons.get(c.status, "⚪ Idle")

                # Container card view for clean isolation
                card_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(16, y_pos - 8), NSSize(488, 44)))
                card_view.setWantsLayer_(True)
                card_view.layer().setCornerRadius_(6.0)

                if is_active:
                    card_view.layer().setBackgroundColor_(NSColor.systemGreenColor().colorWithAlphaComponent_(0.10).CGColor())
                    card_view.layer().setBorderWidth_(1.2)
                    card_view.layer().setBorderColor_(NSColor.systemGreenColor().colorWithAlphaComponent_(0.6).CGColor())
                else:
                    card_view.layer().setBackgroundColor_(NSColor.controlBackgroundColor().colorWithAlphaComponent_(0.35).CGColor())
                    card_view.layer().setBorderWidth_(0.5)
                    card_view.layer().setBorderColor_(NSColor.separatorColor().CGColor())

                # Conversation Title Label
                title_clean = c.title[:38] + ("..." if len(c.title) > 38 else "")
                title_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(10, 20), NSSize(340, 20)))
                title_lbl.setStringValue_(title_clean)
                if is_active:
                    title_lbl.setFont_(NSFont.boldSystemFontOfSize_(13))
                    title_lbl.setTextColor_(NSColor.systemGreenColor())
                else:
                    title_lbl.setFont_(NSFont.systemFontOfSize_(13))
                    title_lbl.setTextColor_(NSColor.labelColor())
                title_lbl.setBezeled_(False)
                title_lbl.setDrawsBackground_(False)
                title_lbl.setEditable_(False)
                title_lbl.setSelectable_(False)
                title_lbl.setWantsLayer_(True)
                card_view.addSubview_(title_lbl)

                # Status Subtitle
                status_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(10, 3), NSSize(340, 16)))
                status_lbl.setStringValue_(status_text)
                status_lbl.setFont_(NSFont.systemFontOfSize_(11))
                status_lbl.setTextColor_(NSColor.secondaryLabelColor())
                status_lbl.setBezeled_(False)
                status_lbl.setDrawsBackground_(False)
                status_lbl.setEditable_(False)
                status_lbl.setSelectable_(False)
                status_lbl.setWantsLayer_(True)
                card_view.addSubview_(status_lbl)

                # Right Badge Label (Shows [ACTIVE] or [BACKGROUND])
                badge_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(355, 12), NSSize(125, 20)))
                if is_active:
                    badge_lbl.setStringValue_("🟢 ACTIVE")
                    badge_lbl.setFont_(NSFont.boldSystemFontOfSize_(11))
                    badge_lbl.setTextColor_(NSColor.systemGreenColor())
                else:
                    if c.status == "waiting_for_user":
                        badge_lbl.setStringValue_("READY")
                        badge_lbl.setTextColor_(NSColor.systemOrangeColor())
                    elif c.status == "agent_working":
                        badge_lbl.setStringValue_("WORKING")
                        badge_lbl.setTextColor_(NSColor.systemBlueColor())
                    else:
                        badge_lbl.setStringValue_("IDLE")
                        badge_lbl.setTextColor_(NSColor.tertiaryLabelColor())
                    badge_lbl.setFont_(NSFont.systemFontOfSize_(11))

                badge_lbl.setAlignment_(2)  # NSTextAlignmentRight
                badge_lbl.setBezeled_(False)
                badge_lbl.setDrawsBackground_(False)
                badge_lbl.setEditable_(False)
                badge_lbl.setSelectable_(False)
                badge_lbl.setWantsLayer_(True)
                card_view.addSubview_(badge_lbl)

                root_view.addSubview_(card_view)
                y_pos -= 48

        # Footer tip
        footer_tip = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(20, 10), NSSize(475, 16)))
        footer_tip.setStringValue_("💡 Click any conversation in Antigravity's sidebar to switch dialogue focus.")
        footer_tip.setFont_(NSFont.systemFontOfSize_(10))
        footer_tip.setTextColor_(NSColor.tertiaryLabelColor())
        footer_tip.setBezeled_(False)
        footer_tip.setDrawsBackground_(False)
        footer_tip.setEditable_(False)
        footer_tip.setSelectable_(False)
        footer_tip.setWantsLayer_(True)
        root_view.addSubview_(footer_tip)

        self._panel.setContentView_(root_view)
