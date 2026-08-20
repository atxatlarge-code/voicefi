"""
Standalone macOS .app Bundle & .dmg Disk Image Packaging Script.
Builds a native drag-and-drop installer: dist/Talk_2_Me_v1.0.0_macOS.dmg.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
ASSETS_DIR = ROOT_DIR / "assets"
APP_NAME = "Talk 2 Me"
APP_BUNDLE = DIST_DIR / f"{APP_NAME}.app"
DMG_NAME = "Talk_2_Me_v1.0.0_macOS.dmg"
DMG_PATH = DIST_DIR / DMG_NAME


def clean():
    print("🧹 Cleaning previous build artifacts...")
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    DIST_DIR.mkdir(exist_ok=True)


def build_app_bundle():
    print("📦 Building native Talk 2 Me.app bundle...")

    # PyInstaller specification for clean standalone menu bar app
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--icon",
        str(ASSETS_DIR / "icon.icns"),
        "--add-data",
        f"{ASSETS_DIR}/icon.icns:assets",
        "--osx-bundle-identifier",
        "com.lienlogicdata.talk2me",
        "--hidden-import",
        "rumps",
        "--hidden-import",
        "pynput",
        "--hidden-import",
        "faster_whisper",
        "--hidden-import",
        "sounddevice",
        "--hidden-import",
        "soundfile",
        "--hidden-import",
        "pydantic",
        "--hidden-import",
        "yaml",
        str(ROOT_DIR / "src" / "talk2me" / "cli.py"),
    ]

    subprocess.run(cmd, check=True, cwd=ROOT_DIR)

    # Configure Info.plist for macOS Menu Bar & Microphone Permissions
    plist_path = APP_BUNDLE / "Contents" / "Info.plist"
    if plist_path.is_file():
        print("⚙️ Setting macOS permissions & LSUIElement in Info.plist...")
        # Use /usr/libexec/PlistBuddy to add Apple permission descriptions
        plist_buddy = "/usr/libexec/PlistBuddy"
        subprocess.run([plist_buddy, "-c", "Add :LSUIElement bool true", str(plist_path)], stderr=subprocess.DEVNULL)
        subprocess.run(
            [
                plist_buddy,
                "-c",
                "Add :NSMicrophoneUsageDescription string 'Talk 2 Me requires microphone access to listen to your voice commands for AI agents.'",
                str(plist_path),
            ],
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                plist_buddy,
                "-c",
                "Add :NSSpeechRecognitionUsageDescription string 'Talk 2 Me uses speech recognition to convert your voice to text.'",
                str(plist_path),
            ],
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                plist_buddy,
                "-c",
                "Add :NSAppleEventsUsageDescription string 'Talk 2 Me needs AppleScript access to focus your AI agent and inject transcribed text.'",
                str(plist_path),
            ],
            stderr=subprocess.DEVNULL,
        )


def build_dmg():
    print(f"💿 Creating drag-and-drop macOS disk image: {DMG_NAME}...")
    dmg_staging = DIST_DIR / "dmg_staging"
    dmg_staging.mkdir(exist_ok=True)

    # 1. Copy Talk 2 Me.app to staging
    shutil.copytree(APP_BUNDLE, dmg_staging / f"{APP_NAME}.app", symlinks=True)

    # 2. Create Applications folder shortcut
    os.symlink("/Applications", str(dmg_staging / "Applications"))

    # 3. Copy License & Patent Notice
    patent_notice = dmg_staging / "PATENT_PENDING_NOTICE.txt"
    patent_notice.write_text(
        "Talk 2 Me™ — The Universal Voice Layer for AI Agents & Computer Use\n"
        "Copyright © 2026 LienLogic Data LLC. All Rights Reserved.\n\n"
        "PATENT PENDING — U.S. Patent Application No. 64/137,300\n"
        "For documentation & updates, visit: https://github.com/jaketrigg/talk-2-me\n"
    )

    # 4. Create DMG using native hdiutil
    temp_dmg = DIST_DIR / "temp.dmg"
    temp_dmg.unlink(missing_ok=True)
    DMG_PATH.unlink(missing_ok=True)

    subprocess.run(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(dmg_staging),
            "-ov",
            "-format",
            "UDRW",
            str(temp_dmg),
        ],
        check=True,
    )

    # Convert to compressed read-only DMG
    subprocess.run(
        [
            "hdiutil",
            "convert",
            str(temp_dmg),
            "-format",
            "UDZO",
            "-imagekey",
            "zlib-level=9",
            "-o",
            str(DMG_PATH),
        ],
        check=True,
    )

    temp_dmg.unlink(missing_ok=True)
    shutil.rmtree(dmg_staging, ignore_errors=True)
    print(f"🎉 SUCCESS: Generated {DMG_PATH} ({DMG_PATH.stat().st_size / (1024*1024):.1f} MB)")


if __name__ == "__main__":
    clean()
    build_app_bundle()
    build_dmg()
