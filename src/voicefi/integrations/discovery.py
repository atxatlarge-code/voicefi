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

    @staticmethod
    def is_antigravity_hook_installed() -> bool:
        """Check if Antigravity lifecycle hook is registered."""
        candidates = [
            Path.home() / ".gemini" / "config" / "plugins" / "voicefi-plugin" / "hooks.json",
            Path.home() / ".gemini" / "config" / "hooks.json",
        ]
        for p in candidates:
            if p.is_file():
                try:
                    content = p.read_text(encoding="utf-8")
                    if "voicefi hook" in content or "voicefi-voice-layer" in content:
                        return True
                except Exception:
                    pass
        return False

    @staticmethod
    def is_claude_hook_installed() -> bool:
        """Check if Claude Code Stop lifecycle hook is registered."""
        claude_settings = Path.home() / ".claude" / "settings.json"
        if claude_settings.is_file():
            try:
                content = claude_settings.read_text(encoding="utf-8")
                if "voicefi hook" in content:
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def is_mcp_configured() -> bool:
        """Check if VoiceFi MCP server is configured in Antigravity or Claude."""
        ag_mcp = Path.home() / ".gemini" / "antigravity" / "mcp" / "voicefi"
        if ag_mcp.is_dir():
            return True
        cl_desktop = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if cl_desktop.is_file():
            try:
                if "voicefi" in cl_desktop.read_text(encoding="utf-8"):
                    return True
            except Exception:
                pass
        cl_mcp = Path.home() / ".claude.json"
        if cl_mcp.is_file():
            try:
                if "voicefi" in cl_mcp.read_text(encoding="utf-8"):
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def is_accessibility_trusted() -> bool:
        """Check if process has macOS accessibility permissions."""
        try:
            import ApplicationServices
            return bool(ApplicationServices.AXIsProcessTrusted())
        except Exception:
            return True

    @staticmethod
    def is_process_running(app_name: str) -> bool:
        """Check if a named macOS application is currently running."""
        try:
            from AppKit import NSWorkspace
            ws = NSWorkspace.sharedWorkspace()
            running = [app.localizedName() for app in ws.runningApplications() if app.localizedName()]
            return any(app_name.lower() in r.lower() for r in running)
        except Exception:
            return False

    @classmethod
    def get_connected_tools_matrix(
        cls,
        config: Any = None,
        companion_summary: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Compile comprehensive status of all connected tools, AI agents,
        bridges/protocols, and macOS permissions.
        """
        ag_hook = cls.is_antigravity_hook_installed()
        ag_detected = cls.detect_antigravity()
        ag_running = cls.is_process_running("Antigravity")

        cl_hook = cls.is_claude_hook_installed()
        cl_detected = cls.detect_claude_code()
        cl_running = cls.is_process_running("Claude")

        cursor_detected = cls.detect_cursor()
        cursor_running = cls.is_process_running("Cursor")

        chatgpt_detected = cls.detect_chatgpt()
        chatgpt_running = cls.is_process_running("ChatGPT")

        windsurf_detected = cls.detect_windsurf()
        windsurf_running = cls.is_process_running("Windsurf")

        mcp_active = cls.is_mcp_configured()
        ax_trusted = cls.is_accessibility_trusted()

        agents: List[Dict[str, Any]] = []
        if ag_detected:
            status = "connected" if ag_hook else "ready"
            detail = "Hook Active • Transcripts Linked" if ag_hook else "Installed • Hook Inactive"
            if ag_running:
                detail += " (Running)"
            agents.append({
                "id": "antigravity",
                "name": "Google Antigravity",
                "status": status,
                "running": ag_running,
                "hook_installed": ag_hook,
                "detail": detail,
            })
        else:
            agents.append({
                "id": "antigravity",
                "name": "Google Antigravity",
                "status": "offline",
                "running": False,
                "hook_installed": False,
                "detail": "Not Detected",
            })

        if cl_detected or cl_running:
            status = "connected" if cl_hook else "ready"
            detail = "Hook Active • Desktop AX Ready" if cl_hook else "Detected • Hook Inactive"
            if cl_running:
                detail += " (Running)"
            agents.append({
                "id": "claude_code",
                "name": "Claude Code CLI & Desktop",
                "status": status,
                "running": cl_running,
                "hook_installed": cl_hook,
                "detail": detail,
            })
        else:
            agents.append({
                "id": "claude_code",
                "name": "Claude Code CLI & Desktop",
                "status": "offline",
                "running": False,
                "hook_installed": False,
                "detail": "Not Detected",
            })

        if cursor_detected or cursor_running:
            agents.append({
                "id": "cursor",
                "name": "Cursor Composer",
                "status": "ready",
                "running": cursor_running,
                "hook_installed": False,
                "detail": "Editor Running • Ready for Voice" if cursor_running else "Installed",
            })

        if chatgpt_detected or chatgpt_running:
            agents.append({
                "id": "chatgpt",
                "name": "ChatGPT for Mac",
                "status": "ready",
                "running": chatgpt_running,
                "hook_installed": False,
                "detail": "App Running • Ready for Voice" if chatgpt_running else "Installed",
            })

        if windsurf_detected or windsurf_running:
            agents.append({
                "id": "windsurf",
                "name": "Windsurf Cascade",
                "status": "ready",
                "running": windsurf_running,
                "hook_installed": False,
                "detail": "Cascade Available",
            })

        comp = companion_summary or {}
        port = comp.get("port", 5141)
        port_online = comp.get("port_online", True)
        relay_connected = comp.get("relay_connected", True)

        bridges = [
            {
                "id": "mcp",
                "name": "VoiceFi MCP Server",
                "status": "connected" if mcp_active else "ready",
                "detail": "Stdio JSON-RPC 2.0 (Active)" if mcp_active else "Available (`vifi mcp`)",
            },
            {
                "id": "local_server",
                "name": "Local Daemon",
                "status": "connected" if port_online else "offline",
                "detail": f"Port {port} Online" if port_online else f"Port {port} Inactive",
            },
            {
                "id": "relay",
                "name": "Cloudflare Edge Relay",
                "status": "connected" if relay_connected else "ready",
                "detail": "companion.voicefi.app",
            },
        ]

        permissions = [
            {
                "id": "accessibility",
                "name": "Accessibility (Auto-Paste)",
                "granted": ax_trusted,
                "detail": "Window Focus & Paste Active" if ax_trusted else "Missing (Grant in macOS)",
            },
            {
                "id": "microphone",
                "name": "Microphone Input",
                "granted": True,
                "detail": "Audio Input Ready",
            },
        ]

        connected_agents = [a["name"].split()[0] for a in agents if a["status"] == "connected"]
        summary_parts = connected_agents + (["MCP"] if mcp_active else [])
        summary_str = " • ".join(summary_parts) if summary_parts else "Ready"

        return {
            "agents": agents,
            "bridges": bridges,
            "permissions": permissions,
            "connected_count": len(connected_agents) + (1 if mcp_active else 0),
            "summary": summary_str,
        }

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

