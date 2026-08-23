"""
Acoustic Echo Cancellation & Self-Hearing Filter.
Prevents AI agents and companion loops from hearing/transcribing their own spoken TTS outputs,
questions, chimes, or acoustic speaker bleed.
"""

import os
import re
import json
import time
import difflib
from pathlib import Path
from typing import Optional, List, Dict

LAST_SPOKEN_FILE = Path("/tmp/voicefi_last_spoken.json")
_RECENT_SPOKEN_ENTRIES: List[Dict[str, float]] = []


def record_agent_spoken(text: str, duration: float = 0.0) -> None:
    """
    Record that an AI agent or TTS engine spoke text aloud with timestamp.
    Persists across in-memory threads and cross-process storage in /tmp.
    """
    if not text or not text.strip():
        return
    clean_text = text.strip()
    now = time.time()
    _RECENT_SPOKEN_ENTRIES.append({"text": clean_text, "timestamp": now, "duration": duration})

    # Keep only last 15 entries within 90s
    while len(_RECENT_SPOKEN_ENTRIES) > 15 or (_RECENT_SPOKEN_ENTRIES and (now - _RECENT_SPOKEN_ENTRIES[0]["timestamp"]) > 90.0):
        _RECENT_SPOKEN_ENTRIES.pop(0)

    # Persist across processes
    try:
        LAST_SPOKEN_FILE.write_text(json.dumps({
            "text": clean_text,
            "timestamp": now,
            "duration": duration,
            "history": _RECENT_SPOKEN_ENTRIES[-5:]
        }))
    except Exception:
        pass


def clear_agent_spoken_history() -> None:
    """Clear recorded spoken history (useful for testing)."""
    global _RECENT_SPOKEN_ENTRIES
    _RECENT_SPOKEN_ENTRIES.clear()
    try:
        LAST_SPOKEN_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def get_recent_spoken_texts(max_age_seconds: float = 60.0) -> List[str]:
    """Retrieve all recent agent spoken utterances within the time window."""
    now = time.time()
    candidates = [e["text"] for e in _RECENT_SPOKEN_ENTRIES if (now - e["timestamp"]) <= max_age_seconds]

    # Also check disk for cross-process entries
    try:
        if LAST_SPOKEN_FILE.is_file():
            data = json.loads(LAST_SPOKEN_FILE.read_text())
            ts = float(data.get("timestamp", 0))
            if (now - ts) <= max_age_seconds:
                txt = data.get("text", "")
                if txt and txt not in candidates:
                    candidates.append(txt)
            for h in data.get("history", []):
                h_ts = float(h.get("timestamp", 0))
                if (now - h_ts) <= max_age_seconds:
                    h_txt = h.get("text", "")
                    if h_txt and h_txt not in candidates:
                        candidates.append(h_txt)
    except Exception:
        pass

    return candidates


def is_acoustic_echo(
    transcript: str,
    reference_text: Optional[str] = None,
    max_age_seconds: float = 60.0,
    similarity_threshold: float = 0.55,
) -> bool:
    """
    Determine if a transcribed string is an acoustic echo of what the agent itself just spoke.
    Checks:
      1. Normalized text identity
      2. Substring & n-gram phrase containment (e.g. "Stage on Railway" inside "Stage on Railway or ship straightaway?")
      3. Word overlap ratio (>= 50% overlap of meaningful words)
      4. SequenceMatcher fuzzy similarity ratio (>= similarity_threshold)
    """
    if not transcript or not transcript.strip():
        return False

    # Normalize transcript
    clean_trans = re.sub(r"[^a-z0-9\s]", "", transcript.lower()).strip()
    clean_trans = re.sub(r"\s+", " ", clean_trans)
    if not clean_trans or len(clean_trans) < 3:
        return False

    trans_words = set(clean_trans.split())
    # Exclude common short noise words
    stop_words = {"the", "a", "an", "is", "it", "to", "in", "on", "of", "and", "or", "for", "do", "you", "we", "i"}
    trans_words_filtered = {w for w in trans_words if len(w) > 2 and w not in stop_words}
    if not trans_words_filtered:
        trans_words_filtered = trans_words

    references = []
    if reference_text:
        references.append(reference_text)
    references.extend(get_recent_spoken_texts(max_age_seconds=max_age_seconds))

    for ref in references:
        if not ref:
            continue
        clean_ref = re.sub(r"[^a-z0-9\s]", "", ref.lower()).strip()
        clean_ref = re.sub(r"\s+", " ", clean_ref)
        if not clean_ref:
            continue

        # 1. Exact match
        if clean_trans == clean_ref:
            return True

        # 2. Substring / phrase match in either direction
        if clean_trans in clean_ref or (len(clean_ref) >= 8 and clean_ref in clean_trans):
            return True

        # 3. Word overlap ratio
        ref_words = set(clean_ref.split())
        ref_words_filtered = {w for w in ref_words if len(w) > 2 and w not in stop_words}
        if not ref_words_filtered:
            ref_words_filtered = ref_words

        if trans_words_filtered and ref_words_filtered:
            overlap = trans_words_filtered.intersection(ref_words_filtered)
            overlap_ratio = len(overlap) / len(trans_words_filtered)
            if overlap_ratio >= 0.5:
                return True

        # 4. Fuzzy sequence similarity
        ratio = difflib.SequenceMatcher(None, clean_trans, clean_ref).ratio()
        if ratio >= similarity_threshold:
            return True

    return False
