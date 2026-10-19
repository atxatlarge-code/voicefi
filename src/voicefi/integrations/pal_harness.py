"""
Pal macOS Computer-Use Harness for VoiceFi.
Provides deterministic, sub-50ms native macOS operating system actions (apps, audio, windows, files)
triggered by 'Hey Pal' or local model ReAct tool-calling loops.
"""

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PalCommandResult:
    success: bool
    command: str
    action_type: str
    details: str
    spoken_summary: str
    should_speak: bool = False


class PalHarness:
    """
    On-device macOS automation harness for voice-activated computer use.
    Executes native LaunchServices, osascript/AppleScript, and system event commands.
    """

    APP_MAP: Dict[str, str] = {
        "garageband": "GarageBand",
        "garage band": "GarageBand",
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "safari": "Safari",
        "terminal": "Terminal",
        "iterm": "iTerm",
        "iterm2": "iTerm",
        "code": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "vscode": "Visual Studio Code",
        "cursor": "Cursor",
        "slack": "Slack",
        "spotify": "Spotify",
        "apple music": "Music",
        "music": "Music",
        "notes": "Notes",
        "messages": "Messages",
        "imessage": "Messages",
        "mail": "Mail",
        "finder": "Finder",
        "settings": "System Settings",
        "system settings": "System Settings",
        "system preferences": "System Settings",
        "calculator": "Calculator",
        "calendar": "Calendar",
        "preview": "Preview",
        "voicefi": "VoiceFi",
    }

    FOLDER_MAP: Dict[str, Path] = {
        "downloads": Path.home() / "Downloads",
        "download": Path.home() / "Downloads",
        "desktop": Path.home() / "Desktop",
        "documents": Path.home() / "Documents",
        "projects": Path.home() / "Projects",
        "voicefi": Path.home() / "Projects" / "VoiceFi",
        "voice fi": Path.home() / "Projects" / "VoiceFi",
        "vifi": Path.home() / "Projects" / "VoiceFi",
        "lienlogic": Path.home() / "Projects" / "LienLogic",
        "lien logic": Path.home() / "Projects" / "LienLogic",
        "home": Path.home(),
    }

    _ACTIVE_TRAINER: Optional[Any] = None

    @classmethod
    def is_training_active(cls) -> bool:
        return cls._ACTIVE_TRAINER is not None

    @classmethod
    def get_active_trainer(cls) -> Optional[Any]:
        return cls._ACTIVE_TRAINER

    @classmethod
    def start_training(cls, workflow_name: str, on_step: Optional[Any] = None) -> PalCommandResult:
        """Start a demonstration-based training session."""
        from voicefi.integrations.pal_trainer import PalTrainer

        if cls._ACTIVE_TRAINER is not None:
            return PalCommandResult(
                success=False,
                command=f"start training {workflow_name}",
                action_type="training",
                details="Training session already active",
                spoken_summary=f"Already training {cls._ACTIVE_TRAINER.workflow_name}",
            )
        cls._ACTIVE_TRAINER = PalTrainer(workflow_name, on_step=on_step)
        cls._ACTIVE_TRAINER.start()
        return PalCommandResult(
            success=True,
            command=f"start training {workflow_name}",
            action_type="training_start",
            details=f"Started training session for '{workflow_name}'",
            spoken_summary=f"Started training {workflow_name}. Show me the steps, and say 'stop training' when done.",
        )

    @classmethod
    def stop_training(cls) -> PalCommandResult:
        """Stop active training, synthesize recipe, and save."""
        if cls._ACTIVE_TRAINER is None:
            return PalCommandResult(
                success=False,
                command="stop training",
                action_type="training",
                details="No training session active",
                spoken_summary="No active training session to stop",
            )
        trainer = cls._ACTIVE_TRAINER
        cls._ACTIVE_TRAINER = None
        recipe = trainer.finish()
        step_count = len(recipe.steps)
        return PalCommandResult(
            success=True,
            command="stop training",
            action_type="training_stop",
            details=f"Compiled '{recipe.name}' with {step_count} steps to ~/.voicefi/workflows/{recipe.id}.yaml",
            spoken_summary=f"Saved workflow {recipe.name} with {step_count} steps. You can run it anytime by saying 'Hey Pal, {recipe.name}'.",
        )

    @classmethod
    def cancel_training(cls) -> PalCommandResult:
        """Cancel active training without saving."""
        if cls._ACTIVE_TRAINER is None:
            return PalCommandResult(
                success=False,
                command="cancel training",
                action_type="training",
                details="No training session active",
                spoken_summary="No active training session to cancel",
            )
        trainer = cls._ACTIVE_TRAINER
        cls._ACTIVE_TRAINER = None
        trainer.cancel()
        return PalCommandResult(
            success=True,
            command="cancel training",
            action_type="training_cancel",
            details=f"Cancelled training session for '{trainer.workflow_name}'",
            spoken_summary="Training cancelled. No workflow was saved.",
        )

    @classmethod
    def record_voice_annotation(cls, text: str) -> None:
        """Attach voice intent text to active training session."""
        if cls._ACTIVE_TRAINER is not None:
            cls._ACTIVE_TRAINER.record_voice_note(text)

    @classmethod
    def run_applescript(cls, script: str) -> Tuple[bool, str]:
        """Execute an AppleScript snippet via osascript with timeout."""
        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=4.0,
            )
            if res.returncode == 0:
                return True, res.stdout.strip()
            return False, res.stderr.strip()
        except Exception as e:
            return False, str(e)

    @classmethod
    def launch_app(cls, raw_name: str) -> PalCommandResult:
        """Launch or focus a macOS application."""
        clean_name = raw_name.lower().strip(" \t\n\r.,!?:;\"'")
        clean_name = re.sub(
            r"\b(?:please|for me|right now|now|thanks|thank you|app|application)\b.*$",
            "",
            clean_name,
            flags=re.IGNORECASE,
        ).strip(" \t\n\r.,!?:;\"'")
        target_app = cls.APP_MAP.get(clean_name, raw_name.strip(" \t\n\r.,!?:;\"'"))
        if clean_name in cls.APP_MAP:
            target_app = cls.APP_MAP[clean_name]
        elif Path(f"/Applications/{clean_name.capitalize()}.app").exists():
            target_app = clean_name.capitalize()

        try:
            res = subprocess.run(
                ["open", "-a", target_app],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
            if res.returncode == 0:
                return PalCommandResult(
                    success=True,
                    command=f"open -a '{target_app}'",
                    action_type="launch_app",
                    details=f"Launched {target_app}",
                    spoken_summary=f"Opened {target_app}",
                    should_speak=False,
                )
            else:
                return PalCommandResult(
                    success=False,
                    command=f"open -a '{target_app}'",
                    action_type="launch_app",
                    details=res.stderr.strip(),
                    spoken_summary=f"Could not open {target_app}",
                    should_speak=True,
                )
        except Exception as e:
            return PalCommandResult(
                success=False,
                command=f"open -a '{target_app}'",
                action_type="launch_app",
                details=str(e),
                spoken_summary=f"Failed to launch {target_app}",
                should_speak=True,
            )

    @classmethod
    def quit_app(cls, raw_name: str) -> PalCommandResult:
        """Quit a running application."""
        clean_name = raw_name.lower().strip(" \t\n\r.,!?:;\"'")
        clean_name = re.sub(
            r"\b(?:please|for me|right now|now|thanks|thank you|app|application)\b.*$",
            "",
            clean_name,
            flags=re.IGNORECASE,
        ).strip(" \t\n\r.,!?:;\"'")
        target_app = cls.APP_MAP.get(clean_name, raw_name.strip(" \t\n\r.,!?:;\"'"))
        if clean_name in cls.APP_MAP:
            target_app = cls.APP_MAP[clean_name]
        elif Path(f"/Applications/{clean_name.capitalize()}.app").exists():
            target_app = clean_name.capitalize()

        script = f'tell application "{target_app}" to quit'
        success, out = cls.run_applescript(script)
        return PalCommandResult(
            success=success,
            command=script,
            action_type="quit_app",
            details=out,
            spoken_summary=f"Quit {target_app}" if success else f"Could not quit {target_app}",
            should_speak=not success,
        )

    @classmethod
    def set_system_volume(
        cls,
        level: Optional[int] = None,
        delta: Optional[int] = None,
        mute: Optional[bool] = None,
    ) -> PalCommandResult:
        """Adjust or mute system output volume."""
        if mute is True:
            success, _ = cls.run_applescript("set volume with output muted")
            return PalCommandResult(
                success=success,
                command="set volume with output muted",
                action_type="volume",
                details="Muted audio",
                spoken_summary="Audio muted",
                should_speak=False,
            )
        elif mute is False:
            success, _ = cls.run_applescript("set volume without output muted")
            return PalCommandResult(
                success=success,
                command="set volume without output muted",
                action_type="volume",
                details="Unmuted audio",
                spoken_summary="Audio unmuted",
                should_speak=False,
            )

        if delta is not None:
            # Get current volume first
            ok, current_str = cls.run_applescript("get output volume of (get volume settings)")
            current = int(current_str) if (ok and current_str.isdigit()) else 50
            level = max(0, min(100, current + delta))

        if level is not None:
            level = max(0, min(100, level))
            script = f"set volume output volume {level} without output muted"
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command=script,
                action_type="volume",
                details=f"Set volume to {level}%",
                spoken_summary=f"Volume set to {level} percent",
                should_speak=False,
            )

        return PalCommandResult(
            success=False,
            command="",
            action_type="volume",
            details="No volume parameter specified",
            spoken_summary="Volume unchanged",
            should_speak=True,
        )

    @classmethod
    def control_garageband(cls, action: str) -> PalCommandResult:
        """Specific fast controls for GarageBand."""
        act = action.lower().strip()
        if "record" in act:
            script = (
                'tell application "GarageBand" to activate\n'
                "delay 0.1\n"
                'tell application "System Events" to keystroke "r"'
            )
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command="GarageBand Record (R)",
                action_type="garageband",
                details="Triggered recording in GarageBand",
                spoken_summary="Recording started in GarageBand",
                should_speak=False,
            )
        elif any(k in act for k in ("play", "stop", "pause", "toggle")):
            script = (
                'tell application "GarageBand" to activate\n'
                "delay 0.1\n"
                'tell application "System Events" to keystroke space'
            )
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command="GarageBand Play/Stop (Space)",
                action_type="garageband",
                details="Toggled playback in GarageBand",
                spoken_summary="Toggled GarageBand playback",
                should_speak=False,
            )
        elif any(k in act for k in ("setting", "preference", "audio", "midi")):
            script = (
                'tell application "GarageBand" to activate\n'
                "delay 0.1\n"
                'tell application "System Events" to keystroke "," using command down'
            )
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command="GarageBand Audio Preferences (Cmd+,)",
                action_type="garageband",
                details="Opened GarageBand Settings",
                spoken_summary="Opened GarageBand audio preferences",
                should_speak=False,
            )

        return cls.launch_app("GarageBand")

    @classmethod
    def open_folder(cls, folder_key_or_path: str) -> PalCommandResult:
        """Open a directory or reveal a file in Finder."""
        raw_clean = folder_key_or_path.strip(" \t\n\r.,!?:;\"'")
        clean = raw_clean.lower()
        # Strip common noise words: 'the', 'my', 'this', 'folder', 'directory'
        clean = re.sub(
            r"\b(?:the|my|this|folder|directory|please|now|right now)\b", "", clean, flags=re.IGNORECASE
        ).strip(" \t\n\r.,!?:;\"'")
        target_path = cls.FOLDER_MAP.get(clean) or cls.FOLDER_MAP.get(raw_clean.lower())

        if not target_path:
            # Check if it's an expanded path
            expanded = Path(os.path.expanduser(raw_clean))
            if expanded.exists():
                target_path = expanded

        if target_path and target_path.exists():
            try:
                subprocess.run(["open", str(target_path)], check=True)
                return PalCommandResult(
                    success=True,
                    command=f"open '{target_path}'",
                    action_type="open_folder",
                    details=f"Opened {target_path}",
                    spoken_summary=f"Opened {target_path.name or 'folder'} in Finder",
                    should_speak=False,
                )
            except Exception as e:
                return PalCommandResult(
                    success=False,
                    command=f"open '{target_path}'",
                    action_type="open_folder",
                    details=str(e),
                    spoken_summary="Failed to open folder",
                    should_speak=True,
                )

        return PalCommandResult(
            success=False,
            command="",
            action_type="open_folder",
            details=f"Folder not found: {folder_key_or_path}",
            spoken_summary="Folder not found",
            should_speak=True,
        )

    @staticmethod
    def strip_wake_prefix(prompt: str) -> str:
        """Strip leading wake-word prefixes ('Hey Pal', 'Hey Brok', 'Hey Viv', 'Hey ViFi', and phonetic variants) and vocal fillers."""
        s = (prompt or "").strip()
        while True:
            prev = s
            s = re.sub(
                r"^(?:(?:hey|hi|ok|okay|yo)\s+)?(?:pal|paul|hal|cal|bell|pow|paypal|brok|brock|broc|brook|viv|vifi|vi-fi|voicefi|wifi|sci-fi|hifi|hate\s+bath)\b[,:\s.!?\-]*",
                "",
                s,
                flags=re.IGNORECASE,
            ).strip()
            s = re.sub(
                r"^(?:(?:uh+|um+|er+|ah+|eh+|hmm+|like|well|so|please)\b[,:\s.!?\-]*)+",
                "",
                s,
                flags=re.IGNORECASE,
            ).strip()
            if s == prev:
                break
        return s

    @classmethod
    def is_deterministic_os_command(cls, prompt: str) -> bool:
        """Return True if the prompt matches a deterministic Tier 0 macOS action (<15ms, no LLM needed)."""
        clean = cls.strip_wake_prefix(prompt).strip(" \t\n\r.,!?:;\"'")
        p_lower = clean.lower()
        if not p_lower:
            return False
        try:
            from voicefi.integrations.app_focus import AppFocusRegistry

            is_trans, _, _ = AppFocusRegistry.parse_transcribe_intent(clean)
            if is_trans:
                return True
        except Exception:
            pass
        if re.match(
            r"^(?:start\s+training|watch\s+me(?:\s+do)?|record\s+workflow|learn\s+how\s+to|stop\s+training|done\s+training|finish\s+training|stop\s+watching|save\s+workflow|cancel\s+training|abort\s+training|discard\s+training)\b",
            p_lower,
        ):
            return True
        if "garageband" in p_lower or "garage band" in p_lower:
            return True
        if re.match(
            r"^(?:scroll\s+(?:down|up)|press\s+(?:enter|return|escape|esc|space)|hit\s+enter|new\s+tab|close\s+tab|refresh(?:\s+page|\s+tab)?|reload(?:\s+page|\s+tab)?|next\s+tab|previous\s+tab|search\s+google\s+for\s+.+|google\s+.+|go\s+to\s+\S+|type\s+.+|click\s+.+|transcribe(?:\s+in\s+.+)?)$",
            p_lower,
        ):
            return True
        if re.match(r"^(?:quit|close|kill|exit|open|launch|start|bring up|switch to|show|reveal)\s+", p_lower):
            return True
        if re.search(r"\b(mute|unmute|shut up|quiet|volume up|volume down|louder|softer)\b", p_lower) or re.search(
            r"(?:set )?volume (?:to )?(\d{1,3})%?", p_lower
        ):
            return True
        if p_lower in ("play", "pause", "resume", "toggle music", "toggle playback", "copy", "paste", "undo"):
            return True
        if p_lower in cls.APP_MAP or Path(f"/Applications/{clean}.app").exists():
            return True
        return False

    @classmethod
    def execute_command(cls, prompt: str, persona: str = "pal") -> PalCommandResult:
        """
        Main entry point for 'Hey Pal' and 'Hey Brok' computer-use command execution.
        Evaluates Fast Tier 0 (sub-15ms deterministic regex/lookup) and falls back to
        Tier 1 Smart Computer-Use (@tool inspections, local Ollama model, and Gemini Live).
        """
        import urllib.parse

        raw_stripped = prompt.strip(" \t\n\r.,!?:;\"'")
        p = cls.strip_wake_prefix(raw_stripped).strip(" \t\n\r.,!?:;\"'") or raw_stripped
        p_lower = p.lower()

        # 0. Training Mode Commands ('Hey Pal, watch me do this' / 'stop training')
        start_train_match = re.match(
            r"^(?:start\s+training|watch\s+me(?:\s+do)?|record\s+workflow|learn\s+how\s+to)\s+(?:a\s+|the\s+)?(.+)$",
            p_lower,
            re.IGNORECASE,
        )
        if start_train_match:
            wf_name = start_train_match.group(1).strip()
            return cls.start_training(wf_name)

        if re.match(
            r"^(?:stop\s+training|done\s+training|finish\s+training|stop\s+watching|save\s+workflow)$",
            p_lower,
            re.IGNORECASE,
        ):
            return cls.stop_training()

        if re.match(
            r"^(?:cancel\s+training|abort\s+training|discard\s+training)$",
            p_lower,
            re.IGNORECASE,
        ):
            return cls.cancel_training()

        # 0.5. Check Dynamic Synthesized Workflows (<0.5ms lookup)
        try:
            from voicefi.integrations.pal_workflow import PalWorkflowRegistry, PalWorkflowRunner

            matched = PalWorkflowRegistry.match_recipe(p)
            if matched:
                recipe, matched_trigger = matched
                return PalWorkflowRunner.execute_recipe(recipe, raw_prompt=p)
        except Exception as e:
            print(f"[PalHarness] Error matching dynamic workflow: {e}")

        # 0.8. Launch Full-Duplex Gemini Live ('go live', 'start live mode', 'brok mode')
        if re.search(r"\b(go\s+live|start\s+live|live\s+mode|brok\s+mode|full\s+duplex)\b", p_lower):
            script = (
                'tell application "Terminal"\n'
                '  activate\n'
                '  do script "vifi live --persona brok"\n'
                'end tell'
            )
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command="vifi live --persona brok",
                action_type="live_session",
                details="Launched full-duplex Brok Live session in Terminal",
                spoken_summary="Launching full-duplex Brok Live mode now.",
                should_speak=True,
            )

        # 0.9. Direct Browser & Keyboard Computer-Use Actions
        if p_lower in ("scroll down", "page down"):
            ok, _ = cls.run_applescript('tell application "System Events" to key code 121')
            return PalCommandResult(ok, "key code 121", "ui_action", "Scrolled down", "Scrolled down.")
        if p_lower in ("scroll up", "page up"):
            ok, _ = cls.run_applescript('tell application "System Events" to key code 116')
            return PalCommandResult(ok, "key code 116", "ui_action", "Scrolled up", "Scrolled up.")
        if p_lower in ("press enter", "hit enter", "press return"):
            ok, _ = cls.run_applescript('tell application "System Events" to key code 36')
            return PalCommandResult(ok, "key code 36", "ui_action", "Pressed Enter", "Pressed Enter.")
        if p_lower in ("press escape", "press esc"):
            ok, _ = cls.run_applescript('tell application "System Events" to key code 53')
            return PalCommandResult(ok, "key code 53", "ui_action", "Pressed Escape", "Pressed Escape.")
        if p_lower == "copy":
            ok, _ = cls.run_applescript('tell application "System Events" to keystroke "c" using command down')
            return PalCommandResult(ok, "Cmd+C", "ui_action", "Copied selection", "Copied to clipboard.")
        if p_lower == "paste":
            ok, _ = cls.run_applescript('tell application "System Events" to keystroke "v" using command down')
            return PalCommandResult(ok, "Cmd+V", "ui_action", "Pasted clipboard", "Pasted from clipboard.")
        if p_lower == "undo":
            ok, _ = cls.run_applescript('tell application "System Events" to keystroke "z" using command down')
            return PalCommandResult(ok, "Cmd+Z", "ui_action", "Undid last action", "Undid last action.")
        if p_lower == "new tab":
            ok, _ = cls.run_applescript(
                'tell application "Google Chrome" to activate\n'
                'tell application "System Events" to keystroke "t" using command down'
            )
            return PalCommandResult(ok, "Chrome Cmd+T", "browser_action", "Opened new tab", "Opened a new tab in Chrome.")
        if p_lower == "close tab":
            ok, _ = cls.run_applescript('tell application "System Events" to keystroke "w" using command down')
            return PalCommandResult(ok, "Cmd+W", "browser_action", "Closed active tab", "Closed active tab.")
        if p_lower in ("refresh", "refresh page", "refresh tab", "reload", "reload page", "reload tab"):
            ok, _ = cls.run_applescript('tell application "System Events" to keystroke "r" using command down')
            return PalCommandResult(ok, "Cmd+R", "browser_action", "Refreshed page", "Refreshed page.")
        if p_lower == "next tab":
            ok, _ = cls.run_applescript(
                'tell application "System Events" to key code 124 using {command down, option down}'
            )
            return PalCommandResult(ok, "Next Tab", "browser_action", "Switched to next tab", "Switched to next tab.")
        if p_lower == "previous tab":
            ok, _ = cls.run_applescript(
                'tell application "System Events" to key code 123 using {command down, option down}'
            )
            return PalCommandResult(ok, "Previous Tab", "browser_action", "Switched to previous tab", "Switched to previous tab.")

        search_match = re.match(r"^(?:search\s+google\s+for|google)\s+(.+)$", p, re.IGNORECASE)
        if search_match:
            q = search_match.group(1).strip()
            url = f"https://www.google.com/search?q={urllib.parse.quote_plus(q)}"
            subprocess.run(["open", "-a", "Google Chrome", url], check=False)
            return PalCommandResult(True, url, "browser_search", f"Searched Google for {q}", f"Searching Google for {q} in Chrome.", should_speak=False)

        goto_match = re.match(r"^go\s+to\s+(\S+)$", p_lower)
        if goto_match:
            raw_site = goto_match.group(1).strip()
            url = raw_site if raw_site.startswith("http") else (f"https://{raw_site}" if "." in raw_site else f"https://{raw_site}.com")
            subprocess.run(["open", "-a", "Google Chrome", url], check=False)
            return PalCommandResult(True, url, "browser_open", f"Opened {url}", f"Opened {raw_site} in Chrome.", should_speak=False)

        try:
            from voicefi.integrations.app_focus import AppFocusRegistry

            is_trans, target_app_parsed, _ = AppFocusRegistry.parse_transcribe_intent(p)
            if is_trans:
                focused = AppFocusRegistry.focus_app_input(target_app_parsed if target_app_parsed else None)
                target_disp = target_app_parsed if target_app_parsed else "active window"
                return PalCommandResult(
                    success=focused,
                    command=f"transcribe in {target_disp}",
                    action_type="transcribe_app_focus",
                    details=f"Focused input box in {target_disp} for live transcription",
                    spoken_summary=f"Transcribing in {target_disp}.",
                    should_speak=False,
                )
        except Exception:
            pass

        type_match = re.match(r"^type\s+(.+)$", p, re.IGNORECASE)
        if type_match:
            text_to_type = type_match.group(1).replace("\\", "\\\\").replace('"', '\\"')
            ok, _ = cls.run_applescript(f'tell application "System Events" to keystroke "{text_to_type}"')
            return PalCommandResult(ok, f"type {text_to_type}", "ui_type", f"Typed '{text_to_type}'", f"Typed {type_match.group(1)}.")

        click_match = re.match(r"^click\s+(?:on\s+|the\s+)?(.+?)(?:\s+button)?$", p, re.IGNORECASE)
        if click_match:
            btn_name = click_match.group(1).strip().replace('"', '\\"')
            script = (
                'tell application "System Events"\n'
                '  set frontApp to first application process whose frontmost is true\n'
                f'  click (first button of window 1 of frontApp whose name contains "{btn_name}" or description contains "{btn_name}")\n'
                'end tell'
            )
            ok, err = cls.run_applescript(script)
            return PalCommandResult(
                ok,
                f"click '{btn_name}'",
                "ui_click",
                err if not ok else f"Clicked {btn_name}",
                f"Clicked {btn_name}." if ok else f"Could not find a button named {btn_name} in the active window.",
            )

        # 1. Quit / Close Application
        quit_match = re.match(
            r"^(?:quit|close|kill|exit)\s+(?:the\s+)?(.+)$",
            p_lower,
            re.IGNORECASE,
        )
        if quit_match:
            target = quit_match.group(1).strip(" \t\n\r.,!?:;\"'")
            if not target.startswith("port ") and target != "tab":
                return cls.quit_app(target)

        # 2. GarageBand specific triggers
        if "garageband" in p_lower or "garage band" in p_lower:
            if any(
                k in p_lower
                for k in ("record", "play", "stop", "pause", "setting", "preference", "audio")
            ):
                return cls.control_garageband(p_lower)
            return cls.launch_app("GarageBand")

        # 2. Volume & Audio Control
        if re.search(r"\b(mute|shut up|quiet)\b", p_lower):
            return cls.set_system_volume(mute=True)
        if re.search(r"\b(unmute)\b", p_lower):
            return cls.set_system_volume(mute=False)

        vol_match = re.search(r"(?:set )?volume (?:to )?(\d{1,3})%?", p_lower)
        if vol_match:
            try:
                lvl = int(vol_match.group(1))
                return cls.set_system_volume(level=lvl)
            except Exception:
                pass

        if "volume up" in p_lower or "louder" in p_lower:
            return cls.set_system_volume(delta=+12)
        if "volume down" in p_lower or "softer" in p_lower:
            return cls.set_system_volume(delta=-12)

        # 3. Launch / Open Application or Folder
        open_match = re.match(
            r"^(?:open|launch|start|bring up|switch to)\s+(?:the\s+)?(.+)$",
            p_lower,
            re.IGNORECASE,
        )
        if open_match:
            target = open_match.group(1).strip(" \t\n\r.,!?:;\"'")
            folder_clean = re.sub(
                r"\b(?:the|my|this|folder|directory)\b", "", target, flags=re.IGNORECASE
            ).strip(" \t\n\r.,!?:;\"'")
            if (
                folder_clean in cls.FOLDER_MAP
                or target in cls.FOLDER_MAP
                or "folder" in target
                or "directory" in target
                or "/" in target
                or "~" in target
            ):
                res = cls.open_folder(folder_clean or target)
                if res.success:
                    return res
            return cls.launch_app(target)

        # 4. Open Folders directly
        if p_lower.startswith("show ") or p_lower.startswith("reveal "):
            target = re.sub(r"^(?:show|reveal)\s+(?:the\s+)?", "", p_lower)
            target = re.sub(
                r"\b(?:the|my|this|folder|directory)\b", "", target, flags=re.IGNORECASE
            ).strip(" \t\n\r.,!?:;\"'")
            return cls.open_folder(target)

        # 6. Global Play/Pause
        if p_lower in ("play", "pause", "resume", "toggle music", "toggle playback"):
            script = 'tell application "System Events" to key code 49'  # Spacebar
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command="Spacebar toggle",
                action_type="media",
                details="Toggled media playback",
                spoken_summary="Toggled playback",
            )

        # 7. Exact known app name match
        if p_lower in cls.APP_MAP or Path(f"/Applications/{p}.app").exists():
            return cls.launch_app(p)

        # 8. Tier 1 Smart Computer-Use (@tool execution + spoken response)
        return cls.execute_smart_computer_use(p, persona=persona)

    @classmethod
    def execute_smart_computer_use(cls, prompt: str, persona: str = "pal") -> PalCommandResult:
        """
        Execute VoiceFi @tool functions (screen/tab/clipboard inspection, Apple Silicon thermal/RAM X-ray,
        git commit roast, git blame, localhost port sniper, on-device local scout) and synthesize a
        spoken response for 'Hey Pal' or 'Hey Brok'.
        """
        import asyncio
        import json
        import urllib.request
        from voicefi.integrations.live_tools import execute_live_tool

        p_lower = prompt.lower().strip()
        is_roast = persona == "brok" or any(w in p_lower for w in ("roast", "brok", "burn", "judge"))

        tool_name = "inspect_mac_screen_and_clipboard"
        tool_args: Dict[str, Any] = {}

        if any(w in p_lower for w in ("ram", "memory", "thermal", "fan", "cpu", "hardware", "x-ray", "xray", "swap", "tier", "hog")):
            tool_name = "mac_thermal_and_router_xray"
        elif any(w in p_lower for w in ("email", "inbox", "gmail", "mail", "draft")):
            tool_name = "inspect_open_email"
        elif any(w in p_lower for w in ("music", "spotify", "song", "track", "playing", "listening", "playlist")):
            tool_name = "roast_now_playing"
        elif any(w in p_lower for w in ("terminal", "command", "bash", "zsh", "history", "last command")):
            tool_name = "roast_last_command"
        elif any(w in p_lower for w in ("pr", "pull request", "code review", "github", "gitlab")):
            tool_name = "roast_open_pr"
        elif any(w in p_lower for w in ("commit", "git log", "last change")):
            tool_name = "roast_last_commit"
        elif "blame" in p_lower:
            m = re.search(r"([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+)", prompt)
            tool_name = "git_blame_courtroom"
            tool_args = {"file_path": m.group(1) if m else "src/voicefi/cli.py"}
        elif "port" in p_lower:
            m = re.search(r"\b(\d{4,5})\b", p_lower)
            tool_name = "free_localhost_port"
            tool_args = {"port": int(m.group(1)) if m else 3000}
        elif any(w in p_lower for w in ("test", "qa", "pytest")):
            tool_name = "run_local_qa_gate"
        elif any(w in p_lower for w in ("scout", "analyze", "router.py", "file")):
            m = re.search(r"([a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+)", prompt)
            tool_name = "local_scout_file"
            tool_args = {
                "file_path": m.group(1) if m else "src/voicefi/local/router.py",
                "question": prompt,
            }
        elif any(w in p_lower for w in ("both agents", "summon both", "viv and steffan", "antigravity and claude")):
            tool_name = "summon_both_agents"
            tool_args = {"task_or_question": prompt}

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    raw_tool_output = pool.submit(
                        asyncio.run, execute_live_tool(tool_name, tool_args)
                    ).result(timeout=5.0)
            else:
                raw_tool_output = asyncio.run(execute_live_tool(tool_name, tool_args))
        except Exception as e:
            raw_tool_output = f"Tool error: {e}"

        spoken = cls._synthesize_spoken_reply(prompt, raw_tool_output, is_roast=is_roast)

        return PalCommandResult(
            success=True,
            command=f"@tool:{tool_name}",
            action_type=f"smart_{tool_name}",
            details=raw_tool_output,
            spoken_summary=spoken,
            should_speak=True,
        )

    @classmethod
    def _synthesize_spoken_reply(cls, prompt: str, tool_output: str, is_roast: bool = False) -> str:
        """Synthesize a crisp 1-2 sentence spoken response from live Mac @tool output."""
        import json
        import urllib.request

        # Keep clipboard preview short and strip raw URLs so TTS never reads query strings aloud
        trimmed_output = tool_output
        if "Clipboard Content:\n" in trimmed_output and "tab" in prompt.lower() and "clipboard" not in prompt.lower():
            trimmed_output = trimmed_output.split("Clipboard Content:\n")[0].strip()
        else:
            trimmed_output = trimmed_output[:700]
        trimmed_output = re.sub(r"\s*\|\s*https?://\S+", "", trimmed_output)

        tab_title = None
        if "Chrome Active Tab:" in trimmed_output and ("tab" in prompt.lower() or "screen" in prompt.lower() or "looking" in prompt.lower()):
            for line in trimmed_output.splitlines():
                if line.startswith("Chrome Active Tab:"):
                    tab_title = line.replace("Chrome Active Tab:", "").split("|")[0].strip()
                    break

        if not is_roast and tab_title and "tab" in prompt.lower() and "clipboard" not in prompt.lower():
            return f"You currently have {tab_title} open in Google Chrome."

        ram_line = ""
        therm_line = "NORMAL"
        cpu_line = ""
        if "Mac Apple Silicon Telemetry" in trimmed_output:
            for line in trimmed_output.splitlines():
                if "Unified RAM:" in line:
                    m_ram = re.search(r"([\d.]+\s*GB)\s*free\s*/\s*([\d.]+\s*GB)\s*total", line)
                    if m_ram:
                        ram_line = f"{m_ram.group(1)} free out of {m_ram.group(2)}"
                elif "Thermal State:" in line:
                    m_th = re.search(r"Thermal State:\s*([A-Za-z]+)", line)
                    if m_th:
                        therm_line = m_th.group(1)
                elif "1m CPU Load:" in line:
                    m_cpu = re.search(r"1m CPU Load:\s*([\d.]+)", line)
                    if m_cpu:
                        cpu_line = m_cpu.group(1)
            if not is_roast and ram_line:
                cpu_part = f" with a CPU load of {cpu_line}" if cpu_line else ""
                return f"Your Mac has {ram_line} of unified memory, thermal state is {therm_line}{cpu_part}."

        style = (
            "You are Brok, a playful, witty, Grok-style AI sidekick and roastmaster living on the user's Mac. "
            "Respond to the user in 1 to 2 punchy, funny, irreverent spoken sentences. "
            "If they ask about their screen, tabs, emails, drafts, PRs, music, or Mac, ruthlessly zero in on the specific subject lines, senders, open tabs, or details shown in the Live Mac Data below. "
            "Deliver a hilarious, sharp, observational roast on their actual open items (like weird tabs, corporate jargon, or playlist picks). "
            "If they ask a general question or brainstorm with you, give a sharp, entertaining, opinionated hot take. "
            "Output ONLY the spoken sentences, no intro or quotes."
            if is_roast
            else "You are Pal, a fast, calm, local Mac companion. Answer the user's question in 1 to 2 concise spoken sentences naming the exact tab, app, or metric from the Mac data below. Output ONLY the spoken sentences."
        )
        full_prompt = f"{style}\n\nUser asked: {prompt}\n\nLive Mac Data:\n{trimmed_output}\n\nSpoken reply:"

        # 1. Ultra-fast local MLX LoRA worker (:9379/v1/chat/completions -> voicefi-coder-mlx, ~65-260ms on Apple Silicon Metal)
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:9379/v1/chat/completions",
                data=json.dumps(
                    {
                        "model": "voicefi-coder-mlx",
                        "messages": [
                            {"role": "system", "content": style},
                            {
                                "role": "user",
                                "content": f"User asked: {prompt}\n\nLive Mac Data:\n{trimmed_output}\n\nSpoken reply:",
                            },
                        ],
                        "max_tokens": 90,
                        "temperature": 0.5,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=1.8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [{}])
                reply = (
                    (choices[0].get("message", {}).get("content") or "")
                    .strip()
                    .replace("*", "")
                    .replace("#", "")
                    .strip('"')
                )
                if reply:
                    return reply
        except Exception:
            pass

        # 2. Local Ollama on Metal (:11434/api/generate -> voicefi-coder:1.5b)
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate",
                data=json.dumps(
                    {
                        "model": "voicefi-coder:1.5b",
                        "prompt": full_prompt,
                        "stream": False,
                        "options": {"temperature": 0.6, "num_predict": 85},
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=2.2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = (data.get("response") or "").strip().replace("*", "").replace("#", "").strip('"')
                if reply:
                    return reply
        except Exception:
            pass

        # 3. Gemini Flash fallback if configured
        try:
            from voicefi.config import load_config
            from voicefi.integrations.gemini_live import resolve_gemini_api_key

            api_key = resolve_gemini_api_key(load_config())
            if api_key:
                from google import genai

                client = genai.Client(api_key=api_key)
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=full_prompt,
                )
                if resp and resp.text:
                    return resp.text.strip().strip('"').replace("*", "")
        except Exception:
            pass

        # 4. Instant deterministic heuristic fallback (sub-5ms, zero network)
        if tab_title:
            if is_roast:
                return f"You're staring at {tab_title} in Chrome. Time to lock in and get back to shipping."
            return f"You have {tab_title} open in Google Chrome."
        if ram_line:
            if is_roast:
                return f"Your Mac is sitting at {ram_line} of memory with thermals on {therm_line}. Hardware is chilling, unlike you."
            return f"Your Mac has {ram_line} of memory, thermal state is {therm_line}."

        lines = [ln.strip() for ln in trimmed_output.splitlines() if ln.strip()]
        return " ".join(lines[:2])[:180]


def is_pal_or_intent_command(prompt: str, engine: Optional[str] = None) -> bool:
    """Determine whether a spoken prompt or target engine should be handled by Pal / Mac OS harness."""
    if not prompt or not prompt.strip():
        return False
    if engine and str(engine).lower() in ("pal", "mac", "system", "os", "computer_use"):
        return True
    low = prompt.strip().lower()
    if re.match(
        r"^(?:(?:hey|hi|ok|okay|yo)\s+)(?:pal|paul|hal|cal|bell|pow|paypal|brok|brock|broc|brook|viv|vifi|vi-fi|voicefi|wifi|sci-fi|hifi|hate\s+bath)\b",
        low,
    ) or re.match(r"^(?:pal|brok|viv|vifi|vi-fi|paypal|hate\s+bath)\b[,:\s]+(?:open|launch|quit|close|start|stop|mute|unmute|set|look|show|switch|bring|check|draft|ship|watch)\b", low):
        return True
    if PalHarness.is_deterministic_os_command(low) and (
        re.match(r"^(?:open|launch|quit|close|kill|mute|unmute|set\s+volume|switch\s+to|bring\s+up)\b", low)
        or "garageband" in low
        or "garage band" in low
    ):
        return True
    if low.startswith("look at my screen"):
        return True
    if any(low.startswith(pfx) for pfx in ("open ", "launch ", "quit ", "mute", "unmute", "set volume")):
        return True
    if any(
        phrase in low
        for phrase in (
            "important emails",
            "check emails",
            "draft responses",
            "ship it",
            "lgtm",
            "watch me do",
            "start training",
            "stop training",
        )
    ):
        return True
    return False


_SHARED_INTENT_ROUTER: Optional[Any] = None


def execute_pal_or_intent_turn(
    prompt: str,
    config: Optional[Any] = None,
    use_local_model: bool = True,
) -> Dict[str, Any]:
    """
    Unified entry point for macOS computer-use and local intent routing (Hey Pal / Hey Brok).
    Triage order:
    0. Fast Tier 0 PalHarness deterministic OS commands (<25ms, no LLM spin-up)
    1. Direct Smart Computer-Use queries (Chrome tabs, RAM/CPU/thermals, clipboard, roasts)
    2. LocalIntentRouter (Tier 0 reflex, Zmail Hero 3-turn, screen vision, 2-speed handoff)
    3. PalHarness Tier 1 fallback
    """
    global _SHARED_INTENT_ROUTER
    from voicefi.config import load_config
    from voicefi.local.intent import LocalIntentRouter
    from voicefi.stt.biasing import PhoneticNormalizer

    cfg = config or load_config()
    norm_prompt = PhoneticNormalizer.normalize(prompt.strip())
    low_norm = norm_prompt.lower()

    # Tier 0 Fast-Path: Deterministic OS commands (e.g. "hey pal open GarageBand", "open Chrome", "mute")
    if PalHarness.is_deterministic_os_command(norm_prompt):
        pal_res = PalHarness.execute_command(norm_prompt, persona="pal")
        if pal_res.success:
            spoken = pal_res.spoken_summary or "Command executed."
            return {
                "success": True,
                "spoken_response": spoken,
                "action_type": pal_res.action_type,
                "details": pal_res.details,
                "pal_res": pal_res,
            }

    # Tier 0b Fast-Path: Direct Mac inspection queries (Chrome tabs, RAM/CPU/thermal, roasts)
    if any(
        kw in low_norm
        for kw in (
            "tabs do i have",
            "tab is open",
            "open in chrome",
            "chrome tab",
            "memory is free",
            "free memory",
            "how much ram",
            "how much memory",
            "thermal state",
            "roast ",
        )
    ):
        pal_res = PalHarness.execute_command(norm_prompt, persona="pal")
        if pal_res.success:
            spoken = pal_res.spoken_summary or "Command executed."
            return {
                "success": True,
                "spoken_response": spoken,
                "action_type": pal_res.action_type,
                "details": pal_res.details,
                "pal_res": pal_res,
            }

    if _SHARED_INTENT_ROUTER is None:
        _SHARED_INTENT_ROUTER = LocalIntentRouter(config=cfg)
    router = _SHARED_INTENT_ROUTER

    # Tier 0c: Explicit escalation to coding agent (Antigravity / Claude Code) with live Mac screen context
    esc_match = re.match(
        r"^(?:send\s+(?:my\s+|this\s+)?screen(?:\s+and\s+active\s+tab)?\s+to\s+(antigravity|claude|agent)(?:[:\s,-]+(.*))?|(?:tell|ask|have)\s+(antigravity|claude|agent)\s+(?:to\s+)?(.+))$",
        norm_prompt,
        re.IGNORECASE,
    )
    if esc_match:
        raw_target = (esc_match.group(1) or esc_match.group(3) or "antigravity").lower()
        target_agent = "claude" if "claude" in raw_target else "antigravity"
        agent_label = "Claude Code" if target_agent == "claude" else "Antigravity"
        user_task = (esc_match.group(2) or esc_match.group(4) or "Review my current Mac screen and active window context.").strip()
        screen_ctx = router._summarize_visible_mac_screen()
        return {
            "success": True,
            "spoken_response": f"Sent to {agent_label} with your live Mac screen context.",
            "action_type": "escalate_agent",
            "escalate_engine": target_agent,
            "escalate_prompt": f"[Mac Screen Context: {screen_ctx}]\n\n{user_task}",
            "details": f"Escalated to {agent_label}: {user_task}",
        }

    router_res = router.route_prompt(norm_prompt, use_local_model=use_local_model)

    if router_res.get("status", "").startswith("handled_"):
        spoken = router_res.get("spoken_response") or router_res.get("reflex_ack") or "Done."
        return {
            "success": True,
            "spoken_response": spoken,
            "action_type": router_res.get("target", "intent"),
            "details": router_res.get("action", norm_prompt),
            "router_res": router_res,
        }

    pal_res = PalHarness.execute_command(norm_prompt, persona="pal")
    spoken = pal_res.spoken_summary or (
        "Command executed." if pal_res.success else "Could not execute command."
    )
    return {
        "success": pal_res.success,
        "spoken_response": spoken,
        "action_type": pal_res.action_type,
        "details": pal_res.details,
        "pal_res": pal_res,
    }

