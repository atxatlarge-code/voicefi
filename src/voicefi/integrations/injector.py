"""
Text injection and window focus utilities for macOS.
Uses AppleScript to paste or type transcribed text into Antigravity or the frontmost application.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional


DEFAULT_TERMINAL_APPS = (
    "Terminal",
    "iTerm2",
    "iTerm",
    "Warp",
    "Ghostty",
    "Alacritty",
    "kitty",
    "WezTerm",
    "Hyper",
    "Code",
    "Visual Studio Code",
    "Cursor",
    "Windsurf",
)


def get_frontmost_app_name() -> str:
    """Return the display name of the current frontmost active application on macOS."""
    applescript = '''
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        return name of frontApp
    end tell
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def is_frontmost_app_a_terminal(allowed_apps: tuple = DEFAULT_TERMINAL_APPS, fallback: bool = False) -> bool:
    """Check if the currently active application is a supported terminal or coding editor."""
    app_name = get_frontmost_app_name()
    if not app_name:
        print("[Injector] ⚠️ Unable to query frontmost application (Accessibility permissions may need granting). Defaulting to safe clipboard copy.")
        return fallback
    app_lower = app_name.lower()
    for allowed in allowed_apps:
        if allowed.lower() in app_lower:
            return True
    return False


def open_accessibility_settings() -> None:
    """Open the macOS Accessibility and Input Monitoring Privacy settings panes directly."""
    try:
        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        subprocess.run(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def focus_antigravity(focus_input: bool = True) -> bool:
    """
    Bring Antigravity application window to the front and focus chat input box.
    Supports both standalone Antigravity and Antigravity IDE.
    """
    applescript = '''
    tell application "System Events"
        set appNames to {"Antigravity", "Antigravity IDE"}
        set foundApp to ""
        repeat with aName in appNames
            if (exists (process (aName as text))) then
                set foundApp to (aName as text)
                exit repeat
            end if
        end repeat
    end tell

    if foundApp is not "" then
        tell application foundApp to activate
        delay 0.2
        if ''' + ('true' if focus_input else 'false') + ''' then
            tell application "System Events"
                keystroke "l" using command down
            end tell
        end if
        return true
    else
        -- Fallback: attempt to activate Antigravity directly
        try
            tell application "Antigravity" to activate
            delay 0.2
            if ''' + ('true' if focus_input else 'false') + ''' then
                tell application "System Events"
                    keystroke "l" using command down
                end tell
            end if
            return true
        on error
            return false
        end try
    end if
    '''
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        return "true" in result.stdout.lower()
    except Exception as e:
        print(f"[Injector] Error focusing Antigravity: {e}")
        return False


_LAST_INJECTED_TEXT = ""
_LAST_INJECT_TIME = 0.0


def process_dictation_macros(text: str) -> Optional[str]:
    """
    Process spoken formatting macros and verbal command cues.
    Returns formatted text string, or None if speech contained a cancel command.
    """
    if not text:
        return None
    raw = text.strip()
    # Check cancel commands
    if raw.lower().strip('.!?,') in ('scratch that', 'cancel dictation', 'clear dictation', 'never mind', 'nevermind', 'cancel'):
        print("[Injector] 🛑 Discarded dictation due to verbal cancel command.")
        return None

    # Strip conversational finish phrases at the end of dictation (e.g. "I'm done talking", "that's all")
    import re
    t = re.sub(r'(?i)[,\s]*(?:that(?:\'s|\s+is)\s+all|i(?:\'m|\s+am)\s+done(?:\s+talking)?|stop\s+listening|over(?:\s+and\s+out)?)[.!?\s]*$', '', raw)

    # Replace formatting macros with whitespace cleanup
    t = re.sub(r'(?i)\s*\b(new line|newline)\b\s*', '\n', t)
    t = re.sub(r'(?i)\s*\bnew paragraph\b\s*', '\n\n', t)
    t = re.sub(r'(?i)\s*\bcomma\b', ',', t)
    t = re.sub(r'(?i)\s*\bperiod\b', '.', t)
    t = re.sub(r'(?i)\s*\bquestion mark\b', '?', t)
    t = re.sub(r'(?i)\s*\bexclamation (point|mark)\b', '!', t)

    # Clean up spaces before punctuation
    t = re.sub(r'\s+([,.\?!])', r'\1', t)
    return t.strip()


def get_clipboard_text() -> Optional[str]:
    """Retrieve the current clipboard text string."""
    try:
        res = subprocess.run(["pbpaste"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1)
        return res.stdout.decode("utf-8")
    except Exception:
        return None


def set_clipboard_text(text: str) -> bool:
    """Set the system clipboard text."""
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        proc.communicate(text.encode("utf-8"), timeout=1)
        return True
    except Exception:
        return False


def restore_clipboard_delayed(prev_text: Optional[str], delay: float = 0.2):
    """Restore the previous clipboard text in the background after pasting."""
    if prev_text is None:
        return

    def _worker():
        time.sleep(delay)
        set_clipboard_text(prev_text)

    import threading
    threading.Thread(target=_worker, daemon=True).start()


def inject_text_to_active_app(
    text: str,
    submit_enter: bool = True,
    target_antigravity: bool = False,
    restore_focus: bool = False,
    preserve_clipboard: bool = True,
) -> bool:
    """
    Inject text into the active application or specifically Antigravity on macOS.
    
    If target_antigravity=True and restore_focus=True, activates Antigravity,
    pastes/submits the prompt into the chat box, and immediately restores focus
    back to the user's previously active application so their screen never gets hijacked.
    """
    global _LAST_INJECTED_TEXT, _LAST_INJECT_TIME
    if not text or not text.strip():
        return False

    # Process verbal macros (e.g. "scratch that" -> cancel, "new line" -> \n)
    processed = process_dictation_macros(text)
    if processed is None:
        return False

    clean_text = processed
    now = time.time()
    if clean_text == _LAST_INJECTED_TEXT and (now - _LAST_INJECT_TIME) < 0.8:
        print("[Injector] Ignored duplicate injection within 0.8s window")
        return True

    _LAST_INJECTED_TEXT = clean_text
    _LAST_INJECT_TIME = now

    # Backup current clipboard if preservation is enabled
    prev_clipboard = get_clipboard_text() if preserve_clipboard else None

    # Step 1: Copy to macOS clipboard using pbcopy
    if not set_clipboard_text(clean_text):
        return False

    time.sleep(0.06)

    enter_script = 'delay 0.12\n        keystroke return' if submit_enter else ''

    if target_antigravity:
        restore_script = '''
        if prevApp is not "" and prevApp is not foundApp and prevApp is not "Antigravity" and prevApp is not "Antigravity IDE" then
            delay 0.1
            try
                tell application prevApp to activate
            end try
        end if
        ''' if restore_focus else ''

        applescript = f'''
        tell application "System Events"
            set prevApp to name of first application process whose frontmost is true
            set appNames to {{"Antigravity", "Antigravity IDE"}}
            set foundApp to ""
            repeat with aName in appNames
                if (exists (process (aName as text))) then
                    set foundApp to (aName as text)
                    exit repeat
                end if
            end repeat
        end tell

        if foundApp is not "" then
            tell application foundApp to activate
        else
            try
                tell application "Antigravity" to activate
            end try
        end if

        delay 0.2
        tell application "System Events"
            keystroke "l" using command down
            delay 0.12
            keystroke "v" using command down
            {enter_script}
        end tell

        {restore_script}
        '''
    else:
        applescript = f'''
        tell application "System Events"
            keystroke "v" using command down
            {enter_script}
        end tell
        '''

    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
        )
        if result.returncode == 0:
            if preserve_clipboard and prev_clipboard is not None:
                restore_clipboard_delayed(prev_clipboard, delay=0.18)
            return True
        else:
            print(f"[Injector] osascript notice (text is in clipboard): {result.stderr.strip()}")
            if preserve_clipboard and prev_clipboard is not None:
                restore_clipboard_delayed(prev_clipboard, delay=0.5)
            return False
    except Exception as e:
        print(f"[Injector] Injection exception: {e}")
        return False


def send_message_to_antigravity(
    conv_id: Optional[str] = None,
    text: str = "",
    sender_name: Optional[str] = None,
    title: Optional[str] = None,
) -> bool:
    """
    Send prompt directly to Antigravity conversation via native agentapi IPC.
    This delivers the message cleanly in the background with 0 window focus changes,
    0 clipboard usage, and 0 screen flashing.
    Supports setting custom message titles and sender attribution (e.g. 'Aria', 'Jake').
    """
    if not text or not text.strip():
        return False

    clean_text = text.strip()
    agentapi_bin = Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi"

    if not conv_id:
        try:
            from voicefi.integrations.conversations import ConversationTracker
            active = ConversationTracker().get_active_or_latest()
            if active:
                conv_id = active.id
        except Exception:
            pass

    resolved_title = title
    if not resolved_title and sender_name:
        resolved_title = f"Message from {sender_name}"

    if agentapi_bin.is_file() and os.access(agentapi_bin, os.X_OK) and conv_id:
        try:
            cmd = [str(agentapi_bin), "send-message"]
            if resolved_title:
                cmd.append(f"--title={resolved_title}")
            cmd.extend([str(conv_id), clean_text])
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                print(f"[Injector] 🚀 Delivered prompt directly via agentapi IPC to {conv_id[:8]} ({resolved_title or 'direct'})")
                return True
            else:
                print(f"[Injector] agentapi notice: {res.stderr.strip()}")
                print(f"[Injector] Active session may have expired. Attempting to create new conversation...")
                new_id = create_new_antigravity_conversation(prompt=clean_text, title=resolved_title)
                if new_id:
                    return True
        except Exception as e:
            print(f"[Injector] agentapi exception: {e}")
            
    if not conv_id:
        print("[Injector] No active session found. Creating a new conversation...")
        new_id = create_new_antigravity_conversation(prompt=clean_text, title=resolved_title)
        if new_id:
            return True

    # Fallback to AppleScript paste with focus restoration
    return inject_text_to_active_app(clean_text, submit_enter=True, target_antigravity=True, restore_focus=True)


def create_new_antigravity_conversation(
    prompt: str = "Hello",
    title: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[str]:
    """
    Start a brand new Antigravity agent conversation.
    Returns the newly created conversation ID if detected, or None.
    """
    clean_prompt = (prompt or "Hello").strip()
    agentapi_bin = Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi"

    if agentapi_bin.is_file() and os.access(agentapi_bin, os.X_OK):
        cmd = [str(agentapi_bin), "new-conversation"]
        if model:
            cmd.append(f"--model={model}")
        if title:
            cmd.append(f"--title={title}")
        cmd.append(clean_prompt)
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8,
            )
            if res.returncode == 0:
                print(f"[Injector] 🚀 Created new Antigravity conversation via agentapi: {res.stdout.strip()}")
                try:
                    import json
                    out_data = json.loads(res.stdout)
                    cid = out_data.get("conversation_id") or out_data.get("id") or out_data.get("conversationId")
                    if cid:
                        from voicefi.integrations.conversations import save_session_cookie
                        save_session_cookie(conv_id=str(cid), title=title or clean_prompt[:40])
                        return str(cid)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Injector] agentapi new-conversation exception: {e}")

    # Fallback to AppleScript
    applescript = '''
    tell application "System Events"
        set appNames to {"Antigravity", "Antigravity IDE"}
        set foundApp to ""
        repeat with aName in appNames
            if (exists (process (aName as text))) then
                set foundApp to (aName as text)
                exit repeat
            end if
        end repeat
    end tell

    if foundApp is not "" then
        tell application foundApp to activate
        delay 0.2
        tell application "System Events"
            keystroke "n" using command down
            delay 0.2
            keystroke "l" using command down
        end tell
        return true
    end if
    return false
    '''
    try:
        subprocess.run(["osascript", "-e", applescript], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4)
    except Exception:
        pass

    time.sleep(0.5)
    try:
        from voicefi.integrations.conversations import ConversationTracker, save_session_cookie
        active = ConversationTracker().get_active_or_latest()
        if active:
            save_session_cookie(conv_id=active.id, title=title or clean_prompt[:40])
            return active.id
    except Exception:
        pass
    return None
