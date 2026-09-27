"""
Native macOS Quick Prompt Bar for VoiceFi.
Provides a floating, stadium-pill-shaped prompt window summoned via Control+Space
to instantly start a new conversation with a selected agent.

Visual Form:
- Pill container: 620px x 52px with 26px corner radius (dark frosted glass)
- Left [+] context button
- Dynamic text input ("Ask Antigravity", "Ask Claude", "Ask Flash")
- Agent / Model selector dropdown pill
- VoiceFi character logo button (toggles hands-free dictation)
- Royal blue action circle button (starts new conversation)
"""

import os
import sys
import time
import threading
import warnings
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

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
    NSTextFieldCell,
    NSTextAlignmentLeft,
    NSTextAlignmentCenter,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSStatusWindowLevel,
    NSFont,
    NSScreen,
    NSView,
    NSImageView,
    NSImage,
    NSImageLeft,
    NSImageScaleProportionallyUpOrDown,
    NSWorkspace,
    NSVisualEffectView,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectBlendingModeBehindWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorMoveToActiveSpace,
    NSMenu,
    NSMenuItem,
    NSApp,
    NSImageSymbolConfiguration,
    NSString,
    NSFontAttributeName,
)
from PyObjCTools import AppHelper

from voicefi.config import load_config, save_config


def is_headless() -> bool:
    """Return True if running in headless / testing mode where screen popups must be suppressed."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("VOICEFI_TESTING") == "1"
    )


# =========================================================================
# Objective-C Subclasses
# =========================================================================

try:
    QuickBarPanel = objc.lookUpClass("QuickBarPanel")
except objc.nosuchclass_error:

    class QuickBarPanel(objc.lookUpClass("NSPanel")):
        """Borderless floating panel that accepts key and main window focus."""

        def canBecomeKeyWindow(self):
            return True

        def canBecomeMainWindow(self):
            return True

        def needsPanelToBecomeKey(self):
            return True

        def performKeyEquivalent_(self, event):
            try:
                flags = event.modifierFlags()
                vk = event.keyCode()
                # 1. Cmd+D or Ctrl+D (Dictation, vk 2)
                is_cmd = bool(flags & 0x100000)
                is_ctrl = bool(flags & 0x40000)
                if vk == 2 and (is_cmd or is_ctrl):
                    QuickPromptBarWindow.get_instance().toggle_voice_input()
                    return True
                # 2. Ctrl+M or Cmd+M (Mic, vk 46)
                if vk == 46 and (is_ctrl or is_cmd):
                    QuickPromptBarWindow.get_instance().toggle_voice_input()
                    return True
                # 3. Ctrl+Space while focused (vk 49 + Control)
                if vk == 49 and is_ctrl and not is_cmd:
                    QuickPromptBarWindow.get_instance().toggle_voice_input()
                    return True
            except Exception:
                pass
            return objc.super(QuickBarPanel, self).performKeyEquivalent_(event)


try:
    QuickBarCenteringCell = objc.lookUpClass("QuickBarCenteringCell")
except objc.nosuchclass_error:

    class QuickBarCenteringCell(objc.lookUpClass("NSTextFieldCell")):
        """Vertically centers prompt input text and selection within NSTextField."""

        def drawingRectForBounds_(self, rect):
            r = objc.super(QuickBarCenteringCell, self).drawingRectForBounds_(rect)
            sz = self.cellSizeForBounds_(rect)
            dy = (rect.size.height - sz.height) / 2.0
            if dy > 0:
                r.origin.y += dy
                r.size.height -= dy
            return r

        def editWithFrame_inView_editor_delegate_event_(
            self, rect, controlView, textObj, delegate, event
        ):
            r = self.drawingRectForBounds_(rect)
            objc.super(QuickBarCenteringCell, self).editWithFrame_inView_editor_delegate_event_(
                r, controlView, textObj, delegate, event
            )

        def selectWithFrame_inView_editor_delegate_start_length_(
            self, rect, controlView, textObj, delegate, selStart, selLength
        ):
            r = self.drawingRectForBounds_(rect)
            objc.super(
                QuickBarCenteringCell, self
            ).selectWithFrame_inView_editor_delegate_start_length_(
                r, controlView, textObj, delegate, selStart, selLength
            )


try:
    QuickBarActionTarget = objc.lookUpClass("QuickBarActionTarget")
except objc.nosuchclass_error:

    class QuickBarActionTarget(objc.lookUpClass("NSObject")):
        """Objective-C target wrapper for button click callbacks."""

        def initWithCallback_(self, callback):
            self = objc.super(QuickBarActionTarget, self).init()
            if self is not None:
                self.callback = callback
            return self

        def buttonClicked_(self, sender):
            if self.callback:
                self.callback()


def _get_current_event():
    """Retrieve active NSEvent from NSApp if available."""
    try:
        from AppKit import NSApp

        return NSApp.currentEvent()
    except Exception:
        return None


try:
    QuickBarTextDelegate = objc.lookUpClass("QuickBarTextDelegate")
except objc.nosuchclass_error:

    class QuickBarTextDelegate(objc.lookUpClass("NSObject")):
        """NSTextField delegate intercepting Return (submit) and Escape (dismiss)."""

        def initWithBar_(self, bar):
            self = objc.super(QuickBarTextDelegate, self).init()
            if self is not None:
                self.bar = bar
            return self

        def control_textView_doCommandBySelector_(self, control, textView, selector):
            sel_name = str(selector)
            if "insertNewline:" in sel_name:
                if self.bar:
                    is_shift = False
                    is_alt = False
                    try:
                        from AppKit import (
                            NSEventModifierFlagShift,
                            NSEventModifierFlagOption,
                        )

                        ev = _get_current_event()
                        if ev:
                            flags = ev.modifierFlags()
                            is_shift = bool(flags & NSEventModifierFlagShift)
                            is_alt = bool(flags & NSEventModifierFlagOption)
                    except Exception:
                        pass
                    self.bar._on_submit_action(new_conversation=is_shift, silent_send=is_alt)
                return True
            elif "cancelOperation:" in sel_name:
                if self.bar:
                    self.bar.hide()
                return True
            return False


try:
    QuickBarWindowDelegate = objc.lookUpClass("QuickBarWindowDelegate")
except objc.nosuchclass_error:

    class QuickBarWindowDelegate(objc.lookUpClass("NSObject")):
        """Window delegate to auto-dismiss on click-away when not recording."""

        def initWithBar_(self, bar):
            self = objc.super(QuickBarWindowDelegate, self).init()
            if self is not None:
                self.bar = bar
            return self

        def windowDidResignKey_(self, notification):
            if (
                self.bar
                and not self.bar.is_voice_active
                and not getattr(self.bar, "_is_menu_open", False)
            ):
                if time.time() - getattr(self.bar, "_last_show_time", 0.0) > 0.35:
                    self.bar.hide()

        def windowWillClose_(self, notification):
            if self.bar:
                self.bar.hide()


# =========================================================================
# Agent Registry
# =========================================================================

SUPPORTED_AGENTS = [
    {
        "id": "antigravity",
        "icon": "🤖",
        "name": "Antigravity",
        "desc": "Google DeepMind Agentic IDE",
        "placeholder": "Ask Antigravity",
    },
    {
        "id": "claude",
        "icon": "🎭",
        "name": "Claude Code",
        "desc": "Anthropic CLI / Desktop",
        "placeholder": "Ask Claude",
    },
    {
        "id": "flash",
        "icon": "✨",
        "name": "Gemini Flash",
        "desc": "Fast Multimodal Reasoning",
        "placeholder": "Ask Gemini",
    },
    {
        "id": "pro",
        "icon": "⚡",
        "name": "Gemini Pro",
        "desc": "Deep Reasoning & Live",
        "placeholder": "Ask Gemini Pro",
    },
    {
        "id": "chatgpt",
        "icon": "✳️",
        "name": "ChatGPT",
        "desc": "OpenAI Desktop Companion",
        "placeholder": "Ask ChatGPT",
    },
]


# =========================================================================
# QuickPromptBarWindow Class
# =========================================================================


class QuickPromptBarWindow:
    """
    Floating stadium pill prompt window for VoiceFi.
    Triggered via Control+Space to start new agent conversations with voice or text.
    """

    _instance: Optional["QuickPromptBarWindow"] = None
    STANDARD_WIDTH = 620.0
    STANDARD_HEIGHT = 52.0
    CORNER_RADIUS = 26.0

    @classmethod
    def get_instance(
        cls,
        on_submit: Optional[Callable[[str, str], None]] = None,
        on_voice_toggle: Optional[Callable[[bool], None]] = None,
    ) -> "QuickPromptBarWindow":
        if cls._instance is None:
            cls._instance = cls(on_submit=on_submit, on_voice_toggle=on_voice_toggle)
        else:
            if on_submit is not None:
                cls._instance.on_submit = on_submit
            if on_voice_toggle is not None:
                cls._instance.on_voice_toggle = on_voice_toggle
        return cls._instance

    def __init__(
        self,
        on_submit: Optional[Callable[[str, str], None]] = None,
        on_voice_toggle: Optional[Callable[[bool], None]] = None,
    ):
        self.on_submit = on_submit
        self.on_voice_toggle = on_voice_toggle
        self.is_voice_active = False
        self._panel: Optional[QuickBarPanel] = None
        self._root_view: Optional[NSView] = None
        self._text_field: Optional[NSTextField] = None
        self._agent_btn: Optional[NSButton] = None
        self._plus_btn: Optional[NSButton] = None
        self._mic_btn: Optional[NSButton] = None
        self._vifi_btn: Optional[NSButton] = None
        self._action_btn: Optional[NSButton] = None
        self._icon_cache: Dict[str, Any] = {}
        self._targets: List[Any] = []
        self._text_delegate: Optional[QuickBarTextDelegate] = None
        self._window_delegate: Optional[QuickBarWindowDelegate] = None
        self._active_recorder = None
        self._ptt_stop_event: Optional[threading.Event] = None

        # Load persisted default agent
        try:
            cfg = load_config()
            self.current_agent_id = (
                getattr(cfg.global_hotkey, "quick_bar_agent", "antigravity") or "antigravity"
            )
        except Exception:
            self.current_agent_id = "antigravity"

        if not is_headless():
            self._build_panel()

    def _get_agent_info(self, agent_id: str) -> Dict[str, str]:
        for a in SUPPORTED_AGENTS:
            if a["id"] == agent_id:
                return a
        return SUPPORTED_AGENTS[0]

    def get_agent_icon(self, agent_id: str, size: int = 16) -> Optional[Any]:
        """Resolve native brand logo image for an agent at the specified point size."""
        if not hasattr(self, "_icon_cache"):
            self._icon_cache = {}
        cache_key = f"{agent_id}_{size}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        ws = NSWorkspace.sharedWorkspace()
        hud_file = Path(__file__).resolve()
        asset_dirs = [
            hud_file.parent.parent.parent.parent / "assets",
            hud_file.parent.parent / "assets",
            Path.home() / ".voicefi" / "assets",
        ]

        agent_map = {
            "antigravity": {
                "files": ["logo-antigravity.svg", "logo-antigravity.png"],
                "app": "Antigravity",
            },
            "claude": {
                "files": ["logo-claude.svg", "logo-claude.png"],
                "app": "Claude",
            },
            "flash": {
                "files": ["logo-gemini.svg", "logo-gemini.png"],
                "app": "Gemini",
            },
            "pro": {
                "files": ["logo-gemini.svg", "logo-gemini.png"],
                "app": "Gemini",
            },
            "chatgpt": {
                "files": ["logo-chatgpt.svg", "logo-chatgpt.png"],
                "app": "ChatGPT",
                "app_res": "/Applications/ChatGPT.app/Contents/Resources/icon-chatgpt.png",
            },
            "cursor": {
                "files": ["logo-cursor.svg", "logo-cursor.png"],
                "app": "Cursor",
            },
            "windsurf": {
                "files": ["logo-windsurf.svg", "logo-windsurf.png"],
                "app": "Windsurf",
            },
            "terminal": {
                "files": ["logo-terminal.svg", "logo-terminal.png"],
                "app": "Terminal",
            },
            "obsidian": {
                "files": ["logo-obsidian.svg", "logo-obsidian.png"],
                "app": "Obsidian",
            },
        }

        info = agent_map.get(agent_id.lower().strip(), {})
        img = None

        # 1. Custom app resource if specified
        if "app_res" in info and os.path.exists(info["app_res"]):
            cand = NSImage.alloc().initWithContentsOfFile_(info["app_res"])
            if cand and hasattr(cand, "isValid") and cand.isValid():
                img = cand

        # 2. Vector SVG or bundled image in asset dirs
        if not img:
            for ad in asset_dirs:
                for fname in info.get("files", []):
                    p = ad / fname
                    if p.is_file():
                        cand = NSImage.alloc().initWithContentsOfFile_(str(p))
                        if cand and hasattr(cand, "isValid") and cand.isValid():
                            img = cand
                            break
                if img:
                    break

        # 3. Native macOS application bundle icon
        if not img:
            app_name = info.get("app")
            if app_name:
                app_path = ws.fullPathForApplication_(app_name)
                if app_path and os.path.exists(app_path):
                    cand = ws.iconForFile_(app_path)
                    if cand and hasattr(cand, "isValid") and cand.isValid():
                        img = cand

        if img:
            img_copy = img.copy()
            img_copy.setSize_(NSSize(size, size))
            self._icon_cache[cache_key] = img_copy
            return img_copy

        return None

    def _layout_controls(self):
        """Perform pixel-perfect layout of controls with exact vertical centering and spacing."""
        if (
            not self._root_view
            or not self._agent_btn
            or not self._text_field
            or not self._mic_btn
            or not self._action_btn
        ):
            return

        w = self.STANDARD_WIDTH
        right_margin = 12.0
        gap = 8.0
        btn_size = 32.0
        btn_y = 10.0  # Exact center Y = 26.0 within 52.0 height container

        # 1. Action / Send button on far right
        action_x = w - right_margin - btn_size
        self._action_btn.setFrame_(NSRect(NSPoint(action_x, btn_y), NSSize(btn_size, btn_size)))

        # 2. Mic dictation button
        mic_x = action_x - gap - btn_size
        self._mic_btn.setFrame_(NSRect(NSPoint(mic_x, btn_y), NSSize(btn_size, btn_size)))

        # 3. Agent selector button
        agent_info = self._get_agent_info(self.current_agent_id)
        title = f"{agent_info['name']} ▾"
        font = NSFont.systemFontOfSize_(12.5)
        needed_w = 120.0
        try:
            ns_str = NSString.stringWithString_(title)
            sz = ns_str.sizeWithAttributes_({NSFontAttributeName: font})
            # icon (16) + spacing (6) + text + horizontal padding (22)
            needed_w = float(sz.width) + 16.0 + 6.0 + 22.0
        except Exception:
            pass

        agent_w = round(max(110.0, min(148.0, needed_w)))
        agent_h = 28.0
        agent_y = 12.0  # Exact center Y = 26.0
        agent_x = mic_x - gap - agent_w
        self._agent_btn.setFrame_(NSRect(NSPoint(agent_x, agent_y), NSSize(agent_w, agent_h)))

        # 4. Text input field
        tf_x = 52.0  # 8px gap after [+] button (ends at 44)
        tf_w = max(100.0, (agent_x - gap) - tf_x)
        tf_h = 30.0
        tf_y = 11.0  # Exact center Y = 26.0
        self._text_field.setFrame_(NSRect(NSPoint(tf_x, tf_y), NSSize(tf_w, tf_h)))

    def _build_panel(self):
        """Construct the native macOS AppKit Quick Prompt Bar window and controls."""
        w, h = self.STANDARD_WIDTH, self.STANDARD_HEIGHT
        screen = NSScreen.mainScreen()
        if screen:
            vf = screen.visibleFrame()
            x = vf.origin.x + (vf.size.width - w) / 2.0
            y = vf.origin.y + (vf.size.height * 0.65) - (h / 2.0)
        else:
            x, y = 300.0, 500.0

        frame = NSRect(NSPoint(x, y), NSSize(w, h))
        style_mask = NSWindowStyleMaskBorderless

        self._panel = QuickBarPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style_mask, NSBackingStoreBuffered, False
        )
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setLevel_(NSStatusWindowLevel + 2)
        self._panel.setFloatingPanel_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCanHide_(False)
        self._panel.setWorksWhenModal_(True)
        self._panel.setBecomesKeyOnlyIfNeeded_(False)
        self._panel.setReleasedWhenClosed_(False)
        self._panel.setMovableByWindowBackground_(True)
        self._panel.setMovable_(True)
        self._panel.setHasShadow_(True)
        self._panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        self._window_delegate = QuickBarWindowDelegate.alloc().initWithBar_(self)
        self._panel.setDelegate_(self._window_delegate)

        # 1. Root container (Stadium Pill Shape)
        self._root_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(w, h)))
        self._root_view.setWantsLayer_(True)
        self._root_view.layer().setCornerRadius_(self.CORNER_RADIUS)
        self._root_view.layer().setMasksToBounds_(True)
        self._root_view.layer().setBorderWidth_(1.0)
        self._root_view.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.16).CGColor()
        )
        self._root_view.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.11, 0.11, 0.13, 0.96).CGColor()
        )

        # 2. Frosted Blur Layer
        self._effect_view = NSVisualEffectView.alloc().initWithFrame_(
            NSRect(NSPoint(0, 0), NSSize(w, h))
        )
        self._effect_view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        self._effect_view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        self._effect_view.setState_(1)
        self._effect_view.setWantsLayer_(True)
        self._effect_view.layer().setCornerRadius_(self.CORNER_RADIUS)
        self._root_view.addSubview_(self._effect_view)

        # 3. Left [+] Button
        self._plus_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(12, 10), NSSize(32, 32)))
        self._plus_btn.setWantsLayer_(True)
        self._plus_btn.layer().setCornerRadius_(16.0)
        self._plus_btn.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.06).CGColor()
        )
        self._plus_btn.layer().setBorderWidth_(0.5)
        self._plus_btn.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.12).CGColor()
        )
        self._plus_btn.setBordered_(False)
        self._plus_btn.setToolTip_("Options & Context")
        plus_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("plus", None)
        if plus_img:
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(13.0, 6)
            plus_img = plus_img.imageWithSymbolConfiguration_(cfg)
            self._plus_btn.setImage_(plus_img)
        else:
            self._plus_btn.setTitle_("+")

        plus_target = QuickBarActionTarget.alloc().initWithCallback_(self._show_plus_menu)
        self._targets.append(plus_target)
        self._plus_btn.setTarget_(plus_target)
        self._plus_btn.setAction_(objc.selector(plus_target.buttonClicked_, signature=b"v@:@"))
        self._root_view.addSubview_(self._plus_btn)

        # 4. Prompt Input Field
        agent_info = self._get_agent_info(self.current_agent_id)
        self._text_field = NSTextField.alloc().initWithFrame_(
            NSRect(NSPoint(52, 11), NSSize(340, 30))
        )
        try:
            cell = QuickBarCenteringCell.alloc().initTextCell_("")
            self._text_field.setCell_(cell)
        except Exception:
            pass
        self._text_field.setFont_(NSFont.systemFontOfSize_(15.0))
        self._text_field.setTextColor_(NSColor.whiteColor())
        self._text_field.setPlaceholderString_(agent_info["placeholder"])
        self._text_field.setBezeled_(False)
        self._text_field.setDrawsBackground_(False)
        self._text_field.setFocusRingType_(1)  # NSFocusRingTypeNone
        self._text_field.setEditable_(True)
        self._text_field.setSelectable_(True)

        self._text_delegate = QuickBarTextDelegate.alloc().initWithBar_(self)
        self._text_field.setDelegate_(self._text_delegate)
        self._root_view.addSubview_(self._text_field)

        # 5. Agent Selector Dropdown Button
        self._agent_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(400, 12), NSSize(120, 28)))
        self._agent_btn.setWantsLayer_(True)
        self._agent_btn.layer().setCornerRadius_(14.0)
        self._agent_btn.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.08).CGColor()
        )
        self._agent_btn.layer().setBorderWidth_(0.5)
        self._agent_btn.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.14).CGColor()
        )
        self._agent_btn.setBordered_(False)
        self._agent_btn.setTitle_(f"{agent_info['name']} ▾")
        self._agent_btn.setFont_(NSFont.systemFontOfSize_(12.5))
        self._agent_btn.setToolTip_("Select Target AI Agent")
        agent_logo = self.get_agent_icon(self.current_agent_id, size=16)
        if agent_logo:
            self._agent_btn.setImage_(agent_logo)
            self._agent_btn.setImagePosition_(NSImageLeft)

        agent_target = QuickBarActionTarget.alloc().initWithCallback_(self._show_agent_menu)
        self._targets.append(agent_target)
        self._agent_btn.setTarget_(agent_target)
        self._agent_btn.setAction_(objc.selector(agent_target.buttonClicked_, signature=b"v@:@"))
        self._root_view.addSubview_(self._agent_btn)

        # 6. Voice Dictation Button (Microphone with active pulse)
        self._mic_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(536, 10), NSSize(32, 32)))
        self._mic_btn.setWantsLayer_(True)
        self._mic_btn.layer().setCornerRadius_(16.0)
        self._mic_btn.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.06).CGColor()
        )
        self._mic_btn.layer().setBorderWidth_(0.5)
        self._mic_btn.layer().setBorderColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.10).CGColor()
        )
        self._mic_btn.setBordered_(False)
        self._mic_btn.setToolTip_("Voice Dictation (Click or Ctrl+Space to Speak)")

        mic_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("mic.fill", None)
        if not mic_img:
            mic_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("mic", None)
        if mic_img:
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(13.5, 5)
            mic_img = mic_img.imageWithSymbolConfiguration_(cfg)
            self._mic_btn.setImage_(mic_img)
        else:
            self._mic_btn.setTitle_("🎙")

        mic_target = QuickBarActionTarget.alloc().initWithCallback_(self.toggle_voice_input)
        self._targets.append(mic_target)
        self._mic_btn.setTarget_(mic_target)
        self._mic_btn.setAction_(objc.selector(mic_target.buttonClicked_, signature=b"v@:@"))
        self._root_view.addSubview_(self._mic_btn)
        self._vifi_btn = self._mic_btn  # Backward-compatible alias

        # 7. Action / Send Button (Royal Blue Up-Arrow Circle)
        self._action_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(576, 10), NSSize(32, 32)))
        self._action_btn.setWantsLayer_(True)
        self._action_btn.layer().setCornerRadius_(16.0)
        self._action_btn.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.145, 0.388, 0.922, 1.0).CGColor()
        )
        self._action_btn.setBordered_(False)
        self._action_btn.setToolTip_("Send Prompt (Enter) • ⌥↵ Silent Send • ⇧↵ New Session")

        send_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("arrow.up", None)
        if not send_img:
            send_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "paperplane.fill", None
            )
        if send_img:
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(14.0, 6)
            send_img = send_img.imageWithSymbolConfiguration_(cfg)
            self._action_btn.setImage_(send_img)
        else:
            self._action_btn.setTitle_("↑")

        action_target = QuickBarActionTarget.alloc().initWithCallback_(self._on_submit_action)
        self._targets.append(action_target)
        self._action_btn.setTarget_(action_target)
        self._action_btn.setAction_(objc.selector(action_target.buttonClicked_, signature=b"v@:@"))
        self._root_view.addSubview_(self._action_btn)

        self._layout_controls()
        self._panel.setContentView_(self._root_view)

    # =========================================================================
    # Menus & Dropdowns
    # =========================================================================

    def _show_plus_menu(self):
        """Display options and context menu when [+] button is clicked."""
        if not self._plus_btn or not self._panel:
            return

        menu = NSMenu.alloc().initWithTitle_("Options")

        item_ctx = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "📎 Include Active Screen Context", None, ""
        )
        menu.addItem_(item_ctx)

        item_new = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "💬 New Conversation (Empty Context)  ⇧↵", None, ""
        )
        target_new = QuickBarActionTarget.alloc().initWithCallback_(
            lambda: self._on_submit_action(new_conversation=True)
        )
        self._targets.append(target_new)
        item_new.setTarget_(target_new)
        item_new.setAction_(objc.selector(target_new.buttonClicked_, signature=b"v@:@"))
        menu.addItem_(item_new)

        item_silent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "🤫 Silent Background Send  ⌥↵", None, ""
        )
        target_silent = QuickBarActionTarget.alloc().initWithCallback_(
            lambda: self._on_submit_action(silent_send=True)
        )
        self._targets.append(target_silent)
        item_silent.setTarget_(target_silent)
        item_silent.setAction_(objc.selector(target_silent.buttonClicked_, signature=b"v@:@"))
        menu.addItem_(item_silent)

        menu.addItem_(NSMenuItem.separatorItem())

        try:
            cfg_curr = load_config()
            focus_target = getattr(cfg_curr.global_hotkey, "quick_bar_focus_target", True)
        except Exception:
            focus_target = True

        focus_title = "✓ Focus Target App on Dispatch" if focus_target else "Focus Target App on Dispatch"
        item_focus = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            focus_title, None, ""
        )

        def _toggle_focus():
            try:
                c = load_config()
                c.global_hotkey.quick_bar_focus_target = not getattr(
                    c.global_hotkey, "quick_bar_focus_target", True
                )
                save_config(c)
            except Exception:
                pass

        target_focus = QuickBarActionTarget.alloc().initWithCallback_(_toggle_focus)
        self._targets.append(target_focus)
        item_focus.setTarget_(target_focus)
        item_focus.setAction_(objc.selector(target_focus.buttonClicked_, signature=b"v@:@"))
        menu.addItem_(item_focus)

        item_speed = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "⚡ Toggle Speed Talking", None, ""
        )

        def _toggle_speed():
            try:
                cfg = load_config()
                cfg.tts.speed_talk = not getattr(cfg.tts, "speed_talk", False)
                save_config(cfg)
            except Exception:
                pass

        target_speed = QuickBarActionTarget.alloc().initWithCallback_(_toggle_speed)
        self._targets.append(target_speed)
        item_speed.setTarget_(target_speed)
        item_speed.setAction_(objc.selector(target_speed.buttonClicked_, signature=b"v@:@"))
        menu.addItem_(item_speed)

        item_settings = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "⚙️ VoiceFi Settings...", None, ""
        )

        def _open_settings():
            import subprocess

            subprocess.Popen(["open", "http://localhost:5141"])

        target_settings = QuickBarActionTarget.alloc().initWithCallback_(_open_settings)
        self._targets.append(target_settings)
        item_settings.setTarget_(target_settings)
        item_settings.setAction_(objc.selector(target_settings.buttonClicked_, signature=b"v@:@"))
        menu.addItem_(item_settings)

        self._is_menu_open = True
        try:
            menu.popUpMenuPositioningItem_atLocation_inView_(None, NSPoint(0, 0), self._plus_btn)
        finally:
            self._is_menu_open = False

    def _build_agent_menu(self) -> NSMenu:
        """Construct agent selection NSMenu with official brand logos instead of emojis."""
        menu = NSMenu.alloc().initWithTitle_("Select Agent")

        for agent in SUPPORTED_AGENTS:
            title = agent["name"]
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
            logo = self.get_agent_icon(agent["id"], size=18)
            if logo:
                item.setImage_(logo)

            # Submenu or custom target to switch agent
            target = QuickBarActionTarget.alloc().initWithCallback_(
                lambda a_id=agent["id"]: self.select_agent(a_id)
            )
            self._targets.append(target)
            item.setTarget_(target)
            item.setAction_(objc.selector(target.buttonClicked_, signature=b"v@:@"))
            if agent["id"] == self.current_agent_id:
                item.setState_(1)
            menu.addItem_(item)
        return menu

    def _show_agent_menu(self):
        """Display agent selection dropdown menu with official brand logos instead of emojis."""
        if not self._agent_btn or not self._panel:
            return

        menu = self._build_agent_menu()
        self._is_menu_open = True
        try:
            menu.popUpMenuPositioningItem_atLocation_inView_(None, NSPoint(0, 0), self._agent_btn)
        finally:
            self._is_menu_open = False

    def select_agent(self, agent_id: str):
        """Switch active agent target, update button title, icon, placeholder, and persist preference."""
        self.current_agent_id = agent_id
        agent_info = self._get_agent_info(agent_id)
        logo = self.get_agent_icon(agent_id, size=16)

        def _update():
            if self._agent_btn:
                self._agent_btn.setTitle_(f"{agent_info['name']} ▾")
                if logo and hasattr(self._agent_btn, "setImage_"):
                    self._agent_btn.setImage_(logo)
                    if hasattr(self._agent_btn, "setImagePosition_"):
                        self._agent_btn.setImagePosition_(NSImageLeft)
                self._layout_controls()
            if self._text_field:
                self._text_field.setPlaceholderString_(agent_info["placeholder"])

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

        # Persist choice
        try:
            cfg = load_config()
            cfg.global_hotkey.quick_bar_agent = agent_id
            save_config(cfg)
        except Exception:
            pass

    # =========================================================================
    # Voice Dictation
    # =========================================================================

    def toggle_voice_input(self):
        """Toggle VoiceFi speech recognition into the text field."""
        if self.is_voice_active:
            self.stop_voice_input()
        else:
            self.start_voice_input()

    def start_voice_input(self):
        """Activate microphone recording and stream live transcript into input field."""
        if self.is_voice_active:
            return
        self.is_voice_active = True
        self._initial_text_before_voice = (
            self._text_field.stringValue().strip() if self._text_field else ""
        )
        if self.on_voice_toggle:
            try:
                self.on_voice_toggle(True)
            except Exception:
                pass

        def _set_active_ui():
            btn = getattr(self, "_mic_btn", None) or getattr(self, "_vifi_btn", None)
            if btn:
                btn.layer().setBackgroundColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        0.92, 0.25, 0.25, 0.88
                    ).CGColor()
                )
                btn.layer().setBorderWidth_(1.2)
                btn.layer().setBorderColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.6, 0.6, 0.9).CGColor()
                )
                wave_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "waveform", None
                )
                if wave_img:
                    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(13.5, 6)
                    wave_img = wave_img.imageWithSymbolConfiguration_(cfg)
                    btn.setImage_(wave_img)
                btn.setToolTip_("Listening... (Click or Ctrl+Space to Stop)")

        if threading.current_thread() is threading.main_thread():
            _set_active_ui()
        else:
            AppHelper.callAfter(_set_active_ui)

        self._ptt_stop_event = threading.Event()

        def _worker():
            try:
                from voicefi.audio.recorder import AudioRecorder
                from voicefi.stt import get_stt_engine
                from voicefi.audio.chimes import play_chime
                from voicefi.tts.base import stop_all_speech

                # Halt any active TTS so it doesn't mute the microphone on built-in speakers
                stop_all_speech()

                cfg = load_config()
                if getattr(cfg.audio_cues, "enabled", True):
                    play_chime("start", block=False)
                time.sleep(0.15)

                recorder = AudioRecorder(
                    sample_rate=cfg.vad.sample_rate,
                    energy_threshold=cfg.vad.energy_threshold,
                    silence_duration=cfg.vad.silence_duration,
                    barge_in=True,
                )
                self._active_recorder = recorder

                def _on_live(txt: str):
                    if not self.is_voice_active and not getattr(self, "_pending_submit", None):
                        return

                    def _update_txt():
                        if self._text_field:
                            prefix = getattr(self, "_initial_text_before_voice", "")
                            full_txt = f"{prefix} {txt}".strip() if prefix else txt
                            self._text_field.setStringValue_(full_txt)

                    AppHelper.callAfter(_update_txt)

                def _on_tick(energy: float, conf: float = 0.0, is_spk: bool = False):
                    if not self.is_voice_active:
                        return

                    def _pulse():
                        btn = getattr(self, "_mic_btn", None) or getattr(self, "_vifi_btn", None)
                        if btn and btn.layer():
                            if is_spk or energy > 0.015:
                                btn.layer().setBorderWidth_(2.0)
                                btn.layer().setBorderColor_(
                                    NSColor.colorWithCalibratedRed_green_blue_alpha_(
                                        1.0, 0.85, 0.85, 1.0
                                    ).CGColor()
                                )
                            else:
                                btn.layer().setBorderWidth_(1.2)
                                btn.layer().setBorderColor_(
                                    NSColor.colorWithCalibratedRed_green_blue_alpha_(
                                        1.0, 0.6, 0.6, 0.9
                                    ).CGColor()
                                )

                    AppHelper.callAfter(_pulse)

                audio_data, temp_wav = recorder.record_speech_auto(
                    on_live_transcript=_on_live,
                    on_listening_tick=_on_tick,
                    stop_event=self._ptt_stop_event,
                    cancel_on_typing=False,
                )

                final_text = ""
                stt = get_stt_engine(cfg)
                if temp_wav and Path(temp_wav).is_file() and Path(temp_wav).stat().st_size > 0:
                    final_text = stt.transcribe(temp_wav)
                elif audio_data is not None and len(audio_data) > 0:
                    final_text = stt.transcribe(audio_data)

                final_text = final_text.strip() if final_text else ""
                prefix = getattr(self, "_initial_text_before_voice", "")
                result_text = f"{prefix} {final_text}".strip() if prefix else final_text

                current_val = self._text_field.stringValue().strip() if self._text_field else ""
                target_text = result_text or current_val

                def _set_final():
                    if self._text_field and target_text:
                        self._text_field.setStringValue_(target_text)

                AppHelper.callAfter(_set_final)

                pending = getattr(self, "_pending_submit", None)
                if pending:
                    self._pending_submit = None
                    new_conv = pending.get("new_conversation", False)
                    silent = pending.get("silent_send", False)

                    def _do_submit():
                        self._dispatch_submitted_text(
                            target_text, new_conversation=new_conv, silent_send=silent
                        )

                    AppHelper.callAfter(_do_submit)

            except Exception as e:
                print(f"[QuickBar] Voice dictation error: {e}", flush=True)
                try:
                    from voicefi.audio.chimes import play_chime

                    play_chime("error", block=False)
                except Exception:
                    pass
            finally:
                self.stop_voice_input()

        threading.Thread(target=_worker, daemon=True, name="QuickBarVoiceWorker").start()

    def stop_voice_input(self):
        """Stop voice dictation and reset button styling."""
        self.is_voice_active = False
        if self.on_voice_toggle:
            try:
                self.on_voice_toggle(False)
            except Exception:
                pass
        if self._ptt_stop_event:
            self._ptt_stop_event.set()
        if self._active_recorder:
            try:
                self._active_recorder.stop()
            except Exception:
                pass
            self._active_recorder = None

        def _reset_ui():
            btn = getattr(self, "_mic_btn", None) or getattr(self, "_vifi_btn", None)
            if btn:
                btn.layer().setBackgroundColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.06).CGColor()
                )
                btn.layer().setBorderWidth_(0.5)
                btn.layer().setBorderColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.10).CGColor()
                )
                mic_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "mic.fill", None
                )
                if not mic_img:
                    mic_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                        "mic", None
                    )
                if mic_img:
                    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(13.5, 5)
                    mic_img = mic_img.imageWithSymbolConfiguration_(cfg)
                    btn.setImage_(mic_img)
                btn.setToolTip_("Voice Dictation (Click or Ctrl+Space to Speak)")

        if threading.current_thread() is threading.main_thread():
            _reset_ui()
        else:
            AppHelper.callAfter(_reset_ui)

    # =========================================================================
    # Submit & Multi-Agent Dispatch
    # =========================================================================

    def _on_submit_action(
        self, new_conversation: bool = False, silent_send: Optional[bool] = None
    ):
        """Submit text prompt to selected agent."""
        if not self._text_field:
            return

        # Determine effective silent send
        if silent_send is None:
            try:
                cfg = load_config()
                focus_target = getattr(cfg.global_hotkey, "quick_bar_focus_target", True)
                effective_silent = not focus_target
            except Exception:
                effective_silent = False
        else:
            effective_silent = silent_send

        if self.is_voice_active:
            print(
                f"[QuickBar] 🎙️ Submit requested while voice active (silent={effective_silent}) -> finalizing speech transcription first...",
                flush=True,
            )
            self._pending_submit = {
                "new_conversation": new_conversation,
                "silent_send": effective_silent,
            }
            self.stop_voice_input()
            if not self._text_field.stringValue().strip():
                self._text_field.setPlaceholderString_("Transcribing speech...")
            return

        text = self._text_field.stringValue().strip()
        self._dispatch_submitted_text(
            text, new_conversation=new_conversation, silent_send=effective_silent
        )

    def _dispatch_submitted_text(
        self, text: str, new_conversation: bool = False, silent_send: bool = False
    ):
        agent_id = self.current_agent_id

        # Hide bar immediately
        self.hide()
        if self._text_field:
            self._text_field.setStringValue_("")
            agent_info = self._get_agent_info(self.current_agent_id)
            self._text_field.setPlaceholderString_(agent_info["placeholder"])

        print(
            f"[QuickBar] 🚀 Dispatching prompt to {agent_id} (new_conv={new_conversation}, silent={silent_send}): {text[:60]}..."
        )

        # If custom callback provided, use it
        if self.on_submit:
            try:
                self.on_submit(text, agent_id)
                if silent_send:
                    self.restore_previous_focus()
                return
            except Exception as e:
                print(f"[QuickBar] on_submit callback error: {e}")

        # Default multi-agent dispatch logic
        self.dispatch_to_agent(
            text, agent_id, new_conversation=new_conversation, silent_send=silent_send
        )

    def dispatch_to_agent(
        self, text: str, agent_id: str, new_conversation: bool = False, silent_send: bool = False
    ):
        """Execute prompt dispatch for the targeted agent."""
        clean_prompt = text.strip() or "Hello"

        if agent_id == "antigravity":
            from voicefi.integrations.injector import (
                inject_text_to_antigravity,
                send_message_to_antigravity,
                focus_antigravity,
                create_new_antigravity_conversation,
            )
            from voicefi.audio.chimes import play_chime

            if new_conversation:
                create_new_antigravity_conversation(prompt=clean_prompt)
                if silent_send:
                    self.restore_previous_focus()
            else:
                if silent_send:
                    # In silent mode, attempt native agentapi IPC first (zero window focus changes)
                    res = send_message_to_antigravity(text=clean_prompt)
                    if not res:
                        inject_text_to_antigravity(
                            clean_prompt,
                            submit_enter=True,
                            restore_focus=True,
                            new_conversation=False,
                        )
                    self.restore_previous_focus()
                else:
                    injected = inject_text_to_antigravity(
                        clean_prompt,
                        submit_enter=True,
                        new_conversation=False,
                    )
                    if not injected:
                        send_message_to_antigravity(text=clean_prompt)
                        focus_antigravity(focus_input=True)

            try:
                cfg = load_config()
                if getattr(cfg.audio_cues, "enabled", True):
                    play_chime(cfg.audio_cues.sent_chime, block=False)
            except Exception:
                pass

        elif agent_id in ("claude", "claude_code"):
            from voicefi.integrations.injector import inject_text_to_claude, focus_app_by_name

            inject_text_to_claude(text=clean_prompt, auto_submit=True)
            if silent_send:
                self.restore_previous_focus()
            else:
                focus_app_by_name("Claude")

        elif agent_id in ("flash", "pro", "gemini"):
            from voicefi.integrations.injector import send_message_to_agent

            send_message_to_agent(text=clean_prompt, target_engine="gemini")
            if silent_send:
                self.restore_previous_focus()

        elif agent_id in ("chatgpt", "openai"):
            from voicefi.integrations.injector import inject_text_to_chatgpt, focus_app_by_name

            inject_text_to_chatgpt(text=clean_prompt, auto_submit=True)
            if silent_send:
                self.restore_previous_focus()
            else:
                focus_app_by_name("ChatGPT")

        else:
            from voicefi.integrations.injector import inject_text_to_antigravity

            inject_text_to_antigravity(
                clean_prompt,
                submit_enter=True,
                restore_focus=silent_send,
                new_conversation=new_conversation,
            )
            if silent_send:
                self.restore_previous_focus()

    # =========================================================================
    # Window Visibility & Toggle
    # =========================================================================

    def show(self, initial_text: Optional[str] = None):
        """Present floating prompt bar centered on active screen with text field focused."""

        def _do_show():
            if not self._panel:
                self._build_panel()
            if not self._panel:
                return

            print("[QuickBar] 🪄 Showing Quick Prompt Bar window", flush=True)

            # Center on current active screen
            screen = NSScreen.mainScreen()
            if screen:
                vf = screen.visibleFrame()
                x = vf.origin.x + (vf.size.width - self.STANDARD_WIDTH) / 2.0
                y = vf.origin.y + (vf.size.height * 0.65) - (self.STANDARD_HEIGHT / 2.0)
                self._panel.setFrameOrigin_(NSPoint(x, y))

            if initial_text and self._text_field:
                self._text_field.setStringValue_(initial_text)

            self._last_show_time = time.time()
            try:
                from AppKit import NSWorkspace

                ws = NSWorkspace.sharedWorkspace()
                front_app = ws.frontmostApplication()
                if front_app:
                    bid = front_app.bundleIdentifier()
                    if not bid or "voicefi" not in bid.lower():
                        self._prev_active_app = front_app
            except Exception:
                pass
            try:
                from AppKit import NSRunningApplication

                NSRunningApplication.currentApplication().activateWithOptions_(1 << 1)
            except Exception:
                pass
            try:
                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass

            self._panel.orderFrontRegardless()
            self._panel.makeKeyAndOrderFront_(None)

            if self._text_field:
                self._panel.makeFirstResponder_(self._text_field)
                self._text_field.selectText_(None)

        if threading.current_thread() is threading.main_thread():
            _do_show()
        else:
            AppHelper.callAfter(_do_show)

    def restore_previous_focus(self):
        """Restore focus to the application that was active before the Quick Bar opened."""

        def _restore():
            try:
                prev_app = getattr(self, "_prev_active_app", None)
                if prev_app:
                    time.sleep(0.12)
                    prev_app.activateWithOptions_(1 << 1)
            except Exception as e:
                print(f"[QuickBar] Could not restore previous focus: {e}")

        threading.Thread(target=_restore, daemon=True, name="QuickBarRestoreFocus").start()

    def hide(self):
        """Dismiss floating prompt bar."""

        def _do_hide():
            print("[QuickBar] 🪄 Hiding Quick Prompt Bar window", flush=True)
            if self.is_voice_active:
                self.stop_voice_input()
            if self._panel and self._panel.isVisible():
                self._panel.orderOut_(None)

        if threading.current_thread() is threading.main_thread():
            _do_hide()
        else:
            AppHelper.callAfter(_do_hide)

    def toggle(self, initial_text: Optional[str] = None):
        """Toggle prompt bar visibility."""

        def _do_toggle():
            if self._panel and self._panel.isVisible():
                self.hide()
            else:
                self.show(initial_text=initial_text)

        if threading.current_thread() is threading.main_thread():
            _do_toggle()
        else:
            AppHelper.callAfter(_do_toggle)
