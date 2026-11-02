"""
Live Agent Tools for Gemini Live.

Curated set of non-blocking tools that Gemini Live can invoke asynchronously
in parallel while streaming speech aloud to the developer.
"""

import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("voicefi.integrations.live_tools")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SFX_DIR = Path.home() / ".voicefi" / "sfx"
SEARCH_EXCLUDE_DIRS = {".venv", "venv", ".git", "node_modules", "__pycache__", "build", "dist"}
SENSITIVE_FILENAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "config.yaml", "relay_session.json"}
SENSITIVE_PATH_PARTS = {".git", ".ssh", ".aws", ".gnupg", ".voicefi"}
FORBIDDEN_SHELL_PATTERNS = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "\r", "\x00")


def _is_safe_repo_file(candidate: Path) -> bool:
    """Ensure candidate resolves inside PROJECT_ROOT and is not a sensitive secret file."""
    try:
        resolved_root = PROJECT_ROOT.resolve()
        resolved = candidate.resolve()
        if not resolved.is_relative_to(resolved_root):
            return False
        rel_parts = resolved.relative_to(resolved_root).parts
        if any(part in SENSITIVE_PATH_PARTS or part.startswith(".env") for part in rel_parts):
            return False
        if resolved.name in SENSITIVE_FILENAMES:
            return False
        return True
    except Exception:
        return False


def read_code_file(path: str, max_lines: int = 50) -> str:
    """
    Read the beginning or content of a source file in the repository.
    Use this to inspect code, configurations, or logs when the user asks a question.
    """
    try:
        clean_path = (path or "").strip().lstrip("/")
        if not clean_path or ".." in Path(clean_path).parts:
            return f"Access denied: path '{path}' must stay inside repository."
        target = (PROJECT_ROOT / clean_path).resolve()
        if not _is_safe_repo_file(target):
            return f"Access denied: path '{path}' is outside repository or restricted."
        if not target.is_file():
            found = None
            safe_name = Path(clean_path).name
            for root_dir in [PROJECT_ROOT / "src", PROJECT_ROOT]:
                if not root_dir.is_dir():
                    continue
                for item in root_dir.rglob(safe_name):
                    if any(part in SEARCH_EXCLUDE_DIRS for part in item.parts):
                        continue
                    if item.is_file() and _is_safe_repo_file(item):
                        found = item.resolve()
                        break
                if found:
                    break
            if found:
                target = found
            else:
                return f"File '{path}' not found in repository."

        safe_max = max(1, min(int(max_lines or 50), 200))
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        preview = "\n".join(lines[:safe_max])
        truncated_note = (
            f"\n... [Truncated: showing first {safe_max} of {len(lines)} lines]"
            if len(lines) > safe_max
            else ""
        )
        return f"File: {target.relative_to(PROJECT_ROOT.resolve())}\n```\n{preview}{truncated_note}\n```"
    except Exception as e:
        return f"Error reading file '{path}': {e}"


def search_codebase(query: str, max_results: int = 5) -> str:
    """
    Fast search for a function, class, or pattern in the codebase using ripgrep.
    """
    try:
        clean_query = (query or "").strip()
        if not clean_query:
            return "Empty search query."
        safe_max = max(1, min(int(max_results or 5), 25))
        cmd = ["rg", "-n", "--max-count", str(safe_max), "--", clean_query, str(PROJECT_ROOT / "src")]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4.0, shell=False)
        output = res.stdout.strip()
        if output:
            lines = output.splitlines()[:safe_max]
            return "Matches found:\n" + "\n".join(lines)
        return f"No matches found for '{clean_query}' in codebase."
    except Exception as e:
        return f"Search error: {e}"


def run_shell_check(command: str) -> str:
    """
    Run safe, non-destructive status checks like 'git status', 'git branch', 'git log -n 3', 'git blame <file>', 'git diff', or 'pytest -q'.
    Destructive commands (rm, push, drop) are rejected.
    """
    clean_cmd = (command or "").strip()
    if not clean_cmd:
        return "Command cannot be empty."
    if any(tok in clean_cmd for tok in FORBIDDEN_SHELL_PATTERNS):
        return f"Command '{command}' rejected: shell chaining or redirection operators are not allowed."

    allowed_prefixes = (
        "git status",
        "git branch",
        "git log",
        "git diff",
        "git blame",
        "git show",
        "uptime",
        "date",
        "pytest -q",
        "pip list",
    )
    if not any(clean_cmd == p or clean_cmd.startswith(p + " ") for p in allowed_prefixes):
        return f"Command '{command}' not in safe allowed list (status/check commands only)."

    try:
        args = shlex.split(clean_cmd)
    except ValueError as e:
        return f"Invalid command syntax: {e}"

    if not args:
        return "Command cannot be empty."

    # Block dangerous git/pytest execution flags
    dangerous_flags = ("--upload-pack", "--exec", "--ext-diff", "--output", "-c", "--override-ini", "-o")
    for arg in args[1:]:
        if any(arg == flag or arg.startswith(flag + "=") for flag in dangerous_flags):
            return f"Command '{command}' rejected: disallowed flag '{arg}'."

    try:
        res = subprocess.run(
            args,
            shell=False,
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
    Play a sound effect: 'rimshot' (punchline), 'applause' (success), 'drum_smash', 'sad_trombone' (fail), 'crickets' (groaner dad joke), 'honk', or 'boing'.
    """
    from voicefi.audio.sfx import play_sfx

    clean_name = name.lower().strip().replace(" ", "_")
    if play_sfx(clean_name, block=False):
        return f"Played sound effect '{clean_name}'"
    return f"Sound effect '{name}' not found."


def dispatch_to_antigravity(instruction: str, conversation_id: Optional[str] = None) -> str:
    """
    Dispatch a coding task, instruction, command, or refactoring request directly to the Antigravity agent (Viv).
    Use this proactively whenever the developer asks Antigravity (or Viv) to write code, edit files, fix bugs, run builds or tests,
    or execute any complex coding or workspace operation.
    """
    from voicefi.tts.base import set_cross_process_hud_state
    from voicefi.integrations.injector import send_message_to_antigravity

    clean_instruction = instruction.strip() if instruction else ""
    if not clean_instruction:
        return "Cannot dispatch an empty instruction to Antigravity."

    preview = clean_instruction[:40] + "..." if len(clean_instruction) > 40 else clean_instruction
    set_cross_process_hud_state(
        "dispatching",
        text=f"Dispatching: {preview}",
        agent_name="Antigravity",
        tag_text="Dispatching to Antigravity",
    )

    res = send_message_to_antigravity(
        conv_id=conversation_id,
        text=clean_instruction,
        sender_name="Gemini Live",
        title="Spoken Task Dispatch",
    )

    if res.success:
        try:
            from voicefi.integrations.turn_lock import set_live_turn_origin

            set_live_turn_origin(res.target_conv_id or conversation_id)
        except Exception:
            pass
        target_info = f" (conversation {res.target_conv_id[:8]})" if res.target_conv_id else ""
        set_cross_process_hud_state(
            "done",
            text="Dispatched to Antigravity",
            agent_name="Antigravity",
        )
        return (
            f"Successfully dispatched task to Antigravity{target_info}: '{clean_instruction}'. "
            "Antigravity will execute the work in the background."
        )
    else:
        set_cross_process_hud_state(
            "done",
            text=f"Dispatch failed: {res.error[:20]}",
            agent_name="Antigravity",
        )
        return f"Failed to dispatch to Antigravity: {res.error}"


def dispatch_to_claude(instruction: str, conversation_id: Optional[str] = None) -> str:
    """
    Dispatch a coding task, terminal command, test run, or refactoring request directly to Claude Code (Steffan).
    Use this whenever the developer asks Claude (or Steffan) to inspect code, run tests, fix a bug, or collaborate with Antigravity.
    """
    from voicefi.tts.base import set_cross_process_hud_state
    from voicefi.integrations.injector import send_message_to_agent

    clean_instruction = instruction.strip() if instruction else ""
    if not clean_instruction:
        return "Cannot dispatch an empty instruction to Claude Code."

    preview = clean_instruction[:40] + "..." if len(clean_instruction) > 40 else clean_instruction
    set_cross_process_hud_state(
        "dispatching",
        text=f"Dispatching to Claude: {preview}",
        agent_name="Claude Code",
        tag_text="Dispatching to Claude Code",
    )

    res = send_message_to_agent(
        conv_id=conversation_id,
        text=clean_instruction,
        sender_name="Gemini Live",
        title="Spoken Task Dispatch",
        target_engine="claude",
    )

    if res.success:
        set_cross_process_hud_state(
            "done",
            text="Dispatched to Claude Code",
            agent_name="Claude Code",
        )
        return (
            f"Successfully dispatched task to Claude Code: '{clean_instruction}'. "
            "Claude Code is executing the task in the background."
        )
    else:
        set_cross_process_hud_state(
            "done",
            text=f"Claude dispatch failed: {res.error[:20]}",
            agent_name="Claude Code",
        )
        return f"Failed to dispatch to Claude Code: {res.error}"


CUSTOM_TOOLS: Dict[str, Any] = {}
_USER_TOOLS_LOADED = False


def tool(fn: Optional[Any] = None, *, name: Optional[str] = None, aliases: Optional[Dict[str, str]] = None) -> Any:
    """
    Decorator to register any Python function as a real-time VoiceFi Live & Agent Tool.

    Usage:
        from voicefi import tool

        @tool
        def deploy_staging(branch: str = "main") -> str:
            \"\"\"Deploy a git branch to staging when requested by voice.\"\"\"
            ...
    """
    def _register(func: Any) -> Any:
        tool_name = name or func.__name__
        CUSTOM_TOOLS[tool_name] = func
        TOOL_MAP[tool_name] = func
        if aliases:
            TOOL_PARAM_ALIASES[tool_name] = dict(aliases)
        setattr(func, "_is_voicefi_tool", True)
        return func

    if fn is not None and callable(fn):
        return _register(fn)
    return _register


live_tool = tool


def load_user_live_tools() -> List[Any]:
    """
    Auto-discover and load custom @tool functions from:
      1. ~/.voicefi/tools/*.py (global user voice tools)
      2. <project_root>/.voicefi/tools/*.py (repo-specific voice tools)
    """
    global _USER_TOOLS_LOADED
    if _USER_TOOLS_LOADED:
        return list(CUSTOM_TOOLS.values())

    import importlib.util

    search_dirs = [
        Path.home() / ".voicefi" / "tools",
        PROJECT_ROOT / ".voicefi" / "tools",
    ]
    for tools_dir in search_dirs:
        if not tools_dir.is_dir():
            continue
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(
                    f"voicefi_user_tool_{py_file.stem}", py_file
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    for attr_name in dir(mod):
                        obj = getattr(mod, attr_name)
                        if callable(obj) and getattr(obj, "_is_voicefi_tool", False):
                            t_name = obj.__name__
                            CUSTOM_TOOLS[t_name] = obj
                            TOOL_MAP[t_name] = obj
            except Exception as e:
                logger.warning("Failed to load user tool file %s: %s", py_file, e)

    _USER_TOOLS_LOADED = True
    return list(CUSTOM_TOOLS.values())


def get_live_tools() -> List[Any]:
    """Return list of built-in + user-defined @tool functions callable by Gemini Live."""
    load_user_live_tools()
    base_tools = [
        read_code_file,
        search_codebase,
        run_shell_check,
        trigger_sound_effect,
        dispatch_to_antigravity,
        dispatch_to_claude,
    ]
    seen = {fn.__name__ for fn in base_tools}
    for custom_fn in CUSTOM_TOOLS.values():
        if custom_fn.__name__ not in seen:
            base_tools.append(custom_fn)
            seen.add(custom_fn.__name__)
    return base_tools


TOOL_MAP: Dict[str, Any] = {
    "read_code_file": read_code_file,
    "search_codebase": search_codebase,
    "run_shell_check": run_shell_check,
    "trigger_sound_effect": trigger_sound_effect,
    "dispatch_to_antigravity": dispatch_to_antigravity,
    "dispatch_to_claude": dispatch_to_claude,
}

TOOL_PARAM_ALIASES = {
    "read_code_file": {"file": "path", "filename": "path", "filepath": "path"},
    "search_codebase": {"term": "query", "pattern": "query", "q": "query"},
    "run_shell_check": {"cmd": "command"},
    "trigger_sound_effect": {"sfx": "name", "sound": "name"},
    "dispatch_to_antigravity": {
        "prompt": "instruction",
        "task": "instruction",
        "command": "instruction",
        "message": "instruction",
        "query": "instruction",
        "text": "instruction",
        "conv_id": "conversation_id",
        "cid": "conversation_id",
        "conversation": "conversation_id",
    },
    "dispatch_to_claude": {
        "prompt": "instruction",
        "task": "instruction",
        "command": "instruction",
        "message": "instruction",
        "query": "instruction",
        "text": "instruction",
        "conv_id": "conversation_id",
        "cid": "conversation_id",
        "conversation": "conversation_id",
    },
}


async def execute_live_tool(name: str, args: Dict[str, Any]) -> str:
    """Execute a live agent tool in a thread pool with parameter alias normalization."""
    import asyncio

    load_user_live_tools()
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


def get_openai_live_tools() -> List[Dict[str, Any]]:
    """
    Return tools formatted for OpenAI Realtime & xAI Grok Voice function calling APIs.
    """
    return [
        {
            "type": "function",
            "name": "read_code_file",
            "description": "Read the beginning or content of a source file in the repository to inspect code, configurations, or logs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file in repo, e.g. 'src/voicefi/live_studio.py'",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum number of lines to read (default: 50)",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "type": "function",
            "name": "search_codebase",
            "description": "Fast search for a function, class, or pattern in the codebase using ripgrep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text pattern, symbol, or keyword to search for",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matching lines to return (default: 5)",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "type": "function",
            "name": "run_shell_check",
            "description": "Run safe, non-destructive status checks like git status, git branch, git log, git blame, git diff, or pytest.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run (e.g. 'git status', 'git branch', 'pytest -q')",
                    }
                },
                "required": ["command"],
            },
        },
        {
            "type": "function",
            "name": "trigger_sound_effect",
            "description": "Play a comedic or dramatic sound effect (rimshot, sad_trombone, drum_smash, honk, applause, crickets).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of sound effect: rimshot, sad_trombone, drum_smash, honk, applause, crickets",
                    }
                },
                "required": ["name"],
            },
        },
        {
            "type": "function",
            "name": "dispatch_to_antigravity",
            "description": "Dispatch a coding instruction, refactor, or bug fix task to Antigravity (Viv).",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "The exact task, bug fix, or refactor instruction",
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "Optional conversation UUID to resume",
                    },
                },
                "required": ["instruction"],
            },
        },
        {
            "type": "function",
            "name": "dispatch_to_claude",
            "description": "Dispatch a coding task or code review to Claude Code (Steffan).",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {
                        "type": "string",
                        "description": "The coding task for Claude Code",
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "Optional conversation UUID to resume",
                    },
                },
                "required": ["instruction"],
            },
        },
    ]
