"""
Extensible App Input-Targeting & Dictation Focus Registry for macOS.
Finds, elevates, and focuses active text/prompt boxes in target applications
before live streaming autotyping begins.
"""

import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple


@dataclass
class AppFocusTarget:
    """Configuration for focusing the input element of a specific application."""
    app_name: str
    bundle_id_pattern: Optional[str] = None
    aliases: Tuple[str, ...] = ()
    shortcut: Optional[str] = None  # e.g., "Cmd+L", "Cmd+T", "Cmd+N"
    custom_focus_fn: Optional[Callable[[], bool]] = None
    focus_delay_s: float = 0.06


class AppFocusRegistry:
    """
    Extensible registry of app-specific focus recipes.
    Handles 'transcribe in <app>' voice workflows and automatic input box discovery.
    """

    _REGISTRY: Dict[str, AppFocusTarget] = {}

    _WAKE_PREFIX_RE = re.compile(
        r"^(?:(?:hey|hi|ok|okay|yo)\s+)?(?:pal|paul|hal|cal|bell|pow|paypal|brok|brock|broc|brook|grok|viv|vifi|vi-fi|voicefi|wifi|sci-fi|hifi|claude|claud|clod|antigravity|anti-gravity|anti\s+gravity|hate\s+bath)\b[,:\s.!?\-]*",
        re.IGNORECASE,
    )
    _LEADING_FILLER_RE = re.compile(
        r"^(?:(?:uh+|um+|er+|ah+|eh+|hmm+|like|well|so|please|can\s+you|could\s+you|would\s+you|let\'?s)\b[,:\s.!?\-]*)+",
        re.IGNORECASE,
    )
    _TARGET_PREFIX_FILLER_RE = re.compile(
        r"^(?:[,:\s.!?\-]+|(?:uh+|um+|er+|ah+|eh+|hmm+|like|the|my|a|an)\b[,:\s.!?\-]*)+",
        re.IGNORECASE,
    )
    _POLITE_SUFFIX_RE = re.compile(
        r"^[,:\s.!?\-]*(?:please|now|right\s+now|for\s+me|thanks|thank\s+you)[,:\s.!?\-]*$",
        re.IGNORECASE,
    )

    @classmethod
    def strip_speech_fillers(cls, text: str) -> str:
        """Strip leading/trailing conversational speech fillers ('uh', 'um', 'like', 'please') and punctuation."""
        s = (text or "").strip(" \t\n\r.,!?:;\"'-")
        while True:
            prev = s
            s = cls._WAKE_PREFIX_RE.sub("", s).strip(" \t\n\r.,!?:;\"'-")
            s = cls._LEADING_FILLER_RE.sub("", s).strip(" \t\n\r.,!?:;\"'-")
            if s == prev:
                break
        return s

    @classmethod
    def _clean_target_candidate(cls, raw_target: str) -> str:
        """Clean speech fillers, articles, and trailing container nouns from an app target name."""
        s = (raw_target or "").strip(" \t\n\r.,!?:;\"'-")
        s = cls._TARGET_PREFIX_FILLER_RE.sub("", s).strip(" \t\n\r.,!?:;\"'-")
        s = re.sub(
            r"\s+(?:please|now|right\s+now|for\s+me|thanks|thank\s+you|window|tab|app|application)$",
            "",
            s,
            flags=re.IGNORECASE,
        ).strip(" \t\n\r.,!?:;\"'-")
        return s

    @classmethod
    def parse_transcribe_intent(
        cls, text: str, allow_bare_in_app: bool = False
    ) -> Tuple[bool, Optional[str], str]:
        """
        Parse spoken dictation/transcribe-in-app commands with resilience to wake words
        and vocal fillers (e.g., 'Hey Pal, uh, transcribe in, uh, LinkedIn.').

        Returns:
            (is_transcribe_intent, target_app, remainder_prompt)
        """
        if not text or not text.strip():
            return False, None, ""

        s = cls.strip_speech_fillers(text)
        if not s:
            return False, None, ""

        verb_type = None
        after_verb = ""

        # 1. Match explicit transcribe / dictate / talk now verbs
        m_trans = re.match(
            r"^(?:start\s+)?(?:transcrib(?:e|ing)|dictat(?:e|ing)|talk\s*now)\b[,:\s.!?\-]*(.*)$",
            s,
            re.IGNORECASE,
        )
        if m_trans:
            verb_type = "transcribe"
            after_verb = (m_trans.group(1) or "").strip()
        else:
            # 2. Match 'type in <app>' (only when followed by in/into/on/to + app target)
            m_type = re.match(
                r"^type\b[,:\s.!?\-]+(?=(?:(?:uh+|um+|er+|ah+|like)\b[,:\s.!?\-]*)*(?:in|into|on|to)\b)(.*)$",
                s,
                re.IGNORECASE,
            )
            if m_type:
                verb_type = "type_in"
                after_verb = (m_type.group(1) or "").strip()
            elif allow_bare_in_app:
                verb_type = "bare_in"
                after_verb = s

        if not verb_type:
            return False, None, text.strip()

        # Strip fillers before checking for 'in <app>'
        after_verb_clean = cls._LEADING_FILLER_RE.sub("", after_verb).strip(" \t\n\r.,!?:;\"'-")

        # Bare 'transcribe' / 'talk now' with no 'in <app>'
        if not after_verb_clean or cls._POLITE_SUFFIX_RE.match(after_verb_clean):
            if verb_type == "transcribe":
                return True, None, ""
            return False, None, text.strip()

        # Check for 'in / into / on / to <app>'
        m_in = re.match(
            r"^(?:in|into|on|to)\b(.*)$",
            after_verb_clean,
            re.IGNORECASE,
        )
        if not m_in:
            return False, None, text.strip()

        rest = cls._TARGET_PREFIX_FILLER_RE.sub("", m_in.group(1) or "").strip()
        if not rest:
            return (True, None, "") if verb_type == "transcribe" else (False, None, text.strip())

        rest_lower = rest.lower()

        # First check registered apps/aliases (longest key first so 'google chrome' matches before 'chrome')
        sorted_keys = sorted(cls._REGISTRY.keys(), key=len, reverse=True)
        for key in sorted_keys:
            m_key = re.match(r"^" + re.escape(key) + r"(?:\b|(?=\W)|$)(.*)$", rest_lower, re.IGNORECASE)
            if m_key:
                target_obj = cls._REGISTRY[key]
                raw_rem = rest[len(key) :].strip()
                # Strip optional trailing container words ('tab', 'window', 'app')
                raw_rem = re.sub(
                    r"^(?:\s+(?:tab|window|app|application)\b)+",
                    "",
                    raw_rem,
                    flags=re.IGNORECASE,
                ).strip(" \t\n\r.,!?:;\"'-")
                if cls._POLITE_SUFFIX_RE.match(raw_rem):
                    raw_rem = ""
                return True, target_obj.app_name, raw_rem

        # For 'type in ...', require a registered app/alias or explicit '.com' so 'type in the box' isn't misrouted
        if verb_type == "type_in" and ".com" not in rest_lower:
            return False, None, text.strip()

        # Dynamic app / website fallback (up to first punctuation or max 3 words)
        m_dyn = re.match(
            r"^([a-zA-Z0-9][a-zA-Z0-9._\-\s]{0,28}?)(?:[,.:;!?-]+(.*)|$)",
            rest,
        )
        if m_dyn:
            cand = cls._clean_target_candidate(m_dyn.group(1) or "")
            rem = (m_dyn.group(2) or "").strip(" \t\n\r.,!?:;\"'-")
            if cls._POLITE_SUFFIX_RE.match(rem):
                rem = ""
            if cand and len(cand.split()) <= 3:
                known = cls.get_target(cand)
                return True, (known.app_name if known else cand), rem

        return False, None, text.strip()

    @classmethod
    def strip_transcribe_command_prefix(
        cls, text: str, target_app: Optional[str] = None
    ) -> str:
        """
        Strip any leading 'Hey Pal, transcribe in <app>' or 'transcribe' meta-command prefix
        from live or final dictation transcripts so the command itself is never typed into the app.
        """
        if not text or not text.strip():
            return ""
        is_cmd, _, rem = cls.parse_transcribe_intent(text, allow_bare_in_app=bool(target_app))
        if is_cmd:
            return rem
        clean = re.sub(
            r"^(?:(?:hey|hi|ok|okay|yo)\s+(?:pal|brok|viv|vifi|voicefi)[,:\s.!?\-]*)?(?:(?:uh+|um+|er+|ah+)\b[,:\s.!?\-]*)*(?:transcribe|talk\s*now)(?:[,:\s.!?\-]+in\b[,:\s.!?\-]*(?:(?:uh+|um+|er+|ah+|the)\b[,:\s.!?\-]*)*[a-zA-Z0-9._\-]+)?[\s,.:;!?-]*",
            "",
            text.strip(),
            flags=re.IGNORECASE,
        ).strip()
        if target_app:
            t_esc = re.escape(target_app.strip())
            clean = re.sub(
                r"^(?:(?:in|into|on|to)\b[,:\s.!?\-]*)?(?:(?:uh+|um+|er+|ah+|the)\b[,:\s.!?\-]*)*"
                + t_esc
                + r"[\s,.:;!?-]*",
                "",
                clean,
                flags=re.IGNORECASE,
            ).strip()
        return clean

    @classmethod
    def register(cls, target: AppFocusTarget) -> None:
        """Register a new app focus target."""
        key = target.app_name.lower().strip()
        cls._REGISTRY[key] = target
        for alias in target.aliases:
            cls._REGISTRY[alias.lower().strip()] = target

    @classmethod
    def get_target(cls, app_or_alias: str) -> Optional[AppFocusTarget]:
        """Look up an AppFocusTarget by app name, localized name, or alias."""
        if not app_or_alias:
            return None
        clean = cls._clean_target_candidate(app_or_alias).lower().strip()
        clean = re.sub(r"\.app$", "", clean).strip()
        if not clean:
            return None
        # Direct match
        if clean in cls._REGISTRY:
            return cls._REGISTRY[clean]
        # Partial match
        for key, target in cls._REGISTRY.items():
            if key == clean or clean in key or key in clean:
                return target
        return None

    @classmethod
    def focus_app_input(cls, app_name_or_alias: Optional[str] = None) -> bool:
        """
        Elevate target application and focus its input/text area.
        If app_name_or_alias is None, targets the currently frontmost application.
        """
        target = None
        clean_query = cls._clean_target_candidate(app_name_or_alias) if app_name_or_alias else None
        if clean_query:
            target = cls.get_target(clean_query)
        else:
            front_name = cls.get_frontmost_app_name()
            if front_name:
                target = cls.get_target(front_name)

        # 1. Execute custom focus function if present
        if target and target.custom_focus_fn:
            try:
                return target.custom_focus_fn()
            except Exception as e:
                print(f"[AppFocusRegistry] Custom focus error for {target.app_name}: {e}")

        # 2. Use target shortcut if configured
        if target and target.shortcut:
            return cls._focus_with_shortcut(target.app_name, target.shortcut, target.focus_delay_s)

        # 3. Dynamic browser tab lookup: If requested target is not an installed app
        # (or user said 'transcribe in <website/service>'), check open browser tabs (Chrome & Safari).
        if clean_query:
            tab_focused = cls._focus_browser_tab(clean_query)
            if tab_focused:
                return True

        # 4. Default fallback for known frontmost app or standard activation
        if clean_query:
            return cls._activate_app(clean_query)

        return True

    @classmethod
    def _focus_browser_tab(cls, tab_query: str) -> bool:
        """
        Search open browser tabs across Google Chrome and Safari for a tab matching `tab_query`.
        If found, switches to that tab and brings the browser window to the front.
        """
        clean_query = tab_query.strip().lower()
        if not clean_query:
            return False

        escaped = clean_query.replace('"', '\\"')
        applescript = f'''
        set tabQuery to "{escaped}"
        set found to false
        try
            tell application "System Events"
                if exists process "Google Chrome" then
                    tell application "Google Chrome"
                        repeat with w in windows
                            set tIndex to 0
                            repeat with t in tabs of w
                                set tIndex to tIndex + 1
                                set tabUrl to (URL of t as string)
                                set tabTitle to (title of t as string)
                                if (tabUrl contains tabQuery) or (tabTitle contains tabQuery) then
                                    set active tab index of w to tIndex
                                    set index of w to 1
                                    activate
                                    set found to true
                                    exit repeat
                                end if
                            end repeat
                            if found then exit repeat
                        end repeat
                    end tell
                end if
            end tell
        end try
        if not found then
            try
                tell application "System Events"
                    if exists process "Safari" then
                        tell application "Safari"
                            repeat with w in windows
                                repeat with t in tabs of w
                                    set tabUrl to (URL of t as string)
                                    set tabTitle to (name of t as string)
                                    if (tabUrl contains tabQuery) or (tabTitle contains tabQuery) then
                                        set current tab of w to t
                                        set index of w to 1
                                        activate
                                        set found to true
                                        exit repeat
                                    end if
                                end repeat
                                if found then exit repeat
                            end repeat
                        end tell
                    end if
                end tell
            end try
        end if
        return found
        '''
        try:
            res = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True, timeout=2.0)
            return "true" in res.stdout.lower()
        except Exception as e:
            print(f"[AppFocusRegistry] Browser tab search error for '{tab_query}': {e}")
            return False

    @classmethod
    def get_frontmost_app_name(cls) -> str:
        """Return the localized name of the currently frontmost application."""
        try:
            from AppKit import NSWorkspace
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front and front.localizedName():
                return str(front.localizedName()).strip()
        except Exception:
            pass
        return ""

    @classmethod
    def _activate_app(cls, app_name: str) -> bool:
        """Activate app via NSWorkspace or AppleScript."""
        try:
            from AppKit import NSWorkspace
            ws = NSWorkspace.sharedWorkspace()
            for app in ws.runningApplications():
                loc = (app.localizedName() or "").lower()
                if loc == app_name.lower() or app_name.lower() in loc:
                    if hasattr(app, "activate"):
                        app.activate()
                        return True
                    elif hasattr(app, "activateWithOptions_"):
                        return bool(app.activateWithOptions_(3))
        except Exception:
            pass

        try:
            subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to activate'],
                capture_output=True,
                timeout=1.5,
            )
            return True
        except Exception:
            return False

    @classmethod
    def _focus_with_shortcut(cls, app_name: str, shortcut: str, delay_s: float = 0.06) -> bool:
        """Activate app and press shortcut (e.g. 'Cmd+L', 'Cmd+T', 'Cmd+N')."""
        cls._activate_app(app_name)
        time.sleep(delay_s)

        parts = [p.strip().lower() for p in shortcut.split("+")]
        key = parts[-1]
        modifiers = parts[:-1]

        mod_clauses = []
        if "cmd" in modifiers or "command" in modifiers:
            mod_clauses.append("command down")
        if "opt" in modifiers or "option" in modifiers or "alt" in modifiers:
            mod_clauses.append("option down")
        if "shift" in modifiers:
            mod_clauses.append("shift down")
        if "ctrl" in modifiers or "control" in modifiers:
            mod_clauses.append("control down")

        using_clause = f" using {{{', '.join(mod_clauses)}}}" if mod_clauses else ""
        applescript = f'''
        tell application "{app_name}" to activate
        delay {delay_s}
        tell application "System Events"
            keystroke "{key}"{using_clause}
        end tell
        '''
        try:
            res = subprocess.run(
                ["osascript", "-e", applescript],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            return res.returncode == 0
        except Exception as e:
            print(f"[AppFocusRegistry] Shortcut error for {app_name} ({shortcut}): {e}")
            return False


# --- Default Recipe Registrations ---

def _focus_antigravity() -> bool:
    from voicefi.integrations.injector import focus_antigravity
    return focus_antigravity(focus_input=True)

def _focus_claude() -> bool:
    from voicefi.integrations.injector import focus_chatgpt
    # In Claude Desktop or Claude CLI, activate and focus prompt
    AppFocusRegistry._activate_app("Claude")
    time.sleep(0.06)
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to keystroke "l" using command down'],
            capture_output=True,
            timeout=1.5,
        )
    except Exception:
        pass
    return True


AppFocusRegistry.register(
    AppFocusTarget(
        app_name="Antigravity",
        bundle_id_pattern=r"com\.google\.antigravity",
        aliases=("antigravity ide", "agy", "anti-gravity", "anti gravity"),
        custom_focus_fn=_focus_antigravity,
    )
)

AppFocusRegistry.register(
    AppFocusTarget(
        app_name="Claude",
        bundle_id_pattern=r"com\.anthropic\.claude",
        aliases=("claude code", "claude desktop"),
        shortcut="Cmd+L",
        custom_focus_fn=_focus_claude,
    )
)

def _focus_chrome() -> bool:
    """
    Focus Google Chrome and elevate the active tab's input area.
    Keeps whatever tab is currently active in Chrome without forcing a tab switch.
    """
    AppFocusRegistry._activate_app("Google Chrome")
    time.sleep(0.06)

    # If the active tab already has an active or focusable input/textarea/editor,
    # ensure it retains focus. If not focused, click the active web body or press Tab to focus.
    click_active_script = '''
    tell application "System Events"
        tell process "Google Chrome"
            try
                set foc to (get value of attribute "AXFocusedUIElement")
                if foc is not missing value then
                    set r to role of foc
                    if r is "AXTextField" or r is "AXTextArea" or r is "AXWebArea" then
                        return true
                    end if
                end if
            end try
        end tell
    end tell
    return false
    '''
    try:
        res = subprocess.run(["osascript", "-e", click_active_script], capture_output=True, text=True, timeout=1.5)
        if "true" in res.stdout.lower():
            return True
    except Exception:
        pass
    return True


def _focus_linkedin() -> bool:
    """
    Dedicated handler for LinkedIn in Google Chrome (or Safari):
    1. Searches all open tabs across Chrome windows for linkedin.com or LinkedIn.
    2. Switches directly to the LinkedIn tab and activates the window.
       (If not found, opens https://www.linkedin.com/feed/).
    3. Finds and clicks the 'Start a post' button / composer text area.
    """
    script = '''
    tell application "Google Chrome"
        set found to false
        repeat with w in windows
            set tIndex to 0
            repeat with t in tabs of w
                set tIndex to tIndex + 1
                if (URL of t contains "linkedin.com") or (title of t contains "LinkedIn") then
                    set active tab index of w to tIndex
                    set index of w to 1
                    activate
                    set found to true
                    exit repeat
                end if
            end repeat
            if found then exit repeat
        end repeat
        if not found then
            if (count of windows) > 0 then
                tell front window
                    set newTab to make new tab with properties {URL:"https://www.linkedin.com/feed/"}
                    set active tab index to (count of tabs)
                    activate
                end tell
            else
                make new window
                tell front window
                    set URL of active tab to "https://www.linkedin.com/feed/"
                    activate
                end tell
            end if
        end if
    end tell
    '''
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2.5)
    except Exception as e:
        print(f"[AppFocusRegistry] LinkedIn tab switch error: {e}")

    time.sleep(0.12)

    # Click / focus the 'Start a post' text area in LinkedIn using macOS Accessibility
    click_script = '''
    tell application "System Events"
        tell process "Google Chrome"
            try
                -- If a text field or text area (e.g. open post composer, comment, or DM box) is already focused, keep it
                set foc to (get value of attribute "AXFocusedUIElement")
                if foc is not missing value then
                    set r to role of foc
                    if r is "AXTextField" or r is "AXTextArea" then
                        return "already_focused"
                    end if
                end if
            end try
            try
                -- First check if a button named "Start a post" exists in window 1 and click it
                set btn to (first UI element of window 1 whose name is "Start a post" or description is "Start a post")
                click btn
                return "clicked_post"
            end try
            try
                set cur to item 1 of (UI elements of window 1)
                repeat 10 times
                    set subs to UI elements of cur
                    if (count of subs) is equal to 1 then
                        set cur to item 1 of subs
                    else
                        exit repeat
                    end if
                end repeat
                set g2 to item 2 of subs
                set g3 to item 1 of (UI elements of g2)
                set scrollArea to item 2 of (UI elements of g3)
                set webArea to item 1 of (UI elements of scrollArea)
                set mainFeed to item 1 of (UI elements of webArea)
                set gMain to item 3 of (UI elements of mainFeed)
                set gContent to item 2 of (UI elements of gMain)
                set gInner to item 2 of (UI elements of gContent)
                set gShare to item 1 of (UI elements of gInner)
                set tf to item 2 of (UI elements of gShare)
                click tf
                return "clicked_post"
            end try
        end tell
    end tell
    return "false"
    '''
    try:
        res = subprocess.run(["osascript", "-e", click_script], capture_output=True, text=True, timeout=2.0)
        out = res.stdout.strip().lower()
        if "clicked_post" in out:
            time.sleep(0.25)
            return True
        if "already_focused" in out or "true" in out:
            return True
    except Exception:
        pass

    return True


AppFocusRegistry.register(
    AppFocusTarget(
        app_name="Google Chrome",
        bundle_id_pattern=r"com\.google\.Chrome",
        aliases=("chrome", "browser"),
        custom_focus_fn=_focus_chrome,
    )
)

AppFocusRegistry.register(
    AppFocusTarget(
        app_name="LinkedIn",
        bundle_id_pattern=r"com\.google\.Chrome",
        aliases=("linkedin.com", "linked in", "linkedin feed"),
        custom_focus_fn=_focus_linkedin,
    )
)

AppFocusRegistry.register(
    AppFocusTarget(
        app_name="Safari",
        bundle_id_pattern=r"com\.apple\.Safari",
        aliases=("safari browser",),
        shortcut="Cmd+L",
    )
)

AppFocusRegistry.register(
    AppFocusTarget(
        app_name="Slack",
        bundle_id_pattern=r"com\.tinyspeck\.slackmacgap",
        aliases=("slack messenger",),
        shortcut="Cmd+K",
    )
)

AppFocusRegistry.register(
    AppFocusTarget(
        app_name="Notes",
        bundle_id_pattern=r"com\.apple\.Notes",
        aliases=("apple notes", "mac notes"),
        shortcut="Cmd+N",
    )
)

AppFocusRegistry.register(
    AppFocusTarget(
        app_name="Visual Studio Code",
        bundle_id_pattern=r"com\.microsoft\.VSCode",
        aliases=("code", "vscode", "vs code"),
        shortcut="Cmd+L",
    )
)

AppFocusRegistry.register(
    AppFocusTarget(
        app_name="Cursor",
        bundle_id_pattern=r"com\.todesktop\..*cursor",
        aliases=("cursor ide", "cursor editor"),
        shortcut="Cmd+L",
    )
)
