"""
voicefi/factory/image_templates.py
Reusable Still Image & Social Carousel Template Engine for the Content Creation Factory.
Supports on-device rendering of high-impact Instagram, LinkedIn, and Facebook cards.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("voicefi.factory.image_templates")


@dataclass
class PosterHorrorConfig:
    """Configuration for the Horror Action Poster Image Template."""
    bg_image_path: str
    headline_primary: str = "SILICON VALLEY"
    headline_suffix: str = "’S"
    headline_sub: str = "GOT YOU"
    footer_lead: str = "LOCKED IN THEIR"
    footer_primary: str = "SUBSCRIPTION\nLOOP"
    footer_color: str = "#FF1E27"
    footer_glow: str = "rgba(255, 30, 39, 0.75)"
    format_type: str = "4:5"  # "4:5" (1080x1350) or "1:1" (1080x1080)
    top_offset_px: int = 110
    bottom_offset_px: int = 70
    headline_size_px: int = 88
    footer_primary_size_px: int = 96
    style_variant: str = "a24"  # "a24", "carpenter", "cyber", "cinematic"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bg_image_path": self.bg_image_path,
            "headline_primary": self.headline_primary,
            "headline_suffix": self.headline_suffix,
            "headline_sub": self.headline_sub,
            "footer_lead": self.footer_lead,
            "footer_primary": self.footer_primary,
            "footer_color": self.footer_color,
            "footer_glow": self.footer_glow,
            "format_type": self.format_type,
            "top_offset_px": self.top_offset_px,
            "bottom_offset_px": self.bottom_offset_px,
            "headline_size_px": self.headline_size_px,
            "footer_primary_size_px": self.footer_primary_size_px,
            "style_variant": self.style_variant,
        }

# Backwards compatibility alias
BrutalistKnockoutConfig = PosterHorrorConfig


class PosterHorrorTemplate:
    """
    Template: Horror Action Poster (poster_horror)
    Features:
    - Cinematic psychological / horror thriller typographic hierarchy
    - Razor-sharp or distressed title lockup with top-aligned suffix
    - Eerie atmospheric gradient vignette over dark server rooms / thriller backgrounds
    - Glowing neon crimson / blood-red punchline footer
    """

    NAME = "poster_horror"
    DESCRIPTION = "Cinematic horror action movie poster with glowing blood-red typography and atmospheric dread."

    @staticmethod
    def render_html(config: BrutalistKnockoutConfig) -> str:
        # Load and base64 encode background image
        bg_path = Path(config.bg_image_path).resolve()
        if not bg_path.is_file():
            raise FileNotFoundError(f"Background image not found: {bg_path}")

        b64_data = base64.b64encode(bg_path.read_bytes()).decode("utf-8")
        ext = bg_path.suffix.lower().replace(".", "")
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"

        # Aspect ratio dimensions
        if config.format_type == "1:1":
            width, height = 1080, 1080
            top_offset = max(50, config.top_offset_px - 40)
            bottom_offset = max(40, config.bottom_offset_px - 15)
            headline_size = int(config.headline_size_px * 0.88)
            footer_size = int(config.footer_primary_size_px * 0.88)
        else:  # 4:5 default
            width, height = 1080, 1350
            top_offset = config.top_offset_px
            bottom_offset = config.bottom_offset_px
            headline_size = config.headline_size_px
            footer_size = config.footer_primary_size_px

        # Suffix HTML
        suffix_html = ""
        if config.headline_suffix:
            suffix_html = f"""<span class="title-sv-s">{config.headline_suffix}</span>"""

        # Format footer primary text (handle newlines)
        footer_primary_html = "<br>".join(config.footer_primary.splitlines())

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Outfit:wght@800;900&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    width: {width}px;
    height: {height}px;
    background: #000;
    position: relative;
    overflow: hidden;
  }}
  .bg {{
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 25%;
  }}
  .overlay {{
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: linear-gradient(
      180deg,
      rgba(0, 0, 0, 0.72) 0%,
      rgba(0, 0, 0, 0.06) 40%,
      rgba(0, 0, 0, 0.20) 65%,
      rgba(0, 0, 0, 0.90) 100%
    );
  }}

  /* Top Section */
  .top-container {{
    position: absolute;
    top: {top_offset}px;
    left: 40px;
    right: 40px;
    text-align: center;
  }}
  .title-sv {{
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Helvetica Neue', sans-serif;
    font-size: {headline_size}px;
    line-height: 0.92;
    color: #FFFFFF;
    letter-spacing: 2px;
    text-transform: uppercase;
    text-shadow: 0 6px 35px rgba(0, 0, 0, 0.95);
    margin-bottom: 14px;
    display: inline-flex;
    align-items: flex-start;
    justify-content: center;
  }}
  .title-sv-s {{
    font-size: 0.50em;
    line-height: 1;
    vertical-align: top;
    margin-top: 2px;
    margin-left: 3px;
    color: #E2E8F0;
    font-family: 'Outfit', -apple-system, sans-serif;
    font-weight: 800;
  }}
  .sub-got-you {{
    font-family: 'Outfit', sans-serif;
    font-size: 32px;
    font-weight: 800;
    letter-spacing: 8px;
    color: #94A3B8;
    text-transform: uppercase;
  }}

  /* Bottom Section */
  .bottom-container {{
    position: absolute;
    bottom: {bottom_offset}px;
    left: 40px;
    right: 40px;
    text-align: center;
  }}
  .sub-locked-in {{
    font-family: 'Outfit', sans-serif;
    font-size: 30px;
    font-weight: 800;
    letter-spacing: 7px;
    color: #FF7A7A;
    text-transform: uppercase;
    margin-bottom: 8px;
  }}
  .title-loop {{
    font-family: 'Anton', sans-serif;
    font-size: {footer_size}px;
    line-height: 0.90;
    color: {config.footer_color};
    letter-spacing: 2px;
    text-transform: uppercase;
    text-shadow: 0 0 50px {config.footer_glow}, 0 4px 20px rgba(0, 0, 0, 0.95);
  }}
</style>
</head>
<body>
  <img class="bg" src="data:{mime};base64,{b64_data}">
  <div class="overlay"></div>

  <div class="top-container">
    <div class="title-sv">
      <span>{config.headline_primary}</span>
      {suffix_html}
    </div>
    <div class="sub-got-you">
      {config.headline_sub}
    </div>
  </div>

  <div class="bottom-container">
    <div class="sub-locked-in">
      {config.footer_lead}
    </div>
    <div class="title-loop">
      {footer_primary_html}
    </div>
  </div>
</body>
</html>"""

    @classmethod
    def render(cls, config: BrutalistKnockoutConfig, output_path: Path) -> bool:
        """Renders the template to a high-resolution PNG using local Playwright or Chrome headless."""
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        width = 1080
        height = 1080 if config.format_type == "1:1" else 1350
        html_content = cls.render_html(config)

        # 1. Try local Playwright in VoiceFi venv
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": width, "height": height})
                page.set_content(html_content, wait_until="networkidle")
                page.evaluate("() => document.fonts.ready")
                page.screenshot(path=str(output_path), type="png")
                browser.close()
            return True
        except Exception as e:
            logger.debug(f"Playwright in-process render notice: {e}, attempting CLI fallback...")

        # 2. Fallback to Google Chrome headless
        chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.exists(chrome_bin):
            tmp_html = Path(tempfile.mkdtemp(prefix="vf_template_")) / "slide.html"
            try:
                tmp_html.write_text(html_content, encoding="utf-8")
                cmd = [
                    chrome_bin,
                    "--headless",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--hide-scrollbars",
                    f"--window-size={width},{height}",
                    f"--screenshot={str(output_path)}",
                    f"file://{str(tmp_html)}",
                ]
                res = subprocess.run(cmd, capture_output=True)
                return res.returncode == 0 and output_path.exists()
            finally:
                if tmp_html.parent.exists():
                    import shutil
                    shutil.rmtree(tmp_html.parent, ignore_errors=True)

        return False


# Backwards compatibility alias
BrutalistKnockoutTemplate = PosterHorrorTemplate

# Registry of templates available in the VoiceFi Content Creation Factory
TEMPLATES = {
    "poster_horror": PosterHorrorTemplate,
    "poster-horror": PosterHorrorTemplate,
    "horror_poster": PosterHorrorTemplate,
    "brutalist_knockout": PosterHorrorTemplate,
}


def render_image(
    template_name: str = "poster_horror",
    bg_image_path: str = "",
    output_path: str = "",
    headline_primary: str = "SILICON VALLEY",
    headline_suffix: str = "’S",
    headline_sub: str = "GOT YOU",
    footer_lead: str = "LOCKED IN THEIR",
    footer_primary: str = "SUBSCRIPTION\nLOOP",
    footer_color: str = "#FF2A2A",
    format_type: str = "4:5",
) -> bool:
    """Helper function to render any registered template with custom text and background."""
    tmpl = TEMPLATES.get(template_name)
    if not tmpl:
        raise ValueError(f"Unknown template: {template_name}. Available: {list(TEMPLATES.keys())}")

    cfg = PosterHorrorConfig(
        bg_image_path=bg_image_path,
        headline_primary=headline_primary,
        headline_suffix=headline_suffix,
        headline_sub=headline_sub,
        footer_lead=footer_lead,
        footer_primary=footer_primary,
        footer_color=footer_color,
        format_type=format_type,
    )
    return tmpl.render(cfg, Path(output_path))


def main():
    parser = argparse.ArgumentParser(description="VoiceFi Factory Horror Action Poster Template Renderer")
    parser.add_argument("--template", default="poster_horror", choices=list(TEMPLATES.keys()), help="Template name")
    parser.add_argument("--bg", required=True, help="Path to background image")
    parser.add_argument("-o", "--output", required=True, help="Output PNG file path")
    parser.add_argument("--headline", default="SILICON VALLEY", help="Top primary headline text")
    parser.add_argument("--suffix", default="’S", help="Top stylized suffix / apostrophe")
    parser.add_argument("--sub", default="GOT YOU", help="Top secondary subtitle")
    parser.add_argument("--footer-lead", default="LOCKED IN THEIR", help="Bottom lead-in phrase")
    parser.add_argument("--footer-primary", default="SUBSCRIPTION\nLOOP", help="Bottom stacked punchword(s)")
    parser.add_argument("--color", default="#FF2A2A", help="Footer accent color (hex)")
    parser.add_argument("--format", default="4:5", choices=["4:5", "1:1"], help="Aspect ratio format")
    args = parser.parse_args()

    success = render_image(
        template_name=args.template,
        bg_image_path=args.bg,
        output_path=args.output,
        headline_primary=args.headline,
        headline_suffix=args.suffix,
        headline_sub=args.sub,
        footer_lead=args.footer_lead,
        footer_primary=args.footer_primary,
        footer_color=args.color,
        format_type=args.format,
    )

    if success:
        print(f"✅ Rendered template [{args.template}] successfully to: {args.output}")
    else:
        print(f"❌ Failed to render template [{args.template}]")
        sys.exit(1)


if __name__ == "__main__":
    main()
