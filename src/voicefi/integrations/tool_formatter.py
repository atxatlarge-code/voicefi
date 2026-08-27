"""
Tool Call and Execution Log Formatter.
Extracts specific, human-readable command details, file targets, search queries,
and live output logs from agent tool calls for rich HUD presentation.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, Tuple, Optional


def format_tool_details(tool_call: Dict[str, Any]) -> Tuple[str, str]:
    """
    Extract specific, human-readable description and tag badge from an agent tool call.
    
    Returns:
        Tuple[str, str]: (detail_subtitle, tag_text)
        Example: ("pytest tests/test_hud.py -v", "Running Command")
                 ("unified_hud.py (L1100-1160)", "Reading File")
                 ("unified_hud.py — Update tool log display", "Editing File")
                 ('Grep: "Running Tool"', "Searching Code")
    """
    if not isinstance(tool_call, dict):
        return ("Running tool...", "Running Tool")

    # 1. Resolve tool name
    tool_name = (
        tool_call.get("name")
        or tool_call.get("tool_name")
        or (tool_call.get("function", {}).get("name") if isinstance(tool_call.get("function"), dict) else "")
        or "tool"
    )

    # 2. Resolve arguments dictionary
    raw_args = (
        tool_call.get("args")
        or tool_call.get("input")
        or (tool_call.get("function", {}).get("arguments") if isinstance(tool_call.get("function"), dict) else {})
        or {}
    )
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except Exception:
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}

    # Extract explicit action / summary if provided
    raw_action = (
        tool_call.get("toolAction")
        or tool_call.get("toolSummary")
        or args.get("toolAction")
        or args.get("toolSummary")
        or args.get("action")
        or args.get("summary")
        or ""
    )
    # Strip emojis and surrounding quotes
    tool_action = re.sub(
        r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]",
        "",
        str(raw_action),
    ).strip('\"\' ')

    norm_name = tool_name.lower().replace("-", "_")

    # Helper to clean up filenames/paths to compact basenames
    def _clean_path(p: str) -> str:
        if not p:
            return ""
        try:
            return Path(p).name or p
        except Exception:
            return p

    # Helper to truncate long strings cleanly
    def _truncate(s: str, max_len: int = 48) -> str:
        s = " ".join(str(s).split()).strip()
        if len(s) > max_len:
            return s[: max_len - 3] + "..."
        return s

    # 3. Handle specific tool types

    # Case A: Shell / Terminal command execution
    if norm_name in ("run_command", "bash", "terminal", "sh", "zsh", "execute_command", "command", "run_shell_command"):
        cmd = (
            args.get("CommandLine")
            or args.get("command")
            or args.get("cmd")
            or args.get("CommandLineString")
            or args.get("command_line")
            or ""
        )
        tag = "Running Command"
        if cmd:
            clean_cmd = _truncate(cmd, max_len=48)
            # If tool_action has a specific helpful note (like "Running test suite")
            if tool_action and tool_action.lower() not in ("running command", "command execution", "running run_command", "run command", f"running {tool_name}"):
                combined = f"{tool_action}: {clean_cmd}"
                if len(combined) <= 50:
                    return (combined, tag)
            return (clean_cmd, tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Executing shell command...", tag)

    # Case B: File reading / viewing
    if norm_name in ("view_file", "read_file", "fileread", "read_file_content", "cat", "open_file"):
        path_str = (
            args.get("AbsolutePath")
            or args.get("TargetFile")
            or args.get("path")
            or args.get("file_path")
            or args.get("filePath")
            or ""
        )
        tag = "Reading File"
        fname = _clean_path(path_str)
        start_l = args.get("StartLine")
        end_l = args.get("EndLine")
        if fname:
            if start_l is not None and end_l is not None:
                return (f"Viewing {fname} (L{start_l}-{end_l})", tag)
            elif start_l is not None:
                return (f"Viewing {fname} (L{start_l}+)", tag)
            return (f"Viewing {fname}", tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Reading file...", tag)

    # Case C: File editing / writing / creating
    if norm_name in ("replace_file_content", "write_to_file", "edit_file", "fileedit", "write", "patch", "create_file"):
        path_str = (
            args.get("TargetFile")
            or args.get("path")
            or args.get("file_path")
            or args.get("filePath")
            or args.get("AbsolutePath")
            or ""
        )
        is_create = norm_name in ("write_to_file", "create_file", "write")
        tag = "Writing File" if is_create else "Editing File"
        fname = _clean_path(path_str)
        desc = (
            args.get("Description")
            or args.get("Instruction")
            or tool_action
            or ""
        )
        desc = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]", "", str(desc)).strip('\"\' ')
        if fname:
            if desc and desc.lower() not in ("editing file", "file edit", "writing file", f"running {tool_name}"):
                short_desc = _truncate(desc, max_len=28)
                combined = f"{fname} — {short_desc}"
                if len(combined) <= 48:
                    return (combined, tag)
            action_verb = "Writing" if is_create else "Editing"
            return (f"{action_verb} {fname}", tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Editing file...", tag)

    # Case D: Grep / Code search
    if norm_name in ("grep_search", "greptool", "grep", "search_code", "ripgrep"):
        query = args.get("Query") or args.get("query") or args.get("pattern") or ""
        tag = "Searching Code"
        if query:
            clean_q = _truncate(query, max_len=36)
            return (f'Grep: "{clean_q}"', tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Searching codebase...", tag)

    # Case E: File search / Glob
    if norm_name in ("find_by_name", "globtool", "find_files", "glob", "find", "locate_files"):
        pattern = args.get("Pattern") or args.get("pattern") or ""
        tag = "Finding Files"
        if pattern:
            clean_p = _truncate(pattern, max_len=36)
            return (f"Finding: {clean_p}", tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Finding files...", tag)

    # Case F: Directory listing
    if norm_name in ("list_dir", "ls", "list_directory", "list_folder"):
        dir_path = args.get("DirectoryPath") or args.get("path") or args.get("dir") or ""
        tag = "Browsing Dir"
        dname = _clean_path(dir_path) or dir_path
        if dname:
            return (f"Listing: {dname}/", tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Listing directory...", tag)

    # Case G: Web Search & Browsing
    if norm_name in ("search_web", "web_search", "google_search", "search"):
        query = args.get("query") or args.get("Query") or args.get("q") or ""
        tag = "Web Search"
        if query:
            clean_q = _truncate(query, max_len=36)
            return (f'Search: "{clean_q}"', tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Searching the web...", tag)

    if norm_name in ("read_url_content", "fetch_web_page", "read_browser_page", "fetch_url"):
        url = args.get("Url") or args.get("url") or ""
        tag = "Reading Web"
        if url:
            clean_url = re.sub(r"^https?://(?:www\.)?", "", str(url))
            return (f"Fetching: {_truncate(clean_url, 38)}", tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Reading web page...", tag)

    # Case H: MCP Tools
    if norm_name in ("call_mcp_tool",) or norm_name.startswith("mcp_"):
        server = args.get("ServerName") or (norm_name.split("_")[1] if "_" in norm_name else "")
        tool = args.get("ToolName") or (norm_name.split("_", 2)[2] if norm_name.count("_") >= 2 else norm_name)
        tag = "MCP Tool"
        if server and tool:
            return (f"MCP: {server} -> {tool}", tag)
        elif tool:
            return (f"MCP: {tool}", tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Running MCP tool...", tag)

    # Case I: Subagent Invocation
    if norm_name in ("invoke_subagent", "dispatch_subagent"):
        subagents = args.get("Subagents", [])
        role = ""
        if isinstance(subagents, list) and subagents and isinstance(subagents[0], dict):
            role = subagents[0].get("Role") or subagents[0].get("TypeName") or ""
        if not role:
            role = args.get("Role") or args.get("TypeName") or ""
        tag = "Subagent"
        if role:
            return (f"Subagent: {_truncate(role, 36)}", tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Invoking subagent...", tag)

    # Case J: Task Management
    if norm_name in ("manage_task", "schedule"):
        action = args.get("Action") or args.get("action") or ""
        task_id = args.get("TaskId") or args.get("task_id") or ""
        prompt = args.get("Prompt") or ""
        tag = "Background Task"
        if action and task_id:
            return (f"Task: {action} {_clean_path(task_id)[:16]}", tag)
        elif prompt:
            return (f"Schedule: {_truncate(prompt, 36)}", tag)
        if tool_action:
            return (_truncate(tool_action, 48), tag)
        return ("Managing tasks...", tag)

    # Case K: Fallback for any other custom tools
    tag = "Running Tool"
    if tool_action and tool_action.lower() not in (f"running {tool_name}", f"running {norm_name}", "running tool"):
        return (_truncate(tool_action, 48), tag)

    # Clean the tool name (e.g. generate_image -> Generate Image)
    pretty_name = tool_name.replace("_", " ").title()
    return (f"Running {pretty_name}...", tag)


METADATA_IGNORE_PATTERNS = [
    r"^Created At:\s*\d{4}",
    r"^Completed At:\s*\d{4}",
    r"^Task logs are available at:",
    r"^YOU MUST TAKE ONE OF THE FOLLOWING",
    r"^DO NOTHING ELSE",
    r"^Tool is running as a background task",
    r"^The command exited with code",
    r"^Last progress:\s*\d+",
    r"^Task id\s+",
    r"^Task:\s+",
    r"^Status:\s*(RUNNING|DONE|ERROR)",
    r"^Log:\s*/",
    r"^Log output:",
    r"^<truncated\s+\d+",
    r"^Output:\s*$",
    r"^The following code has been modified",
    r"^Showing lines \d+ to \d+",
    r"^Total Lines:\s*\d+",
    r"^Total Bytes:\s*\d+",
    r"^File Path:\s*`file://",
]


def extract_log_summary(content: str, max_chars: int = 50) -> Optional[str]:
    """
    Extract a punchy, human-readable single-line log summary from tool output (e.g. pytest, compiler, git, etc.).
    Excludes harness/runner timestamps (Created At), scaffolding, and metadata headers.
    """
    if not content or not isinstance(content, str) or not content.strip():
        return None

    # Strip ANSI escape codes
    clean_text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", content).strip()
    if not clean_text:
        return None

    lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
    if not lines:
        return None

    # Filter out divider lines (=======, ------, ```) and runner metadata (Created At, Task logs, etc.)
    filtered_lines = []
    for l in lines:
        if re.match(r"^([=\-*_#~`]{3,}|\.{5,})$", l) or l.startswith("```"):
            continue
        if any(re.search(pat, l, re.IGNORECASE) for pat in METADATA_IGNORE_PATTERNS):
            continue
        filtered_lines.append(l)

    if not filtered_lines:
        return None

    # 1. Test results summary: e.g. "318 passed in 3.42s", "PASSED tests/test_hud.py", "1 failed, 210 passed"
    for l in reversed(filtered_lines):
        m = re.search(r"(\b\d+\s+(?:passed|failed|errors?|skipped)[^\n=]*)", l, re.IGNORECASE)
        if m:
            summary = m.group(1).strip()
            summary = re.sub(r"^[=\-*_#\s]+", "", summary).strip()
            return summary[:max_chars]

    # 2. Build / Success / Status patterns
    for l in reversed(filtered_lines):
        if re.search(r"\b(Build succeeded|Build complete|Finished\b|Successfully\b|Compiled\b|Generated\b|Created file\b|Updated file\b|Found\s+\d+\s+results?)\b", l, re.IGNORECASE):
            clean_l = re.sub(r"^[=\-*_#\s]+", "", l).strip()
            return clean_l[:max_chars]

    # 3. JSON Grep / Search result line
    for l in reversed(filtered_lines):
        if l.startswith('{"File":') or l.startswith('{"file":'):
            try:
                data = json.loads(l)
                f_path = data.get("File") or data.get("file") or ""
                if f_path:
                    fname = Path(f_path).name or f_path
                    return f"Match in {fname}"[:max_chars]
            except Exception:
                pass

    # 4. Explicit error pattern
    for l in reversed(filtered_lines):
        if re.search(r"\b(Error:|Exception:|FATAL:|FAILED)\b", l):
            clean_l = re.sub(r"^[=\-*_#\s]+", "", l).strip()
            return clean_l[:max_chars]

    # 5. Meaningful fallback: take the last non-trivial line
    for l in reversed(filtered_lines):
        clean_l = re.sub(r"^[=\-*_#\s]+", "", l).strip()
        # Skip trivial braces or punctuation
        if clean_l and clean_l not in ("{", "}", "[", "]", "(", ")", ";"):
            return clean_l[:max_chars]

    return None
