import sys
from pathlib import Path
import AppKit
from AppKit import (
    NSApplication,
    NSData,
    NSImage,
    NSRunLoop,
    NSDate,
    NSBitmapImageFileTypePNG,
    NSRect,
    NSPoint,
    NSSize,
)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

def generate_listening_svg(waves_type=1):
    # Base strokes
    wifi_stroke = "#FFFFFF"
    ear_stroke = "#FF0033"
    ear_dot = "#FF0033"
    mouth_stroke = "#FFFFFF"
    cradle_stroke = "#FFFFFF"
    eye_stroke = "#FFFFFF"
    nose_stroke = "#FFFFFF"
    wave_stroke = "#FF0033"

    extra_waves = ""
    if waves_type == 1:
        # Dual concentric acoustic arcs
        extra_waves = f"""
    <!-- Left Ear Waves -->
    <path d="M 94 206 A 20 20 0 0 0 94 234" fill="none" stroke="{wave_stroke}" stroke-width="4.5" stroke-linecap="round" />
    <path d="M 76 196 A 35 35 0 0 0 76 244" fill="none" stroke="{wave_stroke}" stroke-width="4.5" stroke-linecap="round" />
    <!-- Right Ear Waves -->
    <path d="M 418 206 A 20 20 0 0 1 418 234" fill="none" stroke="{wave_stroke}" stroke-width="4.5" stroke-linecap="round" />
    <path d="M 436 196 A 35 35 0 0 1 436 244" fill="none" stroke="{wave_stroke}" stroke-width="4.5" stroke-linecap="round" />
        """
    elif waves_type == 2:
        # Triple acoustic arcs (strong sonar broadcast)
        extra_waves = f"""
    <!-- Left Ear Waves -->
    <path d="M 96 208 A 16 16 0 0 0 96 232" fill="none" stroke="{wave_stroke}" stroke-width="4" stroke-linecap="round" />
    <path d="M 82 198 A 28 28 0 0 0 82 242" fill="none" stroke="{wave_stroke}" stroke-width="4.5" stroke-linecap="round" />
    <path d="M 68 188 A 40 40 0 0 0 68 252" fill="none" stroke="{wave_stroke}" stroke-width="5" stroke-linecap="round" />
    <!-- Right Ear Waves -->
    <path d="M 416 208 A 16 16 0 0 1 416 232" fill="none" stroke="{wave_stroke}" stroke-width="4" stroke-linecap="round" />
    <path d="M 430 198 A 28 28 0 0 1 430 242" fill="none" stroke="{wave_stroke}" stroke-width="4.5" stroke-linecap="round" />
    <path d="M 444 188 A 40 40 0 0 1 444 252" fill="none" stroke="{wave_stroke}" stroke-width="5" stroke-linecap="round" />
        """
    elif waves_type == 3:
        # Organic curved bracket pulses
        extra_waves = f"""
    <!-- Left Ear Waves -->
    <path d="M 92 202 Q 78 220 92 238" fill="none" stroke="{wave_stroke}" stroke-width="5" stroke-linecap="round" />
    <path d="M 74 190 Q 54 220 74 250" fill="none" stroke="{wave_stroke}" stroke-width="5.5" stroke-linecap="round" />
    <!-- Right Ear Waves -->
    <path d="M 420 202 Q 434 220 420 238" fill="none" stroke="{wave_stroke}" stroke-width="5" stroke-linecap="round" />
    <path d="M 438 190 Q 458 220 438 250" fill="none" stroke="{wave_stroke}" stroke-width="5.5" stroke-linecap="round" />
        """

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="50 50 412 412" width="256" height="256">
  <rect width="100%" height="100%" fill="#12161F" rx="30" />
  <g transform="translate(0, 15)">
    {extra_waves}
    <g fill="none" stroke-linecap="round">
      <path d="M 152 145 A 120 120 0 0 1 360 145" stroke="{wifi_stroke}" stroke-width="18" />
      <path d="M 184 180 A 80 80 0 0 1 328 180" stroke="{wifi_stroke}" stroke-width="17" />
      <path d="M 216 215 A 42 42 0 0 1 296 215" stroke="{wifi_stroke}" stroke-width="16" />
    </g>
    <g stroke-linecap="round">
      <line x1="202" y1="262" x2="234" y2="262" stroke="{eye_stroke}" stroke-width="8" />
      <line x1="278" y1="262" x2="310" y2="262" stroke="{eye_stroke}" stroke-width="8" />
    </g>
    <g>
      <rect x="238" y="278" width="36" height="15" rx="7.5" fill="#000000" stroke="{nose_stroke}" stroke-width="2.5" />
      <line x1="246" y1="285.5" x2="266" y2="285.5" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round" />
    </g>
    <path d="M 230 320 Q 256 342 282 320" fill="none" stroke="{mouth_stroke}" stroke-width="6" stroke-linecap="round" />
    <path d="M 124 220 C 124 350, 175 385, 256 385 C 337 385, 388 350, 388 220" fill="none" stroke="{cradle_stroke}" stroke-width="12" stroke-linecap="round" />
    <g>
      <rect x="110" y="205" width="28" height="30" rx="6" fill="#000000" stroke="{ear_stroke}" stroke-width="3.5" />
      <circle cx="124" cy="220" r="4.5" fill="{ear_dot}" />
    </g>
    <g>
      <rect x="374" y="205" width="28" height="30" rx="6" fill="#000000" stroke="{ear_stroke}" stroke-width="3.5" />
      <circle cx="388" cy="220" r="4.5" fill="{ear_dot}" />
    </g>
    <line x1="256" y1="385" x2="256" y2="430" stroke="#FFFFFF" stroke-width="13" stroke-linecap="round" />
    <line x1="190" y1="430" x2="322" y2="430" stroke="#FFFFFF" stroke-width="13" stroke-linecap="round" />
  </g>
</svg>"""
    return svg

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

def main():
    app = NSApplication.sharedApplication()
    hud = UnifiedDynamicIslandHUD.get_instance()
    out_dir = Path(__file__).parent.parent / "assets" / "screenshots" / "ear_waves"
    out_dir.mkdir(parents=True, exist_ok=True)

    for v in [1, 2, 3]:
        svg_xml = generate_listening_svg(v)
        data = NSData.dataWithBytes_length_(svg_xml.encode("utf-8"), len(svg_xml.encode("utf-8")))
        img = NSImage.alloc().initWithData_(data)
        
        # 1. Save 256px icon
        icon_view = AppKit.NSImageView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(256, 256)))
        icon_view.setImage_(img)
        capture_view(icon_view, out_dir / f"logo_listening_waves_v{v}_256px.png")
        
        # 2. Render inside HUD
        hud.set_listening(prompt_preview="Speak your prompt or question...", user_name="Jake")
        hud._avatar_img.setImage_(img)
        pump_runloop(0.15)
        capture_view(hud._root_view, out_dir / f"hud_listening_waves_v{v}.png")
        print(f"Rendered Option {v}")

if __name__ == "__main__":
    main()
