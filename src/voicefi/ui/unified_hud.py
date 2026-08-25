"""
Native macOS Pure Apple-Style Unified Dynamic Island HUD.
Provides a clean, borderless, frosted-glass fixed-size (480x58) capsule HUD anchored
at the top-right of the screen with a 20px margin or user-dragged position, smoothly updating
its internal content across agent lifecycle states:
- IDLE: "🎙️ VoiceFi • Ready (⇧⌘N)"
- THINKING: Reasoning indicator ("🧠 Antigravity • Thinking...")
- WORKING: Tool action card ("⚡ Antigravity • Running pytest...")
- SPEAKING: Live speech subtitles ("🧔 Antigravity • Christopher 🔊 [Speaking]")
- LISTENING: Microphone VAD indicator with live typing stream ("🎙️ Listening (Jake) • Live Stream")
- EDITING: Interactive review & edit capsule before prompt submission ("✏️ Review & Edit Prompt")
- PAUSED / TRANSCRIBING / DONE: Acoustic state indicators
"""

import math
import threading
import time
import warnings
from typing import Optional, Callable, Dict, Any

try:
    import objc
    if hasattr(objc, "ObjCPointerWarning"):
        warnings.filterwarnings("ignore", category=objc.ObjCPointerWarning)
except Exception:
    pass

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
    NSTextAlignmentRight,
    NSButton,
    NSBezelStyleRounded,
    NSColor,
    NSFloatingWindowLevel,
    NSStatusWindowLevel,
    NSFont,
    NSScreen,
    NSView,
    NSImageView,
    NSImage,
    NSImageScaleProportionallyUpOrDown,
    NSWorkspace,
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
    "cursor": "⚡",
    "openai": "✨",
    "chatgpt": "✳️",
    "codex": "✳️",
    "terminal": "💻",
    "windsurf": "🏄",
    "obsidian": "💎",
    "vscode": "💻",
    "christopher": "🧔",
    "aria": "⚡",
    "sonia": "🔬",
    "guy": "☕",
    "william": "🦘",
    "jenny": "👩‍💻",
    "samantha": "🍎",
    "alex": "🍏",
    "daniel": "🎙️",
    "viv": "✨",
    "emily": "🍀",
    "steffan": "🎩",
    "andrew": "🤠",
}


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
    Thread-safe, main-runloop safe, fixed-size container that updates its internal
    content smoothly across all agent and voice lifecycle states.
    """

    STANDARD_WIDTH: float = 480.0
    STANDARD_HEIGHT: float = 58.0

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
        self._is_speaking = False
        hud_cfg = getattr(self.config, "hud", None)
        self.persistent = getattr(hud_cfg, "persistent", True)
        self.auto_send = getattr(hud_cfg, "auto_send", True)

        self._panel: Optional[NSPanel] = None
        self._root_view: Optional[NSView] = None
        self._effect_view: Optional[NSVisualEffectView] = None
        self._label: Optional[NSTextField] = None
        self._avatar_box: Optional[NSView] = None
        self._avatar_lbl: Optional[NSTextField] = None
        self._avatar_img: Optional[Any] = None
        self._icon_cache: Dict[str, Any] = {}
        self._title_lbl: Optional[NSTextField] = None
        self._tag_lbl: Optional[NSTextField] = None
        self._body_lbl: Optional[NSTextField] = None
        self._edit_container: Optional[NSView] = None
        self._edit_header: Optional[NSTextField] = None
        self._edit_hint: Optional[NSTextField] = None
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

    @property
    def is_speaking(self) -> bool:
        return bool(getattr(self, "_is_speaking", False) and self._current_state == "speaking")

    def _resolve_avatar(self, agent_name: Optional[str], persona_name: Optional[str] = None) -> str:
        """Resolve avatar emoji based on persona or agent name."""
        if persona_name:
            p_key = persona_name.lower().strip()
            if p_key in AVATAR_ICONS:
                return AVATAR_ICONS[p_key]
        if agent_name:
            a_key = agent_name.lower().strip()
            if a_key in AVATAR_ICONS:
                return AVATAR_ICONS[a_key]
        return "🤖"

    def _resolve_app_icon(self, name: Optional[str]) -> Optional[Any]:
        """Resolve native macOS application icon or asset bundle image for a given program or agent."""
        if not name:
            return None
        key = name.lower().strip()

        if not hasattr(self, "_icon_cache"):
            self._icon_cache = {}

        if key in self._icon_cache:
            return self._icon_cache[key]

        icon = None
        try:
            import os

            # 1. Check VoiceFi bundle assets
            if key in ("voicefi", "voicegency", "vf"):
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                candidates = [
                    os.path.join(base_dir, "assets", "VoiceFi.icns"),
                    os.path.join(base_dir, "assets", "VoiceFi.iconset", "icon_32x32@2x.png"),
                    os.path.join(base_dir, "assets", "Voicegency.iconset", "icon_32x32@2x.png"),
                ]
                for p in candidates:
                    if os.path.exists(p):
                        img = NSImage.alloc().initWithContentsOfFile_(p)
                        if img and hasattr(img, "isValid") and img.isValid():
                            icon = img
                            break

            # 2. Check native macOS app bundles
            if not icon:
                ws = NSWorkspace.sharedWorkspace()
                app_map = {
                    "cursor": "Cursor",
                    "claude": "Claude",
                    "claude code": "Claude",
                    "obsidian": "Obsidian",
                    "vscode": "Visual Studio Code",
                    "code": "Visual Studio Code",
                    "visual studio code": "Visual Studio Code",
                    "windsurf": "Windsurf",
                    "terminal": "Terminal",
                    "iterm": "iTerm",
                    "ghostty": "Ghostty",
                    "chatgpt": "ChatGPT",
                    "openai": "ChatGPT",
                    "antigravity": "Antigravity",
                }
                target_app = app_map.get(key, name)
                app_path = ws.fullPathForApplication_(target_app)
                if app_path and os.path.exists(app_path):
                    img = ws.iconForFile_(app_path)
                    if img and hasattr(img, "isValid") and img.isValid():
                        icon = img
        except Exception:
            icon = None

        self._icon_cache[key] = icon
        return icon

    def reset_position(self):
        """Reset user-dragged position back to top-right of the screen with standard margin."""
        self._user_dragged_center_x = None
        self._user_dragged_top_y = None
        if self._panel:
            target_rect = self._get_target_frame(self.STANDARD_WIDTH, self.STANDARD_HEIGHT)
            self._panel.setFrameOrigin_(target_rect.origin)
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

        w, h = self.STANDARD_WIDTH, self.STANDARD_HEIGHT
        target_rect = self._get_target_frame(w, h)
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel

        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            target_rect,
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

        # Root view container (fixed 480x58)
        self._root_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(w, h)))
        self._root_view.setWantsLayer_(True)
        self._root_view.layer().setCornerRadius_(20.0)
        self._root_view.layer().setMasksToBounds_(True)
        self._root_view.layer().setBorderWidth_(1.2)
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
        self._effect_view.layer().setCornerRadius_(20.0)
        self._root_view.addSubview_(self._effect_view)

        # Avatar badge view (left)
        self._avatar_box = NSView.alloc().initWithFrame_(NSRect(NSPoint(14, 15), NSSize(28, 28)))
        self._avatar_box.setWantsLayer_(True)
        self._avatar_box.layer().setCornerRadius_(14.0)
        self._avatar_box.layer().setMasksToBounds_(True)
        self._avatar_box.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.20, 0.28, 0.85).CGColor()
        )

        try:
            self._avatar_img = NSImageView.alloc().initWithFrame_(NSRect(NSPoint(2, 2), NSSize(24, 24)))
            if hasattr(self._avatar_img, "setImageScaling_"):
                self._avatar_img.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            self._avatar_img.setHidden_(True)
            self._avatar_box.addSubview_(self._avatar_img)
        except Exception:
            self._avatar_img = None

        self._avatar_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(0, 1), NSSize(28, 26)))
        self._avatar_lbl.setStringValue_("🎙️")
        self._avatar_lbl.setFont_(NSFont.systemFontOfSize_(15))
        self._avatar_lbl.setAlignment_(NSTextAlignmentCenter)
        self._avatar_lbl.setBezeled_(False)
        self._avatar_lbl.setDrawsBackground_(False)
        self._avatar_lbl.setEditable_(False)
        self._avatar_lbl.setSelectable_(False)
        self._avatar_box.addSubview_(self._avatar_lbl)
        self._root_view.addSubview_(self._avatar_box)

        # Title Label (Bold Agent/User/VoiceFi name)
        self._title_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(50, 32), NSSize(140, 18)))
        self._title_lbl.setFont_(NSFont.boldSystemFontOfSize_(12.5))
        self._title_lbl.setTextColor_(NSColor.whiteColor())
        self._title_lbl.setStringValue_("VoiceFi")
        self._title_lbl.setBezeled_(False)
        self._title_lbl.setDrawsBackground_(False)
        self._title_lbl.setEditable_(False)
        self._title_lbl.setSelectable_(False)
        self._root_view.addSubview_(self._title_lbl)

        # Tag Label (Colored status accent / shortcut)
        self._tag_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(195, 32), NSSize(270, 18)))
        self._tag_lbl.setFont_(NSFont.systemFontOfSize_(11))
        self._tag_lbl.setStringValue_("• Ready (⇧⌘N)")
        self._tag_lbl.setBezeled_(False)
        self._tag_lbl.setDrawsBackground_(False)
        self._tag_lbl.setEditable_(False)
        self._tag_lbl.setSelectable_(False)
        self._root_view.addSubview_(self._tag_lbl)

        # Body Text Label (Subtitles, recognized speech, tool actions, hints)
        self._body_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(50, 8), NSSize(416, 22)))
        self._body_lbl.setFont_(NSFont.systemFontOfSize_(11.5))
        self._body_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.92, 0.96, 0.95))
        self._body_lbl.setStringValue_("Standing by • Dictate (⌃T) or speak to agent (⌃R)")
        self._body_lbl.setBezeled_(False)
        self._body_lbl.setDrawsBackground_(False)
        self._body_lbl.setEditable_(False)
        self._body_lbl.setSelectable_(False)
        self._root_view.addSubview_(self._body_lbl)

        # Single-line Compact Fallback Label (if specifically used)
        self._label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(14, 18), NSSize(452, 22)))
        self._label.setFont_(NSFont.systemFontOfSize_(12.5))
        self._label.setAlignment_(NSTextAlignmentCenter)
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._label.setHidden_(True)
        self._root_view.addSubview_(self._label)

        # Interactive Edit / Review Container (hidden by default, fixed 480x58)
        self._edit_container = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(w, h)))
        self._edit_container.setHidden_(True)

        self._edit_header = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(14, 33), NSSize(270, 18)))
        self._edit_header.setStringValue_("✏️ Review & Edit Prompt:")
        self._edit_header.setFont_(NSFont.boldSystemFontOfSize_(11.5))
        self._edit_header.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.7, 0.85, 1.0, 0.95))
        self._edit_header.setBezeled_(False)
        self._edit_header.setDrawsBackground_(False)
        self._edit_header.setEditable_(False)
        self._edit_header.setSelectable_(False)
        self._edit_container.addSubview_(self._edit_header)

        self._edit_hint = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(290, 33), NSSize(176, 18)))
        self._edit_hint.setStringValue_("[Enter] Send • [Esc] Cancel")
        self._edit_hint.setFont_(NSFont.systemFontOfSize_(10.5))
        self._edit_hint.setAlignment_(NSTextAlignmentRight)
        self._edit_hint.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.6, 0.75, 0.9, 0.8))
        self._edit_hint.setBezeled_(False)
        self._edit_hint.setDrawsBackground_(False)
        self._edit_hint.setEditable_(False)
        self._edit_hint.setSelectable_(False)
        self._edit_container.addSubview_(self._edit_hint)

        self._edit_text_field = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(14, 7), NSSize(376, 24)))
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

        self._send_button = NSButton.alloc().initWithFrame_(NSRect(NSPoint(398, 7), NSSize(68, 24)))
        self._send_button.setTitle_("Send ↵")
        self._send_button.setBezelStyle_(NSBezelStyleRounded)
        self._edit_container.addSubview_(self._send_button)

        self._cancel_button = NSButton.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(0, 0)))
        self._cancel_button.setHidden_(True)
        self._edit_container.addSubview_(self._cancel_button)

        self._root_view.addSubview_(self._edit_container)
        self._panel.setContentView_(self._root_view)

    def _get_target_frame(self, width: float = 480.0, height: float = 58.0) -> NSRect:
        """Calculate screen positioning anchored top-right with margin below Chrome tab bar, or user-dragged position."""
        screen = NSScreen.mainScreen()
        if self._user_dragged_center_x is not None and self._user_dragged_top_y is not None:
            x = self._user_dragged_center_x - (width / 2.0)
            y = self._user_dragged_top_y - height
        elif screen:
            visible = screen.visibleFrame()
            hud_cfg = getattr(self.config, "hud", None) if hasattr(self, "config") else None
            margin_x = float(getattr(hud_cfg, "margin_x", 20.0)) if hud_cfg else 20.0
            margin_y = float(getattr(hud_cfg, "margin_y", 52.0)) if hud_cfg else 52.0
            x = visible.origin.x + visible.size.width - width - margin_x
            y = visible.origin.y + visible.size.height - height - margin_y
        else:
            x, y = 1200, 800
        return NSRect(NSPoint(x, y), NSSize(width, height))

    def _position_top_right(self):
        """Ensure HUD is positioned at top-right of the screen with standard margin."""
        if not self._panel:
            return
        target_rect = self._get_target_frame(self.STANDARD_WIDTH, self.STANDARD_HEIGHT)
        self._panel.setFrameOrigin_(target_rect.origin)

    def _position_top_center(self):
        """Ensure HUD is positioned (compatibility wrapper for _position_top_right)."""
        self._position_top_right()

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
        avatar_image: Optional[Any] = None,
        width: Optional[float] = None,
        height: Optional[float] = None,
        linger: Optional[float] = None,
    ):
        """Update window geometry with rich structured view hierarchy on main thread."""
        w = width or self.STANDARD_WIDTH
        h = height or self.STANDARD_HEIGHT

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

            target_rect = self._get_target_frame(w, h)

            if not self._panel.isVisible():
                self._panel.setFrame_display_(target_rect, True)

            self._root_view.layer().setBorderColor_(border_color.CGColor())

            # Avatar Box (App Logo Image or Persona Emoji)
            if self._avatar_box:
                self._avatar_box.setHidden_(False)
                self._avatar_box.layer().setBackgroundColor_(avatar_bg.CGColor())
                if avatar_image and self._avatar_img:
                    try:
                        self._avatar_img.setImage_(avatar_image)
                        self._avatar_img.setHidden_(False)
                    except Exception:
                        pass
                    if self._avatar_lbl:
                        self._avatar_lbl.setHidden_(True)
                elif self._avatar_lbl:
                    self._avatar_lbl.setStringValue_(avatar_emoji)
                    self._avatar_lbl.setHidden_(False)
                    if self._avatar_img:
                        self._avatar_img.setHidden_(True)

            # Title & Tag (Top row)
            if self._title_lbl:
                self._title_lbl.setHidden_(False)
                self._title_lbl.setStringValue_(title)

            if self._tag_lbl:
                self._tag_lbl.setHidden_(False)
                self._tag_lbl.setStringValue_(tag_text)
                self._tag_lbl.setTextColor_(tag_color)

            # Body Text (Bottom row)
            if self._body_lbl:
                self._body_lbl.setHidden_(False)
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

    def _apply_simple_state(
        self,
        state: str,
        text: str,
        linger: Optional[float] = None,
    ):
        """Single-line / compatibility presentation maintaining fixed geometry."""
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
            self._label.setStringValue_(text)

            target_rect = self._get_target_frame(self.STANDARD_WIDTH, self.STANDARD_HEIGHT)
            if not self._panel.isVisible():
                self._panel.setFrame_display_(target_rect, True)

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
            self._panel.setLevel_(NSStatusWindowLevel + 2)
            self._panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
        else:
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
    # Lifecycle State Handlers (Fixed 480x58)
    # -------------------------------------------------------------------------

    def set_idle(self, linger: Optional[float] = None):
        """Set to Idle State (Fixed 480x58 persistent capsule)."""
        app_icon = self._resolve_app_icon("VoiceFi")
        self._apply_rich_state(
            state="idle",
            avatar_emoji="🎙️",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.20, 0.28, 0.85),
            avatar_image=app_icon,
            title="VoiceFi",
            tag_text="• Ready (⇧⌘N)",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.9, 0.7, 0.95),
            body_text="Standing by • Dictate (⌃T) or speak to agent (⌃R)",
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.20),
            linger=linger,
        )

    def set_thinking(self, agent_name: str = "Antigravity", detail: str = "Thinking..."):
        """Set to Thinking State with rich reasoning card (fixed 480x58)."""
        display_detail = detail or "Analyzing codebase & dependencies..."
        app_icon = self._resolve_app_icon(agent_name)
        avatar = self._resolve_avatar(agent_name)
        self._apply_rich_state(
            state="thinking",
            avatar_emoji=avatar or "🧠",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.35, 0.20, 0.55, 0.85),
            avatar_image=app_icon,
            title=agent_name.capitalize(),
            tag_text="• Thinking...",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.8, 0.65, 1.0, 0.95),
            body_text=display_detail,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.65, 0.45, 0.98, 0.75),
        )

    def set_working(self, agent_name: str = "Antigravity", tool_action: str = "Running tool..."):
        """Set to Working / Tool Execution State with rich tool card (fixed 480x58)."""
        display_tool = tool_action or "Executing background tasks..."
        app_icon = self._resolve_app_icon(agent_name)
        avatar = self._resolve_avatar(agent_name)
        self._apply_rich_state(
            state="working",
            avatar_emoji=avatar or "⚡",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.35, 0.65, 0.85),
            avatar_image=app_icon,
            title=agent_name.capitalize(),
            tag_text="• Running Tool",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.8, 1.0, 0.95),
            body_text=display_tool,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.6, 1.0, 0.8),
        )

    def set_speaking(
        self,
        text: str,
        agent_name: str = "Antigravity",
        persona_name: Optional[str] = None,
        linger: Optional[float] = 2.5,
    ):
        """Set to Speaking State with rich live speech subtitles (fixed 480x58)."""
        self._is_speaking = True
        clean = text.strip() or "Speaking..."
        speaker = persona_name if persona_name else agent_name.capitalize()
        avatar = self._resolve_avatar(agent_name, persona_name)
        app_icon = None if (persona_name and persona_name.lower() in AVATAR_ICONS) else self._resolve_app_icon(agent_name)
        self._apply_rich_state(
            state="speaking",
            avatar_emoji=avatar,
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.4, 0.5, 0.85),
            avatar_image=app_icon,
            title=agent_name.capitalize(),
            tag_text=f"• {speaker} 🔊 [Speaking]",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.9, 1.0, 0.95),
            body_text=f'"{clean}"',
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.85, 0.95, 0.8),
            linger=linger,
        )

    def set_listening(
        self,
        prompt_preview: str = "",
        user_name: str = "Jake",
        live_stream: bool = False,
    ):
        """Set to Listening State with microphone badge and live typing preview (fixed 480x58)."""
        if prompt_preview:
            clean = prompt_preview.strip()
            cursor = " ▌" if live_stream else ""
            body = f'"{clean}"{cursor}'
            tag = "🔴 Live Recording Stream" if live_stream else "🔴 Recording (Live Mic)"
        else:
            body = "Speak your prompt or question..."
            tag = "🔴 Recording (Live Mic)"

        if self._label:
            self._label.setStringValue_("🔴 Listening... (Speak)")

        self._apply_rich_state(
            state="listening",
            avatar_emoji="🎙️",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.65, 0.12, 0.16, 0.85),
            title=f"Listening ({user_name})",
            tag_text=tag,
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.38, 0.42, 0.98),
            body_text=body,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.22, 0.26, 0.85),
        )

    def set_new_conversation(
        self,
        prompt_preview: str = "",
        user_name: str = "Jake",
        live_stream: bool = False,
    ):
        """Set to New Conversation State with Connected Tools indicator (fixed 480x58)."""
        if prompt_preview:
            clean = prompt_preview.strip()
            cursor = " ▌" if live_stream else ""
            body = f'"{clean}"{cursor}'
            tag = "⚡ Connected Tools • Live Stream" if live_stream else "⚡ Connected Tools"
        else:
            body = "Speak initial prompt to start conversation with connected tools..."
            tag = "⚡ Connected Tools"

        self._apply_rich_state(
            state="new_conversation",
            avatar_emoji="✨",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.5, 0.45, 0.85),
            title=f"New Session ({user_name})",
            tag_text=tag,
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.95, 0.8, 0.98),
            body_text=body,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.85, 0.7, 0.85),
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
        """Update subtitle or transcription text dynamically without frame change."""
        def _update():
            if self._body_lbl and self._panel and self._panel.isVisible():
                self._body_lbl.setStringValue_(text)
            if self._label and self._panel and self._panel.isVisible():
                self._label.setStringValue_(text)

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    def update_text(self, text: str):
        """Alias for update_live_text."""
        self.update_live_text(text)

    # -------------------------------------------------------------------------
    # Interactive Edit / Review State (Fixed 480x58)
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
        Maintains fixed 480x58 container dimensions.
        """
        with self._lock:
            self._current_state = "editing"
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

        def _setup_edit():
            if not self._panel or not self._root_view or not self._edit_container:
                return

            target_rect = self._get_target_frame(self.STANDARD_WIDTH, self.STANDARD_HEIGHT)
            if not self._panel.isVisible():
                self._panel.setFrame_display_(target_rect, True)

            # Hide standard labels and show edit container
            if self._label:
                self._label.setHidden_(True)
            if self._avatar_box:
                self._avatar_box.setHidden_(True)
            if self._title_lbl:
                self._title_lbl.setHidden_(True)
            if self._tag_lbl:
                self._tag_lbl.setHidden_(True)
            if self._body_lbl:
                self._body_lbl.setHidden_(True)

            self._edit_container.setHidden_(False)
            self._root_view.layer().setBorderColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.65, 1.0, 0.9).CGColor()
            )

            header_text = f"✏️ Review & Edit ({target_name}):"
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

            self._edit_text_field.setTarget_(self._action_delegate)
            self._edit_text_field.setAction_("submitAction:")
            self._edit_text_field.setDelegate_(self._action_delegate)

            self._send_button.setTarget_(self._action_delegate)
            self._send_button.setAction_("submitAction:")

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
        self._is_speaking = False
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
        self._is_speaking = False
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
        if self._label:
            self._label.setStringValue_(message)
        self._apply_rich_state(
            state="paused",
            avatar_emoji="⏸️",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.55, 0.35, 0.1, 0.85),
            title="VoiceFi",
            tag_text="• Paused",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.65, 0.2, 0.95),
            body_text=message,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.55, 0.15, 0.85),
        )

    def show_transcribing(self):
        """Compatibility bridge for DictationHUD.show_transcribing."""
        if self._label:
            self._label.setStringValue_("⏳ Transcribing...")
        self._apply_rich_state(
            state="transcribing",
            avatar_emoji="⏳",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.45, 0.15, 0.85),
            title="VoiceFi",
            tag_text="• Transcribing...",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.85, 0.3, 0.95),
            body_text="Converting speech to text...",
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.8, 0.25, 0.85),
        )

    def show_done(self, preview_text: str = ""):
        """Compatibility bridge for DictationHUD.show_done."""
        disp = f"✅ {preview_text[:25]}..." if preview_text else "✅ Done"
        if self._label:
            self._label.setStringValue_(disp)
        self._apply_rich_state(
            state="done",
            avatar_emoji="✅",
            avatar_bg=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.5, 0.25, 0.85),
            title="VoiceFi",
            tag_text="• Done",
            tag_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.95, 0.5, 0.98),
            body_text=disp,
            border_color=NSColor.colorWithCalibratedRed_green_blue_alpha_(0.25, 0.85, 0.45, 0.85),
            linger=1.5,
        )
