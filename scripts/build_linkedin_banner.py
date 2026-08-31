#!/usr/bin/env python3
"""
Customizable LinkedIn Banner Generator for VoiceFi.
Modify the settings below to adjust scale, position, and colors.
"""

import subprocess
from pathlib import Path

# ==============================================================================
# ADJUSTMENT SETTINGS (Tweak these values)
# ==============================================================================

# Scale factor for the logo (1.0 = standard, 0.8 = 20% smaller, 1.2 = 20% larger)
SCALE = 0.92

# Position offsets from center (in pixels):
# Positive OFFSET_X moves RIGHT, negative moves LEFT
# Positive OFFSET_Y moves DOWN, negative moves UP
OFFSET_X = 0  # e.g., 50 to shift right away from avatar
OFFSET_Y = 0  # e.g., -10 to shift up slightly

# Canvas Dimensions (LinkedIn standard is 1128 x 191)
CANVAS_WIDTH = 1128
CANVAS_HEIGHT = 191
RETINA_SCALE = 2  # 2x generates 2256 x 382 px

# ==============================================================================
# SCRIPT LOGIC
# ==============================================================================

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "assets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

LIGHT_LOGO = Path(
    "/Users/jaketrigg/Projects/voicefi.org/assets/logo-voicefi-org-light.svg"
).read_text()
DARK_LOGO = Path(
    "/Users/jaketrigg/Projects/voicefi.org/assets/logo-voicefi-org-dark.svg"
).read_text()


def get_svg_inner(svg_str):
    start = svg_str.find(">", svg_str.find("<svg")) + 1
    end = svg_str.rfind("</svg>")
    return svg_str[start:end]


light_inner = get_svg_inner(LIGHT_LOGO)
dark_inner = get_svg_inner(DARK_LOGO)

# Logo intrinsic center is at (-295 * SCALE, -60 * SCALE)
base_x = (CANVAS_WIDTH / 2) + OFFSET_X - (295 * SCALE)
base_y = (CANVAS_HEIGHT / 2) + OFFSET_Y - (60 * SCALE)

white_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}">
  <rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="#FFFFFF" />
  <g transform="translate({base_x:.1f}, {base_y:.1f}) scale({SCALE:.3f})">
    {light_inner}
  </g>
</svg>"""

dark_svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}">
  <rect width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" fill="#090B10" />
  <g transform="translate({base_x:.1f}, {base_y:.1f}) scale({SCALE:.3f})">
    {dark_inner}
  </g>
</svg>"""

(OUTPUT_DIR / "linkedin-banner-white.svg").write_text(white_svg)
(OUTPUT_DIR / "linkedin-banner-dark.svg").write_text(dark_svg)


def render_png(svg_path: Path, png_path: Path):
    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ width: {CANVAS_WIDTH}px; height: {CANVAS_HEIGHT}px; overflow: hidden; background: transparent; }}
    img {{ width: {CANVAS_WIDTH}px; height: {CANVAS_HEIGHT}px; display: block; }}
  </style>
</head>
<body>
  <img src="{svg_path.resolve()}" />
</body>
</html>"""

    html_file = svg_path.with_suffix(".html")
    html_file.write_text(html_content)

    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    cmd = [
        chrome_bin,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={CANVAS_WIDTH},{CANVAS_HEIGHT}",
        f"--force-device-scale-factor={RETINA_SCALE}",
        f"--screenshot={png_path.resolve()}",
        f"file://{html_file.resolve()}",
    ]
    subprocess.run(cmd, check=True)
    html_file.unlink(missing_ok=True)
    print(f"✅ Rendered: {png_path.name}")


render_png(OUTPUT_DIR / "linkedin-banner-white.svg", OUTPUT_DIR / "linkedin-banner-white.png")
render_png(OUTPUT_DIR / "linkedin-banner-dark.svg", OUTPUT_DIR / "linkedin-banner-dark.png")
