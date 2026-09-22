import os
import time
from unittest.mock import patch, MagicMock
import pytest

from voicefi.audio.media_detection import (
    is_finder_quicklook_active,
    is_quicktime_running,
    is_quicktime_frontmost,
    is_quicktime_playing,
    is_dedicated_video_player_active,
    is_active_media_playing,
    get_active_media_info,
    wait_for_media_completion,
    _get_compiled_quicktime_script,
    _reset_compiled_quicktime_script,
)
from voicefi.tts.base import speech_turn_lock, DuplicateSpeechSuppressed


def test_finder_quicklook_floating_and_normal():
    """Verify Finder Quick Look layer 3 floating window detection and rejection of normal windows."""
    # Case 1: Normal Finder folder window (layer 0) -> not quick look
    mock_windows_normal = [
        {
            "kCGWindowOwnerName": "Finder",
            "kCGWindowLayer": 0,
            "kCGWindowIsOnscreen": True,
            "kCGWindowBounds": {"Width": 800, "Height": 600},
        }
    ]
    with patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_windows_normal), \
         patch.dict(os.environ, {"MOCK_QUICKLOOK": "1"}):
        active, detail = is_finder_quicklook_active()
        assert not active
        assert detail is None

    # Case 2: Quick Look preview window (Finder layer 3) -> detected!
    mock_windows_ql = [
        {
            "kCGWindowOwnerName": "Finder",
            "kCGWindowLayer": 3,
            "kCGWindowIsOnscreen": True,
            "kCGWindowBounds": {"Width": 575, "Height": 309},
        }
    ]
    with patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_windows_ql), \
         patch.dict(os.environ, {"MOCK_QUICKLOOK": "1"}):
        active, detail = is_finder_quicklook_active()
        assert active
        assert "Finder Quick Look" in detail

    # Case 3: Small bounds (<100x100) are ignored (shadows, icons, indicators)
    mock_windows_small = [
        {
            "kCGWindowOwnerName": "Finder",
            "kCGWindowLayer": 3,
            "kCGWindowIsOnscreen": True,
            "kCGWindowBounds": {"Width": 32, "Height": 32},
        }
    ]
    with patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_windows_small), \
         patch.dict(os.environ, {"MOCK_QUICKLOOK": "1"}):
        active, detail = is_finder_quicklook_active()
        assert not active


def test_finder_quicklook_fullscreen_and_presentation():
    """Verify Quick Look slideshow, presentation (layer 102/1000), and XPC helper variants."""
    # Case 1: Finder presentation / slideshow (layer 102)
    mock_slideshow = [
        {
            "kCGWindowOwnerName": "Finder",
            "kCGWindowLayer": 102,
            "kCGWindowIsOnscreen": True,
            "kCGWindowBounds": {"Width": 1920, "Height": 1080},
        }
    ]
    with patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_slideshow), \
         patch.dict(os.environ, {"MOCK_QUICKLOOK": "1"}):
        active, detail = is_finder_quicklook_active()
        assert active
        assert "Finder Quick Look preview is open" in detail

    # Case 2: Finder native full screen (layer 1000)
    mock_fullscreen = [
        {
            "kCGWindowOwnerName": "Finder",
            "kCGWindowLayer": 1000,
            "kCGWindowIsOnscreen": True,
            "kCGWindowBounds": {"Width": 1920, "Height": 1080},
        }
    ]
    with patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_fullscreen), \
         patch.dict(os.environ, {"MOCK_QUICKLOOK": "1"}):
        active, detail = is_finder_quicklook_active()
        assert active
        assert "Finder Quick Look preview is open" in detail

    # Case 3: Standalone QuickLookUIService preview (Sonoma / Sequoia)
    mock_xpc = [
        {
            "kCGWindowOwnerName": "QuickLookUIService",
            "kCGWindowLayer": 0,
            "kCGWindowIsOnscreen": True,
            "kCGWindowBounds": {"Width": 640, "Height": 480},
        }
    ]
    with patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_xpc), \
         patch.dict(os.environ, {"MOCK_QUICKLOOK": "1"}):
        active, detail = is_finder_quicklook_active()
        assert active
        assert "Quick Look preview" in detail

    # Case 4: qlmanage CLI preview
    mock_qlmanage = [
        {
            "kCGWindowOwnerName": "qlmanage",
            "kCGWindowLayer": 0,
            "kCGWindowIsOnscreen": True,
            "kCGWindowBounds": {"Width": 800, "Height": 600},
        }
    ]
    with patch("Quartz.CGWindowListCopyWindowInfo", return_value=mock_qlmanage), \
         patch.dict(os.environ, {"MOCK_QUICKLOOK": "1"}):
        active, detail = is_finder_quicklook_active()
        assert active
        assert "qlmanage" in detail


def test_quicktime_playing_detection():
    """Verify QuickTime Player playback state detection."""
    # Case 1: QuickTime is not running
    with patch("voicefi.audio.media_detection.is_quicktime_running", return_value=False):
        active, detail = is_quicktime_playing()
        assert not active
        assert detail is None

    # Case 2: QuickTime is running and actively playing a document ("playing")
    mock_script = MagicMock()
    mock_res = MagicMock()
    mock_res.stringValue.return_value = "playing"
    mock_script.executeAndReturnError_.return_value = (mock_res, None)

    with patch("voicefi.audio.media_detection.is_quicktime_running", return_value=True), \
         patch("voicefi.audio.media_detection._get_compiled_quicktime_script", return_value=mock_script):
        active, detail = is_quicktime_playing()
        assert active
        assert "actively playing" in detail

    # Case 3: QuickTime is running, but clip finished or paused ("idle") -> does not block speech!
    mock_res.stringValue.return_value = "idle"
    with patch("voicefi.audio.media_detection.is_quicktime_running", return_value=True), \
         patch("voicefi.audio.media_detection._get_compiled_quicktime_script", return_value=mock_script):
        active, detail = is_quicktime_playing()
        assert not active
        assert detail is None

    # Case 4: Subprocess fallback when NSAppleScript is unavailable
    with patch("voicefi.audio.media_detection.is_quicktime_running", return_value=True), \
         patch("voicefi.audio.media_detection._get_compiled_quicktime_script", return_value=None), \
         patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="playing\n")
        active, detail = is_quicktime_playing()
        assert active
        assert "actively playing" in detail


def test_quicktime_script_invalidation_on_error():
    """Verify that execution errors invalidate the cached NSAppleScript instance."""
    import voicefi.audio.media_detection as md

    # Pre-populate a dummy script
    md._COMPILED_QT_SCRIPT = MagicMock()
    md._COMPILED_QT_SCRIPT.executeAndReturnError_.return_value = (None, {"NSAppleScriptErrorMessage": "App quit"})

    with patch("voicefi.audio.media_detection.is_quicktime_running", return_value=True):
        active, detail = is_quicktime_playing()
        assert not active
        # Script must have been cleared / invalidated
        assert md._COMPILED_QT_SCRIPT is None


def test_passive_audio_exemption():
    """Verify that passive audio like Spotify, Apple Music, or YouTube does not trigger media detection."""
    with patch("voicefi.audio.media_detection.is_finder_quicklook_active", return_value=(False, None)), \
         patch("voicefi.audio.media_detection.is_quicktime_playing", return_value=(False, None)), \
         patch("voicefi.audio.media_detection.is_dedicated_video_player_active", return_value=(False, None)):
        assert not is_active_media_playing(use_cache=False)
        assert get_active_media_info(use_cache=False) is None


def test_dedicated_player_detection():
    """Verify detection of standalone media players (IINA, VLC, mpv)."""
    # Case 1: IINA frontmost
    with patch("voicefi.audio.media_detection._get_frontmost_app_info", return_value=("com.colliderli.iina", "IINA")), \
         patch.dict(os.environ, {"MOCK_DEDICATED_PLAYERS": "1"}):
        active, detail = is_dedicated_video_player_active()
        assert active
        assert "IINA" in detail

    # Case 2: VLC frontmost
    with patch("voicefi.audio.media_detection._get_frontmost_app_info", return_value=("org.videolan.vlc", "VLC")), \
         patch.dict(os.environ, {"MOCK_DEDICATED_PLAYERS": "1"}):
        active, detail = is_dedicated_video_player_active()
        assert active
        assert "VLC" in detail

    # Case 3: mpv process running
    with patch("voicefi.audio.media_detection._get_frontmost_app_info", return_value=None), \
         patch("subprocess.run") as mock_subproc, \
         patch.dict(os.environ, {"MOCK_DEDICATED_PLAYERS": "1"}):
        mock_subproc.return_value = MagicMock(returncode=0)
        import voicefi.audio.media_detection as md
        md._LAST_MPV_CHECK_TIME = 0.0  # bypass mpv cache
        active, detail = is_dedicated_video_player_active()
        assert active
        assert "mpv" in detail


def test_wait_for_media_completion_settle_hysteresis():
    """
    Verify that rapid arrow-key browsing in Finder Quick Look (where media briefly
    disappears for < settle_seconds) does NOT trigger early speech completion.
    """
    timeline = [
        # (simulated_elapsed_time, is_active)
        (0.0, True),    # User watching video 1
        (0.2, False),   # User pressed Right Arrow: preview flips
        (0.3, True),    # Video 2 loads in 100ms (< settle_seconds 0.4s)
        (0.5, True),    # Watching video 2
        (0.7, False),   # Video 2 closed!
        (1.2, False),   # Remained closed for 0.5s (> settle_seconds 0.4s) -> Finished!
    ]

    current_idx = [0]

    def mock_is_media_playing(use_cache=True):
        idx = min(current_idx[0], len(timeline) - 1)
        res = timeline[idx][1]
        current_idx[0] += 1
        return res

    with patch("voicefi.audio.media_detection.is_active_media_playing", side_effect=mock_is_media_playing), \
         patch("time.sleep", return_value=None):
        res = wait_for_media_completion(
            max_wait_seconds=5.0,
            poll_interval=0.01,
            settle_seconds=0.03,  # Scaled for instant unit test
        )
        assert res is True
        # Must have progressed past the temporary glitch to the stable state
        assert current_idx[0] >= 5


def test_wait_for_media_completion_success():
    """Verify that wait_for_media_completion waits politely and returns True when media clears."""
    call_count = [0]

    def mock_is_media_playing(use_cache=True):
        call_count[0] += 1
        # Returns True on first 2 calls, then False (clip finished!)
        return call_count[0] <= 2

    with patch("voicefi.audio.media_detection.is_active_media_playing", side_effect=mock_is_media_playing), \
         patch("time.sleep", return_value=None):
        res = wait_for_media_completion(
            max_wait_seconds=5.0,
            poll_interval=0.01,
            settle_seconds=0.02,
        )
        assert res is True
        assert call_count[0] >= 3


def test_wait_for_media_completion_timeout():
    """Verify that wait_for_media_completion returns False if media exceeds max_wait_seconds."""
    with patch("voicefi.audio.media_detection.is_active_media_playing", return_value=True):
        res = wait_for_media_completion(max_wait_seconds=0.1, poll_interval=0.02)
        assert res is False


def test_wait_for_media_completion_user_escape():
    """Verify that pressing Esc cancels media waiting immediately."""
    with patch("voicefi.audio.media_detection.is_active_media_playing", return_value=True), \
         patch("voicefi.tts.base.is_speech_interrupted", return_value=True):
        res = wait_for_media_completion(max_wait_seconds=10.0, poll_interval=0.05)
        assert res is False


def test_speech_turn_lock_pre_lock_media_wait():
    """
    Verify that speech_turn_lock politely waits for media completion BEFORE
    acquiring the exclusive cross-process lock.
    """
    wait_called = []
    media_state = [True]

    def mock_wait(max_wait_seconds=600.0, turn_start_time=None):
        wait_called.append(True)
        media_state[0] = False  # Clip finishes!
        return True

    def mock_is_media_playing(use_cache=True):
        return media_state[0]

    with patch("voicefi.audio.media_detection.is_active_media_playing", side_effect=mock_is_media_playing), \
         patch("voicefi.audio.media_detection.wait_for_media_completion", side_effect=mock_wait):
        with speech_turn_lock(text="Test speech after video"):
            pass

    assert len(wait_called) > 0


def test_speech_turn_lock_post_lock_media_abort():
    """Verify that if media starts while acquiring the lock, post-lock re-check aborts turn."""
    # First check (pre-lock): False (media not yet playing)
    # Second check (post-lock): True (user just pressed spacebar right when lock acquired)
    with patch("voicefi.audio.media_detection.is_active_media_playing", side_effect=[False, True]):
        with pytest.raises(DuplicateSpeechSuppressed, match="Media playback started"):
            with speech_turn_lock(text="Interrupted turn"):
                pass

