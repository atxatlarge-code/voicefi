"""
OpenAI Codex and ChatGPT Desktop lifecycle hook and MCP integration for VoiceFi.
Provides automatic MCP server registration in ~/.codex/config.toml,
CLI discovery, and lifecycle hook handling.
"""

import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts import get_tts_engine
from voicefi.tts.base import (
    set_cross_process_hud_state,
    clear_cross_process_hud_state,
    escape_to_stop_speech,
)
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.integrations.conversations import (
    claim_turn,
    save_session_cookie,
    pop_mobile_turn_origin,
    peek_mobile_turn_origin,
    get_claimed_turn_origin,
    has_active_companion_client,
    mark_turn_spoken_on_mac,
    clean_user_message,
    ConversationInfo,
)
from voicefi.integrations.injector import inject_text_to_chatgpt


def get_codex_cli_path() -> Optional[str]:
    """Find the path to the Codex CLI binary."""
    candidates = [
        Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
        Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex",
        Path.home() / ".codex" / "bin" / "codex",
    ]
    for c in candidates:
        if c.is_file() and os.access(str(c), os.X_OK):
            return str(c)
    w = shutil.which("codex")
    if w:
        return w
    return None


def execute_codex_cli(
    prompt: str,
    conv_id: Optional[str] = None,
    cwd: Optional[Path] = None,
    origin: str = "desktop",
    async_execution: bool = True,
    from_conv_id: Optional[str] = None,
    from_engine: Optional[str] = None,
    include_envelope: bool = False,
    timeout: int = 300,
) -> Any:
    """
    Execute Codex CLI non-interactively in headless mode.
    Resumes an existing session if conv_id matches a thread, or launches a new session.
    """
    from voicefi.integrations.injector import DispatchResult
    from voicefi.integrations.conversations import (
        save_session_cookie,
        set_mobile_turn_origin,
        record_agent_route,
        load_session_cookie,
    )

    cli_path = get_codex_cli_path()
    if not cli_path:
        return DispatchResult(
            success=False,
            delivery_type="none",
            error="Codex CLI binary not found",
            engine="codex",
        )

    clean_text = prompt.strip()
    canonical_id = conv_id
    clean_tid = None
    if conv_id:
        clean_tid = conv_id.replace("codex_", "").strip()
        if not canonical_id.startswith("codex_"):
            canonical_id = f"codex_{canonical_id}"
    else:
        canonical_id = f"codex_session_{int(time.time())}"

    if include_envelope and from_conv_id:
        clean_text = f"""[From: {from_engine.capitalize() if from_engine else 'Antigravity'} | Conversation: {from_conv_id}]
{clean_text}

💡 To return your findings to Antigravity, run:
vifi send --to antigravity --reply "Your findings summary"
# or:
curl -s -X POST http://localhost:5141/api/send -H "Content-Type: application/json" -d '{{"text": "Your findings summary", "conv_id": "{from_conv_id}", "engine": "antigravity", "sender_name": "Codex"}}'"""

    if from_conv_id:
        record_agent_route(
            from_engine=from_engine or "antigravity",
            from_conv_id=from_conv_id,
            to_engine="codex",
            to_conv_id=canonical_id,
        )

    if origin == "mobile":
        set_mobile_turn_origin(canonical_id)
        if clean_tid:
            set_mobile_turn_origin(clean_tid)

    # Resolve active workspace
    resolved_cwd = cwd
    if not resolved_cwd or str(resolved_cwd) == str(Path.home()):
        cookie = load_session_cookie()
        if cookie and cookie.get("workspacePath") and Path(cookie["workspacePath"]).is_dir():
            resolved_cwd = Path(cookie["workspacePath"])
        elif (Path.cwd() / "pyproject.toml").is_file() or (Path.cwd() / ".git").is_dir():
            resolved_cwd = Path.cwd()

    save_session_cookie(
        conv_id=canonical_id,
        title=f"Codex ({clean_tid[:8]})" if clean_tid else "Codex Session",
        workspace_path=str(resolved_cwd or Path.cwd()),
        engine="codex",
    )

    def _worker():
        try:
            cmd = [cli_path, "exec"]
            # Check if clean_tid is valid UUID
            is_uuid = False
            if clean_tid:
                uuid_match = re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", clean_tid, re.I)
                is_uuid = bool(uuid_match)

            if is_uuid:
                cmd.extend(["resume", clean_tid, clean_text])
            else:
                cmd.append(clean_text)

            cmd.append("--json")
            cmd.append("--skip-git-repo-check")
            if resolved_cwd:
                cmd.extend(["-C", str(resolved_cwd)])

            env = dict(os.environ)
            env["TERM"] = "xterm-256color"

            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(resolved_cwd or Path.cwd()),
                timeout=timeout,
            )
            print(f"[Codex CLI] Exec finished with code {proc.returncode}")

            if proc.returncode == 0:
                last_msg = ""
                session_path = None
                if proc.stdout:
                    for line in proc.stdout.strip().split("\n"):
                        try:
                            item = json.loads(line)
                            pld = item.get("payload", {})
                            if item.get("type") == "task_complete" or pld.get("type") == "task_complete":
                                last_msg = pld.get("last_agent_message") or ""
                            elif pld.get("type") == "item_completed" and pld.get("item", {}).get("type") == "AgentMessage":
                                parts = [
                                    c.get("text", "")
                                    for c in pld.get("item", {}).get("content", [])
                                    if isinstance(c, dict) and c.get("text")
                                ]
                                if parts:
                                    last_msg = " ".join(parts).strip()
                            if item.get("session_path"):
                                session_path = item["session_path"]
                        except Exception:
                            pass

                try:
                    payload = {
                        "thread_id": clean_tid or canonical_id,
                        "conversationId": canonical_id,
                        "agent": "codex",
                    }
                    if last_msg:
                        payload["last-assistant-message"] = last_msg
                    if session_path:
                        payload["session_path"] = session_path
                    handle_codex_stop_hook(payload)
                except Exception as hook_err:
                    print(f"[Codex CLI] Hook execution error: {hook_err}", file=sys.stderr)
        except Exception as e:
            print(f"[Codex CLI] Execution error: {e}", file=sys.stderr)

    if async_execution:
        th = threading.Thread(target=_worker, daemon=True, name=f"CodexExec-{canonical_id[:16]}")
        th.start()
        return DispatchResult(
            success=True,
            delivery_type="headless",
            target_conv_id=canonical_id,
            engine="codex",
        )
    else:
        _worker()
        return DispatchResult(
            success=True,
            delivery_type="headless",
            target_conv_id=canonical_id,
            engine="codex",
        )


def install_codex_mcp(
    bin_path: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> bool:
    """
    Register VoiceFi MCP server in ~/.codex/config.toml for Codex and ChatGPT Desktop.
    Uses the official codex CLI if available, with TOML file update fallback.
    """
    codex_home = Path.home() / ".codex"
    target_config = config_path or (codex_home / "config.toml")
    codex_home.mkdir(parents=True, exist_ok=True)

    executable = bin_path or shutil.which("voicefi") or shutil.which("vifi") or "voicefi"

    # 1. Try CLI registration first if codex binary is available
    cli_path = get_codex_cli_path()
    if cli_path:
        try:
            res = subprocess.run(
                [cli_path, "mcp", "add", "voicefi", "--", executable, "mcp"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

    # 2. Fallback to editing config.toml directly
    try:
        content = ""
        if target_config.is_file():
            content = target_config.read_text(encoding="utf-8")

        if "[mcp_servers.voicefi]" not in content:
            block = f'\n[mcp_servers.voicefi]\ncommand = "{executable}"\nargs = ["mcp"]\n'
            target_config.write_text(content + block, encoding="utf-8")
        return True
    except Exception as e:
        print(f"[Codex] Error registering MCP in config.toml: {e}", file=sys.stderr)
        return False


def install_codex_hook(
    bin_path: Optional[str] = None,
    hooks_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Register VoiceFi Stop hook in ~/.codex/hooks.json and ~/.codex/config.toml (notify).
    """
    codex_home = Path.home() / ".codex"
    target_hooks = hooks_path or (codex_home / "hooks.json")
    target_config = config_path or (codex_home / "config.toml")
    codex_home.mkdir(parents=True, exist_ok=True)

    executable = bin_path or shutil.which("voicefi") or shutil.which("vifi") or "voicefi"
    hook_command = f"{executable} hook --agent codex"

    # 1. Update ~/.codex/hooks.json
    data: Dict[str, Any] = {}
    if target_hooks.is_file():
        try:
            with open(target_hooks, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}

    if "hooks" not in data or not isinstance(data["hooks"], dict):
        data["hooks"] = {}

    stop_hooks = data["hooks"].get("Stop", [])
    if not isinstance(stop_hooks, list):
        stop_hooks = []

    has_voicefi = False
    for group in stop_hooks:
        if isinstance(group, dict):
            for h in group.get("hooks", []):
                if isinstance(h, dict) and "voicefi" in h.get("command", ""):
                    h["command"] = hook_command
                    has_voicefi = True

    if not has_voicefi:
        stop_hooks.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command,
                        "timeout": 60,
                    }
                ]
            }
        )

    data["hooks"]["Stop"] = stop_hooks

    temp_file = target_hooks.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, target_hooks)

    # 2. Update notify in ~/.codex/config.toml
    try:
        if target_config.is_file():
            toml_text = target_config.read_text(encoding="utf-8")
            notify_entry = f'notify = [\n    "{executable}",\n    "hook",\n    "--agent",\n    "codex",\n    "turn-ended",\n]\n'
            import re

            if re.search(r"notify\s*=\s*\[[^\]]*\]", toml_text):
                toml_text = re.sub(r"notify\s*=\s*\[[^\]]*\]\s*", notify_entry, toml_text, count=1)
            else:
                toml_text = notify_entry + toml_text
            target_config.write_text(toml_text, encoding="utf-8")
    except Exception as e:
        print(f"[Codex] Notice updating notify in config.toml: {e}", file=sys.stderr)

    return target_hooks


def remove_codex_hook(
    hooks_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> bool:
    """Remove VoiceFi hooks from ~/.codex/hooks.json and ~/.codex/config.toml."""
    codex_home = Path.home() / ".codex"
    target_hooks = hooks_path or (codex_home / "hooks.json")
    target_config = config_path or (codex_home / "config.toml")

    # 1. Clean hooks.json
    if target_hooks.is_file():
        try:
            with open(target_hooks, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            if "hooks" in data and "Stop" in data["hooks"]:
                stop_hooks = data["hooks"]["Stop"]
                new_stop = []
                for group in stop_hooks:
                    if isinstance(group, dict):
                        inner = [
                            h
                            for h in group.get("hooks", [])
                            if isinstance(h, dict) and "voicefi" not in h.get("command", "")
                        ]
                        if inner:
                            group["hooks"] = inner
                            new_stop.append(group)
                    else:
                        new_stop.append(group)
                data["hooks"]["Stop"] = new_stop

            temp_file = target_hooks.with_suffix(".json.tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, target_hooks)
        except Exception:
            pass

    # 2. Clean notify from config.toml if pointing to voicefi
    if target_config.is_file():
        try:
            toml_text = target_config.read_text(encoding="utf-8")
            import re

            if "voicefi" in toml_text:
                toml_text = re.sub(r"notify\s*=\s*\[[^\]]*voicefi[^\]]*\]\s*", "", toml_text)
                target_config.write_text(toml_text, encoding="utf-8")
        except Exception:
            pass

    return True


_CODEX_SESSIONS_CACHE: Dict[str, Tuple[float, ConversationInfo]] = {}


def find_recent_codex_sessions(base_dir: Optional[Path] = None, limit: int = 10) -> List[Path]:
    """
    Find recently modified Codex rollout JSONL files across ~/.codex/sessions.
    Prioritizes ~/.codex/state_5.sqlite database for authoritative thread recency,
    falling back to filesystem scanning of ~/.codex/sessions/**/*.jsonl.
    """
    codex_dir = base_dir or (Path.home() / ".codex")
    if not codex_dir.is_dir():
        return []

    candidates: List[Tuple[float, Path]] = []
    seen_paths = set()

    # 1. Query SQLite thread database for fast, sorted lookup
    sqlite_path = codex_dir / "state_5.sqlite"
    if sqlite_path.is_file():
        try:
            conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=2.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, rollout_path, updated_at FROM threads WHERE archived = 0 ORDER BY updated_at DESC LIMIT ?",
                (max(limit * 3, 30),),
            )
            for row in cursor.fetchall():
                _, rpath, updated_at = row
                if rpath:
                    p = Path(rpath)
                    if p.is_file() and p.stat().st_size > 0:
                        resolved_mtime = float(updated_at or p.stat().st_mtime)
                        candidates.append((resolved_mtime, p))
                        seen_paths.add(str(p.resolve()))
            conn.close()
        except Exception:
            pass

    # 2. Filesystem search fallback
    sessions_dir = codex_dir / "sessions"
    if sessions_dir.is_dir():
        try:
            for p in sessions_dir.glob("**/*.jsonl"):
                if p.is_file() and p.stat().st_size > 0:
                    rp = str(p.resolve())
                    if rp not in seen_paths:
                        candidates.append((p.stat().st_mtime, p))
                        seen_paths.add(rp)
        except Exception:
            pass

    # 3. Check archived_sessions if needed
    archived_dir = codex_dir / "archived_sessions"
    if archived_dir.is_dir() and len(candidates) < limit:
        try:
            for p in archived_dir.glob("**/*.jsonl"):
                if p.is_file() and p.stat().st_size > 0:
                    rp = str(p.resolve())
                    if rp not in seen_paths:
                        candidates.append((p.stat().st_mtime, p))
                        seen_paths.add(rp)
        except Exception:
            pass

    if not candidates:
        return []

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in candidates[:limit]]


def find_latest_codex_session(base_dir: Optional[Path] = None) -> Optional[Path]:
    """Find the single most recent Codex session rollout file."""
    sessions = find_recent_codex_sessions(base_dir=base_dir, limit=1)
    return sessions[0] if sessions else None


def parse_codex_session(session_path: Path) -> Optional[ConversationInfo]:
    """Parse a Codex session JSONL rollout file into ConversationInfo with mtime cache."""
    try:
        p = Path(session_path)
        if not p.is_file():
            return None
        mtime = p.stat().st_mtime

        # Extract session UUID from filename or stem
        uuid_match = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            p.stem,
            re.IGNORECASE,
        )
        session_id = uuid_match.group(1) if uuid_match else p.stem
        conv_id = f"codex_{session_id}" if not session_id.startswith("codex_") else session_id

        if conv_id in _CODEX_SESSIONS_CACHE:
            cached_mtime, cached_info = _CODEX_SESSIONS_CACHE[conv_id]
            if cached_mtime == mtime:
                return cached_info

        lines = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(line)

        if not lines:
            return None

        project_name = ""
        cwd = None
        first_user_text = ""
        last_user_text = ""
        last_assistant_text = ""
        last_msg_type = ""
        has_tool_calls_pending = False

        for line in lines:
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    continue
                t = obj.get("type")
                pld = obj.get("payload", {})
                if not isinstance(pld, dict):
                    continue
                pt = pld.get("type")

                if t == "session_meta" and not cwd:
                    cwd = pld.get("cwd")
                    if cwd:
                        project_name = Path(cwd).name

                if pt == "user_message":
                    msg = pld.get("message", "")
                    if msg and not str(msg).startswith("<"):
                        last_msg_type = "user"
                        cleaned = clean_user_message(str(msg))
                        if cleaned:
                            last_user_text = cleaned
                            if not first_user_text:
                                first_user_text = cleaned
                elif pt == "message" and pld.get("role") == "user":
                    parts = [
                        c.get("text", "")
                        for c in pld.get("content", [])
                        if isinstance(c, dict) and c.get("text")
                    ]
                    text = " ".join(parts).strip()
                    if text and not text.startswith("<"):
                        last_msg_type = "user"
                        cleaned = clean_user_message(text)
                        if cleaned:
                            last_user_text = cleaned
                            if not first_user_text:
                                first_user_text = cleaned
                elif pt == "custom_tool_call":
                    has_tool_calls_pending = True
                elif pt == "custom_tool_call_output":
                    has_tool_calls_pending = False
                elif pt == "task_complete":
                    last_msg_type = "assistant"
                    has_tool_calls_pending = False
                    if pld.get("last_agent_message"):
                        last_assistant_text = str(pld["last_agent_message"])
                elif pt == "item_completed":
                    item = pld.get("item", {})
                    if item.get("type") == "AgentMessage":
                        parts = [
                            c.get("text", "")
                            for c in item.get("content", [])
                            if isinstance(c, dict) and c.get("text")
                        ]
                        text = " ".join(parts).strip()
                        if text and not text.startswith("["):
                            last_msg_type = "assistant"
                            last_assistant_text = text
                elif pt == "message" and pld.get("role") == "assistant":
                    parts = [
                        c.get("text", "")
                        for c in pld.get("content", [])
                        if isinstance(c, dict) and c.get("text")
                    ]
                    text = " ".join(parts).strip()
                    if text and not text.startswith("["):
                        last_msg_type = "assistant"
                        last_assistant_text = text
            except Exception:
                continue

        # Look for title in SQLite database first
        title = ""
        try:
            sqlite_path = Path.home() / ".codex" / "state_5.sqlite"
            if sqlite_path.is_file():
                conn = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True, timeout=1.0)
                cur = conn.cursor()
                clean_tid = session_id.replace("codex_", "")
                cur.execute("SELECT title, cwd FROM threads WHERE id = ?", (clean_tid,))
                row = cur.fetchone()
                if row and row[0]:
                    title = row[0].strip()
                    if not cwd and row[1]:
                        cwd = row[1]
                        project_name = Path(cwd).name
                conn.close()
        except Exception:
            pass

        # Derive human-friendly title if SQLite didn't provide one
        if not title:
            if first_user_text:
                clean_first = clean_user_message(first_user_text)
                first_line = clean_first.split("\n")[0].strip() if clean_first else first_user_text.split("\n")[0].strip()
                clean_first = first_line[:40] + ("..." if len(first_line) > 40 else "")
                if project_name:
                    title = f"{project_name}: {clean_first}"
                else:
                    title = clean_first
            else:
                title = f"{project_name} ({session_id[:8]})" if project_name else f"Codex ({session_id[:8]})"

        status = "idle"
        if last_msg_type == "user" or has_tool_calls_pending:
            status = "agent_working"
        elif last_msg_type == "assistant" or last_assistant_text:
            status = "waiting_for_user"

        cleaned_agent_text = ""
        if last_assistant_text:
            cleaned_agent_text = clean_markdown_for_speech(last_assistant_text, max_words=60)

        info = ConversationInfo(
            id=conv_id,
            title=title,
            status=status,
            mtime=mtime,
            last_agent_text=cleaned_agent_text,
            last_user_text=last_user_text,
            transcript_path=p,
            engine="codex",
            project_name=project_name,
            cwd=cwd,
        )
        _CODEX_SESSIONS_CACHE[conv_id] = (mtime, info)
        return info
    except Exception:
        return None


def parse_full_codex_conversation_details(session_path: Path) -> Dict[str, Any]:
    """Parse full turns, tool calls, and assistant responses from a Codex session rollout."""
    p = Path(session_path)
    uuid_match = re.search(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        p.stem,
        re.IGNORECASE,
    )
    session_id = uuid_match.group(1) if uuid_match else p.stem
    conv_id = f"codex_{session_id}" if not session_id.startswith("codex_") else session_id
    mtime = p.stat().st_mtime if p.is_file() else time.time()

    info = parse_codex_session(p)
    title = info.title if info else f"Codex ({session_id[:8]})"
    status = info.status if info else "idle"
    cwd = info.cwd if info else None

    turns: List[Dict[str, Any]] = []
    current_turn: Optional[Dict[str, Any]] = None

    lines = []
    if p.is_file():
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
        except Exception:
            pass

    for idx, line in enumerate(lines):
        try:
            obj = json.loads(line)
        except Exception:
            continue

        if not isinstance(obj, dict):
            continue

        t = obj.get("type")
        pld = obj.get("payload", {})
        if not isinstance(pld, dict):
            continue
        pt = pld.get("type")
        created_at = obj.get("timestamp") or time.time()

        user_text = ""
        if pt == "user_message":
            msg = pld.get("message", "")
            if msg and not str(msg).startswith("<"):
                user_text = str(msg)
        elif pt == "message" and pld.get("role") == "user":
            parts = [
                c.get("text", "")
                for c in pld.get("content", [])
                if isinstance(c, dict) and c.get("text")
            ]
            text = " ".join(parts).strip()
            if text and not text.startswith("<"):
                user_text = text

        if user_text:
            if current_turn and (
                current_turn.get("user_message") == user_text
                or (not current_turn.get("agent_response") and not current_turn.get("agent_steps"))
            ):
                current_turn["user_message"] = clean_user_message(user_text) if user_text else "User prompt"
                current_turn["raw_user_message"] = user_text
                current_turn["user_timestamp"] = created_at
                continue

            if current_turn:
                turns.append(current_turn)

            current_turn = {
                "turn_id": len(turns) + 1,
                "user_message": clean_user_message(user_text) if user_text else "User prompt",
                "raw_user_message": user_text,
                "user_timestamp": created_at,
                "agent_steps": [],
                "agent_response": "",
                "agent_role": "codex",
                "status": "working",
                "completed": False,
            }
            continue

        if current_turn is not None:
            if pt == "custom_tool_call":
                t_name = pld.get("name", "tool")
                raw_inp = pld.get("input", "")
                summary = f"{t_name} {str(raw_inp)[:40]}".strip()
                current_turn["agent_steps"].append(
                    {
                        "step_index": idx,
                        "type": "tool_call",
                        "tool_name": t_name,
                        "summary": summary,
                        "action": t_name,
                        "args": {"input": raw_inp},
                        "status": "DONE",
                        "output": None,
                        "created_at": created_at,
                        "call_id": pld.get("call_id") or pld.get("id"),
                    }
                )
            elif pt == "custom_tool_call_output":
                cid = pld.get("call_id") or pld.get("id")
                out_raw = pld.get("output", "")
                out_str = ""
                if isinstance(out_raw, list):
                    out_str = " ".join(
                        [b.get("text", "") for b in out_raw if isinstance(b, dict) and b.get("text")]
                    )
                elif isinstance(out_raw, str):
                    out_str = out_raw
                if current_turn["agent_steps"]:
                    for s in reversed(current_turn["agent_steps"]):
                        if s.get("output") is None and (not cid or s.get("call_id") == cid):
                            if out_str and len(out_str) > 2500:
                                s["output"] = (
                                    out_str[:2500]
                                    + f"\n\n... [{len(out_str) - 2500:,} more characters truncated]"
                                )
                            else:
                                s["output"] = out_str
                            break
            elif pt == "task_complete":
                current_turn["status"] = "done"
                current_turn["completed"] = True
                if pld.get("last_agent_message"):
                    current_turn["agent_response"] = str(pld["last_agent_message"])
            elif pt == "item_completed":
                item = pld.get("item", {})
                if item.get("type") == "AgentMessage":
                    parts = [
                        c.get("text", "")
                        for c in item.get("content", [])
                        if isinstance(c, dict) and c.get("text")
                    ]
                    text = " ".join(parts).strip()
                    if text and not text.startswith("["):
                        current_turn["agent_response"] = text
                        current_turn["status"] = "done"
                        current_turn["completed"] = True
            elif pt == "message" and pld.get("role") == "assistant":
                parts = [
                    c.get("text", "")
                    for c in pld.get("content", [])
                    if isinstance(c, dict) and c.get("text")
                ]
                text = " ".join(parts).strip()
                if text and not text.startswith("["):
                    current_turn["agent_response"] = text
                    current_turn["status"] = "done"
                    current_turn["completed"] = True

    if current_turn:
        turns.append(current_turn)

    # Artifacts: Search for visualizations or outputs associated with this session
    artifacts = []
    viz_candidates = [
        Path.home() / ".codex" / "visualizations",
    ]
    if cwd:
        viz_candidates.append(Path(cwd) / "outputs")
    for v_dir in viz_candidates:
        if v_dir.is_dir():
            try:
                for item in v_dir.glob(f"**/*{session_id}*"):
                    if item.is_file():
                        artifacts.append(
                            {
                                "name": item.name,
                                "path": str(item),
                                "size": item.stat().st_size,
                                "mtime": item.stat().st_mtime,
                                "extension": item.suffix.lstrip("."),
                                "is_markdown": item.suffix in (".md", ".markdown"),
                            }
                        )
            except Exception:
                pass

    return {
        "id": conv_id,
        "title": title,
        "status": status,
        "mtime": mtime,
        "engine": "codex",
        "turns": turns,
        "artifacts": artifacts,
        "plan_info": None,
        "total_steps": len(lines),
    }


def extract_latest_codex_summary(
    session_path: Optional[Path] = None, max_words: int = 60
) -> str:
    """Extract and summarize the latest assistant response from a Codex session rollout."""
    target_path = session_path or find_latest_codex_session()
    if not target_path or not target_path.is_file():
        return ""

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]

        for line in reversed(lines):
            try:
                obj = json.loads(line)
                pld = obj.get("payload", {})
                if not isinstance(pld, dict):
                    continue
                pt = pld.get("type")
                if pt == "task_complete" and pld.get("last_agent_message"):
                    return clean_markdown_for_speech(
                        str(pld["last_agent_message"]), max_words=max_words
                    )
                if pt == "item_completed":
                    item = pld.get("item", {})
                    if item.get("type") == "AgentMessage":
                        parts = [
                            c.get("text", "")
                            for c in item.get("content", [])
                            if isinstance(c, dict) and c.get("text")
                        ]
                        text = " ".join(parts).strip()
                        if text and not text.startswith("["):
                            return clean_markdown_for_speech(text, max_words=max_words)
                if pt == "message" and pld.get("role") == "assistant":
                    parts = [
                        c.get("text", "")
                        for c in pld.get("content", [])
                        if isinstance(c, dict) and c.get("text")
                    ]
                    text = " ".join(parts).strip()
                    if text and not text.startswith("["):
                        return clean_markdown_for_speech(text, max_words=max_words)
            except Exception:
                continue
    except Exception:
        pass
    return ""


def handle_codex_stop_hook(
    payload: Dict[str, Any],
    config: Optional[VoiceFiConfig] = None,
) -> Dict[str, Any]:
    """
    Handle OpenAI Codex turn-completion Stop / notify hook.
    1. Extracts latest assistant message
    2. Speaks aloud in Codex's voice persona (Emma)
    3. Auto-opens microphone with VAD and transcribes if auto_listen enabled
    4. Injects voice transcription into ChatGPT Desktop / Codex prompt
    """
    cfg = config or load_config()

    # Guard: Instant kill-switch check
    if (
        not cfg.enabled
        or not getattr(cfg.hooks, "enabled", True)
        or not getattr(cfg.hooks, "codex", True)
    ):
        return {"status": "paused"}
    if not getattr(cfg.integrations, "codex", True) and not getattr(
        cfg.integrations, "chatgpt", True
    ):
        return {"status": "disabled"}

    codex_cfg = getattr(cfg, "codex", None)
    read_aloud = getattr(codex_cfg, "read_summary_aloud", True) if codex_cfg else True
    auto_listen = getattr(codex_cfg, "auto_listen", False) if codex_cfg else False
    max_words = getattr(codex_cfg, "max_spoken_words", 60) if codex_cfg else 60

    if not auto_listen and not read_aloud:
        return {"status": "disabled"}

    # Extract summary text from payload or session file
    text_to_speak = ""
    thread_id = "codex_active"
    session_file: Optional[Path] = None

    if isinstance(payload, dict):
        if payload.get("session_path"):
            session_file = Path(payload["session_path"])
        thread_id = str(
            payload.get("thread-id")
            or payload.get("thread_id")
            or payload.get("conversationId")
            or "codex_active"
        )
        if payload.get("last-assistant-message"):
            text_to_speak = str(payload["last-assistant-message"])
        elif payload.get("message"):
            text_to_speak = str(payload["message"])
        elif payload.get("text"):
            text_to_speak = str(payload["text"])
        elif payload.get("content"):
            text_to_speak = str(payload["content"])

    if not session_file and thread_id and thread_id != "codex_active":
        # Look up rollout path from state_5.sqlite if thread_id is known
        try:
            codex_db = Path.home() / ".codex" / "state_5.sqlite"
            if codex_db.is_file():
                conn = sqlite3.connect(f"file:{codex_db}?mode=ro", uri=True, timeout=1.0)
                cur = conn.cursor()
                clean_tid = thread_id.replace("codex_", "")
                cur.execute("SELECT rollout_path FROM threads WHERE id = ?", (clean_tid,))
                r = cur.fetchone()
                if r and r[0] and Path(r[0]).is_file():
                    session_file = Path(r[0])
                conn.close()
        except Exception:
            pass

    if not session_file:
        session_file = find_latest_codex_session()

    if not text_to_speak:
        text_to_speak = extract_latest_codex_summary(
            session_path=session_file,
            max_words=max_words,
        )

    if not text_to_speak:
        return {"status": "empty_turn"}

    # Clean markdown for natural speech
    cleaned = clean_markdown_for_speech(text_to_speak)
    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]) + "..."

    # Deduplicate turn
    if (not thread_id or thread_id == "codex_active") and session_file:
        uuid_match = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            session_file.stem,
            re.IGNORECASE,
        )
        thread_id = uuid_match.group(1) if uuid_match else session_file.stem

    cid_key = f"codex_{thread_id}" if not thread_id.startswith("codex_") else thread_id
    if not claim_turn(thread_id, cleaned, delivered_via="hook") and not claim_turn(cid_key, cleaned, delivered_via="hook"):
        return {"status": "skipped_duplicate"}

    # Update session cookie so Mobile Companion knows Codex is the active agent
    session_title = f"Codex ({thread_id[:8]})"
    parsed_info = parse_codex_session(session_file) if session_file else None
    if parsed_info and parsed_info.title:
        session_title = parsed_info.title

    save_session_cookie(
        conv_id=cid_key,
        transcript_path=str(session_file) if session_file else None,
        title=session_title,
        engine="codex",
    )

    print(f'\n✳️ [Codex Hook] Turn complete: "{cleaned}"')

    try:
        from voicefi.audio.echo_canceller import record_agent_spoken

        record_agent_spoken(cleaned)
    except Exception:
        pass

    # Check Mobile Companion audio routing
    routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
    mute_mac_active = getattr(
        getattr(cfg, "companion", None), "mute_mac_when_companion_active", True
    )
    is_mobile = (
        get_claimed_turn_origin(thread_id, cleaned) == "mobile"
        or get_claimed_turn_origin(cid_key, cleaned) == "mobile"
        or peek_mobile_turn_origin(thread_id)
        or peek_mobile_turn_origin(cid_key)
        or pop_mobile_turn_origin(thread_id)
        or pop_mobile_turn_origin(cid_key)
    )

    if routing == "phone_only":
        return {"status": "phone_only", "agent": "codex"}
    elif routing == "origin_only":
        if is_mobile:
            return {"status": "mobile_handled", "agent": "codex"}
    elif routing == "smart":
        if is_mobile:
            if mute_mac_active:
                return {"status": "mobile_handled", "agent": "codex"}
        elif mute_mac_active and has_active_companion_client(require_mobile=True):
            return {"status": "mac_muted", "agent": "codex"}

    # Check meeting & media detection
    from voicefi.audio.meeting_detection import is_user_on_call

    if is_user_on_call():
        print("[Codex Hook] User is on a call. Skipping spoken feedback and auto-listen.")
        return {"status": "on_call", "agent": "codex"}

    respect_media = getattr(getattr(cfg, "tts", None), "respect_media_playback", True)
    if respect_media:
        try:
            from voicefi.audio.media_detection import is_active_media_playing, wait_for_media_completion

            if is_active_media_playing():
                media_timeout = getattr(getattr(cfg, "tts", None), "media_pause_timeout", 600.0)
                cleared = wait_for_media_completion(max_wait_seconds=media_timeout)
                if not cleared:
                    print(
                        "[Codex Hook] 🎬 Media clip still playing after timeout. Skipping speech."
                    )
                    return {"status": "media_playing", "agent": "codex"}
        except Exception:
            pass

    # Speak the soundbite aloud using Codex's voice persona (Emma)
    hook_start_time = time.time()
    agent_name = (
        payload.get("agent")
        if isinstance(payload, dict) and payload.get("agent")
        else "codex"
    )
    voice_override = payload.get("voice") if isinstance(payload, dict) else None
    tts_engine = None
    if read_aloud:
        tts_engine = get_tts_engine(
            cfg,
            agent_name=agent_name,
            voice_override=voice_override,
            app_name="Codex",
            conv_id=thread_id,
        )
        try:
            set_cross_process_hud_state(
                "speaking",
                text=cleaned,
                agent_name=agent_name,
                persona_name=getattr(tts_engine, "voice", "Emma"),
                app_name="Codex",
                conv_id=thread_id,
            )
            with escape_to_stop_speech(
                agent_name=agent_name, app_name="Codex", conv_id=thread_id
            ):
                tts_engine.speak(cleaned, block=True)
            mark_turn_spoken_on_mac(thread_id, cleaned)
            mark_turn_spoken_on_mac(cid_key, cleaned)
        except Exception as e:
            print(f"[Codex Hook] Speech error: {e}", file=sys.stderr)
        finally:
            clear_cross_process_hud_state()

        from voicefi.tts.base import is_speech_interrupted

        if is_speech_interrupted(hook_start_time):
            clear_cross_process_hud_state()
            return {"status": "interrupted", "agent": "codex"}

    # If auto_listen is disabled, finish early
    if not auto_listen:
        if read_aloud:
            dur_ms = int((time.time() - hook_start_time) * 1000)
            try:
                from voicefi.telemetry import capture_voice_interaction

                capture_voice_interaction(
                    trigger="hook",
                    duration_ms=dur_ms,
                    success=True,
                    agent="codex",
                    voice=getattr(tts_engine, "voice", "Emma"),
                    chars_count=len(cleaned),
                )
            except Exception:
                pass
        return {"status": "spoken", "agent": "codex"}

    # Play start listening chime
    if cfg.audio_cues.enabled:
        play_chime(cfg.audio_cues.start_chime, block=False)

    # Record user response with VAD
    print("🎙️ Listening for response to Codex... (speak and then pause)")
    set_cross_process_hud_state(
        "listening",
        agent_name="codex",
        user_name=cfg.user_name,
        app_name="Codex",
        conv_id=thread_id,
    )
    recorder = AudioRecorder(
        sample_rate=cfg.vad.sample_rate,
        energy_threshold=cfg.vad.energy_threshold,
        silence_duration=cfg.vad.silence_duration,
        max_record_seconds=cfg.vad.max_record_seconds,
    )

    def _on_live(txt: str):
        set_cross_process_hud_state(
            "listening",
            text=txt,
            agent_name="codex",
            user_name=cfg.user_name,
            live_stream=True,
            app_name="Codex",
            conv_id=thread_id,
        )
        try:
            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

            UnifiedDynamicIslandHUD.get_instance().update_live_transcription(
                txt, user_name=cfg.user_name
            )
        except Exception:
            pass

    recorder.on_live_transcript = _on_live
    audio_path = recorder.record()
    clear_cross_process_hud_state()

    if is_speech_interrupted(hook_start_time):
        if audio_path and audio_path.exists():
            audio_path.unlink(missing_ok=True)
        return {"status": "cancelled"}

    if not audio_path or not audio_path.exists():
        print("⚠️ No speech captured.")
        return {"status": "no_audio"}

    # Transcribe speech
    print("⏳ Transcribing speech...")
    set_cross_process_hud_state(
        "thinking",
        text="Transcribing...",
        agent_name="codex",
        user_name=cfg.user_name,
        app_name="Codex",
        conv_id=thread_id,
    )
    stt_engine = get_stt_engine(cfg)
    try:
        transcribed_text = stt_engine.transcribe(audio_path)
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink(missing_ok=True)
    clear_cross_process_hud_state()

    if is_speech_interrupted(hook_start_time):
        return {"status": "cancelled"}

    if not transcribed_text or not transcribed_text.strip():
        print("⚠️ Empty transcription.")
        return {"status": "empty_transcript"}

    print(f'🗣️ User: "{transcribed_text}"')

    # Inject into ChatGPT / Codex Desktop
    auto_sub = getattr(codex_cfg, "auto_submit", False) if codex_cfg else False
    inject_text_to_chatgpt(transcribed_text, submit_enter=auto_sub)

    return {"status": "injected", "text": transcribed_text, "agent": "codex"}
