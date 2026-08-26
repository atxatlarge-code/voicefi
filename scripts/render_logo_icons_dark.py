import sys
from pathlib import Path
import AppKit
from AppKit import (
    NSApplication,
    NSImage,
    NSRect,
    NSPoint,
    NSSize,
    NSColor,
    NSBezierPath,
    NSBitmapImageFileTypePNG,
)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

def main():
    app = NSApplication.sharedApplication()
    hud = UnifiedDynamicIslandHUD.get_instance()
    
    out_dir = Path(__file__).parent.parent / "assets" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    states = ["idle", "thinking", "working", "speaking", "listening"]
    
    bg_colors = {
        "idle": (0.15, 0.20, 0.28, 1.0),
        "thinking": (0.35, 0.20, 0.55, 1.0),
        "working": (0.15, 0.35, 0.65, 1.0),
        "speaking": (0.10, 0.40, 0.50, 1.0),
        "listening": (0.65, 0.12, 0.16, 1.0),
    }
    
    dim = 256
    for st in states:
        vifi_icon = hud._resolve_voicefi_state_icon(st)
        if not vifi_icon:
            continue
            
        target_img = NSImage.alloc().initWithSize_(NSSize(dim, dim))
        target_img.lockFocus()
        
        # Draw dark rounded background
        r, g, b, a = bg_colors.get(st, (0.1, 0.1, 0.1, 1.0))
        bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)
        bg_color.setFill()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSRect(NSPoint(0, 0), NSSize(dim, dim)),
            dim / 2.0,
            dim / 2.0
        )
        path.fill()
        
        # Draw vector icon centered inside with 20px padding
        pad = 20
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
        out_file = out_dir / f"logo_dark_{st}_256px.png"
        png_data.writeToFile_atomically_(str(out_file), True)
        print(f"Rendered: {out_file}")

if __name__ == "__main__":
    main()
