"""
Tests for VoiceFi Speed Talking Feature Suite.
Covers audio DSP rate conversions, pause compression, atempo filter chaining,
config serialization, resolve_voice scaling, CLI subcommands, MCP tools, and analytics.
"""

import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from voicefi.config import VoiceFiConfig, SpeedTalkingConfig, load_config, save_config
from voicefi.audio.speed_talk import (
    SPEED_PRESETS,
    resolve_speed_multiplier,
    multiplier_to_wpm,
    multiplier_to_edge_rate,
    calculate_time_saved,
    build_atempo_filter_chain,
    build_intelligibility_filter_chain,
)
from voicefi.analytics.queries import get_speed_talking_analytics
from voicefi.analytics.store import AnalyticsStore
from voicefi.mcp_server import VoiceFiMCPServer, MCP_TOOLS


def test_speed_presets_definition():
    """Verify all standard speed presets are defined with expected metadata."""
    expected_presets = ["normal", "breezy", "fast", "turbo", "sonic", "auctioneer", "warp", "ludicrous", "supersonic"]
    for p in expected_presets:
        assert p in SPEED_PRESETS, f"Missing preset: {p}"
        meta = SPEED_PRESETS[p]
        assert meta["multiplier"] >= 1.0
        assert meta["wpm"] >= 200
        assert "icon" in meta
        assert "description" in meta

    assert SPEED_PRESETS["normal"]["multiplier"] == 1.0
    assert SPEED_PRESETS["breezy"]["multiplier"] == 1.25
    assert SPEED_PRESETS["fast"]["multiplier"] == 1.5
    assert SPEED_PRESETS["turbo"]["multiplier"] == 1.75
    assert SPEED_PRESETS["sonic"]["multiplier"] == 2.0
    assert SPEED_PRESETS["warp"]["multiplier"] == 2.5
    assert SPEED_PRESETS["supersonic"]["multiplier"] == 3.0


def test_resolve_speed_multiplier():
    """Test resolution of various speed formats into float multipliers."""
    # Presets
    assert resolve_speed_multiplier("normal") == 1.0
    assert resolve_speed_multiplier("breezy") == 1.25
    assert resolve_speed_multiplier("fast") == 1.5
    assert resolve_speed_multiplier("turbo") == 1.75
    assert resolve_speed_multiplier("sonic") == 2.0
    assert resolve_speed_multiplier("warp") == 2.5
    assert resolve_speed_multiplier("supersonic") == 3.0

    # Multiplier strings
    assert resolve_speed_multiplier("1.5x") == 1.5
    assert resolve_speed_multiplier("1.75X") == 1.75
    assert resolve_speed_multiplier("2x") == 2.0
    assert resolve_speed_multiplier("2.5") == 2.5

    # WPM values
    assert resolve_speed_multiplier("300wpm") == 1.5
    assert resolve_speed_multiplier("400wpm") == 2.0
    assert resolve_speed_multiplier("200") == 1.0
    assert resolve_speed_multiplier(300) == 1.5
    assert resolve_speed_multiplier(400) == 2.0

    # Percentage strings
    assert resolve_speed_multiplier("150%") == 1.5
    assert resolve_speed_multiplier("+50%") == 1.5
    assert resolve_speed_multiplier("+100%") == 2.0
    assert resolve_speed_multiplier("-25%") == 0.75

    # Bounds
    assert resolve_speed_multiplier(10.0) == 4.0  # Max clamp
    assert resolve_speed_multiplier(0.1) == 0.5   # Min clamp
    assert resolve_speed_multiplier(None) == 1.0
    assert resolve_speed_multiplier("") == 1.0
    assert resolve_speed_multiplier("invalid") == 1.0


def test_multiplier_to_wpm_and_edge_rate():
    """Test conversion helpers between multipliers, WPM, and EdgeTTS rate strings."""
    assert multiplier_to_wpm(1.0) == 200
    assert multiplier_to_wpm(1.25) == 250
    assert multiplier_to_wpm(1.5) == 300
    assert multiplier_to_wpm(1.75) == 350
    assert multiplier_to_wpm(2.0) == 400
    assert multiplier_to_wpm(2.5) == 500
    assert multiplier_to_wpm(3.0) == 600

    assert multiplier_to_edge_rate(1.0) == "+0%"
    assert multiplier_to_edge_rate(1.25) == "+25%"
    assert multiplier_to_edge_rate(1.5) == "+50%"
    assert multiplier_to_edge_rate(1.75) == "+75%"
    assert multiplier_to_edge_rate(2.0) == "+100%"
    assert multiplier_to_edge_rate(2.5) == "+150%"
    assert multiplier_to_edge_rate(3.0) == "+200%"


def test_calculate_time_saved():
    """Test mathematical calculation of listening time saved."""
    res_1_5 = calculate_time_saved(char_count=500, multiplier=1.5, baseline_wpm=200)
    assert res_1_5["char_count"] == 500
    assert res_1_5["multiplier"] == 1.5
    assert res_1_5["baseline_seconds"] == 30.0
    assert res_1_5["accelerated_seconds"] == 20.0
    assert res_1_5["seconds_saved"] == 10.0
    assert res_1_5["time_saved_pct"] == 33.3

    res_2_0 = calculate_time_saved(char_count=500, multiplier=2.0, baseline_wpm=200)
    assert res_2_0["baseline_seconds"] == 30.0
    assert res_2_0["accelerated_seconds"] == 15.0
    assert res_2_0["seconds_saved"] == 15.0
    assert res_2_0["time_saved_pct"] == 50.0


def test_build_atempo_filter_chain():
    """Test FFmpeg atempo filter chain construction for arbitrary speeds."""
    # 1.5x fits within single filter
    f_1_5 = build_atempo_filter_chain(1.5)
    assert f_1_5 == "atempo=1.5000"

    # 2.0x fits within single filter
    f_2_0 = build_atempo_filter_chain(2.0)
    assert f_2_0 == "atempo=2.0000"

    # 3.0x requires chaining
    f_3_0 = build_atempo_filter_chain(3.0)
    assert f_3_0 == "atempo=2.0,atempo=1.5000"

    # 4.0x requires chaining
    f_4_0 = build_atempo_filter_chain(4.0)
    assert f_4_0 == "atempo=2.0,atempo=2.0000"


def test_intelligibility_filter_chain():
    """Test DSP presence EQ, pause compression, and limiter inclusion."""
    chain = build_intelligibility_filter_chain(
        speed_multiplier=1.75,
        enhance_clarity=True,
        compress_pauses=True,
        max_pause_ms=150,
    )
    assert "silenceremove=" in chain
    assert "atempo=1.7500" in chain
    assert "equalizer=f=3500" in chain
    assert "highshelf=f=8000" in chain
    assert "acompressor=" in chain
    assert "alimiter=" in chain


def test_config_speed_talking_model(tmp_path):
    """Test SpeedTalkingConfig Pydantic model and saving/loading."""
    cfg = VoiceFiConfig()
    assert hasattr(cfg, "speed_talking")
    assert cfg.speed_talking.enabled is False
    assert cfg.speed_talking.preset == "fast"
    assert cfg.speed_talking.multiplier == 1.5
    assert cfg.speed_talking.compress_pauses is True

    # Modify and save
    cfg.speed_talking.enabled = True
    cfg.speed_talking.preset = "turbo"
    cfg.speed_talking.multiplier = 1.75
    test_yaml = tmp_path / "config.yaml"
    save_config(cfg, target_path=test_yaml)

    loaded = load_config(str(test_yaml))
    assert loaded.speed_talking.enabled is True
    assert loaded.speed_talking.preset == "turbo"
    assert loaded.speed_talking.multiplier == 1.75


def test_resolve_voice_with_speed_talking():
    """Test that resolve_voice applies the speed multiplier when Speed Talking is enabled."""
    cfg = VoiceFiConfig()
    cfg.tts.rate = 200
    cfg.speed_talking.enabled = False
    cfg.speed_talking.multiplier = 1.5

    # When disabled: rate is normal baseline
    _, _, rate_disabled = cfg.resolve_voice(agent_name="antigravity")
    assert rate_disabled == 200

    # When enabled: rate is scaled by multiplier
    cfg.speed_talking.enabled = True
    _, _, rate_enabled = cfg.resolve_voice(agent_name="antigravity")
    assert rate_enabled == 300


def test_mcp_speed_talk_tool():
    """Test MCP voicefi_speed_talk tool execution."""
    server = VoiceFiMCPServer()

    # 1. Status query
    res_status = server.execute_tool("voicefi_speed_talk", {"action": "status"})
    assert res_status["isError"] is False or "isError" not in res_status
    assert "Speed Talking Status" in res_status["content"][0]["text"]

    # 2. List presets
    res_list = server.execute_tool("voicefi_speed_talk", {"action": "list_presets"})
    assert "Curated Speed Talking Presets" in res_list["content"][0]["text"]
    assert "turbo" in res_list["content"][0]["text"]

    # 3. Enable speed talking
    res_enable = server.execute_tool("voicefi_speed_talk", {"action": "enable", "preset": "turbo"})
    assert "Speed Talking enabled" in res_enable["content"][0]["text"]
    assert "1.75x" in res_enable["content"][0]["text"]

    # 4. Set exact multiplier
    res_set = server.execute_tool("voicefi_speed_talk", {"action": "set", "preset": "2.0x"})
    assert "Speed Talking preset set" in res_set["content"][0]["text"]
    assert "2.0x" in res_set["content"][0]["text"]

    # 5. Disable speed talking
    res_disable = server.execute_tool("voicefi_speed_talk", {"action": "disable"})
    assert "Speed Talking disabled" in res_disable["content"][0]["text"]


def test_mcp_tools_registration():
    """Verify voicefi_speed_talk and speed fields are registered in MCP_TOOLS."""
    tool_names = [t["name"] for t in MCP_TOOLS]
    assert "voicefi_speed_talk" in tool_names

    speak_tool = next(t for t in MCP_TOOLS if t["name"] == "voicefi_speak")
    props = speak_tool["inputSchema"]["properties"]
    assert "speed" in props
    assert "speed_talk" in props


def test_analytics_speed_talking(tmp_path):
    """Test speed talking analytics query on local store."""
    db_path = tmp_path / "analytics.db"
    store = AnalyticsStore(db_path=db_path)

    # Record turn events with speed multipliers
    store.record_local_event(
        event_name="turn_spoken",
        properties={"char_count": 500, "speed_multiplier": 1.5},
        duration_ms=2000,
        char_count=500,
    )
    store.record_local_event(
        event_name="turn_spoken",
        properties={"char_count": 500, "speed_multiplier": 2.0},
        duration_ms=1500,
        char_count=500,
    )

    analytics = get_speed_talking_analytics(days=7, store=store)
    assert analytics["total_speed_turns"] == 2
    assert analytics["avg_multiplier"] == 1.75
    assert analytics["total_seconds_saved"] > 0
