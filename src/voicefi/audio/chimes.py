"""
System audio cues for VoiceFi.
Plays lightweight macOS sound effects for listening state transitions.
"""

import os
import subprocess
import threading
from typing import Optional
from pathlib import Path


_SENT_SOUND_CANDIDATES = [
    "/System/Applications/Mail.app/Contents/Resources/Mail Sent.aiff",
    "/System/Library/Components/CoreAudio.component/Contents/SharedSupport/SystemSounds/system/SentMessage.caf",
    "/System/Library/PrivateFrameworks/ToneLibrary.framework/Versions/A/Resources/AlertTones/Classic/Swoosh.m4r",
    "/System/Library/PrivateFrameworks/IMDaemonCore.framework/Versions/A/Resources/Sent Message.aiff",
    "/System/Library/Sounds/Pop.aiff",
]


def get_default_sent_sound() -> str:
    """Find the best available macOS email / message sent sound effect."""
    for path in _SENT_SOUND_CANDIDATES:
        if os.path.exists(path):
            return path
    return "/System/Library/Sounds/Pop.aiff"


DEFAULT_SENT_SOUND = get_default_sent_sound()

SYSTEM_SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "done": DEFAULT_SENT_SOUND,
    "sent": DEFAULT_SENT_SOUND,
    "mail_sent": DEFAULT_SENT_SOUND,
    "swoosh": DEFAULT_SENT_SOUND,
    "error": "/System/Library/Sounds/Basso.aiff",
    "alert": "/System/Library/Sounds/Glass.aiff",
}


def play_chime(sound_key_or_path: str, block: bool = False) -> None:
    """
    Play a system audio cue using macOS afplay.

    Args:
        sound_key_or_path: Key in SYSTEM_SOUNDS (e.g. 'start', 'sent', 'done') or absolute path to an audio file.
        block: Whether to block execution until the sound finishes.
    """
    sound_path = SYSTEM_SOUNDS.get(sound_key_or_path, sound_key_or_path)

    # If the configured file does not exist, check fallback
    if not os.path.exists(sound_path):
        if (
            sound_key_or_path in ("done", "sent", "mail_sent", "swoosh")
            or "Mail Sent" in sound_key_or_path
        ):
            sound_path = DEFAULT_SENT_SOUND
        if not os.path.exists(sound_path):
            return

    def _run():
        if not block and (
            os.getenv("VOICEFI_TESTING") == "1" or os.getenv("VOICEFI_HEADLESS") == "1"
        ):
            return
        try:
            subprocess.run(
                ["afplay", sound_path],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    if block:
        _run()
    else:
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
