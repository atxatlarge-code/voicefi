"""
Argument parser definition for VoiceFi CLI interface.
Modularized from cli.py to keep the main entrypoint lightweight.
"""

import argparse
from typing import Optional

from voicefi import __version__
from voicefi.cli_format import VoiceFiArgumentParser, resolve_prog_name
from voicefi.config import VALID_GEMINI_LIVE_VOICES


def build_parser(prog: Optional[str] = None) -> VoiceFiArgumentParser:
    prog_name = prog or resolve_prog_name()
    parser = VoiceFiArgumentParser(
        prog=prog_name,
        description="VoiceFi: Give voice to your agents, and agency for your voice. The Universal Voice Layer for AI Agents, MCP, and macOS.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=str, default=None, help="Path to custom config.yaml")
    parser.add_argument(
        "-l",
        "--live",
        dest="root_live",
        action="store_true",
        help="Start Gemini 3.8 Live interactive full-duplex speech-to-speech studio",
    )

    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", help="Available subcommands"
    )

    # hook
    hook_p = subparsers.add_parser(
        "hook",
        aliases=["hooks"],
        help="Manage or run AI agent lifecycle hooks (Antigravity, Claude Code, Codex)",
    )
    hook_p.add_argument(
        "action",
        nargs="?",
        default=None,
        help="Hook management action (enable, disable, status, remove) or event name",
    )
    hook_p.add_argument(
        "extra_args", nargs="*", default=[], help="Additional hook event arguments or JSON payload"
    )
    hook_p.add_argument(
        "-a",
        "--agent",
        type=str,
        default="antigravity",
        help="Target agent name (antigravity, claude, codex)",
    )
    hook_p.add_argument(
        "-v",
        "--voice",
        type=str,
        default=None,
        help="Voice persona or provider voice to speak this hook with (e.g. Steffan, Ryan, Emma, Ava)",
    )
    hook_p.add_argument(
        "--enable", action="store_true", help="Enable agent lifecycle hooks in configuration"
    )
    hook_p.add_argument(
        "--disable", action="store_true", help="Disable agent lifecycle hooks in configuration"
    )
    hook_p.add_argument(
        "--status", action="store_true", help="Show hook installation and configuration status"
    )
    hook_p.add_argument(
        "--remove", action="store_true", help="Remove hook definitions from agent settings"
    )

    # speak
    speak_p = subparsers.add_parser("speak", help="Speak text aloud")
    speak_p.add_argument("text", nargs="+", help="Text to speak")
    speak_p.add_argument(
        "-a",
        "--agent",
        type=str,
        default=None,
        help="Agent profile to speak as (e.g. antigravity, claude, researcher, debugger)",
    )
    speak_p.add_argument("-v", "--voice", type=str, default=None, help="Voice name or ID override")
    speak_p.add_argument(
        "-p",
        "--provider",
        type=str,
        default=None,
        help="TTS provider override (mac_say, edge_tts, elevenlabs)",
    )
    speak_p.add_argument(
        "-r",
        "--rate",
        type=str,
        default=None,
        help="Speech rate / speed override (e.g. 75%%, 150, -25%%)",
    )
    speak_p.add_argument(
        "-s",
        "--speed",
        "--speed-talk",
        dest="speed",
        type=str,
        default=None,
        help="Speed talking multiplier or preset (e.g. 1.5x, turbo, 2.0x, fast)",
    )
    speak_p.add_argument(
        "--fast",
        action="store_true",
        help="Speak in fast speed talking mode (1.5x / 300 WPM)",
    )

    # setup
    setup_p = subparsers.add_parser(
        "setup",
        help="Auto-configure agent lifecycle hooks & MCP servers (Antigravity, Claude Code)",
    )
    setup_p.add_argument("--all", action="store_true", help="Setup all agents globally")
    setup_p.add_argument("--claude", action="store_true", help="Setup Claude Code")
    setup_p.add_argument("--antigravity", action="store_true", help="Setup Antigravity")
    setup_p.add_argument(
        "--mcp", action="store_true", help="Setup Model Context Protocol (MCP) server configuration"
    )
    setup_p.add_argument(
        "--dev", action="store_true", help="Link agent hooks to current repository local .venv"
    )
    setup_p.add_argument(
        "--remove-hooks",
        "--uninstall-hooks",
        dest="remove_hooks",
        action="store_true",
        help="Remove VoiceFi hooks from agent configurations",
    )

    # mcp
    mcp_p = subparsers.add_parser(
        "mcp", aliases=["mcp-server"], help="Start native Model Context Protocol (MCP) stdio server"
    )
    mcp_p.add_argument(
        "--test",
        "--check",
        "--ping",
        dest="test",
        action="store_true",
        help="Test live PostHog MCP Analytics event emission and connectivity",
    )
    mcp_p.add_argument(
        "--json",
        action="store_true",
        help="Output diagnostics in JSON format",
    )

    ob_p = subparsers.add_parser(
        "onboarding", help="Run interactive First-Time User Experience onboarding flow"
    )
    ob_p.set_defaults(
        func=lambda args: __import__("voicefi.onboarding", fromlist=[""]).run_onboarding()
    )

    # listen
    listen_p = subparsers.add_parser("listen", help="Listen from microphone and transcribe")
    listen_p.add_argument(
        "--to",
        choices=["active", "antigravity", "claude"],
        default="active",
        help="Target agent or app for zero-focus background IPC dispatch (default: active)",
    )
    listen_p.add_argument(
        "--no-inject",
        dest="inject",
        action="store_false",
        default=True,
        help="Do not inject into active app",
    )
    listen_p.add_argument(
        "--no-enter",
        dest="enter",
        action="store_false",
        default=True,
        help="Do not press Enter after pasting",
    )
    listen_p.add_argument(
        "-q", "--quiet", action="store_true", help="Disable audio feedback chimes"
    )

    # loop
    loop_p = subparsers.add_parser("loop", help="Start continuous voice loop")
    loop_p.add_argument("--no-inject", dest="inject", action="store_false", default=True)
    loop_p.add_argument("--no-enter", dest="enter", action="store_false", default=True)
    loop_p.add_argument("-q", "--quiet", action="store_true")

    # wake / wakeword / hey-viv
    wake_p = subparsers.add_parser(
        "wake",
        aliases=["wakeword", "hey-viv"],
        help="Run interactive 'Hey Viv' wake word listener and dispatcher",
    )
    wake_p.add_argument("--phrase", help="Override primary wake phrase (default: 'Hey Viv')")

    # tray / dev
    subparsers.add_parser("tray", help="Launch macOS menu bar companion")
    subparsers.add_parser(
        "dev", help="Launch in foreground dev mode with live console logs and auto-takeover"
    )

    # clean / purge
    clean_p = subparsers.add_parser(
        "clean",
        aliases=["purge", "reset-cache"],
        help="Clean stale Python bytecode, caches, locks, and servers",
    )
    clean_p.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Stop all background servers and clean all caches & locks",
    )
    clean_p.add_argument(
        "--dev",
        "-d",
        action="store_true",
        help="Clean caches, stop servers, and re-link hooks to local repository .venv",
    )
    clean_p.add_argument(
        "--servers",
        "--daemons",
        action="store_true",
        dest="servers",
        help="Stop and terminate running VoiceFi background servers",
    )

    # status / stop / start / restart shortcuts
    subparsers.add_parser(
        "status", help="Show VoiceFi server status, active devices, and port listeners"
    )
    subparsers.add_parser("stop", help="Stop VoiceFi background server and free port 5141")
    subparsers.add_parser("start", help="Start VoiceFi background server (LaunchAgent)")
    subparsers.add_parser("restart", help="Restart VoiceFi background server and reload config")

    # server / daemon / service / kill
    server_p = subparsers.add_parser(
        "server",
        aliases=["daemon", "service"],
        help="Inspect and manage background server, LaunchAgents, and port listeners",
    )
    server_p.add_argument(
        "server_action",
        nargs="?",
        default="status",
        choices=["status", "stop", "kill", "restart", "start", "reload"],
        help="Server action (default: status)",
    )
    subparsers.add_parser(
        "kill", help="Immediately stop all VoiceFi background servers and free port 5141"
    )

    # pause / resume
    subparsers.add_parser(
        "pause", help="Pause VoiceFi audio hooks and active turn-handoffs globally"
    )
    subparsers.add_parser(
        "resume", help="Resume VoiceFi audio hooks and active turn-handoffs globally"
    )
    subparsers.add_parser(
        "permissions", help="Check and open macOS Accessibility & Input Monitoring settings"
    )

    # autostart
    subparsers.add_parser(
        "autostart", help="Register macOS LaunchAgent to keep menu bar icon persistent"
    )
    subparsers.add_parser("stop-autostart", help="Remove macOS LaunchAgent autostart")

    # companion / remote / pair / rc
    comp_p = subparsers.add_parser(
        "companion",
        aliases=["remote", "pair", "rc", "RC"],
        help="Launch Web & Mobile Voice Companion (PWA & QR code)",
    )
    comp_p.add_argument(
        "action",
        nargs="?",
        default=None,
        help="Optional companion action or target view (e.g. 'sheet', 'spicewood')",
    )
    comp_p.add_argument(
        "--port", type=int, default=5141, help="Port to run companion server (default: 5141)"
    )
    comp_p.add_argument(
        "--host", type=str, default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)"
    )
    comp_p.add_argument("--no-qr", action="store_true", help="Do not print terminal QR code")
    comp_p.add_argument(
        "--open", action="store_true", help="Open local companion in default browser"
    )
    comp_p.add_argument(
        "--sheet",
        action="store_true",
        help="Open Spicewood Texas lead sheet directly in companion",
    )
    comp_p.add_argument(
        "--tunnel",
        action="store_true",
        help="Start trusted HTTPS Cloudflare tunnel for remote / mobile LTE/5G access anywhere",
    )

    # panel
    panel_p = subparsers.add_parser("panel", help="Launch interactive Voice Control Panel")
    panel_p.add_argument(
        "--port", type=int, default=5141, help="Port to run web control panel (default: 5141)"
    )
    panel_p.add_argument(
        "--no-browser", action="store_true", help="Do not open browser automatically"
    )
    panel_p.add_argument(
        "--claude", action="store_true", help="Directly open Claude Voice Contenders Studio"
    )

    # bar / prompt / quick
    bar_p = subparsers.add_parser(
        "bar",
        aliases=["prompt", "quick"],
        help="Launch or toggle native macOS Quick Prompt Bar (Control+Space)",
    )
    bar_p.add_argument(
        "text",
        nargs="*",
        default=None,
        help="Optional initial prompt text to populate in the bar",
    )

    # info
    subparsers.add_parser("info", help="Show system status and voices")

    # tier / pricing / trial
    subparsers.add_parser(
        "tier",
        aliases=["pricing", "trial", "plan"],
        help="Display active tier, 14-day free trial countdown, and pricing plans",
    )
    lic_p = subparsers.add_parser(
        "license", help="View license status or activate VoiceFi Pro license key"
    )
    lic_sub = lic_p.add_subparsers(
        dest="license_action", metavar="<action>", help="License action (status, activate)"
    )
    lic_sub.add_parser("status", help="Show active license and 14-day free trial status")
    lic_sub.add_parser(
        "where",
        aliases=["help", "find", "recover", "lost"],
        help="Where to find or recover your license key (Polar email, portal, or trial)",
    )
    lic_act = lic_sub.add_parser(
        "activate", aliases=["set", "apply"], help="Activate a VoiceFi Pro license key"
    )
    lic_act.add_argument("key", type=str, help="Pro license key (e.g. VF1-PRO-...)")
    lic_gen = lic_sub.add_parser(
        "generate",
        aliases=["create", "mint", "new"],
        help="Generate an unforgeable VoiceFi license key (requires admin key)",
    )
    lic_gen.add_argument("--tier", default="PRO", help="License tier (PRO, ORG, ENTERPRISE, VIP)")
    lic_gen.add_argument("--expires", default="PERP", help="Expiration (PERP or YYYYMMDD)")
    lic_gen.add_argument("--tag", default="TESTER", help="Recipient tag or promo name")

    # learn / learning (recursive phonetic and brevity self-learning)
    learn_p = subparsers.add_parser(
        "learn",
        aliases=["learning"],
        help="Inspect and manage recursive phonetic and brevity self-learning memory",
    )
    learn_sub = learn_p.add_subparsers(
        dest="learn_action", metavar="<action>", help="Learning action (status, scan, teach, reset)"
    )
    learn_sub.add_parser(
        "status", help="Show recursive phonetic memory and cognitive brevity metrics"
    )
    l_scan = learn_sub.add_parser(
        "scan", help="Scan active repository to index project symbols into phonetic memory"
    )
    l_scan.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Directory path to scan (defaults to current directory)",
    )
    l_teach = learn_sub.add_parser(
        "teach", help="Manually teach VoiceFi a spoken-to-canonical phonetic mapping"
    )
    l_teach.add_argument("spoken", type=str, help="Spoken phrase (e.g. 'wifi tier')")
    l_teach.add_argument("canonical", type=str, help="Canonical code / command (e.g. 'vifi tier')")
    l_test = learn_sub.add_parser(
        "test", help="Test and benchmark spoken turn summary distillation"
    )
    l_test.add_argument("text", type=str, help="Raw agent text or markdown output to distill")
    learn_sub.add_parser("reset", help="Reset learned phonetic and brevity memory files")

    # voice
    voice_p = subparsers.add_parser("voice", help="Manage and audition agent voices")
    voice_sub = voice_p.add_subparsers(dest="voice_action", metavar="<action>", help="Voice action")

    # voice download-ava (Apple Ava Premium 0ms offline speech)
    v_ava = voice_sub.add_parser(
        "download-ava",
        aliases=["install-ava", "setup-ava", "get-ava", "download_ava", "setup-offline", "offline"],
        help="Download and configure Apple's Ava (Premium) neural voice for 0ms offline speech",
    )
    v_ava.add_argument(
        "--check", action="store_true", help="Check if Ava is installed without opening settings"
    )
    v_ava.add_argument(
        "--no-wait",
        "--no-poll",
        dest="no_wait",
        action="store_true",
        help="Open System Settings without waiting loop",
    )
    v_ava.add_argument(
        "--timeout", type=int, default=300, help="Polling timeout in seconds (default: 300)"
    )
    v_ava.add_argument(
        "-s", "--silent", "-q", "--quiet", dest="silent", action="store_true", help="Silent mode"
    )

    # voice panel
    vp_panel = voice_sub.add_parser("panel", help="Launch interactive Voice Control Panel")
    vp_panel.add_argument("--port", type=int, default=5141)
    vp_panel.add_argument("--no-browser", action="store_true")
    vp_panel.add_argument(
        "--claude", action="store_true", help="Directly open Claude Voice Contenders Studio"
    )

    # voice command
    vp_cmd = voice_sub.add_parser("command", help="Execute a natural voice command")
    vp_cmd.add_argument(
        "command_text",
        nargs="+",
        help="Command phrase to execute (e.g. 'audition Viv', 'switch to Aria')",
    )

    # voice list
    v_list = voice_sub.add_parser("list", help="List curated and system voices")
    v_list.add_argument(
        "--provider", type=str, default=None, help="Filter by provider (edge_tts, mac_say)"
    )
    v_list.add_argument("-a", "--all", action="store_true", help="Include uncurated system voices")

    # voice test
    v_test = voice_sub.add_parser(
        "test", help="Audition / test a single voice or run feedback loop"
    )
    v_test.add_argument(
        "voice",
        nargs="?",
        default=None,
        help="Voice name or ID (e.g. Viv, Christopher, Aria, en-US-AvaNeural)",
    )
    v_test.add_argument("-t", "--text", type=str, default=None, help="Custom text sample to speak")
    v_test.add_argument(
        "-s",
        "--silent",
        action="store_true",
        help="Silently test connection and speed without playing audio over speakers",
    )
    v_test.add_argument(
        "--phrase",
        type=str,
        default=None,
        choices=["greeting", "code_review", "qa_alert", "punctuation", "architecture"],
        help="Preset test phrase",
    )
    v_test.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    v_test.add_argument(
        "-r", "--rate", type=str, default=None, help="Speech rate / speed override (e.g. 75%%, 150)"
    )
    v_test.add_argument(
        "-m",
        "--mic",
        "--mic-loopback",
        dest="mic_loopback",
        action="store_true",
        help="Record and hear 3s microphone loopback test",
    )
    v_test.add_argument(
        "--hearing",
        "--hearing-test",
        dest="hearing",
        action="store_true",
        help="Hearing test: Speak test phrase and verify mic reception via STT",
    )
    v_test.add_argument(
        "--feedback-loop",
        "--loopback",
        dest="feedback_loop",
        action="store_true",
        help="Feedback Loop test: Speak aloud, capture via mic, transcribe, and send",
    )
    v_test.add_argument(
        "--no-send",
        "--dry-run",
        dest="no_send",
        action="store_true",
        help="Do not dispatch transcribed text to conversation",
    )
    v_test.add_argument(
        "-c",
        "--conv-id",
        "--cid",
        dest="conv_id",
        type=str,
        default=None,
        help="Target conversation ID for message delivery",
    )
    v_test.add_argument(
        "--verify",
        "--stt-loopback",
        dest="verify",
        action="store_true",
        help="Acoustic STT verification",
    )
    v_test.add_argument(
        "-b", "--benchmark", action="store_true", help="Benchmark latency of all curated voices"
    )
    v_test.add_argument("-a", "--all", action="store_true", help="Audition all curated personas")
    v_test.add_argument(
        "--hud",
        action="store_true",
        help="Display visual Dynamic Island HUD popup during test (default: headless)",
    )
    v_test.add_argument("--json", action="store_true", help="Output results in JSON format")

    # voice ping (silent connection, speed, and latency test)
    v_ping = voice_sub.add_parser(
        "ping",
        aliases=["check", "speed-test"],
        help="Silently test connection, latency, speed, and health of neural voices",
    )
    v_ping.add_argument(
        "voice",
        nargs="?",
        default=None,
        help="Voice name or ID to ping (e.g. Viv, Andrew, Christopher, Aria). Defaults to active voice.",
    )
    v_ping.add_argument(
        "-t", "--text", type=str, default=None, help="Custom text sample for speed synthesis test"
    )
    v_ping.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Number of pings to measure avg latency and jitter",
    )
    v_ping.add_argument(
        "-a", "--all", action="store_true", help="Ping and benchmark all curated personas"
    )
    v_ping.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    v_ping.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override")
    v_ping.add_argument("--json", action="store_true", help="Output ping results in JSON format")

    # ping top-level
    ping_p = subparsers.add_parser(
        "ping",
        aliases=["speed-test", "check-voice"],
        help="Silently test voice connection, latency, and throughput speed",
    )
    ping_p.add_argument(
        "voice", nargs="?", default=None, help="Voice name or ID to ping. Defaults to active voice."
    )
    ping_p.add_argument(
        "-t", "--text", type=str, default=None, help="Custom text sample for speed synthesis test"
    )
    ping_p.add_argument(
        "-n",
        "--count",
        type=int,
        default=1,
        help="Number of pings to measure avg latency and jitter",
    )
    ping_p.add_argument(
        "-a", "--all", action="store_true", help="Ping and benchmark all curated personas"
    )
    ping_p.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    ping_p.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override")
    ping_p.add_argument("--json", action="store_true", help="Output ping results in JSON format")

    # feedback-loop / proactive top-level
    fb_p = subparsers.add_parser(
        "feedback-loop",
        aliases=[
            "proactive",
            "proactive-feedback-loop",
            "proactive-listening",
            "feedback_loop",
            "loopback",
            "voice-loop",
        ],
        help="Manage ProActive Feedback Loop (on/off/status) or run acoustic verification test",
    )
    fb_p.add_argument("voice", nargs="?", default="Aria", help="Voice to speak")
    fb_p.add_argument(
        "-t",
        "--text",
        type=str,
        default="This is a test feedback loop",
        help="Phrase to speak and verify",
    )
    fb_p.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    fb_p.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override")
    fb_p.add_argument(
        "--no-send",
        "--dry-run",
        dest="no_send",
        action="store_true",
        help="Do not dispatch transcribed text to conversation",
    )
    fb_p.add_argument(
        "-c",
        "--conv-id",
        "--cid",
        dest="conv_id",
        type=str,
        default=None,
        help="Target conversation ID for message delivery",
    )
    fb_p.add_argument(
        "--hud", action="store_true", help="Display visual Dynamic Island HUD during verification"
    )
    fb_p.add_argument(
        "--json", action="store_true", help="Output feedback loop results in JSON format"
    )

    # hearing-test top-level
    ht_p = subparsers.add_parser(
        "hearing-test",
        aliases=["hearing"],
        help="Hearing test: Speak phrase and verify microphone & STT reception from speakers",
    )
    ht_p.add_argument("voice", nargs="?", default="Aria", help="Voice to test")
    ht_p.add_argument(
        "-t",
        "--text",
        type=str,
        default="This is a hearing test",
        help="Phrase to speak and verify",
    )
    ht_p.add_argument("-p", "--provider", type=str, default=None, help="TTS provider override")
    ht_p.add_argument("-r", "--rate", type=str, default=None, help="Speech rate / speed override")
    ht_p.add_argument(
        "--hud", action="store_true", help="Display visual Dynamic Island HUD during verification"
    )
    ht_p.add_argument(
        "--json", action="store_true", help="Output hearing test results in JSON format"
    )

    # barge-in top-level
    barge_p = subparsers.add_parser(
        "barge-in",
        aliases=["test-barge-in", "barge_in"],
        help="Live Active Barge-In test: speaks phrase aloud and tests mid-sentence voice interruption with Silero VAD",
    )
    barge_p.add_argument("voice", nargs="?", default=None, help="Voice to speak during test")
    barge_p.add_argument(
        "-t", "--text", type=str, default=None, help="Phrase to speak and interrupt"
    )

    # voice troubleshoot
    v_tr = voice_sub.add_parser(
        "troubleshoot", help="Run comprehensive audio & voice troubleshooting diagnostic suite"
    )
    v_tr.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive guided troubleshooting wizard",
    )
    v_tr.add_argument(
        "-m",
        "--mic",
        "--loopback",
        dest="loopback",
        action="store_true",
        help="Microphone loopback test",
    )
    v_tr.add_argument("--hearing", action="store_true", help="Run acoustic hearing test")
    v_tr.add_argument("--verify", action="store_true", help="Acoustic STT verification")
    v_tr.add_argument(
        "-b",
        "--benchmark",
        "--tts-only",
        dest="benchmark",
        action="store_true",
        help="Benchmark TTS latency only",
    )
    v_tr.add_argument("-v", "--voice", type=str, default=None, help="Specific voice to test")
    v_tr.add_argument(
        "--hud",
        action="store_true",
        help="Display visual Dynamic Island HUD popup during test (default: headless)",
    )
    v_tr.add_argument(
        "--fix",
        type=str,
        default=None,
        help="Apply auto-fix (reset_defaults, set_offline_fallback, calibrate_mic)",
    )
    v_tr.add_argument("--json", action="store_true", help="Output diagnostic report in JSON")

    # troubleshoot top-level
    tr_top = subparsers.add_parser(
        "troubleshoot",
        aliases=["test"],
        help="Run comprehensive audio & voice troubleshooting diagnostic suite",
    )
    tr_top.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Run interactive guided troubleshooting wizard",
    )
    tr_top.add_argument(
        "-m",
        "--mic",
        "--loopback",
        dest="loopback",
        action="store_true",
        help="Microphone loopback test",
    )
    tr_top.add_argument(
        "-b",
        "--benchmark",
        "--tts-only",
        dest="benchmark",
        action="store_true",
        help="Benchmark TTS latency only",
    )
    tr_top.add_argument("-v", "--voice", type=str, default=None, help="Specific voice to test")
    tr_top.add_argument(
        "--hud",
        action="store_true",
        help="Display visual Dynamic Island HUD popup during test (default: headless)",
    )
    tr_top.add_argument("--fix", type=str, default=None, help="Apply auto-fix")
    tr_top.add_argument("--json", action="store_true", help="Output diagnostic report in JSON")

    # voice audition
    voice_sub.add_parser("audition", help="Play live multi-agent voice showcase across speakers")

    # vad top-level
    vad_p = subparsers.add_parser("vad", help="Open the Expert VAD & Acoustic Inspector Panel")

    # voice rate / speed
    v_rate = voice_sub.add_parser(
        "rate", help="Get or set speech rate / speed (e.g. 75%%, 150, faster, slower)"
    )
    v_rate.add_argument(
        "value",
        nargs="?",
        default=None,
        help="Speed value (e.g. '75%%', '150', 'faster', 'slower', 'reset')",
    )
    v_rate.add_argument(
        "-a", "--agent", type=str, default=None, help="Target specific agent or subagent"
    )

    v_speed = voice_sub.add_parser("speed", help="Alias for 'vg voice rate'")
    v_speed.add_argument(
        "value",
        nargs="?",
        default=None,
        help="Speed value (e.g. '75%%', '150', 'faster', 'slower', 'reset')",
    )
    v_speed.add_argument(
        "-a", "--agent", type=str, default=None, help="Target specific agent or subagent"
    )

    v_st = voice_sub.add_parser(
        "speed-talk",
        aliases=["speedtalk", "speed_talk"],
        help="Enable, configure, audition, or benchmark Speed Talking (1.25x - 3.0x)",
    )
    v_st.add_argument(
        "action",
        nargs="?",
        default=None,
        help="Action or preset (on, off, set, turbo, fast, sonic, warp, test, ramp, demo, stats)",
    )
    v_st.add_argument(
        "preset_or_multiplier",
        nargs="?",
        default=None,
        help="Speed preset or multiplier (e.g. 'turbo', '1.75x', '2.0')",
    )
    v_st.add_argument("-t", "--text", type=str, default=None, help="Custom text to speak")

    # voice set
    v_set = voice_sub.add_parser(
        "set",
        help="Assign a voice to an agent, project, or subagent and play acoustic confirmation",
    )
    v_set.add_argument(
        "agent",
        type=str,
        help="Agent, project, or voice name (e.g. viv, antigravity, claude, lienlogic, default)",
    )
    v_set.add_argument(
        "voice",
        type=str,
        nargs="?",
        default=None,
        help="Voice name or ID (e.g. Viv, Guy, Christopher, Aria) if agent or project was specified first",
    )
    v_set.add_argument(
        "--project",
        action="store_true",
        help="Assign as project-specific voice profile",
    )
    v_set.add_argument(
        "-t", "--text", type=str, default=None, help="Custom confirmation phrase to speak"
    )
    v_set.add_argument(
        "-q",
        "--quiet",
        "--silent",
        dest="quiet",
        action="store_true",
        help="Silently assign voice without playing confirmation speech",
    )
    v_set.add_argument("-p", "--provider", type=str, default=None)
    v_set.add_argument(
        "-r", "--rate", type=str, default=None, help="Speech rate / speed (e.g. 75%%, 150, -25%%)"
    )

    # voice get
    voice_sub.add_parser("get", help="Show active voice mappings")

    # voice clone
    v_clone = voice_sub.add_parser(
        "clone",
        aliases=["train"],
        help="Clone, record, import, test, and manage custom voice profiles",
    )
    v_clone.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Name for the custom cloned voice (or action: list, delete, test)",
    )
    v_clone.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target voice name when action is specified (e.g. 'vifi voice clone delete MyVoice')",
    )
    v_clone.add_argument(
        "--audio",
        "-a",
        nargs="+",
        dest="audio_files",
        default=None,
        help="Audio file(s) to clone from (.wav, .mp3, .m4a)",
    )
    v_clone.add_argument(
        "--record",
        "-r",
        action="store_true",
        help="Launch interactive 4-prompt microphone recording wizard",
    )
    v_clone.add_argument(
        "--assign",
        type=str,
        default=None,
        help="Assign directly to agent upon completion (e.g. antigravity, claude)",
    )
    v_clone.add_argument(
        "--provider",
        type=str,
        default="auto",
        choices=["auto", "kokoro", "local_clone", "f5_tts", "elevenlabs", "edge_tts"],
        help="TTS engine provider for voice cloning",
    )
    v_clone.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    v_clone.add_argument("--description", type=str, default="", help="Voice description")
    v_clone.add_argument("-l", "--list", action="store_true", help="List all custom cloned voices")
    v_clone.add_argument("-t", "--test", action="store_true", help="Audition the cloned voice")
    v_clone.add_argument("--text", type=str, default=None, help="Sample text to speak for audition")
    v_clone.add_argument(
        "-d", "--delete", action="store_true", help="Delete a cloned voice profile"
    )

    # clone
    clone_p = subparsers.add_parser("clone", help="Train and manage custom voice clones")
    clone_sub = clone_p.add_subparsers(dest="clone_action", metavar="<action>", help="Clone action")

    # clone record
    c_rec = clone_sub.add_parser("record", help="Record voice samples via mic wizard")
    c_rec.add_argument("name", type=str, help="Name for the custom cloned voice")
    c_rec.add_argument(
        "--provider",
        type=str,
        default="auto",
        choices=["auto", "f5_tts", "elevenlabs", "edge_tts"],
        help="TTS engine provider for voice cloning",
    )
    c_rec.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    c_rec.add_argument("--description", type=str, default="", help="Voice description")
    c_rec.add_argument(
        "--assign", type=str, default=None, help="Assign directly to agent upon completion"
    )

    # clone import
    c_imp = clone_sub.add_parser("import", help="Train voice from existing audio files")
    c_imp.add_argument("name", type=str, help="Name for the custom cloned voice")
    c_imp.add_argument("files", nargs="+", help="Audio files (.wav, .mp3, .m4a)")
    c_imp.add_argument(
        "--provider",
        type=str,
        default="auto",
        choices=["auto", "f5_tts", "elevenlabs", "edge_tts"],
        help="TTS engine provider for voice cloning",
    )
    c_imp.add_argument("--api-key", type=str, default=None, help="ElevenLabs API key (optional)")
    c_imp.add_argument("--description", type=str, default="", help="Voice description")
    c_imp.add_argument(
        "--assign", type=str, default=None, help="Assign directly to agent upon completion"
    )

    # clone studio
    clone_sub.add_parser(
        "studio", help="Launch local open-source voice cloning web studio (F5-TTS)"
    )

    # clone list
    clone_sub.add_parser("list", help="List all custom trained voices")

    # clone test
    c_test = clone_sub.add_parser("test", help="Audition / test a custom cloned voice")
    c_test.add_argument("name", type=str, help="Name of custom voice to audition")
    c_test.add_argument("-t", "--text", type=str, default=None, help="Text to speak")

    # clone assign
    c_assign = clone_sub.add_parser("assign", help="Assign cloned voice to an agent")
    c_assign.add_argument("name", type=str, help="Name of custom voice")
    c_assign.add_argument(
        "agent", type=str, help="Target agent (antigravity, claude, researcher, debugger, default)"
    )

    # clone delete
    c_del = clone_sub.add_parser("delete", help="Delete a cloned voice profile")
    c_del.add_argument("name", type=str, help="Name of voice to delete")
    c_del.add_argument(
        "--from-provider", action="store_true", help="Also delete from ElevenLabs API"
    )

    # clone prompt
    c_prompt = clone_sub.add_parser("prompt", help="View AI persona style prompt for cloned voice")
    c_prompt.add_argument("name", type=str, help="Name of custom voice")

    # feedback
    fb_p = subparsers.add_parser("feedback", help="Submit feedback, bug reports, or requests")
    fb_sub = fb_p.add_subparsers(dest="feedback_action", metavar="<action>", help="Feedback action")

    fb_submit = fb_sub.add_parser("submit", help="Submit feedback or bug report")
    fb_submit.add_argument("title", nargs="+", help="Feedback title or summary")
    fb_submit.add_argument("-d", "--details", type=str, default="", help="Detailed explanation")
    fb_submit.add_argument(
        "-c",
        "--category",
        type=str,
        default="general",
        choices=["bug", "feature", "voice_quality", "latency", "general"],
    )
    fb_submit.add_argument("--agent-id", type=str, default=None, help="Submitting agent name")
    fb_submit.add_argument(
        "--no-diagnostics", action="store_true", help="Exclude environment diagnostics"
    )

    fb_list = fb_sub.add_parser("list", help="List recent feedback submissions")
    fb_list.add_argument("-n", "--limit", type=int, default=10)

    # memo / buffer
    memo_p = subparsers.add_parser(
        "memo",
        aliases=["buffer"],
        help="Voice memo buffer: capture long rambles & synthesize to code",
    )
    memo_sub = memo_p.add_subparsers(
        dest="memo_action", metavar="<action>", help="Voice memo action"
    )

    # memo record
    m_rec = memo_sub.add_parser(
        "record", help="Record a 2-5 min voice memo with elegant countdown timer"
    )
    m_rec.add_argument(
        "-d",
        "--duration",
        type=str,
        default=None,
        help="Target recording duration (e.g. '3m', '5m', '180')",
    )
    m_rec.add_argument("-t", "--title", type=str, default=None, help="Title for the voice memo")
    m_rec.add_argument(
        "-o", "--out", type=str, default=None, help="Export synthesized plan to markdown file"
    )
    m_rec.add_argument(
        "-c", "--clipboard", action="store_true", help="Copy synthesized plan to clipboard"
    )
    m_rec.add_argument("--no-synth", action="store_true", help="Skip automatic thought synthesis")

    # memo synth
    m_synth = memo_sub.add_parser(
        "synth",
        aliases=["synthesize"],
        help="Synthesize stream-of-consciousness thoughts into code plan",
    )
    m_synth.add_argument("memo_id", nargs="?", default=None, help="Memo ID to synthesize")
    m_synth.add_argument(
        "-t", "--text", nargs="+", default=None, help="Raw speech text to synthesize"
    )
    m_synth.add_argument(
        "-f", "--file", type=str, default=None, help="Text or transcript file to synthesize"
    )
    m_synth.add_argument("--title", type=str, default=None, help="Custom title for generated plan")
    m_synth.add_argument(
        "-o", "--out", type=str, default=None, help="Export path for generated markdown"
    )
    m_synth.add_argument(
        "-c", "--clipboard", action="store_true", help="Copy generated plan to clipboard"
    )

    # memo list
    m_list = memo_sub.add_parser("list", help="List stored voice memos and brain dumps")
    m_list.add_argument("-n", "--limit", type=int, default=20, help="Max memos to list")

    # memo show
    m_show = memo_sub.add_parser("show", help="Display full synthesized plan or transcript")
    m_show.add_argument("memo_id", type=str, help="Memo ID")
    m_show.add_argument(
        "--transcript", dest="transcript_only", action="store_true", help="Show raw transcript only"
    )
    m_show.add_argument(
        "--diagram", dest="diagram_only", action="store_true", help="Show Mermaid diagram only"
    )
    m_show.add_argument(
        "--checklist", dest="checklist_only", action="store_true", help="Show PR checklist only"
    )

    # memo export
    m_exp = memo_sub.add_parser("export", help="Export synthesized plan to markdown or clipboard")
    m_exp.add_argument("memo_id", type=str, help="Memo ID to export")
    m_exp.add_argument("-o", "--out", type=str, default=None, help="Output markdown file path")
    m_exp.add_argument("-c", "--clipboard", action="store_true", help="Copy to clipboard")

    # memo import
    m_imp = memo_sub.add_parser("import", help="Import an audio recording or text note")
    m_imp.add_argument("file", type=str, help="Path to audio file (.wav, .mp3, .m4a) or text file")
    m_imp.add_argument("-t", "--title", type=str, default=None, help="Title for the imported memo")

    # memo delete
    m_del = memo_sub.add_parser("delete", help="Delete a stored voice memo")
    m_del.add_argument("memo_id", type=str, help="Memo ID to delete")

    # ambient listener & proactive meeting co-pilot
    amb_p = subparsers.add_parser(
        "ambient",
        aliases=["meeting"],
        help="ProActive Meeting Assistant & ambient background co-pilot",
    )
    amb_sub = amb_p.add_subparsers(
        dest="ambient_action",
        metavar="<action>",
        help="Meeting / Ambient action (start, stop, status, list, show)",
    )

    amb_start = amb_sub.add_parser("start", help="Start background meeting assistant session")
    amb_start.add_argument(
        "-t", "--title", type=str, default=None, help="Title for the meeting session"
    )
    amb_start.add_argument(
        "-o", "--output", type=str, default=None, help="Custom output markdown file path"
    )
    amb_start.add_argument("-s", "--speaker", type=str, default=None, help="Primary speaker name")
    amb_start.add_argument(
        "--source", choices=["mic", "loopback"], default="mic", help="Audio capture source"
    )
    amb_start.add_argument(
        "--auto-execute",
        action="store_true",
        default=True,
        help="Auto-execute detected Linear tickets, Slack updates, branch scaffolds",
    )
    amb_start.add_argument(
        "--no-auto-execute",
        dest="auto_execute",
        action="store_false",
        help="Stage action items without auto-executing",
    )

    amb_sub.add_parser("stop", help="Finalize active meeting session and save notes")
    amb_sub.add_parser("status", help="Show active meeting assistant status and action logs")
    amb_sub.add_parser("list", help="List saved meeting notes and sessions")

    amb_show = amb_sub.add_parser("show", help="Display full meeting notes")
    amb_show.add_argument(
        "target", nargs="?", default="latest", help="Meeting ID, keyword, or 'latest'"
    )

    amb_test = amb_sub.add_parser(
        "test",
        aliases=["simulate"],
        help="Run comprehensive automated QA simulation or interactive utterance tester",
    )
    amb_test.add_argument(
        "-i", "--interactive", action="store_true", help="Launch interactive utterance tester"
    )

    # STT biasing & phonetic normalizer
    bias_p = subparsers.add_parser(
        "bias", help="Inspect active STT vocabulary biasing or test phonetic normalization"
    )
    bias_p.add_argument("text", nargs="*", default=None, help="Spoken developer input to normalize")

    # obsidian
    obs_p = subparsers.add_parser(
        "obsidian", help="Manage and install VoiceFi plugin for Obsidian vaults"
    )
    obs_sub = obs_p.add_subparsers(dest="obsidian_action", metavar="<action>")
    inst_p = obs_sub.add_parser(
        "install", help="Install and enable VoiceFi plugin into Obsidian vault(s)"
    )
    inst_p.add_argument(
        "-v", "--vault", type=str, default=None, help="Target specific Obsidian vault directory"
    )
    inst_p.add_argument(
        "-a", "--all", action="store_true", help="Install into all registered vaults"
    )
    obs_sub.add_parser("list", help="List registered Obsidian vaults on this machine")
    obs_sub.add_parser(
        "status", help="Show Obsidian installation, vault discovery, and daily note status"
    )
    obs_sub.add_parser(
        "today", help="Display today's daily note content from active Obsidian vault"
    )
    obs_cap_p = obs_sub.add_parser(
        "capture", help="Quick capture text directly into today's daily note"
    )
    obs_cap_p.add_argument(
        "text", nargs="*", default=None, help="Text to append to today's daily note"
    )
    obs_cap_p.add_argument(
        "-v", "--vault", type=str, default=None, help="Target specific Obsidian vault directory"
    )
    obs_launch_p = obs_sub.add_parser(
        "launch", help="Launch or pair AI agent (Antigravity or Claude Code) into vault"
    )
    obs_launch_p.add_argument(
        "--engine",
        choices=["antigravity", "claude"],
        default="antigravity",
        help="Agent engine to launch",
    )

    # capture (top-level shortcut for direct voice-to-vault)
    cap_top_p = subparsers.add_parser(
        "capture", help="Direct voice or text capture into today's Obsidian daily note"
    )
    cap_top_p.add_argument(
        "text", nargs="*", default=None, help="Text to append to today's daily note"
    )
    cap_top_p.add_argument(
        "-v", "--vault", type=str, default=None, help="Target specific Obsidian vault directory"
    )

    # hud
    hud_p = subparsers.add_parser(
        "hud", help="Control, configure, and debug Unified Dynamic Island HUD"
    )
    hud_sub = hud_p.add_subparsers(
        dest="hud_action",
        metavar="<action>",
        help="HUD action (open, close, reset, debug, config, test, show, on, off, status, persistent, auto-send)",
    )
    hud_sub.add_parser(
        "open", aliases=["start", "launch"], help="Open and show persistent Dynamic Island HUD"
    )
    hud_sub.add_parser("close", aliases=["stop", "hide"], help="Close and hide Dynamic Island HUD")
    hud_sub.add_parser("on", aliases=["enable"], help="Enable and show persistent HUD")
    hud_sub.add_parser("off", aliases=["disable"], help="Disable and hide HUD")
    hud_sub.add_parser(
        "reset",
        aliases=["reset-position"],
        help="Reset HUD position to default bottom-right anchor above lower bar",
    )
    hud_sub.add_parser(
        "debug",
        help="Launch interactive terminal HUD Debug Studio with real-time keystroke controls",
    )
    hud_sub.add_parser("test", help="Run automated 6-state HUD showcase")
    hud_sub.add_parser("status", help="Display current HUD status and active settings")

    cfg_p = hud_sub.add_parser("config", help="View or update HUD configuration")
    cfg_p.add_argument(
        "--enabled",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Enable/disable HUD",
    )
    cfg_p.add_argument(
        "--persistent",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Enable/disable persistent resting pill",
    )
    cfg_p.add_argument(
        "--fullscreen-overlay",
        dest="fullscreen_overlay",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Always stay on top of full-screen games/apps",
    )
    cfg_p.add_argument(
        "--auto-send",
        dest="auto_send",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Enable instant auto-send or review mode",
    )
    cfg_p.add_argument(
        "--live-transcript",
        dest="live_transcript",
        type=str,
        default=None,
        choices=["true", "false", "on", "off"],
        help="Stream live transcription typing",
    )
    cfg_p.add_argument(
        "--position",
        type=str,
        default=None,
        choices=["bottom_right", "top_center", "top_right", "top_left", "bottom_center"],
        help="HUD screen position",
    )
    cfg_p.add_argument(
        "--linger", type=float, default=None, help="Linger seconds after done/speaking"
    )

    show_p = hud_sub.add_parser("show", help="Display specific HUD state")
    show_p.add_argument(
        "--state",
        type=str,
        default="idle",
        choices=["idle", "thinking", "working", "speaking", "listening", "editing"],
        help="Target state",
    )
    show_p.add_argument("--text", type=str, default="", help="Custom subtitle / transcription text")
    show_p.add_argument("--duration", type=float, default=4.0, help="Display duration in seconds")

    pers_p = hud_sub.add_parser("persistent", help="Toggle or set persistent HUD mode")
    pers_p.add_argument(
        "persistent_state",
        nargs="?",
        default="toggle",
        choices=["on", "off", "toggle", "status"],
        help="Enable/disable persistent HUD",
    )

    fs_p = hud_sub.add_parser(
        "fullscreen",
        help="Toggle or set full-screen overlay mode (always on top of full screen apps/games)",
    )
    fs_p.add_argument(
        "fullscreen_state",
        nargs="?",
        default="toggle",
        choices=["on", "off", "toggle", "status"],
        help="Enable/disable full screen overlay",
    )

    as_p = hud_sub.add_parser("auto-send", help="Toggle or set auto-send prompt mode")
    as_p.add_argument(
        "auto_send_state",
        nargs="?",
        default="toggle",
        choices=["on", "off", "toggle", "status"],
        help="Enable/disable auto-send mode",
    )

    # new conversation
    new_p = subparsers.add_parser(
        "new", aliases=["new-conversation"], help="Start a new AI conversation with connected tools"
    )
    new_p.add_argument("prompt", nargs="*", default=["Hello"], help="Initial prompt message")
    new_p.add_argument("-t", "--title", type=str, default=None, help="Custom title")
    new_p.add_argument(
        "-m",
        "--model",
        type=str,
        default=None,
        choices=["flash_lite", "flash", "pro"],
        help="Model selection",
    )

    # update / upgrade
    up_p = subparsers.add_parser(
        "update", aliases=["upgrade"], help="Check for and install latest VoiceFi updates"
    )
    up_p.add_argument("--check", action="store_true", help="Check for updates without installing")
    up_p.add_argument("--repo", default=None, help="Custom git repository URL to upgrade from")

    # download-ava top-level (Apple Ava Premium 0ms offline speech)
    ava_top = subparsers.add_parser(
        "download-ava",
        aliases=["install-ava", "setup-ava", "get-ava", "setup-offline", "offline-ava"],
        help="Download and configure Apple's Ava (Premium) neural voice for 0ms offline speech",
    )
    ava_top.add_argument(
        "--check", action="store_true", help="Check if Ava is installed without opening settings"
    )
    ava_top.add_argument(
        "--no-wait",
        "--no-poll",
        dest="no_wait",
        action="store_true",
        help="Open System Settings without waiting loop",
    )
    ava_top.add_argument(
        "--timeout", type=int, default=300, help="Polling timeout in seconds (default: 300)"
    )
    ava_top.add_argument(
        "-s", "--silent", "-q", "--quiet", dest="silent", action="store_true", help="Silent mode"
    )

    # stats / analytics / insights
    stats_p = subparsers.add_parser(
        "stats",
        aliases=["analytics", "insights"],
        help="View local developer activity, tool usage, time saved, and acoustic latency benchmarks",
    )
    stats_p.add_argument(
        "-d", "--days", type=int, default=7, help="Number of days to analyze (default: 7)"
    )
    stats_p.add_argument("--today", action="store_true", help="Show only today's activity")
    stats_p.add_argument("--all", action="store_true", help="Show all-time activity")
    stats_p.add_argument(
        "--export",
        choices=["json", "csv"],
        default=None,
        help="Export local analytics event log as JSON or CSV",
    )
    stats_p.add_argument(
        "--clean",
        type=int,
        nargs="?",
        const=30,
        default=None,
        help="Purge local records older than N days (default: 30)",
    )
    stats_p.add_argument(
        "--reset",
        action="store_true",
        help="Completely wipe local analytics database (~/.voicefi/analytics.db)",
    )
    stats_p.add_argument(
        "--force", action="store_true", help="Bypass confirmation prompt for reset"
    )

    # speed-talk top-level
    speed_talk_p = subparsers.add_parser(
        "speed-talk",
        aliases=["speedtalk", "speed_talk", "fast", "turbo"],
        help="Enable, configure, audition, or benchmark Speed Talking (1.25x - 3.0x)",
    )
    speed_talk_p.add_argument(
        "action",
        nargs="?",
        default=None,
        help="Action or preset (on, off, set, turbo, fast, sonic, warp, test, ramp, demo, stats, list)",
    )
    speed_talk_p.add_argument(
        "preset_or_multiplier",
        nargs="?",
        default=None,
        help="Speed preset or multiplier (e.g. 'turbo', '1.75x', '2.0')",
    )
    speed_talk_p.add_argument("-t", "--text", type=str, default=None, help="Custom text to speak")
    speed_talk_p.add_argument(
        "--on", "--enable", dest="enable", action="store_true", help="Enable speed talking"
    )
    speed_talk_p.add_argument(
        "--off", "--disable", dest="disable", action="store_true", help="Disable speed talking"
    )
    speed_talk_p.add_argument(
        "--stats", action="store_true", help="Show speed talking time saved metrics"
    )
    speed_talk_p.add_argument(
        "--demo", action="store_true", help="Run multi-speed escalating showcase"
    )
    speed_talk_p.add_argument("--ramp", action="store_true", help="Audition dynamic speed ramping")
    speed_talk_p.add_argument(
        "-s",
        "--silent",
        "-q",
        "--quiet",
        dest="silent",
        action="store_true",
        help="Silent mode without audio playback",
    )

    # send / dispatch
    send_p = subparsers.add_parser(
        "send",
        aliases=["dispatch"],
        help="Send message/task across agents or peer Macs on LAN (Antigravity ↔ Claude Code ↔ Peer Macs)",
    )
    send_p.add_argument("text", nargs="+", help="Message or prompt to send")
    send_p.add_argument(
        "--to",
        type=str,
        default="claude",
        help="Target agent engine (claude, antigravity, gemini) or peer Mac name/IP (e.g. mba, pro, 192.168.1.50)",
    )
    send_p.add_argument(
        "--engine",
        type=str,
        default="auto",
        choices=["auto", "antigravity", "claude", "gemini", "chatgpt"],
        help="Target agent engine on remote peer Mac (default: auto)",
    )

    # peers / network discovery
    peers_p = subparsers.add_parser(
        "peers",
        aliases=["peer", "discover"],
        help="Discover VoiceFi instances and active AI coding agents across local Wi-Fi / LAN",
    )
    peers_p.add_argument(
        "--port", type=int, default=5141, help="Peer discovery port (default: 5141)"
    )

    # vandelay industries / import export
    vandelay_p = subparsers.add_parser(
        "vandelay",
        help="Vandelay Industries: Importers & Exporters of fine code, prompts & clipboards across Macs",
    )
    vandelay_p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "import", "in", "export", "out"],
        help="Vandelay action (list, import, export)",
    )
    vandelay_p.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target peer Mac name or IP (e.g. 'mba', 'pro', '192.168.1.80')",
    )

    # clip / clipboard sync
    clip_p = subparsers.add_parser(
        "clip",
        aliases=["clipboard"],
        help="Push or pull clipboard snippets across peer Macs on local Wi-Fi",
    )
    clip_p.add_argument(
        "action",
        choices=["push", "pull", "get", "send", "set"],
        help="Clipboard action: 'push' (send to remote Mac) or 'pull' (fetch from remote Mac)",
    )
    clip_p.add_argument(
        "target",
        help="Target peer Mac name or IP (e.g. 'mba', 'jakes-mbp', '192.168.1.80')",
    )
    send_p.add_argument(
        "--conv-id",
        "--id",
        dest="conv_id",
        type=str,
        default=None,
        help="Target conversation ID (default: active conversation)",
    )
    send_p.add_argument(
        "--reply", action="store_true", help="Reply directly to the originating conversation ID"
    )
    send_p.add_argument(
        "--from-conv-id",
        "--from",
        dest="from_conv_id",
        type=str,
        default=None,
        help="Originating conversation ID",
    )
    send_p.add_argument(
        "--from-engine", type=str, default="antigravity", help="Originating agent engine"
    )
    send_p.add_argument("--title", type=str, default=None, help="Message title / heading")
    send_p.add_argument(
        "--sender",
        dest="sender_name",
        type=str,
        default=None,
        help="Sender attribution (e.g. Claude, Antigravity)",
    )
    send_p.add_argument(
        "--no-envelope", action="store_true", help="Do not include provenance metadata header"
    )
    send_p.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="Execute via background headless CLI without window focus changes",
    )
    send_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate dispatch without sending to target agent or peer",
    )

    # duel / banter
    duel_p = subparsers.add_parser(
        "duel",
        aliases=["banter", "acoustic-test"],
        help="Run acoustic banter & voice benchmark test (Ava ↔ Steffan personas)",
    )
    duel_p.add_argument("--turns", type=int, default=3, help="Number of joke turns (default: 3)")
    duel_p.add_argument("--topic", type=str, default="programming jokes", help="Duel topic")
    duel_p.add_argument(
        "--live", action="store_true", help="Live dispatch prompts to Claude Code terminal session"
    )

    # fx / audio effects
    fx_p = subparsers.add_parser(
        "fx",
        aliases=["voice-fx", "effects"],
        help="Transform voice audio using studio DSP effects (radio announcer, podcast, monster, etc.)",
    )
    fx_p.add_argument(
        "input", nargs="?", default=None, help="Input audio file path or 'list' to show presets"
    )
    fx_p.add_argument(
        "-p",
        "--preset",
        default="radio_announcer",
        help="Voice effect preset (radio_announcer, studio_podcast, stadium_announcer, am_radio, cyber_robot, deep_monster, helium_chipmunk, ethereal_space)",
    )
    fx_p.add_argument(
        "-o", "--output", default=None, help="Output master audio file path (.mp3, .wav, .m4a)"
    )

    # reel / video reel compiler
    reel_p = subparsers.add_parser(
        "reel",
        aliases=["video", "compile-reel"],
        help="Compile multi-format social video reels (9:16, 1:1, 4:5, 16:9)",
    )
    reel_p.add_argument("input", nargs="?", default=None, help="Input master audio file path")
    reel_p.add_argument(
        "-f",
        "--format",
        default="9:16",
        choices=["9:16", "1:1", "4:5", "16:9"],
        help="Video aspect ratio preset",
    )
    reel_p.add_argument("-p", "--preset", default="classic_ai", help="Typography preset pairing")
    reel_p.add_argument(
        "-s", "--speaker", default="Radio Host", help="Speaker name / avatar attribution"
    )
    reel_p.add_argument(
        "--scale",
        "--font-scale",
        dest="font_scale",
        type=float,
        default=1.0,
        help="Typography sizing multiplier",
    )
    reel_p.add_argument("-o", "--output", default=None, help="Output MP4 file path")
    reel_p.add_argument(
        "--open", action="store_true", help="Automatically open video after compilation"
    )
    reel_p.add_argument(
        "--doc",
        "--documentary",
        action="store_true",
        help="Enable Documentary Mode (documentary broadcaster narration, Baskerville subtitles, BBC mastering)",
    )
    reel_p.add_argument(
        "--script", default=None, help="Narrative script text to synthesize in documentary mode"
    )
    reel_p.add_argument(
        "--persona",
        default="documentary_broadcaster",
        help="Voice persona for documentary narration (default: documentary_broadcaster)",
    )
    reel_p.add_argument(
        "--score",
        default="beatdrop",
        choices=["beatdrop", "classical", "none"],
        help="Soundtrack score style",
    )
    reel_p.add_argument(
        "--punchline", default=None, help="Punchline phrase for comedic dead-air tape-stop mute"
    )

    # trim / audio cutter
    trim_p = subparsers.add_parser(
        "trim",
        aliases=["cut", "slice"],
        help="Trim audio start and end timestamps with de-clicking fades",
    )
    trim_p.add_argument("input", nargs="?", default=None, help="Input audio file path")
    trim_p.add_argument(
        "--start", "-s", type=float, default=0.0, help="Start timestamp in seconds (default: 0.0)"
    )
    trim_p.add_argument(
        "--end",
        "-e",
        type=float,
        default=None,
        help="End timestamp in seconds (default: end of audio)",
    )
    trim_p.add_argument(
        "-o", "--output", default=None, help="Output trimmed audio file path (.mp3, .wav, .m4a)"
    )

    # sfx / sound cues
    sfx_p = subparsers.add_parser(
        "sfx",
        aliases=["sound"],
        help="Play comedy or dramatic audio cues (drum_smash, honk, sad_trombone, applause)",
    )
    sfx_p.add_argument(
        "name",
        nargs="?",
        default="drum_smash",
        help="Sound effect name (drum_smash, honk, sad_trombone, applause, boing, crickets, list)",
    )
    sfx_p.add_argument(
        "--volume", "-v", type=float, default=1.0, help="Playback volume (0.1 - 2.0)"
    )

    # bridge / ipc
    bridge_p = subparsers.add_parser(
        "bridge",
        aliases=["ipc-bridge", "ipc"],
        help="Run or manage VoiceFi Local IPC daemon bridge service",
    )
    bridge_p.add_argument(
        "--server", "-s", action="store_true", help="Run local IPC daemon socket server"
    )
    bridge_p.add_argument(
        "--socket",
        type=str,
        default=None,
        help="Path to Unix domain socket (default: /tmp/voicefi.sock)",
    )
    bridge_p.add_argument(
        "--ws-port", type=int, default=None, help="Fallback WebSocket port (default: 8765)"
    )
    bridge_p.add_argument(
        "-a", "--agent", type=str, default="Spark", help="Target agent identifier"
    )
    bridge_p.add_argument(
        "-p", "--persona", type=str, default=None, help="Voice persona (Viv, Christopher, etc.)"
    )

    # spark / gemini runner
    spark_p = subparsers.add_parser(
        "spark", help="Run Gemini Spark agent runner with voice bridge and turn-end hooks"
    )
    spark_p.add_argument("prompt", nargs="*", default=None, help="Optional prompt to execute once")
    spark_p.add_argument(
        "-p", "--persona", type=str, default=None, help="Spoken persona (Viv, Christopher, etc.)"
    )
    spark_p.add_argument("--socket", type=str, default=None, help="Path to Unix domain socket")

    # live / gemini 3.8 live runner
    live_p = subparsers.add_parser(
        "live",
        aliases=["comedy", "gemini-live"],
        help="Run real-time Gemini 3.8 Live voice/comedy session with co-timed sound effects",
    )
    live_p.add_argument(
        "prompt", nargs="*", default=None, help="Prompt or joke topic to execute once"
    )
    live_p.add_argument(
        "--model",
        default="gemini-2.5-flash-native-audio-latest",
        choices=[
            "gemini-2.5-flash-native-audio-latest",
            "gemini-3.8-live",
            "gemini-3.8-live-extended-thinking",
        ],
        help="Live model ID (default: gemini-2.5-flash-native-audio-latest for native audio speech)",
    )
    live_p.add_argument(
        "-v",
        "--voice",
        default="Puck",
        choices=sorted(list(VALID_GEMINI_LIVE_VOICES)),
        help="Voice persona (default: Puck)",
    )
    live_p.add_argument(
        "-m",
        "--mode",
        default="comedy",
        choices=["comedy", "roast", "banter", "assistant"],
        help="Persona mode (default: comedy)",
    )
    live_p.add_argument(
        "-t",
        "--thinking",
        action="store_true",
        help="Use Gemini 3.8 Live Extended Thinking model",
    )
    live_p.add_argument(
        "--thinking-level",
        default="LOW",
        choices=["MINIMAL", "LOW", "MEDIUM", "HIGH"],
        help="Thinking level for extended thinking (default: LOW)",
    )
    live_p.add_argument(
        "--no-sfx",
        action="store_true",
        help="Disable synchronized punchline sound effects",
    )
    live_p.add_argument(
        "--no-play",
        action="store_true",
        help="Do not play audio aloud through speakers",
    )
    live_p.add_argument(
        "-l",
        "--direct",
        dest="direct_live",
        action="store_true",
        help="Start direct microphone-to-speaker full-duplex speech loop",
    )
    live_p.add_argument(
        "--tools",
        action="store_true",
        default=True,
        help="Enable background tools while speaking (code reading, shell checks, sfx)",
    )
    live_p.add_argument(
        "--no-tools",
        dest="tools",
        action="store_false",
        help="Disable background tools",
    )

    # record / voice note recorder
    record_p = subparsers.add_parser(
        "record",
        aliases=["voice-note", "mic-record"],
        help="Record clean studio voice note from microphone",
    )
    record_p.add_argument(
        "-d",
        "--duration",
        type=float,
        default=8.0,
        help="Recording duration in seconds (default: 8.0)",
    )
    record_p.add_argument(
        "-o",
        "--output",
        "--out",
        default="assets/jake_intro.wav",
        help="Output audio file path (.wav)",
    )

    # welcome / onboarding window
    subparsers.add_parser(
        "welcome",
        aliases=["welcome-gui", "license-gui", "activate-gui"],
        help="Launch native macOS Welcome & License Activation Window",
    )

    # scout / recon
    scout_p = subparsers.add_parser(
        "scout",
        aliases=["recon"],
        help="Run on-device Recon Scout to pre-digest logs/files and save context tokens",
    )
    scout_p.add_argument(
        "target",
        nargs="?",
        default=".",
        help="File or directory path to scout (default: current directory)",
    )
    scout_p.add_argument("-q", "--query", default=None, help="Query or anomaly detection objective")
    scout_p.add_argument(
        "--max-bytes",
        type=int,
        default=500_000,
        help="Maximum bytes to scan (default: 500,000)",
    )

    # benchmark
    bench_p = subparsers.add_parser(
        "benchmark",
        aliases=["bench"],
        help="Measure on-device model throughput (tok/s), TTFB latency, and context efficiency",
    )
    bench_p.add_argument("prompt", nargs="*", default=None, help="Custom prompt to benchmark")
    bench_p.add_argument("--name", default="CLI Benchmark", help="Benchmark run label")
    bench_p.add_argument(
        "--history", action="store_true", help="Display previous benchmark scorecard history"
    )
    bench_p.add_argument(
        "-c",
        "--compare",
        action="store_true",
        help="Run empirical Time on Task (ToT) Benchmark: Local vs All-Cloud",
    )
    bench_p.add_argument(
        "-t",
        "--target",
        type=str,
        default="src/voicefi/local/engine.py",
        help="Target file or directory to benchmark",
    )
    bench_p.add_argument(
        "--turns", type=int, default=3, help="Number of multi-turn interactions (1-5, default: 3)"
    )
    bench_p.add_argument(
        "--cloud",
        type=str,
        default="gemini",
        choices=["gemini", "claude"],
        help="Cloud provider to compare against (default: gemini)",
    )
    bench_p.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON comparison profile"
    )

    # eval (direct alias for benchmark --compare)
    eval_p = subparsers.add_parser(
        "eval",
        help="Run empirical Time on Task (ToT) Benchmark comparing Local vs All-Cloud",
    )
    eval_p.add_argument("prompt", nargs="*", default=None, help="Custom prompt or diagnostic query")
    eval_p.add_argument(
        "-t",
        "--target",
        type=str,
        default="src/voicefi/local/engine.py",
        help="Target file or directory to benchmark",
    )
    eval_p.add_argument(
        "--turns", type=int, default=3, help="Number of multi-turn interactions (1-5, default: 3)"
    )
    eval_p.add_argument(
        "--cloud",
        type=str,
        default="gemini",
        choices=["gemini", "claude"],
        help="Cloud provider to compare against (default: gemini)",
    )
    eval_p.add_argument(
        "--history", action="store_true", help="Display previous ToT scorecard history"
    )
    eval_p.add_argument(
        "--json", action="store_true", help="Output machine-readable JSON comparison profile"
    )

    # local model management
    local_p = subparsers.add_parser(
        "local",
        aliases=["litert", "gemma"],
        help="Inspect and manage on-device LiteRT and Gemma models",
    )
    local_p.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["status", "list", "download"],
        help="Action (status, list, download)",
    )

    # help
    subparsers.add_parser("help", help="Display help and command usage")

    return parser
