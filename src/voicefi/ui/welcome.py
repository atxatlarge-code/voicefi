"""
Native macOS AppKit Welcome & License Activation Window.
Provides first-run onboarding, clipboard license auto-detection, 1-click Pro activation,
14-day free trial start, and instant spoken audio verification.
"""

import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Callable

from AppKit import (
    NSApplication,
    NSWindow,
    NSPanel,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSBackingStoreBuffered,
    NSRect,
    NSPoint,
    NSSize,
    NSTextField,
    NSTextAlignmentCenter,
    NSTextAlignmentLeft,
    NSButton,
    NSBezelStyleRounded,
    NSColor,
    NSFont,
    NSFontWeightBold,
    NSFontWeightSemibold,
    NSFontWeightMedium,
    NSFontWeightRegular,
    NSScreen,
    NSView,
    NSImageView,
    NSImage,
    NSImageScaleProportionallyUpOrDown,
    NSWorkspace,
    NSURL,
    NSPasteboard,
    NSPasteboardTypeString,
    NSFloatingWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorMoveToActiveSpace,
)
import objc
from PyObjCTools import AppHelper

from voicefi.config import load_config, save_config
from voicefi.license import verify_license_key, FeatureGate


def is_headless() -> bool:
    """Check if running in headless testing environment."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("VOICEFI_TESTING") == "1"
    )


try:
    WelcomeActionTarget = objc.lookUpClass("WelcomeActionTarget")
except objc.nosuchclass_error:

    class WelcomeActionTarget(objc.lookUpClass("NSObject")):
        """Objective-C target wrapper for NSButton clicks in Welcome Window."""

        def initWithCallback_(self, callback):
            self = objc.super(WelcomeActionTarget, self).init()
            if self is not None:
                self.callback = callback
            return self

        def buttonClicked_(self, sender):
            if self.callback:
                self.callback()


class VoiceFiWelcomeWindow:
    """Native macOS Welcome & License Activation Window."""

    _instance: Optional["VoiceFiWelcomeWindow"] = None

    @classmethod
    def get_instance(cls, on_activated: Optional[Callable] = None) -> "VoiceFiWelcomeWindow":
        if cls._instance is None:
            cls._instance = cls(on_activated=on_activated)
        elif on_activated:
            cls._instance._on_activated_callback = on_activated
        return cls._instance

    @classmethod
    def show_if_first_run(cls, force: bool = False) -> None:
        """Display the welcome window on first application run or if unactivated."""
        if is_headless():
            return

        marker_file = Path.home() / ".voicefi" / ".welcomed"
        config = load_config()
        tier_info = FeatureGate.get_tier_summary(config)

        # Show if explicitly forced, if marker doesn't exist, or if unactivated trial expired
        if force or not marker_file.exists() or (not tier_info.get("is_licensed") and tier_info.get("trial_expired")):
            AppHelper.callAfter(cls.show_window)

    @classmethod
    def show_window(cls) -> None:
        """Display the window on the main Cocoa thread."""
        if is_headless():
            return
        inst = cls.get_instance()
        inst.show()

    def __init__(self, on_activated: Optional[Callable] = None):
        self._on_activated_callback = on_activated
        self.window: Optional[NSPanel] = None
        self.key_field: Optional[NSTextField] = None
        self.status_label: Optional[NSTextField] = None
        self.detected_banner: Optional[NSTextField] = None
        self._targets = []
        self._build_window()

    def _build_window(self):
        if is_headless():
            return

        win_w, win_h = 520.0, 500.0

        # Center on primary active screen
        screen = NSScreen.mainScreen()
        if screen:
            screen_frame = screen.visibleFrame()
            x = screen_frame.origin.x + (screen_frame.size.width - win_w) / 2.0
            y = screen_frame.origin.y + (screen_frame.size.height - win_h) / 2.0
        else:
            x, y = 300.0, 250.0

        frame = NSRect(NSPoint(x, y), NSSize(win_w, win_h))
        style_mask = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
        )

        self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style_mask, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Welcome to VoiceFi Pro")
        self.window.setLevel_(NSFloatingWindowLevel)
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorMoveToActiveSpace
        )
        self.window.setReleasedWhenClosed_(False)

        content_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(win_w, win_h)))
        self.window.setContentView_(content_view)

        # 1. App Icon
        icon_view = NSImageView.alloc().initWithFrame_(NSRect(NSPoint((win_w - 72.0) / 2.0, win_h - 96.0), NSSize(72.0, 72.0)))
        icon_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        
        # Load VoiceFi icon
        icon_paths = [
            Path(__file__).resolve().parent.parent.parent.parent / "assets" / "VoiceFi.icns",
            Path(__file__).resolve().parent.parent.parent.parent / "assets" / "logo-voicefi-avatar-bold-light-1024.png",
            Path.home() / ".voicefi" / "assets" / "VoiceFi.icns",
        ]
        app_icon = None
        for p in icon_paths:
            if p.is_file():
                app_icon = NSImage.alloc().initWithContentsOfFile_(str(p))
                if app_icon and app_icon.isValid():
                    break
        if app_icon:
            icon_view.setImage_(app_icon)
        content_view.addSubview_(icon_view)

        # 2. Main Title
        title_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(20.0, win_h - 132.0), NSSize(win_w - 40.0, 28.0)))
        title_label.setStringValue_("Welcome to VoiceFi")
        title_label.setFont_(NSFont.systemFontOfSize_weight_(20.0, NSFontWeightBold))
        title_label.setAlignment_(NSTextAlignmentCenter)
        title_label.setEditable_(False)
        title_label.setSelectable_(False)
        title_label.setBezeled_(False)
        title_label.setDrawsBackground_(False)
        content_view.addSubview_(title_label)

        # Subtitle
        sub_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(20.0, win_h - 156.0), NSSize(win_w - 40.0, 20.0)))
        sub_label.setStringValue_("Universal Voice Layer for AI Agents & macOS")
        sub_label.setFont_(NSFont.systemFontOfSize_weight_(12.0, NSFontWeightMedium))
        sub_label.setTextColor_(NSColor.secondaryLabelColor())
        sub_label.setAlignment_(NSTextAlignmentCenter)
        sub_label.setEditable_(False)
        sub_label.setSelectable_(False)
        sub_label.setBezeled_(False)
        sub_label.setDrawsBackground_(False)
        content_view.addSubview_(sub_label)

        # 3. Clipboard Key Detected Banner (hidden initially)
        self.detected_banner = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(40.0, win_h - 192.0), NSSize(win_w - 80.0, 24.0)))
        self.detected_banner.setStringValue_("✨ Detected Pro key on clipboard — Ready to activate!")
        self.detected_banner.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightSemibold))
        self.detected_banner.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.75, 0.35, 1.0))
        self.detected_banner.setAlignment_(NSTextAlignmentCenter)
        self.detected_banner.setEditable_(False)
        self.detected_banner.setSelectable_(False)
        self.detected_banner.setBezeled_(False)
        self.detected_banner.setDrawsBackground_(False)
        self.detected_banner.setHidden_(True)
        content_view.addSubview_(self.detected_banner)

        # 4. License Key Input Box
        key_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(40.0, win_h - 224.0), NSSize(win_w - 80.0, 18.0)))
        key_label.setStringValue_("License Key (or Paste Pro Key):")
        key_label.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightSemibold))
        key_label.setTextColor_(NSColor.labelColor())
        key_label.setEditable_(False)
        key_label.setSelectable_(False)
        key_label.setBezeled_(False)
        key_label.setDrawsBackground_(False)
        content_view.addSubview_(key_label)

        self.key_field = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(40.0, win_h - 262.0), NSSize(win_w - 80.0, 32.0)))
        self.key_field.setFont_(NSFont.userFixedPitchFontOfSize_(12.0))
        self.key_field.setPlaceholderString_("VF1-PRO-PERP-...")
        content_view.addSubview_(self.key_field)

        # 5. Primary Action Button: "⚡ Activate Pro License"
        act_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(40.0, win_h - 310.0), NSSize(win_w - 80.0, 38.0)))
        act_btn.setTitle_("⚡ Activate Pro License")
        act_btn.setBezelStyle_(NSBezelStyleRounded)
        act_btn.setFont_(NSFont.systemFontOfSize_weight_(13.0, NSFontWeightBold))
        act_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_activate_clicked)
        self._targets.append(act_target)
        act_btn.setTarget_(act_target)
        act_btn.setAction_(objc.selector(act_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(act_btn)

        # 6. Status Feedback Label
        self.status_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(40.0, win_h - 340.0), NSSize(win_w - 80.0, 22.0)))
        self.status_label.setStringValue_("")
        self.status_label.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        self.status_label.setAlignment_(NSTextAlignmentCenter)
        self.status_label.setEditable_(False)
        self.status_label.setSelectable_(False)
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        content_view.addSubview_(self.status_label)

        # 7. Secondary Action Buttons
        # "✨ Start 14-Day Free Trial"
        trial_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(40.0, win_h - 384.0), NSSize(215.0, 32.0)))
        trial_btn.setTitle_("✨ Start 14-Day Free Trial")
        trial_btn.setBezelStyle_(NSBezelStyleRounded)
        trial_btn.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        trial_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_trial_clicked)
        self._targets.append(trial_target)
        trial_btn.setTarget_(trial_target)
        trial_btn.setAction_(objc.selector(trial_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(trial_btn)

        # "🔊 Test Voice"
        test_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(265.0, win_h - 384.0), NSSize(215.0, 32.0)))
        test_btn.setTitle_("🔊 Test Voice (0ms Speech)")
        test_btn.setBezelStyle_(NSBezelStyleRounded)
        test_btn.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        test_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_test_voice_clicked)
        self._targets.append(test_target)
        test_btn.setTarget_(test_target)
        test_btn.setAction_(objc.selector(test_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(test_btn)

        # 8. Bottom Link: "Need a license? Visit VoiceFi.org"
        get_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(40.0, 20.0), NSSize(win_w - 80.0, 26.0)))
        get_btn.setTitle_("Get a License Key on VoiceFi.org ➔")
        get_btn.setBezelStyle_(NSBezelStyleRounded)
        get_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        get_target = WelcomeActionTarget.alloc().initWithCallback_(self._open_website)
        self._targets.append(get_target)
        get_btn.setTarget_(get_target)
        get_btn.setAction_(objc.selector(get_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(get_btn)

    def show(self):
        """Show the window and inspect clipboard for license keys."""
        if is_headless() or not self.window:
            return

        # Check clipboard for existing key
        self._inspect_clipboard()

        # Check current tier to update fields
        config = load_config()
        if getattr(config, "license_key", ""):
            self.key_field.setStringValue_(config.license_key)
            self.status_label.setStringValue_(f"⚡ Pro Active ({getattr(config, 'tier', 'pro').upper()})")
            self.status_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.75, 0.35, 1.0))

        self.window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def hide(self):
        if self.window:
            self.window.orderOut_(None)

    def _inspect_clipboard(self):
        """Inspect macOS pasteboard for valid VF1- license key."""
        try:
            pb = NSPasteboard.generalPasteboard()
            clip_str = pb.stringForType_(NSPasteboardTypeString)
            if clip_str:
                clip_clean = clip_str.strip()
                if clip_clean.startswith("VF1-") and len(clip_clean) > 20:
                    self.key_field.setStringValue_(clip_clean)
                    self.detected_banner.setHidden_(False)
                    return
        except Exception:
            pass
        if self.detected_banner:
            self.detected_banner.setHidden_(True)

    def _on_activate_clicked(self):
        """Handle License Activation."""
        raw_key = self.key_field.stringValue().strip() if self.key_field else ""
        if not raw_key:
            self._set_status("⚠️ Please enter a license key.", is_error=True)
            return

        res = verify_license_key(raw_key)
        if not res.get("is_valid"):
            err = res.get("error") or "Invalid license key signature."
            self._set_status(f"❌ {err}", is_error=True)
            return

        # Activate on config
        try:
            config = load_config()
            config.license_key = raw_key
            config.tier = res.get("tier", "pro")
            save_config(config)

            # Mark welcomed marker
            marker_file = Path.home() / ".voicefi" / ".welcomed"
            marker_file.parent.mkdir(parents=True, exist_ok=True)
            marker_file.write_text(f"welcomed_at={time.time()}\n")

            tier_name = res.get("tier", "pro").upper()
            tag = res.get("tag", "")
            desc = f"⚡ Pro Activated ({tier_name} - {tag})" if tag else f"⚡ Pro Activated ({tier_name})"
            self._set_status(f"✅ {desc}! All neural voices unlocked.", is_error=False)

            # Play success chime
            try:
                from voicefi.audio.chimes import play_chime
                play_chime("success")
            except Exception:
                pass

            if self._on_activated_callback:
                try:
                    self._on_activated_callback(raw_key)
                except Exception:
                    pass

        except Exception as e:
            self._set_status(f"❌ Error saving license: {e}", is_error=True)

    def _on_trial_clicked(self):
        """Activate 14-day Pro Trial."""
        try:
            config = load_config()
            FeatureGate.start_trial(config)
            save_config(config)

            marker_file = Path.home() / ".voicefi" / ".welcomed"
            marker_file.parent.mkdir(parents=True, exist_ok=True)
            marker_file.write_text(f"welcomed_at={time.time()}\n")

            self._set_status("✅ 14-Day Free Pro Trial Active! Enjoy all features.", is_error=False)

            if self._on_activated_callback:
                try:
                    self._on_activated_callback("trial")
                except Exception:
                    pass
        except Exception as e:
            self._set_status(f"❌ Trial activation error: {e}", is_error=True)

    def _on_test_voice_clicked(self):
        """Speak sample soundbite in background thread."""
        def _speak():
            try:
                from voicefi.tts import get_tts_engine, stop_all_speech
                stop_all_speech()
                engine = get_tts_engine("ava")
                engine.speak_text("Welcome to VoiceFi! Speech synthesis is running smoothly on your Mac.")
            except Exception as e:
                print(f"[Welcome] Voice test error: {e}")

        threading.Thread(target=_speak, daemon=True).start()

    def _open_website(self):
        """Open VoiceFi website in default browser."""
        url = NSURL.URLWithString_("https://voicefi.org")
        NSWorkspace.sharedWorkspace().openURL_(url)

    def _set_status(self, text: str, is_error: bool = False):
        if not self.status_label:
            return
        self.status_label.setStringValue_(text)
        if is_error:
            self.status_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.95, 0.2, 0.2, 1.0))
        else:
            self.status_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.75, 0.35, 1.0))
