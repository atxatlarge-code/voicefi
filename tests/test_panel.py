"""
Unit tests for Voice Control Panel, Voice Command Parser, and REST API.
"""

import json
import urllib.request
from unittest.mock import patch, MagicMock
import pytest

from voicefi.config import VoiceFiConfig, AgentVoiceProfile
from voicefi.ui.panel import (
    parse_voice_command,
    get_current_system_state,
    start_panel_server,
)
from voicefi.cli import cmd_panel, cmd_voice


def test_parse_voice_command_audition():
    """Test voice command parsing for audition intents."""
    cfg = VoiceFiConfig()

    res1 = parse_voice_command("Audition Christopher", cfg)
    assert res1["action"] == "audition"
    assert res1["voice"] == "Christopher"
    assert res1["voice_id"] == "en-US-ChristopherNeural"

    res2 = parse_voice_command("Can you test Aria for me", cfg)
    assert res2["action"] == "audition"
    assert res2["voice"] == "Aria"
    assert res2["voice_id"] == "en-US-AriaNeural"

    res3 = parse_voice_command("Let me hear Sonia", cfg)
    assert res3["action"] == "audition"
    assert res3["voice"] == "Sonia"


def test_parse_voice_command_assignment():
    """Test voice command parsing for agent and subagent assignment."""
    cfg = VoiceFiConfig()

    # Antigravity (main agent)
    res1 = parse_voice_command("Set voice to Christopher", cfg)
    assert res1["action"] == "assign"
    assert res1["target"] == "antigravity"
    assert res1["voice"] == "Christopher"
    assert res1["speech_feedback"] == "This is an automated voice test."
    assert cfg.agents["antigravity"].voice == "en-US-ChristopherNeural"

    # Researcher subagent
    res2 = parse_voice_command("Assign Sonia to researcher", cfg)
    assert res2["action"] == "assign"
    assert res2["target"] == "researcher"
    assert res2["voice"] == "Sonia"
    assert cfg.subagents["researcher"].voice == "en-GB-SoniaNeural"

    # Debugger subagent
    res3 = parse_voice_command("Switch debugger to Aria", cfg)
    assert res3["action"] == "assign"
    assert res3["target"] == "debugger"
    assert res3["voice"] == "Aria"
    assert cfg.subagents["debugger"].voice == "en-US-AriaNeural"


def test_parse_voice_command_speed_and_stop():
    """Test rate adjustments and stop commands."""
    cfg = VoiceFiConfig()
    cfg.tts.rate = 200

    # Speed up
    res_faster = parse_voice_command("Faster please", cfg)
    assert res_faster["action"] == "rate"
    assert res_faster["rate"] == 225
    assert cfg.tts.rate == 225

    # Slow down
    res_slower = parse_voice_command("Talk slower", cfg)
    assert res_slower["action"] == "rate"
    assert res_slower["rate"] == 200
    assert cfg.tts.rate == 200

    # 75% speed
    res_75 = parse_voice_command("Make the voice 75% speed", cfg)
    assert res_75["action"] == "rate"
    assert res_75["rate"] == 150
    assert cfg.tts.rate == 150

    # Explicit WPM rate
    res_wpm = parse_voice_command("Set rate to 180", cfg)
    assert res_wpm["action"] == "rate"
    assert res_wpm["rate"] == 180
    assert cfg.tts.rate == 180

    # Stop
    with patch("voicefi.ui.panel.stop_all_speech") as mock_stop:
        res_stop = parse_voice_command("Stop talking", cfg)
        assert res_stop["action"] == "stop"
        mock_stop.assert_called_once()


def test_parse_voice_command_showcase():
    """Test team showcase voice command."""
    cfg = VoiceFiConfig()
    res = parse_voice_command("Play team showcase", cfg)
    assert res["action"] == "showcase"


def test_get_current_system_state():
    """Test compiling system state for frontend UI."""
    cfg = VoiceFiConfig()
    cfg.agents["antigravity"] = AgentVoiceProfile(
        voice="en-US-ChristopherNeural",
        provider="edge_tts",
    )
    cfg.subagents["researcher"] = AgentVoiceProfile(
        voice="en-GB-SoniaNeural",
        provider="edge_tts",
    )

    state = get_current_system_state(cfg)
    assert state["active_antigravity"]["name"] == "Christopher"
    assert state["subagents"]["researcher"]["name"] == "Sonia"
    assert len(state["curated_personas"]) >= 6
    assert len(state["all_voices"]) >= 5


def test_panel_rest_api():
    """Test running local HTTP server and querying endpoints."""
    cfg = VoiceFiConfig()
    srv, port = start_panel_server(port=9876, config=cfg)
    base_url = f"http://127.0.0.1:{port}"

    # 1. GET /
    with urllib.request.urlopen(f"{base_url}/") as response:
        assert response.status == 200
        html = response.read().decode("utf-8")
        assert "VoiceFi Control Panel" in html
        assert "Curated Personas" in html

    # 2. GET /api/state
    with urllib.request.urlopen(f"{base_url}/api/state") as response:
        assert response.status == 200
        data = json.loads(response.read().decode("utf-8"))
        assert "curated_personas" in data
        assert "active_antigravity" in data

    # 3. POST /api/assign
    req_assign = urllib.request.Request(
        f"{base_url}/api/assign",
        data=json.dumps({"target": "antigravity", "voice": "en-US-AriaNeural", "provider": "edge_tts"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req_assign) as response:
        assert response.status == 200
        res = json.loads(response.read().decode("utf-8"))
        assert res["status"] == "success"
        assert res["voice"] == "en-US-AriaNeural"

    # 4. POST /api/voice_command
    req_cmd = urllib.request.Request(
        f"{base_url}/api/voice_command",
        data=json.dumps({"command": "Switch to Christopher"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req_cmd) as response:
        assert response.status == 200
        res = json.loads(response.read().decode("utf-8"))
        assert res["action"] == "assign"
        assert res["voice"] == "Christopher"

    # 5. GET /api/prompts
    with urllib.request.urlopen(f"{base_url}/api/prompts") as response:
        assert response.status == 200
        prompts = json.loads(response.read().decode("utf-8"))
        assert len(prompts) >= 4

    # 6. GET /api/clones
    with urllib.request.urlopen(f"{base_url}/api/clones") as response:
        assert response.status == 200
        clones = json.loads(response.read().decode("utf-8"))
        assert isinstance(clones, list)

    # Test GET /claude
    req_claude_html = urllib.request.Request(f"http://127.0.0.1:{port}/claude")
    with urllib.request.urlopen(req_claude_html) as response:
        assert response.status == 200
        html_content = response.read().decode("utf-8")
        assert "Claude Voice Contenders" in html_content
        assert "Oliver (Premium)" in html_content

    # Test GET /api/claude/contenders
    req_claude_api = urllib.request.Request(f"http://127.0.0.1:{port}/api/claude/contenders")
    with urllib.request.urlopen(req_claude_api) as response:
        assert response.status == 200
        cdata = json.loads(response.read().decode("utf-8"))
        assert cdata["status"] == "success"
        assert len(cdata["contenders"]) > 0
        names = [c["name"] for c in cdata["contenders"]]
        assert "Ryan" in names
        assert "Thomas" in names

    # Test POST /api/claude/assign
    assign_payload = json.dumps({"voice": "en-GB-RyanNeural", "provider": "edge_tts"}).encode("utf-8")
    req_assign = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/claude/assign",
        data=assign_payload,
        headers={"Content-Type": "application/json"},
    )
    with patch("voicefi.ui.panel.save_config"):
        with urllib.request.urlopen(req_assign) as response:
            assert response.status == 200
            ares = json.loads(response.read().decode("utf-8"))
            assert ares["status"] == "success"
            assert ares["target"] == "claude"
            assert ares["voice"] == "en-GB-RyanNeural"
            assert cfg.agents["claude"].voice == "en-GB-RyanNeural"



def test_cli_panel_argument():
    """Test CLI argument parsing and execution for panel."""
    with patch("voicefi.ui.panel.open_control_panel") as mock_open:
        mock_open.return_value = "http://localhost:5141"
        with patch("time.sleep", side_effect=KeyboardInterrupt):
            args = MagicMock()
            args.port = 5141
            args.no_browser = False
            args.config = None
            cmd_panel(args)
            assert mock_open.call_count == 1
            call_kwargs = mock_open.call_args.kwargs
            assert call_kwargs["port"] == 5141
            assert call_kwargs["open_browser"] is True


def test_cli_voice_command():
    """Test 'vg voice command' CLI invocation."""
    args = MagicMock()
    args.voice_action = "command"
    args.command_text = ["audition", "Christopher"]
    args.config = None

    with patch("voicefi.cli.get_tts_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        cmd_voice(args)
        mock_engine.speak.assert_called_once()


def test_cli_voice_command_assignment_feedback():
    """Test 'vg voice command' assignment uses assigned voice for feedback."""
    args = MagicMock()
    args.voice_action = "command"
    args.command_text = ["set", "voice", "to", "Christopher"]
    args.config = None

    with patch("voicefi.cli.get_tts_engine") as mock_get_engine, \
         patch("voicefi.ui.panel.save_config"):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        cmd_voice(args)
        mock_engine.speak.assert_called_once_with("This is an automated voice test.", block=True)
        # Verify get_tts_engine was called with the target agent and voice override
        assert mock_get_engine.call_args.kwargs.get("agent_name") == "antigravity"
        assert mock_get_engine.call_args.kwargs.get("voice_override") == "en-US-ChristopherNeural"


def test_cli_speak_agent_resolution():
    """Test 'vg speak' command resolves agent voice properly."""
    from voicefi.cli import cmd_speak
    from voicefi.config import VoiceFiConfig, AgentVoiceProfile

    args = MagicMock()
    args.text = ["Hello", "world"]
    args.agent = None
    args.voice = None
    args.provider = None
    args.config = None

    mock_cfg = VoiceFiConfig()
    mock_cfg.agents["antigravity"] = AgentVoiceProfile(voice="en-US-ChristopherNeural", provider="edge_tts")

    with patch("voicefi.cli.load_config", return_value=mock_cfg), \
         patch("voicefi.cli.get_tts_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_engine.voice = "en-US-ChristopherNeural"
        mock_get_engine.return_value = mock_engine
        cmd_speak(args)
        mock_engine.speak.assert_called_once()
        assert mock_get_engine.call_args.kwargs.get("agent_name") == "antigravity"

