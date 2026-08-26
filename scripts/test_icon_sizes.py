import sys
from pathlib import Path
import AppKit
from AppKit import (
    NSApplication,
    NSRunLoop,
    NSDate,
    NSBitmapImageFileTypePNG,
    NSRect,
    NSPoint,
    NSSize,
)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

def pump_runloop(seconds=0.1):
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

def apply_geometry(hud, icon_size, box_size, text_x):
    y_pos = (58.0 - box_size) / 2.0
    hud._avatar_box.setFrame_(NSRect(NSPoint(14, y_pos), NSSize(box_size, box_size)))
    pad = (box_size - icon_size) / 2.0
    hud._avatar_img.setFrame_(NSRect(NSPoint(pad, pad), NSSize(icon_size, icon_size)))
    
    # Adjust text labels x position
    hud._title_lbl.setFrame_(NSRect(NSPoint(text_x, 32), NSSize(140, 18)))
    hud._body_lbl.setFrame_(NSRect(NSPoint(text_x, 8), NSSize(380 - (text_x - 50), 22)))

def main():
    app = NSApplication.sharedApplication()
    hud = UnifiedDynamicIslandHUD.get_instance()
    out_dir = Path(__file__).parent.parent / "assets" / "screenshots" / "icon_sizes"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    sizes = [
        ("current_24px", 24.0, 28.0, 50.0),
        ("medium_34px", 34.0, 38.0, 60.0),
        ("large_40px", 40.0, 44.0, 66.0),
    ]
    
    test_states = [
        ("thinking", lambda: hud.set_thinking(agent_name="Antigravity", detail="Reasoning over AST & planning architecture...")),
        ("listening", lambda: hud.set_listening(prompt_preview="Speak your prompt or question...", user_name="Jake")),
        ("speaking", lambda: hud.set_speaking(text="Refactored the authentication controller and verified all tests.", agent_name="Antigravity", persona_name="Christopher")),
        ("idle", lambda: hud.set_idle()),
    ]
    
    for size_label, icon_px, box_px, text_x in sizes:
        for state_name, setter_fn in test_states:
            setter_fn()
            apply_geometry(hud, icon_px, box_px, text_x)
            pump_runloop(0.15)
            out_file = out_dir / f"hud_{state_name}_{size_label}.png"
            capture_view(hud._root_view, out_file)
            print(f"Captured: {out_file.name}")
            
    # Reset back to standard geometry
    apply_geometry(hud, 24.0, 28.0, 50.0)

if __name__ == "__main__":
    main()
