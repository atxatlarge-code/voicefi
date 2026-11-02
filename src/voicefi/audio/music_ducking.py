"""
Background media ducking for macOS (Spotify, Apple Music).
Temporarily ducks active background music while VoiceFi agents speak,
ensuring speech clarity over earbuds/speakers without stopping music playback.
"""

import contextlib
import os
import subprocess
import sys
from typing import Optional, Tuple


def _duck_active_player(target_volume: int = 20) -> Tuple[Optional[str], Optional[int]]:
    """
    Check if Spotify or Apple Music is currently playing, and if so,
    temporarily lower its volume to `target_volume`.
    Returns (app_name, original_volume) or (None, None).
    """
    if (
        sys.platform != "darwin"
        or os.getenv("VOICEFI_MOCK_AUDIO") == "1"
        or os.getenv("VOICEFI_TESTING") == "1"
        or bool(os.getenv("PYTEST_CURRENT_TEST"))
    ):
        return None, None

    script = f"""
    tell application "System Events"
        set isSpotify to (exists (processes where name is "Spotify"))
        set isMusic to (exists (processes where name is "Music"))
    end tell
    if isSpotify then
        tell application "Spotify"
            if player state is playing then
                set curVol to sound volume
                set sound volume to {target_volume}
                return "Spotify:" & curVol
            end if
        end tell
    end if
    if isMusic then
        tell application "Music"
            if player state is playing then
                set curVol to sound volume
                set sound volume to {target_volume}
                return "Music:" & curVol
            end if
        end tell
    end if
    return "none"
    """
    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=0.6,
        )
        if res.returncode == 0 and ":" in res.stdout:
            parts = res.stdout.strip().split(":", 1)
            return parts[0], int(parts[1])
    except Exception:
        pass
    return None, None


def _restore_active_player(app_name: Optional[str], original_volume: Optional[int]) -> None:
    """Restore player volume after speech completes."""
    if not app_name or original_volume is None or original_volume < 0:
        return
    if (
        sys.platform != "darwin"
        or os.getenv("VOICEFI_MOCK_AUDIO") == "1"
        or os.getenv("VOICEFI_TESTING") == "1"
        or bool(os.getenv("PYTEST_CURRENT_TEST"))
    ):
        return

    script = f'tell application "{app_name}" to set sound volume to {original_volume}'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=0.6,
        )
    except Exception:
        pass


@contextlib.contextmanager
def duck_background_music(target_volume: int = 20):
    """
    Context manager that ducks Spotify or Apple Music to `target_volume`
    for the duration of the enclosed block, then restores original volume.
    """
    app_name, orig_vol = _duck_active_player(target_volume)
    try:
        yield
    finally:
        if app_name and orig_vol is not None:
            _restore_active_player(app_name, orig_vol)
