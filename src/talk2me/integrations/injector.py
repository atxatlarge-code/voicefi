"""
Text injection utilities for macOS.
Uses AppleScript to paste or type transcribed text into the frontmost application.
"""

import subprocess
import time


def inject_text_to_active_app(text: str, submit_enter: bool = True) -> bool:
    """
    Inject text into the currently active application on macOS.
    
    Copies text to clipboard and triggers Cmd+V paste for speed and emoji/unicode support,
    optionally followed by pressing Enter/Return.
    """
    if not text or not text.strip():
        return False

    clean_text = text.strip()

    # Step 1: Copy to macOS clipboard using pbcopy
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(clean_text.encode("utf-8"))
    except Exception as e:
        print(f"[Injector] pbcopy error: {e}")
        return False

    # Small sleep to ensure clipboard is populated
    time.sleep(0.05)

    # Step 2: AppleScript to paste Cmd+V and optionally press Enter
    enter_script = 'keystroke return' if submit_enter else ''
    applescript = f'''
    tell application "System Events"
        keystroke "v" using command down
        delay 0.1
        {enter_script}
    end tell
    '''

    try:
        subprocess.run(
            ["osascript", "-e", applescript],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as e:
        print(f"[Injector] osascript injection error: {e}")
        return False
