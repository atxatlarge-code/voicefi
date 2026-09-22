"""
Native macOS AppKit Welcome & License Activation Window.
Provides first-run onboarding, clipboard license auto-detection, 1-click Pro activation,
macOS system permissions verification (Microphone & Accessibility), interactive
voice loop testing, 14-day free trial start, and instant spoken audio verification.
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
    NSAlert,
    NSAlertStyleInformational,
    NSFloatingWindowLevel,
    NSWindowCollectionBehaviorMoveToActiveSpace,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSBox,
)
from Foundation import NSData
import base64
import webbrowser
import objc
from PyObjCTools import AppHelper

from voicefi.config import load_config, save_config
from voicefi.license import verify_license_key, FeatureGate
from voicefi.redaction import mask_license_key
from voicefi.companion.qr import generate_qr_base64_png, get_companion_urls
from voicefi.companion.server import get_active_tunnel_url, start_cloudflared_tunnel
from voicefi.companion.relay_client import RelaySessionCredentials


def is_headless() -> bool:
    """Check if running in headless testing environment."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("VOICEFI_TESTING") == "1"
    )


def check_accessibility_permission() -> bool:
    """Check if macOS Accessibility trust is granted."""
    try:
        import ApplicationServices

        return bool(ApplicationServices.AXIsProcessTrusted())
    except Exception:
        return False


def check_microphone_permission() -> bool:
    """Check if macOS microphone input stream is accessible."""
    try:
        import sounddevice as sd

        with sd.InputStream(channels=1, samplerate=16000):
            return True
    except Exception:
        return False


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
        self.mic_status_btn: Optional[NSButton] = None
        self.ax_status_btn: Optional[NSButton] = None
        self.key_help_btn: Optional[NSButton] = None
        self.paste_btn: Optional[NSButton] = None
        # Companion Phone Pairing & Tunnel UI
        self.qr_image_view: Optional[NSImageView] = None
        self.qr_url_field: Optional[NSTextField] = None
        self.tunnel_btn: Optional[NSButton] = None
        self.phone_status_label: Optional[NSTextField] = None
        self.copy_qr_btn: Optional[NSButton] = None
        self.open_browser_btn: Optional[NSButton] = None
        self.app_status_badge: Optional[NSTextField] = None
        self.menu_callout_banner: Optional[NSTextField] = None
        self._current_pairing_url: str = ""
        self._poll_active: bool = False
        self._greeting_played = False
        self._targets = []
        self._build_window()

    def _build_window(self):
        if is_headless():
            return

        win_w, win_h = 780.0, 680.0

        # Center on primary active screen
        screen = NSScreen.mainScreen()
        if screen:
            screen_frame = screen.visibleFrame()
            x = screen_frame.origin.x + (screen_frame.size.width - win_w) / 2.0
            y = screen_frame.origin.y + (screen_frame.size.height - win_h) / 2.0
        else:
            x, y = 300.0, 200.0

        frame = NSRect(NSPoint(x, y), NSSize(win_w, win_h))
        style_mask = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
        )

        self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style_mask, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Welcome to VoiceFi")
        self.window.setLevel_(NSFloatingWindowLevel)
        self.window.setCollectionBehavior_(
            NSWindowCollectionBehaviorMoveToActiveSpace | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        self.window.setReleasedWhenClosed_(False)

        content_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(win_w, win_h)))
        self.window.setContentView_(content_view)

        # 1. Top Bar: App Icon & Brand Title
        icon_view = NSImageView.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 70.0), NSSize(52.0, 52.0)))
        icon_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)

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

        title_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(84.0, win_h - 46.0), NSSize(380.0, 26.0)))
        title_label.setStringValue_("Welcome to VoiceFi")
        title_label.setFont_(NSFont.systemFontOfSize_weight_(20.0, NSFontWeightBold))
        title_label.setEditable_(False)
        title_label.setSelectable_(False)
        title_label.setBezeled_(False)
        title_label.setDrawsBackground_(False)
        content_view.addSubview_(title_label)

        sub_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(84.0, win_h - 68.0), NSSize(380.0, 18.0)))
        sub_label.setStringValue_("Universal Voice Layer for AI Agents & macOS")
        sub_label.setFont_(NSFont.systemFontOfSize_weight_(12.0, NSFontWeightMedium))
        sub_label.setTextColor_(NSColor.secondaryLabelColor())
        sub_label.setEditable_(False)
        sub_label.setSelectable_(False)
        sub_label.setBezeled_(False)
        sub_label.setDrawsBackground_(False)
        content_view.addSubview_(sub_label)

        # 2. Live Status Badge (Top Right)
        self.app_status_badge = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(win_w - 274.0, win_h - 48.0), NSSize(250.0, 26.0)))
        self.app_status_badge.setStringValue_("🟢 VoiceFi is Live & Running")
        self.app_status_badge.setFont_(NSFont.systemFontOfSize_weight_(12.5, NSFontWeightBold))
        self.app_status_badge.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.85, 0.4, 1.0))
        self.app_status_badge.setAlignment_(NSTextAlignmentCenter)
        self.app_status_badge.setEditable_(False)
        self.app_status_badge.setSelectable_(False)
        self.app_status_badge.setBezeled_(False)
        self.app_status_badge.setDrawsBackground_(False)
        content_view.addSubview_(self.app_status_badge)

        # 3. macOS Menu Bar Guidance Callout (Top Callout Banner)
        menu_box = NSBox.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 114.0), NSSize(win_w - 48.0, 36.0)))
        menu_box.setBoxType_(4)  # NSBoxCustom
        menu_box.setTitlePosition_(0)  # NSNoTitle
        menu_box.setFillColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.12, 0.18, 0.95))
        menu_box.setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.5, 0.9, 0.5))
        menu_box.setCornerRadius_(10.0)

        self.menu_callout_banner = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(12.0, 7.0), NSSize(win_w - 72.0, 22.0)))
        self.menu_callout_banner.setStringValue_("☝️ Look up at the top right of your macOS Menu Bar for the VoiceFi icon to find the menu, switch voices, or open settings anytime.")
        self.menu_callout_banner.setFont_(NSFont.systemFontOfSize_weight_(12.0, NSFontWeightSemibold))
        self.menu_callout_banner.setTextColor_(NSColor.whiteColor())
        self.menu_callout_banner.setEditable_(False)
        self.menu_callout_banner.setSelectable_(False)
        self.menu_callout_banner.setBezeled_(False)
        self.menu_callout_banner.setDrawsBackground_(False)
        menu_box.addSubview_(self.menu_callout_banner)
        content_view.addSubview_(menu_box)

        # =========================================================================
        # LEFT COLUMN: System Permissions, AI Agents & Pro Activation (w = 360)
        # =========================================================================
        perm_title = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 146.0), NSSize(360.0, 18.0)))
        perm_title.setStringValue_("System Permissions (Local & Private):")
        perm_title.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightSemibold))
        perm_title.setEditable_(False)
        perm_title.setSelectable_(False)
        perm_title.setBezeled_(False)
        perm_title.setDrawsBackground_(False)
        content_view.addSubview_(perm_title)

        self.mic_status_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 180.0), NSSize(175.0, 30.0)))
        self.mic_status_btn.setBezelStyle_(NSBezelStyleRounded)
        self.mic_status_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        mic_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_check_mic_clicked)
        self._targets.append(mic_target)
        self.mic_status_btn.setTarget_(mic_target)
        self.mic_status_btn.setAction_(objc.selector(mic_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(self.mic_status_btn)

        self.ax_status_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(209.0, win_h - 180.0), NSSize(175.0, 30.0)))
        self.ax_status_btn.setBezelStyle_(NSBezelStyleRounded)
        self.ax_status_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        ax_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_check_ax_clicked)
        self._targets.append(ax_target)
        self.ax_status_btn.setTarget_(ax_target)
        self.ax_status_btn.setAction_(objc.selector(ax_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(self.ax_status_btn)

        self._update_permission_badges()

        perm_note = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 204.0), NSSize(360.0, 16.0)))
        perm_note.setStringValue_("Accessibility is used strictly for global hotkeys (Control+T dictation, Esc stop).")
        perm_note.setFont_(NSFont.systemFontOfSize_weight_(10.5, NSFontWeightRegular))
        perm_note.setTextColor_(NSColor.secondaryLabelColor())
        perm_note.setEditable_(False)
        perm_note.setSelectable_(False)
        perm_note.setBezeled_(False)
        perm_note.setDrawsBackground_(False)
        content_view.addSubview_(perm_note)

        eco_box = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 228.0), NSSize(360.0, 20.0)))
        eco_box.setStringValue_("🤖 Antigravity: Ready  •  🟣 Claude Code: Ready")
        eco_box.setFont_(NSFont.systemFontOfSize_weight_(10.5, NSFontWeightSemibold))
        eco_box.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.65, 0.85, 1.0))
        eco_box.setEditable_(False)
        eco_box.setSelectable_(False)
        eco_box.setBezeled_(False)
        eco_box.setDrawsBackground_(False)
        content_view.addSubview_(eco_box)

        self.detected_banner = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 252.0), NSSize(360.0, 20.0)))
        self.detected_banner.setStringValue_("✨ Detected Pro key on clipboard — Ready to activate!")
        self.detected_banner.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightSemibold))
        self.detected_banner.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.75, 0.35, 1.0))
        self.detected_banner.setEditable_(False)
        self.detected_banner.setSelectable_(False)
        self.detected_banner.setBezeled_(False)
        self.detected_banner.setDrawsBackground_(False)
        self.detected_banner.setHidden_(True)
        content_view.addSubview_(self.detected_banner)

        key_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 274.0), NSSize(220.0, 18.0)))
        key_label.setStringValue_("License Key (Pro or Free Trial):")
        key_label.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightSemibold))
        key_label.setTextColor_(NSColor.labelColor())
        key_label.setEditable_(False)
        key_label.setSelectable_(False)
        key_label.setBezeled_(False)
        key_label.setDrawsBackground_(False)
        content_view.addSubview_(key_label)

        self.key_help_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(250.0, win_h - 278.0), NSSize(134.0, 24.0)))
        self.key_help_btn.setTitle_("❓ Where's My Key?")
        self.key_help_btn.setBezelStyle_(NSBezelStyleRounded)
        self.key_help_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        help_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_key_help_clicked)
        self._targets.append(help_target)
        self.key_help_btn.setTarget_(help_target)
        self.key_help_btn.setAction_(objc.selector(help_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(self.key_help_btn)

        self.key_field = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 312.0), NSSize(250.0, 30.0)))
        self.key_field.setFont_(NSFont.userFixedPitchFontOfSize_(12.0))
        self.key_field.setPlaceholderString_("VF1-PRO-...")
        content_view.addSubview_(self.key_field)

        self.paste_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(280.0, win_h - 313.0), NSSize(104.0, 32.0)))
        self.paste_btn.setTitle_("📋 Paste Key")
        self.paste_btn.setBezelStyle_(NSBezelStyleRounded)
        self.paste_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        paste_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_paste_key_clicked)
        self._targets.append(paste_target)
        self.paste_btn.setTarget_(paste_target)
        self.paste_btn.setAction_(objc.selector(paste_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(self.paste_btn)

        key_hint = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 334.0), NSSize(360.0, 16.0)))
        key_hint.setStringValue_("🔑 Emailed upon purchase • Free trial requires no key or card.")
        key_hint.setFont_(NSFont.systemFontOfSize_weight_(10.5, NSFontWeightRegular))
        key_hint.setTextColor_(NSColor.secondaryLabelColor())
        key_hint.setEditable_(False)
        key_hint.setSelectable_(False)
        key_hint.setBezeled_(False)
        key_hint.setDrawsBackground_(False)
        content_view.addSubview_(key_hint)

        act_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 376.0), NSSize(360.0, 36.0)))
        act_btn.setTitle_("⚡ Activate Pro License")
        act_btn.setBezelStyle_(NSBezelStyleRounded)
        act_btn.setFont_(NSFont.systemFontOfSize_weight_(13.0, NSFontWeightBold))
        act_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_activate_clicked)
        self._targets.append(act_target)
        act_btn.setTarget_(act_target)
        act_btn.setAction_(objc.selector(act_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(act_btn)

        self.status_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 402.0), NSSize(360.0, 20.0)))
        self.status_label.setStringValue_("")
        self.status_label.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        self.status_label.setAlignment_(NSTextAlignmentCenter)
        self.status_label.setEditable_(False)
        self.status_label.setSelectable_(False)
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        content_view.addSubview_(self.status_label)

        trial_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 442.0), NSSize(175.0, 34.0)))
        trial_btn.setTitle_("✨ Start 14-Day Free Trial")
        trial_btn.setBezelStyle_(NSBezelStyleRounded)
        trial_btn.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightSemibold))
        trial_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_trial_clicked)
        self._targets.append(trial_target)
        trial_btn.setTarget_(trial_target)
        trial_btn.setAction_(objc.selector(trial_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(trial_btn)

        test_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(209.0, win_h - 442.0), NSSize(175.0, 34.0)))
        test_btn.setTitle_("🔊 Test Voice (0ms Speech)")
        test_btn.setBezelStyle_(NSBezelStyleRounded)
        test_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        test_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_test_voice_clicked)
        self._targets.append(test_target)
        test_btn.setTarget_(test_target)
        test_btn.setAction_(objc.selector(test_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(test_btn)

        practice_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 482.0), NSSize(360.0, 32.0)))
        practice_btn.setTitle_("🎙️ Test Audio Loopback (Dictation Check)")
        practice_btn.setBezelStyle_(NSBezelStyleRounded)
        practice_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        practice_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_practice_clicked)
        self._targets.append(practice_target)
        practice_btn.setTarget_(practice_target)
        practice_btn.setAction_(objc.selector(practice_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(practice_btn)

        hotkey_strip = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, win_h - 510.0), NSSize(360.0, 18.0)))
        hotkey_strip.setStringValue_("⌨️ Universal Hotkeys: ⌃T to speak  •  ⎋ to stop  •  ⇥ to focus")
        hotkey_strip.setFont_(NSFont.systemFontOfSize_weight_(10.5, NSFontWeightSemibold))
        hotkey_strip.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.65, 0.85, 1.0))
        hotkey_strip.setAlignment_(NSTextAlignmentCenter)
        hotkey_strip.setEditable_(False)
        hotkey_strip.setSelectable_(False)
        hotkey_strip.setBezeled_(False)
        hotkey_strip.setDrawsBackground_(False)
        content_view.addSubview_(hotkey_strip)

        # =========================================================================
        # RIGHT COLUMN: Instant Phone Companion & Companion Tunnel QR (w = 352)
        # =========================================================================
        card = NSBox.alloc().initWithFrame_(NSRect(NSPoint(404.0, 48.0), NSSize(352.0, win_h - 170.0)))
        card.setBoxType_(4)  # NSBoxCustom
        card.setTitlePosition_(0)  # NSNoTitle
        card.setFillColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.08, 0.12, 0.95))
        card.setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.26, 0.35, 0.8))
        card.setCornerRadius_(16.0)

        card_title = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(16.0, 474.0), NSSize(320.0, 24.0)))
        card_title.setStringValue_("📱 Connect Your Phone in Seconds")
        card_title.setFont_(NSFont.systemFontOfSize_weight_(13.5, NSFontWeightBold))
        card_title.setEditable_(False)
        card_title.setSelectable_(False)
        card_title.setBezeled_(False)
        card_title.setDrawsBackground_(False)
        card.addSubview_(card_title)

        card_sub = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(16.0, 436.0), NSSize(320.0, 32.0)))
        card_sub.setStringValue_("Scan with your iPhone or Android camera to connect hands-free voice to your Mac:")
        card_sub.setFont_(NSFont.systemFontOfSize_weight_(10.5, NSFontWeightRegular))
        card_sub.setTextColor_(NSColor.secondaryLabelColor())
        card_sub.setEditable_(False)
        card_sub.setSelectable_(False)
        card_sub.setBezeled_(False)
        card_sub.setDrawsBackground_(False)
        card.addSubview_(card_sub)

        # Crisp White Container for High-Contrast QR Code
        qr_box = NSBox.alloc().initWithFrame_(NSRect(NSPoint(76.0, 226.0), NSSize(200.0, 200.0)))
        qr_box.setBoxType_(4)  # NSBoxCustom
        qr_box.setTitlePosition_(0)  # NSNoTitle
        qr_box.setFillColor_(NSColor.whiteColor())
        qr_box.setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.3, 0.35, 1.0))
        qr_box.setCornerRadius_(14.0)

        self.qr_image_view = NSImageView.alloc().initWithFrame_(NSRect(NSPoint(6.0, 6.0), NSSize(188.0, 188.0)))
        self.qr_image_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        qr_box.addSubview_(self.qr_image_view)
        card.addSubview_(qr_box)

        # Tunnel Status & Restart/Start Button
        self.tunnel_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(16.0, 186.0), NSSize(320.0, 32.0)))
        self.tunnel_btn.setTitle_("🌐 Companion Tunnel: Active (HTTPS) ✅")
        self.tunnel_btn.setBezelStyle_(NSBezelStyleRounded)
        self.tunnel_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightSemibold))
        tunnel_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_start_tunnel_clicked)
        self._targets.append(tunnel_target)
        self.tunnel_btn.setTarget_(tunnel_target)
        self.tunnel_btn.setAction_(objc.selector(tunnel_target.buttonClicked_, signature=b"v@:@"))
        card.addSubview_(self.tunnel_btn)

        # URL text field & Copy button
        self.qr_url_field = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(16.0, 150.0), NSSize(232.0, 28.0)))
        self.qr_url_field.setFont_(NSFont.userFixedPitchFontOfSize_(10.5))
        self.qr_url_field.setStringValue_("Loading...")
        self.qr_url_field.setEditable_(False)
        self.qr_url_field.setSelectable_(True)
        card.addSubview_(self.qr_url_field)

        self.copy_qr_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(254.0, 150.0), NSSize(82.0, 30.0)))
        self.copy_qr_btn.setTitle_("📋 Copy")
        self.copy_qr_btn.setBezelStyle_(NSBezelStyleRounded)
        self.copy_qr_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        copy_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_copy_link_clicked)
        self._targets.append(copy_target)
        self.copy_qr_btn.setTarget_(copy_target)
        self.copy_qr_btn.setAction_(objc.selector(copy_target.buttonClicked_, signature=b"v@:@"))
        card.addSubview_(self.copy_qr_btn)

        # Live Phone Connection Status Label
        self.phone_status_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(16.0, 118.0), NSSize(320.0, 22.0)))
        self.phone_status_label.setStringValue_("⏳ Waiting for phone camera scan...")
        self.phone_status_label.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightSemibold))
        self.phone_status_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.7, 0.2, 1.0))
        self.phone_status_label.setAlignment_(NSTextAlignmentCenter)
        self.phone_status_label.setEditable_(False)
        self.phone_status_label.setSelectable_(False)
        self.phone_status_label.setBezeled_(False)
        self.phone_status_label.setDrawsBackground_(False)
        card.addSubview_(self.phone_status_label)

        # Open in Mac Browser Button
        self.open_browser_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(16.0, 78.0), NSSize(320.0, 32.0)))
        self.open_browser_btn.setTitle_("🖥️ Open Companion in Mac Browser ↗")
        self.open_browser_btn.setBezelStyle_(NSBezelStyleRounded)
        self.open_browser_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        open_target = WelcomeActionTarget.alloc().initWithCallback_(self._on_open_browser_clicked)
        self._targets.append(open_target)
        self.open_browser_btn.setTarget_(open_target)
        self.open_browser_btn.setAction_(objc.selector(open_target.buttonClicked_, signature=b"v@:@"))
        card.addSubview_(self.open_browser_btn)

        tip_label = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(16.0, 24.0), NSSize(320.0, 44.0)))
        tip_label.setStringValue_("💡 Tip: After opening on your phone, tap \"Share → Add to Home Screen\" to run as a full-screen standalone app.")
        tip_label.setFont_(NSFont.systemFontOfSize_weight_(10.0, NSFontWeightRegular))
        tip_label.setTextColor_(NSColor.secondaryLabelColor())
        tip_label.setAlignment_(NSTextAlignmentCenter)
        tip_label.setEditable_(False)
        tip_label.setSelectable_(False)
        tip_label.setBezeled_(False)
        tip_label.setDrawsBackground_(False)
        card.addSubview_(tip_label)

        content_view.addSubview_(card)

        # =========================================================================
        # BOTTOM STRIP: Local Privacy & Website Link
        # =========================================================================
        footer_note = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(24.0, 16.0), NSSize(420.0, 22.0)))
        footer_note.setStringValue_("🎙️ VoiceFi runs locally on your Mac • Press Control+T in any app to speak.")
        footer_note.setFont_(NSFont.systemFontOfSize_weight_(10.5, NSFontWeightMedium))
        footer_note.setTextColor_(NSColor.secondaryLabelColor())
        footer_note.setEditable_(False)
        footer_note.setSelectable_(False)
        footer_note.setBezeled_(False)
        footer_note.setDrawsBackground_(False)
        content_view.addSubview_(footer_note)

        get_btn = NSButton.alloc().initWithFrame_(NSRect(NSPoint(win_w - 290.0, 14.0), NSSize(266.0, 26.0)))
        get_btn.setTitle_("Get a License Key on VoiceFi.org ➔")
        get_btn.setBezelStyle_(NSBezelStyleRounded)
        get_btn.setFont_(NSFont.systemFontOfSize_weight_(11.0, NSFontWeightMedium))
        get_target = WelcomeActionTarget.alloc().initWithCallback_(self._open_website)
        self._targets.append(get_target)
        get_btn.setTarget_(get_target)
        get_btn.setAction_(objc.selector(get_target.buttonClicked_, signature=b"v@:@"))
        content_view.addSubview_(get_btn)

    def _update_permission_badges(self):

        """Update Microphone and Accessibility permission badge buttons."""
        if self.mic_status_btn:
            mic_ok = check_microphone_permission()
            if mic_ok:
                self.mic_status_btn.setTitle_("🎙️ Mic Access: Granted ✅")
            else:
                self.mic_status_btn.setTitle_("🎙️ Mic Access: Allow ➔")

        if self.ax_status_btn:
            ax_ok = check_accessibility_permission()
            if ax_ok:
                self.ax_status_btn.setTitle_("⌨️ Hotkeys: Granted ✅")
            else:
                self.ax_status_btn.setTitle_("⌨️ Hotkeys: Allow in Settings ➔")

    def show(self):
        """Show the window and inspect clipboard for license keys."""
        if is_headless():
            return

        if threading.current_thread() is not threading.main_thread():
            try:
                AppHelper.callAfter(self.show)
            except Exception:
                pass
            return

        if not self.window:
            self._build_window()

        if not self.window:
            return

        # Refresh permission status
        self._update_permission_badges()

        # Check clipboard for existing key
        self._inspect_clipboard()

        # Check current tier to update fields
        config = load_config()
        if getattr(config, "license_key", ""):
            self.key_field.setStringValue_(mask_license_key(config.license_key))
            self.status_label.setStringValue_(f"⚡ Pro Active ({getattr(config, 'tier', 'pro').upper()})")
            self.status_label.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.75, 0.35, 1.0))

        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        # Initialize Companion QR code and auto-start tunnel for instant phone pairing
        self._init_companion_tunnel_and_qr()

        # Spoken audio greeting once on first run
        if not self._greeting_played:
            self._greeting_played = True
            def _greet():
                try:
                    time.sleep(0.4)
                    from voicefi.tts import get_tts_engine
                    engine = get_tts_engine("ava")
                    engine.speak_text("Welcome to VoiceFi! Your voice layer is ready.")
                except Exception:
                    pass
            threading.Thread(target=_greet, daemon=True).start()

        try:
            from voicefi.telemetry import capture_event

            capture_event("welcome_window_opened")
        except Exception:
            pass

    def hide(self):
        self._poll_active = False
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

    def _on_key_help_clicked(self):
        """Show informative dialog explaining where to find or recover the license key."""
        try:
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Where is My VoiceFi License Key?")
            alert.setInformativeText_(
                "1. Polar Receipt Email:\n"
                "If you purchased VoiceFi Pro, your cryptographic key was emailed to you immediately "
                "from Polar (notifications@polar.sh) and VoiceFi (talktome@voicefi.org) with the subject 'Your VoiceFi Pro License'.\n\n"
                "2. 1-Click Clipboard Detection:\n"
                "Copy the key (starts with 'VF1-PRO-') from your email or browser receipt, and VoiceFi will automatically detect and paste it here.\n\n"
                "3. 14-Day Free Trial (No Key Needed):\n"
                "If you're testing VoiceFi for the first time, you do NOT need a key! Simply click 'Start 14-Day Free Trial' to unlock 100% of Pro features with zero payment.\n\n"
                "4. Lost Your Key?\n"
                "Visit the Polar Customer Portal (polar.sh/purchases) with your checkout email or email support@voicefi.org to recover it instantly."
            )
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.addButtonWithTitle_("Open Polar Portal ➔")
            alert.addButtonWithTitle_("Contact Support ✉️")
            alert.addButtonWithTitle_("Got It")

            resp = alert.runModal()
            if resp == 1000:  # First button: Open Polar Portal
                url = NSURL.URLWithString_("https://polar.sh/purchases")
                NSWorkspace.sharedWorkspace().openURL_(url)
            elif resp == 1001:  # Second button: Support
                url = NSURL.URLWithString_("mailto:support@voicefi.org?subject=VoiceFi%20License%20Key%20Recovery")
                NSWorkspace.sharedWorkspace().openURL_(url)
        except Exception as e:
            self._set_status("ℹ️ Check your email from notifications@polar.sh for key.", is_error=False)

    def _on_paste_key_clicked(self):
        """Read macOS pasteboard and paste directly into the license key input field."""
        try:
            pb = NSPasteboard.generalPasteboard()
            clip_str = pb.stringForType_(NSPasteboardTypeString)
            if clip_str:
                clip_clean = clip_str.strip()
                if self.key_field:
                    self.key_field.setStringValue_(clip_clean)
                if clip_clean.startswith("VF1-"):
                    self._set_status("📋 Key pasted from clipboard! Click 'Activate Pro License'.", is_error=False)
                    if self.detected_banner:
                        self.detected_banner.setHidden_(False)
                else:
                    self._set_status("📋 Pasted text from clipboard. Ensure format begins with VF1-PRO-...", is_error=False)
                return
        except Exception as e:
            self._set_status(f"⚠️ Clipboard error: {e}", is_error=True)
            return
        self._set_status("⚠️ Clipboard is empty or contains non-text content.", is_error=True)

    def _on_check_mic_clicked(self):
        """Prompt or check microphone permission."""
        mic_ok = check_microphone_permission()
        if mic_ok:
            self._set_status("✅ Microphone is working smoothly!", is_error=False)
        else:
            self._set_status("🎙️ Opening microphone stream to prompt access...", is_error=False)
            try:
                import sounddevice as sd
                with sd.InputStream(channels=1, samplerate=16000):
                    pass
            except Exception as e:
                self._set_status(f"⚠️ Microphone access notice: {e}", is_error=True)
        self._update_permission_badges()

    def _on_check_ax_clicked(self):
        """Prompt or check accessibility permission."""
        ax_ok = check_accessibility_permission()
        if ax_ok:
            self._set_status("✅ Accessibility hotkeys (<Ctrl>+T, <Esc>) are active!", is_error=False)
        else:
            self._set_status("👉 Opening System Settings... Please toggle VoiceFi to ON.", is_error=False)
            try:
                from voicefi.integrations.injector import open_accessibility_settings

                open_accessibility_settings()
            except Exception:
                pass
        self._update_permission_badges()

    def _on_activate_clicked(self):
        """Handle License Activation."""
        raw_key = self.key_field.stringValue().strip() if self.key_field else ""
        if not raw_key:
            self._set_status("⚠️ Please enter a license key.", is_error=True)
            return

        # If key field contains mask bullets and config is already valid, confirm active
        if "•" in raw_key:
            config = load_config()
            if getattr(config, "license_key", "") and FeatureGate.is_pro(config):
                self._set_status("✅ Pro license is already active!", is_error=False)
                return

        res = FeatureGate.activate_license(raw_key)
        if not res.get("success"):
            err = res.get("error") or "Invalid license key signature."
            self._set_status(f"❌ {err}", is_error=True)
            return

        # Immediately mask the key in the field so it is not visible on screen
        if self.key_field:
            self.key_field.setStringValue_(mask_license_key(raw_key))

        # Mark welcomed marker
        try:
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

            # Play success chime
            try:
                from voicefi.audio.chimes import play_chime
                play_chime("success")
            except Exception:
                pass

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

    def _on_practice_clicked(self):
        """Run quick audio loopback verification."""
        self._set_status("🎙️ Recording 2 seconds... speak aloud into your mic!", is_error=False)

        def _run_test():
            try:
                from voicefi.audio.recorder import AudioRecorder
                from voicefi.stt import get_stt_engine

                cfg = load_config()
                rec = AudioRecorder(sample_rate=16000, energy_threshold=0.015, silence_duration=1.0)
                audio, wav_path = rec.record_fixed_seconds(seconds=2.0)
                if wav_path and wav_path.is_file():
                    stt = get_stt_engine(cfg)
                    txt = stt.transcribe(wav_path).strip()
                    wav_path.unlink(missing_ok=True)
                    feedback = f'✅ Transcribed: "{txt}"' if txt else "✅ Audio captured cleanly!"
                    def _update_ui():
                        self._set_status(feedback, is_error=False)
                    AppHelper.callAfter(_update_ui)
            except Exception as e:
                def _err_ui():
                    self._set_status(f"⚠️ Audio test notice: {e}", is_error=True)
                AppHelper.callAfter(_err_ui)

        threading.Thread(target=_run_test, daemon=True).start()

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

    def _create_nsimage_from_url(self, url: str) -> Optional[NSImage]:
        """Generate high-contrast QR code NSImage from URL."""
        try:
            b64_str = generate_qr_base64_png(url)
            if b64_str.startswith("data:image/png;base64,"):
                raw_data = base64.b64decode(b64_str.split(",", 1)[1])
                nsdata = NSData.dataWithBytes_length_(raw_data, len(raw_data))
                img = NSImage.alloc().initWithData_(nsdata)
                if img and img.isValid():
                    return img
        except Exception as e:
            print(f"[WelcomeWindow] QR image generation error: {e}")
        return None

    def _on_start_tunnel_clicked(self):
        """Start or refresh Cloudflare Tunnel in background."""
        if self.tunnel_btn:
            self.tunnel_btn.setTitle_("⏳ Starting Cloudflare Tunnel...")
            self.tunnel_btn.setEnabled_(False)

        def _worker():
            tunnel_url = None
            try:
                tunnel_url = start_cloudflared_tunnel(port=5141)
            except Exception as e:
                print(f"[WelcomeWindow] Tunnel start error: {e}")

            if tunnel_url:
                def _update_ui():
                    self._current_pairing_url = tunnel_url
                    if self.qr_url_field:
                        self.qr_url_field.setStringValue_(tunnel_url)
                    if self.qr_image_view:
                        img = self._create_nsimage_from_url(tunnel_url)
                        if img:
                            self.qr_image_view.setImage_(img)
                    if self.tunnel_btn:
                        self.tunnel_btn.setTitle_("🟢 Companion Tunnel: Active (HTTPS) ✅")
                        self.tunnel_btn.setEnabled_(True)
                    if self.phone_status_label and not "Connected" in (self.phone_status_label.stringValue() or ""):
                        self.phone_status_label.setStringValue_("📱 Point phone camera at QR code...")
                AppHelper.callAfter(_update_ui)
            else:
                def _fail_ui():
                    if self.tunnel_btn:
                        self.tunnel_btn.setTitle_("🌐 Start Cloudflare Tunnel (Click to Retry)")
                        self.tunnel_btn.setEnabled_(True)
                AppHelper.callAfter(_fail_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_copy_link_clicked(self):
        """Copy pairing URL to macOS pasteboard."""
        url = self._current_pairing_url or (self.qr_url_field.stringValue() if self.qr_url_field else "")
        if url:
            try:
                pb = NSPasteboard.generalPasteboard()
                pb.clearContents()
                pb.setString_forType_(url, NSPasteboardTypeString)
                if self.copy_qr_btn:
                    self.copy_qr_btn.setTitle_("Copied! ✅")
                    def _reset():
                        time.sleep(2.0)
                        def _set_back():
                            if self.copy_qr_btn:
                                self.copy_qr_btn.setTitle_("📋 Copy")
                        AppHelper.callAfter(_set_back)
                    threading.Thread(target=_reset, daemon=True).start()
            except Exception as e:
                print(f"[WelcomeWindow] Copy link error: {e}")

    def _on_open_browser_clicked(self):
        """Open companion in default macOS browser."""
        url = self._current_pairing_url or "http://localhost:5141/companion"
        try:
            webbrowser.open(url)
        except Exception:
            pass

    def _init_companion_tunnel_and_qr(self):
        """Initialize companion tunnel and render live QR code."""
        # 1. Immediate initial QR presentation (0ms)
        active_tunnel = get_active_tunnel_url()
        cloud_url = ""
        try:
            creds = RelaySessionCredentials.load_or_create()
            cloud_url = creds.get_pairing_url("https://companion.voicefi.app")
        except Exception:
            pass

        preferred = active_tunnel or cloud_url or "http://localhost:5141/companion"
        self._current_pairing_url = preferred

        if self.qr_url_field:
            self.qr_url_field.setStringValue_(preferred)

        if self.qr_image_view:
            img = self._create_nsimage_from_url(preferred)
            if img:
                self.qr_image_view.setImage_(img)

        if active_tunnel and self.tunnel_btn:
            self.tunnel_btn.setTitle_("🟢 Companion Tunnel: Active (HTTPS) ✅")
        else:
            # Auto-start Cloudflare tunnel in background so QR code upgrades to HTTPS in seconds
            self._on_start_tunnel_clicked()

        # 2. Start background status polling for phone connection
        if not self._poll_active:
            self._poll_active = True
            def _poll_phone_connection():
                import urllib.request
                import json
                while self._poll_active:
                    try:
                        req = urllib.request.Request(
                            "http://127.0.0.1:5141/api/status",
                            headers={"User-Agent": "VoiceFi-Welcome"}
                        )
                        with urllib.request.urlopen(req, timeout=1.5) as resp:
                            if resp.status == 200:
                                data = json.loads(resp.read().decode("utf-8"))
                                connected = (
                                    data.get("connected_clients", 0) > 0
                                    or data.get("has_relay_peer", False)
                                    or data.get("total_connected_devices", 0) > 0
                                )
                                if connected:
                                    def _phone_connected():
                                        if self.phone_status_label:
                                            self.phone_status_label.setStringValue_("🎉 Phone Connected! (Hands-Free Voice Active)")
                                            self.phone_status_label.setTextColor_(
                                                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.85, 0.4, 1.0)
                                            )
                                    AppHelper.callAfter(_phone_connected)
                                    break
                    except Exception:
                        pass
                    time.sleep(2.5)
            threading.Thread(target=_poll_phone_connection, daemon=True).start()
