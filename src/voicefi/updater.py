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

    try:
        # 1. Try GitHub Releases API first
        req = Request(
            GITHUB_API_URL,
            headers={"User-Agent": f"VoiceFi-Updater/{__version__}", "Accept": "application/vnd.github.v3+json"},
        )
        with urlopen(req, timeout=3.5) as resp:
            if resp.status == 200:
                body = json.loads(resp.read().decode("utf-8"))
                tag_name = body.get("tag_name", "").lstrip("v")
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
                headers={"User-Agent": f"VoiceFi-Updater/{__version__}", "Accept": "application/vnd.github.v3+json"},
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
        "notes": release_notes[:200] if release_notes else "",
        "local_version": get_local_version(),
    }
    write_update_cache(cache_payload)
    return update_available, latest_version, release_url


def perform_update(
    relink_hooks: bool = True,
    repo_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute in-place upgrade of VoiceFi virtual environment.
    Runs pip upgrade, updates hooks, and returns result status.
    """
    target_repo = repo_url or DEFAULT_REPO_URL
    old_version = get_local_version()

    # Determine Python/pip binary
    venv_python = Path.home() / ".voicefi" / "venv" / "bin" / "python"
    python_bin = str(venv_python) if venv_python.is_file() else sys.executable

    print(f"\n⚡ Upgrading VoiceFi from {target_repo}...")
    print(f"📦 Active Environment: {python_bin}")

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
                subprocess.run([python_bin, "-m", "voicefi.cli", "setup"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
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
        return {"success": False, "error": "Upgrade timed out (network slow)", "message": "Upgrade timed out"}
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
                print(f"[VoiceFi] 🚀 Pro Auto-Updater: Found new version {new_ver}. Applying silent upgrade in background...")
                res = perform_update(relink_hooks=True)
                if res.get("success"):
                    print(f"[VoiceFi] ✨ Pro Auto-Updater: {res.get('message')}")
                else:
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
