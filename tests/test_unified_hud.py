import pytest
from unittest.mock import MagicMock, patch
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD, HUDActionDelegate


@pytest.fixture
def mock_appkit():
    with patch("voicefi.ui.unified_hud.NSApplication"), \
         patch("voicefi.ui.unified_hud.NSPanel"), \
         patch("voicefi.ui.unified_hud.NSView"), \
         patch("voicefi.ui.unified_hud.NSVisualEffectView"), \
         patch("voicefi.ui.unified_hud.NSTextField"), \
         patch("voicefi.ui.unified_hud.NSButton"), \
         patch("voicefi.ui.unified_hud.NSScreen"), \
         patch("voicefi.ui.unified_hud.NSAnimationContext"):
        yield


def test_unified_hud_singleton(mock_appkit):
    hud1 = UnifiedDynamicIslandHUD.get_instance()
    hud2 = UnifiedDynamicIslandHUD.get_instance()
    assert hud1 is hud2


def test_unified_hud_states(mock_appkit):
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

    # 6. New Conversation with Connected Tools
    hud.set_new_conversation(user_name="Jake")
    assert hud._current_state == "new_conversation"


def test_unified_hud_live_typing_listening(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()
    
    hud.set_listening(user_name="Jake")
    assert hud._current_state == "listening"

    hud.update_live_transcription("Refactor auth system", user_name="Jake")
    assert hud._current_state == "listening"

    # Live typing in new conversation state
    hud.set_new_conversation(user_name="Jake")
    hud.update_live_transcription("Create new API endpoint", user_name="Jake", is_new_conversation=True)
    assert hud._current_state == "new_conversation"


def test_unified_hud_start_new_conversation_dialog(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()
    submitted = []
    cancelled = []

    hud.start_new_conversation_dialog(
        on_submit=lambda t: submitted.append(t),
        on_cancel=lambda: cancelled.append(True),
        initial_text="Build MCP server",
    )
    assert hud._current_state == "editing"



def test_unified_hud_persistent_mode(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()
    hud.set_persistent(True)
    assert hud.persistent is True

    # When persistent, hide() should return to idle
    hud.set_working(agent_name="Antigravity", tool_action="Building")
    assert hud._current_state == "working"
    hud.hide()
    assert hud._current_state == "idle"

    # When disabled, persistent is False
    hud.set_persistent(False)
    assert hud.persistent is False


def test_unified_hud_fullscreen_overlay(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()
    hud.set_fullscreen_overlay(True)
    assert hud.fullscreen_overlay is True

    hud.set_fullscreen_overlay(False)
    assert hud.fullscreen_overlay is False

    # Restore default
    hud.set_fullscreen_overlay(True)
    assert hud.fullscreen_overlay is True



def test_unified_hud_editing_and_auto_send(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()
    
    hud.set_auto_send(False)
    assert hud.auto_send is False

    submitted_text = []
    cancelled = []

    def on_submit(text):
        submitted_text.append(text)

    def on_cancel():
        cancelled.append(True)

    hud.set_editing(
        initial_text="Refactor test_auth.py to use mocks",
        on_submit=on_submit,
        on_cancel=on_cancel,
        target_name="Antigravity",
    )
    assert hud._current_state == "editing"

    # Test delegate action triggers
    mock_field = MagicMock()
    mock_field.stringValue.return_value = "Edited prompt text"

    delegate = HUDActionDelegate.alloc().initWithSubmit_cancel_field_(
        on_submit,
        on_cancel,
        mock_field,
    )
    delegate.submitAction_(None)
    assert len(submitted_text) == 1
    assert submitted_text[0] == "Edited prompt text"

    delegate.cancelAction_(None)
    assert len(cancelled) == 1
    assert cancelled[0] is True


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


def test_unified_hud_draggability_and_reset(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()
    hud._user_dragged_center_x = 300.0
    hud._user_dragged_top_y = 600.0

    frame = hud._get_target_frame(152, 32)
    assert frame.origin.x == 300.0 - (152 / 2.0)
    assert frame.origin.y == 600.0 - 32

    hud.reset_position()
    assert hud._user_dragged_center_x is None
    assert hud._user_dragged_top_y is None

