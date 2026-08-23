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


def claim_turn(conv_id: str, signature: str) -> bool:
    """
    Atomically claims a turn so only one worker (Hook or Watcher) handles it.
    Returns True if this caller claimed the turn, False if already claimed recently.
    """
    turn_file = Path("/tmp/voicefi_active_turn.json")
    now = time.time()
    try:
        if turn_file.is_file():
            with open(turn_file, "r") as f:
                data = json.load(f)
                if data.get("signature") == signature and (now - data.get("timestamp", 0)) < 12.0:
                    return False
        with open(turn_file, "w") as f:
            json.dump({"conv_id": conv_id, "signature": signature, "timestamp": now}, f)
        return True
    except Exception:
        return True


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


def peek_mobile_turn_origin(conv_id: Optional[str] = None, max_age_seconds: float = 300.0) -> bool:
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


def pop_mobile_turn_origin(conv_id: Optional[str] = None, max_age_seconds: float = 300.0) -> bool:
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
) -> None:
    """Save active conversation metadata handshake ('cookie') to disk."""
    if not conv_id:
        return
    cookie_path = get_session_cookie_path()
    data = {
        "conversationId": conv_id,
        "transcriptPath": str(transcript_path) if transcript_path else "",
        "title": title or "",
        "workspacePath": str(workspace_path) if workspace_path else "",
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
    """Load the latest active Antigravity session cookie if present."""
    cookie_path = get_session_cookie_path()
    if not cookie_path.is_file():
        return None
    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data and isinstance(data, dict) and data.get("conversationId"):
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

        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
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

    def get_all_conversations(self, limit: int = 8) -> List[ConversationInfo]:
        """Return parsed list of recent conversations sorted by recency."""
        paths = self.get_recent_transcripts(limit=limit)
        results = []
        for p in paths:
            info = self.parse_conversation(p)
            if info:
                results.append(info)
        return results

    def set_active_focus(self, conv_id: str, transcript_path: Optional[Path] = None, title: Optional[str] = None):
        """Set the currently focused conversation ID and update session cookie."""
        self.active_focus_id = conv_id
        if not transcript_path and conv_id:
            candidate = self.brain_dir / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
            if candidate.is_file():
                transcript_path = candidate
        if not title and transcript_path:
            info = self.parse_conversation(transcript_path)
            if info:
                title = info.title
        save_session_cookie(conv_id=conv_id, transcript_path=str(transcript_path) if transcript_path else None, title=title)

    def get_active_or_latest(self) -> Optional[ConversationInfo]:
        """
        Dynamically determine the currently active Antigravity conversation.
        Prioritizes the most recently updated conversation based on session cookie
        and transcript modification times.
        """
        convs = self.get_all_conversations(limit=5)
        if not convs:
            return None

        latest_conv = convs[0]

        # Check persistent session cookie from recent Antigravity hooks
        cookie = load_session_cookie()
        if cookie and cookie.get("conversationId"):
            cid = cookie["conversationId"]
            cookie_time = float(cookie.get("updatedAt", 0))
            
            # If cookie is newer than or very close to disk mtime, honor cookie
            if cookie_time >= (latest_conv.mtime - 3.0):
                for c in convs:
                    if c.id == cid:
                        self.active_focus_id = cid
                        return c
                # If not in top convs, try parsing directly
                tpath = cookie.get("transcriptPath")
                p = Path(tpath) if tpath else (self.brain_dir / cid / ".system_generated" / "logs" / "transcript.jsonl")
                if p.is_file():
                    info = self.parse_conversation(p)
                    if info:
                        self.active_focus_id = cid
                        return info

        # Otherwise the most recently touched conversation is active
        self.active_focus_id = latest_conv.id
        return latest_conv

    def get_conversation_details(self, conv_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full conversation details including turns, working logs, and artifacts."""
        if not conv_id:
            return None
        transcript_path = self.brain_dir / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
        if not transcript_path.is_file():
            return None
        return parse_full_conversation_details(transcript_path, brain_dir=self.brain_dir)

    def get_artifact(self, conv_id: str, filename: str) -> Optional[Dict[str, Any]]:
        """Retrieve an artifact by filename for a given conversation."""
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


