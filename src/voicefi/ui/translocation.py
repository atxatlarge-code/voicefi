"""
macOS App Translocation & Disk Image Relocation Guard for VoiceFi.
Detects when VoiceFi is executed from a read-only DMG volume or quarantined
App Translocation path and offers a 1-click move to /Applications.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional


def is_headless() -> bool:
    """Check if running in headless testing environment."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("VOICEFI_TESTING") == "1"
    )


def get_bundle_path() -> Optional[Path]:
    """
    Return the Path to the outer .app bundle if running as a frozen PyInstaller bundle.
    Example: /Applications/VoiceFi.app
    """
    try:
        exec_path = Path(sys.executable).resolve()
        # Look for standard macOS bundle structure (.app/Contents/MacOS/...)
        for parent in [exec_path] + list(exec_path.parents):
            if parent.suffix.lower() == ".app":
                return parent
    except Exception:
        pass
    return None


def is_running_from_dmg_or_translocation(bundle_path: Optional[Path] = None) -> bool:
    """
    Check if the running bundle is located in a disk image (/Volumes/...)
    or subjected to macOS Gatekeeper App Translocation.
    """
    target = bundle_path or get_bundle_path()
    if not target:
        return False

    target_str = str(target.resolve())

    # 1. Standard application directories (Valid install locations)
    system_apps = "/Applications/"
    user_apps = str(Path.home() / "Applications") + "/"

    if target_str.startswith(system_apps) or target_str.startswith(user_apps):
        return False

    # 2. Disk Image / Volumes check
    if "/Volumes/" in target_str:
        return True

    # 3. macOS App Translocation check (randomized sandbox folder)
    if "AppTranslocation" in target_str:
        return True

    # 4. Downloads folder direct execution
    user_downloads = str(Path.home() / "Downloads") + "/"
    if target_str.startswith(user_downloads):
        return True

    return False


def move_to_applications(
    bundle_path: Optional[Path] = None,
    target_dir: Optional[Path] = None,
    relaunch: bool = True,
) -> bool:
    """
    Copy VoiceFi.app to /Applications, remove quarantine xattrs,
    detach the DMG volume, and optionally relaunch the installed copy.
    """
    source = bundle_path or get_bundle_path()
    if not source or not source.is_dir():
        return False

    target_root = target_dir or Path("/Applications")
    if not target_root.exists():
        try:
            target_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            # Fallback to ~/Applications if system /Applications is inaccessible
            target_root = Path.home() / "Applications"
            target_root.mkdir(parents=True, exist_ok=True)

    dest_bundle = target_root / source.name

    print(f"📦 [Translocation] Relocating {source} -> {dest_bundle}...")

    # Identify source volume for clean detachment later
    volume_to_detach = None
    try:
        resolved_src = str(source.resolve())
        if "/Volumes/" in resolved_src:
            # e.g. /Volumes/VoiceFi
            parts = resolved_src.split("/Volumes/")
            if len(parts) > 1:
                vol_name = parts[1].split("/")[0]
                volume_to_detach = f"/Volumes/{vol_name}"
    except Exception:
        pass

    try:
        # If target already exists, remove it cleanly
        if dest_bundle.exists():
            shutil.rmtree(dest_bundle, ignore_errors=True)

        # Copy bundle
        shutil.copytree(source, dest_bundle, symlinks=True)

        # Remove Gatekeeper quarantine xattr
        try:
            subprocess.run(
                ["xattr", "-dr", "com.apple.quarantine", str(dest_bundle)],
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass

        # Relaunch from new location
        if relaunch:
            print(f"🚀 [Translocation] Launching installed app from {dest_bundle}...")
            subprocess.Popen(["open", str(dest_bundle)])

            # Detach DMG volume if applicable
            if volume_to_detach:
                try:
                    time.sleep(0.5)
                    subprocess.run(
                        ["hdiutil", "detach", volume_to_detach, "-force", "-quiet"],
                        stderr=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        check=False,
                    )
                except Exception:
                    pass

        return True

    except Exception as e:
        print(f"⚠️ [Translocation] Failed to move bundle: {e}")
        return False


def check_and_prompt_move_to_applications(bundle_path: Optional[Path] = None) -> bool:
    """
    If running from a DMG or Translocation path, display a native Cocoa dialog
    offering to relocate the app to /Applications.
    Returns True if user chose to move and relaunch, False otherwise.
    """
    if is_headless():
        return False

    # Only run automatically for frozen standalone app bundles unless forced
    is_frozen = getattr(sys, "frozen", False)
    force_check = bool(os.getenv("VOICEFI_CHECK_TRANSLOCATION") == "1")

    if not is_frozen and not force_check and bundle_path is None:
        return False

    target = bundle_path or get_bundle_path()
    if not is_running_from_dmg_or_translocation(target):
        return False

    try:
        from AppKit import (
            NSApplication,
            NSAlert,
            NSAlertFirstButtonReturn,
            NSInformationalAlertStyle,
            NSApplicationActivationPolicyRegular,
        )

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        app.activateIgnoringOtherApps_(True)

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Move VoiceFi to Applications Folder?")
        alert.setInformativeText_(
            "VoiceFi works best when installed in your Applications folder. "
            "This ensures automatic background updates, global hotkeys (Control+T), "
            "and AI agent hooks stay connected across reboots.\n\n"
            "Would you like to move it now?"
        )
        alert.setAlertStyle_(NSInformationalAlertStyle)
        alert.addButtonWithTitle_("Move to Applications Folder")
        alert.addButtonWithTitle_("Do Not Move")

        resp = alert.runModal()
        if resp == NSAlertFirstButtonReturn:
            success = move_to_applications(bundle_path=target, relaunch=True)
            if success:
                # Exit current temporary instance since the new one is launched
                sys.exit(0)
                return True
        return False

    except Exception as e:
        print(f"⚠️ [Translocation] Modal prompt error: {e}")
        return False
