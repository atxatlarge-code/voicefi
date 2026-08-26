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
    NSColor,
    NSBezierPath,
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

def render_logo_circle(hud, state, bg_mode, out_path, dim=256):
    vifi_icon = hud._resolve_voicefi_state_icon(state)
    if not vifi_icon:
        return
    target_img = NSImage.alloc().initWithSize_(NSSize(dim, dim))
    target_img.lockFocus()
    
    # 1. Dark canvas (representing HUD surface)
    hud_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.07, 0.10, 1.0)
    hud_bg.setFill()
    NSBezierPath.fillRect_(NSRect(NSPoint(0, 0), NSSize(dim, dim)))
    
    # 2. Circle background
    if bg_mode == "black":
        circle_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.8)
        circle_bg.setFill()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSRect(NSPoint(16, 16), NSSize(dim-32, dim-32)), (dim-32)/2.0, (dim-32)/2.0
        )
        path.fill()
    elif bg_mode == "subtle_dark":
        circle_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.07)
        circle_bg.setFill()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSRect(NSPoint(16, 16), NSSize(dim-32, dim-32)), (dim-32)/2.0, (dim-32)/2.0
        )
        path.fill()
    elif bg_mode == "transparent":
        # No inner circle, icon floats on HUD canvas
        pass
        
    # 3. Draw Icon
    pad = 28
    vifi_icon.drawInRect_fromRect_operation_fraction_(
        NSRect(NSPoint(pad, pad), NSSize(dim - 2*pad, dim - 2*pad)),
        NSRect(NSPoint(0, 0), vifi_icon.size()),
        AppKit.NSCompositingOperationSourceOver,
        1.0
    )
    
    rep = AppKit.NSBitmapImageRep.alloc().initWithFocusedViewRect_(
        NSRect(NSPoint(0, 0), NSSize(dim, dim))
    )
    target_img.unlockFocus()
    png_data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    png_data.writeToFile_atomically_(str(out_path), True)

def main():
    app = NSApplication.sharedApplication()
    hud = UnifiedDynamicIslandHUD.get_instance()
    out_dir = Path(__file__).parent.parent / "assets" / "screenshots" / "bg_comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    states = ["listening", "thinking", "working", "speaking", "idle"]
    bg_modes = ["transparent", "black", "subtle_dark"]
    
    # 1. Render standalone comparison logos
    for st in states:
        for mode in bg_modes:
            render_logo_circle(hud, st, mode, out_dir / f"logo_{st}_{mode}.png")
            
    # 2. Render full HUD capsules with Transparent vs Black vs Subtle
    # Transparent
    hud.set_listening(user_name="Jake")
    hud._avatar_box.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
    pump_runloop(0.15)
    capture_view(hud._root_view, out_dir / "hud_listening_transparent.png")
    
    # Black
    hud.set_listening(user_name="Jake")
    hud._avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.6).CGColor())
    pump_runloop(0.15)
    capture_view(hud._root_view, out_dir / "hud_listening_black.png")
    
    # Subtle dark
    hud.set_listening(user_name="Jake")
    hud._avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.08).CGColor())
    pump_runloop(0.15)
    capture_view(hud._root_view, out_dir / "hud_listening_subtle.png")
    
    # Also for thinking
    hud.set_thinking(agent_name="Antigravity", detail="Reasoning over AST...")
    hud._avatar_box.layer().setBackgroundColor_(NSColor.clearColor().CGColor())
    pump_runloop(0.15)
    capture_view(hud._root_view, out_dir / "hud_thinking_transparent.png")
    
    hud.set_thinking(agent_name="Antigravity", detail="Reasoning over AST...")
    hud._avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.6).CGColor())
    pump_runloop(0.15)
    capture_view(hud._root_view, out_dir / "hud_thinking_black.png")

    hud.set_thinking(agent_name="Antigravity", detail="Reasoning over AST...")
    hud._avatar_box.layer().setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.08).CGColor())
    pump_runloop(0.15)
    capture_view(hud._root_view, out_dir / "hud_thinking_subtle.png")

    print("Background options rendered successfully!")

if __name__ == "__main__":
    main()
