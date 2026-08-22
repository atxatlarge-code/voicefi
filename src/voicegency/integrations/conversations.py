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
    cookie_dir = Path.home() / ".voicegency"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    return cookie_dir / "active_session.json"


def claim_turn(conv_id: str, signature: str) -> bool:
    """
    Atomically claims a turn so only one worker (Hook or Watcher) handles it.
    Returns True if this caller claimed the turn, False if already claimed recently.
    """
    turn_file = Path("/tmp/voicegency_active_turn.json")
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
            elif step_type == "USER_INPUT":
                status = "agent_working"
                last_user_text = last_step.get("content", "") or ""

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
