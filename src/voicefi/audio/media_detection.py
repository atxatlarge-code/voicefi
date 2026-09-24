"""
Smart Media Playback Detection for VoiceFi (Hardened & Optimized).

Intelligently detects when the user is actively watching or reviewing media clips:
1. Preview in Finder (Space bar / Quick Look, including Native Full Screen and Slideshows)
2. QuickTime Player actively playing media (resumes immediately when clip playback concludes)
3. Dedicated video players (mpv, IINA, VLC) if active

Explicitly excludes passive background audio (Spotify, YouTube in web browsers, Music.app)
so normal agent speech and conversational flow are not blocked during casual coding.

Waits politely until the clip/media finishes or is dismissed, then delivers the agent speech!
"""

import os
import time
import subprocess
import threading
from typing import Optional, Dict, Any, Tuple, Callable

try:
    import objc
except ImportError:
    objc = None

_QT_LOCK = threading.Lock()
_COMPILED_QT_SCRIPT = None
_STATE_LOCK = threading.Lock()
_LAST_MEDIA_CHECK_TIME = 0.0
_CACHED_MEDIA_STATE: Tuple[bool, Optional[Dict[str, Any]]] = (False, None)
_CACHE_TTL = 0.25  # 250ms cache TTL matches typical polling frequencies

_LAST_MPV_CHECK_TIME = 0.0
_CACHED_MPV_ACTIVE = False


def _get_compiled_quicktime_script():
    """Lazily compile and cache AppleScript instance with thread-safe error recovery."""
    global _COMPILED_QT_SCRIPT
    with _QT_LOCK:
        if _COMPILED_QT_SCRIPT is not None:
            return _COMPILED_QT_SCRIPT

        try:
            from Foundation import NSAppleScript

            script_source = """
            tell application "QuickTime Player"
                repeat with d in documents
                    try
                        if playing of d then return "playing"
                    end try
                end repeat
            end tell
            return "idle"
            """
            script = NSAppleScript.alloc().initWithSource_(script_source)
            success, err = script.compileAndReturnError_(None)
            if success:
                _COMPILED_QT_SCRIPT = script
            return _COMPILED_QT_SCRIPT
        except Exception:
            return None


def _reset_compiled_quicktime_script():
    """Invalidate cached AppleScript on process termination or error."""
    global _COMPILED_QT_SCRIPT
    with _QT_LOCK:
        _COMPILED_QT_SCRIPT = None


def is_quicktime_running() -> bool:
    """Fast check (< 1ms) to verify if QuickTime Player is running without launching it."""
    if os.environ.get("PYTEST_CURRENT_TEST") and "MOCK_QUICKTIME" not in os.environ:
        return False

    try:
        from AppKit import NSRunningApplication

        apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(
            "com.apple.QuickTimePlayerX"
        )
        if apps and len(apps) > 0:
            return True
        return False
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["pgrep", "-x", "QuickTime Player"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=0.2,
        )
        return res.returncode == 0
    except Exception:
        return False


def _get_frontmost_app_info() -> Optional[Tuple[str, str]]:
    """Return (bundle_id, localized_name) of the frontmost application, or None."""
    try:
        from AppKit import NSWorkspace

        ws = NSWorkspace.sharedWorkspace()
        front_app = ws.frontmostApplication()
        if front_app:
            bid = str(front_app.bundleIdentifier() or "")
            name = str(front_app.localizedName() or "")
            return bid, name
    except Exception:
        pass
    return None


def is_quicktime_frontmost() -> bool:
    """Check if QuickTime Player is currently the frontmost active application."""
    if os.environ.get("PYTEST_CURRENT_TEST") and "MOCK_QUICKTIME" not in os.environ:
        return False

    app_info = _get_frontmost_app_info()
    if app_info:
        bid, _ = app_info
        return bid == "com.apple.QuickTimePlayerX"
    return False


def is_quicktime_playing() -> Tuple[bool, Optional[str]]:
    """
    Check if QuickTime Player is actively playing media.
    Only returns True when a clip is actively playing (resumes as soon as playback concludes).
    """
    if not is_quicktime_running():
        _reset_compiled_quicktime_script()
        return False, None

    # Query document playing state via compiled NSAppleScript (fast path ~15ms)
    script = _get_compiled_quicktime_script()
    if script is not None:
        pool = objc.autorelease_pool() if objc else None
        if pool:
            pool.__enter__()
        try:
            with _QT_LOCK:
                res, err = script.executeAndReturnError_(None)
            if res:
                val = str(res.stringValue() or "").strip()
                if val == "playing":
                    return True, "QuickTime Player is actively playing media"
            elif err:
                _reset_compiled_quicktime_script()
        except Exception:
            _reset_compiled_quicktime_script()
        finally:
            if pool:
                pool.__exit__(None, None, None)

    # Subprocess fallback if NSAppleScript is unavailable
    try:
        fallback_script = """
        tell application "QuickTime Player"
            repeat with d in documents
                try
                    if playing of d then return "playing"
                end try
            end repeat
        end tell
        return "idle"
        """
        proc = subprocess.run(
            ["osascript", "-e", fallback_script],
            capture_output=True,
            text=True,
            timeout=0.3,
        )
        out = proc.stdout.strip()
        if out == "playing":
            return True, "QuickTime Player is actively playing media"
    except Exception:
        pass

    return False, None


def is_finder_quicklook_active() -> Tuple[bool, Optional[str]]:
    """
    Detect if Preview in Finder (Space bar / Quick Look) is open.
    Handles:
    - Normal floating preview (Finder Layer 3)
    - Full-screen presentation / slideshow (Layer 102 / 1000)
    - Out-of-process QuickLookUIService variants (Sonoma & Sequoia)
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and "MOCK_QUICKLOOK" not in os.environ:
        return False, None

    pool = objc.autorelease_pool() if objc else None
    if pool:
        pool.__enter__()
    try:
        import Quartz

        wl = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        if not wl:
            return False, None

        for w in wl:
            owner = str(w.get("kCGWindowOwnerName") or "")
            layer = int(w.get("kCGWindowLayer", 0))
            is_onscreen = bool(w.get("kCGWindowIsOnscreen", False))

            bounds = w.get("kCGWindowBounds", {})
            w_width = float(bounds.get("Width", 0))
            w_height = float(bounds.get("Height", 0))
            is_valid_size = w_width > 100 and w_height > 100

            if not is_valid_size or not is_onscreen:
                continue

            owner_lower = owner.lower()
            alpha = float(w.get("kCGWindowAlpha", 1.0))

            # 1. QuickLook UI service / qlmanage preview (Sonoma/Sequoia standalone XPC layer 0, or floating/presentation layer 3, 102, 1000)
            if (
                (
                    "quicklook" in owner_lower
                    or owner.startswith("QuickLookUIService")
                    or owner == "qlmanage"
                )
                and alpha > 0.5
                and layer in (0, 3, 102, 1000)
            ):
                return True, f"Quick Look preview ({owner}) is open"

            # 2. Finder Quick Look: Floating (layer 3) or Presentation/Slideshow (layer 102 / 1000)
            if owner == "Finder" and alpha > 0.5 and layer in (3, 102, 1000):
                return True, "Finder Quick Look preview is open"
    except Exception:
        pass
    finally:
        if pool:
            pool.__exit__(None, None, None)

    return False, None


def is_dedicated_video_player_active() -> Tuple[bool, Optional[str]]:
    """Check if dedicated video players (mpv, IINA, VLC) are active."""
    global _LAST_MPV_CHECK_TIME, _CACHED_MPV_ACTIVE
    if os.environ.get("PYTEST_CURRENT_TEST") and "MOCK_DEDICATED_PLAYERS" not in os.environ:
        return False, None

    app_info = _get_frontmost_app_info()
    if app_info:
        bid, name = app_info
        if bid in ("com.colliderli.iina", "org.videolan.vlc", "io.mpv") or name.lower() in (
            "iina",
            "vlc",
            "mpv",
        ):
            return True, f"{name} is active"

    # Cached mpv check (cached for 2.0s to avoid process fork churn)
    now = time.time()
    if (now - _LAST_MPV_CHECK_TIME) < 2.0:
        if _CACHED_MPV_ACTIVE:
            return True, "mpv video player is active"
    else:
        _LAST_MPV_CHECK_TIME = now
        try:
            res = subprocess.run(
                ["pgrep", "-x", "mpv"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.1,
            )
            _CACHED_MPV_ACTIVE = res.returncode == 0
            if _CACHED_MPV_ACTIVE:
                return True, "mpv video player is active"
        except Exception:
            _CACHED_MPV_ACTIVE = False

    return False, None


def check_active_media_state(use_cache: bool = True) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Core state checker with sliding thread-safe cache.
    Returns: (is_active, info_dict)
    """
    global _LAST_MEDIA_CHECK_TIME, _CACHED_MEDIA_STATE

    # Fast bypass when running in test / headless / mock environments unless specifically mocked
    if (
        os.getenv("VOICEFI_MOCK_AUDIO") == "1"
        or os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("VOICEFI_TESTING") == "1"
        or os.getenv("PYTEST_CURRENT_TEST")
    ):
        if not (
            os.getenv("MOCK_QUICKLOOK")
            or os.getenv("MOCK_QUICKTIME")
            or os.getenv("MOCK_DEDICATED_PLAYERS")
        ):
            return False, None

    now = time.time()
    with _STATE_LOCK:
        if use_cache and (now - _LAST_MEDIA_CHECK_TIME) < _CACHE_TTL:
            return _CACHED_MEDIA_STATE

    # 1. Check Finder Quick Look (Space bar)
    ql_active, ql_detail = is_finder_quicklook_active()
    if ql_active:
        state = (True, {"source": "finder_quicklook", "detail": ql_detail})
        with _STATE_LOCK:
            _CACHED_MEDIA_STATE = state
            _LAST_MEDIA_CHECK_TIME = now
        return state

    # 2. Check QuickTime Player
    qt_active, qt_detail = is_quicktime_playing()
    if qt_active:
        state = (True, {"source": "quicktime", "detail": qt_detail})
        with _STATE_LOCK:
            _CACHED_MEDIA_STATE = state
            _LAST_MEDIA_CHECK_TIME = now
        return state

    # 3. Check Dedicated Video Players (mpv, IINA, VLC)
    player_active, player_detail = is_dedicated_video_player_active()
    if player_active:
        state = (True, {"source": "dedicated_player", "detail": player_detail})
        with _STATE_LOCK:
            _CACHED_MEDIA_STATE = state
            _LAST_MEDIA_CHECK_TIME = now
        return state

    # Passive background audio (Spotify, Chrome, YouTube) is explicitly ignored
    state = (False, None)
    with _STATE_LOCK:
        _CACHED_MEDIA_STATE = state
        _LAST_MEDIA_CHECK_TIME = now
    return state


def is_active_media_playing(use_cache: bool = True) -> bool:
    """
    Universally check if active media clip playback (Quick Look or QuickTime) is ongoing.
    Passive audio (Spotify, YouTube in browser) returns False.
    """
    is_active, _ = check_active_media_state(use_cache=use_cache)
    return is_active


def get_active_media_info(use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """Return dictionary with active media details if media is playing, else None."""
    _, info = check_active_media_state(use_cache=use_cache)
    return info


def wait_for_media_completion(
    max_wait_seconds: Optional[float] = 600.0,
    poll_interval: float = 0.25,
    settle_seconds: float = 0.4,
    turn_start_time: Optional[float] = None,
    on_wait_tick: Optional[Callable[[float, str], None]] = None,
) -> bool:
    """
    Politely wait for active media clip playback to finish or be closed by the user,
    so that VoiceFi speaks when the clip ends!

    Includes a settle_seconds hysteresis (default 0.4s) so navigating across files
    in Finder Quick Look (e.g. arrow keys) does not falsely trigger early speech.

    Args:
        max_wait_seconds: Max seconds to wait for media to end (default 600.0 / 10 mins).
        poll_interval: Seconds between media status checks (default 0.25s).
        settle_seconds: Inactive stability duration before declaring media clear (default 0.4s).
        turn_start_time: Optional reference timestamp to verify interruption.
        on_wait_tick: Optional callback(elapsed_seconds, media_detail).

    Returns:
        True: Media finished or was closed (safe to speak now!).
        False: Interrupted by user (Esc key) or max_wait_seconds exceeded.
    """
    start_time = time.time()
    effective_start = turn_start_time or start_time

    try:
        from voicefi.tts.base import is_speech_interrupted
    except ImportError:
        is_speech_interrupted = lambda t=0: False  # noqa: E731

    logged_waiting = False
    inactive_start: Optional[float] = None

    while True:
        elapsed = time.time() - start_time
        if max_wait_seconds and max_wait_seconds > 0 and elapsed >= max_wait_seconds:
            return False

        if is_speech_interrupted(effective_start):
            return False

        media_active = is_active_media_playing(use_cache=True)
        if media_active:
            inactive_start = None
            info = get_active_media_info(use_cache=True) or {}
            detail = info.get("detail", "media clip")

            if not logged_waiting:
                print(
                    f"[VoiceFi] 🎬 Active media playback detected ({detail}). Pausing speech until clip finishes..."
                )
                logged_waiting = True

            if on_wait_tick:
                try:
                    on_wait_tick(elapsed, detail)
                except Exception:
                    pass
        else:
            now = time.time()
            if inactive_start is None:
                inactive_start = now
            elif (now - inactive_start) >= settle_seconds:
                # Confirmed stable inactive state!
                break

        time.sleep(poll_interval)

    if logged_waiting:
        print("[VoiceFi] 🎬 Media playback finished! Resuming speech now.")

    return True
