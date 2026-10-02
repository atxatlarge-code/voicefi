import pytest
import tempfile
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from voicefi.integrations.conversations import (
    save_gemma_turn,
    parse_gemma_session,
    parse_full_gemma_conversation_details,
    find_recent_gemma_sessions,
    get_gemma_sessions_dir,
)
from voicefi.ui.companion_window import CompanionDesktopWindow


def test_gemma_session_lifecycle(tmp_path, monkeypatch):
    """Test saving and retrieving local Gemma conversation turns."""
    monkeypatch.setattr(
        "voicefi.integrations.conversations.get_gemma_sessions_dir",
        lambda: tmp_path,
    )

    conv_id = "gemma_test_123"
    path = save_gemma_turn(
        conv_id=conv_id,
        user_text="What is Apple Silicon Metal?",
        agent_text="Metal is Apple's hardware-accelerated GPU framework.",
        model="gemma4-2b",
        title="Apple Silicon Metal",
    )

    assert path.is_file()
    session_data = json.loads(path.read_text(encoding="utf-8"))
    assert session_data["id"] == conv_id
    assert session_data["engine"] == "gemma"
    assert session_data["model"] == "gemma4-2b"
    assert len(session_data["turns"]) == 1
    assert session_data["turns"][0]["user"] == "What is Apple Silicon Metal?"

    # Parse summary info
    info = parse_gemma_session(path)
    assert info is not None
    assert info.id == conv_id
    assert info.engine == "gemma"
    assert info.title == "Apple Silicon Metal"

    # Append second turn
    save_gemma_turn(
        conv_id=conv_id,
        user_text="Does Gemma 4 support it?",
        agent_text="Yes, via LiteRT-LM Metal GPU kernels.",
        model="gemma4-2b",
    )

    # Parse full details
    details = parse_full_gemma_conversation_details(conv_id)
    assert details is not None
    assert details["engine"] == "gemma"
    assert len(details["turns"]) == 2
    assert details["turns"][1]["user"] == "Does Gemma 4 support it?"


def test_companion_desktop_window_headless(monkeypatch):
    """Verify CompanionDesktopWindow works safely in headless / test mode."""
    monkeypatch.setenv("VOICEFI_HEADLESS", "1")
    CompanionDesktopWindow._instance = None

    win = CompanionDesktopWindow.get_instance(port=5141)
    assert win.port == 5141
    # Calling show/hide/toggle in headless mode shouldn't raise
    win.show()
    win.hide()
    win.toggle()


def test_quick_bar_dispatches_to_gemma(monkeypatch):
    """Verify QuickPromptBarWindow routes 'gemma' to CompanionDesktopWindow."""
    monkeypatch.setenv("VOICEFI_TESTING", "1")
    from voicefi.ui.quick_bar import QuickPromptBarWindow

    bar = QuickPromptBarWindow(on_submit=None)
    mock_companion_win = MagicMock()
    monkeypatch.setattr(
        "voicefi.ui.companion_window.CompanionDesktopWindow.get_instance",
        lambda: mock_companion_win,
    )

    bar.dispatch_to_agent("Hello from user", agent_id="gemma", silent_send=False)
    mock_companion_win.dispatch_prompt.assert_called_once_with(
        "Hello from user",
        engine="gemma",
        model="gemma4-2b",
        show_window=True,
    )

    mock_companion_win.reset_mock()
    bar.dispatch_to_agent("Silent prompt", agent_id="gemma4-26b", silent_send=True)
    mock_companion_win.dispatch_prompt.assert_called_once_with(
        "Silent prompt",
        engine="gemma",
        model="gemma4-26b",
        show_window=False,
    )


def test_companion_geometry_config_and_saving():
    """Verify CompanionConfig geometry fields and save_geometry serialization."""
    from voicefi.config import VoiceFiConfig, CompanionConfig

    cfg = VoiceFiConfig()
    assert hasattr(cfg.companion, "window_x")
    assert hasattr(cfg.companion, "window_y")
    assert cfg.companion.window_width == 460.0
    assert cfg.companion.window_height == 760.0
    assert cfg.companion.dock_edge == "right"

    win = CompanionDesktopWindow(port=5141)
    mock_panel = MagicMock()
    mock_frame = MagicMock()
    mock_frame.origin.x = 1200.0
    mock_frame.origin.y = 100.0
    mock_frame.size.width = 460.0
    mock_frame.size.height = 800.0
    mock_panel.frame.return_value = mock_frame

    mock_screen = MagicMock()
    mock_screen_frame = MagicMock()
    mock_screen_frame.origin.x = 0.0
    mock_screen_frame.size.width = 1680.0
    mock_screen.visibleFrame.return_value = mock_screen_frame
    mock_panel.screen.return_value = mock_screen

    win._panel = mock_panel

    with patch("voicefi.ui.companion_window.is_headless", return_value=False), \
         patch("voicefi.config.load_config", return_value=cfg), \
         patch("voicefi.config.save_config") as mock_save:
        win.save_geometry()
        mock_save.assert_called_once()
        saved_cfg = mock_save.call_args[0][0]
        assert saved_cfg.companion.window_x == 1200.0
        assert saved_cfg.companion.window_y == 100.0
        assert saved_cfg.companion.window_width == 460.0
        assert saved_cfg.companion.window_height == 800.0


def test_global_hotkey_companion_defaults():
    """Verify GlobalHotkeyConfig includes companion window hotkey defaults."""
    from voicefi.config import GlobalHotkeyConfig

    hotkey_cfg = GlobalHotkeyConfig()
    assert hotkey_cfg.companion_window_hotkey == "<ctrl>+<alt>+c"
    assert hotkey_cfg.companion_window_enabled is True


import asyncio
from aiohttp.test_utils import AioHTTPTestCase
from voicefi.config import VoiceFiConfig
from voicefi.companion.server import CompanionServer


class GemmaCompanionServerTestCase(AioHTTPTestCase):
    """Integration test suite for CompanionServer Gemma endpoints and TTS."""

    async def get_application(self):
        self.cfg = VoiceFiConfig()
        self.companion_server = CompanionServer(config=self.cfg, port=5141)
        self.companion_server.loop = asyncio.get_event_loop()
        return self.companion_server.app

    async def test_get_and_set_gemma_model_endpoints(self):
        """Test GET and POST /api/config/gemma_model and /api/local_model."""
        # 1. GET current model (defaults to gemma4-2b)
        resp = await self.client.get("/api/config/gemma_model")
        assert resp.status == 200
        data = await resp.json()
        assert data.get("success") is True
        assert data.get("model") in ("gemma4-2b", "gemma4-26b")

        # 2. POST to switch to 26b
        with patch("voicefi.companion.server.save_config") as mock_save, \
             patch.object(self.companion_server, "broadcast_event") as mock_broadcast:
            resp = await self.client.post(
                "/api/config/gemma_model", json={"model": "gemma4-26b"}
            )
            assert resp.status == 200
            post_data = await resp.json()
            assert post_data.get("success") is True
            assert post_data.get("model") == "gemma4-26b"
            mock_save.assert_called_once()
            mock_broadcast.assert_called_with(
                {
                    "type": "gemma_model_changed",
                    "model": "gemma4-26b",
                    "model_name": "gemma4-26b",
                }
            )

        # 3. GET /api/local_model alias
        resp = await self.client.get("/api/local_model")
        assert resp.status == 200
        alias_data = await resp.json()
        assert alias_data.get("model") == "gemma4-26b"

        # 4. POST /api/local_model alias to switch back
        with patch("voicefi.companion.server.save_config"):
            resp = await self.client.post(
                "/api/local_model", json={"model": "gemma4-2b"}
            )
            assert resp.status == 200
            back_data = await resp.json()
            assert back_data.get("model") == "gemma4-2b"

    async def test_speak_in_background_gemma_playback(self):
        """Test _speak_in_background extracts soundbite and invokes neural TTS for Gemma."""
        raw_text = (
            "Here is the code solution:\n"
            "```python\nprint('Hello Gemma')\n```\n"
            "The model loaded onto Apple Silicon Metal successfully."
        )

        mock_tts = MagicMock()
        mock_tts.voice = "Andrew"
        mock_tts.stream_speak = MagicMock()

        with patch("voicefi.companion.server.load_config", return_value=self.cfg), \
             patch("voicefi.companion.server.get_tts_engine", return_value=mock_tts) as mock_get_tts, \
             patch("voicefi.tts.base.stop_active_playback"), \
             patch("voicefi.audio.echo_canceller.record_agent_spoken"), \
             patch("voicefi.tts.base.set_cross_process_hud_state"), \
             patch("voicefi.tts.base.clear_cross_process_hud_state"), \
             patch("voicefi.tts.base.escape_to_stop_speech"), \
             patch.object(self.companion_server, "broadcast_agent_turn_completed") as mock_turn_completed:

            # Execute synchronous helper (spawns thread or speaks)
            with patch("threading.Thread") as mock_thread:
                # Capture thread target and run inline to verify execution
                def run_thread(*args, **kwargs):
                    target = kwargs.get("target")
                    mock_t = MagicMock()
                    mock_t.start = lambda: target() if target else None
                    return mock_t

                mock_thread.side_effect = run_thread

                self.companion_server._speak_in_background(
                    spoken=raw_text,
                    agent_name="gemma",
                    conv_id="gemma_test_voice_1",
                    origin="desktop",
                )

                mock_get_tts.assert_called_once_with(
                    self.companion_server.config,
                    agent_name="gemma",
                    app_name="Gemma",
                    conv_id="gemma_test_voice_1",
                )
                mock_tts.stream_speak.assert_called_once()
                mock_turn_completed.assert_called_once()
                turn_args, turn_kwargs = mock_turn_completed.call_args
                assert turn_kwargs.get("agent_role") == "gemma"
                assert turn_kwargs.get("conv_id") == "gemma_test_voice_1"
                assert "```" not in turn_kwargs.get("summary")

    async def test_api_new_gemma_conversation(self):
        """Test POST /api/conversation/new with engine='gemma' dispatches to local model."""
        mock_eng = MagicMock()
        mock_eng.chat_text = MagicMock(return_value=asyncio.Future())
        mock_eng.chat_text.return_value.set_result("Gemma local reply")

        with patch("voicefi.local.engine.LocalModelEngine", return_value=mock_eng), \
             patch("voicefi.integrations.conversations.save_gemma_turn") as mock_save, \
             patch.object(self.companion_server, "_speak_in_background") as mock_speak:

            resp = await self.client.post("/api/conversation/new", json={
                "prompt": "Explain Metal GPU acceleration",
                "engine": "gemma",
                "model": "gemma4-26b",
            })
            assert resp.status == 200
            data = await resp.json()
            assert data.get("success") is True
            assert data.get("conv_id", "").startswith("gemma_")
            await asyncio.sleep(0.05)
            assert mock_save.call_count == 2
            # Initial placeholder save
            init_args, init_kwargs = mock_save.call_args_list[0]
            assert init_kwargs.get("model") == "gemma4-26b"
            assert init_kwargs.get("user_text") == "Explain Metal GPU acceleration"
            assert init_kwargs.get("agent_text") == ""
            # Final completed save
            final_args, final_kwargs = mock_save.call_args_list[1]
            assert final_kwargs.get("model") == "gemma4-26b"
            assert final_kwargs.get("user_text") == "Explain Metal GPU acceleration"
            assert final_kwargs.get("agent_text") == "Gemma local reply"


def test_companion_dispatch_prompt_fallback_to_local_engine(monkeypatch):
    """Verify dispatch_prompt executes in-process via LocalModelEngine when server is unreachable."""
    monkeypatch.setenv("VOICEFI_HEADLESS", "1")
    CompanionDesktopWindow._instance = None
    win = CompanionDesktopWindow.get_instance(port=59999)  # unreachable port

    from unittest.mock import AsyncMock
    mock_eng = MagicMock()
    mock_eng.chat_text = AsyncMock(return_value="Direct local response")

    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")), \
         patch("voicefi.local.engine.LocalModelEngine", return_value=mock_eng), \
         patch("voicefi.integrations.conversations.save_gemma_turn") as mock_save, \
         patch("voicefi.tts.get_tts_engine") as mock_get_tts:
        win.dispatch_prompt("Offline query", engine="gemma", model="gemma4-2b", show_window=False)
        time.sleep(0.1)
        assert mock_save.call_count >= 1
        save_calls = mock_save.call_args_list
        assert any(call[1].get("user_text") == "Offline query" for call in save_calls)



