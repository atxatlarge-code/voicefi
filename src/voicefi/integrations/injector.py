"""
Text injection and window focus utilities for macOS.
Uses AppleScript to paste or type transcribed text into Antigravity or the frontmost application.
"""

import os
import re
import subprocess
import time
import threading
from pathlib import Path
from typing import Optional, Any, Dict


DEFAULT_TERMINAL_APPS = (
    "Claude",
    "Claude Helper",
    "ChatGPT",
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
    applescript = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        return name of frontApp
    end tell
    """
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


def is_frontmost_app_a_terminal(
    allowed_apps: tuple = DEFAULT_TERMINAL_APPS, fallback: bool = False
) -> bool:
    """Check if the currently active application is a supported terminal or coding editor."""
    app_name = get_frontmost_app_name()
    if not app_name:
        print(
            "[Injector] ⚠️ Unable to query frontmost application (Accessibility permissions may need granting). Defaulting to safe clipboard copy."
        )
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
            [
                "open",
                "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            ],
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
    Uses native AppKit NSWorkspace for instant (<5ms) window elevation.
    """
    activated = False
    try:
        from AppKit import (
            NSWorkspace,
            NSApplicationActivateIgnoringOtherApps,
            NSApplicationActivateAllWindows,
        )

        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            loc_name = (app.localizedName() or "").lower()
            bundle_id = (app.bundleIdentifier() or "").lower()
            if loc_name in ("antigravity", "antigravity ide") or bundle_id == "com.google.antigravity":
                app.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
                )
                activated = True
                break
    except Exception:
        pass

    if not focus_input and activated:
        return True

    applescript = (
        """
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
        delay 0.08
        if """
        + ("true" if focus_input else "false")
        + """ then
            tell application "System Events"
                keystroke "l" using command down
            end tell
        end if
        return true
    else
        -- Fallback: attempt to activate Antigravity directly
        try
            tell application "Antigravity" to activate
            delay 0.08
            if """
        + ("true" if focus_input else "false")
        + """ then
                tell application "System Events"
                    keystroke "l" using command down
                end tell
            end if
            return true
        on error
            return false
        end try
    end if
    """
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", applescript],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        return "true" in result.stdout.lower() or activated
    except Exception as e:
        if activated:
            return True
        print(f"[Injector] Error focusing Antigravity: {e}")
        return False


def navigate_to_antigravity_conversation(conv_id: str, title: Optional[str] = None) -> bool:
    """
    Navigate the Antigravity desktop window directly to a specific conversation by ID or title.
    Uses macOS Accessibility (AXUIElement) and Quartz mouse events to locate and click
    the conversation link without moving the user's mouse cursor.
    """
    if not conv_id:
        return False

    try:
        from AppKit import NSWorkspace
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
            AXUIElementSetAttributeValue,
            AXValueGetValue,
            kAXValueCGRectType,
        )
        import Quartz

        ws = NSWorkspace.sharedWorkspace()
        apps = [
            a
            for a in ws.runningApplications()
            if a.localizedName() in ("Antigravity", "Antigravity IDE")
        ]
        if not apps:
            return False
        app = apps[0]
        app.activateWithOptions_(1 << 1)
        time.sleep(0.12)

        app_ax = AXUIElementCreateApplication(app.processIdentifier())
        AXUIElementSetAttributeValue(app_ax, "AXManualAccessibility", True)
        err, windows = AXUIElementCopyAttributeValue(app_ax, "AXWindows", None)
        if not windows:
            return False
        win = windows[0]

        target_link = None

        def _find_link(el, depth=0):
            nonlocal target_link
            if target_link or depth > 35:
                return
            err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
            if role == "AXLink":
                err, url = AXUIElementCopyAttributeValue(el, "AXURL", None)
                url_str = str(url) if url else ""
                if conv_id and f"/c/{conv_id}" in url_str:
                    target_link = el
                    return
                if title:
                    err, desc = AXUIElementCopyAttributeValue(el, "AXDescription", None)
                    if desc and (
                        title.lower() in str(desc).lower() or str(desc).lower() in title.lower()
                    ):
                        target_link = el
                        return
            err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
            if children:
                for c in children:
                    _find_link(c, depth + 1)

        _find_link(win)

        # If not found in current sidebar, open conversation history with Cmd+Y to inspect full catalog
        if not target_link:
            subprocess.run(
                [
                    "osascript",
                    "-e",
                    'tell application "System Events" to keystroke "y" using command down',
                ],
                capture_output=True,
                timeout=2,
            )
            time.sleep(0.25)
            err, windows = AXUIElementCopyAttributeValue(app_ax, "AXWindows", None)
            if windows:
                _find_link(windows[0])

        if not target_link:
            return False

        err, frame_val = AXUIElementCopyAttributeValue(target_link, "AXFrame", None)
        if not frame_val:
            return False
        success, rect = AXValueGetValue(frame_val, kAXValueCGRectType, None)
        if not success or rect.size.width <= 0 or rect.size.height <= 0:
            return False

        center_x = rect.origin.x + rect.size.width / 2
        center_y = rect.origin.y + rect.size.height / 2
        prev_pos = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))

        point = Quartz.CGPoint(center_x, center_y)
        down = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseDown, point, Quartz.kCGMouseButtonLeft
        )
        up = Quartz.CGEventCreateMouseEvent(
            None, Quartz.kCGEventLeftMouseUp, point, Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
        time.sleep(0.04)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
        time.sleep(0.04)
        Quartz.CGWarpMouseCursorPosition(prev_pos)

        # Focus chat input with Cmd+L
        time.sleep(0.1)
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "l" using command down',
            ],
            capture_output=True,
            timeout=2,
        )
        return True
    except Exception as e:
        print(f"[Injector] Notice navigating to Antigravity conversation: {e}")
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
    if raw.lower().strip(".!?,") in (
        "scratch that",
        "cancel dictation",
        "clear dictation",
        "never mind",
        "nevermind",
        "cancel",
    ):
        print("[Injector] 🛑 Discarded dictation due to verbal cancel command.")
        return None

    # Strip conversational finish phrases at the end of dictation (e.g. "I'm done talking", "that's all")
    import re

    t = re.sub(
        r"(?i)[,\s]*(?:that(?:\'s|\s+is)\s+all|i(?:\'m|\s+am)\s+done(?:\s+talking)?|stop\s+listening|over(?:\s+and\s+out)?)[.!?\s]*$",
        "",
        raw,
    )

    # Replace formatting macros with whitespace cleanup
    t = re.sub(r"(?i)\s*\b(new line|newline)\b\s*", "\n", t)
    t = re.sub(r"(?i)\s*\bnew paragraph\b\s*", "\n\n", t)
    t = re.sub(r"(?i)\s*\bcomma\b", ",", t)
    t = re.sub(r"(?i)\s*\bperiod\b", ".", t)
    t = re.sub(r"(?i)\s*\bquestion mark\b", "?", t)
    t = re.sub(r"(?i)\s*\bexclamation (point|mark)\b", "!", t)

    # Clean up spaces before punctuation
    t = re.sub(r"\s+([,.\?!])", r"\1", t)
    return t.strip()


def get_clipboard_text() -> Optional[str]:
    """Retrieve the current clipboard text string."""
    try:
        res = subprocess.run(
            ["pbpaste"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1
        )
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
    if prev_text is None or os.environ.get("PYTEST_CURRENT_TEST"):
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
    new_conversation: bool = False,
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

    app_name = get_frontmost_app_name()
    from voicefi.tts.normalizer import format_for_app_context

    clean_text = format_for_app_context(processed, app_name=app_name)
    if not clean_text or not clean_text.strip():
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

    enter_script = "delay 0.12\n        keystroke return" if submit_enter else ""

    if target_antigravity:
        restore_script = (
            """
        if prevApp is not "" and prevApp is not foundApp and prevApp is not "Antigravity" and prevApp is not "Antigravity IDE" then
            delay 0.1
            try
                tell application prevApp to activate
            end try
        end if
        """
            if restore_focus
            else ""
        )

        new_conv_snippet = (
            """keystroke "n" using command down
            delay 0.25"""
            if new_conversation
            else ""
        )

        applescript = f"""
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
            {new_conv_snippet}
            keystroke "l" using command down
            delay 0.12
            keystroke "v" using command down
            {enter_script}
        end tell

        {restore_script}
        """
    else:
        applescript = f"""
        tell application "System Events"
            keystroke "v" using command down
            {enter_script}
        end tell
        """

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


def inject_text_to_antigravity(
    text: str,
    submit_enter: bool = True,
    restore_focus: bool = False,
    preserve_clipboard: bool = True,
    new_conversation: bool = False,
) -> bool:
    """
    Inject prompt directly into Antigravity IDE / Antigravity 2.0 chat interface.

    If new_conversation=False (default):
        Focuses the chat input of the current conversation/project ("send here"),
        pastes the prompt, and submits.
    If new_conversation=True:
        Triggers a new conversation session (Cmd+N / Cmd+L), pastes the prompt,
        and submits so the prompt is never lost or left empty.
    """
    return inject_text_to_active_app(
        text=text,
        submit_enter=submit_enter,
        target_antigravity=True,
        restore_focus=restore_focus,
        preserve_clipboard=preserve_clipboard,
        new_conversation=new_conversation,
    )


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "delivery_type": self.delivery_type,
            "error": self.error,
            "target_conv_id": self.target_conv_id,
            "engine": self.engine,
        }


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
        return DispatchResult(
            success=False, delivery_type="none", error="Empty message text", engine="antigravity"
        )

    clean_text = text.strip()
    agentapi_bin = Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi"

    # Resolve conv_id if "reply" or empty or placeholder
    target_id = conv_id
    if target_id == "reply":
        from voicefi.integrations.conversations import get_return_route

        route = get_return_route(target_engine="antigravity")
        if route and route.get("from_conv_id"):
            target_id = route.get("from_conv_id")
            print(
                f"[Injector] ↩️ Resolved return route to originating conversation: {str(target_id)[:8]}"
            )

    if not target_id or target_id in ("active", "null", "none"):
        from voicefi.integrations.conversations import get_latest_antigravity_conversation_id

        target_id = get_latest_antigravity_conversation_id()

    resolved_title = title
    if not resolved_title:
        if sender_name:
            resolved_title = f"Message from {sender_name}"
        else:
            resolved_title = "Message from ViFi Companion"

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
        return DispatchResult(
            success=False,
            delivery_type="none",
            error=err,
            target_conv_id=target_id,
            engine="antigravity",
        )

    if not target_id or str(target_id).startswith("claude_"):
        err = f"No valid Antigravity conversation ID found (resolved: {target_id})"
        print(f"[Injector] ❌ {err}")
        return DispatchResult(
            success=False,
            delivery_type="none",
            error=err,
            target_conv_id=target_id,
            engine="antigravity",
        )

    from voicefi.integrations.antigravity_ls import (
        get_agentapi_env,
        invalidate_antigravity_ls_cache,
    )

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
            print(
                f"[Injector] 🚀 Delivered prompt directly via agentapi IPC to {str(target_id)[:8]} ({resolved_title or 'direct'})"
            )
            return DispatchResult(
                success=True, delivery_type="ipc", target_conv_id=target_id, engine="antigravity"
            )

        last_stderr = (res.stderr or res.stdout).strip()
        print(f"[Injector] agentapi notice (attempt 1): {last_stderr}")

        # If connection/auth error, invalidate cache and retry once
        if any(
            token in last_stderr
            for token in ("Unavailable", "Unauthenticated", "EOF", "error", "connection error")
        ):
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
                print(
                    f"[Injector] 🚀 Delivered prompt directly via agentapi IPC on retry to {str(target_id)[:8]}"
                )
                return DispatchResult(
                    success=True,
                    delivery_type="ipc",
                    target_conv_id=target_id,
                    engine="antigravity",
                )
            last_stderr = (res2.stderr or res2.stdout).strip()
            print(f"[Injector] agentapi notice (retry): {last_stderr}")

        # If project permission denied (e.g. conversation created outside current project),
        # retry against the active workspace conversation ID rather than dropping the message
        if any(token in last_stderr for token in ("outside-of-project", "PermissionDenied", "permission_denied")):
            from voicefi.integrations.conversations import get_latest_antigravity_conversation_id
            latest_id = get_latest_antigravity_conversation_id()
            if latest_id and str(latest_id) != str(target_id):
                print(f"[Injector] 🔄 Rescuing turn with active workspace conversation: {str(latest_id)[:8]}")
                cmd_latest = [str(agentapi_bin), "send-message"]
                if resolved_title:
                    cmd_latest.append(f"--title={resolved_title}")
                cmd_latest.extend([str(latest_id), clean_text])
                res_rescued = subprocess.run(
                    cmd_latest,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True,
                    timeout=6,
                )
                if res_rescued.returncode == 0:
                    print(
                        f"[Injector] 🚀 Delivered prompt directly via agentapi IPC to rescued conversation {str(latest_id)[:8]}"
                    )
                    return DispatchResult(
                        success=True,
                        delivery_type="ipc",
                        target_conv_id=latest_id,
                        engine="antigravity",
                    )
                last_stderr = (res_rescued.stderr or res_rescued.stdout).strip()
                print(f"[Injector] agentapi rescue notice: {last_stderr}")
    except Exception as e:
        last_stderr = str(e)
        print(f"[Injector] agentapi exception: {e}")

    # If foreground fallback is explicitly permitted (e.g. for dictation flows)
    if allow_foreground_fallback:
        pasted = inject_text_to_active_app(
            clean_text, submit_enter=True, target_antigravity=True, restore_focus=False
        )
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
    Start a brand new Antigravity agent conversation and deliver the prompt.
    Returns the newly created conversation ID if detected, or None.
    """
    clean_prompt = (prompt or "Hello").strip()
    agentapi_bin = Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi"

    # 1. If Antigravity GUI is running on macOS, inject directly into the new conversation UI
    gui_injected = False
    try:
        from AppKit import NSWorkspace

        ws = NSWorkspace.sharedWorkspace()
        is_ag_running = any(
            (app.localizedName() or "").lower() in ("antigravity", "antigravity ide")
            or (app.bundleIdentifier() or "").lower() == "com.google.antigravity"
            for app in ws.runningApplications()
        )
        if is_ag_running and not os.environ.get("PYTEST_CURRENT_TEST"):
            gui_injected = inject_text_to_antigravity(
                clean_prompt,
                submit_enter=True,
                new_conversation=True,
            )
    except Exception as e:
        print(f"[Injector] Notice checking Antigravity GUI: {e}")

    # 2. Also register / create via agentapi if available
    if agentapi_bin.is_file() and os.access(agentapi_bin, os.X_OK):
        from voicefi.integrations.antigravity_ls import get_agentapi_env

        env = get_agentapi_env(force_refresh=False)
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
                env=env,
                text=True,
                timeout=8,
            )
            if res.returncode == 0:
                print(
                    f"[Injector] 🚀 Created new Antigravity conversation via agentapi: {res.stdout.strip()}"
                )
                try:
                    import json

                    out_data = json.loads(res.stdout)
                    cid = (
                        out_data.get("conversation_id")
                        or out_data.get("id")
                        or out_data.get("conversationId")
                        or (
                            out_data.get("response", {})
                            .get("newConversation", {})
                            .get("conversationId")
                            if isinstance(out_data.get("response"), dict)
                            else None
                        )
                    )
                    if cid:
                        from voicefi.integrations.conversations import save_session_cookie

                        save_session_cookie(conv_id=str(cid), title=title or clean_prompt[:40])
                        if not gui_injected:
                            focus_antigravity(focus_input=True)
                        return str(cid)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Injector] agentapi new-conversation exception: {e}")

    # 3. Fallback to GUI injection if agentapi wasn't used or failed
    if not gui_injected and not os.environ.get("PYTEST_CURRENT_TEST"):
        inject_text_to_antigravity(clean_prompt, submit_enter=True, new_conversation=True)

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
    term_priority = [
        "claude", "ghostty", "iterm2", "iterm", "warp",
        "cursor", "code", "visual studio code", "windsurf", "alacritty", "kitty", "wezterm", "terminal"
    ]
    try:
        from AppKit import (
            NSWorkspace,
            NSApplicationActivateIgnoringOtherApps,
            NSApplicationActivateAllWindows,
        )

        ws = NSWorkspace.sharedWorkspace()
        running = {(app.localizedName() or "").lower(): app for app in ws.runningApplications()}
        for name in term_priority:
            if name in running:
                app = running[name]
                app.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
                )
                return app.localizedName()
    except Exception:
        pass

    applescript = """
    tell application "System Events"
        set termApps to {"Claude", "Ghostty", "iTerm2", "iTerm", "Warp", "Terminal", "Cursor", "Code", "Visual Studio Code", "Windsurf", "Alacritty", "kitty", "WezTerm"}
        repeat with aName in termApps
            if (exists (process (aName as text))) then
                return (aName as text)
            end if
        end repeat
        return ""
    end tell
    """
    try:
        res = subprocess.run(
            ["osascript", "-e", applescript],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        found = res.stdout.strip()
        if found:
            subprocess.run(
                ["osascript", "-e", f'tell application "{found}" to activate'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            time.sleep(0.08)
            return found
    except Exception:
        pass
    return None


def _focus_and_click_claude_desktop() -> bool:
    """
    Focus Claude Desktop app and accurately focus the prompt textarea.
    Uses native macOS Accessibility (AXUIElement) with zero mouse movement,
    falling back to resilient window-relative coordinates.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    try:
        from AppKit import NSWorkspace
        import Quartz

        ws = NSWorkspace.sharedWorkspace()
        claude_apps = [app for app in ws.runningApplications() if app.localizedName() == "Claude"]
        if not claude_apps:
            return False

        claude_app = claude_apps[0]
        claude_app.activateWithOptions_(1 << 1)
        time.sleep(0.15)

        # 1. Try native AX focus on the Prompt AXTextArea (Zero mouse movement)
        try:
            from ApplicationServices import (
                AXUIElementCreateApplication,
                AXUIElementSetAttributeValue,
                AXUIElementCopyAttributeValue,
            )

            pid = claude_app.processIdentifier()
            app_ax = AXUIElementCreateApplication(pid)
            AXUIElementSetAttributeValue(app_ax, "AXManualAccessibility", True)

            err, windows = AXUIElementCopyAttributeValue(app_ax, "AXWindows", None)
            if windows:
                win = windows[0]
                target_textarea = None

                def _find_textarea(el):
                    nonlocal target_textarea
                    if target_textarea is not None:
                        return
                    err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
                    if role == "AXTextArea":
                        target_textarea = el
                        return
                    err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
                    if children:
                        for c in children:
                            _find_textarea(c)

                _find_textarea(win)

                if target_textarea:
                    # Set AXFocused directly without moving the mouse pointer
                    err = AXUIElementSetAttributeValue(target_textarea, "AXFocused", True)
                    if err == 0:
                        time.sleep(0.08)
                        return True
        except Exception as ax_err:
            print(f"[Injector] AX focus notice: {ax_err}")

        # 2. Resilient fallback: calculate window geometry (middle horizontal, 45px from bottom)
        res = subprocess.run(
            [
                "osascript",
                "-e",
                """
            tell application "System Events"
                tell process "Claude"
                    return {position of window 1, size of window 1}
                end tell
            end tell
            """,
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = [int(p.strip()) for p in res.stdout.strip().split(",")]
            x, y, w, h = parts[0], parts[1], parts[2], parts[3]
            click_x = x + (w / 2)
            click_y = y + h - 45  # 45px from bottom reliably hits prompt box center
            pt = Quartz.CGPoint(click_x, click_y)
            down = Quartz.CGEventCreateMouseEvent(
                None, Quartz.kCGEventLeftMouseDown, pt, Quartz.kCGMouseButtonLeft
            )
            up = Quartz.CGEventCreateMouseEvent(
                None, Quartz.kCGEventLeftMouseUp, pt, Quartz.kCGMouseButtonLeft
            )
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
            time.sleep(0.05)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)
            time.sleep(0.12)
            return True
    except Exception as e:
        print(f"[Injector] Notice focusing Claude Desktop: {e}")
    return False


def _click_claude_desktop_send() -> bool:
    """
    Click the 'Send' button in Claude Desktop via Accessibility API.
    Returns True if successfully pressed.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    try:
        from AppKit import NSWorkspace
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
            AXUIElementPerformAction,
            AXUIElementSetAttributeValue,
        )

        ws = NSWorkspace.sharedWorkspace()
        claude_apps = [app for app in ws.runningApplications() if app.localizedName() == "Claude"]
        if not claude_apps:
            return False

        claude_app = claude_apps[0]
        pid = claude_app.processIdentifier()
        app_ax = AXUIElementCreateApplication(pid)
        AXUIElementSetAttributeValue(app_ax, "AXManualAccessibility", True)

        err, windows = AXUIElementCopyAttributeValue(app_ax, "AXWindows", None)
        if not windows:
            return False

        win = windows[0]
        send_btn = [None]

        def _find_send(el):
            if send_btn[0] is not None:
                return
            err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
            err, desc = AXUIElementCopyAttributeValue(el, "AXDescription", None)
            if role == "AXButton" and desc == "Send":
                send_btn[0] = el
                return
            err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
            if children:
                for c in children:
                    _find_send(c)

        _find_send(win)
        if send_btn[0]:
            err = AXUIElementPerformAction(send_btn[0], "AXPress")
            return err == 0
    except Exception as e:
        print(f"[Injector] Notice clicking Claude Desktop send button: {e}")
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
    is_claude_desktop = False
    try:
        from AppKit import NSWorkspace
        ws = NSWorkspace.sharedWorkspace()
        is_claude_desktop = any(app.localizedName() == "Claude" for app in ws.runningApplications())
    except Exception:
        pass

    if is_claude_desktop:
        _focus_and_click_claude_desktop()
        app_name = "Claude"
    else:
        app_name = focus_terminal_app()

    enter_script = (
        """
            delay 0.15
            key code 36
    """
        if submit_enter
        else ""
    )

    # Step 2: Bring Claude / Terminal to front and paste
    applescript = f"""
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
        delay 0.15
        tell application "System Events"
            tell process targetApp
                set frontmost to true
            end tell
            if targetApp is "Claude" then
                -- Claude Desktop (Electron): keystroke cmd+v directly to prevent Edit menu bar focus drop
                keystroke "v" using command down
            else
                try
                    tell process targetApp
                        click menu item "Paste" of menu "Edit" of menu bar item "Edit" of menu bar 1
                    end tell
                on error
                    keystroke "v" using command down
                end try
            end if
            {enter_script}
        end tell
        return true
    end if
    return false
    """
    try:
        res = subprocess.run(
            ["osascript", "-e", applescript],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
        )
        success = "true" in res.stdout.lower()
        if is_claude_desktop and submit_enter:
            time.sleep(0.1)
            _click_claude_desktop_send()
        if preserve_clipboard and prev_clipboard is not None:
            restore_clipboard_delayed(prev_clipboard, delay=0.4)
        return success
    except Exception as e:
        print(f"[Injector] inject_text_to_claude error: {e}")
        if preserve_clipboard and prev_clipboard is not None:
            restore_clipboard_delayed(prev_clipboard, delay=0.4)
        return False


def focus_chatgpt(focus_input: bool = True) -> bool:
    """
    Bring ChatGPT macOS desktop application to the front.
    Uses native AppKit NSWorkspace fast-path to prevent AppleScript timeouts when not running.
    """
    try:
        from AppKit import (
            NSWorkspace,
            NSApplicationActivateIgnoringOtherApps,
            NSApplicationActivateAllWindows,
        )

        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            loc = (app.localizedName() or "").lower()
            bundle = (app.bundleIdentifier() or "").lower()
            if "chatgpt" in loc or bundle in ("com.openai.chat", "com.openai.chatgpt"):
                app.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
                )
                return True
    except Exception:
        pass

    applescript = """
    tell application "System Events"
        if exists (process "ChatGPT") then
            tell application "ChatGPT" to activate
            delay 0.08
            tell process "ChatGPT"
                set frontmost to true
            end tell
            return true
        end if
    end tell
    return false
    """
    try:
        res = subprocess.run(
            ["osascript", "-e", applescript],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
        )
        return "true" in res.stdout.lower()
    except Exception:
        return False


def inject_text_to_chatgpt(
    text: str,
    submit_enter: bool = True,
    restore_focus: bool = False,
    preserve_clipboard: bool = True,
) -> bool:
    """
    Inject transcribed voice prompt or message into ChatGPT for Mac desktop app.
    """
    if not text or not text.strip():
        return False

    clean_text = text.strip()
    prev_clipboard = get_clipboard_text() if preserve_clipboard else None

    if not set_clipboard_text(clean_text):
        return False

    time.sleep(0.05)

    enter_script = (
        """
            delay 0.15
            key code 36
    """
        if submit_enter
        else ""
    )

    applescript = f"""
    tell application "System Events"
        if exists (process "ChatGPT") then
            tell application "ChatGPT" to activate
            delay 0.18
            tell process "ChatGPT"
                set frontmost to true
                try
                    click menu item "Paste" of menu "Edit" of menu bar item "Edit" of menu bar 1
                on error
                    keystroke "v" using command down
                end try
                {enter_script}
            end tell
            return true
        end if
    end tell
    return false
    """
    try:
        res = subprocess.run(
            ["osascript", "-e", applescript],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=4,
        )
        success = "true" in res.stdout.lower()
        if preserve_clipboard and prev_clipboard is not None:
            restore_clipboard_delayed(prev_clipboard, delay=0.4)
        return success
    except Exception as e:
        print(f"[Injector] inject_text_to_chatgpt error: {e}")
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
    use_headless: Optional[bool] = None,
    cwd: Optional[Path] = None,
    engine: Optional[str] = None,
    **kwargs: Any,
) -> DispatchResult:
    """
    Unified dispatcher to send messages to Antigravity, Claude Code, or ChatGPT Desktop.
    Automatically resolves engine from conversation ID or active session cookie if unstated.
    Supports zero-flicker headless execution for Claude Code when requested or configured.
    """
    if not text or not text.strip():
        return DispatchResult(success=False, delivery_type="none", error="Empty message text")

    engine = target_engine or engine
    cleaned_lower = text.strip().lower()

    # 1. If conversation ID is explicitly a Claude session, always route to Claude
    if conv_id and (conv_id.startswith("claude_") or "claude" in conv_id.lower()):
        engine = "claude"
    elif conv_id and (
        conv_id.startswith("chatgpt_")
        or "chatgpt" in conv_id.lower()
        or "openai" in conv_id.lower()
    ):
        engine = "chatgpt"

    # 2. Resilient spoken intent detection for Claude (e.g. 'all right Claude can you tell me a joke')
    explicit_claude = bool(
        re.search(
            r"\b(?:hey|ask|tell|all\s+right|alright|okay|so|can\s+you\s+ask|could\s+you\s+ask|send\s+to|talk\s+to|switch\s+to|have|message)?\s*claude\b",
            cleaned_lower,
        )
    )
    if explicit_claude:
        engine = "claude"

    if not engine and conv_id:
        if conv_id == "reply":
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
        from voicefi.config import load_config
        cfg = load_config()
        claude_cfg = getattr(cfg, "claude", None)
        mode = getattr(claude_cfg, "dispatch_mode", "auto")

        from voicefi.integrations.conversations import (
            has_active_companion_client,
            peek_mobile_turn_origin,
        )

        is_mobile = (
            sender_name in ("Pixel Remote", "Mobile Companion", "ViFi Companion")
            or (conv_id and peek_mobile_turn_origin(conv_id))
            or has_active_companion_client()
        )

        run_headless = False
        if use_headless is True:
            run_headless = True
        elif use_headless is False:
            run_headless = False
        elif mode == "headless":
            run_headless = True
        elif mode == "auto":
            run_headless = bool(is_mobile)

        resolved_from = from_conv_id
        if not resolved_from and include_envelope:
            from voicefi.integrations.conversations import get_latest_antigravity_conversation_id
            resolved_from = get_latest_antigravity_conversation_id()

        if run_headless:
            from voicefi.integrations.claude_runner import ClaudeHeadlessRunner
            runner = ClaudeHeadlessRunner.get_instance()
            turn_origin = "mobile" if is_mobile else "desktop"
            return runner.dispatch(
                text=text,
                conv_id=conv_id,
                cwd=cwd,
                from_conv_id=resolved_from,
                from_engine=from_engine or "antigravity",
                include_envelope=include_envelope,
                config=cfg,
                origin=turn_origin,
            )

        print(f'[Injector] 🎭 Injecting prompt into Claude Code terminal: "{text[:50]}..."')
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
    elif engine in ("chatgpt", "openai", "codex"):
        print(f'[Injector] 🤖 Injecting prompt into ChatGPT / Codex Desktop: "{text[:50]}..."')
        pasted = inject_text_to_chatgpt(text, submit_enter=True)
        return DispatchResult(
            success=pasted,
            delivery_type="foreground_paste" if pasted else "none",
            error=None if pasted else "Failed to inject prompt into ChatGPT for Mac",
            engine=engine,
        )
    elif engine in ("gemini", "gemini_cli"):
        print(f'[Injector] 🚀 Dispatching prompt to Gemini agent: "{text[:50]}..."')
        return send_message_to_antigravity(
            conv_id=conv_id,
            text=text,
            sender_name=sender_name or "Gemini",
            title=title,
            from_conv_id=from_conv_id,
            allow_foreground_fallback=allow_foreground_fallback,
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


def focus_app_by_name(app_name: str) -> bool:
    """
    Bring any macOS application to the front by its localized name.
    Uses AppKit NSWorkspace with NSApplicationActivateIgnoringOtherApps (1 << 1),
    falling back to AppleScript.
    """
    if not app_name or not app_name.strip():
        return False
    target = app_name.strip()

    # 1. Try native AppKit NSWorkspace
    try:
        from AppKit import NSWorkspace

        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            loc_name = app.localizedName()
            if loc_name and (
                loc_name.lower() == target.lower() or target.lower() in loc_name.lower()
            ):
                app.activateWithOptions_(1 << 1)
                return True
    except Exception:
        pass

    # 2. Fallback to AppleScript
    applescript = f'''
    tell application "System Events"
        if exists (process "{target}") then
            tell application "{target}" to activate
            return true
        end if
    end tell
    try
        tell application "{target}" to activate
        return true
    on error
        return false
    end try
    '''
    try:
        res = subprocess.run(
            ["osascript", "-e", applescript],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=2,
        )
        return "true" in res.stdout.lower()
    except Exception:
        return False


_FOCUS_LOCK = threading.Lock()
_LAST_FOCUS_TS = 0.0
_FOCUS_DEBOUNCE_INTERVAL = 0.35


def focus_speaking_agent_window(
    agent_name: Optional[str] = None,
    app_name: Optional[str] = None,
    conv_id: Optional[str] = None,
    force: bool = False,
) -> bool:
    """
    Focus the window/application where the current or most recent speech turn originated.
    Invoked when pressing Tab while an AI agent is speaking aloud (or recently spoke).
    Supports Antigravity, Claude Code, ChatGPT, IDEs, and custom app targets.
    Thread-safe with sliding debounce to prevent subprocess storms.
    """
    global _LAST_FOCUS_TS
    now = time.time()
    with _FOCUS_LOCK:
        if (
            not force
            and not os.environ.get("PYTEST_CURRENT_TEST")
            and (now - _LAST_FOCUS_TS) < _FOCUS_DEBOUNCE_INTERVAL
        ):
            return True
        _LAST_FOCUS_TS = now

    # 1. If arguments not provided, dynamically read from active speaking status,
    # recent speaking cache, or cross-process HUD state
    if not agent_name and not app_name:
        try:
            from voicefi.tts.base import (
                get_agent_speaking_info,
                get_recent_speaking_info,
                get_cross_process_hud_state,
            )

            info = (
                get_agent_speaking_info()
                or get_recent_speaking_info(window_seconds=3.5)
                or get_cross_process_hud_state()
            )
            if info and isinstance(info, dict):
                agent_name = agent_name or info.get("agent_name")
                app_name = app_name or info.get("app_name")
                conv_id = conv_id or info.get("conv_id")
        except Exception:
            pass

    # Update active conversation tracking if conv_id is present
    if conv_id:
        try:
            from voicefi.integrations.conversations import ConversationTracker

            ConversationTracker().set_active_focus(conv_id)
        except Exception:
            pass

    agent_lower = (agent_name or "").lower()
    app_lower = (app_name or "").lower()

    # 2. Route based on agent/app identity:
    # 2a. Claude Code or Claude Desktop
    if "claude" in agent_lower or "claude" in app_lower:
        print("[Injector] 🎯 Tab to Focus: Focusing Claude / Terminal window...")
        if focus_terminal_app():
            return True
        if _focus_and_click_claude_desktop():
            return True
        return focus_app_by_name("Claude")

    # 2b. ChatGPT Desktop
    if "chatgpt" in agent_lower or "openai" in agent_lower or "chatgpt" in app_lower:
        print("[Injector] 🎯 Tab to Focus: Focusing ChatGPT window...")
        return focus_chatgpt(focus_input=True)

    # 2c. Specific app name provided (e.g. Ghostty, Cursor, Code, Terminal, Warp, Obsidian, etc.)
    if app_name and app_lower not in ("antigravity", "antigravity ide", "voicefi", "viv", "agent"):
        print(f"[Injector] 🎯 Tab to Focus: Focusing {app_name} window...")
        if focus_app_by_name(app_name):
            return True

    # 2d. Antigravity / Subagents / Default
    print(f"[Injector] 🎯 Tab to Focus: Focusing Antigravity window (agent: {agent_name or 'Antigravity'})...")
    focused = focus_antigravity(focus_input=True)
    if not focused and app_name:
        focused = focus_app_by_name(app_name)
    if not focused:
        focused = bool(focus_terminal_app())
    return focused

