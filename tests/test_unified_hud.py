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

    frame = hud._get_target_frame(hud.STANDARD_WIDTH, hud.STANDARD_HEIGHT)
    assert frame.origin.x == 300.0 - (hud.STANDARD_WIDTH / 2.0)
    assert frame.origin.y == 600.0 - hud.STANDARD_HEIGHT
    assert frame.size.width == 480.0
    assert frame.size.height == 58.0

    hud.reset_position()
    assert hud._user_dragged_center_x is None
    assert hud._user_dragged_top_y is None

    # Test top-right anchoring with default margins on NSScreen (margin_x=20.0, margin_y=52.0)
    mock_screen = MagicMock()
    mock_visible = MagicMock()
    mock_visible.origin.x = 0.0
    mock_visible.origin.y = 0.0
    mock_visible.size.width = 1920.0
    mock_visible.size.height = 1080.0
    mock_screen.visibleFrame.return_value = mock_visible

    with patch("voicefi.ui.unified_hud.NSScreen.mainScreen", return_value=mock_screen):
        frame_tr = hud._get_target_frame(hud.STANDARD_WIDTH, hud.STANDARD_HEIGHT)
        # Expected: x = 1920 - 480 - 20 = 1420.0; y = 1080 - 58 - 52 = 970.0 (clears Chrome top tab bar)
        assert frame_tr.origin.x == 1420.0
        assert frame_tr.origin.y == 970.0
        assert frame_tr.size.width == 480.0
        assert frame_tr.size.height == 58.0

        # Test custom configured margins
        hud.config.hud.margin_x = 30.0
        hud.config.hud.margin_y = 60.0
        frame_custom = hud._get_target_frame(hud.STANDARD_WIDTH, hud.STANDARD_HEIGHT)
        assert frame_custom.origin.x == 1920.0 - 480.0 - 30.0
        assert frame_custom.origin.y == 1080.0 - 58.0 - 60.0
        hud.config.hud.margin_x = 20.0
        hud.config.hud.margin_y = 52.0


def test_unified_hud_fixed_dimensions(mock_appkit):
    hud = UnifiedDynamicIslandHUD.get_instance()
    assert hud.STANDARD_WIDTH == 480.0
    assert hud.STANDARD_HEIGHT == 58.0


def test_cmd_hud_actions(mock_appkit):
    from voicefi.cli import cmd_hud
    import argparse
    from voicefi.config import load_config

    # Test 'on' action
    args_on = argparse.Namespace(hud_action="on")
    with patch("subprocess.run") as mock_run, \
         patch("voicefi.cli.cmd_autostart") as mock_autostart:
        mock_run.return_value.returncode = 1 # daemon not running -> starts autostart
        cmd_hud(args_on)
        mock_autostart.assert_called_once()
        cfg = load_config()
        assert cfg.hud.enabled is True
        assert cfg.hud.persistent is True

    # Test 'off' action
    args_off = argparse.Namespace(hud_action="off")
    cmd_hud(args_off)
    cfg = load_config()
    assert cfg.hud.enabled is False

    # Test 'debug' action in non-tty mode (clean exit)
    args_debug = argparse.Namespace(hud_action="debug")
    with patch("sys.stdin.isatty", return_value=False):
        cmd_hud(args_debug)

    # Test 'open' action
    args_open = argparse.Namespace(hud_action="open")
    with patch("subprocess.run") as mock_run, \
         patch("voicefi.cli.cmd_autostart") as mock_autostart:
        mock_run.return_value.returncode = 0
        cmd_hud(args_open)
        cfg = load_config()
        assert cfg.hud.enabled is True
        assert cfg.hud.persistent is True

    # Test 'close' action
    args_close = argparse.Namespace(hud_action="close")
    cmd_hud(args_close)
    cfg = load_config()
    assert cfg.hud.enabled is False

    # Test 'reset' action
    args_reset = argparse.Namespace(hud_action="reset")
    cmd_hud(args_reset)

    # Test 'fullscreen' toggle
    args_fs = argparse.Namespace(hud_action="fullscreen", fullscreen_state="toggle")
    cmd_hud(args_fs)

    # Test 'status' action
    args_stat = argparse.Namespace(hud_action="status")
    cmd_hud(args_stat)


def test_tray_dynamic_config_reload(mock_appkit, tmp_path):
    from voicefi.ui.tray import VoiceFiTrayApp
    from voicefi.config import VoiceFiConfig
    with patch("voicefi.ui.tray.get_default_config_path") as mock_cfg_path, \
         patch("voicefi.ui.tray.load_config") as mock_load_cfg:
        fake_cfg_file = tmp_path / "config.yaml"
        fake_cfg_file.write_text("dummy")
        mock_cfg_path.return_value = fake_cfg_file

        mock_cfg = VoiceFiConfig()
        mock_cfg.hud.enabled = True
        mock_cfg.hud.persistent = True
        mock_cfg.hud.fullscreen_overlay = True
        mock_cfg.hud.auto_send = True
        mock_load_cfg.return_value = mock_cfg

        app = VoiceFiTrayApp.__new__(VoiceFiTrayApp)
        app.config = VoiceFiConfig()
        app.hud = UnifiedDynamicIslandHUD.get_instance()
        app._last_config_mtime = 0.0

        # Run reload check
        app._check_config_reload()
        assert app.hud.persistent is True
        assert app.config.hud.enabled is True


