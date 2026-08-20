"""
Text injection and window focus utilities for macOS.
Uses AppleScript to paste or type transcribed text into Antigravity or the frontmost application.
"""

import subprocess
import time


def focus_antigravity() -> bool:
    """Bring Antigravity application window to the front on macOS."""
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Antigravity" to activate'],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        time.sleep(0.2)
        return True
    except Exception as e:
        print(f"[Injector] Error focusing Antigravity: {e}")
        return False


def inject_text_to_active_app(text: str, submit_enter: bool = True, target_antigravity: bool = False) -> bool:
    """
    Inject text into the active application or specifically Antigravity on macOS.
    
    Copies text to clipboard via pbcopy and triggers Cmd+V paste via AppleScript.
    """
    if not text or not text.strip():
        return False

    clean_text = text.strip()

    if target_antigravity:
        focus_antigravity()

    # Step 1: Copy to macOS clipboard using pbcopy
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(clean_text.encode("utf-8"))
    except Exception as e:
        print(f"[Injector] pbcopy error: {e}")
        return False

    time.sleep(0.1)

    # Step 2: AppleScript to paste into frontmost window
    enter_script = 'keystroke return' if submit_enter else ''
    applescript = f'''
    tell application "System Events"
        keystroke "v" using command down
        delay 0.1
        {enter_script}
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            return True
        else:
            print(f"[Injector] osascript notice (text is in clipboard): {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"[Injector] Injection exception: {e}")
        return False
