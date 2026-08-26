"""
Terminal Layout, ANSI Styling, Fuzzy Typo Recovery, and Categorized Help Engine for VoiceFi CLI.
"""

import argparse
import difflib
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from voicefi import __version__


# ---------------------------------------------------------------------------
# ANSI Terminal Styling Helpers
# ---------------------------------------------------------------------------

def _use_color(stream=None) -> bool:
    """Determine if ANSI color codes should be enabled."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR") in ("1", "true", "TRUE"):
        return True
    target_stream = stream or sys.stderr
    return hasattr(target_stream, "isatty") and target_stream.isatty()


def colorize(text: str, code: str, stream=None) -> str:
    """Wrap text in ANSI escape sequence if terminal supports color."""
    if _use_color(stream):
        return f"\033[{code}m{text}\033[0m"
    return text


def c_bold(text: str, stream=None) -> str:
    return colorize(text, "1", stream)


def c_cyan(text: str, stream=None) -> str:
    return colorize(text, "36", stream)


def c_bold_cyan(text: str, stream=None) -> str:
    return colorize(text, "1;36", stream)


def c_green(text: str, stream=None) -> str:
    return colorize(text, "32", stream)


def c_bold_green(text: str, stream=None) -> str:
    return colorize(text, "1;32", stream)


def c_yellow(text: str, stream=None) -> str:
    return colorize(text, "33", stream)


def c_bold_yellow(text: str, stream=None) -> str:
    return colorize(text, "1;33", stream)


def c_dim(text: str, stream=None) -> str:
    return colorize(text, "2;90", stream)


def c_red(text: str, stream=None) -> str:
    return colorize(text, "31", stream)


def c_bold_red(text: str, stream=None) -> str:
    return colorize(text, "1;31", stream)


def c_magenta(text: str, stream=None) -> str:
    return colorize(text, "35", stream)


# ---------------------------------------------------------------------------
# Program Name Resolution
# ---------------------------------------------------------------------------

def resolve_prog_name() -> str:
    """Resolve the invoked binary name (e.g. 'vifi' or 'voicefi')."""
    if sys.argv and sys.argv[0]:
        prog_stem = Path(sys.argv[0]).stem.lower()
        if prog_stem in ("vifi", "voicefi"):
            return prog_stem
    return "vifi"


# ---------------------------------------------------------------------------
# Command Catalog & Categorized Help Definitions
# ---------------------------------------------------------------------------

COMMAND_CATEGORIES = [
    (
        "🤖 Agent & Integration",
        [
            ("hook", "Run as AI agent lifecycle hook (Antigravity, Claude Code)"),
            ("speak", "Speak text aloud with neural or local offline voice"),
            ("listen", "Listen from microphone, transcribe, and inject into active app"),
            ("loop", "Start continuous interactive voice loop"),
            ("new", "Start a new AI agent conversation with connected tools"),
            ("setup", "Auto-configure agent lifecycle hooks (Antigravity, Claude)"),
            ("onboarding", "Run interactive First-Time User Experience onboarding"),
        ],
    ),
    (
        "🎙️ Voice & Personas",
        [
            ("voice", "Manage, switch, audition, and test agent voices"),
            ("download-ava", "Setup Apple's Ava (Premium) neural voice for 0ms offline speech"),
            ("ping", "Silently test voice connection latency & throughput speed"),
            ("clone", "Train and manage custom voice clones (F5-TTS, ElevenLabs)"),
        ],
    ),
    (
        "🪟 Interface & Controls",
        [
            ("hud", "Dynamic Island floating status pill and debug studio"),
            ("tray", "Launch macOS menu bar companion"),
            ("panel", "Launch interactive Web Voice Control Panel"),
            ("companion", "Launch Web & Mobile Voice Companion (PWA & QR code)"),
        ],
    ),
    (
        "🧠 Memory & Knowledge",
        [
            ("memo", "Voice memo buffer: capture long rambles & synthesize to code"),
            ("ambient", "Ambient background listening & proactive triage co-pilot"),
            ("bias", "STT vocabulary biasing & phonetic normalization"),
            ("obsidian", "Manage and install VoiceFi Obsidian vault voice plugin"),
        ],
    ),
    (
        "🛠️ Diagnostics & Audio",
        [
            ("troubleshoot", "Comprehensive audio, mic, VAD, and TTS diagnostic suite"),
            ("feedback-loop", "Acoustic loopback test (Speak → Listen → Transcribe)"),
            ("hearing-test", "Speaker-to-mic acoustic reception verification"),
            ("dev", "Live foreground dev mode with real-time VAD & barge-in logs"),
            ("pause / resume", "Globally pause / resume voice hooks and turn-handoffs"),
            ("permissions", "Check macOS Accessibility & Microphone permissions"),
            ("info", "Display system status, active devices, and voices"),
        ],
    ),
    (
        "⚙️ Management & Daemons",
        [
            ("daemon", "Inspect and manage background daemons, LaunchAgents, and ports"),
            ("clean", "Purge __pycache__, stale locks, caches, and orphaned daemons"),
            ("dev", "Live foreground dev mode with real-time logs and auto-takeover"),
            ("update", "Check for and install latest VoiceFi updates"),
            ("autostart", "Enable background LaunchAgent daemon (vifi tray)"),
            ("stop-autostart", "Remove background LaunchAgent daemon"),
            ("feedback", "Submit sanitized feedback, telemetry, or bug reports"),
            ("help", "Display help and command usage"),
        ],
    ),
]


def render_categorized_help(prog: str = "vifi", stream=None) -> str:
    """Generate modern, structured, and categorized CLI help output."""
    lines: List[str] = []
    
    # Header Banner
    title = f"🎙️  VoiceFi v{__version__}"
    tagline = "Universal Voice Layer for AI Agents, MCP & macOS"
    lines.append(f"{c_bold_cyan(title, stream)} {c_dim('— ' + tagline, stream)}")
    lines.append("")
    
    # Usage
    lines.append(f"{c_bold_yellow('Usage:', stream)} {c_bold(prog, stream)} {c_cyan('<command>', stream)} {c_dim('[options] [arguments]', stream)}")
    lines.append("")

    # Categories
    for cat_name, commands in COMMAND_CATEGORIES:
        lines.append(f"{c_bold(cat_name, stream)}:")
        for cmd_name, cmd_help in commands:
            cmd_styled = f"  {c_bold_cyan(cmd_name):<28}" if _use_color(stream) else f"  {cmd_name:<18}"
            lines.append(f"{cmd_styled} {cmd_help}")
        lines.append("")

    # Options
    lines.append(f"{c_bold('Options:', stream)}")
    lines.append(f"  {c_bold_yellow('-h, --help', stream):<28} Show this help message and exit" if _use_color(stream) else "  -h, --help         Show this help message and exit")
    lines.append(f"  {c_bold_yellow('--version', stream):<28} Show VoiceFi version" if _use_color(stream) else "  --version          Show VoiceFi version")
    lines.append(f"  {c_bold_yellow('--config <path>', stream):<28} Path to custom config.yaml" if _use_color(stream) else "  --config <path>    Path to custom config.yaml")
    lines.append("")

    # Quick Examples
    lines.append(f"{c_bold('💡 Quick Examples:', stream)}")
    lines.append(f"  {c_dim('$', stream)} {c_bold(prog + ' speak', stream)} {c_green('\"Hello world! Ready to pair program.\"', stream)}")
    lines.append(f"  {c_dim('$', stream)} {c_bold(prog + ' voice set antigravity', stream)} {c_green('\"Ava (Premium)\"', stream)}")
    lines.append(f"  {c_dim('$', stream)} {c_bold(prog + ' ping --all', stream)}")
    lines.append(f"  {c_dim('$', stream)} {c_bold(prog + ' troubleshoot', stream)}")
    lines.append(f"  {c_dim('$', stream)} {c_bold(prog + ' hud debug', stream)}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fuzzy Typo Matching & Error Card Formatter
# ---------------------------------------------------------------------------

def find_closest_matches(query: str, possibilities: Sequence[str], n: int = 3, cutoff: float = 0.5) -> List[str]:
    """Find close matches for typos using prefix, substring, and scored fuzzy matching."""
    q = query.strip().lower()
    if not q:
        return []

    # 1. Exact match (case-insensitive)
    exact = [p for p in possibilities if p.lower() == q]
    if exact:
        return exact

    # 2. Prefix matches (e.g. "lis" -> "list", "onboard" -> "onboarding", "trouble" -> "troubleshoot")
    prefix_hits = [p for p in possibilities if p.lower().startswith(q)]

    # 3. Substring contains matches (e.g. "board" -> "onboarding")
    substring_hits = [p for p in possibilities if q in p.lower() and p not in prefix_hits]

    # 4. Scored fuzzy matches using difflib
    scored: List[Tuple[float, str]] = []
    for p in possibilities:
        if p not in prefix_hits and p not in substring_hits:
            ratio = difflib.SequenceMatcher(None, q, p.lower()).ratio()
            if ratio >= cutoff:
                scored.append((ratio, p))
    scored.sort(key=lambda x: x[0], reverse=True)

    fuzzy_hits: List[str] = []
    if scored:
        best_score = scored[0][0]
        for score, p in scored:
            if best_score >= 0.75:
                # If high-confidence match exists, keep only candidates close to best score
                if score >= best_score - 0.15:
                    fuzzy_hits.append(p)
            else:
                fuzzy_hits.append(p)

    # Combine in priority order: Prefix -> Substring -> Scored Fuzzy
    combined = prefix_hits + substring_hits + fuzzy_hits

    # Deduplicate while preserving order
    unique: List[str] = []
    for item in combined:
        if item not in unique:
            unique.append(item)
    return unique[:n]


def render_error_box(title: str, message: str, suggestions: Optional[List[str]] = None, prog: str = "vifi", stream=None) -> str:
    """Render a clean, high-signal terminal error card."""
    lines: List[str] = []
    
    # Calculate box width
    clean_msg = f"❌ {title}: {message}"
    box_width = max(len(clean_msg) + 4, 48)
    box_width = min(box_width, 80)

    top_border = "╭" + "─" * (box_width - 2) + "╮"
    bot_border = "╰" + "─" * (box_width - 2) + "╯"

    lines.append("")
    lines.append(c_bold_red(top_border, stream))
    lines.append(f"{c_bold_red('│', stream)} {c_bold_red('❌ ' + title + ':', stream)} {c_bold(message, stream):<{box_width - len(title) - 8}} {c_bold_red('│', stream)}")
    lines.append(c_bold_red(bot_border, stream))
    lines.append("")

    if suggestions:
        lines.append(f"{c_bold_yellow('💡 Did you mean?', stream)}")
        for s in suggestions:
            cmd_preview = f"{prog} {s}" if not s.startswith("-") else s
            lines.append(f"   {c_bold_cyan('❯ ' + cmd_preview, stream)}")
        lines.append("")

    lines.append(f"{c_dim('Run', stream)} {c_bold(prog + ' --help', stream)} {c_dim('or', stream)} {c_bold(prog + ' help', stream)} {c_dim('to view available commands.', stream)}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Custom VoiceFiArgumentParser
# ---------------------------------------------------------------------------

class VoiceFiArgumentParser(argparse.ArgumentParser):
    """
    Enhanced ArgumentParser with:
    - Grouped, categorized, color-aware help formatting
    - Dynamic 'vifi' / 'voicefi' binary name resolution
    - Intelligent error catching with fuzzy 'Did you mean?' typo suggestions
    - Clean subparser usage lines (no 50-choice raw dumps)
    """

    def __init__(self, *args, **kwargs):
        if "prog" not in kwargs or not kwargs["prog"]:
            kwargs["prog"] = resolve_prog_name()
        super().__init__(*args, **kwargs)
        self._valid_command_choices: Set[str] = set()

    def format_help(self) -> str:
        """Format top-level help using our categorized layout, or fallback for sub-commands."""
        # If this is the root parser (has our dest="command" subparser)
        if any(isinstance(a, argparse._SubParsersAction) and a.dest == "command" for a in self._actions):
            return render_categorized_help(prog=self.prog, stream=sys.stdout)
        return super().format_help()

    def error(self, message: str):
        """Custom error handler that formats crisp error cards and fuzzy typo suggestions."""
        prog = self.prog or resolve_prog_name()

        # Case 1: Invalid choice (e.g. "argument <command>: invalid choice: 'onbaoarding' (choose from ...)")
        choice_match = re.search(r"(?:argument\s+([<>\w\-]+):\s+)?invalid choice:\s+'([^']+)'(?:\s+\(choose from (.*?)\))?", message)
        if choice_match:
            raw_arg = choice_match.group(1) or ""
            arg_name = raw_arg.strip("<>")
            bad_choice = choice_match.group(2)
            raw_choices = choice_match.group(3) or ""
            
            # Extract choice list
            choices: List[str] = []
            if raw_choices:
                choices = [c.strip(" '\"") for c in raw_choices.split(",") if c.strip(" '\"")]
            
            # If choices not in message, collect from registered subparser actions
            if not choices:
                for action in self._actions:
                    if isinstance(action, argparse._SubParsersAction) and action.choices:
                        choices.extend(action.choices.keys())

            suggestions = find_closest_matches(bad_choice, choices, n=3)
            
            is_sub_action = arg_name in ("voice_action", "hud_action", "memo_action", "clone_action", "ambient_action", "obsidian_action", "feedback_action", "action")
            is_main_cmd = arg_name in ("command", "")

            label = "Unknown action" if is_sub_action else ("Unknown command" if is_main_cmd else f"Invalid value for '{arg_name}'")
            err_box = render_error_box(label, f"'{bad_choice}'", suggestions=suggestions, prog=prog, stream=sys.stderr)
            sys.stderr.write(err_box + "\n")
            sys.exit(2)

        # Case 2: Unrecognized arguments (e.g. "unrecognized arguments: --verison")
        unrec_match = re.search(r"unrecognized arguments:\s+(.+)", message)
        if unrec_match:
            bad_args_str = unrec_match.group(1).strip()
            bad_args = bad_args_str.split()
            all_opts: List[str] = []
            for action in self._actions:
                all_opts.extend(action.option_strings)

            suggestions: List[str] = []
            for bad_arg in bad_args:
                suggestions.extend(find_closest_matches(bad_arg, all_opts, n=2))

            err_box = render_error_box("Unrecognized argument", bad_args_str, suggestions=suggestions, prog=prog, stream=sys.stderr)
            sys.stderr.write(err_box + "\n")
            sys.exit(2)

        # Case 3: Required argument missing (e.g. "the following arguments are required: text")
        req_match = re.search(r"the following arguments are required:\s+(.+)", message)
        if req_match:
            missing_arg = req_match.group(1)
            err_box = render_error_box("Missing required argument", f"'{missing_arg}'", suggestions=None, prog=prog, stream=sys.stderr)
            sys.stderr.write(err_box + "\n")
            sys.exit(2)

        # Generic fallback
        err_box = render_error_box("Argument error", message, suggestions=None, prog=prog, stream=sys.stderr)
        sys.stderr.write(err_box + "\n")
        sys.exit(2)
