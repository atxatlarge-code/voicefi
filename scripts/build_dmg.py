"""
Standalone macOS .app Bundle & .dmg Disk Image Packaging Script.
Builds a native drag-and-drop installer: dist/VoiceFi_v{version}_macOS.dmg.
Supports Developer ID code signing, Hardened Runtime, and Apple Notarization.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
ASSETS_DIR = ROOT_DIR / "assets"
SRC_DIR = ROOT_DIR / "src"
ENTITLEMENTS_FILE = ROOT_DIR / "entitlements.plist"
APP_NAME = "VoiceFi"
APP_BUNDLE = DIST_DIR / f"{APP_NAME}.app"
ICON_FILE = ASSETS_DIR / "VoiceFi.icns"
MENU_BAR_ICON = ASSETS_DIR / "voicefi-menu-bar-icon.svg"


def get_version(override: str = None) -> str:
    if override:
        return override.lstrip("v")
    try:
        sys.path.insert(0, str(SRC_DIR))
        from voicefi import __version__

        return str(__version__).lstrip("v")
    except Exception:
        return "0.1.0"


def clean():
    print("🧹 Cleaning previous build artifacts...")
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    shutil.rmtree(BUILD_DIR, ignore_errors=True)
    DIST_DIR.mkdir(exist_ok=True)


def build_app_bundle(version: str = "0.1.0"):
    print(f"📦 Building native VoiceFi.app bundle (v{version}) with PyInstaller...")

    add_data = []
    if ICON_FILE.is_file():
        add_data.extend(["--add-data", f"{ICON_FILE}:assets"])
    if MENU_BAR_ICON.is_file():
        add_data.extend(["--add-data", f"{MENU_BAR_ICON}:assets"])

    # Embed silero vad and other package assets if present
    vad_asset = SRC_DIR / "voicefi" / "assets"
    if vad_asset.is_dir():
        add_data.extend(["--add-data", f"{vad_asset}:voicefi/assets"])

    # Embed companion static PWA files
    companion_static = SRC_DIR / "voicefi" / "companion" / "static"
    if companion_static.is_dir():
        add_data.extend(["--add-data", f"{companion_static}:voicefi/companion/static"])

    py_exec = sys.executable
    venv_py = ROOT_DIR / ".venv" / "bin" / "python3"
    if venv_py.is_file():
        py_exec = str(venv_py)

    cmd = [
        py_exec,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON_FILE),
        "--osx-bundle-identifier",
        "org.voicefi.app",
        "--paths",
        "src",
        *add_data,
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
        str(SRC_DIR / "voicefi" / "cli.py"),
    ]

    subprocess.run(cmd, check=True, cwd=ROOT_DIR)

    # Configure Info.plist for macOS Menu Bar & Required Permissions
    plist_path = APP_BUNDLE / "Contents" / "Info.plist"
    if plist_path.is_file():
        print("⚙️ Configuring macOS permissions and LSUIElement in Info.plist...")
        plist_buddy = "/usr/libexec/PlistBuddy"

        def set_plist_val(key_type, key_name, value):
            subprocess.run(
                [plist_buddy, "-c", f"Delete :{key_name}", str(plist_path)],
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [plist_buddy, "-c", f"Add :{key_name} {key_type} {value}", str(plist_path)],
                stderr=subprocess.DEVNULL,
            )

        set_plist_val("bool", "LSUIElement", "true")
        set_plist_val("bool", "NSHighResolutionCapable", "true")
        set_plist_val("string", "CFBundleDisplayName", "'VoiceFi'")
        set_plist_val("string", "CFBundleShortVersionString", f"'{version}'")
        set_plist_val("string", "CFBundleVersion", f"'{version}'")
        set_plist_val(
            "string",
            "NSMicrophoneUsageDescription",
            "'VoiceFi requires microphone access to listen to your voice commands for AI agents.'",
        )
        set_plist_val(
            "string",
            "NSSpeechRecognitionUsageDescription",
            "'VoiceFi uses speech recognition to convert your voice to text.'",
        )
        set_plist_val(
            "string",
            "NSAppleEventsUsageDescription",
            "'VoiceFi needs AppleScript access to focus your AI agent and inject transcribed text.'",
        )
        set_plist_val(
            "string",
            "NSAccessibilityUsageDescription",
            "'VoiceFi uses accessibility features to listen for global hotkeys (Ctrl+T) and inject text into active applications.'",
        )

        # Re-sign ad-hoc if not signed with identity to restore sealed resource signature
        subprocess.run(["codesign", "--deep", "--force", "-s", "-", str(APP_BUNDLE)], stderr=subprocess.DEVNULL)



def sign_app_bundle(identity: str):
    print(f"🔏 Signing VoiceFi.app with identity: '{identity}'...")

    # Sign embedded binaries & dylibs inside the app bundle
    frameworks_dir = APP_BUNDLE / "Contents" / "Frameworks"
    if frameworks_dir.is_dir():
        for item in frameworks_dir.rglob("*"):
            if item.is_file() and (item.suffix in (".dylib", ".so") or os.access(item, os.X_OK)):
                cmd = ["codesign", "--force", "--options", "runtime", "--sign", identity, str(item)]
                if ENTITLEMENTS_FILE.is_file():
                    cmd.extend(["--entitlements", str(ENTITLEMENTS_FILE)])
                subprocess.run(cmd, stderr=subprocess.DEVNULL)

    # Sign the top-level app bundle
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


def build_dmg(version: str, identity: str = None) -> Path:
    dmg_name = f"VoiceFi_v{version}_macOS.dmg"
    dmg_path = DIST_DIR / dmg_name
    print(f"💿 Creating drag-and-drop macOS disk image: {dmg_name}...")

    dmg_staging = DIST_DIR / "dmg_staging"
    shutil.rmtree(dmg_staging, ignore_errors=True)
    dmg_staging.mkdir(exist_ok=True)

    # 1. Copy VoiceFi.app to staging
    shutil.copytree(APP_BUNDLE, dmg_staging / f"{APP_NAME}.app", symlinks=True)

    # 2. Create Applications folder shortcut
    os.symlink("/Applications", str(dmg_staging / "Applications"))

    # 3. Copy Quickstart guide
    quickstart = dmg_staging / "QUICKSTART.txt"
    quickstart.write_text(
        "VoiceFi™ — Universal Voice Layer for AI Agents & macOS\n\n"
        "QUICKSTART:\n"
        "1. Drag 'VoiceFi.app' into the Applications folder.\n"
        "2. Launch VoiceFi from Applications or Spotlight.\n"
        "3. The 🎙️ icon will appear in your macOS menu bar.\n"
        "4. Press Control + T to dictate into any window or agent.\n\n"
        "14-Day Free Pro Trial automatically active upon first launch.\n\n"
        "Documentation & Updates: https://voicefi.org\n"
        "License Keys & Pro: https://voicefi.app\n"
        "Support: talktome@voicefi.org\n"
    )

    # 4. Copy High-DPI DMG Background
    dmg_bg_file = ASSETS_DIR / "dmg_background.png"
    if not dmg_bg_file.is_file():
        try:
            from scripts.render_dmg_background import render_dmg_background
            render_dmg_background()
        except Exception:
            pass

    bg_dir = dmg_staging / ".background"
    bg_dir.mkdir(exist_ok=True)
    if dmg_bg_file.is_file():
        shutil.copy(dmg_bg_file, bg_dir / "background.png")

    # 5. Volume Icon
    if ICON_FILE.is_file():
        volume_icon = dmg_staging / ".VolumeIcon.icns"
        shutil.copy(ICON_FILE, volume_icon)
        setfile_path = shutil.which("SetFile")
        if setfile_path:
            subprocess.run(
                [setfile_path, "-c", "icnC", str(volume_icon)], stderr=subprocess.DEVNULL
            )
            subprocess.run([setfile_path, "-a", "C", str(dmg_staging)], stderr=subprocess.DEVNULL)
            subprocess.run([setfile_path, "-a", "V", str(bg_dir)], stderr=subprocess.DEVNULL)

    # 6. Create temporary read-write DMG using native hdiutil
    temp_dmg = DIST_DIR / "temp.dmg"
    temp_dmg.unlink(missing_ok=True)
    dmg_path.unlink(missing_ok=True)

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

    # 7. Mount temporary DMG and configure Finder window layout & positions via AppleScript
    print("🎨 Styling Finder drag-and-drop window layout...")
    mount_output = subprocess.run(
        ["hdiutil", "attach", str(temp_dmg), "-noautoopen", "-nobrowse"],
        capture_output=True,
        text=True,
        check=True,
    )
    mount_point = None
    for line in mount_output.stdout.splitlines():
        if f"/Volumes/{APP_NAME}" in line:
            mount_point = line.split()[-1]
            break
    if not mount_point:
        mount_point = f"/Volumes/{APP_NAME}"

    apple_script = f"""
    tell application "Finder"
        tell disk "{APP_NAME}"
            open
            set current view of container window to icon view
            set toolbar visible of container window to false
            set statusbar visible of container window to false
            set the bounds of container window to {{280, 120, 940, 540}}
            set theViewOptions to the icon view options of container window
            set arrangement of theViewOptions to not arranged
            set icon size of theViewOptions to 120
            set text size of theViewOptions to 12
            try
                set background picture of theViewOptions to file ".background:background.png"
            end try
            set position of item "{APP_NAME}.app" of container window to {{170, 220}}
            set position of item "Applications" of container window to {{490, 220}}
            try
                set position of item "QUICKSTART.txt" of container window to {{330, 365}}
            end try
            close
            open
            update without registering applications
            delay 1
        end tell
    end tell
    """
    try:
        subprocess.run(["osascript", "-e", apple_script], capture_output=True, text=True, timeout=12)
        print("  ✓ Configured Finder window layout and icon positions.")
    except Exception as e:
        print(f"  ⚠️ Note on AppleScript Finder styling: {e}")
    finally:
        # Detach temporary volume
        subprocess.run(["hdiutil", "detach", mount_point, "-force", "-quiet"], stderr=subprocess.DEVNULL)
        time.sleep(1)

    # 8. Convert to compressed read-only DMG
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
            str(dmg_path),
        ],
        check=True,
    )

    temp_dmg.unlink(missing_ok=True)
    shutil.rmtree(dmg_staging, ignore_errors=True)

    # Sign the DMG disk image if identity provided
    if identity:
        print(f"🔏 Signing {dmg_name} with Developer ID...")
        subprocess.run(["codesign", "--sign", identity, str(dmg_path)], check=True)

    print(f"🎉 SUCCESS: Generated {dmg_path} ({dmg_path.stat().st_size / (1024 * 1024):.1f} MB)")
    return dmg_path


def notarize_dmg(dmg_path: Path, keychain_profile: str = None, apple_id: str = None, team_id: str = None, password: str = None):
    print(f"☁️ Submitting {dmg_path.name} to Apple Notary Service...")
    cmd = ["xcrun", "notarytool", "submit", str(dmg_path), "--wait"]
    if keychain_profile:
        cmd.extend(["--keychain-profile", keychain_profile])
    elif apple_id and team_id and password:
        cmd.extend(["--apple-id", apple_id, "--team-id", team_id, "--password", password])
    else:
        raise ValueError("Must provide either keychain_profile or apple_id/team_id/password for notarization")

    subprocess.run(cmd, check=True)
    print("📎 Stapling notarization ticket to DMG...")
    subprocess.run(["xcrun", "stapler", "staple", str(dmg_path)], check=True)
    print("🎉 Notarization and ticket stapling complete!")


def verify_dmg(dmg_path: Path):
    print(f"🔍 Verifying disk image {dmg_path.name}...")
    mount_point = DIST_DIR / "verify_mount"
    shutil.rmtree(mount_point, ignore_errors=True)
    mount_point.mkdir(exist_ok=True)

    try:
        subprocess.run(
            [
                "hdiutil",
                "attach",
                str(dmg_path),
                "-mountpoint",
                str(mount_point),
                "-nobrowse",
                "-quiet",
            ],
            check=True,
        )

        app_in_dmg = mount_point / f"{APP_NAME}.app"
        app_symlink = mount_point / "Applications"
        quickstart = mount_point / "QUICKSTART.txt"

        assert app_in_dmg.exists(), f"{APP_NAME}.app missing in DMG"
        assert app_symlink.is_symlink(), "Applications symlink missing in DMG"
        assert quickstart.exists(), "QUICKSTART.txt missing in DMG"
        print(
            "✅ Verified DMG contents: App bundle, Applications shortcut, and Quickstart guide present."
        )

        dmg_exe = app_in_dmg / "Contents" / "MacOS" / APP_NAME
        assert dmg_exe.is_file(), "Executable binary missing inside DMG .app"
        result = subprocess.run(
            [str(dmg_exe), "--help"], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"Executable failed with code {result.returncode}: {result.stderr}"
        )
        print("✅ Verified binary execution from DMG volume.")

    finally:
        subprocess.run(
            ["hdiutil", "detach", str(mount_point), "-force", "-quiet"], stderr=subprocess.DEVNULL
        )
        shutil.rmtree(mount_point, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build, Sign, and Notarize VoiceFi macOS DMG")
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Release version string (defaults to voicefi.__version__)",
    )
    parser.add_argument(
        "--sign",
        type=str,
        default=None,
        help="Developer ID Application identity (e.g. 'Developer ID Application: ...')",
    )
    parser.add_argument(
        "--notarize",
        type=str,
        default=None,
        help="Keychain profile for notarytool (e.g. 'voicefi-notary')",
    )
    parser.add_argument(
        "--apple-id",
        type=str,
        default=None,
        help="Apple ID email for notarytool",
    )
    parser.add_argument(
        "--team-id",
        type=str,
        default=None,
        help="Apple Developer Team ID for notarytool",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="App-specific password for notarytool",
    )
    parser.add_argument(
        "--skip-app",
        action="store_true",
        help="Skip PyInstaller and rebuild DMG from existing dist/VoiceFi.app",
    )
    args = parser.parse_args()

    ver = get_version(args.version)
    sign_identity = args.sign
    if not sign_identity:
        try:
            res = subprocess.run(
                ["security", "find-identity", "-p", "codesigning", "-v"],
                capture_output=True,
                text=True,
            )
            for line in res.stdout.splitlines():
                if "Developer ID Application:" in line:
                    start = line.find('"')
                    end = line.rfind('"')
                    if start != -1 and end != -1:
                        sign_identity = line[start + 1 : end]
                        print(f"🔑 Auto-detected Developer ID identity: {sign_identity}")
                        break
        except Exception:
            pass

    if not args.skip_app:
        clean()
        build_app_bundle(version=ver)
        if sign_identity:
            sign_app_bundle(sign_identity)

    dmg_file = build_dmg(version=ver, identity=sign_identity)

    if args.notarize or (args.apple_id and args.team_id and args.password):
        notarize_dmg(
            dmg_file,
            keychain_profile=args.notarize,
            apple_id=args.apple_id,
            team_id=args.team_id,
            password=args.password,
        )

    verify_dmg(dmg_file)

