"""
VoiceFi Utterance Ring Buffer & Zero-Cost Replay Dispatcher.
Maintains a lightweight 10-utterance JSONL ring buffer at /tmp/vifi_history.jsonl
containing transcribed payloads and metadata (timestamp, audio_duration, target_route)
written right before dispatching over /tmp/vifi.sock.
"""

import datetime
import json
import logging
import os
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from voicefi.ipc.protocol import build_prompt_dispatch_event

logger = logging.getLogger("voicefi.ipc.history")

DEFAULT_HISTORY_PATH = "/tmp/vifi_history.jsonl"
DEFAULT_VIFI_SOCKET_PATH = "/tmp/vifi.sock"
FALLBACK_SOCKET_PATH = "/tmp/voicefi.sock"
MAX_HISTORY_ENTRIES = 10


def resolve_history_path(history_path: Optional[Union[str, Path]] = None) -> Path:
    """Resolve the ring buffer file path, honoring VIFI_HISTORY_PATH env override."""
    if history_path is not None:
        return Path(history_path)
    env_path = os.environ.get("VIFI_HISTORY_PATH")
    if env_path:
        return Path(env_path)
    return Path(DEFAULT_HISTORY_PATH)


def record_utterance_history(
    transcript: str,
    target_route: str = "antigravity",
    audio_duration: float = 0.0,
    timestamp: Optional[float] = None,
    source: str = "whisperkit",
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    history_path: Optional[Union[str, Path]] = None,
    max_entries: int = MAX_HISTORY_ENTRIES,
    deduplicate_window: float = 0.0,
) -> Dict[str, Any]:
    """
    Write a transcribed utterance and metadata (timestamp, audio_duration, target_route)
    to the ring buffer at /tmp/vifi_history.jsonl, keeping the last `max_entries` (10) utterances.
    """
    clean_text = (transcript or "").strip()
    now_ts = float(timestamp if timestamp is not None else time.time())
    iso_ts = datetime.datetime.fromtimestamp(now_ts, tz=datetime.timezone.utc).isoformat()
    dur = round(float(audio_duration or 0.0), 3)
    route = (target_route or "antigravity").strip()

    extra_meta: Dict[str, Any] = dict(metadata) if isinstance(metadata, dict) else {}
    extra_meta.setdefault("timestamp", now_ts)
    extra_meta.setdefault("audio_duration", dur)
    extra_meta.setdefault("target_route", route)

    entry: Dict[str, Any] = {
        "transcript": clean_text,
        "payload": clean_text,
        "timestamp": now_ts,
        "iso_timestamp": iso_ts,
        "audio_duration": dur,
        "target_route": route,
        "source": source,
        "session_id": session_id,
        "metadata": extra_meta,
    }

    path = resolve_history_path(history_path)
    existing = load_utterance_history(history_path=path, max_entries=max_entries * 2)
    if (
        deduplicate_window > 0
        and existing
        and existing[-1].get("transcript") == clean_text
        and abs(now_ts - float(existing[-1].get("timestamp", 0.0))) <= deduplicate_window
    ):
        if dur > 0 and not existing[-1].get("audio_duration"):
            existing[-1]["audio_duration"] = dur
            existing[-1]["metadata"]["audio_duration"] = dur
        if route and existing[-1].get("target_route") in (None, "", "active"):
            existing[-1]["target_route"] = route
            existing[-1]["metadata"]["target_route"] = route
        ring = existing[-max_entries:] if max_entries > 0 else existing
    else:
        existing.append(entry)
        ring = existing[-max_entries:] if max_entries > 0 else existing

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in ring)
        tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
        tmp_path.write_text(serialized, encoding="utf-8")
        tmp_path.replace(path)
    except Exception as e:
        logger.debug("Atomic write to %s failed (%s); falling back to direct write", path, e)
        try:
            with open(path, "w", encoding="utf-8") as f:
                for item in ring:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception as e2:
            logger.warning("Could not write utterance history to %s: %s", path, e2)

    return entry


def load_utterance_history(
    history_path: Optional[Union[str, Path]] = None,
    max_entries: int = MAX_HISTORY_ENTRIES,
) -> List[Dict[str, Any]]:
    """Read up to the last `max_entries` utterances from /tmp/vifi_history.jsonl."""
    path = resolve_history_path(history_path)
    if not path.is_file():
        return []

    entries: List[Dict[str, Any]] = []
    try:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in raw_lines:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                parsed = json.loads(line_str)
                if isinstance(parsed, dict):
                    # Normalize payload / transcript aliases if written by external producer
                    text_val = (
                        parsed.get("transcript")
                        or parsed.get("payload")
                        or parsed.get("text")
                        or ""
                    )
                    parsed.setdefault("transcript", text_val)
                    parsed.setdefault("payload", text_val)
                    meta = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
                    parsed.setdefault(
                        "target_route",
                        meta.get("target_route") or parsed.get("target") or "antigravity",
                    )
                    parsed.setdefault(
                        "audio_duration",
                        float(meta.get("audio_duration") or parsed.get("duration") or 0.0),
                    )
                    parsed.setdefault(
                        "timestamp",
                        float(meta.get("timestamp") or time.time()),
                    )
                    entries.append(parsed)
            except Exception:
                continue
    except Exception as e:
        logger.debug("Error reading history file %s: %s", path, e)
        return []

    if max_entries > 0:
        return entries[-max_entries:]
    return entries


def get_last_utterance(
    history_path: Optional[Union[str, Path]] = None,
    index: int = -1,
) -> Optional[Dict[str, Any]]:
    """
    Retrieve the latest utterance (default index=-1) or a specific entry from the ring buffer.
    Supports negative indexing (-1 is latest, -2 is previous) or 0-based positive indexing.
    """
    entries = load_utterance_history(history_path=history_path, max_entries=MAX_HISTORY_ENTRIES)
    if not entries:
        return None
    try:
        return entries[index]
    except IndexError:
        return entries[-1]


def dispatch_payload_over_socket(
    transcript: str,
    target_route: str = "antigravity",
    audio_duration: float = 0.0,
    session_id: Optional[str] = None,
    source: str = "whisperkit",
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
    socket_path: Optional[str] = None,
    record_history: bool = False,
    history_path: Optional[Union[str, Path]] = None,
    timeout: float = 1.5,
) -> bool:
    """
    Dispatch a transcribed prompt payload over the Unix domain socket (/tmp/vifi.sock
    or /tmp/voicefi.sock). Optionally writes to /tmp/vifi_history.jsonl right before dispatching.
    """
    clean_text = (transcript or "").strip()
    if not clean_text:
        return False

    now_ts = time.time()
    meta: Dict[str, Any] = dict(metadata) if isinstance(metadata, dict) else {}
    meta.update(
        {
            "timestamp": meta.get("timestamp", now_ts),
            "audio_duration": float(
                audio_duration if audio_duration is not None else meta.get("audio_duration", 0.0)
            ),
            "target_route": target_route or meta.get("target_route", "antigravity"),
        }
    )

    if record_history:
        record_utterance_history(
            transcript=clean_text,
            target_route=meta["target_route"],
            audio_duration=meta["audio_duration"],
            timestamp=meta["timestamp"],
            source=source,
            session_id=session_id,
            metadata=meta,
            history_path=history_path,
        )

    event = build_prompt_dispatch_event(
        transcript=clean_text,
        session_id=session_id,
        source=source,
        confidence=confidence,
        metadata=meta,
    )
    event["params"]["target_route"] = meta["target_route"]
    event["params"]["audio_duration"] = meta["audio_duration"]
    event["params"]["timestamp"] = meta["timestamp"]

    candidates: List[str] = []
    if socket_path:
        candidates.append(socket_path)
    else:
        env_sock = os.environ.get("VIFI_SOCKET_PATH")
        if env_sock:
            candidates.append(env_sock)
        candidates.extend([DEFAULT_VIFI_SOCKET_PATH, FALLBACK_SOCKET_PATH])

    raw_bytes = (json.dumps(event) + "\n").encode("utf-8")
    for cand in candidates:
        sock_p = Path(cand)
        if not sock_p.exists():
            continue
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(timeout)
                client.connect(str(sock_p))
                client.sendall(raw_bytes)
            return True
        except Exception as e:
            logger.debug("Socket dispatch to %s failed: %s", cand, e)
            continue

    return False
