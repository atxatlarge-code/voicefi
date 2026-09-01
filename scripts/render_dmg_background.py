#!/usr/bin/env python3
"""
Render high-DPI Retina Background Image for VoiceFi macOS .dmg Installer Window.
Outputs: assets/dmg_background.png (1320 x 840 px @2x for 660 x 420 pt window).
"""

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
    NSFont,
    NSFontWeightBold,
    NSFontWeightBlack,
    NSFontWeightSemibold,
    NSFontWeightMedium,
    NSMutableParagraphStyle,
    NSTextAlignmentCenter,
    NSShadow,
    NSGraphicsContext,
    NSGradient,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"
OUT_FILE = ASSETS_DIR / "dmg_background.png"


def render_dmg_background():
    app = NSApplication.sharedApplication()

    # Dimensions in Points (660 x 420 pt) and Pixels (1320 x 840 px @2x)
    pt_w, pt_h = 660.0, 420.0
    scale = 2.0
    px_w, px_h = int(pt_w * scale), int(pt_h * scale)

    img = NSImage.alloc().initWithSize_(NSSize(px_w, px_h))
    img.lockFocus()

    ctx = NSGraphicsContext.currentContext()
    ctx.setImageInterpolation_(AppKit.NSImageInterpolationHigh)

    # Convert coordinates to 2x pixel space
    transform = AppKit.NSAffineTransform.transform()
    transform.scaleBy_(scale)
    transform.concat()

    # 1. Background Canvas Gradient (Modern Dark Obsidian Glass)
    c1 = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.035, 0.035, 0.045, 1.0) # #09090C
    c2 = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.065, 0.065, 0.080, 1.0) # #111114
    bg_gradient = NSGradient.alloc().initWithStartingColor_endingColor_(c1, c2)
    bg_rect = NSRect(NSPoint(0, 0), NSSize(pt_w, pt_h))
    bg_gradient.drawInRect_angle_(bg_rect, -90.0)

    # 2. Subtle Glow behind Left (App) and Right (Applications) icon landing pads
    # Left Pad Center: (170, 205 in AppKit bottom-up coordinates is pt_h - 220 = 200)
    app_center_x = 170.0
    apps_center_x = 490.0
    pad_center_y = 195.0

    def draw_drop_pad(cx, cy, label_text):
        pad_w, pad_h = 136.0, 136.0
        pad_rect = NSRect(NSPoint(cx - pad_w / 2.0, cy - pad_h / 2.0), NSSize(pad_w, pad_h))
        
        # Outer soft glow ring
        glow_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.22, 0.28, 0.4)
        glow_color.setStroke()
        glow_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(pad_rect, 28.0, 28.0)
        glow_path.setLineWidth_(1.5)
        
        # Dashed line pattern
        pattern = [6.0, 5.0]
        glow_path.setLineDash_count_phase_(pattern, 2, 0.0)
        glow_path.stroke()

        # Inner subtle tinted fill
        fill_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 1.0, 1.0, 0.025)
        fill_color.setFill()
        glow_path.fill()

    draw_drop_pad(app_center_x, pad_center_y, "VoiceFi.app")
    draw_drop_pad(apps_center_x, pad_center_y, "Applications")

    # 3. Center Directional Electric Red Arrow ➔
    center_x = 330.0
    arrow_y = pad_center_y + 10.0

    # Draw stylish pill badge around arrow
    badge_w, badge_h = 154.0, 32.0
    badge_rect = NSRect(NSPoint(center_x - badge_w / 2.0, arrow_y - badge_h / 2.0), NSSize(badge_w, badge_h))
    badge_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(badge_rect, 16.0, 16.0)

    # Red badge background
    red_badge_bg = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.165, 0.165, 0.14)
    red_badge_bg.setFill()
    badge_path.fill()

    red_badge_stroke = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.165, 0.165, 0.45)
    red_badge_stroke.setStroke()
    badge_path.setLineWidth_(1.2)
    badge_path.stroke()

    # Red Arrow icon inside badge
    arrow_path = NSBezierPath.bezierPath()
    arrow_path.setLineWidth_(3.0)
    arrow_path.setLineCapStyle_(AppKit.NSLineCapStyleRound)
    arrow_path.setLineJoinStyle_(AppKit.NSLineJoinStyleRound)
    
    # Stem
    arrow_path.moveToPoint_(NSPoint(center_x - 18.0, arrow_y))
    arrow_path.lineToPoint_(NSPoint(center_x + 18.0, arrow_y))
    # Arrowhead
    arrow_path.moveToPoint_(NSPoint(center_x + 10.0, arrow_y + 6.5))
    arrow_path.lineToPoint_(NSPoint(center_x + 18.0, arrow_y))
    arrow_path.lineToPoint_(NSPoint(center_x + 10.0, arrow_y - 6.5))
    
    red_arrow_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.22, 0.22, 1.0)
    red_arrow_color.setStroke()
    arrow_path.stroke()

    # Text under arrow badge: "Drag to Applications"
    para = NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(NSTextAlignmentCenter)

    inst_font = NSFont.systemFontOfSize_weight_(11.0, NSFontWeightBold)
    inst_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.85, 0.88, 0.94, 0.90)
    inst_attrs = {
        AppKit.NSFontAttributeName: inst_font,
        AppKit.NSForegroundColorAttributeName: inst_color,
        AppKit.NSParagraphStyleAttributeName: para,
    }
    inst_str = AppKit.NSAttributedString.alloc().initWithString_attributes_(
        "Drag to Applications to Install", inst_attrs
    )
    inst_str.drawInRect_(NSRect(NSPoint(center_x - 120.0, arrow_y - 34.0), NSSize(240.0, 20.0)))

    # 4. Header Section at Top
    # App Title: VoiceFi
    title_font = NSFont.systemFontOfSize_weight_(26.0, NSFontWeightBlack)
    title_white = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.98, 0.98, 1.0, 1.0)
    title_red = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.165, 0.165, 1.0)
    
    title_attrs_white = {
        AppKit.NSFontAttributeName: title_font,
        AppKit.NSForegroundColorAttributeName: title_white,
        AppKit.NSParagraphStyleAttributeName: para,
    }
    title_attrs_red = {
        AppKit.NSFontAttributeName: title_font,
        AppKit.NSForegroundColorAttributeName: title_red,
        AppKit.NSParagraphStyleAttributeName: para,
    }

    title_str = AppKit.NSMutableAttributedString.alloc().initWithString_attributes_("Voice", title_attrs_white)
    title_str.appendAttributedString_(AppKit.NSAttributedString.alloc().initWithString_attributes_("Fi", title_attrs_red))
    
    title_str.drawInRect_(NSRect(NSPoint(0, pt_h - 62.0), NSSize(pt_w, 34.0)))

    # Subtitle: "Universal Voice Layer for AI Agents & macOS"
    sub_font = NSFont.systemFontOfSize_weight_(12.0, NSFontWeightMedium)
    sub_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.55, 0.60, 0.70, 1.0)
    sub_attrs = {
        AppKit.NSFontAttributeName: sub_font,
        AppKit.NSForegroundColorAttributeName: sub_color,
        AppKit.NSParagraphStyleAttributeName: para,
    }
    sub_str = AppKit.NSAttributedString.alloc().initWithString_attributes_(
        "Universal Voice Layer for AI Agents & macOS", sub_attrs
    )
    sub_str.drawInRect_(NSRect(NSPoint(0, pt_h - 84.0), NSSize(pt_w, 20.0)))

    # 5. Footer Section at Bottom
    foot_font = NSFont.systemFontOfSize_weight_(10.5, NSFontWeightMedium)
    foot_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.40, 0.45, 0.55, 0.85)
    foot_attrs = {
        AppKit.NSFontAttributeName: foot_font,
        AppKit.NSForegroundColorAttributeName: foot_color,
        AppKit.NSParagraphStyleAttributeName: para,
    }
    foot_str = AppKit.NSAttributedString.alloc().initWithString_attributes_(
        "100% Private Offline Neural Speech • Universal Apple Silicon & Intel • Pro 14-Day Preview Included", foot_attrs
    )
    foot_str.drawInRect_(NSRect(NSPoint(0, 16.0), NSSize(pt_w, 18.0)))

    rep = AppKit.NSBitmapImageRep.alloc().initWithFocusedViewRect_(
        NSRect(NSPoint(0, 0), NSSize(px_w, px_h))
    )
    img.unlockFocus()

    png_data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    png_data.writeToFile_atomically_(str(OUT_FILE), True)
    print(f"🎉 Generated DMG Background: {OUT_FILE} ({px_w}x{px_h} px)")


if __name__ == "__main__":
    render_dmg_background()
