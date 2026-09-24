"""
VoiceFi Self-Updater & Version Management.
Provides non-blocking background update checks (24h cache), CLI self-update (`vifi update`),
Menu Bar 1-click updates, and Pro tier silent background auto-upgrades.
"""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.request import Request, urlopen

from voicefi import __version__
from voicefi.config import VoiceFiConfig, load_config
from voicefi.license import FeatureGate

CACHE_FILE = Path.home() / ".voicefi" / ".update_check.json"
CACHE_TTL_SECONDS = 86400  # 24 hours
GITHUB_API_URL = "https://api.github.com/repos/atxatlarge-code/voicefi/releases/latest"
GITHUB_COMMITS_URL = "https://api.github.com/repos/atxatlarge-code/voicefi/commits/main"
DEFAULT_REPO_URL = "git+https://github.com/atxatlarge-code/voicefi.git"


def get_local_version() -> str:
    """Return the currently installed VoiceFi version string."""
    return __version__


def parse_semver(v: str) -> Tuple[int, ...]:
    """Parse version string into an integer tuple for comparison (e.g. '0.1.0' -> (0, 1, 0))."""
    clean = str(v).strip().lstrip("v").split("-")[0].split("+")[0]
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0, 0, 0)


def read_update_cache() -> Optional[Dict[str, Any]]:
    """Read cached update check metadata if within TTL."""
    if not CACHE_FILE.is_file():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        last_check = float(data.get("timestamp", 0))
        if (time.time() - last_check) < CACHE_TTL_SECONDS:
            return data
    except Exception:
        pass
    return None


def write_update_cache(data: Dict[str, Any]) -> None:
    """Persist update check metadata to ~/.voicefi/.update_check.json."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data["timestamp"] = time.time()
        CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def check_for_updates(force: bool = False) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if a newer version of VoiceFi is available on GitHub.
    Returns: (is_update_available, latest_version_or_sha, release_notes_or_url)
    """
    if not force:
        cached = read_update_cache()
        if cached is not None:
            return (
                bool(cached.get("update_available")),
                cached.get("latest_version"),
                cached.get("url") or cached.get("notes"),
            )

    local_ver_tuple = parse_semver(get_local_version())
    latest_version = get_local_version()
    release_url = "https://github.com/atxatlarge-code/voicefi"
    release_notes = ""
    update_available = False

    dmg_url = "https://voicefi.org/download/mac"

    try:
        # 1. Try GitHub Releases API first
        req = Request(
            GITHUB_API_URL,
            headers={
                "User-Agent": f"VoiceFi-Updater/{__version__}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        with urlopen(req, timeout=3.5) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                tag_name = body.get("tag_name", "").lstrip("v")
                if isinstance(body.get("assets"), list):
                    for asset in body["assets"]:
                        if asset.get("name", "").lower().endswith(".dmg"):
                            dmg_url = asset.get("browser_download_url", dmg_url)
                            break
                if tag_name:
                    remote_tuple = parse_semver(tag_name)
                    if remote_tuple > local_ver_tuple:
                        update_available = True
                        latest_version = tag_name
                        release_url = body.get("html_url", release_url)
                        release_notes = body.get("body", "")
    except Exception:
        # 2. Fallback: check latest commit timestamp / sha on main branch
        try:
            req_commit = Request(
                GITHUB_COMMITS_URL,
                headers={
                    "User-Agent": f"VoiceFi-Updater/{__version__}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            with urlopen(req_commit, timeout=3.0) as c_resp:
                if c_resp.status == 200:
                    c_body = json.loads(c_resp.read().decode("utf-8"))
                    sha = c_body.get("sha", "")[:7]
                    latest_version = f"{__version__}+git.{sha}"
        except Exception:
            pass

    cache_payload = {
        "update_available": update_available,
        "latest_version": latest_version,
        "url": release_url,
        "dmg_url": dmg_url,
        "notes": release_notes[:200] if release_notes else "",
        "local_version": get_local_version(),
    }
    write_update_cache(cache_payload)
    return update_available, latest_version, release_url


def is_dmg_install() -> bool:
    """
    Return True if VoiceFi is running as a standalone macOS .app bundle
    (e.g., PyInstaller frozen bundle or installed from DMG in /Applications).
    """
    if getattr(sys, "frozen", False):
        return True
    try:
        exec_str = str(Path(sys.executable).resolve())
        if ".app/Contents/" in exec_str or "VoiceFi.app" in exec_str:
            return True
    except Exception:
        pass
    venv_python = Path.home() / ".voicefi" / "venv" / "bin" / "python"
    if venv_python.is_file():
        return False
    return False


def upgrade_dmg_app_bundle(
    dmg_url: Optional[str] = None,
    version: Optional[str] = None,
    relaunch: bool = True,
    timeout_seconds: int = 180,
) -> Dict[str, Any]:
    """
    Download latest VoiceFi macOS DMG, silently mount it, copy the new
    VoiceFi.app to replace the current application bundle in /Applications,
    unmount DMG, and optionally relaunch the updated app seamlessly.
    Falls back to download_and_open_dmg() if in-place replacement fails.
    """
    import tempfile
    import shutil

    ver = version or "latest"
    target_url = dmg_url or "https://voicefi.org/download/mac"
    cache_dir = Path.home() / ".voicefi" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    target_dmg = cache_dir / f"VoiceFi_{ver}_update.dmg"

    try:
        import rumps

        rumps.notification(
            "VoiceFi Updater 💿",
            f"Downloading VoiceFi {ver}...",
            "Downloading latest version in background...",
        )
    except Exception:
        pass

    try:
        # 1. Download DMG
        req = Request(
            target_url,
            headers={"User-Agent": f"VoiceFi-Updater/{__version__}"},
        )
        with urlopen(req, timeout=timeout_seconds) as resp:
            with open(target_dmg, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

        if not target_dmg.is_file() or target_dmg.stat().st_size < 1_000_000:
            raise RuntimeError("Downloaded DMG was invalid or incomplete.")

        # 2. Silently mount DMG
        mount_dir = Path(tempfile.mkdtemp(prefix="vifi_update_mount_"))
        mount_res = subprocess.run(
            [
                "hdiutil",
                "attach",
                str(target_dmg),
                "-mountpoint",
                str(mount_dir),
                "-noautoopen",
                "-quiet",
            ],
            capture_output=True,
            text=True,
        )
        if mount_res.returncode != 0:
            raise RuntimeError(f"hdiutil attach failed: {mount_res.stderr}")

        source_app = mount_dir / "VoiceFi.app"
        if not source_app.is_dir():
            subprocess.run(["hdiutil", "detach", str(mount_dir), "-force", "-quiet"], check=False)
            raise RuntimeError("VoiceFi.app not found in mounted DMG volume.")

        # 3. Locate installed bundle
        from voicefi.ui.translocation import get_bundle_path

        installed_bundle = get_bundle_path()
        if not installed_bundle or not installed_bundle.is_dir():
            if Path("/Applications/VoiceFi.app").is_dir():
                installed_bundle = Path("/Applications/VoiceFi.app")
            elif (Path.home() / "Applications" / "VoiceFi.app").is_dir():
                installed_bundle = Path.home() / "Applications" / "VoiceFi.app"
            else:
                installed_bundle = Path("/Applications/VoiceFi.app")

        parent_dir = installed_bundle.parent
        staged_bundle = parent_dir / f"{installed_bundle.name}.new"
        backup_bundle = parent_dir / f"{installed_bundle.name}.old"

        # 4. Copy to staged bundle
        if staged_bundle.exists():
            shutil.rmtree(staged_bundle, ignore_errors=True)
        shutil.copytree(source_app, staged_bundle, symlinks=True)

        # 5. Clear quarantine on staged bundle
        subprocess.run(
            ["xattr", "-dr", "com.apple.quarantine", str(staged_bundle)],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            check=False,
        )

        # 6. Detach DMG volume and clean up downloaded file
        subprocess.run(["hdiutil", "detach", str(mount_dir), "-force", "-quiet"], check=False)
        shutil.rmtree(mount_dir, ignore_errors=True)
        target_dmg.unlink(missing_ok=True)

        # 7. Atomic directory swap
        if backup_bundle.exists():
            shutil.rmtree(backup_bundle, ignore_errors=True)
        if installed_bundle.exists():
            os.rename(installed_bundle, backup_bundle)
        os.rename(staged_bundle, installed_bundle)
        shutil.rmtree(backup_bundle, ignore_errors=True)

        # 8. Success notification
        try:
            import rumps

            rumps.notification(
                "VoiceFi Upgraded 🎉",
                f"Version v{ver} Active",
                "VoiceFi was updated and restarted successfully.",
            )
        except Exception:
            pass

        # 9. Relaunch
        if relaunch:
            subprocess.Popen(["open", str(installed_bundle)])
            time.sleep(1.0)
            sys.exit(0)

        return {
            "success": True,
            "is_dmg": True,
            "in_place": True,
            "new_version": ver,
            "message": f"Successfully updated VoiceFi.app to v{ver} in place!",
        }

    except Exception as e:
        print(
            f"⚠️ [Updater] In-place DMG upgrade failed: {e}. Falling back to standard DMG download..."
        )
        return download_and_open_dmg(dmg_url=dmg_url, version=ver, timeout_seconds=timeout_seconds)


def download_and_open_dmg(
    dmg_url: Optional[str] = None,
    version: Optional[str] = None,
    timeout_seconds: int = 120,
) -> Dict[str, Any]:
    """
    Download latest VoiceFi macOS DMG to ~/Downloads and open it with Finder
    for easy drag-and-drop upgrade.
    """
    import webbrowser

    ver = version or "latest"
    target_url = dmg_url or "https://voicefi.org/download/mac"
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    target_dmg = downloads_dir / f"VoiceFi_{ver}_macOS.dmg"

    try:
        import rumps

        rumps.notification(
            "VoiceFi Updater 💿",
            f"Downloading VoiceFi {ver}...",
            "Downloading latest macOS disk image to ~/Downloads",
        )
    except Exception:
        pass

    try:
        req = Request(
            target_url,
            headers={"User-Agent": f"VoiceFi-Updater/{__version__}"},
        )
        with urlopen(req, timeout=timeout_seconds) as resp:
            with open(target_dmg, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

        if target_dmg.is_file() and target_dmg.stat().st_size > 1_000_000:
            subprocess.run(["open", str(target_dmg)], check=False)
            try:
                import rumps

                rumps.notification(
                    "VoiceFi Installer Ready 🎉",
                    f"VoiceFi {ver} Disk Image Opened",
                    "Drag VoiceFi into Applications to complete the upgrade.",
                )
            except Exception:
                pass
            return {
                "success": True,
                "is_dmg": True,
                "dmg_path": str(target_dmg),
                "new_version": ver,
                "message": f"Downloaded and opened VoiceFi {ver} installer. Drag to Applications to complete!",
            }
        else:
            raise RuntimeError("Downloaded DMG file was invalid or incomplete.")
    except Exception as e:
        # Fallback: open browser directly to download page
        try:
            import webbrowser

            webbrowser.open("https://voicefi.org/download/mac")
            import rumps

            rumps.notification(
                "VoiceFi Update 🌐",
                f"Opening Download Page ({ver})",
                "Download the new DMG to upgrade VoiceFi.",
            )
        except Exception:
            pass
        return {
            "success": True,
            "is_dmg": True,
            "fallback": True,
            "new_version": ver,
            "message": f"Opened latest DMG download page in browser ({e})",
        }


def perform_update(
    relink_hooks: bool = True,
    repo_url: Optional[str] = None,
    force_dmg: bool = False,
    relaunch: bool = True,
) -> Dict[str, Any]:
    """
    Execute upgrade of VoiceFi.
    If running as a standalone DMG .app bundle, upgrades the bundle in place
    and relaunches seamlessly.
    Otherwise, runs in-place pip/uv upgrade inside the virtual environment.
    """
    old_version = get_local_version()

    # Standalone DMG bundle handling
    if force_dmg or is_dmg_install():
        _, new_ver, _ = check_for_updates(force=True)
        cached = read_update_cache() or {}
        dmg_url = cached.get("dmg_url") or "https://voicefi.org/download/mac"
        return upgrade_dmg_app_bundle(
            dmg_url=dmg_url,
            version=new_ver or old_version,
            relaunch=relaunch,
        )

    target_repo = repo_url or DEFAULT_REPO_URL
    old_version = get_local_version()

    # Determine Python/pip binary and uv tool
    venv_python = Path.home() / ".voicefi" / "venv" / "bin" / "python"
    python_bin = str(venv_python) if venv_python.is_file() else sys.executable

    uv_path = Path.home() / ".local" / "bin" / "uv"
    uv_bin = str(uv_path) if uv_path.is_file() else None
    if not uv_bin:
        import shutil

        uv_bin = shutil.which("uv")

    print(f"\n⚡ Upgrading VoiceFi from {target_repo}...")
    print(f"📦 Active Environment: {python_bin}")

    if uv_bin:
        cmd = [
            uv_bin,
            "pip",
            "install",
            "--python",
            python_bin,
            "--upgrade",
            "--no-cache",
            target_repo,
        ]
    else:
        # Verify pip exists or bootstrap with ensurepip
        try:
            chk = subprocess.run(
                [python_bin, "-m", "pip", "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if chk.returncode != 0:
                subprocess.run(
                    [python_bin, "-m", "ensurepip", "--upgrade"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

        cmd = [
            python_bin,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-cache-dir",
            target_repo,
        ]

    try:
        start_t = time.perf_counter()
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
        duration_s = round(time.perf_counter() - start_t, 1)

        if proc.returncode != 0:
            error_msg = proc.stderr.strip() or proc.stdout.strip() or "Unknown pip install error"
            return {
                "success": False,
                "error": error_msg,
                "message": f"Upgrade failed: {error_msg[:120]}",
            }

        # Re-link hooks and write configuration
        if relink_hooks:
            try:
                subprocess.run(
                    [python_bin, "-m", "voicefi.cli", "setup"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            except Exception:
                pass

        # Invalidate update cache
        try:
            CACHE_FILE.unlink(missing_ok=True)
        except Exception:
            pass

        # Try to read new version
        new_version = old_version
        try:
            v_res = subprocess.run(
                [python_bin, "-c", "from voicefi import __version__; print(__version__)"],
                stdout=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if v_res.returncode == 0 and v_res.stdout.strip():
                new_version = v_res.stdout.strip()
        except Exception:
            pass

        # Desktop notification
        try:
            import rumps

            rumps.notification(
                "VoiceFi Upgraded 🎉",
                f"Version {new_version} Active",
                "Voice bridges, smart VAD, and personas are up to date.",
            )
        except Exception:
            pass

        return {
            "success": True,
            "old_version": old_version,
            "new_version": new_version,
            "duration_s": duration_s,
            "message": f"Successfully updated VoiceFi ({old_version} -> {new_version}) in {duration_s}s!",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Upgrade timed out (network slow)",
            "message": "Upgrade timed out",
        }
    except Exception as e:
        return {"success": False, "error": str(e), "message": f"Upgrade error: {e}"}


def run_auto_update_if_enabled(config: Optional[VoiceFiConfig] = None) -> None:
    """
    Execute silent background auto-upgrade if enabled for Pro tier users.
    Runs non-blocking in background during idle periods.
    """
    cfg = config or load_config()
    auto_update_enabled = getattr(cfg, "auto_update", False)

    # Only run auto-updater if user enabled it and tier allows it
    if not auto_update_enabled:
        return

    if not FeatureGate.can_use_feature("auto_update", cfg):
        return

    def _worker():
        try:
            is_avail, new_ver, _ = check_for_updates(force=False)
            if is_avail:
                print(
                    f"[VoiceFi] 🚀 Pro Auto-Updater: Found new version {new_ver}. Applying silent upgrade in background..."
                )
                res = perform_update(relink_hooks=True, relaunch=True)
                if res.get("success"):
                    print(f"[VoiceFi] ✨ Pro Auto-Updater: {res.get('message')}")
                else:
                    print(f"[VoiceFi] ⚠️ Pro Auto-Updater failed: {res.get('error')}")
                    print(f"[VoiceFi] ⚠️ Pro Auto-Updater failed: {res.get('error')}")
        except Exception as e:
            print(f"[VoiceFi] Auto-updater exception: {e}")

    threading.Thread(target=_worker, daemon=True).start()


def trigger_background_update_check() -> None:
    """Trigger an asynchronous, non-blocking update check thread."""

    def _worker():
        try:
            check_for_updates(force=False)
            run_auto_update_if_enabled()
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()
