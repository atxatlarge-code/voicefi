"""
Data Exporter and Management Utilities for Local VoiceFi Analytics.
Allows developers to export their local event log to JSON/CSV or wipe/clean records.
"""

import csv
import io
import json
from typing import Any, Dict, List, Optional

from voicefi.analytics.store import AnalyticsStore, get_analytics_store
from voicefi.analytics.queries import _normalize_days


def export_events_json(days: int = 0, store: Optional[AnalyticsStore] = None) -> str:
    """Export all or recent local event records as a formatted JSON string."""
    db = store or get_analytics_store()
    conn = db._get_connection()

    d, time_clause = _normalize_days(days, default_days=0)

    with conn:
        rows = conn.execute(
            """
            SELECT
                id, event_name, timestamp, duration_ms, success,
                caller_agent, tool_name, provider, persona, char_count,
                is_barge_in, error_type, metadata_json
            FROM events
            WHERE timestamp >= datetime('now', ?)
            ORDER BY id ASC
            """,
            (time_clause,),
        ).fetchall()

        events_list = []
        for r in rows:
            meta = {}
            if r["metadata_json"]:
                try:
                    meta = json.loads(r["metadata_json"])
                except Exception:
                    pass
            events_list.append({
                "id": r["id"],
                "event_name": r["event_name"],
                "timestamp": r["timestamp"],
                "duration_ms": r["duration_ms"],
                "success": bool(r["success"]),
                "caller_agent": r["caller_agent"],
                "tool_name": r["tool_name"],
                "provider": r["provider"],
                "persona": r["persona"],
                "char_count": r["char_count"],
                "is_barge_in": bool(r["is_barge_in"]),
                "error_type": r["error_type"],
                "metadata": meta,
            })
        return json.dumps({"voicefi_analytics_export": events_list}, indent=2)


def export_events_csv(days: int = 0, store: Optional[AnalyticsStore] = None) -> str:
    """Export local event records as CSV format."""
    db = store or get_analytics_store()
    conn = db._get_connection()

    d, time_clause = _normalize_days(days, default_days=0)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "event_name", "timestamp", "duration_ms", "success",
        "caller_agent", "tool_name", "provider", "persona", "char_count",
        "is_barge_in", "error_type"
    ])

    with conn:
        rows = conn.execute(
            """
            SELECT
                id, event_name, timestamp, duration_ms, success,
                caller_agent, tool_name, provider, persona, char_count,
                is_barge_in, error_type
            FROM events
            WHERE timestamp >= datetime('now', ?)
            ORDER BY id ASC
            """,
            (time_clause,),
        ).fetchall()

        for r in rows:
            writer.writerow([
                r["id"], r["event_name"], r["timestamp"], r["duration_ms"],
                r["success"], r["caller_agent"] or "", r["tool_name"] or "",
                r["provider"] or "", r["persona"] or "", r["char_count"],
                r["is_barge_in"], r["error_type"] or ""
            ])

    return output.getvalue()


def clean_analytics_data(retention_days: int = 30, store: Optional[AnalyticsStore] = None) -> int:
    """Purge analytics events older than the specified retention days."""
    db = store or get_analytics_store()
    return db.prune_expired_events(days=retention_days)


def reset_analytics_data(store: Optional[AnalyticsStore] = None):
    """Completely wipe all records from the local analytics database."""
    db = store or get_analytics_store()
    db.reset_database()
