#!/usr/bin/env python3
"""
Render VoiceFi macOS App Icon with White Background Squircle.
Generates all 10 macOS retina iconset sizes and compiles assets/VoiceFi.icns.
"""

import math
import os
import subprocess
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
    NSShadow,
    NSGraphicsContext,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"
ICONSET_DIR = ASSETS_DIR / "VoiceFi.iconset"
ICNS_FILE = ASSETS_DIR / "VoiceFi.icns"


def draw_voicefi_character(rect: NSRect):
    """Draw the crisp vector VoiceFi character within rect."""
    x = rect.origin.x
    y = rect.origin.y
    w = rect.size.width
    h = rect.size.height

    # Scale relative to 400x400 reference box
    scale = min(w, h) / 400.0
    ox = x + (w - 400.0 * scale) / 2.0
    oy = y + (h - 400.0 * scale) / 2.0

    def sx(val):
        return ox + val * scale

    def sy(val):
        return oy + (400.0 - val) * scale

    def sw(val):
        return val * scale

    # Colors
    red_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.165, 0.165, 1.0)
    red_bright = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.23, 0.19, 1.0)
    red_dark = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.88, 0.0, 0.165, 1.0)
    black_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.09, 0.16, 1.0)
    white_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 1.0)

    hat_y_offset = 15.0

    # Top Hat Arc
    p1 = NSBezierPath.bezierPath()
    p1.setLineWidth_(sw(22.0))
    p1.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    p1.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        NSPoint(sx(200.0), sy(125.0 + hat_y_offset)),
        sw(105.0),
        25.0,
        155.0,
        False,
    )
    red_color.setStroke()
    p1.stroke()

    # Mid Hat Arc
    p2 = NSBezierPath.bezierPath()
    p2.setLineWidth_(sw(20.0))
    p2.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    p2.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        NSPoint(sx(200.0), sy(125.0 + hat_y_offset)),
        sw(70.0),
        25.0,
        155.0,
        False,
    )
    red_bright.setStroke()
    p2.stroke()

    # Low Hat Arc
    p3 = NSBezierPath.bezierPath()
    p3.setLineWidth_(sw(18.0))
    p3.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    p3.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
        NSPoint(sx(200.0), sy(125.0 + hat_y_offset)),
        sw(36.0),
        25.0,
        155.0,
        False,
    )
    red_dark.setStroke()
    p3.stroke()

    # 2. Cyber Eyes
    eye_y = 205.0
    eye_path = NSBezierPath.bezierPath()
    eye_path.setLineWidth_(sw(12.0))
    eye_path.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    eye_path.moveToPoint_(NSPoint(sx(150.0), sy(eye_y)))
    eye_path.lineToPoint_(NSPoint(sx(180.0), sy(eye_y)))
    eye_path.moveToPoint_(NSPoint(sx(220.0), sy(eye_y)))
    eye_path.lineToPoint_(NSPoint(sx(250.0), sy(eye_y)))
    black_color.setStroke()
    eye_path.stroke()

    # 3. USB-C Port Nose
    nose_rect = NSRect(NSPoint(sx(184.0), sy(234.0)), NSSize(sw(32.0), sw(14.0)))
    nose_bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        nose_rect, sw(7.0), sw(7.0)
    )
    white_color.setFill()
    nose_bg.fill()
    red_color.setStroke()
    nose_bg.setLineWidth_(sw(3.5))
    nose_bg.stroke()

    slit = NSBezierPath.bezierPath()
    slit.setLineWidth_(sw(3.0))
    slit.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    slit.moveToPoint_(NSPoint(sx(192.0), sy(227.0)))
    slit.lineToPoint_(NSPoint(sx(208.0), sy(227.0)))
    black_color.setStroke()
    slit.stroke()

    # 4. Friendly Waveform Smile
    smile = NSBezierPath.bezierPath()
    smile.setLineWidth_(sw(7.5))
    smile.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    smile.moveToPoint_(NSPoint(sx(175.0), sy(258.0)))
    smile.curveToPoint_controlPoint1_controlPoint2_(
        NSPoint(sx(225.0), sy(258.0)),
        NSPoint(sx(190.0), sy(276.0)),
        NSPoint(sx(210.0), sy(276.0)),
    )
    red_color.setStroke()
    smile.stroke()

    # 5. Studio Microphone Cradle & Plug Base
    cradle = NSBezierPath.bezierPath()
    cradle.setLineWidth_(sw(17.0))
    cradle.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    cradle.moveToPoint_(NSPoint(sx(80.0), sy(175.0)))
    cradle.curveToPoint_controlPoint1_controlPoint2_(
        NSPoint(sx(200.0), sy(310.0)),
        NSPoint(sx(80.0), sy(280.0)),
        NSPoint(sx(125.0), sy(310.0)),
    )
    cradle.curveToPoint_controlPoint1_controlPoint2_(
        NSPoint(sx(320.0), sy(175.0)),
        NSPoint(sx(275.0), sy(310.0)),
        NSPoint(sx(320.0), sy(280.0)),
    )
    black_color.setStroke()
    cradle.stroke()

    # Left Plug Prong
    l_prong_rect = NSRect(NSPoint(sx(67.0), sy(192.0)), NSSize(sw(26.0), sw(28.0)))
    l_prong = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        l_prong_rect, sw(6.0), sw(6.0)
    )
    white_color.setFill()
    l_prong.fill()
    black_color.setStroke()
    l_prong.setLineWidth_(sw(3.5))
    l_prong.stroke()

    l_dot = NSBezierPath.bezierPathWithOvalInRect_(
        NSRect(NSPoint(sx(75.5), sy(182.5)), NSSize(sw(9.0), sw(9.0)))
    )
    red_color.setFill()
    l_dot.fill()

    # Right Plug Prong
    r_prong_rect = NSRect(NSPoint(sx(307.0), sy(192.0)), NSSize(sw(26.0), sw(28.0)))
    r_prong = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        r_prong_rect, sw(6.0), sw(6.0)
    )
    white_color.setFill()
    r_prong.fill()
    black_color.setStroke()
    r_prong.setLineWidth_(sw(3.5))
    r_prong.stroke()

    r_dot = NSBezierPath.bezierPathWithOvalInRect_(
        NSRect(NSPoint(sx(315.5), sy(182.5)), NSSize(sw(9.0), sw(9.0)))
    )
    red_color.setFill()
    r_dot.fill()

    # Stem & Base Stand
    stem = NSBezierPath.bezierPath()
    stem.setLineWidth_(sw(18.0))
    stem.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    stem.moveToPoint_(NSPoint(sx(200.0), sy(310.0)))
    stem.lineToPoint_(NSPoint(sx(200.0), sy(350.0)))
    black_color.setStroke()
    stem.stroke()

    base_stand = NSBezierPath.bezierPath()
    base_stand.setLineWidth_(sw(18.0))
    base_stand.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    base_stand.moveToPoint_(NSPoint(sx(138.0), sy(350.0)))
    base_stand.lineToPoint_(NSPoint(sx(262.0), sy(350.0)))
    black_color.setStroke()
    base_stand.stroke()


def render_icon(size: int) -> bytes:
    """Render a single icon size with white squircle tile background."""
    img = NSImage.alloc().initWithSize_(NSSize(size, size))
    img.lockFocus()

    NSGraphicsContext.currentContext().setImageInterpolation_(
        AppKit.NSImageInterpolationHigh
    )

    # 1. macOS Squircle Tile Geometry
    margin = size * 0.088
    tile_size = size - 2 * margin
    corner_radius = tile_size * 0.224

    tile_rect = NSRect(NSPoint(margin, margin), NSSize(tile_size, tile_size))
    squircle_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        tile_rect, corner_radius, corner_radius
    )

    if size >= 64:
        shadow = NSShadow.alloc().init()
        shadow.setShadowColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.0, 0.0, 0.0, 0.18)
        )
        shadow.setShadowOffset_(NSSize(0, -size * 0.025))
        shadow.setShadowBlurRadius_(size * 0.05)
        shadow.set()

    white_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.99, 0.99, 1.0, 1.0)
    white_bg.setFill()
    squircle_path.fill()

    stroke_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
        0.0, 0.0, 0.0, 0.07
    )
    stroke_color.setStroke()
    squircle_path.setLineWidth_(max(1.0, size * 0.003))
    squircle_path.stroke()

    # 2. Draw Character Inside Squircle
    char_pad = tile_size * 0.13
    char_rect = NSRect(
        NSPoint(margin + char_pad, margin + char_pad),
        NSSize(tile_size - 2 * char_pad, tile_size - 2 * char_pad),
    )
    draw_voicefi_character(char_rect)

    rep = AppKit.NSBitmapImageRep.alloc().initWithFocusedViewRect_(
        NSRect(NSPoint(0, 0), NSSize(size, size))
    )
    img.unlockFocus()

    return rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)


def main():
    print("🎨 Rendering VoiceFi macOS App Iconset with White Background Squircle...")
    app = NSApplication.sharedApplication()

    ICONSET_DIR.mkdir(parents=True, exist_ok=True)

    sizes = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    for fname, dim in sizes:
        out_path = ICONSET_DIR / fname
        png_data = render_icon(dim)
        png_data.writeToFile_atomically_(str(out_path), True)
        print(f"  ✓ Rendered {fname} ({dim}x{dim})")

    master_png = ASSETS_DIR / "logo-voicefi-avatar-bold-light-1024.png"
    png_1024 = render_icon(1024)
    png_1024.writeToFile_atomically_(str(master_png), True)
    print(f"  ✓ Updated master {master_png.name}")

    print("📦 Compiling VoiceFi.icns using macOS iconutil...")
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_FILE)],
        check=True,
    )
    print(f"🎉 SUCCESS: Generated {ICNS_FILE} ({ICNS_FILE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
