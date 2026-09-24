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
                    try:
                        from AppKit import NSApp, NSEventModifierFlagShift

                        ev = NSApp.currentEvent()
                        if ev:
                            is_shift = bool(ev.modifierFlags() & NSEventModifierFlagShift)
                    except Exception:
                        pass
                    self.bar._on_submit_action(new_conversation=is_shift)
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
        self._vifi_btn: Optional[NSButton] = None
        self._action_btn: Optional[NSButton] = None
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
        self._plus_btn.setBordered_(False)
        self._plus_btn.setToolTip_("Options & Context")
        plus_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("plus", None)
        if plus_img:
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(14.0, 5)
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
            NSRect(NSPoint(48, 11), NSSize(360, 30))
        )
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
        self._agent_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(414, 12), NSSize(100, 28)))
        self._agent_btn.setWantsLayer_(True)
        self._agent_btn.layer().setCornerRadius_(14.0)
        self._agent_btn.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.08).CGColor()
        )
        self._agent_btn.setBordered_(False)
        self._agent_btn.setTitle_(f"{agent_info['name']} ▾")
        self._agent_btn.setFont_(NSFont.systemFontOfSize_(12.5))
        self._agent_btn.setToolTip_("Select Target AI Agent")

        agent_target = QuickBarActionTarget.alloc().initWithCallback_(self._show_agent_menu)
        self._targets.append(agent_target)
        self._agent_btn.setTarget_(agent_target)
        self._agent_btn.setAction_(objc.selector(agent_target.buttonClicked_, signature=b"v@:@"))
        self._root_view.addSubview_(self._agent_btn)

        # 6. VoiceFi Character Logo Button (Replaces Generic Mic)
        self._vifi_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(522, 10), NSSize(32, 32)))
        self._vifi_btn.setWantsLayer_(True)
        self._vifi_btn.layer().setCornerRadius_(16.0)
        self._vifi_btn.setBordered_(False)
        self._vifi_btn.setToolTip_("VoiceFi Voice Engine (Click to Speak / Dictate)")

        # Load VoiceFi Logo Asset
        icon_paths = [
            Path(__file__).resolve().parent.parent.parent.parent
            / "assets"
            / "logo-voicefi-avatar-bold-dark-1024.png",
            Path(__file__).resolve().parent.parent.parent.parent / "assets" / "VoiceFi.icns",
            Path.home() / ".voicefi" / "assets" / "VoiceFi.icns",
        ]
        vifi_icon = None
        for p in icon_paths:
            if p.is_file():
                vifi_icon = NSImage.alloc().initWithContentsOfFile_(str(p))
                if vifi_icon and vifi_icon.isValid():
                    vifi_icon.setSize_(NSSize(24, 24))
                    break
        if vifi_icon:
            self._vifi_btn.setImage_(vifi_icon)
            if hasattr(self._vifi_btn, "setImageScaling_"):
                self._vifi_btn.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        else:
            self._vifi_btn.setTitle_("VF")

        vifi_target = QuickBarActionTarget.alloc().initWithCallback_(self.toggle_voice_input)
        self._targets.append(vifi_target)
        self._vifi_btn.setTarget_(vifi_target)
        self._vifi_btn.setAction_(objc.selector(vifi_target.buttonClicked_, signature=b"v@:@"))
        self._root_view.addSubview_(self._vifi_btn)

        # 7. Royal Blue Action Submit Circle Button
        self._action_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(566, 7), NSSize(38, 38)))
        self._action_btn.setWantsLayer_(True)
        self._action_btn.layer().setCornerRadius_(19.0)
        self._action_btn.layer().setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.145, 0.388, 0.922, 1.0).CGColor()
        )
        self._action_btn.setBordered_(False)
        self._action_btn.setToolTip_("Send Prompt (Enter) • ⇧↵ for New Session")

        action_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("waveform", None)
        if not action_img:
            action_img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                "sparkles", None
            )
        if action_img:
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(16.0, 5)
            action_img = action_img.imageWithSymbolConfiguration_(cfg)
            self._action_btn.setImage_(action_img)
        else:
            self._action_btn.setTitle_("↵")

        action_target = QuickBarActionTarget.alloc().initWithCallback_(self._on_submit_action)
        self._targets.append(action_target)
        self._action_btn.setTarget_(action_target)
        self._action_btn.setAction_(objc.selector(action_target.buttonClicked_, signature=b"v@:@"))
        self._root_view.addSubview_(self._action_btn)

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

        menu.addItem_(NSMenuItem.separatorItem())

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

    def _show_agent_menu(self):
        """Display agent selection dropdown menu when model button is clicked."""
        if not self._agent_btn or not self._panel:
            return

        menu = NSMenu.alloc().initWithTitle_("Select Agent")

        for agent in SUPPORTED_AGENTS:
            title = f"{agent['icon']} {agent['name']}"
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")

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

        self._is_menu_open = True
        try:
            menu.popUpMenuPositioningItem_atLocation_inView_(None, NSPoint(0, 0), self._agent_btn)
        finally:
            self._is_menu_open = False

    def select_agent(self, agent_id: str):
        """Switch active agent target, update button title, placeholder, and persist preference."""
        self.current_agent_id = agent_id
        agent_info = self._get_agent_info(agent_id)

        def _update():
            if self._agent_btn:
                self._agent_btn.setTitle_(f"{agent_info['name']} ▾")
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

        def _set_active_ui():
            if self._vifi_btn:
                self._vifi_btn.layer().setBackgroundColor_(
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.2, 0.2, 0.4).CGColor()
                )

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

                cfg = load_config()
                if getattr(cfg.audio_cues, "enabled", True):
                    play_chime("start", block=False)
                time.sleep(0.2)

                recorder = AudioRecorder(
                    sample_rate=cfg.vad.sample_rate,
                    energy_threshold=cfg.vad.energy_threshold,
                    silence_duration=cfg.vad.silence_duration,
                )
                self._active_recorder = recorder

                def _on_live(txt: str):
                    if not self.is_voice_active:
                        return

                    def _update_txt():
                        if self._text_field:
                            self._text_field.setStringValue_(txt)

                    AppHelper.callAfter(_update_txt)

                audio_data, temp_wav = recorder.record_speech_auto(
                    on_live_transcript=_on_live,
                )

                if audio_data is not None:
                    stt = get_stt_engine(cfg)
                    final_text = stt.transcribe(audio_data)
                    if final_text and final_text.strip():

                        def _set_final():
                            if self._text_field:
                                self._text_field.setStringValue_(final_text.strip())

                        AppHelper.callAfter(_set_final)

            except Exception as e:
                print(f"[QuickBar] Voice dictation error: {e}")
            finally:
                self.stop_voice_input()

        threading.Thread(target=_worker, daemon=True, name="QuickBarVoiceWorker").start()

    def stop_voice_input(self):
        """Stop voice dictation and reset button styling."""
        self.is_voice_active = False
        if self._ptt_stop_event:
            self._ptt_stop_event.set()
        if self._active_recorder:
            try:
                self._active_recorder.stop()
            except Exception:
                pass
            self._active_recorder = None

        def _reset_ui():
            if self._vifi_btn:
                self._vifi_btn.layer().setBackgroundColor_(NSColor.clearColor().CGColor())

        if threading.current_thread() is threading.main_thread():
            _reset_ui()
        else:
            AppHelper.callAfter(_reset_ui)

    # =========================================================================
    # Submit & Multi-Agent Dispatch
    # =========================================================================

    def _on_submit_action(self, new_conversation: bool = False):
        """Submit text prompt to selected agent."""
        if not self._text_field:
            return

        text = self._text_field.stringValue().strip()
        agent_id = self.current_agent_id

        # Hide bar immediately
        self.hide()
        self._text_field.setStringValue_("")

        print(
            f"[QuickBar] 🚀 Dispatching prompt to {agent_id} (new_conv={new_conversation}): {text[:60]}..."
        )

        # If custom callback provided, use it
        if self.on_submit:
            try:
                self.on_submit(text, agent_id)
                return
            except Exception as e:
                print(f"[QuickBar] on_submit callback error: {e}")

        # Default multi-agent dispatch logic
        self.dispatch_to_agent(text, agent_id, new_conversation=new_conversation)

    def dispatch_to_agent(self, text: str, agent_id: str, new_conversation: bool = False):
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
            focus_app_by_name("Claude")

        elif agent_id in ("flash", "pro", "gemini"):
            from voicefi.integrations.injector import send_message_to_agent

            send_message_to_agent(text=clean_prompt, target_engine="gemini")

        elif agent_id in ("chatgpt", "openai"):
            from voicefi.integrations.injector import inject_text_to_chatgpt, focus_app_by_name

            inject_text_to_chatgpt(text=clean_prompt, auto_submit=True)
            focus_app_by_name("ChatGPT")

        else:
            from voicefi.integrations.injector import inject_text_to_antigravity

            inject_text_to_antigravity(
                clean_prompt, submit_enter=True, new_conversation=new_conversation
            )

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
