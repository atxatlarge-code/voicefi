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
from typing import Optional, Any, Dict, List, Tuple


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


def cooperative_activate_app(target_app: Any) -> bool:
    """
    Cooperatively activate target macOS application without focus drops on macOS 14+ (Sonoma/Sequoia).
    Yields the current process's activation token to the target application before requesting activation.
    Falls back gracefully to activateWithOptions_ on macOS 11-13.
    """
    if not target_app:
        return False

    try:
        from AppKit import NSApplication, NSRunningApplication

        # On macOS 14+, NSApplication.sharedApplication() or NSRunningApplication supports yieldActivationToApplication:
        ns_app = NSApplication.sharedApplication()
        if hasattr(ns_app, "yieldActivationToApplication_"):
            try:
                ns_app.yieldActivationToApplication_(target_app)
            except Exception:
                pass
        else:
            curr = NSRunningApplication.currentApplication()
            if hasattr(curr, "yieldActivationToApplication_"):
                try:
                    curr.yieldActivationToApplication_(target_app)
                except Exception:
                    pass

        # Request target app activation (macOS 14+ activate)
        if hasattr(target_app, "activate"):
            try:
                res = target_app.activate()
                if res is True or res is None:
                    return True
            except Exception:
                pass

        # Fallback for macOS 11-13 or older runtimes
        if hasattr(target_app, "activateWithOptions_"):
            return bool(target_app.activateWithOptions_(3))
    except Exception:
        pass

    return False


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
            if (
                loc_name in ("antigravity", "antigravity ide")
                or bundle_id == "com.google.antigravity"
            ):
                activated = cooperative_activate_app(app)
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


def _navigate_antigravity_via_cdp(conv_id: str, project_id: Optional[str] = None) -> bool:
    """
    Navigate Antigravity 2.0 directly to `/c/<conv_id>?section=<project_id>` via its local
    DevToolsActivePort using a zero-dependency WebSocket Runtime.evaluate call.
    Works reliably even when the sidebar is virtualized or the project section is collapsed.
    """
    if not conv_id:
        return False
    try:
        import base64
        import json
        import socket
        import struct
        import urllib.request
        from pathlib import Path

        port_file = (
            Path.home() / "Library" / "Application Support" / "Antigravity" / "DevToolsActivePort"
        )
        if not port_file.is_file():
            return False
        lines = port_file.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        if not lines:
            return False
        port = int(lines[0].strip())

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=0.45) as resp:
            targets = json.loads(resp.read().decode("utf-8", errors="ignore"))

        ws_url = None
        for t in targets:
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                ws_url = t["webSocketDebuggerUrl"]
                break
        if not ws_url:
            return False

        # Parse ws://127.0.0.1:<port>/devtools/page/<id>
        without_scheme = ws_url.split("://", 1)[-1]
        host_port, path_part = without_scheme.split("/", 1)
        ws_path = "/" + path_part
        host, port_str = host_port.split(":", 1)
        ws_port = int(port_str)

        js_expr = f"""
        (() => {{
            const convId = {json.dumps(str(conv_id))};
            const projectId = {json.dumps(str(project_id or ""))};
            const targetPath = '/c/' + convId + (projectId ? '?section=' + projectId : '');

            const focusComposer = () => {{
                setTimeout(() => {{
                    const input = document.querySelector('[aria-label="Message input"], [contenteditable="true"][role="combobox"], [contenteditable="true"]');
                    if (input && typeof input.focus === 'function') {{
                        input.focus();
                    }}
                }}, 60);
            }};

            if (window.location.pathname === '/c/' + convId) {{
                focusComposer();
                return 'already_active';
            }}

            const existingLink = document.querySelector('a[href*="/c/' + convId + '"]');
            if (existingLink) {{
                existingLink.click();
                focusComposer();
                return 'clicked_dom_link';
            }}

            const rootEl = document.querySelector('[data-testid="conversation-list-sidebar"]') || document.querySelector('a[href^="/c/"]') || document.body.firstElementChild;
            if (rootEl) {{
                const fk = Object.keys(rootEl).find(k => k.startsWith('__reactFiber$'));
                if (fk) {{
                    let cur = rootEl[fk];
                    while (cur) {{
                        const mp = cur.memoizedProps;
                        if (mp && mp.value && mp.value.routesByPath && mp.value.history && typeof mp.value.history.push === 'function') {{
                            mp.value.history.push(targetPath);
                            focusComposer();
                            return 'router_history_push';
                        }}
                        cur = cur.return;
                    }}
                }}
            }}

            window.history.pushState({{}}, '', targetPath);
            window.dispatchEvent(new PopStateEvent('popstate'));
            focusComposer();
            return 'history_pushstate';
        }})()
        """

        sock = socket.create_connection((host, ws_port), timeout=0.6)
        try:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            handshake = (
                f"GET {ws_path} HTTP/1.1\r\n"
                f"Host: {host}:{ws_port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            )
            sock.sendall(handshake.encode("ascii"))
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = sock.recv(4096)
                if not chunk:
                    return False
                buf += chunk

            payload_bytes = json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {"expression": js_expr, "returnByValue": True},
                }
            ).encode("utf-8")
            mask_key = os.urandom(4)
            header = bytearray([0x81])
            length = len(payload_bytes)
            if length < 126:
                header.append(0x80 | length)
            elif length < 65536:
                header.append(0x80 | 126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(0x80 | 127)
                header.extend(struct.pack("!Q", length))
            header.extend(mask_key)
            masked = bytearray(payload_bytes[i] ^ mask_key[i % 4] for i in range(length))
            sock.sendall(header + masked)

            resp_data = sock.recv(8192)
            return bool(resp_data and b"result" in resp_data)
        finally:
            try:
                sock.close()
            except Exception:
                pass
    except Exception:
        return False


def navigate_to_antigravity_conversation(conv_id: str, title: Optional[str] = None) -> bool:
    """
    Navigate the Antigravity desktop window directly to a specific conversation by ID or title.
    Uses Antigravity's local DevTools router navigation first (supporting virtualized sidebars and
    collapsed project sections), falling back to macOS Accessibility (AXUIElement) without moving
    the user's mouse cursor.
    """
    if not conv_id:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True

    # Resolve conversation title and project_id from SQLite database
    project_id: Optional[str] = None
    if conv_id:
        try:
            import sqlite3
            from pathlib import Path

            db_path = Path.home() / ".gemini" / "antigravity" / "conversation_summaries.db"
            if db_path.is_file():
                with sqlite3.connect(str(db_path), timeout=0.5) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT title, project_id FROM conversation_summaries WHERE conversation_id = ? LIMIT 1",
                        (str(conv_id),),
                    )
                    row = cur.fetchone()
                    if row:
                        if not title and row[0]:
                            title = str(row[0])
                        if len(row) > 1 and row[1]:
                            project_id = str(row[1])
        except Exception:
            pass

    try:
        from AppKit import NSWorkspace
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
            AXUIElementSetAttributeValue,
            AXUIElementPerformAction,
            AXValueGetValue,
            kAXValueCGRectType,
        )
        import Quartz

        ws = NSWorkspace.sharedWorkspace()
        apps = [
            a
            for a in ws.runningApplications()
            if (a.localizedName() or "").strip() in ("Antigravity", "Antigravity IDE")
            or (a.bundleIdentifier() or "").lower() == "com.google.antigravity"
        ]
        if not apps:
            return False
        app = apps[0]
        cooperative_activate_app(app)
        time.sleep(0.06)

        # Primary deterministic navigation via Antigravity's local DevTools router
        if _navigate_antigravity_via_cdp(conv_id=str(conv_id), project_id=project_id):
            return True

        time.sleep(0.04)
        app_ax = AXUIElementCreateApplication(app.processIdentifier())
        AXUIElementSetAttributeValue(app_ax, "AXManualAccessibility", True)

        # In Chromium/Electron, AXWindows is often empty () while AXMainWindow/AXFocusedWindow exist
        win = None
        err, win = AXUIElementCopyAttributeValue(app_ax, "AXMainWindow", None)
        if not win or err != 0:
            err, win = AXUIElementCopyAttributeValue(app_ax, "AXFocusedWindow", None)
        if not win or err != 0:
            err, windows = AXUIElementCopyAttributeValue(app_ax, "AXWindows", None)
            if windows:
                win = windows[0]
        if not win:
            return focus_antigravity(focus_input=True)

        # Fast-path: check if target conversation is ALREADY open in the active window
        def _check_already_active(el, depth=0):
            if depth > 10:
                return False
            err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
            if role == "AXWebArea":
                err, url = AXUIElementCopyAttributeValue(el, "AXURL", None)
                url_str = str(url) if url else ""
                if conv_id and f"/c/{conv_id}" in url_str:
                    return True
            err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
            if children:
                for c in children:
                    if _check_already_active(c, depth + 1):
                        return True
            return False

        if _check_already_active(win):
            time.sleep(0.04)
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

        target_link = None
        clean_title = (title or "").strip().lower()

        def _find_link(el, depth=0):
            nonlocal target_link
            if target_link is not None or depth > 35:
                return
            err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
            if role == "AXLink":
                err, url = AXUIElementCopyAttributeValue(el, "AXURL", None)
                url_str = str(url) if url else ""
                if conv_id and f"/c/{conv_id}" in url_str:
                    target_link = el
                    return
                if clean_title:
                    err, desc = AXUIElementCopyAttributeValue(el, "AXDescription", None)
                    desc_str = str(desc).strip().lower() if desc else ""
                    if desc_str and (clean_title in desc_str or desc_str in clean_title):
                        target_link = el
                        return
            err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
            if children:
                for c in children:
                    _find_link(c, depth + 1)

        _find_link(win)

        # If not found and project_id is known, expand collapsed project section in sidebar and re-scan
        if not target_link and project_id:
            project_toggle_btn = None

            def _find_project_toggle(el, depth=0):
                nonlocal project_toggle_btn
                if project_toggle_btn is not None or depth > 30:
                    return
                err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
                if not children:
                    return
                has_proj_link = False
                cand_btn = None
                for c in children:
                    _, c_role = AXUIElementCopyAttributeValue(c, "AXRole", None)
                    if c_role == "AXLink":
                        _, c_url = AXUIElementCopyAttributeValue(c, "AXURL", None)
                        if c_url and f"section={project_id}" in str(c_url):
                            has_proj_link = True
                    elif c_role == "AXButton":
                        _, exp = AXUIElementCopyAttributeValue(c, "AXExpanded", None)
                        if exp is False:
                            cand_btn = c
                if has_proj_link and cand_btn is not None:
                    project_toggle_btn = cand_btn
                    return
                for c in children:
                    _find_project_toggle(c, depth + 1)

            _find_project_toggle(win)
            if project_toggle_btn is not None:
                AXUIElementPerformAction(project_toggle_btn, "AXPress")
                time.sleep(0.15)
                _find_link(win)

        if not target_link:
            return focus_antigravity(focus_input=True)

        # 1. Native AXPress action
        press_err = AXUIElementPerformAction(target_link, "AXPress")
        time.sleep(0.06)

        # 2. Resilient Quartz click fallback ONLY if AXPress failed
        if press_err != 0:
            err, frame_val = AXUIElementCopyAttributeValue(target_link, "AXFrame", None)
            if frame_val:
                success, rect = AXValueGetValue(frame_val, kAXValueCGRectType, None)
                if success and rect.size.width > 0:
                    center_x = rect.origin.x + rect.size.width / 2
                    center_y = rect.origin.y + (
                        rect.size.height / 2 if rect.size.height > 5 else 15.0
                    )
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

        # 3. Focus chat input with Cmd+L
        time.sleep(0.10)
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
        return focus_antigravity(focus_input=True)


def select_claude_conversation_window(
    conv_id: Optional[str] = None,
    title: Optional[str] = None,
) -> bool:
    """
    Focus Claude Code application window and select the active conversation thread.
    Supports both Claude Desktop (Claude.app) and CLI terminal emulators
    (Terminal.app, iTerm2, Ghostty, Warp, Cursor, Code).
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True

    # 1. Check for running Claude Desktop app
    try:
        from AppKit import NSWorkspace

        ws = NSWorkspace.sharedWorkspace()
        claude_apps = [
            a for a in ws.runningApplications() if (a.localizedName() or "").lower() == "claude"
        ]
        if claude_apps:
            claude_app = claude_apps[0]
            cooperative_activate_app(claude_app)
            time.sleep(0.10)

            # If conv_id is provided, resolve conversation title from session jsonl
            resolved_title = title
            if not resolved_title and conv_id:
                try:
                    import glob
                    import json
                    from pathlib import Path

                    clean_cid = conv_id.replace("claude_", "")
                    pattern = str(Path.home() / ".claude" / "projects" / "*" / f"{clean_cid}.jsonl")
                    matched_files = glob.glob(pattern)
                    if matched_files:
                        with open(matched_files[0], "r", encoding="utf-8") as fp:
                            for line in fp:
                                try:
                                    obj = json.loads(line.strip())
                                    if obj.get("type") == "custom-title" and obj.get("customTitle"):
                                        resolved_title = obj.get("customTitle")
                                        break
                                except Exception:
                                    continue
                except Exception:
                    pass

            # If we have a title, search Claude Desktop's AX tree for matching conversation button
            if resolved_title:
                try:
                    from ApplicationServices import (
                        AXUIElementCreateApplication,
                        AXUIElementSetAttributeValue,
                        AXUIElementCopyAttributeValue,
                        AXUIElementPerformAction,
                    )

                    app_ax = AXUIElementCreateApplication(claude_app.processIdentifier())
                    AXUIElementSetAttributeValue(app_ax, "AXManualAccessibility", True)
                    err, win = AXUIElementCopyAttributeValue(app_ax, "AXMainWindow", None)
                    if not win:
                        err, wins = AXUIElementCopyAttributeValue(app_ax, "AXWindows", None)
                        if wins:
                            win = wins[0]

                    target_btn = None
                    t_lower = resolved_title.strip().lower()

                    def _find_claude_btn(el, depth=0):
                        nonlocal target_btn
                        if target_btn is not None or depth > 30:
                            return
                        err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
                        if role in ("AXButton", "AXRow", "AXStaticText"):
                            for attr in ("AXTitle", "AXDescription", "AXValue"):
                                err, text_val = AXUIElementCopyAttributeValue(el, attr, None)
                                if text_val and t_lower in str(text_val).strip().lower():
                                    target_btn = el
                                    return
                        err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
                        if children:
                            for c in children:
                                _find_claude_btn(c, depth + 1)

                    if win:
                        _find_claude_btn(win)
                    if target_btn:
                        AXUIElementPerformAction(target_btn, "AXPress")
                        time.sleep(0.08)
                except Exception as e:
                    print(f"[Injector] Notice selecting Claude Desktop conversation: {e}")

            # Focus prompt textarea in Claude Desktop
            if _focus_and_click_claude_desktop():
                return True
            return True
    except Exception as e:
        print(f"[Injector] Notice checking Claude Desktop: {e}")

    # 2. Check for Claude CLI session in terminal
    focused_term = focus_terminal_app()
    if focused_term:
        return True

    return focus_app_by_name("Claude")


def select_codex_conversation_window(
    conv_id: Optional[str] = None,
    title: Optional[str] = None,
) -> bool:
    """
    Focus Codex application window and select the active thread or conversation.
    Supports ChatGPT macOS desktop app and terminal emulators.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True

    # 1. Check for ChatGPT desktop app
    try:
        from AppKit import NSWorkspace

        ws = NSWorkspace.sharedWorkspace()
        chatgpt_apps = [
            a
            for a in ws.runningApplications()
            if (a.localizedName() or "").lower() in ("chatgpt", "chatgpt.app")
            or (a.bundleIdentifier() or "").lower() in ("com.openai.chat", "com.openai.chatgpt")
        ]
        if chatgpt_apps:
            app = chatgpt_apps[0]
            cooperative_activate_app(app)
            time.sleep(0.10)

            # If conv_id or title is known, search AX tree to select conversation thread
            if conv_id or title:
                try:
                    from ApplicationServices import (
                        AXUIElementCreateApplication,
                        AXUIElementSetAttributeValue,
                        AXUIElementCopyAttributeValue,
                        AXUIElementPerformAction,
                    )

                    app_ax = AXUIElementCreateApplication(app.processIdentifier())
                    AXUIElementSetAttributeValue(app_ax, "AXManualAccessibility", True)
                    err, win = AXUIElementCopyAttributeValue(app_ax, "AXMainWindow", None)
                    if not win:
                        err, wins = AXUIElementCopyAttributeValue(app_ax, "AXWindows", None)
                        if wins:
                            win = wins[0]

                    target_btn = None
                    search_term = (title or conv_id or "").strip().lower()

                    def _find_chatgpt_thread(el, depth=0):
                        nonlocal target_btn
                        if target_btn is not None or depth > 30:
                            return
                        err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
                        if role in ("AXButton", "AXRow", "AXStaticText", "AXLink"):
                            for attr in ("AXTitle", "AXDescription", "AXValue"):
                                err, val = AXUIElementCopyAttributeValue(el, attr, None)
                                if val and search_term in str(val).strip().lower():
                                    target_btn = el
                                    return
                        err, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
                        if children:
                            for c in children:
                                _find_chatgpt_thread(c, depth + 1)

                    if win and search_term:
                        _find_chatgpt_thread(win)
                    if target_btn:
                        AXUIElementPerformAction(target_btn, "AXPress")
                        time.sleep(0.08)
                except Exception:
                    pass

            return focus_chatgpt(focus_input=True)
    except Exception as e:
        print(f"[Injector] Notice checking ChatGPT desktop: {e}")

    # 2. Fall back to terminal if running CLI
    focused_term = focus_terminal_app()
    if focused_term:
        return True

    return focus_app_by_name("ChatGPT")


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
        r"(?i)[,\s]*(?:transcribe\s+done|stop\s+transcrib(?:ing|e)|done\s+transcribing|stop\s+dictat(?:ing|e)|that(?:\'s|\s+is)\s+all|i(?:\'m|\s+am)\s+done(?:\s+talking)?|stop\s+listening|over(?:\s+and\s+out)?)[.!?\s]*$",
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


_LAST_AGENTAPI_TEXT = ""
_LAST_AGENTAPI_TIME = 0.0
_LAST_AGENTAPI_TARGET_ID = ""


def send_message_to_antigravity(
    conv_id: Optional[str] = None,
    text: str = "",
    sender_name: Optional[str] = None,
    title: Optional[str] = None,
    from_conv_id: Optional[str] = None,
    allow_foreground_fallback: bool = False,
    force: bool = False,
) -> DispatchResult:
    """
    Send prompt directly to Antigravity conversation via native agentapi IPC.
    This delivers the message cleanly in the background with 0 window focus changes,
    0 clipboard usage, and 0 screen flashing.
    Supports setting custom message titles, sender attribution, and return-routing.
    """
    global _LAST_AGENTAPI_TEXT, _LAST_AGENTAPI_TIME, _LAST_AGENTAPI_TARGET_ID
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

    # Short-window prompt deduplication to prevent double-injection from dual mics (phone + Mac) or relay retries
    now = time.time()
    min_window = 3.0 if len(clean_text) <= 15 or len(clean_text.split()) <= 2 else 15.0
    if not force and not os.environ.get("VOICEFI_DISABLE_DEDUP"):
        if (
            clean_text == _LAST_AGENTAPI_TEXT
            and str(target_id) == str(_LAST_AGENTAPI_TARGET_ID)
            and (now - _LAST_AGENTAPI_TIME) < min_window
            and (not os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("VOICEFI_TEST_DEDUP"))
        ):
            print(
                f"[Injector] ⏭️ Ignored duplicate message to Antigravity ({str(target_id)[:8]}) within {min_window:.1f}s window: '{clean_text[:40]}'"
            )
            return DispatchResult(
                success=True,
                delivery_type="deduplicated",
                target_conv_id=target_id,
                engine="antigravity",
            )

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
            _LAST_AGENTAPI_TEXT = clean_text
            _LAST_AGENTAPI_TIME = now
            _LAST_AGENTAPI_TARGET_ID = str(target_id)
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
                _LAST_AGENTAPI_TEXT = clean_text
                _LAST_AGENTAPI_TIME = now
                _LAST_AGENTAPI_TARGET_ID = str(target_id)
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
        if any(
            token in last_stderr
            for token in ("outside-of-project", "PermissionDenied", "permission_denied")
        ):
            from voicefi.integrations.conversations import get_latest_antigravity_conversation_id

            latest_id = get_latest_antigravity_conversation_id()
            if latest_id and str(latest_id) != str(target_id):
                print(
                    f"[Injector] 🔄 Rescuing turn with active workspace conversation: {str(latest_id)[:8]}"
                )
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
                    _LAST_AGENTAPI_TEXT = clean_text
                    _LAST_AGENTAPI_TIME = now
                    _LAST_AGENTAPI_TARGET_ID = str(latest_id)
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
        try:
            from voicefi.telemetry import capture_exception

            capture_exception(
                e,
                properties={
                    "component": "injector.agentapi",
                    "target_conv_id": str(target_id)[:16] if target_id else "unknown",
                    "$exception_fingerprint": ["injector.agentapi", type(e).__name__],
                },
            )
        except Exception:
            pass

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
    if last_stderr and not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            from voicefi.telemetry import capture_exception

            capture_exception(
                RuntimeError(f"agentapi IPC delivery failed: {last_stderr[:100]}"),
                properties={
                    "component": "injector.agentapi",
                    "target_conv_id": str(target_id)[:16] if target_id else "unknown",
                    "$exception_fingerprint": ["injector.agentapi", "delivery_failed"],
                },
            )
        except Exception:
            pass

    return DispatchResult(
        success=False,
        delivery_type="none",
        error=f"agentapi IPC delivery failed: {last_stderr}",
        target_conv_id=target_id,
        engine="antigravity",
    )


def _click_antigravity_new_conversation_in_project(project_name: str) -> bool:
    """
    Locate the matching project in Antigravity's sidebar ('Projects' section) and press
    its 'New Conversation in Project' AXLink so the new conversation opens in that exact project.
    """
    if not project_name or os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    target_names = [project_name.strip().lower()]
    if target_names[0] in ("vifi.co", "voicefi.org"):
        target_names.append("voicefi")

    try:
        from AppKit import NSWorkspace
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            AXUIElementPerformAction,
            AXUIElementSetAttributeValue,
        )

        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            app_name = (app.localizedName() or "").lower()
            bundle_id = (app.bundleIdentifier() or "").lower()
            if app_name not in ("antigravity", "antigravity ide") and bundle_id != "com.google.antigravity":
                continue

            ax = AXUIElementCreateApplication(app.processIdentifier())
            AXUIElementSetAttributeValue(ax, "AXManualAccessibility", True)
            _, wins = AXUIElementCopyAttributeValue(ax, "AXWindows", None)
            if not wins:
                continue

            found_link = None

            def _walk(el, depth=0):
                nonlocal found_link
                if found_link is not None or depth > 28:
                    return
                _, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
                _, children = AXUIElementCopyAttributeValue(el, "AXChildren", None)
                if role == "AXGroup" and children and len(children) >= 2:
                    _, c0_role = AXUIElementCopyAttributeValue(children[0], "AXRole", None)
                    _, c0_title = AXUIElementCopyAttributeValue(children[0], "AXTitle", None)
                    if c0_role == "AXButton" and c0_title:
                        btn_name = str(c0_title).strip().lower()
                        if btn_name in target_names:
                            _, g_children = AXUIElementCopyAttributeValue(
                                children[1], "AXChildren", None
                            )
                            for gc in g_children or []:
                                _, gc_role = AXUIElementCopyAttributeValue(gc, "AXRole", None)
                                _, gc_title = AXUIElementCopyAttributeValue(gc, "AXTitle", None)
                                _, gc_desc = AXUIElementCopyAttributeValue(
                                    gc, "AXDescription", None
                                )
                                lbl = str(gc_title or gc_desc or "").lower()
                                if gc_role == "AXLink" and (
                                    "new conversation" in lbl or not lbl
                                ):
                                    found_link = gc
                                    return
                for c in children or []:
                    _walk(c, depth + 1)

            _walk(wins[0])
            if found_link is not None:
                AXUIElementPerformAction(found_link, "AXPress")
                print(
                    f"[Injector] 🎯 Pressed 'New Conversation in Project' AXLink for project '{project_name}'"
                )
                return True
    except Exception as e:
        print(f"[Injector] Notice pressing project new-conversation link: {e}")
    return False


def create_new_antigravity_conversation(
    prompt: str = "Hello",
    title: Optional[str] = None,
    model: Optional[str] = None,
    workspace_path: Optional[str] = None,
    focus_window: bool = False,
    restore_focus: bool = True,
) -> Optional[str]:
    """
    Start a brand new Antigravity agent conversation and deliver the prompt.
    Delivers cleanly via native agentapi IPC without adjusting screen focus or
    stealing active window attention unless focus_window=True.
    Returns the newly created conversation ID if detected, or None.
    """
    clean_prompt = (prompt or "Hello").strip()
    resolved_ws: Optional[str] = None
    proj_name: Optional[str] = None

    if not workspace_path:
        try:
            from voicefi.integrations.conversations import load_session_cookie
            cookie = load_session_cookie() or {}
            if cookie.get("workspacePath") and Path(cookie["workspacePath"]).is_dir():
                workspace_path = cookie["workspacePath"]
            elif Path.cwd().is_dir() and (Path.cwd() / ".git").exists():
                workspace_path = str(Path.cwd())
        except Exception:
            pass

    if workspace_path and Path(str(workspace_path)).expanduser().is_dir():
        resolved_ws = str(Path(str(workspace_path)).expanduser().resolve())
        proj_name = Path(resolved_ws).name
        if not title:
            title = f"{proj_name}: {(prompt or 'New Conversation').strip()[:32]}"

    brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
    existing_cids = set()
    if brain_dir.is_dir():
        try:
            existing_cids = {d.name for d in brain_dir.iterdir() if d.is_dir()}
        except Exception:
            existing_cids = set()

    agentapi_bin = Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi"

    # 1. Native agentapi IPC (Fast, headless, zero screen focus adjustment, zero clipboard pollution)
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
                cwd=resolved_ws if resolved_ws else None,
                text=True,
                timeout=8,
            )
            if res.returncode == 0:
                print(
                    f"[Injector] 🚀 Created new Antigravity conversation via agentapi IPC: {res.stdout.strip()}"
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

                        save_session_cookie(
                            conv_id=str(cid),
                            title=title or clean_prompt[:40],
                            workspace_path=resolved_ws,
                        )
                        if focus_window:
                            focus_antigravity(focus_input=True)
                        return str(cid)
                except Exception:
                    pass
        except Exception as e:
            print(f"[Injector] agentapi new-conversation notice: {e}")

    # 2. GUI injection fallback (if agentapi was not available or failed)
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
            clicked_project_link = False
            if proj_name:
                clicked_project_link = _click_antigravity_new_conversation_in_project(proj_name)
                if clicked_project_link:
                    time.sleep(0.35)
            gui_injected = inject_text_to_antigravity(
                clean_prompt,
                submit_enter=True,
                restore_focus=restore_focus if not focus_window else False,
                new_conversation=not clicked_project_link,
            )
    except Exception as e:
        print(f"[Injector] Notice checking Antigravity GUI fallback: {e}")

    # If GUI injection ran, wait for the newly created brain/<conv_id> directory and return it!
    if gui_injected and not os.environ.get("PYTEST_CURRENT_TEST"):
        from voicefi.integrations.conversations import ConversationTracker, save_session_cookie

        for _ in range(10):
            time.sleep(0.25)
            try:
                if brain_dir.is_dir():
                    new_dirs = [
                        d
                        for d in brain_dir.iterdir()
                        if d.is_dir()
                        and d.name not in existing_cids
                        and (d / ".system_generated" / "logs" / "transcript.jsonl").is_file()
                    ]
                    if new_dirs:
                        new_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
                        new_cid = new_dirs[0].name
                        save_session_cookie(
                            conv_id=new_cid,
                            title=title or clean_prompt[:40],
                            workspace_path=resolved_ws,
                        )
                        if focus_window:
                            focus_antigravity(focus_input=True)
                        return new_cid
            except Exception:
                pass

    # 3. Last-resort fallback to GUI injection if neither agentapi nor project click ran
    if not gui_injected and not os.environ.get("PYTEST_CURRENT_TEST"):
        inject_text_to_antigravity(
            clean_prompt,
            submit_enter=True,
            restore_focus=restore_focus if not focus_window else False,
            new_conversation=True,
        )

    time.sleep(0.5)
    try:
        from voicefi.integrations.conversations import ConversationTracker, save_session_cookie

        active = ConversationTracker().get_active_or_latest()
        if active:
            save_session_cookie(
                conv_id=active.id,
                title=title or clean_prompt[:40],
                workspace_path=resolved_ws,
            )
            return active.id
    except Exception:
        pass
    return None


def focus_terminal_app() -> Optional[str]:
    """Find and focus the running terminal, coding editor, or Claude app."""
    term_priority = [
        "claude",
        "ghostty",
        "iterm2",
        "iterm",
        "warp",
        "cursor",
        "code",
        "visual studio code",
        "windsurf",
        "alacritty",
        "kitty",
        "wezterm",
        "terminal",
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
                if cooperative_activate_app(app):
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
        cooperative_activate_app(claude_app)
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

    restore_snippet = (
        """
        if prevApp is not "" and prevApp is not targetApp then
            delay 0.08
            try
                tell application prevApp to activate
            end try
        end if
        """
        if restore_focus
        else ""
    )

    # Step 2: Bring Claude / Terminal to front and paste
    applescript = f"""
    tell application "System Events"
        set prevApp to ""
        try
            set prevApp to name of first application process whose frontmost is true
        end try
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
            {restore_snippet}
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
        try:
            from voicefi.telemetry import capture_exception

            capture_exception(
                e,
                properties={
                    "component": "injector.claude",
                    "$exception_fingerprint": ["injector.claude", type(e).__name__],
                },
            )
        except Exception:
            pass
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
                if cooperative_activate_app(app):
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

    restore_snippet = (
        """
        if prevApp is not "" and prevApp is not "ChatGPT" then
            delay 0.08
            try
                tell application prevApp to activate
            end try
        end if
        """
        if restore_focus
        else ""
    )

    applescript = f"""
    tell application "System Events"
        set prevApp to ""
        try
            set prevApp to name of first application process whose frontmost is true
        end try
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
            {restore_snippet}
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
        try:
            from voicefi.telemetry import capture_exception

            capture_exception(
                e,
                properties={
                    "component": "injector.chatgpt",
                    "$exception_fingerprint": ["injector.chatgpt", type(e).__name__],
                },
            )
        except Exception:
            pass
        if preserve_clipboard and prev_clipboard is not None:
            restore_clipboard_delayed(prev_clipboard, delay=0.4)
        return False


def focus_gemini(focus_input: bool = True) -> bool:
    """
    Bring Gemini macOS desktop application to the front.
    Uses native AppKit NSWorkspace fast-path to prevent AppleScript timeouts when not running.
    """
    try:
        from AppKit import NSWorkspace

        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            loc = (app.localizedName() or "").lower()
            bundle = (app.bundleIdentifier() or "").lower()
            if "gemini" in loc or bundle == "com.google.geminimacos":
                if cooperative_activate_app(app):
                    return True
    except Exception:
        pass

    applescript = """
    tell application "System Events"
        if exists (process "Gemini") then
            tell application "Gemini" to activate
            delay 0.08
            tell process "Gemini"
                set frontmost to true
                if count of windows is 0 then
                    try
                        click menu item "New Chat" of menu "File" of menu bar item "File" of menu bar 1
                    end try
                end if
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


def inject_text_to_gemini(
    text: str,
    submit_enter: bool = True,
    restore_focus: bool = False,
    preserve_clipboard: bool = True,
) -> bool:
    """
    Inject transcribed voice prompt or message into Gemini for Mac desktop app.
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

    restore_snippet = (
        """
        if prevApp is not "" and prevApp is not "Gemini" then
            delay 0.08
            try
                tell application prevApp to activate
            end try
        end if
        """
        if restore_focus
        else ""
    )

    applescript = f"""
    tell application "System Events"
        set prevApp to ""
        try
            set prevApp to name of first application process whose frontmost is true
        end try
        tell application "Gemini" to activate
        delay 0.18
        if exists (process "Gemini") then
            tell process "Gemini"
                set frontmost to true
                if count of windows is 0 then
                    try
                        click menu item "New Chat" of menu "File" of menu bar item "File" of menu bar 1
                        delay 0.15
                    end try
                end if
                try
                    click menu item "Paste" of menu "Edit" of menu bar item "Edit" of menu bar 1
                on error
                    keystroke "v" using command down
                end try
                {enter_script}
            end tell
            {restore_snippet}
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
        print(f"[Injector] inject_text_to_gemini error: {e}")
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

    # 1. If conversation ID is explicitly a Claude or Codex session
    if conv_id and (conv_id.startswith("claude_") or "claude" in conv_id.lower()):
        engine = "claude"
    elif conv_id and (conv_id.startswith("codex_") or "codex" in conv_id.lower()):
        engine = "codex"
    elif conv_id and (
        conv_id.startswith("chatgpt_")
        or "chatgpt" in conv_id.lower()
        or "openai" in conv_id.lower()
    ):
        engine = "chatgpt"

    # 2. Resilient spoken intent detection for Claude and Codex
    explicit_claude = bool(
        re.search(
            r"\b(?:hey|ask|tell|all\s+right|alright|okay|so|can\s+you\s+ask|could\s+you\s+ask|send\s+to|talk\s+to|switch\s+to|have|message)?\s*claude\b",
            cleaned_lower,
        )
    )
    explicit_codex = bool(
        re.search(
            r"\b(?:hey|ask|tell|all\s+right|alright|okay|so|can\s+you\s+ask|could\s+you\s+ask|send\s+to|talk\s+to|switch\s+to|have|message)?\s*codex\b",
            cleaned_lower,
        )
    )
    if not engine:
        if explicit_codex:
            engine = "codex"
        elif explicit_claude:
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

    if not kwargs.get("_is_replay") and (
        not os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("VIFI_HISTORY_PATH")
    ):
        try:
            from voicefi.ipc.history import record_utterance_history

            record_utterance_history(
                transcript=text.strip(),
                target_route=engine,
                audio_duration=float(kwargs.get("audio_duration", 0.0) or 0.0),
                session_id=conv_id,
                source=sender_name or "dispatcher",
                deduplicate_window=2.0,
            )
        except Exception:
            pass

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
    elif engine == "codex":
        from voicefi.config import load_config

        cfg = load_config()
        codex_cfg = getattr(cfg, "codex", None)
        mode = getattr(codex_cfg, "dispatch_mode", "auto")

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
            run_headless = bool(
                is_mobile
                or (conv_id and conv_id.startswith("codex_"))
                or target_engine == "codex"
                or explicit_codex
            )

        resolved_from = from_conv_id
        if not resolved_from and include_envelope:
            from voicefi.integrations.conversations import get_latest_antigravity_conversation_id

            resolved_from = get_latest_antigravity_conversation_id()

        from voicefi.integrations.codex import get_codex_cli_path, execute_codex_cli

        cli_path = get_codex_cli_path()
        if run_headless and cli_path:
            turn_origin = "mobile" if is_mobile else "desktop"
            return execute_codex_cli(
                prompt=text,
                conv_id=conv_id,
                cwd=cwd,
                origin=turn_origin,
                async_execution=True,
                from_conv_id=resolved_from,
                from_engine=from_engine or "antigravity",
                include_envelope=include_envelope,
            )

        print(f'[Injector] 🤖 Injecting prompt into ChatGPT / Codex Desktop: "{text[:50]}..."')
        pasted = inject_text_to_chatgpt(text, submit_enter=True)
        return DispatchResult(
            success=pasted,
            delivery_type="foreground_paste" if pasted else "none",
            error=None if pasted else "Failed to inject prompt into ChatGPT for Mac",
            engine="codex",
        )
    elif engine in ("chatgpt", "openai"):
        print(f'[Injector] 🤖 Injecting prompt into ChatGPT Desktop: "{text[:50]}..."')
        pasted = inject_text_to_chatgpt(text, submit_enter=True)
        return DispatchResult(
            success=pasted,
            delivery_type="foreground_paste" if pasted else "none",
            error=None if pasted else "Failed to inject prompt into ChatGPT for Mac",
            engine=engine,
        )
    elif engine in ("gemini", "gemini_app", "gemini_desktop"):
        print(f'[Injector] ✨ Injecting prompt into Gemini Desktop: "{text[:50]}..."')
        pasted = inject_text_to_gemini(text, submit_enter=True)
        return DispatchResult(
            success=pasted,
            delivery_type="foreground_paste" if pasted else "none",
            error=None if pasted else "Failed to inject prompt into Gemini for Mac",
            engine=engine,
        )
    elif engine == "gemini_cli":
        print(f'[Injector] 🚀 Dispatching prompt to Gemini CLI agent: "{text[:50]}..."')
        extra_kwargs = {"force": kwargs["force"]} if "force" in kwargs else {}
        return send_message_to_antigravity(
            conv_id=conv_id,
            text=text,
            sender_name=sender_name or "Gemini",
            title=title,
            from_conv_id=from_conv_id,
            allow_foreground_fallback=allow_foreground_fallback,
            **extra_kwargs,
        )
    else:
        extra_kwargs = {"force": kwargs["force"]} if "force" in kwargs else {}
        return send_message_to_antigravity(
            conv_id=conv_id,
            text=text,
            sender_name=sender_name,
            title=title,
            from_conv_id=from_conv_id,
            allow_foreground_fallback=allow_foreground_fallback,
            **extra_kwargs,
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
                return cooperative_activate_app(app)
    except Exception:
        pass

    # 2. Fallback to AppleScript
    safe_target = (
        target.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\x00", "")
    )
    applescript = f'''
    tell application "System Events"
        if exists (process "{safe_target}") then
            tell application "{safe_target}" to activate
            return true
        end if
    end tell
    try
        tell application "{safe_target}" to activate
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
    Invoked when pressing Option+Tab while an AI agent is speaking aloud (or recently spoke).
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
                or get_recent_speaking_info(window_seconds=120.0)
                or get_cross_process_hud_state()
            )
            if info and isinstance(info, dict):
                agent_name = agent_name or info.get("agent_name")
                app_name = app_name or info.get("app_name")
                conv_id = conv_id or info.get("conv_id")
        except Exception:
            pass

        # If still not resolved and not in pytest, check active session cookie / tracker
        if not agent_name and not app_name and not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                from voicefi.integrations.conversations import (
                    load_session_cookie,
                    ConversationTracker,
                )

                cookie = load_session_cookie()
                if cookie:
                    conv_id = conv_id or cookie.get("conv_id") or cookie.get("conversationId")
                    eng = (cookie.get("engine") or "").lower()
                    if eng == "claude":
                        app_name = "Claude"
                    elif eng in ("codex", "chatgpt"):
                        app_name = "ChatGPT"
                    else:
                        app_name = "Antigravity"
                if not conv_id:
                    latest_info = ConversationTracker().get_active_or_latest()
                    if latest_info and latest_info.id:
                        conv_id = latest_info.id
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
        print(
            f"[Injector] 🎯 Option+Tab / HUD Click: Focusing Claude window (conv: {conv_id or 'active'})..."
        )
        if conv_id and select_claude_conversation_window(conv_id=conv_id):
            return True
        if focus_terminal_app():
            return True
        if _focus_and_click_claude_desktop():
            return True
        return focus_app_by_name("Claude")

    # 2b. ChatGPT Desktop / Codex
    if (
        "chatgpt" in agent_lower
        or "openai" in agent_lower
        or "chatgpt" in app_lower
        or "codex" in agent_lower
        or "codex" in app_lower
    ):
        print(
            f"[Injector] 🎯 Option+Tab / HUD Click: Focusing Codex / ChatGPT window (conv: {conv_id or 'active'})..."
        )
        if conv_id and select_codex_conversation_window(conv_id=conv_id):
            return True
        return focus_chatgpt(focus_input=True)

    # 2c. Specific app name provided (e.g. Ghostty, Cursor, Code, Terminal, Warp, Obsidian, etc.)
    _non_standalone_apps = {
        "antigravity",
        "antigravity ide",
        "voicefi",
        "viv",
        "agent",
        "main",
        "gemini",
        "the continental",
        "the_continental",
        "sonia",
        "christopher",
        "stefan",
        "emma",
        "andrew",
        "ava",
        "guy",
        "fenrir",
        "attenborough",
        "documentary_broadcaster",
    }
    if app_name and app_lower not in _non_standalone_apps:
        print(f"[Injector] 🎯 Option+Tab / HUD Click: Focusing {app_name} window...")
        if focus_app_by_name(app_name):
            return True

    # 2d. Antigravity / Subagents / Default
    print(
        f"[Injector] 🎯 Option+Tab / HUD Click: Focusing Antigravity window (conv: {conv_id or 'active'}, agent: {agent_name or 'Antigravity'})..."
    )
    if conv_id:
        if navigate_to_antigravity_conversation(conv_id=conv_id):
            return True

    focused = focus_antigravity(focus_input=True)
    if not focused and app_name:
        focused = focus_app_by_name(app_name)
    if not focused:
        focused = bool(focus_terminal_app())
    return focused


class LiveAutotyper:
    """
    Real-time streaming autotyper for macOS.
    Incrementally types partial speech-to-text directly into the focused text field as the user speaks,
    reconciling word revisions with simulated backspaces and finishing cleanly on turn completion.
    """

    def __init__(self, enabled: bool = True, pure_forward: bool = True):
        self.enabled = enabled
        self.pure_forward = pure_forward
        self._typed_text: str = ""
        self._lock = threading.Lock()
        self._is_closed = False
        self._quartz_available: Optional[bool] = None

    def _check_quartz(self) -> bool:
        if self._quartz_available is None:
            try:
                import Quartz

                self._quartz_available = hasattr(Quartz, "CGEventCreateKeyboardEvent")
            except Exception:
                self._quartz_available = False
        return bool(self._quartz_available)

    @property
    def has_typed(self) -> bool:
        with self._lock:
            return bool(self._typed_text)

    @property
    def typed_text(self) -> str:
        with self._lock:
            return self._typed_text

    @staticmethod
    def _find_new_forward_words(typed_words: List[str], new_words: List[str]) -> List[str]:
        """
        Find words in new_words that extend beyond already typed words.
        Guarantees strictly forward progress with zero backspaces.
        """
        def _norm(w: str) -> str:
            return re.sub(r"[^\w]", "", w).lower()

        t_norm = [_norm(w) for w in typed_words if _norm(w)]
        n_norm = [_norm(w) for w in new_words if _norm(w)]

        if not t_norm:
            return new_words

        # 1. Direct prefix match: new_norm starts with t_norm
        if len(n_norm) >= len(t_norm) and n_norm[:len(t_norm)] == t_norm:
            return new_words[len(t_norm):]

        # 2. Look for the longest suffix of t_norm that appears in n_norm
        for k in range(len(t_norm), 0, -1):
            target_sub = t_norm[-k:]
            sub_len = len(target_sub)
            for i in range(len(n_norm) - sub_len, -1, -1):
                if n_norm[i:i + sub_len] == target_sub:
                    return new_words[i + sub_len:]

        # 3. Fallback: if new_words has strictly more words than typed_words, take the tail
        if len(new_words) > len(typed_words):
            return new_words[len(typed_words):]

        return []

    def update(self, new_text: str) -> None:
        """Process incremental partial transcript and type delta into focused text field."""
        if not self.enabled or self._is_closed or not new_text or not new_text.strip():
            return
        if not self._check_quartz():
            return

        with self._lock:
            if self._is_closed:
                return
            # Hold back trailing mid-syllable hyphenated fragments (e.g. "Google ant-") until word completes
            trimmed = re.sub(r"(?:^|\s+)\S+-[\. …]*$", "", new_text.strip()).strip()
            # Strip trailing ellipses and punctuation jitter from partial transcripts
            clean = re.sub(r"[\. …]+$", "", trimmed).strip()
            if not clean or clean == self._typed_text:
                return

            if self.pure_forward:
                typed_words = self._typed_text.split()
                new_words = clean.split()
                words_to_add = self._find_new_forward_words(typed_words, new_words)
                if words_to_add:
                    suffix = (" " if self._typed_text else "") + " ".join(words_to_add)
                    self._send_text(suffix)
                    self._typed_text = (self._typed_text + suffix).strip()
                return

            def _normalize_word(w: str) -> str:
                return re.sub(r"[^\w]", "", w).lower()

            typed_words = self._typed_text.split()
            new_words = clean.split()

            typed_norm = [_normalize_word(w) for w in typed_words if _normalize_word(w)]
            new_norm = [_normalize_word(w) for w in new_words if _normalize_word(w)]

            # 1. Word-level pure forward extension (no backspacing at all!)
            if typed_norm and len(new_norm) >= len(typed_norm) and new_norm[:len(typed_norm)] == typed_norm:
                words_to_add = new_words[len(typed_norm):]
                if words_to_add:
                    suffix = (" " if self._typed_text else "") + " ".join(words_to_add)
                    self._send_text(suffix)
                    self._typed_text += suffix
                return

            # 2. Word-level last-word revision (only backspace the active tail word)
            if len(typed_norm) > 1 and len(new_norm) >= len(typed_norm) and new_norm[:len(typed_norm)-1] == typed_norm[:-1]:
                last_word_len = len(typed_words[-1])
                self._send_backspaces(last_word_len)
                replacement_words = new_words[len(typed_norm)-1:]
                replacement_str = " ".join(replacement_words)
                self._send_text(replacement_str)
                self._typed_text = " ".join(typed_words[:-1]) + " " + replacement_str
                return

            # 3. Fallback character-level common prefix for general edits
            common_len = 0
            min_len = min(len(self._typed_text), len(clean))
            while common_len < min_len and self._typed_text[common_len] == clean[common_len]:
                common_len += 1

            backspaces = len(self._typed_text) - common_len
            suffix = clean[common_len:]

            if backspaces > 0:
                self._send_backspaces(backspaces)

            if suffix:
                self._send_text(suffix)

            self._typed_text = clean

    def finish(self, final_text: str, submit_enter: bool = False) -> bool:
        """Reconcile final transcribed text with whatever was typed live, and optionally submit."""
        if not self.enabled or not self._check_quartz():
            return False

        with self._lock:
            self._is_closed = True
            clean = (final_text or "").strip()

            if self.pure_forward:
                if clean and not self._typed_text:
                    self._send_text(clean)
                    self._typed_text = clean
                elif clean and self._typed_text:
                    typed_words = self._typed_text.split()
                    new_words = clean.split()
                    words_to_add = self._find_new_forward_words(typed_words, new_words)
                    if words_to_add:
                        suffix = (" " if self._typed_text else "") + " ".join(words_to_add)
                        self._send_text(suffix)
                        self._typed_text = (self._typed_text + suffix).strip()
                    # Attach final sentence punctuation (. ? !) without rewinding
                    if clean and clean[-1] in ".?!" and not self._typed_text.endswith(clean[-1]):
                        self._send_text(clean[-1])
                        self._typed_text += clean[-1]
                if submit_enter:
                    self._send_return()
                return True

            if not clean and self._typed_text:
                self._send_backspaces(len(self._typed_text))
                self._typed_text = ""
            elif clean and not self._typed_text:
                self._send_text(clean)
                self._typed_text = clean
            elif clean and self._typed_text:
                def _normalize_word(w: str) -> str:
                    return re.sub(r"[^\w]", "", w).lower()

                typed_words = self._typed_text.split()
                new_words = clean.split()
                typed_norm = [_normalize_word(w) for w in typed_words if _normalize_word(w)]
                new_norm = [_normalize_word(w) for w in new_words if _normalize_word(w)]

                # If typed words are already a prefix of final words, forward-append remaining words
                if typed_norm and len(new_norm) >= len(typed_norm) and new_norm[:len(typed_norm)] == typed_norm:
                    words_to_add = new_words[len(typed_norm):]
                    if words_to_add:
                        suffix = " " + " ".join(words_to_add)
                        self._send_text(suffix)
                        self._typed_text += suffix
                    # Attach final sentence punctuation (. ? !) without rewinding
                    if clean and clean[-1] in ".?!" and not self._typed_text.endswith(clean[-1]):
                        self._send_text(clean[-1])
                        self._typed_text += clean[-1]
                else:
                    common_len = 0
                    min_len = min(len(self._typed_text), len(clean))
                    while common_len < min_len and self._typed_text[common_len] == clean[common_len]:
                        common_len += 1

                    backspaces = len(self._typed_text) - common_len
                    suffix = clean[common_len:]

                    if backspaces > 0:
                        self._send_backspaces(backspaces)
                    if suffix:
                        self._send_text(suffix)
                    self._typed_text = clean

            if submit_enter:
                self._send_return()

            return True

    def cancel(self) -> None:
        """Erase any live-typed text if the session was cancelled by user."""
        if not self._check_quartz():
            return
        with self._lock:
            self._is_closed = True
            if self._typed_text:
                self._send_backspaces(len(self._typed_text))
                self._typed_text = ""

    def close(self) -> None:
        with self._lock:
            self._is_closed = True

    @staticmethod
    def _send_backspaces(count: int) -> None:
        """Emit simulated macOS virtual Backspace (0x33 / 51) key events to login session."""
        try:
            import Quartz

            for _ in range(count):
                down = Quartz.CGEventCreateKeyboardEvent(None, 51, True)
                Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)
                up = Quartz.CGEventCreateKeyboardEvent(None, 51, False)
                Quartz.CGEventPost(Quartz.kCGSessionEventTap, up)
                time.sleep(0.002)
        except Exception as e:
            print(f"[LiveAutotyper] Backspace error: {e}", flush=True)

    @staticmethod
    def _send_text(text: str) -> None:
        """Emit simulated macOS Quartz unicode keystrokes to login session."""
        try:
            import Quartz

            for char in text:
                if char == "\n":
                    down = Quartz.CGEventCreateKeyboardEvent(None, 36, True)
                    Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)
                    up = Quartz.CGEventCreateKeyboardEvent(None, 36, False)
                    Quartz.CGEventPost(Quartz.kCGSessionEventTap, up)
                else:
                    down = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
                    Quartz.CGEventKeyboardSetUnicodeString(down, len(char), char)
                    Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)
                    up = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
                    Quartz.CGEventKeyboardSetUnicodeString(up, len(char), char)
                    Quartz.CGEventPost(Quartz.kCGSessionEventTap, up)
                time.sleep(0.001)
        except Exception as e:
            print(f"[LiveAutotyper] Send text error: {e}", flush=True)

    @staticmethod
    def _send_return() -> None:
        """Emit simulated macOS Return (0x24 / 36) key event to login session."""
        try:
            import Quartz

            down = Quartz.CGEventCreateKeyboardEvent(None, 36, True)
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, down)
            up = Quartz.CGEventCreateKeyboardEvent(None, 36, False)
            Quartz.CGEventPost(Quartz.kCGSessionEventTap, up)
        except Exception as e:
            print(f"[LiveAutotyper] Return error: {e}", flush=True)
