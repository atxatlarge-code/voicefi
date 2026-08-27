"""
Text injection and window focus utilities for macOS.
Uses AppleScript to paste or type transcribed text into Antigravity or the frontmost application.
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Any


DEFAULT_TERMINAL_APPS = (
    "Claude",
    "Claude Helper",
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


def restore_clipboard_delayed(prev_text: Optional[str], delay: float = 0.4):
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
                restore_clipboard_delayed(prev_clipboard, delay=0.4)
            return True
        else:
            print(f"[Injector] osascript notice (text is in clipboard): {result.stderr.strip()}")
            if preserve_clipboard and prev_clipboard is not None:
                restore_clipboard_delayed(prev_clipboard, delay=0.5)
            return False
    except Exception as e:
        print(f"[Injector] Injection exception: {e}")
        return False


from dataclasses import dataclass


@dataclass
class DispatchResult:
    success: bool
    delivery_type: str = "none"  # "ipc", "foreground_paste", "none"
    error: Optional[str] = None
    target_conv_id: Optional[str] = None
    engine: str = "antigravity"

    def __bool__(self) -> bool:
        return self.success

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, bool):
            return self.success == other
        return super().__eq__(other)



def send_message_to_antigravity(
    conv_id: Optional[str] = None,
    text: str = "",
    sender_name: Optional[str] = None,
    title: Optional[str] = None,
    from_conv_id: Optional[str] = None,
    allow_foreground_fallback: bool = False,
) -> DispatchResult:
    """
    Send prompt directly to Antigravity conversation via native agentapi IPC.
    This delivers the message cleanly in the background with 0 window focus changes,
    0 clipboard usage, and 0 screen flashing.
    Supports setting custom message titles, sender attribution, and return-routing.
    """
    if not text or not text.strip():
        return DispatchResult(success=False, delivery_type="none", error="Empty message text", engine="antigravity")

    clean_text = text.strip()
    agentapi_bin = Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi"

    # Resolve conv_id if "reply" or empty or placeholder
    target_id = conv_id
    if target_id == "reply":
        from voicefi.integrations.conversations import get_return_route
        route = get_return_route(target_engine="antigravity")
        if route and route.get("from_conv_id"):
            target_id = route.get("from_conv_id")
            print(f"[Injector] ↩️ Resolved return route to originating conversation: {str(target_id)[:8]}")

    if not target_id or target_id in ("active", "null", "none"):
        from voicefi.integrations.conversations import get_latest_antigravity_conversation_id
        target_id = get_latest_antigravity_conversation_id()

    resolved_title = title
    if not resolved_title:
        if sender_name:
            resolved_title = f"Message from {sender_name}"
        else:
            resolved_title = "Cross-Agent Message"

    if from_conv_id:
        from voicefi.integrations.conversations import record_agent_route
        record_agent_route(
            from_engine=sender_name.lower() if sender_name else "claude",
            from_conv_id=from_conv_id,
            to_engine="antigravity",
            to_conv_id=target_id,
        )

    if not agentapi_bin.is_file() or not os.access(agentapi_bin, os.X_OK):
        err = f"agentapi binary not found or not executable at {agentapi_bin}"
        print(f"[Injector] ❌ {err}")
        return DispatchResult(success=False, delivery_type="none", error=err, target_conv_id=target_id, engine="antigravity")

    if not target_id or str(target_id).startswith("claude_"):
        err = f"No valid Antigravity conversation ID found (resolved: {target_id})"
        print(f"[Injector] ❌ {err}")
        return DispatchResult(success=False, delivery_type="none", error=err, target_conv_id=target_id, engine="antigravity")

    from voicefi.integrations.antigravity_ls import get_agentapi_env, invalidate_antigravity_ls_cache

    env = get_agentapi_env(target_conv_id=target_id, force_refresh=False)
    cmd = [str(agentapi_bin), "send-message"]
    if resolved_title:
        cmd.append(f"--title={resolved_title}")
    cmd.extend([str(target_id), clean_text])

    last_stderr = ""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            timeout=6,
        )
        if res.returncode == 0:
            print(f"[Injector] 🚀 Delivered prompt directly via agentapi IPC to {str(target_id)[:8]} ({resolved_title or 'direct'})")
            return DispatchResult(success=True, delivery_type="ipc", target_conv_id=target_id, engine="antigravity")

        last_stderr = (res.stderr or res.stdout).strip()
        print(f"[Injector] agentapi notice (attempt 1): {last_stderr}")

        # If connection/auth error, invalidate cache and retry once
        if any(token in last_stderr for token in ("Unavailable", "Unauthenticated", "EOF", "error", "connection error")):
            invalidate_antigravity_ls_cache()
            env_retry = get_agentapi_env(target_conv_id=target_id, force_refresh=True)
            res2 = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env_retry,
                text=True,
                timeout=6,
            )
            if res2.returncode == 0:
                print(f"[Injector] 🚀 Delivered prompt directly via agentapi IPC on retry to {str(target_id)[:8]}")
                return DispatchResult(success=True, delivery_type="ipc", target_conv_id=target_id, engine="antigravity")
            last_stderr = (res2.stderr or res2.stdout).strip()
            print(f"[Injector] agentapi notice (retry): {last_stderr}")
    except Exception as e:
        last_stderr = str(e)
        print(f"[Injector] agentapi exception: {e}")

    # If foreground fallback is explicitly permitted (e.g. for dictation flows)
    if allow_foreground_fallback:
        pasted = inject_text_to_active_app(clean_text, submit_enter=True, target_antigravity=True, restore_focus=False)
        return DispatchResult(
            success=pasted,
            delivery_type="foreground_paste" if pasted else "none",
            error=last_stderr if not pasted else None,
            target_conv_id=target_id,
            engine="antigravity",
        )

    # For targeted cross-agent dispatches, NEVER fall back to pasting into foreground apps
    return DispatchResult(
        success=False,
        delivery_type="none",
        error=f"agentapi IPC delivery failed: {last_stderr}",
        target_conv_id=target_id,
        engine="antigravity",
    )




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


def focus_terminal_app() -> Optional[str]:
    """Find and focus the running terminal, coding editor, or Claude app."""
    applescript = '''
    tell application "System Events"
        set termApps to {"Claude", "Ghostty", "iTerm2", "iTerm", "Warp", "Terminal", "Cursor", "Code", "Visual Studio Code", "Windsurf", "Alacritty", "kitty", "WezTerm"}
        repeat with aName in termApps
            if (exists (process (aName as text))) then
                return (aName as text)
            end if
        end repeat
        return ""
    end tell
    '''
    try:
        res = subprocess.run(["osascript", "-e", applescript], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=3)
        found = res.stdout.strip()
        if found:
            subprocess.run(["osascript", "-e", f'tell application "{found}" to activate'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            time.sleep(0.15)
            return found
    except Exception:
        pass
    return None


def _focus_and_click_claude_desktop() -> bool:
    """Focus Claude Desktop app and post a synthetic mouse click to focus the prompt textarea."""
    try:
        import Quartz
        from AppKit import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        claude_apps = [app for app in ws.runningApplications() if app.localizedName() == "Claude"]
        if not claude_apps:
            return False
        claude_apps[0].activateWithOptions_(1 << 1)
        time.sleep(0.2)

        res = subprocess.run([
            "osascript", "-e",
            '''
            tell application "System Events"
                tell process "Claude"
                    return {position of window 1, size of window 1}
                end tell
            end tell
            '''
        ], capture_output=True, text=True, timeout=2)
        if res.returncode == 0 and res.stdout.strip():
            parts = [int(p.strip()) for p in res.stdout.strip().split(',')]
            x, y, w, h = parts[0], parts[1], parts[2], parts[3]
            click_x = x + (w / 2)
            click_y = y + h - 80
            pt = Quartz.CGPoint(click_x, click_y)
            down = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, pt, Quartz.kCGMouseButtonLeft)
            up = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, pt, Quartz.kCGMouseButtonLeft)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
            time.sleep(0.05)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
            time.sleep(0.15)
            return True
    except Exception as e:
        print(f"[Injector] Notice focusing Claude Desktop: {e}")
    return False


def inject_text_to_claude(
    text: str,
    submit_enter: bool = True,
    restore_focus: bool = False,
    preserve_clipboard: bool = True,
    from_conv_id: Optional[str] = None,
    from_engine: str = "antigravity",
    include_envelope: bool = False,
) -> bool:
    """
    Inject transcribed voice prompt or typed message into Claude Code terminal or Claude App.
    Optionally formats with a cross-agent provenance envelope and return instructions.
    """
    if not text or not text.strip():
        return False

    clean_text = text.strip()

    if include_envelope and from_conv_id:
        clean_text = f"""[From: {from_engine.capitalize()} | Conversation: {from_conv_id}]
{clean_text}

💡 To return your findings to Antigravity, run:
vifi send --to antigravity --reply "Your findings summary"
# or:
curl -s -X POST http://localhost:5141/api/send -H "Content-Type: application/json" -d '{{"text": "Your findings summary", "conv_id": "{from_conv_id}", "engine": "antigravity", "sender_name": "Claude"}}'"""

    if from_conv_id:
        from voicefi.integrations.conversations import record_agent_route
        record_agent_route(
            from_engine=from_engine,
            from_conv_id=from_conv_id,
            to_engine="claude",
        )

    prev_clipboard = get_clipboard_text() if preserve_clipboard else None

    # Step 1: Set clipboard
    if not set_clipboard_text(clean_text):
        return False

    time.sleep(0.05)

    # If Claude Desktop app is running, focus and click its input box
    app_name = focus_terminal_app()
    if app_name == "Claude":
        _focus_and_click_claude_desktop()

    enter_script = '''
            delay 0.15
            key code 36
    ''' if submit_enter else ''

    # Step 2: Bring Claude / Terminal to front and paste
    applescript = f'''
    tell application "System Events"
        set termApps to {{"Claude", "Ghostty", "iTerm2", "iTerm", "Warp", "Terminal", "Cursor", "Code", "Visual Studio Code", "Windsurf"}}
        set targetApp to ""
        repeat with aName in termApps
            if (exists (process (aName as text))) then
                set targetApp to (aName as text)
                exit repeat
            end if
        end repeat
    end tell

    if targetApp is not "" then
        tell application targetApp to activate
        delay 0.18
        tell application "System Events"
            tell process targetApp
                set frontmost to true
            end tell
            try
                tell process targetApp
                    click menu item "Paste" of menu "Edit" of menu bar item "Edit" of menu bar 1
                end tell
            on error
                keystroke "v" using command down
            end try
            {enter_script}
        end tell
        return true
    end if
    return false
    '''
    try:
        res = subprocess.run(["osascript", "-e", applescript], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4)
        success = "true" in res.stdout.lower()
        if preserve_clipboard and prev_clipboard is not None:
            restore_clipboard_delayed(prev_clipboard, delay=0.4)
        return success
    except Exception as e:
        print(f"[Injector] inject_text_to_claude error: {e}")
        if preserve_clipboard and prev_clipboard is not None:
            restore_clipboard_delayed(prev_clipboard, delay=0.4)
        return False


def send_message_to_agent(
    conv_id: Optional[str] = None,
    text: str = "",
    sender_name: Optional[str] = None,
    title: Optional[str] = None,
    target_engine: Optional[str] = None,
    from_conv_id: Optional[str] = None,
    from_engine: Optional[str] = None,
    include_envelope: bool = False,
    allow_foreground_fallback: bool = False,
) -> DispatchResult:
    """
    Unified dispatcher to send messages to Antigravity or Claude Code.
    Automatically resolves engine from conversation ID or active session cookie if unstated.
    """
    if not text or not text.strip():
        return DispatchResult(success=False, delivery_type="none", error="Empty message text")

    from voicefi.audio.echo_canceller import is_acoustic_echo
    if is_acoustic_echo(text.strip()):
        print(f"[Injector] 🛡️ Blocked injection of acoustic self-echo: \"{text.strip()[:50]}...\"")
        return DispatchResult(success=False, delivery_type="none", error="Suppressed acoustic self-echo")

    engine = target_engine
    if not engine and conv_id:
        if conv_id.startswith("claude_") or "claude" in conv_id.lower():
            engine = "claude"
        elif conv_id == "reply":
            from voicefi.integrations.conversations import get_return_route
            route = get_return_route()
            if route and route.get("from_engine"):
                engine = route.get("from_engine")
        else:
            engine = "antigravity"

    if not engine:
        from voicefi.integrations.conversations import load_session_cookie, ConversationTracker
        cookie = load_session_cookie()
        if cookie and cookie.get("engine"):
            engine = cookie["engine"]
        else:
            active = ConversationTracker().get_active_or_latest()
            if active:
                engine = getattr(active, "engine", "antigravity")

    engine = engine or "antigravity"

    if engine in ("claude", "claude_code"):
        print(f"[Injector] 🎭 Injecting prompt into Claude Code terminal: \"{text[:50]}...\"")
        resolved_from = from_conv_id
        if not resolved_from and include_envelope:
            from voicefi.integrations.conversations import get_latest_antigravity_conversation_id
            resolved_from = get_latest_antigravity_conversation_id()
        pasted = inject_text_to_claude(
            text,
            submit_enter=True,
            from_conv_id=resolved_from,
            from_engine=from_engine or "antigravity",
            include_envelope=include_envelope,
        )
        return DispatchResult(
            success=pasted,
            delivery_type="foreground_paste" if pasted else "none",
            error=None if pasted else "Failed to inject keystrokes into Claude terminal window",
            engine="claude",
        )
    else:
        return send_message_to_antigravity(
            conv_id=conv_id,
            text=text,
            sender_name=sender_name,
            title=title,
            from_conv_id=from_conv_id,
            allow_foreground_fallback=allow_foreground_fallback,
        )



