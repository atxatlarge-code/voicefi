"""
Local-First SQLite Analytics Store for VoiceFi.
Provides atomic, WAL-mode local event logging and persistence at ~/.voicefi/analytics.db.
100% offline, zero external dependencies, complete developer data ownership.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


_LOCAL_STORE_INSTANCE: Optional["AnalyticsStore"] = None
_STORE_LOCK = threading.Lock()


def get_default_db_path() -> Path:
    """Return the standard path to the local analytics database."""
    base_dir = Path.home() / ".voicefi"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "analytics.db"


class AnalyticsStore:
    """Thread-safe SQLite repository for local VoiceFi usage analytics."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or get_default_db_path()
        self._local = threading.local()
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection configured with WAL mode."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,
                check_same_thread=False,
                isolation_level=None,  # Autocommit mode
            )
            conn.row_factory = sqlite3.Row
            # Enable Write-Ahead Logging for high-concurrency non-blocking writes
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                conn.execute("PRAGMA busy_timeout = 5000;")
            except Exception:
                pass
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self):
        """Initialize database tables and indexes if they do not exist."""
        conn = self._get_connection()
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_name TEXT NOT NULL,
                    timestamp DATETIME DEFAULT (datetime('now')),
                    duration_ms INTEGER DEFAULT 0,
                    success BOOLEAN DEFAULT 1,
                    caller_agent TEXT,
                    tool_name TEXT,
                    provider TEXT,
                    persona TEXT,
                    char_count INTEGER DEFAULT 0,
                    is_barge_in BOOLEAN DEFAULT 0,
                    error_type TEXT,
                    metadata_json TEXT
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_name_agent ON events(event_name, caller_agent);
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_rollups (
                    date TEXT PRIMARY KEY,
                    total_turns INTEGER DEFAULT 0,
                    total_spoken_seconds REAL DEFAULT 0.0,
                    total_chars INTEGER DEFAULT 0,
                    mcp_calls INTEGER DEFAULT 0,
                    barge_in_count INTEGER DEFAULT 0,
                    p50_latency_ms REAL DEFAULT 0.0,
                    p95_latency_ms REAL DEFAULT 0.0,
                    antigravity_turns INTEGER DEFAULT 0,
                    claude_turns INTEGER DEFAULT 0
                );
            """)

    def record_local_event(
        self,
        event_name: str,
        properties: Optional[Dict[str, Any]] = None,
        duration_ms: int = 0,
        success: bool = True,
        caller_agent: Optional[str] = None,
        tool_name: Optional[str] = None,
        provider: Optional[str] = None,
        persona: Optional[str] = None,
        char_count: int = 0,
        is_barge_in: bool = False,
        error_type: Optional[str] = None,
    ) -> Optional[int]:
        """Insert a sanitized event record into the local SQLite database."""
        props = dict(properties or {})
        # Extract properties if not passed directly
        dur = duration_ms or props.get("duration_ms", 0)
        succ = success if "success" not in props else bool(props.get("success", True))
        agent = caller_agent or props.get("agent") or props.get("caller_agent")
        tool = tool_name or props.get("tool_name") or props.get("tool")
        prov = provider or props.get("provider")
        pers = persona or props.get("persona") or props.get("voice")
        chars = char_count or props.get("char_count") or props.get("chars_count", 0)
        barge = is_barge_in or props.get("is_barge_in", False)
        err = error_type or props.get("error_type")

        # Exclude redundant keys from metadata_json to save space
        clean_props = {
            k: v for k, v in props.items()
            if k not in (
                "duration_ms", "success", "agent", "caller_agent",
                "tool_name", "tool", "provider", "persona", "voice",
                "char_count", "chars_count", "is_barge_in", "error_type",
                "prompt", "raw_text", "raw_speech", "text"
            )
        }

        try:
            meta_json = json.dumps(clean_props) if clean_props else None
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO events (
                        event_name, duration_ms, success, caller_agent,
                        tool_name, provider, persona, char_count,
                        is_barge_in, error_type, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(event_name),
                        max(0, int(dur)),
                        1 if succ else 0,
                        str(agent).strip()[:40] if agent else None,
                        str(tool).strip()[:50] if tool else None,
                        str(prov).strip()[:40] if prov else None,
                        str(pers).strip()[:50] if pers else None,
                        max(0, int(chars)),
                        1 if barge else 0,
                        str(err).strip()[:80] if err else None,
                        meta_json,
                    ),
                )
                return cursor.lastrowid
        except Exception:
            return None

    def prune_expired_events(self, days: int = 90) -> int:
        """Prune event records older than the specified retention threshold."""
        try:
            conn = self._get_connection()
            with conn:
                cursor = conn.execute(
                    "DELETE FROM events WHERE timestamp < datetime('now', ?);",
                    (f"-{max(1, int(days))} days",),
                )
                return cursor.rowcount
        except Exception:
            return 0

    def reset_database(self):
        """Completely wipe all records from the local analytics database."""
        conn = self._get_connection()
        with conn:
            conn.execute("DELETE FROM events;")
            conn.execute("DELETE FROM daily_rollups;")
            conn.execute("VACUUM;")


def get_analytics_store(db_path: Optional[Path] = None) -> AnalyticsStore:
    """Get or instantiate the global thread-safe AnalyticsStore singleton."""
    global _LOCAL_STORE_INSTANCE
    with _STORE_LOCK:
        if _LOCAL_STORE_INSTANCE is None or (db_path and _LOCAL_STORE_INSTANCE.db_path != db_path):
            _LOCAL_STORE_INSTANCE = AnalyticsStore(db_path=db_path)
        return _LOCAL_STORE_INSTANCE
