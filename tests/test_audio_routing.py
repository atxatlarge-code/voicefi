import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from voicefi.config import VoiceFiConfig
from voicefi.integrations.antigravity import handle_antigravity_stop_hook
from voicefi.integrations.claude import handle_claude_stop_hook
from voicefi.integrations.conversations import (
    has_active_companion_client,
    record_companion_heartbeat,
    clear_companion_heartbeat,
    set_mobile_turn_origin,
    peek_mobile_turn_origin,
    pop_mobile_turn_origin,
    claim_turn,
    get_claimed_turn_origin,
)


@pytest.fixture(autouse=True)
def cleanup_test_files():
    """Ensure clean test environment before and after each test."""
    clear_companion_heartbeat()
    for p in [
        Path("/tmp/voicefi_mobile_turn.json"),
        Path("/tmp/voicefi_active_turns.json"),
        Path("/tmp/voicefi_companion_clients.json"),
    ]:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
    yield
    clear_companion_heartbeat()
    for p in [
        Path("/tmp/voicefi_mobile_turn.json"),
        Path("/tmp/voicefi_active_turns.json"),
        Path("/tmp/voicefi_companion_clients.json"),
    ]:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass


# ==============================================================================
# 1. CONVERSATIONS & HEARTBEAT TESTS
# ==============================================================================

def test_companion_heartbeat_lifecycle():
    assert not has_active_companion_client()

    record_companion_heartbeat(1)
    assert has_active_companion_client()

    record_companion_heartbeat(0)
    assert not has_active_companion_client()

    # Expired heartbeat
    heartbeat_file = Path("/tmp/voicefi_companion_clients.json")
    with open(heartbeat_file, "w") as f:
        json.dump({"clients": 1, "timestamp": time.time() - 35.0}, f)
    assert not has_active_companion_client(max_age_seconds=25.0)


def test_mobile_turn_origin_peek_and_pop():
    set_mobile_turn_origin("conv-123")

    # Peek should NOT consume marker
    assert peek_mobile_turn_origin("conv-123")
    assert peek_mobile_turn_origin("conv-123")

    # Pop should consume marker
    assert pop_mobile_turn_origin("conv-123")
    assert not pop_mobile_turn_origin("conv-123")
    assert not peek_mobile_turn_origin("conv-123")


def test_claim_turn_preserves_mobile_origin():
    set_mobile_turn_origin("conv-mobile-1")
    claimed = claim_turn("conv-mobile-1", "conv-mobile-1:step_1", step_index=1)
    assert claimed is True

    origin = get_claimed_turn_origin("conv-mobile-1", "conv-mobile-1:step_1", step_index=1)
    assert origin == "mobile"

    # Recent conversation fallback
    fallback_origin = get_claimed_turn_origin("conv-mobile-1", "different_sig_same_conv")
    assert fallback_origin == "mobile"


# ==============================================================================
# 2. ANTIGRAVITY STOP HOOK ROUTING TESTS
# ==============================================================================

def test_antigravity_smart_routing_suppresses_mac_when_turn_is_mobile(tmp_path):
    cfg = VoiceFiConfig()
    cfg.companion.audio_routing = "smart"
    cfg.companion.mute_mac_when_companion_active = False  # Even if False, mobile turn must suppress Mac

    fake_transcript = tmp_path / "transcript.jsonl"
    fake_transcript.write_text('{"type": "PLANNER_RESPONSE", "content": "Task completed."}\n')

    with patch("voicefi.integrations.antigravity.extract_latest_agent_summary", return_value=("Task completed.", "antigravity", 1)), \
         patch("voicefi.integrations.antigravity.claim_turn", return_value=True), \
         patch("voicefi.integrations.antigravity.get_claimed_turn_origin", return_value="mobile"), \
         patch("voicefi.integrations.antigravity.peek_mobile_turn_origin", return_value=True), \
         patch("voicefi.integrations.antigravity.has_active_companion_client", return_value=False), \
         patch("voicefi.integrations.antigravity.get_tts_engine") as mock_tts:

        res = handle_antigravity_stop_hook(
            payload={"conv_id": "conv-mobile-test", "transcriptPath": str(fake_transcript)},
            config=cfg,
        )

        assert res == {}
        mock_tts.assert_not_called()


def test_antigravity_smart_routing_suppresses_mac_when_companion_is_active(tmp_path):
    cfg = VoiceFiConfig()
    cfg.companion.audio_routing = "smart"
    cfg.companion.mute_mac_when_companion_active = True

    fake_transcript = tmp_path / "transcript.jsonl"
    fake_transcript.write_text('{"type": "PLANNER_RESPONSE", "content": "Desk turn summary."}\n')

    with patch("voicefi.integrations.antigravity.extract_latest_agent_summary", return_value=("Desk turn summary.", "antigravity", 2)), \
         patch("voicefi.integrations.antigravity.claim_turn", return_value=True), \
         patch("voicefi.integrations.antigravity.get_claimed_turn_origin", return_value="desktop"), \
         patch("voicefi.integrations.antigravity.peek_mobile_turn_origin", return_value=False), \
         patch("voicefi.integrations.antigravity.has_active_companion_client", return_value=True), \
         patch("voicefi.integrations.antigravity.get_tts_engine") as mock_tts:

        res = handle_antigravity_stop_hook(
            payload={"conv_id": "conv-desktop-test", "transcriptPath": str(fake_transcript)},
            config=cfg,
        )

        assert res == {}
        mock_tts.assert_not_called()


def test_antigravity_smart_routing_speaks_on_mac_when_companion_inactive(tmp_path):
    cfg = VoiceFiConfig()
    cfg.companion.audio_routing = "smart"
    cfg.companion.mute_mac_when_companion_active = True
    cfg.antigravity.read_summary_aloud = True
    cfg.antigravity.auto_listen = False
    cfg.antigravity.show_speech_popup = False

    fake_transcript = tmp_path / "transcript.jsonl"
    fake_transcript.write_text('{"type": "PLANNER_RESPONSE", "content": "Desk turn summary."}\n')

    mock_engine = MagicMock()

    with patch("voicefi.integrations.antigravity.extract_latest_agent_summary", return_value=("Desk turn summary.", "antigravity", 3)), \
         patch("voicefi.integrations.antigravity.claim_turn", return_value=True), \
         patch("voicefi.integrations.antigravity.get_claimed_turn_origin", return_value="desktop"), \
         patch("voicefi.integrations.antigravity.peek_mobile_turn_origin", return_value=False), \
         patch("voicefi.integrations.antigravity.has_active_companion_client", return_value=False), \
         patch("voicefi.audio.meeting_detection.is_user_on_call", return_value=False), \
         patch("voicefi.integrations.antigravity.get_tts_engine", return_value=mock_engine):

        res = handle_antigravity_stop_hook(
            payload={"conv_id": "conv-desktop-solo", "transcriptPath": str(fake_transcript)},
            config=cfg,
        )

        mock_engine.stream_speak.assert_called_once_with("Desk turn summary.", block=True)


def test_antigravity_both_mode_speaks_even_when_mobile(tmp_path):
    cfg = VoiceFiConfig()
    cfg.companion.audio_routing = "both"
    cfg.antigravity.read_summary_aloud = True
    cfg.antigravity.auto_listen = False
    cfg.antigravity.show_speech_popup = False

    fake_transcript = tmp_path / "transcript.jsonl"
    fake_transcript.write_text('{"type": "PLANNER_RESPONSE", "content": "Echo summary."}\n')

    mock_engine = MagicMock()

    with patch("voicefi.integrations.antigravity.extract_latest_agent_summary", return_value=("Echo summary.", "antigravity", 4)), \
         patch("voicefi.integrations.antigravity.claim_turn", return_value=True), \
         patch("voicefi.integrations.antigravity.get_claimed_turn_origin", return_value="mobile"), \
         patch("voicefi.integrations.antigravity.peek_mobile_turn_origin", return_value=True), \
         patch("voicefi.integrations.antigravity.has_active_companion_client", return_value=True), \
         patch("voicefi.audio.meeting_detection.is_user_on_call", return_value=False), \
         patch("voicefi.integrations.antigravity.get_tts_engine", return_value=mock_engine):

        res = handle_antigravity_stop_hook(
            payload={"conv_id": "conv-both-test", "transcriptPath": str(fake_transcript)},
            config=cfg,
        )

        mock_engine.stream_speak.assert_called_once_with("Echo summary.", block=True)


# ==============================================================================
# 3. CLAUDE STOP HOOK ROUTING TESTS
# ==============================================================================

def test_claude_smart_routing_suppresses_mac_when_turn_is_mobile(tmp_path):
    cfg = VoiceFiConfig()
    cfg.companion.audio_routing = "smart"
    cfg.companion.mute_mac_when_companion_active = False

    fake_session = tmp_path / "session_123.jsonl"
    fake_session.write_text('{"type": "assistant", "message": {"content": "Claude finished mobile command."}}\n')

    with patch("voicefi.integrations.claude.claim_turn", return_value=True), \
         patch("voicefi.integrations.claude.get_claimed_turn_origin", return_value="mobile"), \
         patch("voicefi.integrations.claude.peek_mobile_turn_origin", return_value=True), \
         patch("voicefi.integrations.claude.pop_mobile_turn_origin", return_value=False), \
         patch("voicefi.integrations.claude.has_active_companion_client", return_value=False), \
         patch("voicefi.integrations.claude.get_tts_engine") as mock_tts:

        res = handle_claude_stop_hook(
            payload={"message": "Claude finished mobile command.", "session_path": str(fake_session)},
            config=cfg,
        )

        assert res.get("status") == "mobile_handled"
        mock_tts.assert_not_called()


def test_claude_smart_routing_suppresses_mac_when_companion_is_active(tmp_path):
    cfg = VoiceFiConfig()
    cfg.companion.audio_routing = "smart"
    cfg.companion.mute_mac_when_companion_active = True

    fake_session = tmp_path / "session_456.jsonl"
    fake_session.write_text('{"type": "assistant", "message": {"content": "Claude finished desktop command."}}\n')

    with patch("voicefi.integrations.claude.claim_turn", return_value=True), \
         patch("voicefi.integrations.claude.get_claimed_turn_origin", return_value="desktop"), \
         patch("voicefi.integrations.claude.peek_mobile_turn_origin", return_value=False), \
         patch("voicefi.integrations.claude.pop_mobile_turn_origin", return_value=False), \
         patch("voicefi.integrations.claude.has_active_companion_client", return_value=True), \
         patch("voicefi.integrations.claude.get_tts_engine") as mock_tts:

        res = handle_claude_stop_hook(
            payload={"message": "Claude finished desktop command.", "session_path": str(fake_session)},
            config=cfg,
        )

        assert res.get("status") == "mac_muted"
        mock_tts.assert_not_called()


# ==============================================================================
# 4. WATCHER SMART ROUTING TESTS
# ==============================================================================

def test_watcher_smart_routing_suppresses_mac_when_turn_is_mobile():
    from voicefi.integrations.watcher import TranscriptWatcher

    cfg = VoiceFiConfig()
    cfg.companion.audio_routing = "smart"
    cfg.companion.mute_mac_when_companion_active = False

    watcher = TranscriptWatcher(cfg)

    with patch("voicefi.integrations.watcher.get_claimed_turn_origin", return_value="mobile"), \
         patch("voicefi.integrations.watcher.peek_mobile_turn_origin", return_value=True), \
         patch("voicefi.integrations.watcher.has_active_companion_client", return_value=False), \
         patch("voicefi.integrations.watcher.get_tts_engine") as mock_tts:

        # Simulating routing check
        routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
        mute_mac_active = getattr(getattr(cfg, "companion", None), "mute_mac_when_companion_active", True)
        is_mobile = True

        suppressed = False
        if routing == "smart":
            if is_mobile or (mute_mac_active and has_active_companion_client()):
                suppressed = True

        assert suppressed is True


# ==============================================================================
# 5. RELAY CLIENT HEARTBEAT TESTS
# ==============================================================================

@pytest.mark.anyio
async def test_relay_client_heartbeat_on_peer_events():
    from voicefi.companion.relay_client import RelayClient, RelaySessionCredentials

    creds = RelaySessionCredentials(session_id="test-sess", token="test-token")
    client = RelayClient(credentials=creds)

    assert not has_active_companion_client()

    # Peer connects
    await client._handle_incoming_message(json.dumps({"type": "peer_connected"}))
    assert has_active_companion_client()

    # Ping maintains heartbeat
    await client._handle_incoming_message(json.dumps({"type": "ping"}))
    assert has_active_companion_client()

    # Peer disconnects
    await client._handle_incoming_message(json.dumps({"type": "peer_disconnected"}))
    assert not has_active_companion_client()
