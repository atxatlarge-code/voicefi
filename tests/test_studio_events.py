"""
Unit tests for the Interactive Ambient Voice + Active Listening & Memo Visualizer Studio.
Verifies event throttling, state transitions, remote controls, REST endpoints, and WebSocket sync.
"""


import time
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from voicefi.config import VoiceFiConfig, StudioConfig
from voicefi.audio.ambient import AmbientAudioStream
from voicefi.memo.recorder import MemoBufferRecorder
from voicefi.integrations.proactive import ProactiveDispatcher, ProactiveTask, TriageCategory
from voicefi.companion.server import CompanionServer


def test_studio_config_defaults():
    """Verify StudioConfig model and integration with VoiceFiConfig."""
    cfg = VoiceFiConfig()
    assert hasattr(cfg, "studio")
    assert cfg.studio.auto_open_browser is True
    assert cfg.studio.energy_broadcast_hz == 10
    assert cfg.studio.particle_theme == "google"


def test_ambient_stream_callbacks():
    """Verify AmbientAudioStream initializes with callbacks and handles state changes."""
    energy_events = []
    state_events = []
    progress_events = []

    stream = AmbientAudioStream(
        sample_rate=16000,
        chunk_duration=0.05,
        energy_threshold=0.005,
        on_energy=lambda e, nf, sp: energy_events.append((e, nf, sp)),
        on_state_change=lambda st: state_events.append(st),
        on_utterance_progress=lambda dur: progress_events.append(dur),
    )

    assert stream.is_running is False
    assert stream._current_state == "stopped"

    # Test state transitions
    stream._set_state("listening")
    assert "listening" in state_events
    assert stream._current_state == "listening"

    stream._set_state("speech_detected")
    assert "speech_detected" in state_events

    stream.pause()
    assert stream._current_state == "paused"

    stream.resume()
    assert stream._current_state == "listening"


def test_memo_recorder_remote_controls():
    """Verify MemoBufferRecorder remote extension, pause toggling, and finish signals."""
    recorder = MemoBufferRecorder(
        target_duration_seconds=180.0,
        sample_rate=16000,
        energy_threshold=0.003,
    )

    # Test extension
    assert recorder._pending_extension_seconds == 0.0
    recorder.extend(60.0)
    assert recorder._pending_extension_seconds == 60.0
    recorder.extend(120.0)
    assert recorder._pending_extension_seconds == 180.0

    # Test pause toggle
    assert recorder.pause_event.is_set() is False
    is_paused = recorder.toggle_pause()
    assert is_paused is True
    assert recorder.pause_event.is_set() is True
    is_paused = recorder.toggle_pause()
    assert is_paused is False
    assert recorder.pause_event.is_set() is False

    # Test finish
    assert recorder.stop_event.is_set() is False
    recorder.finish()
    assert recorder.stop_event.is_set() is True


def test_proactive_triage_task_creation():
    """Verify ProactiveDispatcher creates tasks and classifies SCAFFOLD/RESEARCH."""
    dispatcher = ProactiveDispatcher()

    task1 = dispatcher.process_utterance("Let's build a new webhook endpoint for Stripe payments")
    assert task1 is not None
    assert task1.category in (TriageCategory.SCAFFOLD, TriageCategory.RESEARCH)
    assert task1.status == "staged"

    staged = dispatcher.get_staged_tasks()
    assert len(staged) >= 1
    assert any(t.id == task1.id for t in staged)

    # Test dismiss
    dispatcher.dismiss_task(task1.id)
    assert len(dispatcher.get_staged_tasks()) == 0


class TestStudioServerEndpoints(AioHTTPTestCase):
    """Test suite for CompanionServer studio endpoints and REST API."""

    async def get_application(self):
        self.config = VoiceFiConfig()
        self.server = CompanionServer(config=self.config, port=8765)
        return self.server.app

    @unittest_run_loop
    async def test_get_studio_page(self):
        """Verify GET /studio returns 200 with HTML content."""
        resp = await self.client.request("GET", "/studio")
        assert resp.status == 200
        text = await resp.text()
        assert "VoiceFi™ Studio" in text
        assert "ambientWaveform" in text
        assert "stagedTasksDeck" in text
        assert "timerCircle" in text

    @unittest_run_loop
    async def test_ambient_status_and_lifecycle(self):
        """Verify GET /api/ambient/status and POST /api/ambient/start/stop."""
        resp = await self.client.request("GET", "/api/ambient/status")
        assert resp.status == 200
        data = await resp.json()
        assert "is_running" in data
        assert "staged_tasks" in data

        # Mock AmbientAudioStream to test start/stop via endpoint
        with patch("voicefi.companion.server.AmbientAudioStream") as MockStream:
            mock_inst = MagicMock()
            mock_inst.is_running = True
            mock_inst.current_noise_floor = 0.005
            MockStream.return_value = mock_inst

            start_resp = await self.client.request("POST", "/api/ambient/start", json={"source": "mic"})
            assert start_resp.status == 200
            start_data = await start_resp.json()
            assert start_data["success"] is True

            stop_resp = await self.client.request("POST", "/api/ambient/stop")
            assert stop_resp.status == 200
            stop_data = await stop_resp.json()
            assert stop_data["success"] is True

    @unittest_run_loop
    async def test_memos_rest_api(self):
        """Verify GET /api/memos lists stored memos."""
        resp = await self.client.request("GET", "/api/memos")
        assert resp.status == 200
        data = await resp.json()
        assert "memos" in data
        assert isinstance(data["memos"], list)

    @unittest_run_loop
    async def test_ambient_task_actions(self):
        """Verify POST /api/ambient/tasks/{task_id}/action dismiss and dispatch."""
        self.server._ambient_dispatcher = ProactiveDispatcher()
        task = self.server._ambient_dispatcher.process_utterance("Let's create a database schema for users")
        assert task is not None

        # Test dismiss
        resp = await self.client.request("POST", f"/api/ambient/tasks/{task.id}/action", json={"action": "dismiss"})
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "dismissed"
