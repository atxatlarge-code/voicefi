import os
import sys
from pathlib import Path
import AppKit
from AppKit import (
    NSApplication,
    NSRunLoop,
    NSDate,
    NSBitmapImageFileTypePNG,
    NSImage,
    NSRect,
    NSPoint,
    NSSize,
)

# Ensure src is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD


def pump_runloop(seconds=0.15):
    loop = NSRunLoop.currentRunLoop()
    end_date = NSDate.dateWithTimeIntervalSinceNow_(seconds)
    while NSDate.date().compare_(end_date) < 0:
        loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.02))


def capture_view(view, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bounds = view.bounds()
    rep = view.bitmapImageRepForCachingDisplayInRect_(bounds)
    view.cacheDisplayInRect_toBitmapImageRep_(bounds, rep)
    png_data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    if png_data:
        png_data.writeToFile_atomically_(str(output_path), True)
        print(f"Captured: {output_path} ({int(bounds.size.width)}x{int(bounds.size.height)})")
    else:
        print(f"Failed to capture: {output_path}")


def capture_nsimage(ns_img, output_path, width=256, height=256):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    target_img = NSImage.alloc().initWithSize_(NSSize(width, height))
    target_img.lockFocus()
    ns_img.drawInRect_fromRect_operation_fraction_(
        NSRect(NSPoint(0, 0), NSSize(width, height)),
        NSRect(NSPoint(0, 0), ns_img.size()),
        AppKit.NSCompositingOperationCopy,
        1.0,
    )
    rep = AppKit.NSBitmapImageRep.alloc().initWithFocusedViewRect_(
        NSRect(NSPoint(0, 0), NSSize(width, height))
    )
    target_img.unlockFocus()

    png_data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    if png_data:
        png_data.writeToFile_atomically_(str(output_path), True)
        print(f"Captured Icon: {output_path} ({width}x{height})")


def main():
    app = NSApplication.sharedApplication()
    hud = UnifiedDynamicIslandHUD.get_instance()

    output_dir = Path(__file__).parent.parent / "assets" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)

    states_to_capture = [
        ("idle", lambda: hud.set_idle()),
        (
            "thinking",
            lambda: hud.set_thinking(
                agent_name="Antigravity", detail="Reasoning over AST & planning architecture..."
            ),
        ),
        (
            "working",
            lambda: hud.set_working(
                agent_name="Antigravity", tool_action="Executing: pytest tests/ -v (Passed 210/210)"
            ),
        ),
        (
            "speaking",
            lambda: hud.set_speaking(
                text="All 12 unit tests passed. Ready to deploy. Staging on Railway now...",
                agent_name="Antigravity",
                persona_name="Viv",
            ),
        ),
        ("listening", lambda: hud.set_listening(prompt_preview="", user_name="Jake")),
        (
            "listening_stream",
            lambda: hud.set_listening(
                prompt_preview="Fix the expired token bug in auth_service.py",
                user_name="Jake",
                live_stream=True,
            ),
        ),
        (
            "new_conversation",
            lambda: hud.set_new_conversation(
                prompt_preview="Start a new session with Google Search and MCP tools",
                user_name="Jake",
                live_stream=True,
            ),
        ),
        (
            "editing",
            lambda: hud.set_editing(
                initial_text="Refactor authentication controller to use JWT tokens",
                on_submit=lambda x: None,
                target_name="Antigravity",
            ),
        ),
    ]

    for state_name, setter_fn in states_to_capture:
        setter_fn()
        pump_runloop(0.2)

        # Capture HUD Root View (The Capsule)
        out_file = output_dir / f"hud_{state_name}.png"
        capture_view(hud._root_view, out_file)

        # Also capture the individual reactive logo icon for this state
        vifi_icon = hud._resolve_voicefi_state_icon(state_name.split("_")[0])
        if vifi_icon:
            icon_out_file = output_dir / f"logo_{state_name.split('_')[0]}_256px.png"
            capture_nsimage(vifi_icon, icon_out_file, 256, 256)

    print("\nAll HUD state screenshots captured successfully!")


if __name__ == "__main__":
    main()
