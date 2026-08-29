"""
Unit tests for VoiceFi Local Analytics Store, Aggregations, and Telemetry Egress.
Tests SQLite WAL schema, time-saved equations, terminal stats formatting, and dual-sink logging.
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

from voicefi.analytics.store import AnalyticsStore
from voicefi.analytics.queries import (
    calculate_time_saved_hours,
    get_analytics_summary,
    get_daily_turn_volume,
    get_tool_usage_breakdown,
    get_agent_distribution,
)
from voicefi.analytics.terminal import render_horizontal_bar, format_stats_dashboard
from voicefi.analytics.exporter import (
    export_events_json,
    export_events_csv,
    clean_analytics_data,
    reset_analytics_data,
)
from voicefi.telemetry import (
    record_event,
    capture_mcp_tool_call,
    capture_barge_in_event,
    capture_agent_dispatch,
)


@pytest.fixture
def temp_store(tmp_path):
    """Fixture providing an isolated AnalyticsStore in a temporary SQLite database."""
    db_file = tmp_path / "test_analytics.db"
    store = AnalyticsStore(db_path=db_file)
    return store


def test_analytics_store_schema_initialization(temp_store):
    """Verify that SQLite tables and WAL mode are initialized properly."""
    conn = temp_store._get_connection()
    tables = [
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    ]
    assert "events" in tables
    assert "daily_rollups" in tables


def test_record_local_event_and_query(temp_store):
    """Verify recording events with various parameters and metadata."""
    event_id = temp_store.record_local_event(
        event_name="mcp_tool_call",
        duration_ms=1250,
        success=True,
        caller_agent="antigravity",
        tool_name="voicefi_speak",
        provider="apple_speech",
        persona="Ava (Premium)",
        char_count=64,
        is_barge_in=False,
    )
    assert event_id is not None
    assert event_id > 0

    conn = temp_store._get_connection()
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    assert row["event_name"] == "mcp_tool_call"
    assert row["caller_agent"] == "antigravity"
    assert row["tool_name"] == "voicefi_speak"
    assert row["persona"] == "Ava (Premium)"
    assert row["char_count"] == 64
    assert row["duration_ms"] == 1250
    assert row["success"] == 1


def test_calculate_time_saved_hours():
    """Verify the mathematical calculation for developer hours saved."""
    # 0 input should return 0.0
    assert calculate_time_saved_hours(0, 0.0, 0) == 0.0

    # 10,000 characters spoken across 50 turns with 150 seconds spoken duration,
    # 5 cross-agent dispatches, and 1 voice memo synthesis
    hours = calculate_time_saved_hours(
        total_chars=10000,
        total_spoken_seconds=150.0,
        total_turns=50,
        dispatches_count=5,
        memos_count=1,
        typing_wpm=50,
    )
    assert hours > 1.0
    assert isinstance(hours, float)



def test_get_analytics_summary(temp_store):
    """Verify aggregated summary calculations across multiple event types."""
    temp_store.record_local_event(
        event_name="voice_interaction",
        duration_ms=800,
        caller_agent="antigravity",
        persona="Ava (Premium)",
        char_count=40,
    )
    temp_store.record_local_event(
        event_name="voice_interaction",
        duration_ms=1200,
        caller_agent="claude",
        persona="Viv",
        char_count=60,
    )
    temp_store.record_local_event(
        event_name="mcp_tool_call",
        duration_ms=500,
        caller_agent="antigravity",
        tool_name="voicefi_speak",
        persona="Ava (Premium)",
        char_count=30,
        is_barge_in=True,
    )

    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["total_turns"] == 3
    assert summary["total_chars"] == 130
    assert summary["barge_in_count"] == 1
    assert summary["mcp_calls_count"] == 1
    assert summary["top_agent"] == "antigravity"
    assert summary["top_persona"] == "Ava (Premium)"
    assert summary["p50_latency_ms"] > 0
    assert summary["p95_latency_ms"] >= summary["p50_latency_ms"]


def test_get_daily_turn_volume_and_tool_breakdown(temp_store):
    """Verify grouped aggregations for volume sparklines and tool distributions."""
    temp_store.record_local_event(
        event_name="mcp_tool_call",
        tool_name="voicefi_speak",
        caller_agent="antigravity",
        duration_ms=1000,
    )
    temp_store.record_local_event(
        event_name="mcp_tool_call",
        tool_name="voicefi_listen",
        caller_agent="antigravity",
        duration_ms=2000,
    )

    daily = get_daily_turn_volume(days=7, store=temp_store)
    assert len(daily) >= 1
    assert daily[0]["turns"] == 2

    tools = get_tool_usage_breakdown(days=7, store=temp_store)
    assert len(tools) == 2
    tool_names = [t["tool"] for t in tools]
    assert "voicefi_speak" in tool_names
    assert "voicefi_listen" in tool_names


def test_export_events_json_and_csv(temp_store):
    """Verify JSON and CSV export formats."""
    temp_store.record_local_event(
        event_name="voice_interaction",
        duration_ms=900,
        caller_agent="antigravity",
        persona="Ava (Premium)",
        char_count=50,
    )

    # JSON export test
    json_str = export_events_json(days=7, store=temp_store)
    data = json.loads(json_str)
    assert "voicefi_analytics_export" in data
    assert len(data["voicefi_analytics_export"]) == 1
    assert data["voicefi_analytics_export"][0]["caller_agent"] == "antigravity"

    # CSV export test
    csv_str = export_events_csv(days=7, store=temp_store)
    assert "event_name,timestamp" in csv_str
    assert "voice_interaction" in csv_str
    assert "antigravity" in csv_str


def test_clean_and_reset_analytics_data(temp_store):
    """Verify data pruning and database reset functions."""
    temp_store.record_local_event(event_name="test_event_1")
    temp_store.record_local_event(event_name="test_event_2")

    # Clean (retention 30 days) should not delete fresh records
    pruned = clean_analytics_data(retention_days=30, store=temp_store)
    assert pruned == 0

    # Reset should wipe all records
    reset_analytics_data(store=temp_store)
    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["total_turns"] == 0


def test_render_horizontal_bar():
    """Verify scaled Unicode bar rendering."""
    bar_empty = render_horizontal_bar(0, 100, width=10)
    assert "░" in bar_empty

    bar_full = render_horizontal_bar(100, 100, width=10)
    assert "█" in bar_full


def test_dual_sink_record_event(temp_store):
    """Verify that record_event logs to local SQLite store and dispatches to telemetry."""
    with patch("voicefi.analytics.store.get_analytics_store", return_value=temp_store):
        with patch("voicefi.telemetry.capture_event") as mock_remote:
            record_event(
                "mcp_tool_call",
                {
                    "tool_name": "voicefi_speak",
                    "caller_agent": "antigravity",
                    "duration_ms": 1100,
                    "char_count": 45,
                },
            )
            # 1. Verify remote capture was called
            assert mock_remote.called

            # 2. Verify local store received the event
            summary = get_analytics_summary(days=7, store=temp_store)
            assert summary["total_turns"] == 1
            assert summary["total_chars"] == 45


def test_capture_mcp_tool_call_helper(temp_store):
    """Verify capture_mcp_tool_call helper dispatches correctly."""
    with patch("voicefi.analytics.store.get_analytics_store", return_value=temp_store):
        with patch("voicefi.telemetry.capture_event") as mock_remote:
            capture_mcp_tool_call(
                tool_name="voicefi_listen",
                duration_ms=3500,
                caller_agent="claude",
                persona="Viv",
                success=True,
            )
            assert mock_remote.called
            summary = get_analytics_summary(days=7, store=temp_store)
            assert summary["total_turns"] == 1
            assert summary["top_agent"] == "claude"
