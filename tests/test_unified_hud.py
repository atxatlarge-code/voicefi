import pytest
from unittest.mock import MagicMock, patch
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD


@pytest.fixture
def mock_appkit():
    with patch("voicefi.ui.unified_hud.NSApplication"), \
         patch("voicefi.ui.unified_hud.NSPanel"), \
         patch("voicefi.ui.unified_hud.NSView"), \
         patch("voicefi.ui.unified_hud.NSVisualEffectView"), \
         patch("voicefi.ui.unified_hud.NSTextField"), \
         patch("voicefi.ui.unified_hud.NSScreen"), \
         patch("voicefi.ui.unified_hud.NSAnimationContext"):
        yield


def test_unified_hud_singleton(mock_appkit):
    hud1 = UnifiedDynamicIslandHUD.get_instance()
    hud2 = UnifiedDynamicIslandHUD.get_instance()
    assert hud1 is hud2


def test_unified_hud_5_states(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()
    
    # 1. Idle
    hud.set_idle()
    assert hud._current_state == "idle"

    # 2. Thinking
    hud.set_thinking(agent_name="Antigravity", detail="Evaluating code...")
    assert hud._current_state == "thinking"

    # 3. Working
    hud.set_working(agent_name="Antigravity", tool_action="Running pytest")
    assert hud._current_state == "working"

    # 4. Speaking
    hud.set_speaking(text="Test speech text", persona_name="Christopher")
    assert hud._current_state == "speaking"

    # 5. Listening
    hud.set_listening(user_name="Jake")
    assert hud._current_state == "listening"


def test_unified_hud_backward_compatibility(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()

    hud.show_speech(text="Hello world", agent_name="Antigravity")
    assert hud._current_state == "speaking"

    hud.show_listening()
    assert hud._current_state == "listening"

    hud.show_paused(message="Paused while agent speaks")
    assert hud._current_state == "paused"

    hud.show_transcribing()
    assert hud._current_state == "transcribing"

    hud.show_done(preview_text="Refactored")
    assert hud._current_state == "done"
