"""
Tests for Tab-to-Focus speaking window feature.
Verifies is_tab_key detection, focus_speaking_agent_window routing,
metadata persistence, and keyboard listener interactions during speech.
"""

import json
import time
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

from voicefi.tts.base import (
    is_tab_key,
    is_option_tab_event,
    is_escape_key,
    set_agent_speaking,
    get_agent_speaking_info,
    set_cross_process_hud_state,
    get_cross_process_hud_state,
    focus_speaking_window,
    escape_to_stop_speech,
    get_recent_speaking_info,
    AGENT_SPEAKING_STATUS_FILE,
    HUD_STATE_STATUS_FILE,
    LAST_AGENT_SPEAKING_STATUS_FILE,
)
from voicefi.integrations.injector import (
    focus_speaking_agent_window,
    focus_app_by_name,
)


class DummyKey:
    """Mock pynput key object."""
    def __init__(self, name=None, vk=None, char=None, value=None):
        self.name = name
        self.vk = vk
        self.char = char
        self.value = value


class TestIsTabKey:
    def test_tab_key_enum(self):
        try:
            from pynput.keyboard import Key
            assert is_tab_key(Key.tab) is True
            assert is_tab_key(Key.space) is False
            assert is_tab_key(Key.esc) is False
            assert is_tab_key(Key.enter) is False
        except ImportError:
            pass

    def test_tab_vk_code(self):
        # macOS virtual key code 48 is Tab
        key = DummyKey(vk=48)
        assert is_tab_key(key) is True

        key_non_tab = DummyKey(vk=49)
        assert is_tab_key(key_non_tab) is False

    def test_tab_char(self):
        key = DummyKey(char="\t")
        assert is_tab_key(key) is True

        key_other = DummyKey(char="a")
        assert is_tab_key(key_other) is False

    def test_tab_name(self):
        key = DummyKey(name="tab")
        assert is_tab_key(key) is True

    def test_none_key(self):
        assert is_tab_key(None) is False


class TestIsOptionTabEvent:
    def test_option_tab_event_enums(self):
        try:
            from pynput.keyboard import Key
            # Option+Tab is True
            assert is_option_tab_event(Key.tab, modifiers={"alt"}) is True
            # Bare Tab is False
            assert is_option_tab_event(Key.tab, modifiers=set()) is False
            # Cmd+Tab is False
            assert is_option_tab_event(Key.tab, modifiers={"cmd"}) is False
            # Ctrl+Tab is False
            assert is_option_tab_event(Key.tab, modifiers={"ctrl"}) is False
            # Cmd+Option+Tab is False
            assert is_option_tab_event(Key.tab, modifiers={"alt", "cmd"}) is False
            # Ctrl+Option+Tab is False
            assert is_option_tab_event(Key.tab, modifiers={"alt", "ctrl"}) is False
            # Option+Space is False
            assert is_option_tab_event(Key.space, modifiers={"alt"}) is False
        except ImportError:
            pass

    def test_dummy_key_option_tab(self):
        tab_key = DummyKey(vk=48)
        non_tab = DummyKey(vk=49)
        # Option+Tab with vk=48
        assert is_option_tab_event(tab_key, modifiers={"alt"}) is True
        # Bare Tab (no modifiers)
        assert is_option_tab_event(tab_key, modifiers=set()) is False
        # Non-tab key with Option
        assert is_option_tab_event(non_tab, modifiers={"alt"}) is False
        # None key
        assert is_option_tab_event(None, modifiers={"alt"}) is False


class TestSpeakingStateMetadata:
    def test_set_and_get_agent_speaking_info_with_window_metadata(self, tmp_path, monkeypatch):
        status_file = tmp_path / "voicefi_speaking_test.json"
        hud_file = tmp_path / "voicefi_hud_test.json"
        monkeypatch.setattr("voicefi.tts.base.AGENT_SPEAKING_STATUS_FILE", status_file)
        monkeypatch.setattr("voicefi.tts.base.HUD_STATE_STATUS_FILE", hud_file)

        set_agent_speaking(
            True,
            text="Hello from Antigravity agent",
            agent_name="antigravity",
            persona_name="Viv",
            app_name="Antigravity",
            conv_id="test-conv-123",
            workspace_path="/Users/test/workspace",
        )

        info = get_agent_speaking_info()
        assert info is not None
        assert info.get("agent_name") == "antigravity"
        assert info.get("persona_name") == "Viv"
        assert info.get("app_name") == "Antigravity"
        assert info.get("conv_id") == "test-conv-123"
        assert info.get("workspace_path") == "/Users/test/workspace"

        hud_info = get_cross_process_hud_state()
        assert hud_info is not None
        assert hud_info.get("state") == "speaking"
        assert hud_info.get("app_name") == "Antigravity"
        assert hud_info.get("conv_id") == "test-conv-123"

        # Cleanup speaking
        set_agent_speaking(False)
        assert get_agent_speaking_info() is None

    def test_recent_speaking_info_grace_period(self, tmp_path, monkeypatch):
        status_file = tmp_path / "voicefi_speaking_test.json"
        last_file = tmp_path / "voicefi_last_speaking_test.json"
        monkeypatch.setattr("voicefi.tts.base.AGENT_SPEAKING_STATUS_FILE", status_file)
        monkeypatch.setattr("voicefi.tts.base.LAST_AGENT_SPEAKING_STATUS_FILE", last_file)

        set_agent_speaking(
            True,
            text="Recent speech test",
            agent_name="claude",
            persona_name="Viv",
            app_name="Claude",
            conv_id="claude-456",
        )

        # Active while speaking
        assert get_recent_speaking_info(window_seconds=2.0) is not None
        assert get_recent_speaking_info(window_seconds=2.0).get("agent_name") == "claude"

        # Stop speech
        set_agent_speaking(False)
        assert get_agent_speaking_info() is None

        # Still accessible within grace period
        recent = get_recent_speaking_info(window_seconds=3.0)
        assert recent is not None
        assert recent.get("agent_name") == "claude"
        assert recent.get("app_name") == "Claude"

        # Not accessible if window_seconds is 0
        assert get_recent_speaking_info(window_seconds=-1.0) is None


class TestFocusSpeakingAgentWindow:
    @patch("voicefi.integrations.injector.focus_antigravity")
    def test_focus_antigravity_default(self, mock_focus_ag):
        mock_focus_ag.return_value = True
        res = focus_speaking_agent_window(agent_name="antigravity", app_name="Antigravity")
        assert res is True
        mock_focus_ag.assert_called_once_with(focus_input=True)

    @patch("voicefi.integrations.injector.focus_terminal_app")
    def test_focus_claude(self, mock_focus_term):
        mock_focus_term.return_value = "Ghostty"
        res = focus_speaking_agent_window(agent_name="claude", app_name="Claude")
        assert res is True
        mock_focus_term.assert_called_once()

    @patch("voicefi.integrations.injector.focus_chatgpt")
    def test_focus_chatgpt(self, mock_focus_chatgpt):
        mock_focus_chatgpt.return_value = True
        res = focus_speaking_agent_window(agent_name="chatgpt", app_name="ChatGPT")
        assert res is True
        mock_focus_chatgpt.assert_called_once_with(focus_input=True)

    @patch("voicefi.integrations.injector.focus_app_by_name")
    def test_focus_custom_app(self, mock_focus_app):
        mock_focus_app.return_value = True
        res = focus_speaking_agent_window(agent_name="custom_worker", app_name="Ghostty")
        assert res is True
        mock_focus_app.assert_called_once_with("Ghostty")

    @patch("voicefi.integrations.injector.focus_antigravity")
    def test_focus_from_saved_speaking_info(self, mock_focus_ag, tmp_path, monkeypatch):
        status_file = tmp_path / "voicefi_speaking_test.json"
        monkeypatch.setattr("voicefi.tts.base.AGENT_SPEAKING_STATUS_FILE", status_file)
        mock_focus_ag.return_value = True

        set_agent_speaking(
            True,
            text="Explaining code",
            agent_name="antigravity",
            app_name="Antigravity",
        )

        res = focus_speaking_agent_window()
        assert res is True
        mock_focus_ag.assert_called_once_with(focus_input=True)

        set_agent_speaking(False)

    @patch("voicefi.integrations.injector.navigate_to_antigravity_conversation")
    def test_focus_antigravity_with_conv_id(self, mock_nav_ag):
        mock_nav_ag.return_value = True
        res = focus_speaking_agent_window(
            agent_name="antigravity",
            app_name="Antigravity",
            conv_id="conv-12345",
        )
        assert res is True
        mock_nav_ag.assert_called_once_with(conv_id="conv-12345")

    @patch("voicefi.integrations.injector.focus_antigravity")
    @patch("voicefi.integrations.injector.navigate_to_antigravity_conversation")
    def test_focus_antigravity_with_conv_id_fallback(self, mock_nav_ag, mock_focus_ag):
        mock_nav_ag.return_value = False
        mock_focus_ag.return_value = True
        res = focus_speaking_agent_window(
            agent_name="antigravity",
            app_name="Antigravity",
            conv_id="conv-fail",
        )
        assert res is True
        mock_nav_ag.assert_called_once_with(conv_id="conv-fail")
        mock_focus_ag.assert_called_once_with(focus_input=True)

    @patch("voicefi.integrations.injector.select_claude_conversation_window")
    def test_focus_claude_with_conv_id(self, mock_sel_claude):
        mock_sel_claude.return_value = True
        res = focus_speaking_agent_window(
            agent_name="claude",
            app_name="Claude",
            conv_id="claude-789",
        )
        assert res is True
        mock_sel_claude.assert_called_once_with(conv_id="claude-789")

    @patch("voicefi.integrations.injector.select_codex_conversation_window")
    def test_focus_codex_with_conv_id(self, mock_sel_codex):
        mock_sel_codex.return_value = True
        res = focus_speaking_agent_window(
            agent_name="codex",
            app_name="ChatGPT",
            conv_id="codex-321",
        )
        assert res is True
        mock_sel_codex.assert_called_once_with(conv_id="codex-321")


class TestEscapeToStopSpeechWithOptionTab:
    @patch("voicefi.tts.base.focus_speaking_window")
    def test_bare_tab_does_not_trigger_focus(self, mock_focus_win, monkeypatch):
        # Remove PYTEST_CURRENT_TEST override temporarily for this isolated test
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        captured_callback = {}

        class MockListener:
            def __init__(self, on_press=None, on_release=None, **kwargs):
                captured_callback["on_press"] = on_press
                captured_callback["on_release"] = on_release
                self.daemon = True

            def start(self):
                pass

            def stop(self):
                pass

        with patch("pynput.keyboard.Listener", MockListener):
            with escape_to_stop_speech(agent_name="antigravity", app_name="Antigravity"):
                on_press = captured_callback.get("on_press")
                assert on_press is not None

                # Bare Tab (vk=48 without Option): must NOT trigger focus
                on_press(DummyKey(vk=48))
                time.sleep(0.05)
                mock_focus_win.assert_not_called()

    @patch("voicefi.tts.base.focus_speaking_window")
    def test_option_tab_triggers_focus(self, mock_focus_win, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        captured_callback = {}

        class MockListener:
            def __init__(self, on_press=None, on_release=None, **kwargs):
                captured_callback["on_press"] = on_press
                captured_callback["on_release"] = on_release
                self.daemon = True

            def start(self):
                pass

            def stop(self):
                pass

        with patch("pynput.keyboard.Listener", MockListener):
            with escape_to_stop_speech(agent_name="antigravity", app_name="Antigravity"):
                on_press = captured_callback.get("on_press")
                on_release = captured_callback.get("on_release")
                assert on_press is not None

                # Press Option (vk=58), then Tab (vk=48)
                on_press(DummyKey(vk=58))
                on_press(DummyKey(vk=48))
                time.sleep(0.05)
                mock_focus_win.assert_called_once_with(
                    agent_name="antigravity",
                    app_name="Antigravity",
                    conv_id=None,
                )

                # Release Option
                if on_release:
                    on_release(DummyKey(vk=58))

                # Press bare Tab again -> should NOT trigger focus
                mock_focus_win.reset_mock()
                on_press(DummyKey(vk=48))
                time.sleep(0.05)
                mock_focus_win.assert_not_called()

    @patch("voicefi.tts.base.focus_speaking_window")
    def test_cmd_tab_does_not_trigger_focus(self, mock_focus_win, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        captured_callback = {}

        class MockListener:
            def __init__(self, on_press=None, on_release=None, **kwargs):
                captured_callback["on_press"] = on_press
                captured_callback["on_release"] = on_release
                self.daemon = True

            def start(self):
                pass

            def stop(self):
                pass

        with patch("pynput.keyboard.Listener", MockListener):
            with escape_to_stop_speech(agent_name="antigravity", app_name="Antigravity"):
                on_press = captured_callback.get("on_press")
                assert on_press is not None

                # Press Cmd (vk=55) then Tab (vk=48) -> Cmd+Tab must NOT trigger focus
                on_press(DummyKey(vk=55))
                on_press(DummyKey(vk=48))
                time.sleep(0.05)
                mock_focus_win.assert_not_called()

    @patch("voicefi.tts.base.focus_speaking_window")
    def test_option_tab_passes_conv_id(self, mock_focus_win, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        captured_callback = {}

        class MockListener:
            def __init__(self, on_press=None, on_release=None, **kwargs):
                captured_callback["on_press"] = on_press
                captured_callback["on_release"] = on_release
                self.daemon = True

            def start(self):
                pass

            def stop(self):
                pass

        with patch("pynput.keyboard.Listener", MockListener):
            with escape_to_stop_speech(
                agent_name="antigravity",
                app_name="Antigravity",
                conv_id="conv-specific-123",
            ):
                on_press = captured_callback.get("on_press")
                assert on_press is not None

                # Press Option (vk=58) then Tab (vk=48)
                on_press(DummyKey(vk=58))
                on_press(DummyKey(vk=48))
                time.sleep(0.05)
                mock_focus_win.assert_called_once_with(
                    agent_name="antigravity",
                    app_name="Antigravity",
                    conv_id="conv-specific-123",
                )


class TestTabFocusDebounceAndNonBlocking:
    @patch("voicefi.integrations.injector.focus_antigravity")
    def test_sliding_debounce_prevents_spam(self, mock_focus_ag, monkeypatch):
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setattr("voicefi.integrations.injector._LAST_FOCUS_TS", 0.0)
        mock_focus_ag.return_value = True

        # First call should succeed and invoke underlying focus
        res1 = focus_speaking_agent_window(agent_name="antigravity", app_name="Antigravity", force=False)
        assert res1 is True
        assert mock_focus_ag.call_count == 1

        # Second call immediately after (within 350ms) should be debounced
        res2 = focus_speaking_agent_window(agent_name="antigravity", app_name="Antigravity", force=False)
        assert res2 is True
        # Under debounce, call_count should still be 1!
        assert mock_focus_ag.call_count == 1

        # Forced call bypasses debounce
        res3 = focus_speaking_agent_window(agent_name="antigravity", app_name="Antigravity", force=True)
        assert res3 is True
        assert mock_focus_ag.call_count == 2


class TestHUDAppNameClick:
    @patch("voicefi.integrations.injector.focus_speaking_agent_window")
    def test_hud_app_name_click_dispatches_focus(self, mock_focus_win):
        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

        hud = MagicMock(spec=UnifiedDynamicIslandHUD)
        hud._active_agent_name = "antigravity"
        hud._active_app_name = "Antigravity"
        hud._active_conv_id = "test-conv-999"

        # Execute handle_app_name_click with hud as self
        UnifiedDynamicIslandHUD.handle_app_name_click(hud)

        # Allow spawned daemon thread to execute
        time.sleep(0.08)
        mock_focus_win.assert_called_once_with(
            agent_name="antigravity",
            app_name="Antigravity",
            conv_id="test-conv-999",
            force=True,
        )

    @patch("voicefi.tts.base.is_agent_speaking")
    def test_hud_body_click_delegates_to_app_name_click_when_idle(self, mock_is_speaking):
        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

        mock_is_speaking.return_value = False
        hud = MagicMock(spec=UnifiedDynamicIslandHUD)

        UnifiedDynamicIslandHUD.handle_body_click(hud)
        hud.handle_app_name_click.assert_called_once()

    @patch("voicefi.tts.base.stop_all_speech")
    @patch("voicefi.tts.base.is_agent_speaking")
    def test_hud_body_click_stops_speech_when_speaking(self, mock_is_speaking, mock_stop_speech):
        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

        mock_is_speaking.return_value = True
        hud = MagicMock(spec=UnifiedDynamicIslandHUD)

        UnifiedDynamicIslandHUD.handle_body_click(hud)
        mock_stop_speech.assert_called_once()
        hud.handle_app_name_click.assert_not_called()
