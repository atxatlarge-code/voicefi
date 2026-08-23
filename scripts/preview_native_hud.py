import time
import os
import subprocess
from pathlib import Path
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
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSScreen,
    NSView,
    NSVisualEffectView,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectBlendingModeBehindWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSRunLoop,
    NSDate,
)

NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)

class NativeHUDPreview:
    def __init__(self):
        screen = NSScreen.mainScreen()
        self.screen_frame = screen.frame() if screen else NSRect(NSPoint(0, 0), NSSize(1440, 900))
        self.visible_frame = screen.visibleFrame() if screen else NSRect(NSPoint(0, 0), NSSize(1440, 875))
        
        # Build base panel
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSRect(NSPoint(500, 800), NSSize(480, 80)),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setLevel_(NSFloatingWindowLevel + 15)
        self.panel.setFloatingPanel_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        # Root container view
        self.root_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(480, 80)))
        self.root_view.setWantsLayer_(True)
        self.root_view.layer().setCornerRadius_(20.0)
        self.root_view.layer().setMasksToBounds_(True)
        
        # Frosted glass blur
        self.effect_view = NSVisualEffectView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(480, 80)))
        self.effect_view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        self.effect_view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        self.effect_view.setState_(1)
        self.effect_view.setWantsLayer_(True)
        self.effect_view.layer().setCornerRadius_(20.0)
        self.root_view.addSubview_(self.effect_view)

        # Avatar badge
        self.avatar_box = NSView.alloc().initWithFrame_(NSRect(NSPoint(14, 38), NSSize(30, 30)))
        self.avatar_box.setWantsLayer_(True)
        self.avatar_box.layer().setCornerRadius_(15.0)
        self.avatar_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(0, 2), NSSize(30, 26)))
        self.avatar_lbl.setFont_(NSFont.systemFontOfSize_(16))
        self.avatar_lbl.setAlignment_(1)
        self.avatar_lbl.setBezeled_(False)
        self.avatar_lbl.setDrawsBackground_(False)
        self.avatar_box.addSubview_(self.avatar_lbl)
        self.root_view.addSubview_(self.avatar_box)

        # Title / Agent Header
        self.title_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(54, 46), NSSize(160, 20)))
        self.title_lbl.setFont_(NSFont.boldSystemFontOfSize_(13))
        self.title_lbl.setTextColor_(NSColor.whiteColor())
        self.title_lbl.setBezeled_(False)
        self.title_lbl.setDrawsBackground_(False)
        self.root_view.addSubview_(self.title_lbl)

        # Status Subtitle Tag
        self.tag_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(200, 46), NSSize(260, 20)))
        self.tag_lbl.setFont_(NSFont.systemFontOfSize_(11))
        self.tag_lbl.setBezeled_(False)
        self.tag_lbl.setDrawsBackground_(False)
        self.root_view.addSubview_(self.tag_lbl)

        # Content Text Body
        self.body_lbl = NSTextField.alloc().initWithFrame_(NSRect(NSPoint(14, 10), NSSize(450, 26)))
        self.body_lbl.setFont_(NSFont.systemFontOfSize_(12))
        self.body_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.92, 0.96, 0.95))
        self.body_lbl.setBezeled_(False)
        self.body_lbl.setDrawsBackground_(False)
        self.root_view.addSubview_(self.body_lbl)

        self.panel.setContentView_(self.root_view)

    def set_state(self, state: str, agent: str = "Antigravity", persona: str = "Christopher", text: str = ""):
        if state == "idle":
            w, h = 170, 36
            self.root_view.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.14, 0.92).CGColor())
            self.root_view.layer().setBorderWidth_(1.0)
            self.root_view.layer().setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.45, 0.55, 0.35).CGColor())
            
            self.avatar_box.setFrame_(NSRect(NSPoint(8, 6), NSSize(24, 24)))
            self.avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.25, 0.35, 0.6).CGColor())
            self.avatar_lbl.setStringValue_("🎙️")
            self.avatar_lbl.setFont_(NSFont.systemFontOfSize_(12))
            
            self.title_lbl.setFrame_(NSRect(NSPoint(38, 8), NSSize(120, 20)))
            self.title_lbl.setStringValue_("VoiceFi  Ready")
            self.title_lbl.setFont_(NSFont.boldSystemFontOfSize_(12))
            self.tag_lbl.setStringValue_("")
            self.body_lbl.setStringValue_("")
        elif state == "thinking":
            w, h = 380, 48
            self.root_view.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.12, 0.08, 0.22, 0.94).CGColor())
            self.root_view.layer().setBorderWidth_(1.5)
            self.root_view.layer().setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.65, 0.45, 0.98, 0.75).CGColor())
            
            self.avatar_box.setFrame_(NSRect(NSPoint(10, 10), NSSize(28, 28)))
            self.avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.35, 0.2, 0.55, 0.8).CGColor())
            self.avatar_lbl.setStringValue_("🧠")
            self.avatar_lbl.setFont_(NSFont.systemFontOfSize_(15))
            
            self.title_lbl.setFrame_(NSRect(NSPoint(46, 24), NSSize(140, 18)))
            self.title_lbl.setStringValue_(agent)
            self.title_lbl.setFont_(NSFont.boldSystemFontOfSize_(12))
            
            self.tag_lbl.setFrame_(NSRect(NSPoint(180, 24), NSSize(180, 18)))
            self.tag_lbl.setStringValue_("• Thinking...")
            self.tag_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.8, 0.65, 1.0, 0.9))
            
            self.body_lbl.setFrame_(NSRect(NSPoint(46, 6), NSSize(320, 18)))
            self.body_lbl.setStringValue_("Analyzing codebase architecture & plan...")
            self.body_lbl.setFont_(NSFont.systemFontOfSize_(11))
        elif state == "working":
            w, h = 400, 48
            self.root_view.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.12, 0.22, 0.94).CGColor())
            self.root_view.layer().setBorderWidth_(1.5)
            self.root_view.layer().setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.6, 1.0, 0.8).CGColor())
            
            self.avatar_box.setFrame_(NSRect(NSPoint(10, 10), NSSize(28, 28)))
            self.avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.35, 0.65, 0.8).CGColor())
            self.avatar_lbl.setStringValue_("⚡")
            self.avatar_lbl.setFont_(NSFont.systemFontOfSize_(15))
            
            self.title_lbl.setFrame_(NSRect(NSPoint(46, 24), NSSize(140, 18)))
            self.title_lbl.setStringValue_(agent)
            self.title_lbl.setFont_(NSFont.boldSystemFontOfSize_(12))
            
            self.tag_lbl.setFrame_(NSRect(NSPoint(180, 24), NSSize(200, 18)))
            self.tag_lbl.setStringValue_("• Running Tool")
            self.tag_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.5, 0.8, 1.0, 0.9))
            
            self.body_lbl.setFrame_(NSRect(NSPoint(46, 6), NSSize(340, 18)))
            self.body_lbl.setStringValue_("Executing: pytest tests/ -v (150 passed)")
            self.body_lbl.setFont_(NSFont.systemFontOfSize_(11))
        elif state == "speaking":
            w, h = 480, 80
            self.root_view.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.05, 0.14, 0.18, 0.95).CGColor())
            self.root_view.layer().setBorderWidth_(1.5)
            self.root_view.layer().setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.15, 0.85, 0.95, 0.8).CGColor())
            
            self.avatar_box.setFrame_(NSRect(NSPoint(14, 40), NSSize(28, 28)))
            self.avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.4, 0.5, 0.8).CGColor())
            self.avatar_lbl.setStringValue_("🧔")
            self.avatar_lbl.setFont_(NSFont.systemFontOfSize_(15))
            
            self.title_lbl.setFrame_(NSRect(NSPoint(50, 46), NSSize(120, 20)))
            self.title_lbl.setStringValue_(agent)
            self.title_lbl.setFont_(NSFont.boldSystemFontOfSize_(12.5))
            
            self.tag_lbl.setFrame_(NSRect(NSPoint(160, 46), NSSize(300, 20)))
            self.tag_lbl.setStringValue_(f"• {persona} 🔊 [Speaking]")
            self.tag_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.3, 0.9, 1.0, 0.9))
            
            self.body_lbl.setFrame_(NSRect(NSPoint(14, 10), NSSize(450, 30)))
            self.body_lbl.setStringValue_(text or "Hey Jake! I have verified all 150 test suites across VoiceFi.")
            self.body_lbl.setFont_(NSFont.systemFontOfSize_(12))
        elif state == "listening":
            w, h = 420, 64
            self.root_view.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.04, 0.16, 0.10, 0.95).CGColor())
            self.root_view.layer().setBorderWidth_(1.5)
            self.root_view.layer().setBorderColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.2, 0.9, 0.5, 0.85).CGColor())
            
            self.avatar_box.setFrame_(NSRect(NSPoint(14, 26), NSSize(28, 28)))
            self.avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.45, 0.25, 0.8).CGColor())
            self.avatar_lbl.setStringValue_("🎙️")
            self.avatar_lbl.setFont_(NSFont.systemFontOfSize_(15))
            
            self.title_lbl.setFrame_(NSRect(NSPoint(50, 32), NSSize(160, 20)))
            self.title_lbl.setStringValue_("Listening to Jake")
            self.title_lbl.setFont_(NSFont.boldSystemFontOfSize_(12.5))
            
            self.tag_lbl.setFrame_(NSRect(NSPoint(180, 32), NSSize(220, 20)))
            self.tag_lbl.setStringValue_("🟢 Active Microphone")
            self.tag_lbl.setTextColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.4, 0.95, 0.6, 0.95))
            
            self.body_lbl.setFrame_(NSRect(NSPoint(14, 6), NSSize(390, 22)))
            self.body_lbl.setStringValue_(text or '"Yeah, proceed with the unified Dynamic Island implementation..."')
            self.body_lbl.setFont_(NSFont.systemFontOfSize_(11.5))

        # Position top-center beneath camera notch
        x = self.visible_frame.origin.x + (self.visible_frame.size.width - w) / 2.0
        y = self.visible_frame.origin.y + self.visible_frame.size.height - h - 6.0
        
        self.panel.setFrame_display_(NSRect(NSPoint(x, y), NSSize(w, h)), True)
        self.root_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(w, h)))
        self.effect_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(w, h)))
        self.panel.orderFrontRegardless()

    def capture_screenshot(self, out_path: str):
        frame = self.panel.frame()
        # Convert Cocoa coordinates (bottom-left) to screencapture rect (top-left)
        screen_h = self.screen_frame.size.height
        sc_x = int(frame.origin.x) - 10
        sc_y = int(screen_h - (frame.origin.y + frame.size.height)) - 10
        sc_w = int(frame.size.width) + 20
        sc_h = int(frame.size.height) + 20
        rect_str = f"{sc_x},{sc_y},{sc_w},{sc_h}"
        cmd = ["screencapture", "-x", "-R", rect_str, out_path]
        subprocess.run(cmd)

preview = NativeHUDPreview()
artifact_dir = Path(__file__).resolve().parent.parent / "assets" / "screenshots"
artifact_dir.mkdir(parents=True, exist_ok=True)

# Render and capture all 5 states
states = [
    ("idle", "VoiceFi", "", ""),
    ("thinking", "Antigravity", "Christopher", ""),
    ("working", "Antigravity", "Christopher", ""),
    ("speaking", "Antigravity", "Christopher", "Hey Jake! I have verified all 150 test suites across VoiceFi."),
    ("listening", "Jake", "", "Yeah, proceed with the unified Dynamic Island implementation..."),
]

for s, agent, persona, txt in states:
    preview.set_state(s, agent=agent, persona=persona, text=txt)
    # Pump Cocoa run loop
    for _ in range(10):
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.03))
    out_file = artifact_dir / f"native_hud_{s}.png"
    preview.capture_screenshot(str(out_file))
    print(f"Captured real native HUD for state: {s} -> {out_file.name}")

preview.panel.orderOut_(None)
print("Finished capturing all 5 real native HUD screenshots.")
