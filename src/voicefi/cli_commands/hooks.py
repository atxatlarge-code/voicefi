"""
Hook lifecycle and management CLI subcommands.
"""

import json
import os
import sys
import time
from typing import Any
from voicefi.config import load_config, save_config


def cmd_hook(args: Any) -> None:
    """Handle AI agent lifecycle hook from stdin or manage hook configurations."""
    action = getattr(args, "action", None)
    if getattr(args, "disable", False):
        action = "disable"
    elif getattr(args, "enable", False):
        action = "enable"
    elif getattr(args, "status", False):
        action = "status"
    elif getattr(args, "remove", False):
        action = "remove"

    if action in ("disable", "off"):
        config = load_config(args.config)
        config.hooks.enabled = False
        save_config(config)
        print("🛑 VoiceFi hooks disabled globally (config.yaml: hooks.enabled = false).")
        print(
            "   Agent Stop hooks will immediately return without audio, microphone, or keyboard activity."
        )
        return

    if action in ("enable", "on"):
        config = load_config(args.config)
        config.hooks.enabled = True
        save_config(config)
        print("✅ VoiceFi hooks enabled globally (config.yaml: hooks.enabled = true).")
        return

    if action in ("remove", "uninstall"):
        from voicefi.integrations.antigravity import remove_antigravity_hook
        from voicefi.integrations.claude import remove_claude_hook
        from voicefi.integrations.codex import remove_codex_hook

        remove_antigravity_hook()
        remove_claude_hook()
        remove_codex_hook()
        print(
            "🗑️ VoiceFi hooks removed from Antigravity, Claude Code, and Codex configuration files."
        )
        return

    if action == "status":
        config = load_config(args.config)
        from voicefi.server import get_full_server_status

        st = get_full_server_status()
        hooks = st.get("hooks", {})
        print("\n🪝 VoiceFi Agent Lifecycle Hook Status")
        print("==================================================================")
        print(
            f"  • Global Hooks Enabled:    {'🟢 YES' if (config.enabled and config.hooks.enabled) else '🔴 NO (Disabled)'}"
        )
        print(
            f"  • VoiceFi Master Switch:   {'🟢 Enabled' if config.enabled else '⚪ Paused (enabled: false)'}"
        )
        print(
            f"  • Config Hooks Switch:     {'🟢 Enabled' if config.hooks.enabled else '🔴 Disabled (hooks.enabled: false)'}"
        )
        print("\n  📦 Agent Configurations:")
        print(
            f"    • Antigravity Hook Active: {'🟢 Enabled' if config.hooks.antigravity else '🔴 Disabled'}"
        )
        print(
            f"      - Auto Listen:           {'✅ Yes' if config.antigravity.auto_listen else '❌ No'}"
        )
        print(
            f"      - Read Summary Aloud:    {'✅ Yes' if config.antigravity.read_summary_aloud else '❌ No'}"
        )
        print(f"      - Installed In Plugin:   {hooks.get('antigravity') or '❌ Not installed'}")
        print(
            f"    • Claude Code Hook Active: {'🟢 Enabled' if config.hooks.claude else '🔴 Disabled'}"
        )
        print(
            f"      - Auto Listen:           {'✅ Yes' if config.claude.auto_listen else '❌ No'}"
        )
        print(
            f"      - Read Summary Aloud:    {'✅ Yes' if config.claude.read_summary_aloud else '❌ No'}"
        )
        print(f"      - Installed In Settings: {hooks.get('claude') or '❌ Not installed'}")
        print(
            f"    • Codex Hook Active:       {'🟢 Enabled' if getattr(config.hooks, 'codex', True) else '🔴 Disabled'}"
        )
        print(f"      - Installed In Settings: {hooks.get('codex') or '❌ Not installed'}")
        print("==================================================================\n")
        print(
            "💡 Commands: 'vifi hook disable' | 'vifi hook enable' | 'vifi hook remove' | 'vifi pause'\n"
        )
        return

    try:
        with open("/tmp/antigravity_hook_test.log", "a") as f:
            f.write(f"[{time.time()}] HOOK CALLED with args={args}\n")
    except Exception:
        pass
    config = load_config(args.config)
    target_agent = getattr(args, "agent", "antigravity").lower().strip()

    # Set base zero-PII hook telemetry early
    setattr(
        args,
        "_telemetry_extra",
        {
            "hook_agent": target_agent,
            "has_stdin_payload": False,
            "ipc_forwarded": False,
        },
    )

    # 1. Instant kill-switch guard: if VoiceFi is globally paused or hooks are disabled
    if not config.enabled or not getattr(config.hooks, "enabled", True):
        print(json.dumps({}))
        return

    # 2. Per-agent hook disable guard
    is_claude = target_agent in ("claude", "claude_code") or target_agent.startswith("claude")
    is_codex = (
        target_agent in ("codex", "openai", "chatgpt")
        or target_agent.startswith("codex")
        or target_agent.startswith("chatgpt")
        or target_agent.startswith("openai")
    )
    if is_claude:
        if not getattr(config.hooks, "claude", True) or not getattr(
            config.integrations, "claude_code", True
        ):
            print(json.dumps({}))
            return
        if not config.claude.auto_listen and not config.claude.read_summary_aloud:
            print(json.dumps({}))
            return
    elif is_codex:
        if not getattr(config.hooks, "codex", True) or not getattr(
            config.integrations, "codex", True
        ):
            print(json.dumps({}))
            return
        codex_cfg = getattr(config, "codex", None)
        if codex_cfg and not codex_cfg.auto_listen and not codex_cfg.read_summary_aloud:
            print(json.dumps({}))
            return
    elif target_agent == "antigravity" or target_agent.startswith("antigravity"):
        if not getattr(config.hooks, "antigravity", True) or not getattr(
            config.integrations, "antigravity", True
        ):
            print(json.dumps({}))
            return
        if not config.antigravity.auto_listen and not config.antigravity.read_summary_aloud:
            print(json.dumps({}))
            return

    # Read hook payload: first check CLI arguments (e.g. Codex notify: turn-ended '{"type":...}')
    payload = {}
    extra = getattr(args, "extra_args", []) or []
    candidate_strings = []
    if action and action not in ("enable", "disable", "status", "remove", "uninstall", "on", "off"):
        candidate_strings.append(action)
    candidate_strings.extend(extra)
    candidate_strings.extend(sys.argv)

    for item in candidate_strings:
        if isinstance(item, str) and item.strip().startswith("{") and item.strip().endswith("}"):
            try:
                payload = json.loads(item.strip())
                break
            except Exception:
                pass

    # Read hook payload from stdin non-blockingly if not found in argv
    if not payload:
        try:
            if not sys.stdin.isatty():
                has_fileno = False
                try:
                    fd = sys.stdin.fileno()
                    has_fileno = True
                except Exception:
                    has_fileno = False

                if has_fileno:
                    import select

                    r, _, _ = select.select([fd], [], [], 0.3)
                    if r:
                        raw_bytes = b""
                        while True:
                            chunk = os.read(fd, 65536)
                            if not chunk:
                                break
                            raw_bytes += chunk
                            r2, _, _ = select.select([fd], [], [], 0.02)
                            if not r2:
                                break
                        text = raw_bytes.decode("utf-8").strip()
                        if text:
                            payload = json.loads(text)
                else:
                    raw_input = sys.stdin.readline()
                    if raw_input and raw_input.strip():
                        payload = json.loads(raw_input)
        except Exception:
            payload = {}

    if payload.get("agent"):
        target_agent = str(payload["agent"]).lower().strip()
    else:
        payload["agent"] = target_agent

    # Re-check per-agent guard with payload agent if specified
    if target_agent in ("claude", "claude_code"):
        if not getattr(config.hooks, "claude", True) or not getattr(
            config.integrations, "claude_code", True
        ):
            print(json.dumps({}))
            return
        if not config.claude.auto_listen and not config.claude.read_summary_aloud:
            print(json.dumps({}))
            return
    elif target_agent in ("codex", "openai", "chatgpt"):
        if not getattr(config.hooks, "codex", True) or not getattr(
            config.integrations, "codex", True
        ):
            print(json.dumps({}))
            return
        codex_cfg = getattr(config, "codex", None)
        if codex_cfg and not codex_cfg.auto_listen and not codex_cfg.read_summary_aloud:
            print(json.dumps({}))
            return
    elif target_agent == "antigravity":
        if not getattr(config.hooks, "antigravity", True) or not getattr(
            config.integrations, "antigravity", True
        ):
            print(json.dumps({}))
            return
        if not config.antigravity.auto_listen and not config.antigravity.read_summary_aloud:
            print(json.dumps({}))
            return

    # Set base zero-PII hook telemetry
    setattr(
        args,
        "_telemetry_extra",
        {
            "hook_agent": target_agent,
            "has_stdin_payload": bool(payload),
            "ipc_forwarded": False,
        },
    )

    # Ensure agent and voice override metadata are populated in payload
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("agent", target_agent)
    voice_arg = getattr(args, "voice", None)
    if voice_arg:
        payload["voice"] = voice_arg

    # Fast IPC Forwarding: if VoiceFi background server is running,
    # forward hook event directly for instant (< 10ms) return to the agent
    from voicefi.integrations.server_client import forward_hook_to_server

    server_resp = forward_hook_to_server(payload, config)
    if server_resp and server_resp.get("status") in ("handled", "ok"):
        if hasattr(args, "_telemetry_extra") and isinstance(args._telemetry_extra, dict):
            args._telemetry_extra["ipc_forwarded"] = True
        print(json.dumps({}))
        return

    # Standalone fallback: execute in-process if background server is offline
    cli_mod = sys.modules.get("voicefi.cli")
    if is_claude:
        hook_fn = getattr(cli_mod, "handle_claude_stop_hook", None) if cli_mod else None
        if hook_fn is None:
            from voicefi.integrations.claude import handle_claude_stop_hook as hook_fn

        result = hook_fn(payload, config)
    elif is_codex:
        hook_fn = getattr(cli_mod, "handle_codex_stop_hook", None) if cli_mod else None
        if hook_fn is None:
            from voicefi.integrations.codex import handle_codex_stop_hook as hook_fn

        result = hook_fn(payload, config)
    else:
        hook_fn = getattr(cli_mod, "handle_antigravity_stop_hook", None) if cli_mod else None
        if hook_fn is None:
            from voicefi.integrations.antigravity import handle_antigravity_stop_hook as hook_fn

        result = hook_fn(payload, config)

    # Output clean JSON object as required by hook contract
    out = result if isinstance(result, dict) else {}
    if "decision" in out and out["decision"] == "allow":
        out["decision"] = "approve"
    print(json.dumps(out))
