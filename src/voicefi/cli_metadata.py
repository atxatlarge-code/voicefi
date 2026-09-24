"""
Sanitized, zero-PII telemetry metadata extraction for VoiceFi CLI arguments.
"""

import re
import argparse
from typing import Dict, Any


def extract_cli_metadata(args: argparse.Namespace) -> dict:
    """
    Extract sanitized, zero-PII metadata from CLI arguments.
    Strictly allowlisted: excludes all free-form user text, prompts, transcripts, audio, and paths.
    """
    cmd = getattr(args, "command", "unknown") or "unknown"
    props: dict = {"command": cmd, "$is_server": True}

    # 1. Subcommands / Actions (Strictly allowlisted strings)
    subcommand = None
    if hasattr(args, "server_action") and args.server_action:
        subcommand = str(args.server_action)
    elif hasattr(args, "daemon_action") and args.daemon_action:
        subcommand = str(args.daemon_action)
    elif hasattr(args, "voice_action") and args.voice_action:
        subcommand = str(args.voice_action)
    elif hasattr(args, "hud_action") and args.hud_action:
        subcommand = str(args.hud_action)
    elif hasattr(args, "clone_action") and args.clone_action:
        subcommand = str(args.clone_action)
    elif hasattr(args, "memo_action") and args.memo_action:
        subcommand = str(args.memo_action)
    elif hasattr(args, "ambient_action") and args.ambient_action:
        subcommand = str(args.ambient_action)
    elif hasattr(args, "feedback_action") and args.feedback_action:
        subcommand = str(args.feedback_action)
    elif hasattr(args, "obsidian_action") and args.obsidian_action:
        subcommand = str(args.obsidian_action)
    elif hasattr(args, "hook_action") and args.hook_action:
        subcommand = str(args.hook_action)
    elif hasattr(args, "setup_action") and args.setup_action:
        subcommand = str(args.setup_action)
    elif cmd in (
        "download-ava",
        "ping",
        "feedback-loop",
        "hearing-test",
        "barge-in",
        "troubleshoot",
        "kill",
        "autostart",
        "stop-autostart",
        "pause",
        "resume",
        "permissions",
        "mcp",
        "onboarding",
        "panel",
        "companion",
        "info",
        "update",
        "status",
        "stop",
        "start",
        "restart",
        "server",
        "setup",
    ):
        subcommand = cmd

    if subcommand:
        props["subcommand"] = subcommand

    # 2. Agent / Persona metadata (Allowlisted clean identifiers only)
    agent = getattr(args, "agent", None)
    if agent and isinstance(agent, str):
        clean_agent = agent.lower().strip()
        if re.match(r"^[a-z0-9_-]{1,32}$", clean_agent):
            props["agent"] = clean_agent

    # 3. Voice & Provider metadata (Allowlisted clean identifiers only)
    voice = getattr(args, "voice", None)
    if voice and isinstance(voice, str):
        clean_voice = voice.strip()
        if "/" not in clean_voice and "\\" not in clean_voice:
            props["voice"] = clean_voice[:40]

    provider = getattr(args, "provider", None)
    if provider and isinstance(provider, str):
        clean_provider = provider.strip().lower()
        if re.match(r"^[a-z0-9_-]{1,30}$", clean_provider):
            props["provider"] = clean_provider

    # 4. Safe scrubbed args/flags (Allowlisted flags only — ZERO user data/paths)
    flags = []
    flag_map = [
        ("dev", "--dev"),
        ("all", "--all"),
        ("silent", "--silent"),
        ("quiet", "--quiet"),
        ("json", "--json"),
        ("interactive", "--interactive"),
        ("benchmark", "--benchmark"),
        ("mic_loopback", "--mic"),
        ("loopback", "--loopback"),
        ("hearing", "--hearing"),
        ("feedback_loop", "--feedback-loop"),
        ("verify", "--verify"),
        ("check", "--check"),
        ("no_wait", "--no-wait"),
        ("no_qr", "--no-qr"),
        ("no_browser", "--no-browser"),
        ("claude", "--claude"),
        ("antigravity", "--antigravity"),
        ("mcp", "--mcp"),
        ("servers", "--servers"),
        ("daemons", "--daemons"),
        ("clipboard", "--clipboard"),
        ("no_synth", "--no-synth"),
        ("global_install", "--global"),
    ]
    for flag_attr, flag_name in flag_map:
        val = getattr(args, flag_attr, None)
        if val is True:
            flags.append(flag_name)

    if getattr(args, "inject", None) is False:
        flags.append("--no-inject")
    if getattr(args, "enter", None) is False:
        flags.append("--no-enter")

    props["args"] = flags
    props["flags"] = flags

    # 5. Command-specific safe enums
    if cmd == "hud" and hasattr(args, "state") and args.state:
        props["hud_state"] = str(args.state)

    if cmd in ("troubleshoot", "voice") and getattr(args, "fix", None):
        clean_fix = str(args.fix).strip().lower()
        if re.match(r"^[a-z0-9_-]{1,40}$", clean_fix):
            props["fix_target"] = clean_fix

    return props
