"""
Analytical Queries, Aggregations, and Metric Calculators for VoiceFi.
Computes P50/P95 latencies, developer time-saved formulas, daily turn counts, and tool distributions.
"""

import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from voicefi.analytics.store import AnalyticsStore, get_analytics_store


def calculate_time_saved_breakdown(
    total_chars: int,
    total_spoken_seconds: float,
    total_turns: int,
    dispatches_count: int = 0,
    memos_count: int = 0,
    typing_wpm: int = 50,
) -> Dict[str, Any]:
    """
    Calculate granular time-saved line items across all productivity dimensions:
    1. Speech vs Typing/Reading Bandwidth
    2. Terminal Babysitting & Async Notification
    3. Cross-Agent Handoff Automation
    4. Voice Memo & Architecture Spec Synthesis
    """
    if total_chars <= 0 and total_turns <= 0 and dispatches_count <= 0 and memos_count <= 0:
        return {
            "total_hours": 0.0,
            "total_seconds": 0.0,
            "speech_vs_typing_seconds": 0.0,
            "speech_vs_typing_str": "+0 mins",
            "babysitting_seconds": 0.0,
            "babysitting_str": "+0 mins",
            "dispatch_seconds": 0.0,
            "dispatch_str": "+0 mins",
            "memo_seconds": 0.0,
            "memo_str": "+0 mins",
        }

    chars_per_sec = (typing_wpm * 5) / 60.0  # ~4.16 chars/sec @ 50 wpm
    typing_reading_seconds = total_chars / max(chars_per_sec, 1.0)
    speech_vs_typing_seconds = max(0.0, typing_reading_seconds - total_spoken_seconds)
    babysitting_seconds = total_turns * 15.0
    dispatch_seconds = dispatches_count * 45.0
    memo_seconds = memos_count * 900.0

    net_seconds = speech_vs_typing_seconds + babysitting_seconds + dispatch_seconds + memo_seconds

    def _fmt(sec: float) -> str:
        if sec >= 3600:
            return f"+{sec / 3600.0:.2f} hrs"
        elif sec >= 60:
            return f"+{sec / 60.0:.1f} mins"
        else:
            return f"+{int(round(sec))} secs"

    return {
        "total_hours": round(net_seconds / 3600.0, 2),
        "total_seconds": net_seconds,
        "speech_vs_typing_seconds": speech_vs_typing_seconds,
        "speech_vs_typing_str": _fmt(speech_vs_typing_seconds),
        "babysitting_seconds": babysitting_seconds,
        "babysitting_str": _fmt(babysitting_seconds),
        "dispatch_seconds": dispatch_seconds,
        "dispatch_str": _fmt(dispatch_seconds),
        "memo_seconds": memo_seconds,
        "memo_str": _fmt(memo_seconds),
    }


def calculate_time_saved_hours(
    total_chars: int,
    total_spoken_seconds: float,
    total_turns: int,
    dispatches_count: int = 0,
    memos_count: int = 0,
    typing_wpm: int = 50,
) -> float:
    """Calculate total estimated engineering hours saved."""
    breakdown = calculate_time_saved_breakdown(
        total_chars=total_chars,
        total_spoken_seconds=total_spoken_seconds,
        total_turns=total_turns,
        dispatches_count=dispatches_count,
        memos_count=memos_count,
        typing_wpm=typing_wpm,
    )
    return breakdown["total_hours"]



def get_analytics_summary(days: int = 7, store: Optional[AnalyticsStore] = None) -> Dict[str, Any]:
    """Retrieve high-level KPI scorecards for the given time window."""
    db = store or get_analytics_store()
    conn = db._get_connection()

    time_clause = f"-{max(1, int(days))} days" if days > 0 else "-100 years"

    with conn:
        # 1. Total Voice Interactions & Turns
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_events,
                SUM(CASE WHEN event_name IN ('voice_interaction', 'mcp_tool_call') THEN 1 ELSE 0 END) as total_turns,
                SUM(CASE WHEN event_name IN ('voice_interaction', 'mcp_tool_call') THEN duration_ms ELSE 0 END) as total_duration_ms,
                SUM(char_count) as total_chars,
                SUM(CASE WHEN is_barge_in = 1 THEN 1 ELSE 0 END) as barge_in_count,
                SUM(CASE WHEN event_name = 'mcp_tool_call' THEN 1 ELSE 0 END) as mcp_calls_count,
                SUM(CASE WHEN event_name = 'agent_dispatch' THEN 1 ELSE 0 END) as dispatches_count,
                SUM(CASE WHEN event_name IN ('memo', 'ambient', 'voice_memo') OR tool_name IN ('memo', 'ambient') THEN 1 ELSE 0 END) as memos_count
            FROM events
            WHERE timestamp >= datetime('now', ?)
            """,
            (time_clause,),
        ).fetchone()

        total_turns = int(row["total_turns"] or 0)
        total_duration_ms = int(row["total_duration_ms"] or 0)
        total_spoken_seconds = total_duration_ms / 1000.0
        total_chars = int(row["total_chars"] or 0)
        barge_in_count = int(row["barge_in_count"] or 0)
        mcp_calls_count = int(row["mcp_calls_count"] or 0)
        dispatches_count = int(row["dispatches_count"] or 0)
        memos_count = int(row["memos_count"] or 0)

        # 2. Top Agent
        agent_row = conn.execute(
            """
            SELECT caller_agent, COUNT(*) as count
            FROM events
            WHERE timestamp >= datetime('now', ?) AND caller_agent IS NOT NULL AND caller_agent != ''
            GROUP BY caller_agent
            ORDER BY count DESC
            LIMIT 1
            """,
            (time_clause,),
        ).fetchone()
        top_agent = agent_row["caller_agent"] if agent_row else "antigravity"

        # 3. Top Persona / Voice
        persona_row = conn.execute(
            """
            SELECT persona, COUNT(*) as count
            FROM events
            WHERE timestamp >= datetime('now', ?) AND persona IS NOT NULL AND persona != ''
            GROUP BY persona
            ORDER BY count DESC
            LIMIT 1
            """,
            (time_clause,),
        ).fetchone()
        top_persona = persona_row["persona"] if persona_row else "Ava (Premium)"

        # 4. Latency Percentiles (P50 & P95) for voice interactions
        latency_rows = conn.execute(
            """
            SELECT duration_ms
            FROM events
            WHERE timestamp >= datetime('now', ?) AND duration_ms > 0
            ORDER BY duration_ms ASC
            """,
            (time_clause,),
        ).fetchall()

        durations = [r["duration_ms"] for r in latency_rows]
        if durations:
            n = len(durations)
            p50_idx = min(int(n * 0.50), n - 1)
            p95_idx = min(int(n * 0.95), n - 1)
            p50_latency_ms = float(durations[p50_idx])
            p95_latency_ms = float(durations[p95_idx])
        else:
            p50_latency_ms = 0.0
            p95_latency_ms = 0.0

        # Calculate time saved across all dimensions
        time_saved_breakdown = calculate_time_saved_breakdown(
            total_chars=total_chars,
            total_spoken_seconds=total_spoken_seconds,
            total_turns=total_turns,
            dispatches_count=dispatches_count,
            memos_count=memos_count,
        )

        return {
            "days": days,
            "total_turns": total_turns,
            "total_spoken_minutes": round(total_spoken_seconds / 60.0, 1),
            "estimated_hours_saved": time_saved_breakdown["total_hours"],
            "time_saved_breakdown": time_saved_breakdown,
            "top_agent": top_agent,
            "top_persona": top_persona,
            "p50_latency_ms": p50_latency_ms,
            "p95_latency_ms": p95_latency_ms,
            "barge_in_count": barge_in_count,
            "mcp_calls_count": mcp_calls_count,
            "dispatches_count": dispatches_count,
            "memos_count": memos_count,
            "total_chars": total_chars,
        }




def get_daily_turn_volume(days: int = 7, store: Optional[AnalyticsStore] = None) -> List[Dict[str, Any]]:
    """Retrieve day-by-day turn counts for sparklines and volume charts."""
    db = store or get_analytics_store()
    conn = db._get_connection()

    time_clause = f"-{max(1, int(days))} days" if days > 0 else "-100 years"

    with conn:
        rows = conn.execute(
            """
            SELECT
                strftime('%Y-%m-%d', timestamp) as day_date,
                strftime('%w', timestamp) as day_of_week,
                COUNT(*) as turn_count,
                SUM(duration_ms) as total_duration_ms
            FROM events
            WHERE timestamp >= datetime('now', ?)
            GROUP BY day_date
            ORDER BY day_date ASC
            """,
            (time_clause,),
        ).fetchall()

        day_map = {
            "0": "Sun", "1": "Mon", "2": "Tue", "3": "Wed",
            "4": "Thu", "5": "Fri", "6": "Sat"
        }

        results = []
        for r in rows:
            results.append({
                "date": r["day_date"],
                "day_name": day_map.get(str(r["day_of_week"]), "Day"),
                "turns": int(r["turn_count"] or 0),
                "duration_ms": int(r["total_duration_ms"] or 0),
            })
        return results


def get_tool_usage_breakdown(days: int = 7, store: Optional[AnalyticsStore] = None) -> List[Dict[str, Any]]:
    """Retrieve call counts and percentages grouped by tool name."""
    db = store or get_analytics_store()
    conn = db._get_connection()

    time_clause = f"-{max(1, int(days))} days" if days > 0 else "-100 years"

    with conn:
        rows = conn.execute(
            """
            SELECT
                COALESCE(tool_name, event_name) as tool,
                COUNT(*) as count
            FROM events
            WHERE timestamp >= datetime('now', ?)
            GROUP BY tool
            ORDER BY count DESC
            """,
            (time_clause,),
        ).fetchall()

        total = sum(r["count"] for r in rows) or 1
        results = []
        for r in rows:
            c = int(r["count"])
            results.append({
                "tool": str(r["tool"]),
                "count": c,
                "percentage": round((c / total) * 100.0, 1),
            })
        return results


def get_agent_distribution(days: int = 7, store: Optional[AnalyticsStore] = None) -> List[Dict[str, Any]]:
    """Retrieve turns grouped by calling coding agent (e.g. antigravity, claude)."""
    db = store or get_analytics_store()
    conn = db._get_connection()

    time_clause = f"-{max(1, int(days))} days" if days > 0 else "-100 years"

    with conn:
        rows = conn.execute(
            """
            SELECT
                COALESCE(caller_agent, 'default') as agent,
                COUNT(*) as count
            FROM events
            WHERE timestamp >= datetime('now', ?) AND caller_agent IS NOT NULL
            GROUP BY agent
            ORDER BY count DESC
            """,
            (time_clause,),
        ).fetchall()

        total = sum(r["count"] for r in rows) or 1
        results = []
        for r in rows:
            c = int(r["count"])
            results.append({
                "agent": str(r["agent"]),
                "count": c,
                "percentage": round((c / total) * 100.0, 1),
            })
        return results
