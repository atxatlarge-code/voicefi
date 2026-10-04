"""
Persistent Turn Session Memory for VoiceFi.
Maintains recent agent turn contexts, full responses, spoken summaries,
and metadata to support contextual readout expansion ("tell me everything")
and edge model conversational review.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List


@dataclass
class TurnRecord:
    conv_id: str
    agent_name: str
    full_text: str
    spoken_text: str
    format_used: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class TurnSessionMemory:
    """In-memory persistent store for recent agent turns across conversations."""

    _instance: Optional["TurnSessionMemory"] = None

    def __init__(self, max_history_per_conv: int = 10):
        self._history: Dict[str, List[TurnRecord]] = {}
        self._latest_record: Optional[TurnRecord] = None
        self._max_history = max_history_per_conv

    @classmethod
    def get_instance(cls) -> "TurnSessionMemory":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record_turn(
        self,
        conv_id: str,
        full_text: str,
        spoken_text: str,
        agent_name: str = "antigravity",
        format_used: str = "first_sentence",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TurnRecord:
        """Store a completed turn in session memory."""
        cid = conv_id or "default"
        rec = TurnRecord(
            conv_id=cid,
            agent_name=agent_name,
            full_text=full_text,
            spoken_text=spoken_text,
            format_used=format_used,
            timestamp=time.time(),
            metadata=metadata or {},
        )
        if cid not in self._history:
            self._history[cid] = []
        self._history[cid].append(rec)
        if len(self._history[cid]) > self._max_history:
            self._history[cid].pop(0)

        self._latest_record = rec
        return rec

    def get_latest_turn(self, conv_id: Optional[str] = None) -> Optional[TurnRecord]:
        """Get the most recent turn for a specific conversation or globally."""
        if conv_id and conv_id in self._history and self._history[conv_id]:
            return self._history[conv_id][-1]
        return self._latest_record

    def get_history(self, conv_id: Optional[str] = None, limit: int = 5) -> List[TurnRecord]:
        """Return chronological turn history for conversational review."""
        if conv_id and conv_id in self._history:
            return self._history[conv_id][-limit:]
        if self._latest_record:
            return [self._latest_record]
        return []

    def get_full_readout_text(self, conv_id: Optional[str] = None) -> str:
        """Extract the full text of the latest turn for speech expansion."""
        rec = self.get_latest_turn(conv_id)
        if not rec or not rec.full_text:
            return ""
        return rec.full_text

    def clear(self, conv_id: Optional[str] = None):
        """Clear session memory for a conversation or entirely."""
        if conv_id:
            self._history.pop(conv_id, None)
            if self._latest_record and self._latest_record.conv_id == conv_id:
                self._latest_record = None
        else:
            self._history.clear()
            self._latest_record = None
