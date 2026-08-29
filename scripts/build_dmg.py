"""
Standalone macOS .app Bundle & .dmg Disk Image Packaging Script.
Builds a native drag-and-drop installer: dist/VoiceFi_v1.0.0_macOS.dmg.
Supports optional Developer ID code signing & Apple notarization.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
ASSETS_DIR = ROOT_DIR / "assets"
ENTITLEMENTS_FILE = ROOT_DIR / "entitlements.plist"
APP_NAME = "VoiceFi"
APP_BUNDLE = DIST_DIR / f"{APP_NAME}.app"
DMG_NAME = "VoiceFi_v1.0.0_macOS.dmg"
DMG_PATH = DIST_DIR / DMG_NAME
ICON_FILE = ASSETS_DIR / "VoiceFi.icns"


def clean():
    print("🧹 Cleaning previous build artifacts...")
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    DIST_DIR.mkdir(exist_ok=True)


def build_app_bundle():
    print("📦 Building native VoiceFi.app bundle with PyInstaller...")

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
        "org.voicefi.app",
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
        "voicefi",
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
        str(ROOT_DIR / "src" / "voicefi" / "cli.py"),
    ]

    subprocess.run(cmd, check=True, cwd=ROOT_DIR)

    # Configure Info.plist for macOS Menu Bar & Required Permissions
    plist_path = APP_BUNDLE / "Contents" / "Info.plist"
    if plist_path.is_file():
        print("⚙️ Configuring macOS permissions and LSUIElement in Info.plist...")
        plist_buddy = "/usr/libexec/PlistBuddy"

        def set_plist_val(key_type, key_name, value):
            subprocess.run([plist_buddy, "-c", f"Delete :{key_name}", str(plist_path)], stderr=subprocess.DEVNULL)
            subprocess.run([plist_buddy, "-c", f"Add :{key_name} {key_type} {value}", str(plist_path)], stderr=subprocess.DEVNULL)

        set_plist_val("bool", "LSUIElement", "true")
        set_plist_val("bool", "NSHighResolutionCapable", "true")
        set_plist_val("string", "CFBundleDisplayName", "'VoiceFi'")
        set_plist_val("string", "NSMicrophoneUsageDescription", "'VoiceFi requires microphone access to listen to your voice commands for AI agents.'")
        set_plist_val("string", "NSSpeechRecognitionUsageDescription", "'VoiceFi uses speech recognition to convert your voice to text.'")
        set_plist_val("string", "NSAppleEventsUsageDescription", "'VoiceFi needs AppleScript access to focus your AI agent and inject transcribed text.'")
        set_plist_val("string", "NSAccessibilityUsageDescription", "'VoiceFi uses accessibility features to listen for global hotkeys and inject text into active applications.'")


def sign_app_bundle(identity: str):
    print(f"🔏 Signing VoiceFi.app with identity: '{identity}'...")
    cmd = [
        "codesign",
        "--deep",
        "--force",
        "--options",
        "runtime",
        "--sign",
        identity,
    ]
    if ENTITLEMENTS_FILE.is_file():
        cmd.extend(["--entitlements", str(ENTITLEMENTS_FILE)])
    cmd.append(str(APP_BUNDLE))

    subprocess.run(cmd, check=True)
    print("✅ App bundle signed with hardened runtime.")


def build_dmg(identity: str = None):
    print(f"💿 Creating drag-and-drop macOS disk image: {DMG_NAME}...")
    dmg_staging = DIST_DIR / "dmg_staging"
    shutil.rmtree(dmg_staging, ignore_errors=True)
    dmg_staging.mkdir(exist_ok=True)

    # 1. Copy VoiceFi.app to staging
    shutil.copytree(APP_BUNDLE, dmg_staging / f"{APP_NAME}.app", symlinks=True)

    # 2. Create Applications folder shortcut
    os.symlink("/Applications", str(dmg_staging / "Applications"))

    # 3. Copy License & Quickstart guide
    quickstart = dmg_staging / "QUICKSTART.txt"
    quickstart.write_text(
        "VoiceFi™ — Universal Voice Layer for AI Agents & macOS\n\n"
        "QUICKSTART:\n"
        "1. Drag 'VoiceFi.app' into the Applications folder.\n"
        "2. Launch VoiceFi from Applications or Spotlight.\n"
        "3. The 🎙️ icon will appear in your macOS menu bar.\n"
        "4. Press Control + T to dictate into any window or agent.\n\n"
        "Documentation & Updates: https://voicefi.org\n"
        "Support: team@voicefi.org\n"
    )

    # 4. Volume Icon
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

    # Sign the DMG if identity provided
    if identity:
        print(f"🔏 Signing {DMG_NAME} with Developer ID...")
        subprocess.run(["codesign", "--sign", identity, str(DMG_PATH)], check=True)

    print(f"🎉 SUCCESS: Generated {DMG_PATH} ({DMG_PATH.stat().st_size / (1024*1024):.1f} MB)")


def notarize_dmg(keychain_profile: str):
    print(f"☁️ Submitting {DMG_NAME} to Apple Notary Service (profile: {keychain_profile})...")
    subprocess.run(
        [
            "xcrun",
            "notarytool",
            "submit",
            str(DMG_PATH),
            "--keychain-profile",
            keychain_profile,
            "--wait",
        ],
        check=True,
    )
    print("📎 Stapling notarization ticket to DMG...")
    subprocess.run(["xcrun", "stapler", "staple", str(DMG_PATH)], check=True)
    print("🎉 Notarization and ticket stapling complete!")


def verify_dmg():
    print(f"🔍 Verifying disk image {DMG_NAME}...")
    mount_point = DIST_DIR / "verify_mount"
    shutil.rmtree(mount_point, ignore_errors=True)
    mount_point.mkdir(exist_ok=True)

    try:
        subprocess.run(
            ["hdiutil", "attach", str(DMG_PATH), "-mountpoint", str(mount_point), "-nobrowse", "-quiet"],
            check=True,
        )

        app_in_dmg = mount_point / f"{APP_NAME}.app"
        app_symlink = mount_point / "Applications"
        quickstart = mount_point / "QUICKSTART.txt"

        assert app_in_dmg.exists(), f"{APP_NAME}.app missing in DMG"
        assert app_symlink.is_symlink(), "Applications symlink missing in DMG"
        assert quickstart.exists(), "QUICKSTART.txt missing in DMG"
        print("✅ Verified DMG contents: App bundle, Applications shortcut, and Quickstart guide present.")

        dmg_exe = app_in_dmg / "Contents" / "MacOS" / APP_NAME
        assert dmg_exe.is_file(), "Executable binary missing inside DMG .app"
        result = subprocess.run([str(dmg_exe), "--help"], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f"Executable failed with code {result.returncode}: {result.stderr}"
        print("✅ Verified binary execution from DMG volume.")

    finally:
        subprocess.run(["hdiutil", "detach", str(mount_point), "-force", "-quiet"], stderr=subprocess.DEVNULL)
        shutil.rmtree(mount_point, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build, Sign, and Notarize VoiceFi macOS DMG")
    parser.add_argument("--sign", type=str, default=None, help="Developer ID Application identity (e.g. 'Developer ID Application: ...')")
    parser.add_argument("--notarize", type=str, default=None, help="Keychain profile for notarytool (e.g. 'voicefi-notary')")
    parser.add_argument("--skip-app", action="store_true", help="Skip PyInstaller and rebuild DMG from existing dist/VoiceFi.app")
    args = parser.parse_args()

    if not args.skip_app:
        clean()
        build_app_bundle()
        if args.sign:
            sign_app_bundle(args.sign)

    build_dmg(identity=args.sign)

    if args.notarize:
        notarize_dmg(args.notarize)

    verify_dmg()
