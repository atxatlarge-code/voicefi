"""
Live Agent Tools for Gemini Live.

Curated set of non-blocking tools that Gemini Live can invoke asynchronously
in parallel while streaming speech aloud to the developer.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger("voicefi.integrations.live_tools")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SFX_DIR = Path.home() / ".voicefi" / "sfx"
SEARCH_EXCLUDE_DIRS = {".venv", "venv", ".git", "node_modules", "__pycache__", "build", "dist"}


def read_code_file(path: str, max_lines: int = 50) -> str:
    """
    Read the beginning or content of a source file in the repository.
    Use this to inspect code, configurations, or logs when the user asks a question.
    """
    try:
        clean_path = path.strip().lstrip("/")
        target = PROJECT_ROOT / clean_path
        if not target.is_file():
            found = None
            for root_dir in [PROJECT_ROOT / "src", PROJECT_ROOT]:
                if not root_dir.is_dir():
                    continue
                for item in root_dir.rglob(Path(clean_path).name):
                    if any(part in SEARCH_EXCLUDE_DIRS for part in item.parts):
                        continue
                    if item.is_file():
                        found = item
                        break
                if found:
                    break
            if found:
                target = found
            else:
                return f"File '{path}' not found in repository."

        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        preview = "\n".join(lines[:max_lines])
        truncated_note = (
            f"\n... [Truncated: showing first {max_lines} of {len(lines)} lines]"
            if len(lines) > max_lines
            else ""
        )
        return f"File: {target.relative_to(PROJECT_ROOT)}\n```\n{preview}{truncated_note}\n```"
    except Exception as e:
        return f"Error reading file '{path}': {e}"


def search_codebase(query: str, max_results: int = 5) -> str:
    """
    Fast search for a function, class, or pattern in the codebase using ripgrep.
    """
    try:
        cmd = ["rg", "-n", "--max-count", str(max_results), query, str(PROJECT_ROOT / "src")]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4.0)
        output = res.stdout.strip()
        if output:
            lines = output.splitlines()[:max_results]
            return "Matches found:\n" + "\n".join(lines)
        return f"No matches found for '{query}' in codebase."
    except Exception as e:
        return f"Search error: {e}"


def run_shell_check(command: str) -> str:
    """
    Run safe, non-destructive status checks like 'git status', 'git branch', 'git log -n 3', or 'uptime'.
    Destructive commands (rm, push, drop) are rejected.
    """
    clean_cmd = command.strip()
    allowed_prefixes = (
        "git status",
        "git branch",
        "git log",
        "git diff --stat",
        "uptime",
        "date",
        "pytest -q",
        "pip list",
    )
    if not any(clean_cmd.startswith(p) for p in allowed_prefixes):
        return f"Command '{command}' not in safe allowed list (status/check commands only)."

    try:
        res = subprocess.run(
            clean_cmd,
            shell=True,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        out = (res.stdout + res.stderr).strip()
        return out[:500] if out else "Command completed with no output."
    except Exception as e:
        return f"Execution error: {e}"


def trigger_sound_effect(name: str) -> str:
    """
    Play a sound effect: 'rimshot' (punchline), 'applause' (success), 'drum_smash', 'sad_trombone' (fail), 'crickets' (groaner dad joke).
    """
    clean_name = name.lower().strip().replace(" ", "_")
    sfx_file = SFX_DIR / f"{clean_name}.wav"
    if sfx_file.is_file():
        try:
            subprocess.Popen(
                ["afplay", str(sfx_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            return f"Played sound effect '{clean_name}'"
        except Exception as e:
            return f"Error playing sound effect: {e}"
    return f"Sound effect '{name}' not found."


def get_live_tools() -> List[Any]:
    """Return list of tool functions callable by Gemini Live."""
    return [
        read_code_file,
        search_codebase,
        run_shell_check,
        trigger_sound_effect,
    ]


TOOL_MAP: Dict[str, Any] = {
    "read_code_file": read_code_file,
    "search_codebase": search_codebase,
    "run_shell_check": run_shell_check,
    "trigger_sound_effect": trigger_sound_effect,
}

TOOL_PARAM_ALIASES = {
    "read_code_file": {"file": "path", "filename": "path", "filepath": "path"},
    "search_codebase": {"term": "query", "pattern": "query", "q": "query"},
    "run_shell_check": {"cmd": "command"},
    "trigger_sound_effect": {"sfx": "name", "sound": "name"},
}


async def execute_live_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute a live agent tool in a thread pool with parameter alias normalization."""
    import asyncio

    clean_name = str(name).strip() if name else ""
    tool_fn = TOOL_MAP.get(clean_name)
    if not tool_fn:
        logger.warning("Requested tool '%s' not found in live tool map", clean_name)
        return f"Tool '{name}' is not recognized."

    normalized_args = dict(args) if args else {}
    aliases = TOOL_PARAM_ALIASES.get(clean_name, {})
    for alt_key, target_key in aliases.items():
        if alt_key in normalized_args and target_key not in normalized_args:
            normalized_args[target_key] = normalized_args.pop(alt_key)

    try:
        res = await asyncio.to_thread(tool_fn, **normalized_args)
        return str(res)
    except TypeError as te:
        logger.warning(
            "Tool signature mismatch for %s with args %s: %s", clean_name, normalized_args, te
        )
        return f"Invalid tool arguments for '{name}': {te}"
    except Exception as e:
        logger.error(
            "Error executing live tool '%s' with args %s: %s", clean_name, normalized_args, e
        )
        return f"Error executing tool '{name}': {e}"
