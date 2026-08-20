"""
System audio cues for Talk 2 Me.
Plays lightweight macOS sound effects for listening state transitions.
"""

import os
import subprocess
import threading
from typing import Optional
from pathlib import Path


SYSTEM_SOUNDS = {
    "start": "/System/Library/Sounds/Tink.aiff",
    "done": "/System/Library/Sounds/Pop.aiff",
    "error": "/System/Library/Sounds/Basso.aiff",
    "alert": "/System/Library/Sounds/Glass.aiff",
}


def play_chime(sound_key_or_path: str, block: bool = False) -> None:
    """
    Play a system audio cue using macOS afplay.
    
    Args:
        sound_key_or_path: Key in SYSTEM_SOUNDS (e.g. 'start', 'done') or absolute path to an audio file.
        block: Whether to block execution until the sound finishes.
    """
    sound_path = SYSTEM_SOUNDS.get(sound_key_or_path, sound_key_or_path)
    
    if not os.path.exists(sound_path):
        return

    def _run():
        try:
            subprocess.run(["afplay", sound_path], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    if block:
        _run()
    else:
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
