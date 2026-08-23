"""
Unit tests for voice catalog, agent persona resolution, and CLI voice management.
"""

from unittest.mock import patch, MagicMock
import pytest
from voicefi.config import VoiceFiConfig, AgentVoiceProfile
from voicefi.tts import (
    get_tts_engine,
    find_persona,
    get_curated_personas,
    list_all_available_voices,
    MacSayTTS,
    EdgeTTS,
)
from voicefi.cli import cmd_voice


def test_persona_lookup():
    """Test finding personas by name and ID."""
    p1 = find_persona("Christopher")
    assert p1 is not None
    assert p1.id == "en-US-ChristopherNeural"
    assert p1.gender == "Male"

    p2 = find_persona("en-US-AriaNeural")
    assert p2 is not None
    assert p2.name == "Aria"

    p_none = find_persona("NonExistentVoiceXYZ")
    assert p_none is None


def test_agent_voice_resolution():
    """Test resolve_voice logic in VoiceFiConfig."""
    cfg = VoiceFiConfig()
    cfg.tts.voice = "Samantha"
    cfg.tts.provider = "mac_say"

    # Default fallback
    prov, v, rate = cfg.resolve_voice(None)
    assert prov == "mac_say"
    assert v == "Samantha"

    # Unmapped agent falls back to default
    prov, v, rate = cfg.resolve_voice("unknown_agent")
    assert prov == "mac_say"
    assert v == "Samantha"

    # Mapped main agent
    cfg.agents["antigravity"] = AgentVoiceProfile(
        voice="en-US-ChristopherNeural",
        provider="edge_tts",
        rate=210,
    )
    prov, v, rate = cfg.resolve_voice("antigravity")
    assert prov == "edge_tts"
    assert v == "en-US-ChristopherNeural"
    assert rate == 210

    # Mapped subagent
    cfg.subagents["researcher"] = AgentVoiceProfile(
        voice="en-GB-SoniaNeural",
        provider="edge_tts",
    )
    prov, v, rate = cfg.resolve_voice("researcher")
    assert prov == "edge_tts"
    assert v == "en-GB-SoniaNeural"


def test_get_tts_engine_with_agent_name():
    """Test get_tts_engine instantiation with agent mapping."""
    cfg = VoiceFiConfig()
    cfg.subagents["debugger"] = AgentVoiceProfile(
        voice="en-US-AriaNeural",
        provider="edge_tts",
    )

    engine = get_tts_engine(cfg, agent_name="debugger")
    assert isinstance(engine, EdgeTTS)
    assert engine.voice == "en-US-AriaNeural"


def test_voice_catalog_listing():
    """Test listing curated personas and full catalog."""
    personas = get_curated_personas()
    assert len(personas) >= 6
    names = [p.name for p in personas]
    assert "Christopher" in names
    assert "Aria" in names
    assert "Sonia" in names

    all_voices = list_all_available_voices(provider="edge_tts")
    assert len(all_voices) >= 5


def test_cmd_voice_cli_get(capsys):
    """Test 'vg voice get' output."""
    args = MagicMock()
    args.voice_action = "get"
    args.config = None

    cmd_voice(args)
    captured = capsys.readouterr()
    assert "Active Voice Assignments" in captured.out


def test_unfocused_agent_voice_resolution():
    """Test resolve_voice when is_focused=False."""
    cfg = VoiceFiConfig()
    cfg.tts.provider = "mac_say"
    cfg.tts.voice = "Samantha"

    # Default contrast for Samantha on mac_say is Daniel
    prov, v, rate = cfg.resolve_voice("antigravity", is_focused=False)
    assert prov == "mac_say"
    assert v == "Daniel"

    # Edge TTS contrast
    cfg.tts.provider = "edge_tts"
    cfg.tts.voice = "en-US-ChristopherNeural"
    prov, v, rate = cfg.resolve_voice(None, is_focused=False)
    assert prov == "edge_tts"
    assert v == "en-US-AriaNeural"

    # Explicit unfocused voice configured
    cfg.antigravity.unfocused_agent_voice = "en-GB-SoniaNeural"
    prov, v, rate = cfg.resolve_voice("some_role", is_focused=False)
    assert v == "en-GB-SoniaNeural"


def test_rate_normalization():
    """Test rate normalization across EdgeTTS and MacSayTTS."""
    from voicefi.tts import normalize_edge_rate, normalize_mac_rate

    # 75% speed
    assert normalize_edge_rate("75%") == "-25%"
    assert normalize_edge_rate(75) == "-25%"
    assert normalize_edge_rate(-25) == "-25%"
    assert normalize_edge_rate(150) == "-25%"
    assert normalize_edge_rate("150wpm") == "-25%"

    assert normalize_mac_rate("75%") == 150
    assert normalize_mac_rate(75) == 150
    assert normalize_mac_rate(-25) == 150
    assert normalize_mac_rate(150) == 150
    assert normalize_mac_rate("150wpm") == 150

    # Normal speed (100%)
    assert normalize_edge_rate(0) == "+0%"
    assert normalize_edge_rate(200) == "+0%"
    assert normalize_edge_rate("100%") == "+0%"

    assert normalize_mac_rate(0) == 200
    assert normalize_mac_rate(200) == 200
    assert normalize_mac_rate("100%") == 200


def test_cmd_voice_cli_speed(capsys):
    """Test 'vg voice speed 75%' CLI invocation."""
    args = MagicMock()
    args.voice_action = "speed"
    args.value = "75%"
    args.agent = None
    args.config = None

    with patch("voicefi.cli.save_config") as mock_save:
        cmd_voice(args)
        captured = capsys.readouterr()
        assert "75% (150 WPM)" in captured.out
        mock_save.assert_called_once()

