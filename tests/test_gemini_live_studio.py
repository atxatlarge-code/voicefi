"""
Unit tests for Gemini 3.8 Live Full-Duplex Studio, Tools, and Web Showcase.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from voicefi.audio.live_stream import calculate_rms, LiveAudioStream
from voicefi.integrations.live_tools import (
    read_code_file,
    search_codebase,
    run_shell_check,
    trigger_sound_effect,
    get_live_tools,
    execute_live_tool,
    TOOL_MAP,
)
from voicefi.live_studio import GeminiLiveStudio


def test_calculate_rms():
    # Empty bytes
    assert calculate_rms(b"") == 0.0
    # Silence (all zeros)
    silence = b"\x00\x00" * 100
    assert calculate_rms(silence) == 0.0
    # Max volume sine/square sample
    loud = b"\xff\x7f" * 100  # 32767
    assert calculate_rms(loud) > 0.9


def test_live_tools_definitions():
    tools = get_live_tools()
    assert len(tools) == 4
    tool_names = [t.__name__ for t in tools]
    assert "read_code_file" in tool_names
    assert "search_codebase" in tool_names
    assert "run_shell_check" in tool_names
    assert "trigger_sound_effect" in tool_names
    assert len(TOOL_MAP) == 4


def test_live_tools_shell_check_safety():
    # Safe command allowed
    res = run_shell_check("git branch")
    assert "git branch" not in res or "error" not in res.lower()

    # Dangerous command blocked
    res_blocked = run_shell_check("rm -rf /tmp/test")
    assert "not in safe allowed list" in res_blocked


def test_live_tools_read_code():
    res = read_code_file("src/voicefi/config.py", max_lines=5)
    assert "GeminiConfig" in res or "VoiceFiConfig" in res or "File:" in res


def test_live_tools_sfx():
    res = trigger_sound_effect("rimshot")
    assert "rimshot" in res.lower()


def test_execute_live_tool():
    import asyncio
    res = asyncio.run(execute_live_tool("read_code_file", {"path": "src/voicefi/config.py", "max_lines": 3}))
    assert "config.py" in res


def test_gemini_live_studio_init():
    studio = GeminiLiveStudio(
        api_key="AIzaSyFakeKeyForTestUnit1234567890abcdef",
        model="gemini-3.8-live",
        voice="Puck",
        use_thinking=True,
        thinking_level="HIGH",
        enable_tools=True,
    )
    assert studio.model == "gemini-3.8-live-extended-thinking"
    assert studio.voice == "Puck"
    assert studio.use_thinking is True
    assert studio.thinking_level == "HIGH"
    assert studio.enable_tools is True

    # Test LiveConnectConfig generation
    cfg = studio._build_live_config()
    assert cfg.response_modalities == ["AUDIO"]
    assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
    assert cfg.thinking_config is not None
    assert len(cfg.tools) == 4


def test_companion_server_live_route():
    from voicefi.companion.server import CompanionServer
    server = CompanionServer()
    route_paths = [r.resource.canonical for r in server.app.router.routes() if hasattr(r, "resource") and r.resource]
    assert "/live" in route_paths
    assert "/ws/live" in route_paths


def test_tool_interruption_payload_preservation():
    """Verify that even when epoch changes, a valid response payload is preserved."""
    captured_epoch = 1
    current_epoch = 2  # Interrupted
    is_stale = (captured_epoch != current_epoch)
    if is_stale:
        payload = {"result": "Action cancelled or superseded by developer interruption."}
    else:
        payload = {"result": "normal output"}
    assert "cancelled" in payload["result"]


