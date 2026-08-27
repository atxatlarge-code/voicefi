"""
Conversation manager and tracker for Antigravity.
Discovers active conversations, parses topics and turn statuses, and tracks active focus targets.
"""

import glob
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Any


def get_session_cookie_path() -> Path:
    """Path to the persistent active Antigravity session cookie."""
    cookie_dir = Path.home() / ".voicefi"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    return cookie_dir / "active_session.json"


import fcntl


def _normalize_turn_signature(signature: str) -> str:
    """Extract clean text content from signature for resilient deduplication."""
    if not signature:
        return ""
    # Strip conversation ID prefix if present: "conv_id:text" -> "text"
    if ":" in signature:
        _, text_part = signature.split(":", 1)
    else:
        text_part = signature
    clean = re.sub(r"[^a-z0-9]", "", text_part.lower()).strip()
    return clean[:30]


def claim_turn(
    conv_id: Optional[str],
    signature: str,
    origin: Optional[str] = None,
    step_index: Optional[int] = None,
    turn_id: Optional[str] = None,
) -> bool:
    """
    Atomically claims a turn using cross-process file locks so only one worker
    (CLI Hook or Background Watcher) handles speech and mic capture.
    Returns True if this caller claimed the turn, False if already claimed recently.
    """
    turn_file = Path("/tmp/voicefi_active_turns.json")
    lock_file = Path("/tmp/voicefi_active_turns.lock")
    now = time.time()
    norm_sig = _normalize_turn_signature(signature)

    # Derive canonical step_index if embedded in signature (e.g. "conv_id:step_42" or "step:42")
    resolved_step_idx = step_index
    if resolved_step_idx is None:
        m = re.search(r"\bstep[_\s:]+(\d+)\b", signature, re.IGNORECASE)
        if m:
            resolved_step_idx = int(m.group(1))

    canonical_turn_id = turn_id or (
        f"{conv_id}:step_{resolved_step_idx}" if conv_id and resolved_step_idx is not None and resolved_step_idx >= 0
        else (f"{conv_id}:{norm_sig}" if conv_id and norm_sig else signature)
    )

    resolved_origin = origin
    if not resolved_origin:
        resolved_origin = "mobile" if pop_mobile_turn_origin(conv_id) else "desktop"

    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_file, "a+") as lock_fp:
            fcntl.flock(lock_fp, fcntl.LOCK_EX)
            try:
                entries: List[Dict[str, Any]] = []
                if turn_file.is_file():
                    try:
                        with open(turn_file, "r") as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                entries = data
                            elif isinstance(data, dict):
                                entries = [data]
                    except Exception:
                        entries = []

                # Clean entries older than 15 seconds
                valid_entries = [
                    e for e in entries
                    if (now - float(e.get("timestamp", 0))) < 15.0
                ]

                # Check if this exact turn_id, step_index, signature, OR normalized text was already claimed
                for e in valid_entries:
                    e_sig = e.get("signature", "")
                    e_norm = e.get("norm_sig") or _normalize_turn_signature(e_sig)
                    e_cid = e.get("conv_id", "")
                    e_ts = float(e.get("timestamp", 0))
                    e_step = e.get("step_index")
                    e_tid = e.get("turn_id")

                    # 1. Exact Turn ID match
                    if canonical_turn_id and e_tid and e_tid == canonical_turn_id:
                        return False

                    # 2. Exact conversation + step index match (100% deterministic)
                    if (
                        conv_id
                        and e_cid == conv_id
                        and resolved_step_idx is not None
                        and resolved_step_idx >= 0
                        and e_step is not None
                        and e_step == resolved_step_idx
                    ):
                        return False

                    # 3. Exact signature string match
                    if e_sig == signature:
                        return False

                    # 4. Normalized text match
                    if norm_sig and e_norm == norm_sig:
                        return False

                    # 5. Conversation-level rapid debounce (3.5s window for same conversation when step_index is unknown or same)
                    if conv_id and e_cid == conv_id:
                        if (
                            resolved_step_idx is not None
                            and e_step is not None
                            and resolved_step_idx != e_step
                        ):
                            continue
                        if (now - e_ts) < 3.5:
                            return False
                        if norm_sig and (norm_sig in e_norm or e_norm in norm_sig):
                            return False

                # Claim this turn atomically
                valid_entries.append({
                    "conv_id": conv_id,
                    "turn_id": canonical_turn_id,
                    "step_index": resolved_step_idx,
                    "signature": signature,
                    "norm_sig": norm_sig,
                    "origin": resolved_origin,
                    "timestamp": now,
                })
                # Keep up to 25 entries
                if len(valid_entries) > 25:
                    valid_entries = valid_entries[-25:]

                with open(turn_file, "w") as f:
                    json.dump(valid_entries, f)

                return True
            finally:
                fcntl.flock(lock_fp, fcntl.LOCK_UN)
    except Exception:
        # Fallback to permissive execution if locking fails
        return True


def get_claimed_turn_origin(
    conv_id: Optional[str],
    signature: str,
    step_index: Optional[int] = None,
) -> Optional[str]:
    """Get the origin (mobile or desktop) recorded when this turn was claimed."""
    turn_file = Path("/tmp/voicefi_active_turns.json")
    if not turn_file.is_file():
        return None
    try:
        norm_sig = _normalize_turn_signature(signature)
        with open(turn_file, "r") as f:
            entries = json.load(f)
        if isinstance(entries, list):
            for e in reversed(entries):
                e_sig = e.get("signature", "")
                e_norm = e.get("norm_sig") or _normalize_turn_signature(e_sig)
                e_cid = e.get("conv_id", "")
                e_step = e.get("step_index")
                if (
                    conv_id
                    and e_cid == conv_id
                    and step_index is not None
                    and e_step is not None
                    and e_step == step_index
                ):
                    return e.get("origin")
                if e_sig == signature or (norm_sig and e_norm == norm_sig):
                    return e.get("origin")
    except Exception:
        pass
    return None


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

    text = question_text.strip().rstrip("?.!")
    
    # 1. Quoted choices: "foo" or "bar"
    quotes = re.findall(r'["\']([^"\']+)["\']', text)
    if len(quotes) >= 2:
        return [q.strip().lower() for q in quotes if q.strip()]

    # 2. Simple 'A or B' split
    if " or " in text.lower():
        # Match 'X or Y' where X might have a prefix like 'Would you like to'
        parts = re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
        if len(parts) == 2:
            left, right = parts[0].strip(), parts[1].strip()
            # Clean common question leading phrasing from left
            left = re.sub(
                r"^(?:do you want to|would you like to|should we|shall we|can we|do we|please choose:?)\s*",
                "",
                left,
                flags=re.IGNORECASE,
            ).strip()
            if left and right:
                return [left.lower(), right.lower()]

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


def set_mobile_turn_origin(conv_id: Optional[str] = None) -> None:
    """Record that the current pending turn was initiated from mobile companion."""
    origin_file = Path("/tmp/voicefi_mobile_turn.json")
    try:
        data = {
            "conv_id": conv_id or "active",
            "timestamp": time.time(),
        }
        with open(origin_file, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def peek_mobile_turn_origin(conv_id: Optional[str] = None, max_age_seconds: float = 45.0) -> bool:
    """
    Check if the pending turn originated from mobile companion without consuming the marker.
    """
    origin_file = Path("/tmp/voicefi_mobile_turn.json")
    if not origin_file.is_file():
        return False
    try:
        with open(origin_file, "r") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        cid = data.get("conv_id")
        if (time.time() - ts) < max_age_seconds:
            if not conv_id or not cid or cid == "active" or cid == conv_id:
                return True
    except Exception:
        pass
    return False


def pop_mobile_turn_origin(conv_id: Optional[str] = None, max_age_seconds: float = 45.0) -> bool:
    """
    Check and consume mobile turn origin marker.
    Returns True if the completed turn originated from mobile companion (and consumes the marker), False otherwise.
    """
    origin_file = Path("/tmp/voicefi_mobile_turn.json")
    if not origin_file.is_file():
        return False
    try:
        with open(origin_file, "r") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        cid = data.get("conv_id")
        if (time.time() - ts) < max_age_seconds:
            if not conv_id or not cid or cid == "active" or cid == conv_id:
                origin_file.unlink(missing_ok=True)
                return True
        else:
            origin_file.unlink(missing_ok=True)
    except Exception:
        pass
    return False


def record_companion_heartbeat(num_clients: int = 1) -> None:
    """Record active companion client heartbeat to allow Mac to coordinate audio routing."""
    heartbeat_file = Path("/tmp/voicefi_companion_clients.json")
    try:
        data = {
            "clients": max(0, num_clients),
            "timestamp": time.time(),
        }
        with open(heartbeat_file, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def has_active_companion_client(max_age_seconds: float = 15.0) -> bool:
    """Return True if at least one mobile companion client is connected and active."""
    heartbeat_file = Path("/tmp/voicefi_companion_clients.json")
    if not heartbeat_file.is_file():
        return False
    try:
        with open(heartbeat_file, "r") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        count = data.get("clients", 0)
        if (time.time() - ts) < max_age_seconds and count > 0:
            return True
    except Exception:
        pass
    return False


def clear_companion_heartbeat() -> None:
    """Clear companion client heartbeat."""
    heartbeat_file = Path("/tmp/voicefi_companion_clients.json")
    try:
        heartbeat_file.unlink(missing_ok=True)
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
            if data and isinstance(data, dict) and (data.get("conversationId") or data.get("conv_id")):
                cid = data.get("conversationId") or data.get("conv_id")
                data["conversationId"] = cid
                data["conv_id"] = cid
                return data
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
    cwd: Optional[str] = None


class ConversationTracker:
    """Tracks active and recent Antigravity conversations."""

    def __init__(self, brain_dir: Optional[Path] = None):
        self.brain_dir = brain_dir or (Path.home() / ".gemini" / "antigravity" / "brain")
        self.active_focus_id: Optional[str] = None
        self._cache: Dict[str, ConversationInfo] = {}

    def get_recent_transcripts(self, limit: int = 10) -> List[Path]:
        """Find recently modified transcript.jsonl files in brain directory."""
        if not self.brain_dir.is_dir():
            return []

        pattern = str(self.brain_dir / "*" / ".system_generated" / "logs" / "transcript.jsonl")
        files = glob.glob(pattern)
        if not files:
            return []

        def _get_conv_mtime(f: str) -> float:
            try:
                p = Path(f)
                full = p.parent / "transcript_full.jsonl"
                if full.is_file():
                    return max(os.path.getmtime(f), os.path.getmtime(str(full)))
                return os.path.getmtime(f)
            except Exception:
                return 0.0

        files.sort(key=_get_conv_mtime, reverse=True)
        return [Path(f) for f in files[:limit]]

    def _get_pb_titles(self) -> Dict[str, str]:
        """Extract genuine side-panel conversation titles from agyhub_summaries_proto.pb."""
        pb_path = Path.home() / ".gemini" / "antigravity" / "agyhub_summaries_proto.pb"
        if not pb_path.is_file():
            return {}
        try:
            data = pb_path.read_bytes()
            # Protobuf pattern: \n$ <36-byte uuid> \x12 <varint> \n <1-byte len> <title>
            pattern = rb"\n\$([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\x12[\x80-\xff]*[\x00-\x7f]\n([\x01-\x7f])"
            titles = {}
            for m in re.finditer(pattern, data):
                cid = m.group(1).decode("ascii")
                t_len = m.group(2)[0]
                t_start = m.end()
                t_bytes = data[t_start:t_start + t_len]
                title = t_bytes.decode("utf-8", errors="ignore").strip()
                if title and not title.startswith("file:///"):
                    titles[cid] = title
            return titles
        except Exception:
            return {}

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

            # Priority 1: Exact generated title from Antigravity's side panel summaries
            pb_titles = self._get_pb_titles()
            if conv_id in pb_titles and pb_titles[conv_id]:
                title = pb_titles[conv_id]
            else:
                # Fallback: Extract title from initial user prompt
                first_step = json.loads(lines[0])
                first_content = first_step.get("content", "")
                if first_content:
                    clean = re.sub(r"<USER_REQUEST>\s*", "", first_content)
                    clean = re.sub(r"</USER_REQUEST>.*", "", clean, flags=re.DOTALL)
                    clean = re.sub(r"/antigravity-guide\s*", "", clean)
                    clean = clean.strip()
                    if clean:
                        first_line = clean.split("\n")[0].strip()
                        title = first_line[:45] + ("..." if len(first_line) > 45 else "")

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
            )
            self._cache[conv_id] = info
            return info
        except Exception:
            return None

    def get_all_conversations(self, limit: int = 12) -> List[ConversationInfo]:
        """Return parsed list of recent conversations (Antigravity & Claude Code) sorted by recency."""
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

        # Sort all conversations chronologically by mtime
        results.sort(key=lambda x: x.mtime, reverse=True)
        return results[:limit]

    def set_active_focus(self, conv_id: str, transcript_path: Optional[Path] = None, title: Optional[str] = None):
        """Set the currently focused conversation ID and update session cookie."""
        self.active_focus_id = conv_id
        engine = "claude" if (conv_id.startswith("claude_") or "claude" in conv_id.lower()) else "antigravity"

        if not transcript_path and conv_id:
            if engine == "claude":
                clean_id = conv_id.replace("claude_", "")
                matches = list((Path.home() / ".claude" / "projects").glob(f"*/{clean_id}.jsonl"))
                if matches:
                    transcript_path = matches[0]
            else:
                candidate = self.brain_dir / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
                if candidate.is_file():
                    transcript_path = candidate

        if not title and transcript_path:
            info = parse_claude_session(transcript_path) if engine == "claude" else self.parse_conversation(transcript_path)
            if info:
                title = info.title
        save_session_cookie(
            conv_id=conv_id,
            transcript_path=str(transcript_path) if transcript_path else None,
            title=title,
            engine=engine,
        )

    def get_active_or_latest(self) -> Optional[ConversationInfo]:
        """
        Dynamically determine the currently active conversation (Antigravity or Claude Code).
        Prioritizes the most recently updated conversation based on transcript modification times
        and active session cookies.
        """
        convs = self.get_all_conversations(limit=10)
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
            if latest_conv.id == cid or (latest_conv.id.startswith("claude_") and latest_conv.id.replace("claude_", "") == cid):
                self.active_focus_id = latest_conv.id
                return latest_conv

            # If a different conversation was touched on disk after the cookie was saved,
            # that fresher conversation on disk takes immediate priority.
            if latest_conv.mtime > (cookie_time + 1.0):
                self.set_active_focus(latest_conv.id, transcript_path=latest_conv.transcript_path, title=latest_conv.title)
                self.active_focus_id = latest_conv.id
                return latest_conv

            # If cookie was very recently updated (< 60s) and not superseded by disk writes:
            if (now - cookie_time) < 60.0 and cookie_time >= (latest_conv.mtime - 1.0):
                for c in convs:
                    if c.id == cid or (c.id.startswith("claude_") and c.id.replace("claude_", "") == cid) or (cid.startswith("claude_") and cid.replace("claude_", "") == c.id):
                        self.active_focus_id = c.id
                        return c
                # Try parsing directly if path provided in cookie
                tpath = cookie.get("transcriptPath")
                if tpath and Path(tpath).is_file():
                    p = Path(tpath)
                    engine = cookie.get("engine", "antigravity")
                    if engine == "claude" or "claude" in str(p) or p.name.endswith(".jsonl"):
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
        self.set_active_focus(latest_conv.id, transcript_path=latest_conv.transcript_path, title=latest_conv.title)
        self.active_focus_id = latest_conv.id
        return latest_conv

    def get_conversation_details(self, conv_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full conversation details for Antigravity or Claude."""
        if not conv_id:
            return None

        # Check if this is a Claude Code session
        if conv_id.startswith("claude_"):
            clean_id = conv_id.replace("claude_", "")
            matches = list((Path.home() / ".claude" / "projects").glob(f"*/{clean_id}.jsonl"))
            if matches:
                return parse_full_claude_conversation_details(matches[0])

        transcript_path = self.brain_dir / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
        if transcript_path.is_file():
            return parse_full_conversation_details(transcript_path, brain_dir=self.brain_dir)

        # Check Claude sessions by raw stem
        matches = list((Path.home() / ".claude" / "projects").glob(f"*/{conv_id}.jsonl"))
        if matches:
            return parse_full_claude_conversation_details(matches[0])

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
    """Clean internal Antigravity tags and metadata from raw user input string."""
    if not content:
        return ""
    clean = content
    # Extract <USER_REQUEST>...</USER_REQUEST> if present
    m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", clean, re.DOTALL)
    if m:
        clean = m.group(1).strip()

    # Remove trailing metadata tags
    clean = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", clean, flags=re.DOTALL)
    clean = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", clean, flags=re.DOTALL)

    # Clean slash command prefixes like /antigravity-guide
    clean = re.sub(r"^/[a-zA-Z0-9_-]+\s*", "", clean).strip()
    return clean or content.strip()


def get_conversation_artifacts(conv_id: str, brain_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
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
                artifacts.append({
                    "name": item.name,
                    "path": str(item),
                    "size": item.stat().st_size,
                    "mtime": item.stat().st_mtime,
                    "extension": ext,
                    "is_markdown": ext in ("md", "markdown"),
                })
    except Exception:
        pass
    return artifacts


def get_artifact_content(conv_id: str, filename: str, brain_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
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


def parse_full_conversation_details(transcript_path: Path, brain_dir: Optional[Path] = None) -> Dict[str, Any]:
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
            msg_match = re.search(r"\[Message\][^\n]*\bcontent=(.*?)(?:\n</SYSTEM_MESSAGE>|\Z)", content, re.DOTALL)
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
                    t_name = tc.get("name") or tc.get("tool_name") or "tool"
                    t_args = tc.get("args", {})
                    t_summary = ""
                    t_action = ""
                    if isinstance(t_args, dict):
                        t_summary = str(t_args.get("toolSummary", "")).strip('\"')
                        t_action = str(t_args.get("toolAction", "")).strip('\"')
                    current_turn["agent_steps"].append({
                        "step_index": step_index,
                        "type": "tool_call",
                        "tool_name": t_name,
                        "summary": t_summary or t_name,
                        "action": t_action,
                        "args": t_args,
                        "status": step_status,
                        "output": None,
                        "created_at": created_at,
                    })
            elif stype == "GENERIC":
                # Tool output matching previous tool_call step
                if current_turn["agent_steps"]:
                    for s in reversed(current_turn["agent_steps"]):
                        if s.get("type") == "tool_call" and s.get("output") is None:
                            s["output"] = content
                            break
            elif stype == "PLANNER_RESPONSE" and source == "MODEL":
                if content:
                    current_turn["agent_response"] = content
                    current_turn["agent_role"] = step.get("role") or step.get("agent_role") or "antigravity"
                    if step_status == "DONE" and not tool_calls:
                        current_turn["status"] = "done"
                        current_turn["completed"] = True
            elif stype == "SYSTEM_MESSAGE":
                current_turn["agent_steps"].append({
                    "step_index": step_index,
                    "type": "system_message",
                    "tool_name": "system",
                    "summary": "System Update",
                    "action": "",
                    "args": {},
                    "status": step_status,
                    "output": content,
                    "created_at": created_at,
                })

    if current_turn:
        turns.append(current_turn)

    # Ensure overall status is 'agent_working' whenever the latest turn is active
    if turns and (not turns[-1].get("completed") or turns[-1].get("status") == "working"):
        status = "agent_working"

    artifacts = get_conversation_artifacts(conv_id, brain_dir=brain_dir)

    plan_info = None
    for art in artifacts:
        if art.get("name") == "implementation_plan.md":
            plan_info = {
                "name": "implementation_plan.md",
                "mtime": art.get("mtime"),
                "size": art.get("size"),
                "exists": True,
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


def parse_claude_session(session_path: Path) -> Optional[ConversationInfo]:
    """Parse a Claude Code session JSONL file into ConversationInfo."""
    try:
        p = Path(session_path)
        if not p.is_file():
            return None
        mtime = p.stat().st_mtime
        session_id = p.stem  # e.g. "c32203cb-5b68-4bbb-ba3e-18990b071640"
        conv_id = f"claude_{session_id}" if not session_id.startswith("claude_") else session_id

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
                        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
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
        title_prefix = f"Claude • {project_name}" if project_name else "Claude"
        if first_user_text:
            first_line = first_user_text.split("\n")[0].strip()
            clean_first = first_line[:40] + ("..." if len(first_line) > 40 else "")
            title = f"{title_prefix}: {clean_first}"
        else:
            title = f"{title_prefix} ({session_id[:8]})"

        status = "idle"
        if last_msg_type == "user" or has_tool_calls_pending:
            status = "agent_working"
        elif last_msg_type == "assistant" or last_assistant_text:
            status = "waiting_for_user"

        cleaned_agent_text = ""
        if last_assistant_text:
            from voicefi.integrations.antigravity import clean_markdown_for_speech
            cleaned_agent_text = clean_markdown_for_speech(last_assistant_text, max_words=60)

        return ConversationInfo(
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
                parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
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
                                current_turn["agent_steps"].append({
                                    "step_index": idx,
                                    "type": "tool_call",
                                    "tool_name": t_name,
                                    "summary": t_summary,
                                    "action": t_name,
                                    "args": t_input,
                                    "status": "DONE",
                                    "output": None,
                                    "created_at": created_at,
                                })
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
                elif att_type in ("tool_result", "hook_output") or "output" in att or "content" in att:
                    if current_turn["agent_steps"]:
                        for s in reversed(current_turn["agent_steps"]):
                            if s.get("output") is None:
                                s["output"] = att.get("output") or att.get("content") or ""
                                break

    if current_turn:
        turns.append(current_turn)

    # Artifacts: Search for plans in ~/.claude/plans and any workspace docs
    artifacts = []
    claude_plans_dir = Path.home() / ".claude" / "plans"
    if claude_plans_dir.is_dir():
        try:
            for item in sorted(claude_plans_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if item.is_file() and item.suffix in (".md", ".markdown"):
                    artifacts.append({
                        "name": item.name,
                        "path": str(item),
                        "size": item.stat().st_size,
                        "mtime": item.stat().st_mtime,
                        "extension": "md",
                        "is_markdown": True,
                    })
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



