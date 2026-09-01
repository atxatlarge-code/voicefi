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
    is_escape_key,
    set_agent_speaking,
    get_agent_speaking_info,
    set_cross_process_hud_state,
    get_cross_process_hud_state,
    focus_speaking_window,
    escape_to_stop_speech,
    AGENT_SPEAKING_STATUS_FILE,
    HUD_STATE_STATUS_FILE,
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


class TestEscapeToStopSpeechWithTab:
    @patch("voicefi.tts.base.focus_speaking_window")
    def test_tab_triggers_focus(self, mock_focus_win, monkeypatch):
        # Remove PYTEST_CURRENT_TEST override temporarily for this isolated test
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        captured_callback = {}

        class MockListener:
            def __init__(self, on_press=None, **kwargs):
                captured_callback["on_press"] = on_press
                self.daemon = True

            def start(self):
                pass

            def stop(self):
                pass

        with patch("pynput.keyboard.Listener", MockListener):
            with escape_to_stop_speech(agent_name="antigravity", app_name="Antigravity"):
                on_press = captured_callback.get("on_press")
                assert on_press is not None

                # Trigger Tab
                on_press(DummyKey(vk=48))
                mock_focus_win.assert_called_once_with(
                    agent_name="antigravity",
                    app_name="Antigravity",
                    conv_id=None,
                )
