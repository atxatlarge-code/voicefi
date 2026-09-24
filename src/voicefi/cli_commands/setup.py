"""
Setup, onboarding, permissions, and MCP server CLI subcommands.
"""

import os
import sys
import json
import shutil
from pathlib import Path
from typing import Any

from voicefi.config import load_config, save_config, get_default_config_path
from voicefi.integrations.antigravity import handle_antigravity_stop_hook


def cmd_onboarding(args):
    """Run interactive First-Time User Experience onboarding flow."""
    from voicefi.onboarding import run_onboarding

    run_onboarding()


def cmd_permissions(args):
    """Open macOS Accessibility and Input Monitoring security settings."""
    from voicefi.integrations.injector import open_accessibility_settings

    try:
        import ApplicationServices

        options = {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
        trusted = ApplicationServices.AXIsProcessTrustedWithOptions(options)
    except Exception:
        trusted = False

    print("\n🔐 macOS Accessibility & Hotkey Permissions")
    print("------------------------------------------------------------------")
    if trusted:
        print("✅ Accessibility permissions are granted and active!")
    else:
        print("⚠️  Accessibility permission is not yet enabled for this terminal/app.")
        print("👉 Opening macOS System Settings...")
        open_accessibility_settings()
        print("Please toggle Terminal / iTerm / Antigravity to ON in the list.")
    print("------------------------------------------------------------------\n")


def cmd_mcp(args):
    """Run native Stdio JSON-RPC 2.0 Model Context Protocol (MCP) Server for VoiceFi."""
    if (
        getattr(args, "test", False)
        or getattr(args, "ping", False)
        or getattr(args, "check", False)
    ):
        from voicefi.mcp_server import test_posthog_mcp_analytics
        import json

        result = test_posthog_mcp_analytics()
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
            return

        print("\n" + "=" * 60)
        print("  📊 PostHog MCP Analytics — Diagnostics & Egress Test")
        print("=" * 60)
        if result.get("success"):
            print(f"  ✅ Status:           Connected & Delivering ({result.get('status', 'ok')})")
            print(f"  🔑 API Key:          {result.get('api_key_masked')}")
            print(f"  🌐 Ingestion Host:   {result.get('host')}")
            print(f"  👤 Distinct ID:      {result.get('distinct_id')}")
            print(f"  ⚡ Roundtrip Latency: {result.get('latency_ms')} ms")
            print("  📦 Events Emitted:")
            for evt in result.get("events_captured", []):
                print(f"     • {evt}")
            print("\n  👉 Events successfully captured and verified on PostHog dashboard.")
        else:
            print(f"  ❌ Error:            {result.get('error')}")
            print(f"  🌐 Ingestion Host:   {result.get('host')}")
            print(f"  👤 Distinct ID:      {result.get('distinct_id')}")
        print("=" * 60 + "\n")
        return

    from voicefi.mcp_server import run_mcp_server

    run_mcp_server()


def cmd_setup(args):
    """Automatically register VoiceFi lifecycle hooks and MCP server with AI agents (Antigravity, Claude Code, Claude Desktop)."""
    from voicefi.integrations.claude import install_claude_hook, install_claude_desktop_mcp
    from voicefi.integrations.discovery import AgentToolDetector

    setup_all = getattr(args, "all", False)
    setup_claude = getattr(args, "claude", False) or setup_all
    setup_antigravity = getattr(args, "antigravity", False) or setup_all
    is_dev = getattr(args, "dev", False)

    if getattr(args, "remove_hooks", False):
        from voicefi.integrations.antigravity import remove_antigravity_hook
        from voicefi.integrations.claude import remove_claude_hook

        remove_antigravity_hook()
        remove_claude_hook()
        print("🗑️ VoiceFi hooks removed from Antigravity and Claude Code configuration files.")
        return

    # If no explicit agent flags are specified, auto-detect active systems
    if (
        not getattr(args, "claude", False)
        and not getattr(args, "antigravity", False)
        and not setup_all
    ):
        setup_antigravity = True
        if AgentToolDetector.detect_claude_code():
            setup_claude = True

    # Resolution logic: if --dev, prioritize project venv
    bin_path = None
    if is_dev:
        ws_candidates = [
            Path.cwd() / ".venv" / "bin" / "voicefi",
            Path.cwd() / "venv" / "bin" / "voicefi",
            Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "voicefi",
        ]
        for cand in ws_candidates:
            if cand.is_file() and os.access(str(cand), os.X_OK):
                bin_path = str(cand)
                break

    if not bin_path:
        venv_bin = Path(sys.executable).parent / "voicefi"
        if venv_bin.exists():
            bin_path = str(venv_bin)
        else:
            bin_path = shutil.which("voicefi") or shutil.which("vifi") or "voicefi"

    if setup_antigravity:
        hook_command = f"{bin_path} hook"
        hooks_data = {
            "voicefi-voice-layer": {
                "enabled": True,
                "Stop": [
                    {
                        "type": "command",
                        "command": hook_command,
                        "timeout": 60,
                    }
                ],
            }
        }

        plugin_dir = Path.home() / ".gemini" / "config" / "plugins" / "voicefi-plugin"
        plugin_dir.mkdir(parents=True, exist_ok=True)

        mcp_server_entry = {
            "command": bin_path,
            "args": ["mcp"],
        }

        # Install as standard Antigravity plugin in ~/.gemini/config/plugins/voicefi-plugin
        try:
            plugin_json_path = plugin_dir / "plugin.json"
            plugin_manifest = {
                "name": "voicefi-plugin",
                "version": "1.0.0",
                "description": "VoiceFi Voice Layer lifecycle hooks, skills, and MCP tools for Antigravity AI coding agent.",
                "author": {"name": "VoiceFi"},
                "keywords": ["voice", "voicefi", "tts", "stt", "vad", "mcp"],
            }
            with open(plugin_json_path, "w", encoding="utf-8") as f:
                json.dump(plugin_manifest, f, indent=2)

            plugin_hooks_path = plugin_dir / "hooks.json"
            with open(plugin_hooks_path, "w", encoding="utf-8") as f:
                json.dump(hooks_data, f, indent=2)

            # Register plugin MCP config
            plugin_mcp_path = plugin_dir / "mcp_config.json"
            plugin_mcp_data = {"mcpServers": {"voicefi": mcp_server_entry}}
            with open(plugin_mcp_path, "w", encoding="utf-8") as f:
                json.dump(plugin_mcp_data, f, indent=2)

            # Sync bundled skills into plugin directory
            skills_src_dir = Path(__file__).resolve().parent.parent.parent / ".agents" / "skills"
            if not skills_src_dir.is_dir():
                skills_src_dir = Path.cwd() / ".agents" / "skills"
            if skills_src_dir.is_dir():
                plugin_skills_dir = plugin_dir / "skills"
                plugin_skills_dir.mkdir(parents=True, exist_ok=True)
                for skill_sub in skills_src_dir.iterdir():
                    if skill_sub.is_dir():
                        target_sub = plugin_skills_dir / skill_sub.name
                        target_sub.mkdir(parents=True, exist_ok=True)
                        for s_file in skill_sub.glob("*"):
                            if s_file.is_file():
                                shutil.copy2(s_file, target_sub / s_file.name)

            # Sync rules (AGENTS.md) into plugin directory
            agents_rule_src = Path(__file__).resolve().parent.parent.parent / "AGENTS.md"
            if not agents_rule_src.is_file():
                agents_rule_src = Path.cwd() / "AGENTS.md"
            if agents_rule_src.is_file():
                plugin_rules_dir = plugin_dir / "rules"
                plugin_rules_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(agents_rule_src, plugin_rules_dir / "AGENTS.md")

            # Register in ~/.gemini/config/config.json
            global_config_json = Path.home() / ".gemini" / "config" / "config.json"
            if global_config_json.is_file():
                try:
                    c_data = json.loads(global_config_json.read_text(encoding="utf-8")) or {}
                    if "plugins" not in c_data:
                        c_data["plugins"] = {}
                    c_data["plugins"]["voicefi-plugin"] = {"enabled": True}
                    global_config_json.write_text(json.dumps(c_data, indent=2), encoding="utf-8")
                except Exception:
                    pass

            # Clean duplicate global hook in ~/.gemini/config/hooks.json to prevent double-firing
            global_hooks_path = Path.home() / ".gemini" / "config" / "hooks.json"
            if global_hooks_path.is_file():
                try:
                    with open(global_hooks_path, "r", encoding="utf-8") as f:
                        gh = json.load(f) or {}
                    if "voicefi-voice-layer" in gh:
                        del gh["voicefi-voice-layer"]
                        with open(global_hooks_path, "w", encoding="utf-8") as f:
                            json.dump(gh, f, indent=2)
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ Notice creating plugin registration: {e}")

        # Also register in global ~/.gemini/config/mcp_config.json
        try:
            global_mcp_path = Path.home() / ".gemini" / "config" / "mcp_config.json"
            global_mcp_data = {}
            if global_mcp_path.is_file():
                try:
                    with open(global_mcp_path, "r", encoding="utf-8") as f:
                        global_mcp_data = json.load(f) or {}
                except Exception:
                    global_mcp_data = {}
            if "mcpServers" not in global_mcp_data:
                global_mcp_data["mcpServers"] = {}
            global_mcp_data["mcpServers"]["voicefi"] = mcp_server_entry
            with open(global_mcp_path, "w", encoding="utf-8") as f:
                json.dump(global_mcp_data, f, indent=2)
            print(f"✅ Antigravity MCP server registered: {global_mcp_path}")
        except Exception as e:
            print(f"⚠️ Notice updating global MCP config: {e}")

        print(f"✅ Antigravity plugin & hook installed: {plugin_dir}")

        # Also update workspace-level .agents/mcp_config.json if present
        ws_agents_dir = Path.cwd() / ".agents"
        if ws_agents_dir.is_dir():
            ws_agents_hook = ws_agents_dir / "hooks.json"
            if ws_agents_hook.is_file():
                try:
                    with open(ws_agents_hook, "r", encoding="utf-8") as f:
                        wsh = json.load(f) or {}
                    if "voicefi-voice-layer" in wsh:
                        del wsh["voicefi-voice-layer"]
                        with open(ws_agents_hook, "w", encoding="utf-8") as f:
                            json.dump(wsh, f, indent=2)
                except Exception:
                    pass

            ws_agents_mcp = ws_agents_dir / "mcp_config.json"
            try:
                ws_mcp_data = {}
                if ws_agents_mcp.is_file():
                    try:
                        with open(ws_agents_mcp, "r", encoding="utf-8") as f:
                            ws_mcp_data = json.load(f) or {}
                    except Exception:
                        ws_mcp_data = {}
                if "mcpServers" not in ws_mcp_data:
                    ws_mcp_data["mcpServers"] = {}
                ws_mcp_data["mcpServers"]["voicefi"] = mcp_server_entry
                with open(ws_agents_mcp, "w", encoding="utf-8") as f:
                    json.dump(ws_mcp_data, f, indent=2)
                print(f"✅ Workspace Antigravity MCP config updated: {ws_agents_mcp}")
            except Exception as e:
                print(f"⚠️ Could not update workspace MCP config: {e}")

    if setup_claude:
        try:
            claude_settings = install_claude_hook(bin_path=bin_path)
            print(f"✅ Claude Code hook installed: {claude_settings}")
        except Exception as e:
            print(f"⚠️ Could not install Claude Code hook: {e}")
        try:
            claude_desktop_cfg = install_claude_desktop_mcp(bin_path=bin_path)
            if claude_desktop_cfg:
                print(f"✅ Claude Desktop MCP server registered: {claude_desktop_cfg}")
        except Exception as e:
            print(f"⚠️ Could not register Claude Desktop MCP server: {e}")

    # Auto-register Codex & ChatGPT Desktop MCP when detected
    if AgentToolDetector.detect_codex() or setup_all:
        try:
            from voicefi.integrations.codex import install_codex_mcp, install_codex_hook

            if install_codex_mcp(bin_path=bin_path):
                print("✅ OpenAI Codex MCP server registered: ~/.codex/config.toml")
            codex_hook_path = install_codex_hook(bin_path=bin_path)
            if codex_hook_path:
                print(f"✅ OpenAI Codex hook installed: {codex_hook_path}")
        except Exception as e:
            print(f"⚠️ Could not configure OpenAI Codex integration: {e}")

    # Ensure config file exists and defaults to Viv for overall and antigravity
    config_path = get_default_config_path()
    config = load_config()
    changed = False
    if not config_path.is_file():
        save_config(config)
    else:
        if not config.tts.voice or config.tts.voice in (
            "Samantha",
            "en-US-ChristopherNeural",
            "Christopher",
            "christopher",
        ):
            config.tts.voice = "en-US-AvaNeural"
            config.tts.provider = "edge_tts"
            changed = True
        if "antigravity" not in config.agents or config.agents["antigravity"].voice in (
            "en-US-ChristopherNeural",
            "Christopher",
            "christopher",
            None,
            "",
        ):
            from voicefi.config import AgentVoiceProfile

            config.agents["antigravity"] = AgentVoiceProfile(
                voice="en-US-AvaNeural",
                provider="edge_tts",
                offline_voice="Ava (Premium)",
                description="Antigravity Primary Agent",
            )
            changed = True
        if changed:
            save_config(config)

    print(f"⚙️ Configuration saved at: {config_path}")
