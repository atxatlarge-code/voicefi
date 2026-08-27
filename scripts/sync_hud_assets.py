#!/usr/bin/env python3
"""
VoiceFi HUD & Assets Web Synchronizer
Synchronizes an explicit curated allowlist of AppKit Dynamic Island HUD screenshots,
vector marks, and web components between VoiceFi and voicefi.org.

Usage:
    python scripts/sync_hud_assets.py
    python scripts/sync_hud_assets.py --web-dir /path/to/voicefi.org
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

VOICEFI_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEB_DIR = VOICEFI_ROOT.parent / "voicefi.org"

# =========================================================================
# EXPLICIT ALLOWLIST OF ASSETS TO SYNC (No arbitrary globbing)
# =========================================================================

# 1. Native AppKit Dynamic Island 480x58 Screenshots
HUD_SCREENSHOTS = [
    "hud_idle.png",
    "hud_thinking.png",
    "hud_working.png",
    "hud_speaking.png",
    "hud_listening.png",
    "hud_listening_stream.png",
    "hud_new_conversation.png",
    "hud_editing.png",
]

# 2. Native 256x256 Vector Status Logos
LOGO_ICONS = [
    "logo_idle_256px.png",
    "logo_thinking_256px.png",
    "logo_working_256px.png",
    "logo_speaking_256px.png",
    "logo_listening_256px.png",
    "logo_editing_256px.png",
    "logo_new_256px.png",
]

# 3. Core Brand SVG Vectors & High-DPI Icons
BRAND_ASSETS = [
    "logo-voicefi-mark.svg",
    "logo-voicefi-mark-light.svg",
    "logo-voicefi-mark-dark.svg",
    "logo-voicefi-character-light.svg",
    "logo-voicefi-character-dark.svg",
    "logo-voicefi-symbol.svg",
    "logo-voicefi-reactive.svg",
    "logo-antigravity.svg",
    "logo-obsidian.svg",
    "icon-master.svg",
    "og-image.png",
]

# 4. Shared Web HUD Controller & Stylesheet
WEB_COMPONENTS = [
    "voicefi-hud.js",
    "voicefi-hud.css",
]


def sync_hud_assets(web_dir: Path, skip_capture: bool = False) -> bool:
    web_dir = Path(web_dir).resolve()
    web_assets_dir = web_dir / "assets"

    if not web_assets_dir.exists():
        print(f"❌ Error: Target web assets directory not found at {web_assets_dir}")
        return False

    print(f"🔄 Synchronizing VoiceFi HUD components & assets to: {web_dir}")

    # 1. Regenerate native macOS AppKit screenshots via capture_hud_states.py
    if not skip_capture:
        capture_script = VOICEFI_ROOT / "scripts" / "capture_hud_states.py"
        if capture_script.exists():
            print("\n📸 [1/3] Generating native AppKit HUD state screenshots...")
            try:
                subprocess.run([sys.executable, str(capture_script)], check=True, cwd=str(VOICEFI_ROOT))
            except subprocess.CalledProcessError as e:
                print(f"⚠️ Warning: HUD screenshot capture returned code {e.returncode}")
        else:
            print("⚠️ capture_hud_states.py not found, skipping screenshot generation.")
    else:
        print("\n⏩ [1/3] Skipping native AppKit capture (--skip-capture)")

    # 2. Copy Shared Web HUD Controller & CSS (Explicit list)
    print("\n📦 [2/3] Copying shared Web HUD components...")
    companion_static = VOICEFI_ROOT / "src" / "voicefi" / "companion" / "static"
    for filename in WEB_COMPONENTS:
        src = companion_static / filename
        dst = web_assets_dir / filename
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✓ Synced {filename} -> assets/{filename}")
        else:
            print(f"  ⚠️ Warning: Component not found: {src}")

    # 3. Copy Native HUD Screenshots and Vector Logos (Explicit allowlist)
    print("\n🎨 [3/3] Copying curated HUD screenshots & brand assets...")
    screenshots_dir = VOICEFI_ROOT / "assets" / "screenshots"
    assets_dir = VOICEFI_ROOT / "assets"
    copied_count = 0

    # Sync AppKit screenshots
    for filename in HUD_SCREENSHOTS:
        src = screenshots_dir / filename
        if src.exists():
            shutil.copy2(src, web_assets_dir / filename)
            copied_count += 1
        else:
            print(f"  ⚠️ Warning: Missing screenshot: {filename}")

    # Sync status logo icons
    for filename in LOGO_ICONS:
        src = screenshots_dir / filename
        if src.exists():
            shutil.copy2(src, web_assets_dir / filename)
            copied_count += 1
        else:
            print(f"  ⚠️ Warning: Missing logo icon: {filename}")

    # Sync brand SVGs
    for filename in BRAND_ASSETS:
        src = assets_dir / filename
        if src.exists():
            shutil.copy2(src, web_assets_dir / filename)
            copied_count += 1
        else:
            print(f"  ⚠️ Warning: Missing brand asset: {filename}")

    print(f"  ✓ Synced {copied_count} explicit curated assets to {web_assets_dir.relative_to(web_dir.parent)}")
    print("\n✨ HUD & Web Assets Synchronization Complete (Explicit Allowlist)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Synchronize VoiceFi HUD components and assets to voicefi.org")
    parser.add_argument(
        "--web-dir",
        type=Path,
        default=DEFAULT_WEB_DIR,
        help=f"Path to voicefi.org repo (default: {DEFAULT_WEB_DIR})",
    )
    parser.add_argument(
        "--skip-capture",
        action="store_true",
        help="Skip re-capturing AppKit screenshots and only copy static assets",
    )
    args = parser.parse_args()

    success = sync_hud_assets(args.web_dir, args.skip_capture)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
