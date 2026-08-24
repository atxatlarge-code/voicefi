"""
Standalone macOS .app Bundle & .dmg Disk Image Packaging Script.
Builds a native drag-and-drop installer: dist/Voicegency_v1.0.0_macOS.dmg.
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
APP_NAME = "VoiceFi"
APP_BUNDLE = DIST_DIR / f"{APP_NAME}.app"
DMG_NAME = "VoiceFi_v1.0.0_macOS.dmg"
DMG_PATH = DIST_DIR / DMG_NAME
ICON_FILE = ASSETS_DIR / "icon.icns"
SPEC_FILE = ROOT_DIR / "VoiceFi.spec"


def clean():
    print("🧹 Cleaning previous build artifacts...")
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    DIST_DIR.mkdir(exist_ok=True)


def build_app_bundle():
    print("📦 Building native Voicegency.app bundle with PyInstaller...")

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
        str(ICON_FILE),
        "--add-data",
        f"{ICON_FILE}:assets",
        "--osx-bundle-identifier",
        "com.lienlogicdata.voicegency",
        "--paths",
        "src",
        "--collect-all",
        "sounddevice",
        "--collect-all",
        "soundfile",
        "--collect-all",
        "edge_tts",
        "--collect-all",
        "faster_whisper",
        "--collect-all",
        "ctranslate2",
        "--collect-all",
        "aiohttp",
        "--collect-all",
        "qrcode",
        "--collect-all",
        "voicegency",
        "--hidden-import",
        "rumps",
        "--hidden-import",
        "pynput",
        "--hidden-import",
        "pynput.keyboard._darwin",
        "--hidden-import",
        "pynput.mouse._darwin",
        "--hidden-import",
        "AppKit",
        "--hidden-import",
        "Cocoa",
        "--hidden-import",
        "objc",
        "--hidden-import",
        "Foundation",
        "--hidden-import",
        "yaml",
        "--hidden-import",
        "pydantic",
        "--hidden-import",
        "requests",
        "--hidden-import",
        "numpy",
        str(ROOT_DIR / "src" / "voicegency" / "cli.py"),
    ]

    subprocess.run(cmd, check=True, cwd=ROOT_DIR)

    # Configure Info.plist for macOS Menu Bar & Required Permissions
    plist_path = APP_BUNDLE / "Contents" / "Info.plist"
    if plist_path.is_file():
        print("⚙️ Configuring macOS permissions and LSUIElement in Info.plist...")
        plist_buddy = "/usr/libexec/PlistBuddy"

        def set_plist_val(key_type, key_name, value):
            # Try Delete first to allow overwriting if key already exists
            subprocess.run([plist_buddy, "-c", f"Delete :{key_name}", str(plist_path)], stderr=subprocess.DEVNULL)
            subprocess.run([plist_buddy, "-c", f"Add :{key_name} {key_type} {value}", str(plist_path)], stderr=subprocess.DEVNULL)

        set_plist_val("bool", "LSUIElement", "true")
        set_plist_val("bool", "NSHighResolutionCapable", "true")
        set_plist_val("string", "CFBundleDisplayName", "'Voicegency'")
        set_plist_val("string", "NSMicrophoneUsageDescription", "'Voicegency requires microphone access to listen to your voice commands for AI agents.'")
        set_plist_val("string", "NSSpeechRecognitionUsageDescription", "'Voicegency uses speech recognition to convert your voice to text.'")
        set_plist_val("string", "NSAppleEventsUsageDescription", "'Voicegency needs AppleScript access to focus your AI agent and inject transcribed text.'")
        set_plist_val("string", "NSAccessibilityUsageDescription", "'Voicegency uses accessibility features to listen for global hotkeys and inject text into active applications.'")


def build_dmg():
    print(f"💿 Creating drag-and-drop macOS disk image: {DMG_NAME}...")
    dmg_staging = DIST_DIR / "dmg_staging"
    shutil.rmtree(dmg_staging, ignore_errors=True)
    dmg_staging.mkdir(exist_ok=True)

    # 1. Copy Voicegency.app to staging
    shutil.copytree(APP_BUNDLE, dmg_staging / f"{APP_NAME}.app", symlinks=True)

    # 2. Create Applications folder shortcut
    os.symlink("/Applications", str(dmg_staging / "Applications"))

    # 3. Copy License, Patent Notice & Quickstart guide
    patent_notice = dmg_staging / "PATENT_PENDING_NOTICE.txt"
    patent_notice.write_text(
        "Voicegency™ — Giving your agents a voice, and your voice agency.\n"
        "Copyright © 2026 LienLogic Data LLC. All Rights Reserved.\n\n"
        "PATENT PENDING — U.S. Patent Application No. 64/137,300\n\n"
        "QUICKSTART:\n"
        "1. Drag 'Voicegency.app' into the Applications folder.\n"
        "2. Launch Voicegency from Applications or Spotlight.\n"
        "3. The 🎙️ icon will appear in your macOS menu bar.\n"
        "4. Press Control + T to dictate into any window, or ` (backtick) to jump to your active agent.\n\n"
        "For documentation & updates, visit: https://voicegency.com\n"
    )

    # 4. Optional Volume Icon
    if ICON_FILE.is_file():
        volume_icon = dmg_staging / ".VolumeIcon.icns"
        shutil.copy(ICON_FILE, volume_icon)
        setfile_path = shutil.which("SetFile")
        if setfile_path:
            subprocess.run([setfile_path, "-c", "icnC", str(volume_icon)], stderr=subprocess.DEVNULL)
            subprocess.run([setfile_path, "-a", "C", str(dmg_staging)], stderr=subprocess.DEVNULL)

    # 5. Create DMG using native hdiutil
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


def verify_dmg():
    print(f"🔍 Verifying disk image {DMG_NAME}...")
    mount_point = DIST_DIR / "verify_mount"
    shutil.rmtree(mount_point, ignore_errors=True)
    mount_point.mkdir(exist_ok=True)

    try:
        # Attach DMG
        subprocess.run(
            ["hdiutil", "attach", str(DMG_PATH), "-mountpoint", str(mount_point), "-nobrowse", "-quiet"],
            check=True,
        )

        app_in_dmg = mount_point / f"{APP_NAME}.app"
        app_symlink = mount_point / "Applications"
        notice = mount_point / "PATENT_PENDING_NOTICE.txt"

        assert app_in_dmg.exists(), "Voicegency.app missing in DMG"
        assert app_symlink.is_symlink(), "Applications symlink missing in DMG"
        assert notice.exists(), "PATENT_PENDING_NOTICE.txt missing in DMG"
        print("✅ Verified DMG contents: App bundle, Applications shortcut, and Quickstart guide present.")

        # Test the executable inside the DMG
        dmg_exe = app_in_dmg / "Contents" / "MacOS" / APP_NAME
        assert dmg_exe.is_file(), "Executable binary missing inside DMG .app"
        result = subprocess.run([str(dmg_exe), "info"], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, f"Executable failed with code {result.returncode}: {result.stderr}"
        print("✅ Verified binary execution from DMG volume.")

    finally:
        subprocess.run(["hdiutil", "detach", str(mount_point), "-force", "-quiet"], stderr=subprocess.DEVNULL)
        shutil.rmtree(mount_point, ignore_errors=True)


if __name__ == "__main__":
    clean()
    build_app_bundle()
    build_dmg()
    verify_dmg()
