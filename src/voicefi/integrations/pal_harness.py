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
        clean_name = raw_name.lower().strip()
        target_app = cls.APP_MAP.get(clean_name, raw_name.strip())

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
                )
            else:
                return PalCommandResult(
                    success=False,
                    command=f"open -a '{target_app}'",
                    action_type="launch_app",
                    details=res.stderr.strip(),
                    spoken_summary=f"Could not open {target_app}",
                )
        except Exception as e:
            return PalCommandResult(
                success=False,
                command=f"open -a '{target_app}'",
                action_type="launch_app",
                details=str(e),
                spoken_summary=f"Failed to launch {target_app}",
            )

    @classmethod
    def quit_app(cls, raw_name: str) -> PalCommandResult:
        """Quit a running application."""
        clean_name = raw_name.lower().strip()
        target_app = cls.APP_MAP.get(clean_name, raw_name.strip())

        script = f'tell application "{target_app}" to quit'
        success, out = cls.run_applescript(script)
        return PalCommandResult(
            success=success,
            command=script,
            action_type="quit_app",
            details=out,
            spoken_summary=f"Quit {target_app}" if success else f"Could not quit {target_app}",
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
            )
        elif mute is False:
            success, _ = cls.run_applescript("set volume without output muted")
            return PalCommandResult(
                success=success,
                command="set volume without output muted",
                action_type="volume",
                details="Unmuted audio",
                spoken_summary="Audio unmuted",
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
            )

        return PalCommandResult(
            success=False,
            command="",
            action_type="volume",
            details="No volume parameter specified",
            spoken_summary="Volume unchanged",
        )

    @classmethod
    def control_garageband(cls, action: str) -> PalCommandResult:
        """Specific fast controls for GarageBand."""
        act = action.lower().strip()
        if "record" in act:
            script = (
                'tell application "GarageBand" to activate\n'
                'delay 0.1\n'
                'tell application "System Events" to keystroke "r"'
            )
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command="GarageBand Record (R)",
                action_type="garageband",
                details="Triggered recording in GarageBand",
                spoken_summary="Recording started in GarageBand",
            )
        elif any(k in act for k in ("play", "stop", "pause", "toggle")):
            script = (
                'tell application "GarageBand" to activate\n'
                'delay 0.1\n'
                'tell application "System Events" to keystroke space'
            )
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command="GarageBand Play/Stop (Space)",
                action_type="garageband",
                details="Toggled playback in GarageBand",
                spoken_summary="Toggled GarageBand playback",
            )
        elif any(k in act for k in ("setting", "preference", "audio", "midi")):
            script = (
                'tell application "GarageBand" to activate\n'
                'delay 0.1\n'
                'tell application "System Events" to keystroke "," using command down'
            )
            success, _ = cls.run_applescript(script)
            return PalCommandResult(
                success=success,
                command="GarageBand Audio Preferences (Cmd+,)",
                action_type="garageband",
                details="Opened GarageBand Settings",
                spoken_summary="Opened GarageBand audio preferences",
            )

        return cls.launch_app("GarageBand")

    @classmethod
    def open_folder(cls, folder_key_or_path: str) -> PalCommandResult:
        """Open a directory or reveal a file in Finder."""
        clean = folder_key_or_path.lower().strip()
        target_path = cls.FOLDER_MAP.get(clean)

        if not target_path:
            # Check if it's an expanded path
            expanded = Path(os.path.expanduser(folder_key_or_path))
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
                )
            except Exception as e:
                return PalCommandResult(
                    success=False,
                    command=f"open '{target_path}'",
                    action_type="open_folder",
                    details=str(e),
                    spoken_summary="Failed to open folder",
                )

        return PalCommandResult(
            success=False,
            command="",
            action_type="open_folder",
            details=f"Folder not found: {folder_key_or_path}",
            spoken_summary="Folder not found",
        )

    @classmethod
    def execute_command(cls, prompt: str) -> PalCommandResult:
        """
        Main entry point for 'Hey Pal' computer-use command execution.
        Evaluates Fast Tier 0 (sub-15ms deterministic regex/lookup) and falls back to
        local model parsing if needed.
        """
        p = prompt.strip()
        p_lower = p.lower()

        # 1. Quit / Close Application
        quit_match = re.match(
            r"^(?:quit|close|kill|exit)\s+(?:the\s+)?(.+)$",
            p_lower,
            re.IGNORECASE,
        )
        if quit_match:
            target = quit_match.group(1).strip()
            return cls.quit_app(target)

        # 2. GarageBand specific triggers
        if "garageband" in p_lower or "garage band" in p_lower:
            if any(k in p_lower for k in ("record", "play", "stop", "pause", "setting", "preference", "audio")):
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

        # 3. Launch / Open Application
        open_match = re.match(
            r"^(?:open|launch|start|bring up|switch to)\s+(?:the\s+)?(.+)$",
            p_lower,
            re.IGNORECASE,
        )
        if open_match:
            target = open_match.group(1).strip()
            # Check if it's a folder first
            if target in cls.FOLDER_MAP or "folder" in target or "/" in target or "~" in target:
                clean_target = target.replace("folder", "").strip()
                res = cls.open_folder(clean_target)
                if res.success:
                    return res
            return cls.launch_app(target)

        # 4. Open Folders directly
        if p_lower.startswith("show ") or p_lower.startswith("reveal "):
            target = re.sub(r"^(?:show|reveal)\s+(?:the\s+)?", "", p_lower).replace("folder", "").strip()
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

        # 7. Fallback: try launching as an application name
        return cls.launch_app(p)
