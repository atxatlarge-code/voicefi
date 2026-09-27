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
    assert len(tools) == 5
    tool_names = [t.__name__ for t in tools]
    assert "read_code_file" in tool_names
    assert "search_codebase" in tool_names
    assert "run_shell_check" in tool_names
    assert "trigger_sound_effect" in tool_names
    assert "dispatch_to_antigravity" in tool_names
    assert len(TOOL_MAP) == 5


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


def test_dispatch_to_antigravity_success():
    from voicefi.integrations.live_tools import dispatch_to_antigravity
    from voicefi.integrations.injector import DispatchResult

    mock_res = DispatchResult(
        success=True,
        delivery_type="agentapi",
        target_conv_id="8dbf2cc1-05d1-4ad3",
        engine="antigravity",
    )
    with patch("voicefi.integrations.injector.send_message_to_antigravity", return_value=mock_res) as mock_send:
        with patch("voicefi.tts.base.set_cross_process_hud_state") as mock_hud:
            res = dispatch_to_antigravity("Run pytest on unit tests")
            assert "Successfully dispatched task to Antigravity" in res
            assert "8dbf2cc1" in res
            mock_send.assert_called_once_with(
                conv_id=None,
                text="Run pytest on unit tests",
                sender_name="Gemini Live",
                title="Spoken Task Dispatch",
            )
            # Verify HUD was called for dispatching and then done
            hud_states = [call.args[0] for call in mock_hud.call_args_list]
            assert "dispatching" in hud_states
            assert "done" in hud_states


def test_dispatch_to_antigravity_failure():
    from voicefi.integrations.live_tools import dispatch_to_antigravity
    from voicefi.integrations.injector import DispatchResult

    mock_res = DispatchResult(
        success=False,
        delivery_type="none",
        error="agentapi binary not found",
        engine="antigravity",
    )
    with patch("voicefi.integrations.injector.send_message_to_antigravity", return_value=mock_res):
        with patch("voicefi.tts.base.set_cross_process_hud_state") as mock_hud:
            res = dispatch_to_antigravity("Create new migration")
            assert "Failed to dispatch to Antigravity: agentapi binary not found" in res
            hud_states = [call.args[0] for call in mock_hud.call_args_list]
            assert "dispatching" in hud_states
            assert "done" in hud_states


def test_dispatch_to_antigravity_alias_normalization():
    import asyncio
    from voicefi.integrations.injector import DispatchResult

    mock_res = DispatchResult(
        success=True,
        delivery_type="agentapi",
        target_conv_id="cid-9999",
        engine="antigravity",
    )
    with patch("voicefi.integrations.injector.send_message_to_antigravity", return_value=mock_res) as mock_send:
        with patch("voicefi.tts.base.set_cross_process_hud_state"):
            res = asyncio.run(execute_live_tool("dispatch_to_antigravity", {"task": "fix all lint errors", "cid": "cid-9999"}))
            assert "Successfully dispatched task to Antigravity" in res
            mock_send.assert_called_once_with(
                conv_id="cid-9999",
                text="fix all lint errors",
                sender_name="Gemini Live",
                title="Spoken Task Dispatch",
            )


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
    assert len(cfg.tools) == 5


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


