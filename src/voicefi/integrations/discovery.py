"""
Multi-Agent and Tool Auto-Discovery for VoiceFi.
Detects installed AI coding tools (Antigravity, Claude Code, Cursor, Aider, Windsurf)
and manages their integration states.
"""

import os
from pathlib import Path
from typing import Dict, Any, List


class AgentToolDetector:
    """Detects available AI agent tools on the local macOS system."""

    @staticmethod
    def detect_antigravity() -> bool:
        """Check if Antigravity agent directories exist."""
        path = Path.home() / ".gemini" / "antigravity"
        return path.is_dir()

    @staticmethod
    def detect_claude_code() -> bool:
        """Check if Claude Code CLI is installed or configured."""
        claude_dir = Path.home() / ".claude"
        return (
            claude_dir.is_dir()
            or os.path.exists("/usr/local/bin/claude")
            or os.path.exists(str(Path.home() / ".local" / "bin" / "claude"))
        )

    @staticmethod
    def detect_cursor() -> bool:
        """Check if Cursor editor is installed in /Applications."""
        return os.path.exists("/Applications/Cursor.app") or os.path.exists(
            str(Path.home() / "Applications" / "Cursor.app")
        )

    @staticmethod
    def detect_windsurf() -> bool:
        """Check if Windsurf editor is installed."""
        return os.path.exists("/Applications/Windsurf.app") or os.path.exists(
            str(Path.home() / "Applications" / "Windsurf.app")
        )

    @staticmethod
    def detect_chatgpt() -> bool:
        """Check if ChatGPT macOS desktop app is installed in /Applications."""
        return os.path.exists("/Applications/ChatGPT.app") or os.path.exists(
            str(Path.home() / "Applications" / "ChatGPT.app")
        )

    @staticmethod
    def detect_codex() -> bool:
        """Check if Codex CLI or ~/.codex workspace exists."""
        codex_home = Path.home() / ".codex"
        codex_bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
        return codex_home.is_dir() or codex_bundled.is_file()

    @staticmethod
    def detect_aider() -> bool:
        """Check if Aider CLI is installed."""
        return os.path.exists(str(Path.home() / ".aider")) or os.path.exists("/usr/local/bin/aider")

    @classmethod
    def get_all_detected_tools(cls) -> Dict[str, Dict[str, Any]]:
        """Return discovery status for all supported agent tools."""
        return {
            "antigravity": {
                "name": "Antigravity Agent",
                "detected": cls.detect_antigravity(),
                "description": "Live JSONL transcript watcher & turn-handoff",
            },
            "claude_code": {
                "name": "Claude Code CLI",
                "detected": cls.detect_claude_code(),
                "description": "Terminal session watcher & prompt return hooks",
            },
            "chatgpt": {
                "name": "ChatGPT for Mac",
                "detected": cls.detect_chatgpt(),
                "description": "Desktop app focus, prompt injection & voice loop",
            },
            "codex": {
                "name": "OpenAI Codex",
                "detected": cls.detect_codex(),
                "description": "Native stdio MCP tools & background workspace integration",
            },
            "cursor": {
                "name": "Cursor Composer",
                "detected": cls.detect_cursor(),
                "description": "Target window focus & composer voice injection",
            },
            "windsurf": {
                "name": "Windsurf Cascade",
                "detected": cls.detect_windsurf(),
                "description": "Cascade agent focus & audio handoff",
            },
            "system_dictation": {
                "name": "System-Wide Dictation",
                "detected": True,
                "description": "Universal Ctrl+T dictation across all macOS apps",
            },
        }
