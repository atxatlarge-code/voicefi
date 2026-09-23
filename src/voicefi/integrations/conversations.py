"""
Conversation manager and tracker for Antigravity.
Discovers active conversations, parses topics and turn statuses, and tracks active focus targets.
"""

import fcntl
import glob
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from voicefi.integrations.tool_formatter import format_tool_details
from voicefi.integrations.turn_lock import (
    _normalize_turn_signature,
    is_pid_alive,
    claim_turn,
    mark_turn_completed,
    mark_turn_spoken_on_mac,
    claim_active_conversation_turn,
    get_claimed_turn_origin,
    get_turn_delivery_info,
    set_mobile_turn_origin,
    peek_mobile_turn_origin,
    pop_mobile_turn_origin,
    record_companion_heartbeat,
    has_active_companion_client,
    has_active_mobile_companion,
    clear_companion_heartbeat,
)


def get_session_cookie_path() -> Path:
    """Path to the persistent active Antigravity session cookie."""
    cookie_dir = Path.home() / ".voicefi"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    return cookie_dir / "active_session.json"




@dataclass
class PendingQuestion:
    conv_id: str
    question_text: str
    options: List[str]
    timestamp: float
    status: str = "pending"  # "pending", "answered", "dismissed"


def extract_choice_options(question_text: str) -> List[str]:
    """
    Extract candidate options from questions like:
    - 'Stage on Railway or ship straightaway?' -> ['stage on railway', 'ship straightaway']
    - '"Option A" or "Option B"' -> ['option a', 'option b']
    """
    if not question_text or not question_text.strip():
        return []

    raw = question_text.strip()
    is_question = raw.endswith("?") or bool(
        re.match(
            r"^(?:which|should we|shall we|do you want|would you like|would you prefer|choose|select)\b",
            raw,
            re.IGNORECASE,
        )
    )
    if not is_question:
        return []

    text = raw.rstrip("?.!")

    # 1. Numbered or bulleted markdown lists: "1. Option A\n2. Option B" or "- Option A\n- Option B"
    list_items = re.findall(r"(?:^|\n)\s*(?:\d+[\.\)]|[-*•])\s+([^\n]+)", raw)
    if len(list_items) >= 2:
        return [item.strip().lower() for item in list_items if len(item.strip()) > 1]

    # 2. Quoted choices: "foo" or "bar"
    quotes = re.findall(r'["\']([^"\']+)["\']', text)
    if len(quotes) >= 2:
        return [q.strip().lower() for q in quotes if q.strip()]

    # 3. Oxford comma & multi-choice 'or' split: "A, B, or C" / "A or B"
    if " or " in text.lower():
        tokens = re.split(r",\s*(?:or\s+)?|\s+or\s+", text, flags=re.IGNORECASE)
        clean_tokens = []
        for t in tokens:
            cleaned_t = re.sub(
                r"^(?:do you want to|would you like to|would you prefer to|should we|shall we|can we|do we|please choose:?)\s*",
                "",
                t.strip(),
                flags=re.IGNORECASE,
            ).strip()
            if cleaned_t and len(cleaned_t) > 1:
                clean_tokens.append(cleaned_t.lower())

        if len(clean_tokens) >= 2:
            # If the first token starts with a verb phrase like "deploy to " or "use " in a multi-item
            # list (>= 3 items) while subsequent tokens do not, strip that verb prefix so
            # "Should we deploy to AWS, GCP, or Azure?" yields ["aws", "gcp", "azure"]
            if len(clean_tokens) >= 3:
                prefix_match = re.match(
                    r"^(?:deploy to|connect to|switch to|use|run|test|build)\s+(.+)$",
                    clean_tokens[0],
                    re.IGNORECASE,
                )
                if prefix_match:
                    candidate_verb = clean_tokens[0].split()[0]
                    if not any(t.startswith(candidate_verb) for t in clean_tokens[1:]):
                        clean_tokens[0] = prefix_match.group(1).strip()

            return clean_tokens

    return []


_PENDING_QUESTIONS_FILE = Path("/tmp/voicefi_pending_questions.json")


def set_pending_question(
    conv_id: str,
    question_text: str,
    options: Optional[List[str]] = None,
) -> None:
    """Record an active clarifying question or choice waiting for user answer."""
    if not question_text:
        return

    opts = options if options is not None else extract_choice_options(question_text)
    data = {
        "conv_id": conv_id or "active",
        "question_text": question_text.strip(),
        "options": opts,
        "timestamp": time.time(),
        "status": "pending",
    }

    try:
        current: Dict[str, Any] = {}
        if _PENDING_QUESTIONS_FILE.is_file():
            try:
                current = json.loads(_PENDING_QUESTIONS_FILE.read_text())
            except Exception:
                current = {}
        cid_key = conv_id or "active"
        current[cid_key] = data
        current["_latest"] = data
        _PENDING_QUESTIONS_FILE.write_text(json.dumps(current, indent=2))
    except Exception:
        pass


def get_pending_question(
    conv_id: Optional[str] = None,
    max_age_seconds: float = 300.0,
) -> Optional[Dict[str, Any]]:
    """Retrieve active pending question for conversation if within age limit."""
    if not _PENDING_QUESTIONS_FILE.is_file():
        return None
    try:
        current = json.loads(_PENDING_QUESTIONS_FILE.read_text())
        data = current.get(conv_id) if conv_id else current.get("_latest")
        if not data:
            return None
        ts = float(data.get("timestamp", 0))
        if (time.time() - ts) <= max_age_seconds and data.get("status") == "pending":
            return data
    except Exception:
        pass
    return None


def resolve_pending_question(
    conv_id: Optional[str] = None,
    selected_option: Optional[str] = None,
) -> None:
    """Mark a pending question as resolved / answered."""
    if not _PENDING_QUESTIONS_FILE.is_file():
        return
    try:
        current = json.loads(_PENDING_QUESTIONS_FILE.read_text())
        cid_key = conv_id or "_latest"
        if cid_key in current:
            current[cid_key]["status"] = "answered"
            current[cid_key]["resolved_option"] = selected_option
        if "_latest" in current:
            current["_latest"]["status"] = "answered"
            current["_latest"]["resolved_option"] = selected_option
        _PENDING_QUESTIONS_FILE.write_text(json.dumps(current, indent=2))
    except Exception:
        pass


def clear_pending_question(conv_id: Optional[str] = None) -> None:
    """Clear pending question markers."""
    if not _PENDING_QUESTIONS_FILE.is_file():
        return
    try:
        if not conv_id:
            _PENDING_QUESTIONS_FILE.unlink(missing_ok=True)
        else:
            current = json.loads(_PENDING_QUESTIONS_FILE.read_text())
            current.pop(conv_id, None)
            if current.get("_latest", {}).get("conv_id") == conv_id:
                current.pop("_latest", None)
            _PENDING_QUESTIONS_FILE.write_text(json.dumps(current, indent=2))
    except Exception:
        pass





def save_session_cookie(
    conv_id: str,
    transcript_path: Optional[str] = None,
    title: Optional[str] = None,
    workspace_path: Optional[str] = None,
    engine: str = "antigravity",
) -> None:
    """Save active conversation metadata handshake ('cookie') to disk."""
    if not conv_id:
        return
    cookie_path = get_session_cookie_path()
    data = {
        "conversationId": conv_id,
        "conv_id": conv_id,
        "transcriptPath": str(transcript_path) if transcript_path else "",
        "title": title or "",
        "workspacePath": str(workspace_path) if workspace_path else "",
        "engine": engine,
        "updatedAt": time.time(),
    }
    try:
        tmp_file = cookie_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp_file.replace(cookie_path)
    except Exception as e:
        print(f"[ConversationTracker] Notice saving session cookie: {e}")


def load_session_cookie() -> Optional[Dict[str, Any]]:
    """Load the latest active Antigravity/Claude session cookie if present."""
    cookie_path = get_session_cookie_path()
    if not cookie_path.is_file():
        return None
    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if (
                data
                and isinstance(data, dict)
                and (data.get("conversationId") or data.get("conv_id"))
            ):
                cid = data.get("conversationId") or data.get("conv_id")
                data["conversationId"] = cid
                data["conv_id"] = cid
                return data
    except Exception:
        pass
    return None


_AGENT_ROUTES_FILE = Path("/tmp/voicefi_agent_routes.json")
_ROUTES_THREAD_LOCK = threading.RLock()


def record_agent_route(
    from_engine: str,
    from_conv_id: str,
    to_engine: str,
    to_conv_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record cross-agent dispatch route for bi-directional provenance and return routing.
    """
    if not from_engine or not from_conv_id:
        return

    route = {
        "from_engine": from_engine,
        "from_conv_id": str(from_conv_id),
        "to_engine": to_engine,
        "to_conv_id": str(to_conv_id) if to_conv_id else None,
        "timestamp": time.time(),
        "metadata": metadata or {},
    }

    with _ROUTES_THREAD_LOCK:
        try:
            _AGENT_ROUTES_FILE.parent.mkdir(parents=True, exist_ok=True)
            lock_path = _AGENT_ROUTES_FILE.with_suffix(".lock")
            with open(lock_path, "a+") as lock_fp:
                try:
                    fcntl.flock(lock_fp, fcntl.LOCK_EX)
                except Exception:
                    pass

                try:
                    current: List[Dict[str, Any]] = []
                    if _AGENT_ROUTES_FILE.is_file():
                        try:
                            raw = _AGENT_ROUTES_FILE.read_text(encoding="utf-8")
                            data = json.loads(raw)
                            if isinstance(data, list):
                                current = data
                        except Exception:
                            current = []

                    # Keep latest 20 routes within last 24h
                    cutoff = time.time() - 86400.0
                    current = [
                        r
                        for r in current
                        if isinstance(r, dict) and float(r.get("timestamp", 0)) > cutoff
                    ]
                    current.append(route)
                    if len(current) > 20:
                        current = current[-20:]

                    tmp_file = _AGENT_ROUTES_FILE.with_suffix(".tmp")
                    tmp_file.write_text(json.dumps(current, indent=2), encoding="utf-8")
                    tmp_file.replace(_AGENT_ROUTES_FILE)
                finally:
                    try:
                        fcntl.flock(lock_fp, fcntl.LOCK_UN)
                    except Exception:
                        pass
        except Exception as e:
            print(f"[ConversationTracker] Notice recording agent route: {e}")


def get_return_route(target_engine: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get the most recent origin route for returning messages to target_engine.
    E.g. If Claude wants to reply to Antigravity, finds the last route from Antigravity -> Claude.
    """
    if not _AGENT_ROUTES_FILE.is_file():
        return None

    with _ROUTES_THREAD_LOCK:
        lock_path = _AGENT_ROUTES_FILE.with_suffix(".lock")
        lock_fp = None
        try:
            if lock_path.parent.is_dir():
                lock_fp = open(lock_path, "a+")
                try:
                    fcntl.flock(lock_fp, fcntl.LOCK_SH)
                except Exception:
                    pass
        except Exception:
            pass

        try:
            raw = _AGENT_ROUTES_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list) or not data:
                return None

            # Scan backwards from newest
            for route in reversed(data):
                if not isinstance(route, dict):
                    continue
                if target_engine:
                    if route.get("from_engine") == target_engine:
                        return route
                else:
                    return route
        except Exception:
            pass
        finally:
            if lock_fp is not None:
                try:
                    fcntl.flock(lock_fp, fcntl.LOCK_UN)
                    lock_fp.close()
                except Exception:
                    pass
    return None


def get_latest_antigravity_conversation_id() -> Optional[str]:
    """
    Find the most recently updated genuine Antigravity conversation ID (excluding Claude and Codex sessions).
    """
    try:
        # First check session cookie if it is Antigravity
        cookie = load_session_cookie()
        if cookie and cookie.get("engine") == "antigravity":
            cid = cookie.get("conv_id")
            if cid and not str(cid).startswith("claude_") and not str(cid).startswith("codex_"):
                return str(cid)

        tracker = ConversationTracker()
        active = tracker.get_active_or_latest()
        if (
            active
            and getattr(active, "engine", "") == "antigravity"
            and not str(active.id).startswith("claude_")
            and not str(active.id).startswith("codex_")
        ):
            return str(active.id)

        for c in tracker.get_all_conversations(limit=10):
            if getattr(c, "engine", "") == "antigravity" and not str(c.id).startswith("claude_") and not str(c.id).startswith("codex_"):
                return str(c.id)
    except Exception:
        pass
    return None


@dataclass
class ConversationInfo:
    id: str
    title: str
    status: str  # 'waiting_for_user' | 'agent_working' | 'idle'
    mtime: float
    last_agent_text: str = ""
    last_user_text: str = ""
    transcript_path: Optional[Path] = None
    engine: str = "antigravity"  # 'antigravity' | 'claude'
    project_name: Optional[str] = None
    workspace_path: Optional[str] = None
    cwd: Optional[str] = None


class ConversationTracker:
    """Tracks active and recent Antigravity conversations."""

    def __init__(self, brain_dir: Optional[Path] = None):
        self.brain_dir = brain_dir or (Path.home() / ".gemini" / "antigravity" / "brain")
        self.active_focus_id: Optional[str] = None
        self._cache: Dict[str, ConversationInfo] = {}
        self._transcripts_cache: List[Path] = []
        self._last_transcripts_scan: float = 0.0
        self._pb_titles_cache: Dict[str, str] = {}
        self._pb_titles_mtime: float = 0.0

    def get_recent_transcripts(self, limit: int = 10, ttl: float = 2.0) -> List[Path]:
        """Find recently modified transcript.jsonl files in brain directory with TTL caching."""
        if not self.brain_dir.is_dir():
            return []

        now = time.time()
        if (now - self._last_transcripts_scan) < ttl and len(self._transcripts_cache) >= limit:
            return self._transcripts_cache[:limit]

        candidates = []
        try:
            with os.scandir(self.brain_dir) as it:
                subdirs = [e for e in it if e.is_dir()]
            subdirs.sort(key=lambda e: e.stat().st_mtime, reverse=True)
            for entry in subdirs[: max(limit * 3, 30)]:
                p = Path(entry.path) / ".system_generated" / "logs" / "transcript.jsonl"
                if p.is_file():
                    mtime = p.stat().st_mtime
                    try:
                        full = p.parent / "transcript_full.jsonl"
                        if full.is_file():
                            mtime = max(mtime, full.stat().st_mtime)
                    except Exception:
                        pass
                    candidates.append((mtime, p))
        except Exception:
            candidates = []

        if not candidates:
            pattern = str(self.brain_dir / "*" / ".system_generated" / "logs" / "transcript.jsonl")
            files = glob.glob(pattern)
            for f in files:
                p = Path(f)
                try:
                    full = p.parent / "transcript_full.jsonl"
                    m = max(os.path.getmtime(f), os.path.getmtime(str(full))) if full.is_file() else os.path.getmtime(f)
                except Exception:
                    m = 0.0
                candidates.append((m, p))

        candidates.sort(key=lambda x: x[0], reverse=True)
        res = [p for _, p in candidates]
        self._transcripts_cache = res
        self._last_transcripts_scan = now
        return res[:limit]

    def _get_pb_titles(self) -> Dict[str, str]:
        """Extract genuine side-panel conversation titles from agyhub_summaries_proto.pb with mtime cache."""
        pb_path = Path.home() / ".gemini" / "antigravity" / "agyhub_summaries_proto.pb"
        if not pb_path.is_file():
            return {}
        try:
            mtime = pb_path.stat().st_mtime
            if self._pb_titles_cache and mtime == self._pb_titles_mtime:
                return self._pb_titles_cache
            data = pb_path.read_bytes()
            # Protobuf pattern: \n$ <36-byte uuid> \x12 <varint> \n <1-byte len> <title>
            pattern = rb"\n\$([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\x12[\x80-\xff]*[\x00-\x7f]\n([\x01-\x7f])"
            titles = {}
            for m in re.finditer(pattern, data):
                cid = m.group(1).decode("ascii")
                t_len = m.group(2)[0]
                t_start = m.end()
                t_bytes = data[t_start : t_start + t_len]
                title = t_bytes.decode("utf-8", errors="ignore").strip()
                if title and not title.startswith("file:///"):
                    titles[cid] = title
            self._pb_titles_cache = titles
            self._pb_titles_mtime = mtime
            return titles
        except Exception:
            return self._pb_titles_cache or {}

    def parse_conversation(self, transcript_path: Path) -> Optional[ConversationInfo]:
        """Parse conversation transcript to extract metadata, title, and current state."""
        try:
            p = Path(transcript_path)
            conv_id = p.parent.parent.parent.name
            mtime = os.path.getmtime(p)
            full_path = p.parent / "transcript_full.jsonl"
            if full_path.is_file():
                try:
                    mtime = max(mtime, os.path.getmtime(full_path))
                except Exception:
                    pass

            # Check cache if mtime unchanged
            if conv_id in self._cache and self._cache[conv_id].mtime == mtime:
                return self._cache[conv_id]

            with open(p, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]

            if not lines:
                return None

            title = f"Conversation {conv_id[:8]}"
            status = "idle"
            last_agent_text = ""
            last_user_text = ""
            workspace_path = None
            project_name = None

            # Check active session cookie for workspace path
            cookie = load_session_cookie()
            if cookie and cookie.get("conv_id") == conv_id and cookie.get("workspacePath"):
                workspace_path = cookie.get("workspacePath")

            # Extract workspace path from transcript lines
            for l_str in lines[:10]:
                try:
                    step_data = json.loads(l_str)
                    content_str = step_data.get("content", "")
                    if content_str and not workspace_path:
                        m_ws = re.search(r"(/Users/[^\s\n\r\'\"<>]+/Projects/[A-Za-z0-9_.-]+)", content_str)
                        if m_ws:
                            workspace_path = m_ws.group(1)
                    for tc in step_data.get("tool_calls", []):
                        args = tc.get("args", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        if isinstance(args, dict):
                            for k in ("Cwd", "SearchPath", "DirectoryPath", "AbsolutePath", "TargetFile"):
                                val = args.get(k)
                                if val and isinstance(val, str) and "/Projects/" in val:
                                    m_ws = re.search(r"(/Users/[^/]+/Projects/[A-Za-z0-9_.-]+)", val)
                                    if m_ws:
                                        workspace_path = m_ws.group(1)
                                        break
                        if workspace_path:
                            break
                    if workspace_path:
                        break
                except Exception:
                    continue

            if workspace_path:
                project_name = Path(workspace_path).name

            # Priority 1: Exact generated title from Antigravity's side panel summaries
            pb_titles = self._get_pb_titles()
            if conv_id in pb_titles and pb_titles[conv_id]:
                title = pb_titles[conv_id]
            else:
                # Fallback: Extract title from initial user prompt with text
                for l_str in lines:
                    try:
                        step_data = json.loads(l_str)
                        if step_data.get("type") == "USER_INPUT":
                            raw_c = step_data.get("content", "")
                            clean = clean_user_message(raw_c)
                            if clean:
                                first_line = clean.split("\n")[0].strip()
                                if first_line:
                                    title = first_line[:45] + ("..." if len(first_line) > 45 else "")
                                    break
                    except Exception:
                        continue

            # Determine status from the last step
            last_step = json.loads(lines[-1])
            step_type = last_step.get("type", "")
            step_source = last_step.get("source", "")
            step_status = last_step.get("status", "")
            tool_calls = last_step.get("tool_calls", [])

            if step_type == "PLANNER_RESPONSE" and step_source == "MODEL":
                if step_status == "DONE" and not tool_calls:
                    status = "waiting_for_user"
                    last_agent_text = last_step.get("content", "") or ""
                else:
                    status = "agent_working"
            elif step_type in ("USER_INPUT", "GENERIC", "SYSTEM_MESSAGE"):
                status = "agent_working"
                if step_type == "USER_INPUT":
                    last_user_text = extract_user_message(last_step.get("content", "")) or ""
                elif step_type == "SYSTEM_MESSAGE":
                    c = last_step.get("content", "")
                    if "[Message]" in c:
                        last_user_text = extract_user_message(c) or ""

            info = ConversationInfo(
                id=conv_id,
                title=title,
                status=status,
                mtime=mtime,
                last_agent_text=last_agent_text,
                last_user_text=last_user_text,
                transcript_path=p,
                project_name=project_name,
                workspace_path=workspace_path,
            )
            self._cache[conv_id] = info
            return info
        except Exception:
            return None

    def get_all_conversations(self, limit: int = 12) -> List[ConversationInfo]:
        """Return parsed list of recent conversations (Antigravity, Claude Code, and Codex) sorted by recency."""
        results: List[ConversationInfo] = []

        # 1. Antigravity transcripts
        ag_paths = self.get_recent_transcripts(limit=limit)
        for p in ag_paths:
            info = self.parse_conversation(p)
            if info:
                results.append(info)

        # 2. Claude Code project sessions
        try:
            from voicefi.integrations.claude import find_recent_claude_sessions

            claude_paths = find_recent_claude_sessions(limit=limit)
        except Exception:
            claude_paths = []
        for p in claude_paths:
            info = parse_claude_session(p)
            if info:
                results.append(info)

        # 3. Codex sessions
        try:
            from voicefi.integrations.codex import find_recent_codex_sessions, parse_codex_session

            codex_paths = find_recent_codex_sessions(limit=limit)
        except Exception:
            codex_paths = []
        for p in codex_paths:
            info = parse_codex_session(p)
            if info:
                results.append(info)

        # 4. If active focus or session cookie conversation is not yet on disk (e.g. newly created session),
        # synthesize and prepend it so the user can immediately see and interact with it in the UI.
        cookie = load_session_cookie()
        target_focus = self.active_focus_id or (cookie.get("conversationId") if cookie else None)
        if target_focus and not any(r.id == target_focus for r in results):
            focus_engine = (
                "codex"
                if (target_focus.startswith("codex_") or "codex" in target_focus.lower())
                else (
                    "claude"
                    if (target_focus.startswith("claude_") or "claude" in target_focus.lower())
                    else "antigravity"
                )
            )
            c_title = (cookie.get("title") if cookie else None) or f"{focus_engine.capitalize()} Session"
            synth_info = ConversationInfo(
                id=target_focus,
                title=c_title,
                status="agent_working",
                mtime=time.time(),
                engine=focus_engine,
            )
            results.insert(0, synth_info)

        # Sort all conversations chronologically by mtime
        results.sort(key=lambda x: x.mtime, reverse=True)
        return results[:limit]

    def set_active_focus(
        self, conv_id: str, transcript_path: Optional[Path] = None, title: Optional[str] = None
    ):
        """Set the currently focused conversation ID and update session cookie."""
        self.active_focus_id = conv_id
        engine = (
            "codex"
            if (conv_id.startswith("codex_") or "codex" in conv_id.lower())
            else (
                "claude"
                if (conv_id.startswith("claude_") or "claude" in conv_id.lower())
                else "antigravity"
            )
        )

        if not transcript_path and conv_id:
            if engine == "codex":
                try:
                    from voicefi.integrations.codex import find_recent_codex_sessions
                    clean_id = conv_id.replace("codex_", "")
                    for p in find_recent_codex_sessions(limit=30):
                        if clean_id in p.name or conv_id in p.name:
                            transcript_path = p
                            break
                except Exception:
                    pass
            elif engine == "claude":
                clean_id = conv_id.replace("claude_", "")
                matches = list((Path.home() / ".claude" / "projects").glob(f"*/{clean_id}.jsonl"))
                if matches:
                    transcript_path = matches[0]
            else:
                candidate = (
                    self.brain_dir / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
                )
                if candidate.is_file():
                    transcript_path = candidate

        if not title and transcript_path:
            if engine == "codex":
                from voicefi.integrations.codex import parse_codex_session
                info = parse_codex_session(transcript_path)
            elif engine == "claude":
                info = parse_claude_session(transcript_path)
            else:
                info = self.parse_conversation(transcript_path)
            if info:
                title = info.title
        save_session_cookie(
            conv_id=conv_id,
            transcript_path=str(transcript_path) if transcript_path else None,
            title=title,
            engine=engine,
        )

    def get_active_or_latest(self, engine: Optional[str] = None) -> Optional[ConversationInfo]:
        """
        Dynamically determine the currently active conversation (Antigravity, Claude Code, or Codex).
        Prioritizes the most recently updated conversation based on transcript modification times
        and active session cookies. Optionally filters by engine.
        """
        convs = self.get_all_conversations(limit=12)
        if engine:
            clean_eng = engine.lower().strip()
            if clean_eng in ("claude", "claude_code"):
                convs = [c for c in convs if getattr(c, "engine", "") == "claude" or c.id.startswith("claude_")]
            elif clean_eng in ("codex", "chatgpt", "openai"):
                convs = [c for c in convs if getattr(c, "engine", "") == "codex" or c.id.startswith("codex_")]
            elif clean_eng in ("antigravity", "agy"):
                convs = [
                    c
                    for c in convs
                    if getattr(c, "engine", "") not in ("claude", "codex")
                    and not c.id.startswith("claude_")
                    and not c.id.startswith("codex_")
                ]

        if not convs:
            return None

        latest_conv = convs[0]

        # Check persistent session cookie from recent hooks / focus events
        cookie = load_session_cookie()
        if cookie and cookie.get("conversationId"):
            cid = cookie["conversationId"]
            cookie_time = float(cookie.get("updatedAt", 0))
            now = time.time()

            # If the newest conversation on disk matches the cookie, it's definitely active
            if latest_conv.id == cid or (
                latest_conv.id.startswith("claude_")
                and latest_conv.id.replace("claude_", "") == cid
            ) or (
                latest_conv.id.startswith("codex_")
                and latest_conv.id.replace("codex_", "") == cid
            ):
                self.active_focus_id = latest_conv.id
                return latest_conv

            # If a different conversation was touched on disk after the cookie was saved,
            # that fresher conversation on disk takes immediate priority.
            if latest_conv.mtime > (cookie_time + 1.0):
                self.set_active_focus(
                    latest_conv.id,
                    transcript_path=latest_conv.transcript_path,
                    title=latest_conv.title,
                )
                self.active_focus_id = latest_conv.id
                return latest_conv

            # If cookie was very recently updated (< 60s) and not superseded by disk writes:
            if (now - cookie_time) < 60.0 and cookie_time >= (latest_conv.mtime - 1.0):
                for c in convs:
                    if (
                        c.id == cid
                        or (c.id.startswith("claude_") and c.id.replace("claude_", "") == cid)
                        or (cid.startswith("claude_") and cid.replace("claude_", "") == c.id)
                        or (c.id.startswith("codex_") and c.id.replace("codex_", "") == cid)
                        or (cid.startswith("codex_") and cid.replace("codex_", "") == c.id)
                    ):
                        self.active_focus_id = c.id
                        return c
                # Try parsing directly if path provided in cookie
                tpath = cookie.get("transcriptPath")
                if tpath and Path(tpath).is_file():
                    p = Path(tpath)
                    engine = cookie.get("engine", "antigravity")
                    if engine == "codex" or "codex" in str(p) or "sessions" in str(p):
                        from voicefi.integrations.codex import parse_codex_session
                        info = parse_codex_session(p)
                        if info:
                            self.active_focus_id = info.id
                            return info
                    elif engine == "claude" or "claude" in str(p) or p.name.endswith(".jsonl"):
                        info = parse_claude_session(p)
                        if info:
                            self.active_focus_id = info.id
                            return info
                    else:
                        info = self.parse_conversation(p)
                        if info:
                            self.active_focus_id = info.id
                            return info

        # Otherwise the most recently touched conversation on disk is active
        self.set_active_focus(
            latest_conv.id, transcript_path=latest_conv.transcript_path, title=latest_conv.title
        )
        self.active_focus_id = latest_conv.id
        return latest_conv

    def get_conversation_details(self, conv_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full conversation details for Antigravity, Claude, or Codex."""
        if not conv_id:
            return None

        # Check if this is a Codex session
        if conv_id.startswith("codex_"):
            clean_id = conv_id.replace("codex_", "")
            try:
                from voicefi.integrations.codex import (
                    parse_full_codex_conversation_details,
                    find_recent_codex_sessions,
                )
                for p in find_recent_codex_sessions(limit=50):
                    if clean_id in p.name or clean_id in str(p):
                        return parse_full_codex_conversation_details(p)
            except Exception:
                pass

        # Check if this is a Claude Code session
        if conv_id.startswith("claude_"):
            clean_id = conv_id.replace("claude_", "")
            matches = list((Path.home() / ".claude" / "projects").glob(f"*/{clean_id}.jsonl"))
            if matches:
                return parse_full_claude_conversation_details(matches[0])

        transcript_path = (
            self.brain_dir / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
        )
        if transcript_path.is_file():
            return parse_full_conversation_details(transcript_path, brain_dir=self.brain_dir)

        # Check Claude sessions by raw stem
        matches = list((Path.home() / ".claude" / "projects").glob(f"*/{conv_id}.jsonl"))
        if matches:
            return parse_full_claude_conversation_details(matches[0])

        # Check Codex sessions by raw stem or UUID
        try:
            from voicefi.integrations.codex import (
                find_recent_codex_sessions,
                parse_full_codex_conversation_details,
            )
            for p in find_recent_codex_sessions(limit=30):
                if conv_id in p.name or p.stem == conv_id or (conv_id.startswith("codex_") and p.stem in conv_id):
                    return parse_full_codex_conversation_details(p)
        except Exception:
            pass

        # Try finding in recent Claude sessions
        try:
            from voicefi.integrations.claude import find_recent_claude_sessions

            claude_recent = find_recent_claude_sessions(limit=10)
        except Exception:
            claude_recent = []
        for p in claude_recent:
            if p.stem == conv_id or f"claude_{p.stem}" == conv_id:
                return parse_full_claude_conversation_details(p)

        return None

    def get_artifact(self, conv_id: str, filename: str) -> Optional[Dict[str, Any]]:
        """Retrieve an artifact by filename for a given conversation (Antigravity or Claude)."""
        safe_name = Path(filename).name

        # 1. Check Antigravity brain dir if not a pure Claude session
        if not conv_id.startswith("claude_"):
            target = self.brain_dir / conv_id / safe_name
            if target.is_file():
                return get_artifact_content(conv_id, filename, brain_dir=self.brain_dir)

        # 2. Check Claude plans directory
        claude_target = Path.home() / ".claude" / "plans" / safe_name
        if claude_target.is_file():
            try:
                text = claude_target.read_text(encoding="utf-8", errors="replace")
                return {
                    "name": safe_name,
                    "content": text,
                    "size": claude_target.stat().st_size,
                    "is_image": False,
                    "type": "markdown",
                }
            except Exception as e:
                return {"name": safe_name, "error": str(e), "content": "", "size": 0}

        return get_artifact_content(conv_id, filename, brain_dir=self.brain_dir)


def extract_user_message(content: str) -> Optional[str]:
    """Extract clean user message text from USER_INPUT or SYSTEM_MESSAGE containing user prompts."""
    if not content or not content.strip():
        return None

    # Check for [Message] ... content=... (IPC/subagent/queued user message)
    m = re.search(r"\[Message\][^\n]*\bcontent=(.*?)(?:\n</SYSTEM_MESSAGE>|\Z)", content, re.DOTALL)
    if m:
        extracted = m.group(1).strip()
        return clean_user_message(extracted)

    # Check for <USER_REQUEST>...</USER_REQUEST>
    m2 = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", content, re.DOTALL)
    if m2:
        return clean_user_message(m2.group(1).strip())

    return clean_user_message(content)


def clean_user_message(content: str) -> str:
    """Clean internal Antigravity tags, envelopes, attachments, and metadata from raw user input string."""
    if not content:
        return ""
    clean = content
    # Extract <USER_REQUEST>...</USER_REQUEST> if present
    if "<USER_REQUEST>" in clean:
        m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", clean, re.DOTALL)
        clean = m.group(1).strip() if m else ""

    # Remove trailing metadata tags
    clean = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", clean, flags=re.DOTALL)
    clean = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", clean, flags=re.DOTALL)

    # Clean cross-agent bridge provenance headers & envelopes
    clean = re.sub(r"^\[From:\s*[^\]]+\]\s*", "", clean)
    clean = re.sub(r"^\[Message[^\]]*\]\s*", "", clean)
    clean = re.sub(r"^\[Attached Screenshot:\s*[^\]]+\]\s*", "", clean)
    clean = re.sub(r"^\[ATTACHED\s*\([0-9]+\):[^\]]+\]\s*", "", clean)

    # Clean slash command prefixes like /antigravity-guide
    clean = re.sub(r"^/[a-zA-Z0-9_-]+\s*", "", clean).strip()
    return clean.strip()


def get_conversation_artifacts(
    conv_id: str, brain_dir: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """List artifact files in the conversation's brain directory."""
    bdir = brain_dir or (Path.home() / ".gemini" / "antigravity" / "brain")
    conv_path = bdir / conv_id
    if not conv_path.is_dir():
        return []

    artifacts = []
    try:
        for item in sorted(conv_path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if (
                item.is_file()
                and not item.name.startswith(".")
                and not item.name.endswith(".metadata.json")
            ):
                ext = item.suffix.lstrip(".").lower()
                artifacts.append(
                    {
                        "name": item.name,
                        "path": str(item),
                        "size": item.stat().st_size,
                        "mtime": item.stat().st_mtime,
                        "extension": ext,
                        "is_markdown": ext in ("md", "markdown"),
                    }
                )
    except Exception:
        pass
    return artifacts


def get_artifact_content(
    conv_id: str, filename: str, brain_dir: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Retrieve content of an artifact file safely."""
    bdir = brain_dir or (Path.home() / ".gemini" / "antigravity" / "brain")
    # Sanitize filename
    safe_name = Path(filename).name
    target = bdir / conv_id / safe_name
    if not target.is_file():
        return None

    try:
        ext = target.suffix.lstrip(".").lower()
        if ext in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
            import base64

            b64 = base64.b64encode(target.read_bytes()).decode("ascii")
            mime = f"image/{'svg+xml' if ext == 'svg' else ext}"
            return {
                "name": safe_name,
                "content": f"data:{mime};base64,{b64}",
                "size": target.stat().st_size,
                "is_image": True,
                "type": "image",
            }
        else:
            text = target.read_text(encoding="utf-8", errors="replace")
            return {
                "name": safe_name,
                "content": text,
                "size": target.stat().st_size,
                "is_image": False,
                "type": "markdown" if ext in ("md", "markdown") else "text",
            }
    except Exception as e:
        return {"name": safe_name, "error": str(e), "content": "", "size": 0}


def parse_full_conversation_details(
    transcript_path: Path, brain_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Parse a conversation transcript into full Antigravity conversational turns,
    including working logs (tool calls & results), thoughts, full markdown responses, and artifacts.
    """
    p = Path(transcript_path)
    conv_id = p.parent.parent.parent.name
    mtime = p.stat().st_mtime if p.exists() else time.time()

    tracker = ConversationTracker(brain_dir=brain_dir)
    basic_info = tracker.parse_conversation(p)
    title = basic_info.title if basic_info else f"Conversation {conv_id[:8]}"
    status = basic_info.status if basic_info else "idle"

    turns: List[Dict[str, Any]] = []
    current_turn: Optional[Dict[str, Any]] = None

    if not p.is_file():
        return {
            "id": conv_id,
            "title": title,
            "status": status,
            "mtime": mtime,
            "turns": [],
            "artifacts": get_conversation_artifacts(conv_id, brain_dir=brain_dir),
            "total_steps": 0,
        }

    lines = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
    except Exception:
        pass

    for idx, line in enumerate(lines):
        try:
            step = json.loads(line)
        except Exception:
            continue

        stype = step.get("type", "")
        source = step.get("source", "")
        content = step.get("content", "") or ""
        step_status = step.get("status", "DONE")
        created_at = step.get("created_at")
        tool_calls = step.get("tool_calls", [])
        step_index = step.get("step_index", idx)

        is_user_input = False
        user_text = ""

        if stype == "USER_INPUT":
            is_user_input = True
            user_text = extract_user_message(content) or content.strip()
        elif stype == "SYSTEM_MESSAGE":
            # Check if this SYSTEM_MESSAGE encapsulates a user message sent via IPC
            msg_match = re.search(
                r"\[Message\][^\n]*\bcontent=(.*?)(?:\n</SYSTEM_MESSAGE>|\Z)", content, re.DOTALL
            )
            if msg_match and "Task id " not in content:
                is_user_input = True
                user_text = clean_user_message(msg_match.group(1).strip())

        if is_user_input:
            if current_turn:
                turns.append(current_turn)

            current_turn = {
                "turn_id": len(turns) + 1,
                "user_message": user_text,
                "raw_user_message": content,
                "user_timestamp": created_at,
                "agent_steps": [],
                "agent_response": "",
                "agent_role": "antigravity",
                "status": "working",
                "completed": False,
            }
        elif current_turn is not None:
            if tool_calls:
                for tc in tool_calls:
                    t_desc, t_tag = format_tool_details(tc)
                    t_name = tc.get("name") or tc.get("tool_name") or "tool"
                    t_args = tc.get("args", {})
                    current_turn["agent_steps"].append(
                        {
                            "step_index": step_index,
                            "type": "tool_call",
                            "tool_name": t_name,
                            "summary": t_desc,
                            "action": t_tag,
                            "args": t_args,
                            "status": step_status,
                            "output": None,
                            "created_at": created_at,
                        }
                    )
            elif stype == "GENERIC":
                # Tool output matching previous tool_call step
                if current_turn["agent_steps"]:
                    for s in reversed(current_turn["agent_steps"]):
                        if s.get("type") == "tool_call" and s.get("output") is None:
                            # Truncate very large tool outputs to prevent mobile WebProcess memory crashes
                            if content and len(content) > 2500:
                                s["output"] = (
                                    content[:2500]
                                    + f"\n\n... [{len(content) - 2500:,} more characters truncated for mobile performance]"
                                )
                            else:
                                s["output"] = content
                            break
            elif stype == "PLANNER_RESPONSE" and source == "MODEL":
                if content:
                    current_turn["agent_response"] = content
                    current_turn["agent_role"] = (
                        step.get("role") or step.get("agent_role") or "antigravity"
                    )
                    if step_status == "DONE" and not tool_calls:
                        current_turn["status"] = "done"
                        current_turn["completed"] = True
            elif stype == "SYSTEM_MESSAGE":
                current_turn["agent_steps"].append(
                    {
                        "step_index": step_index,
                        "type": "system_message",
                        "tool_name": "system",
                        "summary": "System Update",
                        "action": "",
                        "args": {},
                        "status": step_status,
                        "output": (
                            content[:2500]
                            + f"\n\n... [{len(content) - 2500:,} more characters truncated]"
                        )
                        if (content and len(content) > 2500)
                        else content,
                        "created_at": created_at,
                    }
                )

    if current_turn:
        turns.append(current_turn)

    # Ensure overall status is 'agent_working' whenever the latest turn is active
    if turns and (not turns[-1].get("completed") or turns[-1].get("status") == "working"):
        status = "agent_working"

    artifacts = get_conversation_artifacts(conv_id, brain_dir=brain_dir)

    plan_info = None
    bdir = brain_dir or (Path.home() / ".gemini" / "antigravity" / "brain")
    for art in artifacts:
        if art.get("name") == "implementation_plan.md":
            plan_path = bdir / conv_id / "implementation_plan.md"
            meta_path = bdir / conv_id / "implementation_plan.md.metadata.json"
            requires_review = True
            plan_status = "awaiting_approval"

            # Check metadata.json
            if meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    if meta.get("requestFeedback") is False or meta.get("userFacing") is False:
                        requires_review = False
                        plan_status = "approved"
                except Exception:
                    pass

            # Check file content header / status
            if requires_review and plan_path.is_file():
                try:
                    content = plan_path.read_text(encoding="utf-8", errors="ignore")
                    if re.search(r"(?i)#\s*\[(?:APPROVED|COMPLETED|DONE)", content) or re.search(
                        r"(?i)\*\*Status:\*\*\s*(?:Approved|Completed|Done)", content
                    ):
                        requires_review = False
                        plan_status = "approved"
                    elif "User Review Required" not in content and "Open Questions" not in content:
                        requires_review = False
                        plan_status = "approved"
                except Exception:
                    pass

            plan_info = {
                "name": "implementation_plan.md",
                "mtime": art.get("mtime"),
                "size": art.get("size"),
                "exists": True,
                "requires_review": requires_review,
                "status": plan_status,
            }
            break

    return {
        "id": conv_id,
        "title": title,
        "status": status,
        "mtime": mtime,
        "turns": turns,
        "artifacts": artifacts,
        "plan_info": plan_info,
        "total_steps": len(lines),
    }


def find_recent_claude_sessions(base_dir: Optional[Path] = None, limit: int = 10) -> List[Path]:
    """Find recently modified Claude Code session JSONL files across all projects."""
    claude_dir = base_dir or (Path.home() / ".claude")
    projects_dir = claude_dir / "projects"
    if not projects_dir.is_dir():
        return []

    candidate_files = []
    try:
        for p in projects_dir.glob("*/*.jsonl"):
            if p.is_file() and p.stat().st_size > 0:
                candidate_files.append((p.stat().st_mtime, p))
    except Exception:
        return []

    if not candidate_files:
        return []

    candidate_files.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in candidate_files[:limit]]


_CLAUDE_SESSIONS_CACHE: Dict[str, Tuple[float, ConversationInfo]] = {}


def parse_claude_session(session_path: Path) -> Optional[ConversationInfo]:
    """Parse a Claude Code session JSONL file into ConversationInfo with mtime cache."""
    try:
        p = Path(session_path)
        if not p.is_file():
            return None
        mtime = p.stat().st_mtime
        session_id = p.stem  # e.g. "c32203cb-5b68-4bbb-ba3e-18990b071640"
        conv_id = f"claude_{session_id}" if not session_id.startswith("claude_") else session_id

        if conv_id in _CLAUDE_SESSIONS_CACHE:
            cached_mtime, cached_info = _CLAUDE_SESSIONS_CACHE[conv_id]
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
        parent_name = p.parent.name
        if parent_name.startswith("-"):
            parts = [seg for seg in parent_name.split("-") if seg]
            if parts:
                project_name = parts[-1]

        first_user_text = ""
        last_user_text = ""
        last_assistant_text = ""
        last_msg_type = ""
        has_tool_calls_pending = False
        cwd = None

        for line in lines:
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    continue
                if not cwd and obj.get("cwd"):
                    cwd = obj.get("cwd")
                    if not project_name and cwd:
                        project_name = Path(cwd).name

                t = obj.get("type")
                if t == "user":
                    last_msg_type = "user"
                    msg = obj.get("message", {})
                    content = msg.get("content", "")
                    text = ""
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        parts = [
                            b.get("text", "")
                            for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        ]
                        text = " ".join(parts)
                    if text:
                        cleaned = clean_user_message(text)
                        if cleaned:
                            last_user_text = cleaned
                            if not first_user_text:
                                first_user_text = cleaned
                elif t == "assistant":
                    last_msg_type = "assistant"
                    has_tool_calls_pending = False
                    msg = obj.get("message", {})
                    content = msg.get("content", [])
                    text_parts = []
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                if block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                                elif block.get("type") == "tool_use":
                                    has_tool_calls_pending = True
                    elif isinstance(content, str):
                        text_parts.append(content)
                    if text_parts:
                        last_assistant_text = " ".join(text_parts).strip()
                elif t == "last-prompt":
                    lp = obj.get("lastPrompt", "")
                    if lp:
                        if not first_user_text:
                            first_user_text = lp
                        last_user_text = lp
                elif t == "attachment":
                    att = obj.get("attachment", {})
                    if att.get("type") == "hook_success":
                        has_tool_calls_pending = False
            except Exception:
                continue

        # Generate human-friendly title
        if first_user_text:
            clean_first = clean_user_message(first_user_text)
            first_line = clean_first.split("\n")[0].strip() if clean_first else first_user_text.split("\n")[0].strip()
            clean_first = first_line[:40] + ("..." if len(first_line) > 40 else "")
            if project_name:
                title = f"{project_name}: {clean_first}"
            else:
                title = clean_first
        else:
            title = f"{project_name} ({session_id[:8]})" if project_name else f"Claude ({session_id[:8]})"

        status = "idle"
        if last_msg_type == "user" or has_tool_calls_pending:
            status = "agent_working"
        elif last_msg_type == "assistant" or last_assistant_text:
            status = "waiting_for_user"

        cleaned_agent_text = ""
        if last_assistant_text:
            from voicefi.integrations.antigravity import clean_markdown_for_speech

            cleaned_agent_text = clean_markdown_for_speech(last_assistant_text, max_words=60)

        info = ConversationInfo(
            id=conv_id,
            title=title,
            status=status,
            mtime=mtime,
            last_agent_text=cleaned_agent_text,
            last_user_text=last_user_text,
            transcript_path=p,
            engine="claude",
            project_name=project_name,
            cwd=cwd,
        )
        _CLAUDE_SESSIONS_CACHE[conv_id] = (mtime, info)
        return info
    except Exception:
        return None


def parse_full_claude_conversation_details(session_path: Path) -> Dict[str, Any]:
    """Parse full turns, tool calls, and assistant responses from a Claude Code session."""
    p = Path(session_path)
    session_id = p.stem
    conv_id = f"claude_{session_id}" if not session_id.startswith("claude_") else session_id
    mtime = p.stat().st_mtime if p.is_file() else time.time()

    info = parse_claude_session(p)
    title = info.title if info else f"Claude ({session_id[:8]})"
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

        t = obj.get("type")
        created_at = obj.get("timestamp")

        if t == "user":
            msg = obj.get("message", {})
            content = msg.get("content", "")
            user_text = ""
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                user_text = " ".join(parts)

            if current_turn:
                turns.append(current_turn)

            current_turn = {
                "turn_id": len(turns) + 1,
                "user_message": clean_user_message(user_text) if user_text else "User prompt",
                "raw_user_message": user_text,
                "user_timestamp": created_at,
                "agent_steps": [],
                "agent_response": "",
                "agent_role": "claude",
                "status": "working",
                "completed": False,
            }
        elif current_turn is not None:
            if t == "assistant":
                msg = obj.get("message", {})
                content = msg.get("content", [])
                text_parts = []
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            b_type = block.get("type")
                            if b_type == "text":
                                text_parts.append(block.get("text", ""))
                            elif b_type == "tool_use":
                                t_name = block.get("name", "tool")
                                t_input = block.get("input", {})
                                t_summary = f"{t_name} {str(t_input.get('command') or t_input.get('path') or '')[:40]}".strip()
                                current_turn["agent_steps"].append(
                                    {
                                        "step_index": idx,
                                        "type": "tool_call",
                                        "tool_name": t_name,
                                        "summary": t_summary,
                                        "action": t_name,
                                        "args": t_input,
                                        "status": "DONE",
                                        "output": None,
                                        "created_at": created_at,
                                    }
                                )
                elif isinstance(content, str):
                    text_parts.append(content)

                if text_parts:
                    current_turn["agent_response"] = "\n\n".join(text_parts)
                    current_turn["status"] = "done"
                    current_turn["completed"] = True
            elif t == "attachment":
                att = obj.get("attachment", {})
                att_type = att.get("type")
                if att_type == "hook_success":
                    if current_turn:
                        current_turn["status"] = "done"
                        current_turn["completed"] = True
                elif (
                    att_type in ("tool_result", "hook_output")
                    or "output" in att
                    or "content" in att
                ):
                    if current_turn["agent_steps"]:
                        for s in reversed(current_turn["agent_steps"]):
                            if s.get("output") is None:
                                raw_out = att.get("output") or att.get("content") or ""
                                if raw_out and len(raw_out) > 2500:
                                    s["output"] = (
                                        raw_out[:2500]
                                        + f"\n\n... [{len(raw_out) - 2500:,} more characters truncated]"
                                    )
                                else:
                                    s["output"] = raw_out
                                break

    if current_turn:
        turns.append(current_turn)

    # Artifacts: Search for plans associated with this session in ~/.claude/plans
    artifacts = []
    claude_plans_dir = Path.home() / ".claude" / "plans"
    if claude_plans_dir.is_dir():
        try:
            full_session_text = "\n".join(lines)
            for item in sorted(
                claude_plans_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True
            ):
                if item.is_file() and item.suffix in (".md", ".markdown"):
                    if item.name in full_session_text or item.stem in full_session_text:
                        artifacts.append(
                            {
                                "name": item.name,
                                "path": str(item),
                                "size": item.stat().st_size,
                                "mtime": item.stat().st_mtime,
                                "extension": "md",
                                "is_markdown": True,
                            }
                        )
        except Exception:
            pass

    plan_info = None
    if artifacts:
        plan_info = {
            "name": artifacts[0]["name"],
            "mtime": artifacts[0]["mtime"],
            "size": artifacts[0]["size"],
            "exists": True,
        }

    return {
        "id": conv_id,
        "title": title,
        "status": status,
        "mtime": mtime,
        "engine": "claude",
        "turns": turns,
        "artifacts": artifacts,
        "plan_info": plan_info,
        "total_steps": len(lines),
    }
