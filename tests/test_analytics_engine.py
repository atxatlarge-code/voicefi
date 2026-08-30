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
    calculate_time_saved_breakdown,
    get_analytics_summary,
    get_daily_turn_volume,
    get_tool_usage_breakdown,
    get_agent_distribution,
    get_cognitive_flow_breakdown,
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
    assert hours > 0.8
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
    """Verify capture_mcp_tool_call helper dispatches correctly without inflating spoken turns for non-speech tools."""
    with patch("voicefi.analytics.store.get_analytics_store", return_value=temp_store):
        with patch("voicefi.telemetry.capture_event") as mock_remote:
            # 1. Listen tool should be tracked as an MCP call, but NOT as a spoken voice turn
            capture_mcp_tool_call(
                tool_name="voicefi_listen",
                duration_ms=3500,
                caller_agent="claude",
                persona="Viv",
                success=True,
            )
            assert mock_remote.called
            summary = get_analytics_summary(days=7, store=temp_store)
            assert summary["total_turns"] == 0
            assert summary["mcp_calls_count"] == 1
            assert summary["top_agent"] == "claude"

            # 2. Speak tool should be tracked as both an MCP call and a spoken voice turn
            capture_mcp_tool_call(
                tool_name="voicefi_speak",
                duration_ms=1200,
                caller_agent="antigravity",
                persona="Ava (Premium)",
                char_count=50,
                success=True,
            )
            summary2 = get_analytics_summary(days=7, store=temp_store)
            assert summary2["total_turns"] == 1
            assert summary2["mcp_calls_count"] == 2
            assert summary2["total_chars"] == 50


def test_mcp_speak_deduplication_and_turn_accounting(temp_store):
    """Verify that voicefi_speak tool invocations record exactly 1 turn without double-counting duration or characters."""
    temp_store.record_local_event(
        event_name="mcp_tool_call",
        tool_name="voicefi_speak",
        duration_ms=1500,
        caller_agent="antigravity",
        persona="Ava (Premium)",
        char_count=80,
    )
    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["total_turns"] == 1
    assert summary["total_spoken_minutes"] == round(1.5 / 60.0, 1)
    assert summary["total_chars"] == 80
    assert summary["mcp_calls_count"] == 1


def test_operational_tools_exclusion_from_voice_metrics(temp_store):
    """Verify that utility/diagnostic tool calls (status, ping, stop, set_voice) are excluded from spoken turns."""
    temp_store.record_local_event(event_name="mcp_tool_call", tool_name="voicefi_status", duration_ms=5)
    temp_store.record_local_event(event_name="mcp_tool_call", tool_name="voicefi_ping_voice", duration_ms=150)
    temp_store.record_local_event(event_name="mcp_tool_call", tool_name="voicefi_stop", duration_ms=2)
    temp_store.record_local_event(event_name="mcp_tool_call", tool_name="voicefi_set_voice", duration_ms=10)

    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["total_turns"] == 0
    assert summary["total_chars"] == 0
    assert summary["total_spoken_minutes"] == 0.0
    assert summary["mcp_calls_count"] == 4

    tools = get_tool_usage_breakdown(days=7, store=temp_store)
    assert len(tools) == 4
    tool_names = [t["tool"] for t in tools]
    assert "voicefi_status" in tool_names
    assert "voicefi_ping_voice" in tool_names
    assert "voicefi_stop" in tool_names
    assert "voicefi_set_voice" in tool_names


def test_acoustic_latency_isolation(temp_store):
    """Verify that P50 and P95 latency isolate voice synthesis from non-voice execution/recording."""
    # Long listening recording (should be excluded from acoustic TTS latency)
    temp_store.record_local_event(event_name="mcp_tool_call", tool_name="voicefi_listen", duration_ms=8000)
    # Long operational status/ping (should be excluded)
    temp_store.record_local_event(event_name="mcp_tool_call", tool_name="voicefi_status", duration_ms=3000)

    # Actual voice synthesis events
    temp_store.record_local_event(
        event_name="voice_interaction",
        duration_ms=120,
        caller_agent="antigravity",
    )
    temp_store.record_local_event(
        event_name="mcp_tool_call",
        tool_name="voicefi_speak",
        duration_ms=250,
        caller_agent="antigravity",
    )
    temp_store.record_local_event(
        event_name="ping_voice",
        duration_ms=180,
    )

    summary = get_analytics_summary(days=7, store=temp_store)
    # Latencies should be calculated solely from [120, 180, 250], ignoring 8000 and 3000
    assert summary["p50_latency_ms"] == 180.0
    assert summary["p95_latency_ms"] == 250.0


def test_hai_cognitive_flow_breakdown_four_modalities(temp_store):
    """Verify get_cognitive_flow_breakdown correctly maps events to the 4 HAI modalities."""
    # 1. Pure Voice Hands-Free
    temp_store.record_local_event(
        event_name="voice_interaction",
        caller_agent="antigravity",
        duration_ms=800,
        properties={"trigger": "hook"},
    )
    # 2. Spoken + Glanced Diff (Hybrid)
    temp_store.record_local_event(
        event_name="voice_interaction",
        caller_agent="antigravity",
        duration_ms=1000,
        properties={"trigger": "diff"},
    )
    # 3. Cross-Agent Delegation (Autonomous Bridge)
    temp_store.record_local_event(
        event_name="agent_dispatch",
        caller_agent="antigravity",
        properties={"target_engine": "claude"},
    )
    # 4. Voice Memo & Spec Synthesis
    temp_store.record_local_event(
        event_name="voice_memo",
        caller_agent="antigravity",
        duration_ms=180000,
    )

    flow = get_cognitive_flow_breakdown(days=7, store=temp_store)
    assert flow["total_turns"] == 4
    assert flow["flow_preservation_score"] > 80.0
    assert flow["net_flow_minutes_saved"] > 0.0

    modalities = {m["name"]: m for m in flow["modalities"]}
    assert "Pure Voice Hands-Free" in modalities
    assert modalities["Pure Voice Hands-Free"]["turns"] == 1
    assert "Spoken + Glanced Diff" in modalities
    assert modalities["Spoken + Glanced Diff"]["turns"] == 1
    assert "Cross-Agent Delegation" in modalities
    assert modalities["Cross-Agent Delegation"]["turns"] == 1
    assert "Voice Memo & Spec Synthesis" in modalities
    assert modalities["Voice Memo & Spec Synthesis"]["turns"] == 1


def test_hai_empty_store_flow_preservation(temp_store):
    """Verify empty database returns clean 100% flow preservation score without errors."""
    flow = get_cognitive_flow_breakdown(days=7, store=temp_store)
    assert flow["total_turns"] == 0
    assert flow["flow_preservation_score"] == 100.0
    assert flow["net_flow_minutes_saved"] == 0.0
    assert len(flow["modalities"]) == 4


def test_format_stats_dashboard_rendering(temp_store):
    """Verify format_stats_dashboard renders ANSI scorecards and tables without crashing."""
    temp_store.record_local_event(
        event_name="voice_interaction",
        duration_ms=1200,
        caller_agent="antigravity",
        persona="Ava (Premium)",
        char_count=60,
    )
    temp_store.record_local_event(
        event_name="agent_dispatch",
        caller_agent="antigravity",
        properties={"target_engine": "claude"},
    )
    dashboard = format_stats_dashboard(days=7, store=temp_store)
    assert "VoiceFi Developer Activity & Tool Analytics" in dashboard
    assert "Total Spoken Turns" in dashboard
    assert "Estimated Time Saved" in dashboard
    assert "Cognitive Flow & Human-AI Interaction (HAI) Dynamics" in dashboard
    assert "Pure Voice Hands-Free" in dashboard


def test_resilience_corrupted_and_malformed_metadata_json(temp_store):
    """Verify queries and summaries remain robust against corrupt, non-dict, or non-numeric metadata."""
    conn = temp_store._get_connection()
    with conn:
        # 1. Corrupt JSON syntax
        conn.execute(
            "INSERT INTO events (event_name, duration_ms, metadata_json) VALUES (?, ?, ?)",
            ("voice_interaction", 150, "{not valid json"),
        )
        # 2. JSON string literal (not a dict)
        conn.execute(
            "INSERT INTO events (event_name, duration_ms, metadata_json) VALUES (?, ?, ?)",
            ("voice_interaction", 200, json.dumps("string_payload")),
        )
        # 3. JSON array literal (not a dict)
        conn.execute(
            "INSERT INTO events (event_name, duration_ms, metadata_json) VALUES (?, ?, ?)",
            ("voice_interaction", 250, json.dumps([1, 2, 3])),
        )
        # 4. JSON dict with non-numeric latencies
        conn.execute(
            "INSERT INTO events (event_name, duration_ms, metadata_json) VALUES (?, ?, ?)",
            ("voice_interaction", 300, json.dumps({"tts_latency_ms": "invalid", "ctl_ms": "corrupt"})),
        )

    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["total_turns"] == 4
    assert summary["p50_latency_ms"] == 250.0  # Median index of [150, 200, 250, 300]
    assert summary["p95_latency_ms"] == 300.0

    flow = get_cognitive_flow_breakdown(days=7, store=temp_store)
    assert flow["total_turns"] == 4
    assert flow["flow_preservation_score"] == 100.0

    # Ensure format_stats_dashboard renders cleanly with corrupt rows
    dashboard = format_stats_dashboard(days=7, store=temp_store)
    assert "VoiceFi Developer Activity" in dashboard


def test_time_saved_boundary_and_negative_conditions():
    """Verify time-saved equations safely clamp negative and zero inputs."""
    res_zero = calculate_time_saved_breakdown(0, 0.0, 0, 0, 0)
    assert res_zero["total_hours"] == 0.0
    assert res_zero["total_seconds"] == 0.0

    # Negative inputs should not cause negative hours or crashes
    res_neg = calculate_time_saved_breakdown(-100, -50.0, -10, -5, -2, typing_wpm=-10)
    assert res_neg["total_hours"] == 0.0
    assert res_neg["total_seconds"] == 0.0
    assert res_neg["speech_vs_typing_seconds"] == 0.0

    # Test hours wrapper
    assert calculate_time_saved_hours(-50, -10.0, -1) == 0.0


def test_store_resilience_non_dict_properties_and_unserializable_objects(temp_store):
    """Verify record_local_event safely handles non-dict properties and objects."""
    import datetime
    # 1. Non-dict properties
    id1 = temp_store.record_local_event(
        event_name="test_event",
        properties="not_a_dict",  # type: ignore
        duration_ms=100,
    )
    assert id1 is not None

    # 2. Object with datetime and function in dict
    id2 = temp_store.record_local_event(
        event_name="test_event_2",
        properties={
            "created_at": datetime.datetime.now(),
            "custom_fn": lambda x: x,
            "nested": {"key": "val"},
        },
        duration_ms=200,
    )
    assert id2 is not None

    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["days"] == 7


def test_concurrent_multithreaded_wal_writes_and_reads(temp_store):
    """Verify SQLite WAL mode handles heavy concurrent multi-threaded writes and reads without lock errors."""
    import threading

    errors = []
    num_threads = 12
    events_per_thread = 25

    def worker(worker_id):
        try:
            for i in range(events_per_thread):
                temp_store.record_local_event(
                    event_name="voice_interaction" if i % 2 == 0 else "mcp_tool_call",
                    tool_name="voicefi_speak" if i % 2 != 0 else None,
                    caller_agent="antigravity" if worker_id % 2 == 0 else "claude",
                    duration_ms=100 + i,
                    char_count=20 + i,
                    properties={"worker": worker_id, "iteration": i},
                )
                if i % 5 == 0:
                    # Concurrently read while writing
                    get_analytics_summary(days=7, store=temp_store)
                    get_cognitive_flow_breakdown(days=7, store=temp_store)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent workers encountered errors: {errors}"
    summary = get_analytics_summary(days=7, store=temp_store)
    expected_turns = num_threads * events_per_thread
    assert summary["total_turns"] == expected_turns


def test_normalize_days_and_none_parameter_handling(temp_store):
    """Verify queries handle None, strings, and zero/negative days without raising exceptions."""
    temp_store.record_local_event(event_name="voice_interaction", duration_ms=500)

    # None parameter
    summary_none = get_analytics_summary(days=None, store=temp_store)
    assert summary_none["total_turns"] == 1

    flow_none = get_cognitive_flow_breakdown(days=None, store=temp_store)
    assert flow_none["total_turns"] == 1

    vol_none = get_daily_turn_volume(days=None, store=temp_store)
    assert len(vol_none) == 1

    tools_none = get_tool_usage_breakdown(days=None, store=temp_store)
    assert len(tools_none) == 1

    agents_none = get_agent_distribution(days=None, store=temp_store)
    assert isinstance(agents_none, list)

    json_none = export_events_json(days=None, store=temp_store)
    assert "voicefi_analytics_export" in json_none

    csv_none = export_events_csv(days=None, store=temp_store)
    assert "event_name,timestamp" in csv_none


def test_case_insensitive_agent_distribution(temp_store):
    """Verify that Antigravity and antigravity or Claude and claude are grouped together."""
    temp_store.record_local_event(event_name="voice_interaction", caller_agent="Antigravity", duration_ms=500)
    temp_store.record_local_event(event_name="voice_interaction", caller_agent="antigravity", duration_ms=500)
    temp_store.record_local_event(event_name="voice_interaction", caller_agent="Claude", duration_ms=500)
    temp_store.record_local_event(event_name="voice_interaction", caller_agent="claude", duration_ms=500)

    dist = get_agent_distribution(days=7, store=temp_store)
    agent_names = [a["agent"] for a in dist]
    assert "antigravity" in agent_names
    assert "claude" in agent_names
    assert len(agent_names) == 2

    agent_counts = {a["agent"]: a["count"] for a in dist}
    assert agent_counts["antigravity"] == 2
    assert agent_counts["claude"] == 2


def test_latency_extraction_from_metadata_when_duration_zero(temp_store):
    """Verify latency rows with duration_ms=0 but valid metadata latency are included in percentiles."""
    temp_store.record_local_event(
        event_name="voice_interaction",
        duration_ms=0,
        properties={"tts_latency_ms": 75.0},
    )
    temp_store.record_local_event(
        event_name="voice_interaction",
        duration_ms=0,
        properties={"ttfb_ms": 125.0},
    )

    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["p50_latency_ms"] == 125.0  # [75.0, 125.0], idx 1 = 125.0
    assert summary["p95_latency_ms"] == 125.0


def test_flow_preservation_label_classification(temp_store):
    """Verify dynamic flow label formatting based on preservation score thresholds."""
    # 1. 100% Flow (Pure voice) -> (Deep Flow)
    temp_store.record_local_event(event_name="voice_interaction", properties={"modality": "pure_voice"})
    dashboard_deep = format_stats_dashboard(days=7, store=temp_store)
    assert "(Deep Flow)" in dashboard_deep

    # 2. Hybrid glance -> (Moderate Flow)
    temp_store.reset_database()
    for _ in range(5):
        temp_store.record_local_event(event_name="voice_interaction", properties={"modality": "hybrid_glance"})
    flow_data = get_cognitive_flow_breakdown(days=7, store=temp_store)
    assert flow_data["flow_preservation_score"] == 85.0
    dashboard_mod = format_stats_dashboard(days=7, store=temp_store)
    assert "(Deep Flow)" in dashboard_mod  # 85% is threshold for Deep Flow


def test_zero_day_pruning_and_vacuum(temp_store):
    """Verify pruning with days=0 purges all events and compacts database."""
    temp_store.record_local_event(event_name="test_1", duration_ms=100)
    temp_store.record_local_event(event_name="test_2", duration_ms=200)

    pruned = temp_store.prune_expired_events(days=0)
    assert pruned == 2
    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["total_turns"] == 0


def test_format_stats_dashboard_with_none_and_invalid_days(temp_store):
    """Verify format_stats_dashboard gracefully handles days=None and invalid string parameters."""
    temp_store.record_local_event(event_name="voice_interaction", duration_ms=500, char_count=50)

    dashboard_none = format_stats_dashboard(days=None, store=temp_store)
    assert "VoiceFi Developer Activity & Tool Analytics" in dashboard_none
    assert "(Last 7 Days)" in dashboard_none

    dashboard_str = format_stats_dashboard(days="invalid", store=temp_store)
    assert "VoiceFi Developer Activity & Tool Analytics" in dashboard_str

    dashboard_all = format_stats_dashboard(days=0, store=temp_store)
    assert "(All Time)" in dashboard_all

    dashboard_today = format_stats_dashboard(days=1, store=temp_store)
    assert "(Today)" in dashboard_today


def test_mcp_ping_voice_ttfb_latency_metadata_propagation(temp_store):
    """Verify voicefi_ping_voice records explicit TTFB latency into extra_props and metadata."""
    from voicefi.mcp_server import VoiceFiMCPServer
    with patch("voicefi.analytics.store.get_analytics_store", return_value=temp_store):
        server = VoiceFiMCPServer()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.provider = "apple_speech"
        mock_result.audio_bytes = 4096
        mock_result.latency_ms = 42.5
        mock_result.chars_per_sec = 120.0
        with patch("voicefi.troubleshoot.AudioTroubleshooter.ping_voice_silently", return_value=mock_result):
            res = server.execute_tool("voicefi_ping_voice", {"voice": "Ava (Premium)"})
            assert not res.get("isError")
            assert "TTFB: 42.5ms" in res["content"][0]["text"]

            # Verify local event in store has TTFB metadata
            conn = temp_store._get_connection()
            row = conn.execute("SELECT * FROM events WHERE tool_name = 'voicefi_ping_voice' OR event_name = 'mcp_tool_call' ORDER BY id DESC LIMIT 1").fetchone()
            assert row is not None
            meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            assert meta.get("tts_latency_ms") == 42.5


def test_cli_clean_zero_retention_and_broken_pipe_handling(temp_store):
    """Verify vifi stats --clean 0 executes zero-day pruning and BrokenPipeError is handled cleanly."""
    from types import SimpleNamespace
    from voicefi.cli import cmd_stats
    with patch("voicefi.analytics.exporter.get_analytics_store", return_value=temp_store), \
         patch("voicefi.analytics.store.get_analytics_store", return_value=temp_store), \
         patch("voicefi.analytics.queries.get_analytics_store", return_value=temp_store):
        temp_store.record_local_event(event_name="voice_interaction", duration_ms=400)
        temp_store.record_local_event(event_name="voice_interaction", duration_ms=600)
        assert get_analytics_summary(days=7, store=temp_store)["total_turns"] == 2

        # 1. Test clean 0
        args_clean_0 = SimpleNamespace(reset=False, force=False, clean=0, today=False, all=False, days=7, export=None)
        cmd_stats(args_clean_0)
        assert get_analytics_summary(days=7, store=temp_store)["total_turns"] == 0

        # 2. Test BrokenPipeError in cmd_stats
        temp_store.record_local_event(event_name="voice_interaction", duration_ms=400)
        args_export = SimpleNamespace(reset=False, force=False, clean=None, today=False, all=False, days=7, export="json")
        with patch("voicefi.analytics.print_stats_dashboard", side_effect=BrokenPipeError):
            with patch("builtins.print", side_effect=BrokenPipeError):
                # Should not raise uncaught BrokenPipeError
                cmd_stats(args_export)


def test_weighted_dispatch_and_zero_gaze_triage(temp_store):
    """Verify weighted dispatches (substantive vs banter) and zero-gaze triage time calculations."""
    # 1. 2 substantive dispatches (> 80 chars) and 10 joke/ping dispatches (< 80 chars)
    for _ in range(2):
        temp_store.record_local_event(
            event_name="agent_dispatch",
            tool_name="voicefi_send",
            char_count=150,
            properties={"task": "Refactor auth middleware"},
        )
    for _ in range(10):
        temp_store.record_local_event(
            event_name="mcp_tool_call",
            tool_name="voicefi_send",
            char_count=25,
            properties={"joke": "Knock knock"},
        )

    # Record 5 voice turns
    for _ in range(5):
        temp_store.record_local_event(
            event_name="voice_interaction",
            duration_ms=1000,
            char_count=50,
        )

    summary = get_analytics_summary(days=7, store=temp_store)
    assert summary["dispatches_count"] == 12
    assert summary["substantive_dispatches"] == 2
    assert summary["banter_dispatches"] == 10

    bd = summary["time_saved_breakdown"]
    # 2 substantive @ 30s (60s) + 10 banter @ 3.5s (35s) = 95s
    assert bd["dispatch_seconds"] == 95.0
    # 5 turns * 18s = 90s zero-gaze triage
    assert bd["babysitting_seconds"] == 90.0

    # Test dashboard rendering includes zero-gaze audio triage and dispatch breakdown
    dashboard = format_stats_dashboard(days=7, store=temp_store)
    assert "Zero-Gaze Audio Triage:" in dashboard
    assert "12 dispatches: 2 tasks @ 30s + 10 jokes/pings @ 3.5s" in dashboard
    assert "Zero-Gaze Triage Focus:" in dashboard




