"""
Native macOS Pure Apple-Style Unified Dynamic Island HUD.
Provides a clean, borderless, frosted-glass capsule HUD anchored directly beneath
the top-center screen / camera notch, smoothly morphing across agent lifecycle states:
- IDLE: Compact persistent pill ("🎙️ VoiceFi • Ready")
- THINKING: Reasoning indicator ("🧠 Antigravity • Thinking...")
- WORKING: Tool action pill ("⚡ Antigravity • Running pytest...")
- SPEAKING: Live speech subtitles ("🔊 Christopher: '...'")
- LISTENING: Microphone VAD indicator with live typing stream ("🎙️ Jake: '...' ▌")
- EDITING: Interactive review & edit capsule before prompt submission ("✏️ Review & Edit Prompt")
"""

import math
import threading
import time
from typing import Optional, Callable

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSPanel,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered,
    NSRect,
    NSPoint,
    NSSize,
    NSTextField,
    NSTextAlignmentCenter,
    NSButton,
    NSBezelStyleRounded,
    NSColor,
    NSFloatingWindowLevel,
    NSStatusWindowLevel,
    NSFont,
    NSScreen,
    NSView,
    NSVisualEffectView,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectBlendingModeBehindWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSAnimationContext,
)
import objc
from PyObjCTools import AppHelper

from voicefi.config import load_config, save_config


try:
    HUDWindowDelegate = objc.lookUpClass("HUDWindowDelegate")
except objc.nosuchclass_error:
    class HUDWindowDelegate(objc.lookUpClass("NSObject")):
        """Objective-C delegate for tracking user dragging and window position."""

        def initWithHUD_(self, hud):
            self = objc.super(HUDWindowDelegate, self).init()
            if self is not None:
                self.hud = hud
            return self

        def windowDidMove_(self, notification):
            if self.hud and self.hud._panel and not getattr(self.hud, "_is_animating", False):
                frame = self.hud._panel.frame()
                self.hud._user_dragged_center_x = frame.origin.x + (frame.size.width / 2.0)
                self.hud._user_dragged_top_y = frame.origin.y + frame.size.height


try:
    HUDActionDelegate = objc.lookUpClass("HUDActionDelegate")
except objc.nosuchclass_error:
    class HUDActionDelegate(objc.lookUpClass("NSObject")):
        """Objective-C delegate wrapper for HUD edit mode Return key & button actions."""

        def initWithSubmit_cancel_field_(self, on_submit, on_cancel, text_field):
            self = objc.super(HUDActionDelegate, self).init()
            if self is not None:
                self.on_submit = on_submit
                self.on_cancel = on_cancel
                self.text_field = text_field
            return self

        def submitAction_(self, sender):
            if self.on_submit and self.text_field:
                val = str(self.text_field.stringValue() or "").strip()
                self.on_submit(val)

        def cancelAction_(self, sender):
            if self.on_cancel:
                self.on_cancel()

        def control_textView_doCommandBySelector_(self, control, text_view, command_selector):
            # Handle Escape key inside NSTextField
            if str(command_selector) == "cancelOperation:":
                if self.on_cancel:
                    self.on_cancel()
                return True
            return False


class UnifiedDynamicIslandHUD:
    """
    Singleton Native Apple-Style Unified Dynamic Island HUD for macOS.
    Thread-safe, main-runloop safe, with persistent capsule, live typing, and review edit modes.
    """

    _instance: Optional["UnifiedDynamicIslandHUD"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "UnifiedDynamicIslandHUD":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.config = load_config()
        self._current_state = "idle"
        hud_cfg = getattr(self.config, "hud", None)
        self.persistent = getattr(hud_cfg, "persistent", True)
        self.auto_send = getattr(hud_cfg, "auto_send", True)

        self._panel: Optional[NSPanel] = None
        self._root_view: Optional[NSView] = None
        self._effect_view: Optional[NSVisualEffectView] = None
        self._label: Optional[NSTextField] = None
        self._avatar_box: Optional[NSView] = None
        self._avatar_lbl: Optional[NSTextField] = None
        self._title_lbl: Optional[NSTextField] = None
        self._tag_lbl: Optional[NSTextField] = None
        self._body_lbl: Optional[NSTextField] = None
        self._edit_container: Optional[NSView] = None
        self._edit_header: Optional[NSTextField] = None
        self._edit_text_field: Optional[NSTextField] = None
        self._send_button: Optional[NSButton] = None
        self._cancel_button: Optional[NSButton] = None
        self._action_delegate: Optional[Any] = None

        self._hide_timer: Optional[threading.Timer] = None
        self._is_visible = False
        self._is_animating = False
        self._user_dragged_center_x: Optional[float] = None
        self._user_dragged_top_y: Optional[float] = None
        self._window_delegate: Optional[Any] = None

        self._init_native_window()

    def reset_position(self):
        """Reset user-dragged position back to top-center camera notch."""
        self._user_dragged_center_x = None
        self._user_dragged_top_y = None
        if self._current_state == "idle":
            self.set_idle()

    def _init_native_window(self):
        """Build the borderless NSPanel with native Apple HUD blur and interactive views."""
        try:
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
        except Exception:
            pass

        w, h = 155, 34
        rect = NSRect(NSPoint(500, 800), NSSize(w, h))
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel

        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setLevel_(NSStatusWindowLevel + 2)
        self._panel.setFloatingPanel_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCanHide_(False)
        self._panel.setWorksWhenModal_(True)
        self._panel.setBecomesKeyOnlyIfNeeded_(True)
        self._panel.setReleasedWhenClosed_(False)
        self._panel.setMovableByWindowBackground_(True)
        self._panel.setMovable_(True)

        self.fullscreen_overlay = True
        self._update_window_level_and_collection()

        # Window Drag Tracking Delegate
        self._window_delegate = HUDWindowDelegate.alloc().initWithHUD_(self)
        self._panel.setDelegate_(self._window_delegate)

        # Root view container
        self._root_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(w, h)))
        self._root_view.setWantsLayer_(True)
        self._root_view.layer().setCornerRadius_(h / 2.0)
        self._root_view.layer().setMasksToBounds_(True)
        self._root_view.layer().setBorderWidth_(1.0)
        self._root_view.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.20).CGColor()
        )

        # Apple standard HUD frosted blur
        self._effect_view = NSVisualEffectView.alloc().initWithFrame_(
            NSRect(NSPoint(0, 0), NSSize(w, h))
        )
        self._effect_view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        self._effect_view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        self._effect_view.setState_(1)
        self._effect_view.setWantsLayer_(True)
        self._effect_view.layer().setCornerRadius_(h / 2.0)
        self._root_view.addSubview_(self._effect_view)

        # Single-line Compact Label (for Idle / Transcribing / Done pills)
        self._label = NSTextField.alloc().initWithFrame_(
            NSRect(NSPoint(8, 7), NSSize(w - 16, 20))
        )
        self._label.setStringValue_("🎙️ VoiceFi • Ready")
        self._label.setFont_(NSFont.systemFontOfSize_(12.5))
        self._label.setAlignment_(NSTextAlignmentCenter)
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._root_view.addSubview_(self._label)

        # Avatar badge view
        self._avatar_box = NSView.alloc().initWithFrame_(NSRect(NSPoint(12, 10), NSSize(28, 28)))
        self._avatar_box.setWantsLayer_(True)
        self._avatar_box.layer().setCornerRadius_(14.0)
        self._avatar_box.setHidden_(True)

        self._avatar_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(0, 1), NSSize(28, 26)))
        self._avatar_lbl.setFont_(NSFont.systemFontOfSize_(15))
        self._avatar_lbl.setAlignment_(NSTextAlignmentCenter)
        self._avatar_lbl.setBezeled_(False)
        self._avatar_lbl.setDrawsBackground_(False)
        self._avatar_lbl.setEditable_(False)
        self._avatar_lbl.setSelectable_(False)
        self._avatar_box.addSubview_(self._avatar_lbl)
        self._root_view.addSubview_(self._avatar_box)

        # Title Label (Bold Agent/User name)
        self._title_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(48, 24), NSSize(140, 18)))
        self._title_lbl.setFont_(NSFont.boldSystemFontOfSize_(12.5))
        self._title_lbl.setTextColor_(NSColor.whiteColor())
        self._title_lbl.setBezeled_(False)
        self._title_lbl.setDrawsBackground_(False)
        self._title_lbl.setEditable_(False)
        self._title_lbl.setSelectable_(False)
        self._title_lbl.setHidden_(True)
        self._root_view.addSubview_(self._title_lbl)

        # Tag Label (Colored status accent)
        self._tag_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(180, 24), NSSize(240, 18)))
        self._tag_lbl.setFont_(NSFont.systemFontOfSize_(11))
        self._tag_lbl.setBezeled_(False)
        self._tag_lbl.setDrawsBackground_(False)
        self._tag_lbl.setEditable_(False)
        self._tag_lbl.setSelectable_(False)
        self._tag_lbl.setHidden_(True)
        self._root_view.addSubview_(self._tag_lbl)

        # Body Text Label (Subtitles, recognized speech, tool actions)
        self._body_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(48, 6), NSSize(380, 18)))
        self._body_lbl.setFont_(NSFont.systemFontOfSize_(11.5))
        self._body_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.92, 0.96, 0.95))
        self._body_lbl.setBezeled_(False)
        self._body_lbl.setDrawsBackground_(False)
        self._body_lbl.setEditable_(False)
        self._body_lbl.setSelectable_(False)
        self._body_lbl.setHidden_(True)
        self._root_view.addSubview_(self._body_lbl)

        # Interactive Edit / Review Container (hidden by default)
        self._edit_container = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(480, 94)))
        self._edit_container.setHidden_(True)

        # Edit Header
        self._edit_header = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(14, 68), NSSize(450, 18)))
        self._edit_header.setStringValue_("✏️ Review & Edit Prompt (Enter to Send • Esc to Cancel):")
        self._edit_header.setFont_(NSFont.boldSystemFontOfSize_(11))
        self._edit_header.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.7, 0.85, 1.0, 0.95))
        self._edit_header.setBezeled_(False)
        self._edit_header.setDrawsBackground_(False)
        self._edit_header.setEditable_(False)
        self._edit_header.setSelectable_(False)
        self._edit_container.addSubview_(self._edit_header)

        # Edit Text Input Field
        self._edit_text_field = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(14, 34), NSSize(452, 28)))
        self._edit_text_field.setFont_(NSFont.systemFontOfSize_(12.5))
        self._edit_text_field.setTextColor_(NSColor.whiteColor())
        self._edit_text_field.setBezeled_(True)
        self._edit_text_field.setDrawsBackground_(True)
        self._edit_text_field.setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.14, 0.22, 0.85)
        )
        self._edit_text_field.setEditable_(True)
        self._edit_text_field.setSelectable_(True)
        self._edit_container.addSubview_(self._edit_text_field)

        # Action Buttons
        self._send_button = NSButton.alloc().initWithFrame_(NSRect(NSPoint(386, 6), NSSize(80, 24)))
        self._send_button.setTitle_("Send ↵")
        self._send_button.setBezelStyle_(NSBezelStyleRounded)
        self._edit_container.addSubview_(self._send_button)

        self._cancel_button = NSButton.alloc().initWithFrame_(NSRect(NSPoint(302, 6), NSSize(78, 24)))
        self._cancel_button.setTitle_("Cancel ✕")
        self._cancel_button.setBezelStyle_(NSBezelStyleRounded)
        self._edit_container.addSubview_(self._cancel_button)

        self._root_view.addSubview_(self._edit_container)
        self._panel.setContentView_(self._root_view)

    def _get_target_frame(self, width: float, height: float) -> NSRect:
        """Calculate screen positioning anchored top-center below notch, or user-dragged position."""
        screen = NSScreen.mainScreen()
        if self._user_dragged_center_x is not None and self._user_dragged_top_y is not None:
            x = self._user_dragged_center_x - (width / 2.0)
            y = self._user_dragged_top_y - height
        elif screen:
            visible = screen.visibleFrame()
            x = visible.origin.x + (visible.size.width - width) / 2.0
            y = visible.origin.y + visible.size.height - height - 8.0
        else:
            x, y = 500, 800
        return NSRect(NSPoint(x, y), NSSize(width, height))

    def _apply_state(
        self,
        state: str,
        text: str,
        width: float,
        height: float,
        font_size: float = 12.5,
        linger: Optional[float] = None,
    ):
        """Update window geometry for single-line/idle presentation on main thread."""
        with self._lock:
            self._current_state = state
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

        def _update():
            if not self._panel or not self._root_view or not self._effect_view or not self._label:
                return

            if self._edit_container:
                self._edit_container.setHidden_(True)
            if self._avatar_box:
                self._avatar_box.setHidden_(True)
            if self._title_lbl:
                self._title_lbl.setHidden_(True)
            if self._tag_lbl:
                self._tag_lbl.setHidden_(True)
            if self._body_lbl:
                self._body_lbl.setHidden_(True)

            self._label.setHidden_(False)

            target_rect = self._get_target_frame(width, height)
            corner_radius = height / 2.0 if height <= 50 else 20.0

            # Animate frame resizing with smooth Apple spring curve
            self._is_animating = True
            try:
                NSAnimationContext.beginGrouping()
                NSAnimationContext.currentContext().setDuration_(0.20)
                self._panel.animator().setFrame_display_(target_rect, True)
                NSAnimationContext.endGrouping()
            except Exception:
                self._panel.setFrame_display_(target_rect, True)
            finally:
                self._is_animating = False

            self._root_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            self._root_view.layer().setCornerRadius_(corner_radius)
            self._root_view.layer().setBorderWidth_(1.0)
            self._root_view.layer().setBorderColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.20).CGColor()
            )

            self._effect_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            self._effect_view.layer().setCornerRadius_(corner_radius)

            label_h = font_size + 8.0
            label_y = max(2.0, (height - label_h) / 2.0)
            self._label.setFrame_(NSRect(NSPoint(8, label_y), NSSize(width - 16, label_h)))
            self._label.setFont_(NSFont.systemFontOfSize_(font_size))
            self._label.setAlignment_(NSTextAlignmentCenter)
            self._label.setStringValue_(text)

            self._panel.orderFrontRegardless()
            self._is_visible = True

            if linger and linger > 0:
                with self._lock:
                    if self.persistent:
                        self._hide_timer = threading.Timer(linger, self.set_idle)
                    else:
                        self._hide_timer = threading.Timer(linger, self.hide)
                    self._hide_timer.daemon = True
                    self._hide_timer.start()

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    def _apply_rich_state(
        self,
        state: str,
        avatar_emoji: str,
        avatar_bg: NSColor,
        title: str,
        tag_text: str,
        tag_color: NSColor,
        body_text: str,
        border_color: NSColor,
        width: float,
        height: float,
        linger: Optional[float] = None,
    ):
        """Update window geometry with rich structured multi-line view hierarchy on main thread."""
        with self._lock:
            self._current_state = state
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

        def _update():
            if not self._panel or not self._root_view or not self._effect_view:
                return

            if self._edit_container:
                self._edit_container.setHidden_(True)
            if self._label:
                self._label.setHidden_(True)

            target_rect = self._get_target_frame(width, height)
            corner_radius = 20.0

            self._is_animating = True
            try:
                NSAnimationContext.beginGrouping()
                NSAnimationContext.currentContext().setDuration_(0.20)
                self._panel.animator().setFrame_display_(target_rect, True)
                NSAnimationContext.endGrouping()
            except Exception:
                self._panel.setFrame_display_(target_rect, True)
            finally:
                self._is_animating = False

            self._root_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            self._root_view.layer().setCornerRadius_(corner_radius)
            self._root_view.layer().setBorderWidth_(1.5)
            self._root_view.layer().setBorderColor_(border_color.CGColor())

            self._effect_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            self._effect_view.layer().setCornerRadius_(corner_radius)

            # Avatar Box
            if self._avatar_box and self._avatar_lbl:
                avatar_size = 28.0
                avatar_y = max(8.0, height - avatar_size - 10.0)
                self._avatar_box.setHidden_(False)
                self._avatar_box.setFrame_(NSRect(NSPoint(12, avatar_y), NSSize(avatar_size, avatar_size)))
                self._avatar_box.layer().setBackgroundColor_(avatar_bg.CGColor())
                self._avatar_lbl.setStringValue_(avatar_emoji)

            # Title & Tag (Top row)
            header_y = height - 26.0
            if self._title_lbl:
                self._title_lbl.setHidden_(False)
                self._title_lbl.setFrame_(NSRect(NSPoint(48, header_y), NSSize(140, 18)))
                self._title_lbl.setStringValue_(title)

            if self._tag_lbl:
                self._tag_lbl.setHidden_(False)
                self._tag_lbl.setFrame_(NSRect(NSPoint(180, header_y), NSSize(max(100, width - 190), 18)))
                self._tag_lbl.setStringValue_(tag_text)
                self._tag_lbl.setTextColor_(tag_color)

            # Body Text (Bottom row)
            if self._body_lbl:
                self._body_lbl.setHidden_(False)
                body_h = max(16.0, height - 32.0)
                self._body_lbl.setFrame_(NSRect(NSPoint(48, 6), NSSize(max(100, width - 58), body_h)))
                self._body_lbl.setStringValue_(body_text)

            self._panel.orderFrontRegardless()
            self._is_visible = True

            if linger and linger > 0:
                with self._lock:
                    if self.persistent:
                        self._hide_timer = threading.Timer(linger, self.set_idle)
                    else:
                        self._hide_timer = threading.Timer(linger, self.hide)
                    self._hide_timer.daemon = True
                    self._hide_timer.start()

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    # -------------------------------------------------------------------------
    # Configuration & Persistence
    # -------------------------------------------------------------------------

    def set_persistent(self, enabled: bool):
        """Toggle persistent mode for the HUD capsule."""
        self.persistent = enabled
        if enabled:
            self.set_idle()
        else:
            self.hide()

    def set_auto_send(self, enabled: bool):
        """Toggle auto-send prompt/feedback vs interactive review edit mode."""
        self.auto_send = enabled

    def _update_window_level_and_collection(self):
        """Update window level and collection behavior based on fullscreen_overlay setting."""
        if not self._panel:
            return
        if self.fullscreen_overlay:
            # Always on top of full-screen games, apps, and video playback
            self._panel.setLevel_(NSStatusWindowLevel + 2)
            self._panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
        else:
            # Allow full screen apps to overlap / hide behind
            self._panel.setLevel_(NSFloatingWindowLevel)
            self._panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
            )

    def set_fullscreen_overlay(self, enabled: bool):
        """Toggle whether HUD stays on top of full-screen apps or allows full-screen overlap."""
        self.fullscreen_overlay = enabled

        def _update():
            self._update_window_level_and_collection()
            if self._is_visible and self._panel:
                self._panel.orderFrontRegardless()

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    # -------------------------------------------------------------------------
    # Lifecycle State Handlers
    # -------------------------------------------------------------------------

    def set_idle(self, linger: Optional[float] = None):
        """Set to Idle State (Compact Persistent Pill)."""
        self._apply_state(
            state="idle",
            text="🎙️ VoiceFi • Ready (⌘⇧N)",
            width=188,
            height=34,
            font_size=12.5,
            linger=linger,
        )

    def set_thinking(self, agent_name: str = "Antigravity", detail: str = "Thinking..."):
        """Set to Thinking State with rich reasoning card."""
        display_detail = detail or "Analyzing codebase & dependencies..."
        width = max(380, min(500, len(display_detail) * 7.5 + 80))
        self._apply_rich_state(
            state="thinking",
            avatar_emoji="🧠",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.35, 0.2, 0.55, 0.8),
            title=agent_name.capitalize(),
            tag_text="• Thinking...",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.8, 0.65, 1.0, 0.95),
            body_text=display_detail,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.65, 0.45, 0.98, 0.75),
            width=width,
            height=48,
        )

    def set_working(self, agent_name: str = "Antigravity", tool_action: str = "Running tool..."):
        """Set to Working / Tool Execution State with rich tool card."""
        display_tool = tool_action or "Executing background tasks..."
        width = max(390, min(520, len(display_tool) * 7.5 + 80))
        self._apply_rich_state(
            state="working",
            avatar_emoji="⚡",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.35, 0.65, 0.8),
            title=agent_name.capitalize(),
            tag_text="• Running Tool",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.8, 1.0, 0.95),
            body_text=display_tool,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.6, 1.0, 0.8),
            width=width,
            height=48,
        )

    def set_speaking(
        self,
        text: str,
        agent_name: str = "Antigravity",
        persona_name: Optional[str] = None,
        linger: Optional[float] = 2.5,
    ):
        """Set to Speaking State with rich live speech subtitles."""
        clean = text.strip() or "Speaking..."
        speaker = persona_name if persona_name else agent_name.capitalize()
        width = max(420, min(540, len(clean) * 7.5 + 80))
        self._apply_rich_state(
            state="speaking",
            avatar_emoji="🧔",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.4, 0.5, 0.8),
            title=agent_name.capitalize(),
            tag_text=f"• {speaker} 🔊 [Speaking]",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.9, 1.0, 0.95),
            body_text=f'"{clean}"',
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.85, 0.95, 0.8),
            width=width,
            height=58,
            linger=linger,
        )

    def set_listening(
        self,
        prompt_preview: str = "",
        user_name: str = "Jake",
        live_stream: bool = False,
    ):
        """Set to Listening State with rich microphone badge and live typing preview."""
        if prompt_preview:
            clean = prompt_preview.strip()
            cursor = " ▌" if live_stream else ""
            body = f'"{clean}"{cursor}'
            tag = "🔴 Live Recording Stream" if live_stream else "🔴 Recording (Live Mic)"
            width = max(390, min(520, len(clean) * 7.5 + 80))
        else:
            body = "Speak your prompt or question..."
            tag = "🔴 Recording (Live Mic)"
            width = 360

        self._apply_rich_state(
            state="listening",
            avatar_emoji="🎙️",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.65, 0.12, 0.16, 0.85),
            title=f"Listening ({user_name})",
            tag_text=tag,
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.38, 0.42, 0.98),
            body_text=body,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.22, 0.26, 0.85),
            width=width,
            height=52,
        )

    def set_new_conversation(
        self,
        prompt_preview: str = "",
        user_name: str = "Jake",
        live_stream: bool = False,
    ):
        """Set to New Conversation State with Connected Tools indicator and live prompt preview."""
        if prompt_preview:
            clean = prompt_preview.strip()
            cursor = " ▌" if live_stream else ""
            body = f'"{clean}"{cursor}'
            tag = "⚡ Connected Tools • Live Stream" if live_stream else "⚡ Connected Tools"
            width = max(420, min(540, len(clean) * 7.5 + 80))
        else:
            body = "Speak initial prompt to start conversation with connected tools..."
            tag = "⚡ Connected Tools"
            width = 440

        self._apply_rich_state(
            state="new_conversation",
            avatar_emoji="✨",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.5, 0.45, 0.85),
            title=f"New Session ({user_name})",
            tag_text=tag,
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.95, 0.8, 0.98),
            body_text=body,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.85, 0.7, 0.85),
            width=width,
            height=54,
        )

    def start_new_conversation_dialog(
        self,
        on_submit: Callable[[str], None],
        on_cancel: Optional[Callable[[], None]] = None,
        initial_text: str = "",
    ):
        """Open the review/edit capsule configured for starting a new conversation with connected tools."""
        self.set_editing(
            initial_text=initial_text,
            on_submit=on_submit,
            on_cancel=on_cancel,
            target_name="New Conversation (Connected Tools)",
        )

    def update_live_transcription(self, text: str, user_name: str = "Jake", is_new_conversation: bool = False):
        """Update the listening state with live transcription tokens."""
        if is_new_conversation or self._current_state == "new_conversation":
            self.set_new_conversation(prompt_preview=text, user_name=user_name, live_stream=True)
        else:
            self.set_listening(prompt_preview=text, user_name=user_name, live_stream=True)

    def update_live_text(self, text: str):
        """Update subtitle or transcription text dynamically without full resize."""
        def _update():
            if self._label and self._panel and self._panel.isVisible():
                self._label.setStringValue_(text)

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    # -------------------------------------------------------------------------
    # Interactive Edit / Review State
    # -------------------------------------------------------------------------

    def set_editing(
        self,
        initial_text: str,
        on_submit: Callable[[str], None],
        on_cancel: Optional[Callable[[], None]] = None,
        target_name: str = "Antigravity",
    ):
        """
        Open the interactive review & edit capsule on the main thread.
        Allows the user to modify the transcribed text before sending, or cancel.
        """
        with self._lock:
            self._current_state = "editing"
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

        def _setup_edit():
            if not self._panel or not self._root_view or not self._edit_container:
                return

            width, height = 480, 94
            target_rect = self._get_target_frame(width, height)

            try:
                NSAnimationContext.beginGrouping()
                NSAnimationContext.currentContext().setDuration_(0.18)
                self._panel.animator().setFrame_display_(target_rect, True)
                NSAnimationContext.endGrouping()
            except Exception:
                self._panel.setFrame_display_(target_rect, True)

            self._root_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            self._root_view.layer().setCornerRadius_(20.0)
            self._effect_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            self._effect_view.layer().setCornerRadius_(20.0)

            # Hide standard label and show edit container
            if self._label:
                self._label.setHidden_(True)
            self._edit_container.setHidden_(False)
            self._edit_container.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))

            header_text = f"✏️ Review & Edit ({target_name}) — [Enter] Send • [Esc] Cancel:"
            self._edit_header.setStringValue_(header_text)
            self._edit_text_field.setStringValue_(initial_text)

            def _wrapped_submit(edited_text: str):
                self.show_done(preview_text=edited_text[:20])
                try:
                    on_submit(edited_text)
                except Exception as e:
                    print(f"[HUD] Error in edit submit callback: {e}")

            def _wrapped_cancel():
                if self.persistent:
                    self.set_idle()
                else:
                    self.hide()
                if on_cancel:
                    try:
                        on_cancel()
                    except Exception:
                        pass

            self._action_delegate = HUDActionDelegate.alloc().initWithSubmit_cancel_field_(
                _wrapped_submit,
                _wrapped_cancel,
                self._edit_text_field,
            )

            # Setup target action on text field and buttons
            self._edit_text_field.setTarget_(self._action_delegate)
            self._edit_text_field.setAction_("submitAction:")
            self._edit_text_field.setDelegate_(self._action_delegate)

            self._send_button.setTarget_(self._action_delegate)
            self._send_button.setAction_("submitAction:")

            self._cancel_button.setTarget_(self._action_delegate)
            self._cancel_button.setAction_("cancelAction:")

            # Make key window and focus text field
            self._panel.setBecomesKeyOnlyIfNeeded_(False)
            self._panel.makeKeyAndOrderFront_(None)
            self._panel.makeFirstResponder_(self._edit_text_field)
            self._is_visible = True

        if threading.current_thread() is threading.main_thread():
            _setup_edit()
        else:
            AppHelper.callAfter(_setup_edit)

    # -------------------------------------------------------------------------
    # Finish & Hide Handlers
    # -------------------------------------------------------------------------

    def finish_speech(self, linger_seconds: float = 2.0):
        """Conclude speech turn and return to persistent idle or auto-hide."""
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
            if self.persistent:
                self._hide_timer = threading.Timer(linger_seconds, self.set_idle)
            else:
                self._hide_timer = threading.Timer(linger_seconds, self.hide)
            self._hide_timer.daemon = True
            self._hide_timer.start()

    def hide(self):
        """Hide the HUD panel or return to persistent idle."""
        if self.persistent:
            self.set_idle()
            return

        def _do_hide():
            if self._panel and self._panel.isVisible():
                self._panel.orderOut_(None)
                self._is_visible = False

        if threading.current_thread() is threading.main_thread():
            _do_hide()
        else:
            AppHelper.callAfter(_do_hide)

    def force_hide(self):
        """Explicitly hide the HUD panel regardless of persistent setting."""
        def _do_force_hide():
            if self._panel and self._panel.isVisible():
                self._panel.orderOut_(None)
                self._is_visible = False

        if threading.current_thread() is threading.main_thread():
            _do_force_hide()
        else:
            AppHelper.callAfter(_do_force_hide)

    # -------------------------------------------------------------------------
    # Backward Compatibility Delegates (AgentSpeechHUD & DictationHUD)
    # -------------------------------------------------------------------------

    def show_speech(
        self,
        text: str,
        agent_name: str = "Antigravity",
        role: Optional[str] = None,
        persona_name: Optional[str] = None,
        is_speaking: bool = True,
        position: str = "top_center",
    ):
        """Compatibility bridge for AgentSpeechHUD.show_speech."""
        self.set_speaking(
            text=text,
            agent_name=agent_name,
            persona_name=persona_name,
            linger=None,
        )

    def show_listening(self, prompt_preview: str = ""):
        """Compatibility bridge for DictationHUD.show_listening."""
        self.set_listening(
            prompt_preview=prompt_preview,
            user_name=getattr(self.config, "user_name", "Jake"),
        )

    def show_paused(self, message: str = "⏸️ Agent Speaking (Paused)..."):
        """Compatibility bridge for DictationHUD.show_paused."""
        self._apply_state(
            state="paused",
            text=message,
            width=240,
            height=34,
            font_size=12.5,
        )

    def show_transcribing(self):
        """Compatibility bridge for DictationHUD.show_transcribing."""
        self._apply_state(
            state="transcribing",
            text="⏳ Transcribing...",
            width=175,
            height=34,
            font_size=12.5,
        )

    def show_done(self, preview_text: str = ""):
        """Compatibility bridge for DictationHUD.show_done."""
        disp = f"✅ {preview_text[:20]}..." if preview_text else "✅ Done"
        self._apply_state(
            state="done",
            text=disp,
            width=160,
            height=34,
            font_size=12.5,
            linger=1.2,
        )

