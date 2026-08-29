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

    p2 = find_persona("en-US-EmmaNeural")
    assert p2 is not None
    assert p2.name in ("Aria", "Emma")

    p3 = find_persona("Aria")
    assert p3 is not None
    assert p3.id == "en-US-EmmaNeural"

    p4 = find_persona("Emma")
    assert p4 is not None
    assert p4.id == "en-US-EmmaNeural"

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
        voice="en-US-EmmaNeural",
        provider="edge_tts",
    )

    engine = get_tts_engine(cfg, agent_name="debugger")
    assert isinstance(engine, EdgeTTS)
    assert engine.voice == "en-US-EmmaNeural"


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
    assert v == "en-US-EmmaNeural"

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


def test_cmd_voice_set_plays_acoustic_confirmation(capsys):
    """Test 'vifi voice set antigravity Viv' plays personalized acoustic confirmation phrase."""
    args = MagicMock()
    args.voice_action = "set"
    args.agent = "antigravity"
    args.voice = "Viv"
    args.provider = None
    args.rate = None
    args.text = None
    args.quiet = False
    args.silent = False
    args.config = None

    mock_tts = MagicMock()
    with patch("voicefi.cli.save_config"), \
         patch("voicefi.cli.get_tts_engine", return_value=mock_tts):
        cmd_voice(args)
        captured = capsys.readouterr()
        assert "Successfully assigned agent 'antigravity' to voice: 'en-US-AvaNeural'" in captured.out
        assert "Playing confirmation:" in captured.out
        mock_tts.speak.assert_called_once()
        spoken_phrase = mock_tts.speak.call_args[0][0]
        assert "Viv" in spoken_phrase
        assert "Antigravity" in spoken_phrase


def test_cmd_voice_set_quiet_flag(capsys):
    """Test 'vifi voice set antigravity Viv --quiet' skips audio playback."""
    args = MagicMock()
    args.voice_action = "set"
    args.agent = "antigravity"
    args.voice = "Viv"
    args.provider = None
    args.rate = None
    args.text = None
    args.quiet = True
    args.silent = False
    args.config = None

    mock_tts = MagicMock()
    with patch("voicefi.cli.save_config"), \
         patch("voicefi.cli.get_tts_engine", return_value=mock_tts):
        cmd_voice(args)
        captured = capsys.readouterr()
        assert "Successfully assigned agent 'antigravity' to voice: 'en-US-AvaNeural'" in captured.out
        mock_tts.speak.assert_not_called()


def test_cmd_voice_set_single_arg_viv(capsys):
    """Test 'vifi voice set viv' assigns global default and primary agent."""
    args = MagicMock()
    args.voice_action = "set"
    args.agent = "viv"
    args.voice = None
    args.provider = None
    args.rate = None
    args.text = None
    args.quiet = False
    args.silent = False
    args.config = None

    mock_tts = MagicMock()
    with patch("voicefi.cli.save_config") as mock_save, \
         patch("voicefi.cli.get_tts_engine", return_value=mock_tts):
        cmd_voice(args)
        captured = capsys.readouterr()
        assert "Successfully assigned global default & primary agent (antigravity) to voice: 'en-US-AvaNeural'" in captured.out
        mock_save.assert_called_once()
        mock_tts.speak.assert_called_once()
        spoken_phrase = mock_tts.speak.call_args[0][0]
        assert "default voice" in spoken_phrase


def test_cmd_voice_set_avaneural_alias(capsys):
    """Test 'vifi voice set avaneural' resolves to en-US-AvaNeural."""
    args = MagicMock()
    args.voice_action = "set"
    args.agent = "avaneural"
    args.voice = None
    args.provider = None
    args.rate = None
    args.text = None
    args.quiet = True
    args.silent = False
    args.config = None

    with patch("voicefi.cli.save_config"):
        cmd_voice(args)
        captured = capsys.readouterr()
        assert "Successfully assigned global default & primary agent (antigravity) to voice: 'en-US-AvaNeural'" in captured.out


def test_cmd_voice_set_reversed_args(capsys):
    """Test 'vifi voice set viv claude' handles reversed voice/agent ordering gracefully."""
    args = MagicMock()
    args.voice_action = "set"
    args.agent = "viv"
    args.voice = "claude"
    args.provider = None
    args.rate = None
    args.text = None
    args.quiet = True
    args.silent = False
    args.config = None

    with patch("voicefi.cli.save_config"):
        cmd_voice(args)
        captured = capsys.readouterr()
        assert "Successfully assigned agent 'claude' to voice: 'en-US-AvaNeural'" in captured.out


def test_find_persona_ava_viv_aliases():
    """Verify find_persona cleanly resolves Viv, Ava, and Ava Neural to EdgeTTS, while Ava (Premium) maps to mac_say."""
    from voicefi.tts.catalog import find_persona

    p_viv = find_persona("Viv")
    assert p_viv is not None
    assert p_viv.id == "en-US-AvaNeural"
    assert p_viv.provider == "edge_tts"

    p_ava = find_persona("Ava")
    assert p_ava is not None
    assert p_ava.id == "en-US-AvaNeural"
    assert p_ava.provider == "edge_tts"

    p_ava_neural = find_persona("Ava Neural")
    assert p_ava_neural is not None
    assert p_ava_neural.id == "en-US-AvaNeural"
    assert p_ava_neural.provider == "edge_tts"

    p_premium = find_persona("Ava (Premium)")
    assert p_premium is not None
    assert p_premium.id == "Ava (Premium)"
    assert p_premium.provider == "mac_say"




