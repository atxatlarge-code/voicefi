"""
Atomic cross-process turn claim mutex and session origin tracking.
Ensures that exactly one worker (CLI Hook or Background Watcher) handles speech and mic capture,
and coordinates audio routing between Mac CoreAudio and mobile companions.
"""

import errno
import fcntl
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable


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


def _atomic_write_json(target_path: Path, data: Any) -> None:
    """Write JSON atomically via temp file with guaranteed cleanup on failure."""
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=target_path.parent, delete=False) as tf:
            temp_name = tf.name
            json.dump(data, tf)
        os.replace(temp_name, str(target_path))
        temp_name = None
    except Exception:
        # Fallback direct write
        with open(target_path, "w") as f:
            json.dump(data, f)
    finally:
        if temp_name and os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def is_pid_alive(pid: int) -> bool:
    """Check if process with given PID is currently active."""
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        # EPERM means process exists but we lack permission to signal it
        return e.errno == errno.EPERM


_ACTIVE_TURNS_FILE = Path("/tmp/voicefi_active_turns.json")
_ACTIVE_TURNS_LOCK = Path("/tmp/voicefi_active_turns.lock")
_MOBILE_TURN_FILE = Path("/tmp/voicefi_mobile_turn.json")
_COMPANION_CLIENTS_FILE = Path("/tmp/voicefi_companion_clients.json")


def claim_turn(
    conv_id: Optional[str],
    signature: str,
    origin: Optional[str] = None,
    step_index: Optional[int] = None,
    turn_id: Optional[str] = None,
    delivered_via: str = "hook",
    spoken_on_mac: bool = False,
) -> bool:
    """
    Atomically claims a turn using cross-process file locks so only one worker
    (CLI Hook or Background Watcher) handles speech and mic capture.
    Validates process liveness so crashed server threads never cause permanent turn lockouts.
    Returns True if this caller claimed the turn, False if already claimed recently.
    """
    turn_file = _ACTIVE_TURNS_FILE
    lock_file = _ACTIVE_TURNS_LOCK
    now = time.time()
    norm_sig = _normalize_turn_signature(signature)

    # Derive canonical step_index if embedded in signature (e.g. "conv_id:step_42" or "step:42")
    resolved_step_idx = step_index
    if resolved_step_idx is None:
        m = re.search(r"\bstep[_\s:]+(\d+)\b", signature, re.IGNORECASE)
        if m:
            resolved_step_idx = int(m.group(1))

    canonical_turn_id = turn_id or (
        f"{conv_id}:step_{resolved_step_idx}"
        if conv_id and resolved_step_idx is not None and resolved_step_idx >= 0
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

                # Clean entries older than 60 seconds
                valid_entries = [e for e in entries if (now - float(e.get("timestamp", 0))) < 60.0]

                # Check if this exact turn_id, step_index, signature, OR normalized text was already claimed
                for e in valid_entries:
                    e_pid = e.get("pid")
                    e_status = e.get("status", "claimed")
                    e_ts = float(e.get("timestamp", 0))
                    # If claiming process died mid-flight before completion, ignore stale lock
                    # BUT if timestamp is within recent debounce window (< 4.0s), respect the lock
                    if e_pid and e_status != "completed" and not is_pid_alive(int(e_pid)):
                        if (now - e_ts) >= 4.0:
                            continue

                    e_sig = e.get("signature", "")
                    e_norm = e.get("norm_sig") or _normalize_turn_signature(e_sig)
                    e_cid = e.get("conv_id", "")
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

                    # If both this turn and the recorded turn have explicit, distinct step indices
                    # (e.g. step 2136 vs step 2134), they represent distinct conversational turns
                    # and must NOT be suppressed by text/signature matching.
                    is_distinct_step = (
                        resolved_step_idx is not None
                        and resolved_step_idx >= 0
                        and e_step is not None
                        and e_step >= 0
                        and resolved_step_idx != e_step
                    )

                    if not is_distinct_step:
                        # 3. Exact signature string match
                        if e_sig == signature:
                            return False

                        # 4. Normalized text match or strong prefix match
                        if norm_sig and e_norm:
                            if norm_sig == e_norm:
                                return False
                            if len(norm_sig) >= 15 and len(e_norm) >= 15:
                                if norm_sig[:20] == e_norm[:20]:
                                    return False

                    # 5. Conversation-level rapid debounce & explicit speech suppression
                    if conv_id and e_cid == conv_id:
                        # Suppress generic turn-end speech if an explicit speech tool/command ran in this conversation within 3s
                        if "explicit" in e_sig and (now - e_ts) < 3.0:
                            return False
                        if (resolved_step_idx is None or resolved_step_idx == e_step) and (
                            now - e_ts
                        ) < 3.0:
                            return False

                # Claim this turn atomically
                valid_entries.append(
                    {
                        "conv_id": conv_id,
                        "turn_id": canonical_turn_id,
                        "step_index": resolved_step_idx,
                        "signature": signature,
                        "norm_sig": norm_sig,
                        "origin": resolved_origin,
                        "delivered_via": delivered_via,
                        "spoken_on_mac": spoken_on_mac,
                        "timestamp": now,
                        "pid": os.getpid(),
                        "status": "claimed",
                    }
                )
                # Keep up to 25 entries
                if len(valid_entries) > 25:
                    valid_entries = valid_entries[-25:]

                _atomic_write_json(turn_file, valid_entries)

                return True
            finally:
                fcntl.flock(lock_fp, fcntl.LOCK_UN)
    except Exception:
        # Fallback to permissive execution if locking fails
        return True


def mark_turn_completed(
    turn_id: Optional[str] = None,
    conv_id: Optional[str] = None,
    step_index: Optional[int] = None,
) -> None:
    """Mark active turn as completed so its speech output is recorded."""
    if not turn_id and not conv_id:
        return
    turn_file = _ACTIVE_TURNS_FILE
    lock_file = _ACTIVE_TURNS_LOCK
    try:
        if not turn_file.is_file():
            return
        with open(lock_file, "a+") as lock_fp:
            fcntl.flock(lock_fp, fcntl.LOCK_EX)
            try:
                entries = []
                with open(turn_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        entries = data
                for e in entries:
                    match = False
                    if turn_id and (e.get("turn_id") == turn_id or e.get("signature") == turn_id):
                        match = True
                    elif conv_id and e.get("conv_id") == conv_id:
                        if step_index is None or e.get("step_index") == step_index:
                            match = True
                    if match:
                        e["status"] = "completed"
                _atomic_write_json(turn_file, entries)
            finally:
                fcntl.flock(lock_fp, fcntl.LOCK_UN)
    except Exception:
        pass


def mark_turn_spoken_on_mac(
    conv_id: Optional[str] = None,
    signature: Optional[str] = None,
    step_index: Optional[int] = None,
    turn_id: Optional[str] = None,
) -> bool:
    """
    Mark that this turn's speech was synthesized and played aloud on Mac desktop CoreAudio.
    Used by Companion to suppress duplicate speech when running alongside a desktop coding agent.
    """
    turn_file = _ACTIVE_TURNS_FILE
    lock_file = _ACTIVE_TURNS_LOCK
    try:
        if not turn_file.is_file():
            return False
        norm_sig = _normalize_turn_signature(signature) if signature else ""
        with open(lock_file, "a+") as lock_fp:
            fcntl.flock(lock_fp, fcntl.LOCK_EX)
            try:
                entries = []
                with open(turn_file, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        entries = data
                matched = False
                for e in entries:
                    match = False
                    if turn_id and (e.get("turn_id") == turn_id or e.get("signature") == turn_id):
                        match = True
                    elif conv_id and e.get("conv_id") == conv_id:
                        if step_index is not None and e.get("step_index") is not None:
                            if e.get("step_index") == step_index:
                                match = True
                        elif signature:
                            e_sig = e.get("signature", "")
                            e_norm = e.get("norm_sig") or _normalize_turn_signature(e_sig)
                            if e_sig == signature or (norm_sig and e_norm == norm_sig):
                                match = True
                        else:
                            # If no signature or step_index specified, mark the latest entry for this conv_id
                            match = True
                    if match:
                        e["spoken_on_mac"] = True
                        matched = True
                        break
                if matched:
                    _atomic_write_json(turn_file, entries)
                    return True

            finally:
                fcntl.flock(lock_fp, fcntl.LOCK_UN)
    except Exception:
        pass
    return False


def claim_active_conversation_turn(
    text: str,
    conv_id: Optional[str] = None,
    step_index: Optional[int] = None,
    origin: Optional[str] = None,
    conv_id_resolver: Optional[Callable[[], Optional[str]]] = None,
) -> bool:
    """
    Record an explicit speech action during an active conversation turn so turn-end hooks
    automatically suppress duplicate summary speech.
    """
    cid = conv_id
    if not cid and conv_id_resolver:
        try:
            cid = conv_id_resolver()
        except Exception:
            cid = None
    if not cid:
        try:
            from voicefi.integrations.conversations import load_session_cookie

            cookie = load_session_cookie()
            if cookie:
                cid = cookie.get("conv_id")
        except Exception:
            pass
    if not cid:
        return False
    norm = _normalize_turn_signature(text)
    turn_sig = f"{cid}:explicit_{norm}"
    return claim_turn(cid, turn_sig, origin=origin, step_index=step_index)


def get_claimed_turn_origin(
    conv_id: Optional[str],
    signature: str,
    step_index: Optional[int] = None,
) -> Optional[str]:
    """Get the origin (mobile or desktop) recorded when this turn was claimed."""
    turn_file = _ACTIVE_TURNS_FILE
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
                if conv_id and e_cid == conv_id and step_index is not None and e_step is not None:
                    if e_step == step_index:
                        return e.get("origin")
                    continue
                if e_sig == signature or (norm_sig and e_norm == norm_sig):
                    if step_index is None or e_step is None or step_index == e_step:
                        return e.get("origin")
            # Recent conversation fallback: if this conversation was claimed with mobile origin within last 60s
            for e in reversed(entries):
                e_cid = e.get("conv_id", "")
                e_ts = float(e.get("timestamp", 0))
                if conv_id and e_cid == conv_id and (time.time() - e_ts) < 60.0:
                    if e.get("origin") == "mobile":
                        return "mobile"
    except Exception:
        pass
    return None


def get_turn_delivery_info(
    conv_id: Optional[str],
    signature: str,
    step_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Get delivery provenance (hook vs otherwise/watcher, spoken_on_mac, origin) for a turn.
    Used by Companion to check if a coding agent turn was delivered via hook or otherwise.
    """
    turn_file = _ACTIVE_TURNS_FILE
    default_info = {
        "delivered_via": "otherwise",
        "delivered_via_hook": False,
        "spoken_on_mac": False,
        "origin": "desktop",
        "status": "unknown",
    }
    if not turn_file.is_file():
        return default_info
    try:
        norm_sig = _normalize_turn_signature(signature) if signature else ""
        with open(turn_file, "r") as f:
            entries = json.load(f)
        if isinstance(entries, list):
            for e in reversed(entries):
                e_sig = e.get("signature", "")
                e_norm = e.get("norm_sig") or _normalize_turn_signature(e_sig)
                e_cid = e.get("conv_id", "")
                e_step = e.get("step_index")
                match = False
                if conv_id and e_cid == conv_id and step_index is not None and e_step is not None:
                    if e_step == step_index:
                        match = True
                    else:
                        continue
                elif signature and (e_sig == signature or (norm_sig and e_norm == norm_sig)):
                    if step_index is None or e_step is None or step_index == e_step:
                        match = True

                if match:
                    d_via = e.get("delivered_via", "hook")
                    return {
                        "delivered_via": d_via,
                        "delivered_via_hook": (d_via == "hook"),
                        "spoken_on_mac": bool(e.get("spoken_on_mac", False)),
                        "origin": e.get("origin", "desktop"),
                        "status": e.get("status", "claimed"),
                    }
            # Fallback by conversation id within recent 60s
            for e in reversed(entries):
                e_cid = e.get("conv_id", "")
                e_ts = float(e.get("timestamp", 0))
                if conv_id and e_cid == conv_id and (time.time() - e_ts) < 60.0:
                    d_via = e.get("delivered_via", "hook")
                    return {
                        "delivered_via": d_via,
                        "delivered_via_hook": (d_via == "hook"),
                        "spoken_on_mac": bool(e.get("spoken_on_mac", False)),
                        "origin": e.get("origin", "desktop"),
                        "status": e.get("status", "claimed"),
                    }
    except Exception:
        pass
    return default_info


def set_mobile_turn_origin(conv_id: Optional[str] = None) -> None:
    """Record that the current pending turn was initiated from mobile companion."""
    origin_file = _MOBILE_TURN_FILE
    try:
        data = {
            "conv_id": conv_id or "active",
            "timestamp": time.time(),
        }
        with open(origin_file, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def _matches_mobile_turn(cid: Optional[str], conv_id: Optional[str]) -> bool:
    if not conv_id or not cid or cid == "active" or conv_id == "active":
        return True
    if cid == conv_id:
        return True
    clean_cid = str(cid).replace("claude_", "").replace("codex_", "")
    clean_conv = str(conv_id).replace("claude_", "").replace("codex_", "")
    if clean_cid == clean_conv:
        return True
    if (str(cid).startswith("claude") or "claude" in str(cid)) and (
        str(conv_id).startswith("claude") or "claude" in str(conv_id)
    ):
        return True
    if (str(cid).startswith("codex") or "codex" in str(cid)) and (
        str(conv_id).startswith("codex") or "codex" in str(conv_id)
    ):
        return True
    return False


def peek_mobile_turn_origin(conv_id: Optional[str] = None, max_age_seconds: float = 300.0) -> bool:
    """
    Check if the pending turn originated from mobile companion without consuming the marker.
    """
    origin_file = _MOBILE_TURN_FILE
    if not origin_file.is_file():
        return False
    try:
        with open(origin_file, "r") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        cid = data.get("conv_id")
        if (time.time() - ts) < max_age_seconds:
            if _matches_mobile_turn(cid, conv_id):
                return True
    except Exception:
        pass
    return False


def pop_mobile_turn_origin(conv_id: Optional[str] = None, max_age_seconds: float = 300.0) -> bool:
    """
    Check and consume mobile turn origin marker.
    Returns True if the completed turn originated from mobile companion (and consumes the marker), False otherwise.
    """
    origin_file = _MOBILE_TURN_FILE
    if not origin_file.is_file():
        return False
    try:
        with open(origin_file, "r") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        cid = data.get("conv_id")
        if (time.time() - ts) < max_age_seconds:
            if _matches_mobile_turn(cid, conv_id):
                origin_file.unlink(missing_ok=True)
                return True
        else:
            origin_file.unlink(missing_ok=True)
    except Exception:
        pass
    return False


def record_companion_heartbeat(
    num_clients: int = 1,
    num_mobile_clients: Optional[int] = None,
    has_mobile: Optional[bool] = None,
) -> None:
    """
    Record active companion client heartbeat to allow Mac to coordinate audio routing.
    Distinguishes between local laptop desktop browser companion tabs and remote phone companions.
    """
    heartbeat_file = _COMPANION_CLIENTS_FILE
    try:
        if has_mobile is not None:
            is_mobile_active = bool(has_mobile) and (num_clients > 0)
        elif num_mobile_clients is not None:
            is_mobile_active = (num_mobile_clients > 0) and (num_clients > 0)
        else:
            # Backward-compatible default: single client parameter implies active mobile companion
            is_mobile_active = num_clients > 0

        data = {
            "clients": max(0, num_clients),
            "mobile_clients": max(
                0,
                num_mobile_clients
                if num_mobile_clients is not None
                else (1 if is_mobile_active else 0),
            ),
            "has_mobile": is_mobile_active,
            "timestamp": time.time(),
        }
        with open(heartbeat_file, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def has_active_companion_client(
    max_age_seconds: float = 25.0, require_mobile: bool = False
) -> bool:
    """
    Return True if at least one companion client is connected and active.
    If require_mobile=False (default), any active companion (remote phone or browser) returns True
    so that Mac desktop audio is muted when mute_mac_when_companion_active is enabled.
    """
    heartbeat_file = _COMPANION_CLIENTS_FILE
    if not heartbeat_file.is_file():
        return False
    try:
        with open(heartbeat_file, "r") as f:
            data = json.load(f)
        ts = data.get("timestamp", 0)
        count = data.get("clients", 0)
        has_mobile = (
            data.get("has_mobile", True)
            if "has_mobile" in data
            else (data.get("mobile_clients", 1) > 0)
        )
        if (time.time() - ts) < max_age_seconds and count > 0:
            if require_mobile:
                return bool(has_mobile)
            return True
    except Exception:
        pass
    return False


def has_active_mobile_companion(max_age_seconds: float = 25.0) -> bool:
    """Return True if at least one remote/mobile phone companion client is connected."""
    return has_active_companion_client(max_age_seconds=max_age_seconds, require_mobile=True)


def clear_companion_heartbeat() -> None:
    """Clear companion client heartbeat."""
    heartbeat_file = _COMPANION_CLIENTS_FILE
    try:
        heartbeat_file.unlink(missing_ok=True)
    except Exception:
        pass
