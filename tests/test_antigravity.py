"""Unit tests for Antigravity transcript parsing and markdown speech cleaner."""

import json
import os
from pathlib import Path
from voicefi.integrations.antigravity import clean_markdown_for_speech, extract_latest_agent_summary


def test_clean_markdown_strips_code_blocks():
    markdown = """
    I have created the files. Here is the code:
    ```python
    def hello():
        print("world")
    ```
    Would you like to run the test suite now?
    """
    cleaned = clean_markdown_for_speech(markdown, max_words=60)
    assert "def hello():" not in cleaned
    assert "Would you like to run the test suite now?" in cleaned


def test_clean_markdown_strips_links_and_headers():
    markdown = """
    # Project Update
    Please check [documentation](file:///Users/test/docs.md) and run `pytest`.
    """
    cleaned = clean_markdown_for_speech(markdown, max_words=60)
    assert "#" not in cleaned
    assert "file:///" not in cleaned
    assert "documentation" in cleaned
    assert "pytest" in cleaned


def test_extract_latest_agent_summary_from_transcript(tmp_path: Path):
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "Please implement feature X."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "I am working on feature X now."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Feature X has been implemented and tested successfully! What would you like to build next?"},
    ]

    with open(transcript_file, "w", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item) + "\n")

    summary = extract_latest_agent_summary(transcript_file, max_words=50)
    assert "Feature X has been implemented" in summary
    assert "What would you like to build next?" in summary


def test_session_cookie_handshake(tmp_path: Path, monkeypatch):
    from voicefi.integrations.conversations import save_session_cookie, load_session_cookie, ConversationTracker

    cookie_file = tmp_path / "active_session.json"
    monkeypatch.setattr("voicefi.integrations.conversations.get_session_cookie_path", lambda: cookie_file)

    test_conv_id = "test-conv-123456"
    test_title = "Feature Development Session"
    save_session_cookie(test_conv_id, title=test_title, transcript_path=str(tmp_path / "transcript.jsonl"))

    cookie = load_session_cookie()
    assert cookie is not None
    assert cookie["conversationId"] == test_conv_id
    assert cookie["title"] == test_title

    # Create dummy transcript so tracker can parse it
    tfile = tmp_path / test_conv_id / ".system_generated" / "logs" / "transcript.jsonl"
    tfile.parent.mkdir(parents=True, exist_ok=True)
    with open(tfile, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "USER_INPUT", "source": "USER", "content": "Help me build an app."}) + "\n")

    tracker = ConversationTracker(brain_dir=tmp_path)
    active = tracker.get_active_or_latest()
    assert active is not None
    assert active.id == test_conv_id


def test_handle_stop_hook_injects_with_target_antigravity(tmp_path: Path, monkeypatch):
    from voicefi.integrations.antigravity import handle_antigravity_stop_hook
    from voicefi.config import VoiceFiConfig
    from unittest.mock import MagicMock

    cfg = VoiceFiConfig()
    cfg.antigravity.read_summary_aloud = False
    cfg.antigravity.auto_listen = True
    cfg.antigravity.inject_to_active_window = True
    cfg.antigravity.show_speech_popup = False
    cfg.audio_cues.enabled = False

    tfile = tmp_path / "transcript.jsonl"
    with open(tfile, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "PLANNER_RESPONSE", "source": "MODEL", "status": "DONE", "content": "Done with task."}) + "\n")

    # Mock recorder and STT
    dummy_wav = tmp_path / "dummy.wav"
    dummy_wav.write_text("audio")
    monkeypatch.setattr("voicefi.integrations.antigravity.AudioRecorder.record_speech_auto", lambda self, *args, **kwargs: (None, dummy_wav))
    
    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "Run the tests next"
    monkeypatch.setattr("voicefi.integrations.antigravity.get_stt_engine", lambda cfg: mock_stt)

    mock_send = MagicMock(return_value=True)
    monkeypatch.setattr("voicefi.integrations.antigravity.send_message_to_antigravity", mock_send)
    monkeypatch.setattr("voicefi.integrations.antigravity.claim_turn", lambda cid, sig: True)

    payload = {"conversationId": "test-123", "transcriptPath": str(tfile)}
    handle_antigravity_stop_hook(payload, config=cfg)

    mock_send.assert_called_once_with(conv_id="test-123", text="Run the tests next")


def test_extract_latest_agent_summary_multi_turn_with_intermediate_tool_calls(tmp_path: Path):
    """Test extracting only the latest turn's model message across multi-turn sessions with tool calls."""
    transcript_file = tmp_path / "transcript.jsonl"
    lines = [
        # Turn 1
        {"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "Initialize repo."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Initializing repository."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "tool_calls": [{"name": "run_command", "args": {}}]},
        {"type": "GENERIC", "source": "MODEL", "content": "Git initialized."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Turn 1 complete. What next?"},
        # Turn 2
        {"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "Now add tests."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "tool_calls": [{"name": "run_command", "args": {}}]},
        {"type": "GENERIC", "source": "MODEL", "content": "Tests added."},
        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Turn 2 complete: All 5 tests passed!"},
    ]

    with open(transcript_file, "w", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item) + "\n")

    summary = extract_latest_agent_summary(transcript_file, max_words=50)
    assert "Turn 2 complete: All 5 tests passed!" in summary
    assert "Turn 1 complete" not in summary


def test_send_message_to_antigravity_cookie_resolution(tmp_path: Path, monkeypatch):
    """Test send_message_to_antigravity correctly resolves conv_id from session cookie with conversationId key."""
    from voicefi.integrations.injector import send_message_to_antigravity
    from unittest.mock import MagicMock

    cookie_file = tmp_path / "active_session.json"
    monkeypatch.setattr("voicefi.integrations.conversations.get_session_cookie_path", lambda: cookie_file)

    cookie_file.write_text(json.dumps({
        "conversationId": "session-xyz-987",
        "engine": "antigravity",
        "updatedAt": 1000.0,
    }))

    mock_run = MagicMock(returncode=0)
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_run)
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)
    monkeypatch.setattr("os.access", lambda path, mode: True)

    success = send_message_to_antigravity(conv_id=None, text="Hello Antigravity")
    assert success is True


def test_cmd_hook_unclosed_stdin_pipe(monkeypatch):
    """Test cmd_hook reads payload immediately without blocking on an unclosed stdin pipe."""
    import argparse
    import io
    from voicefi.cli import cmd_hook
    from unittest.mock import MagicMock

    args = argparse.Namespace(config=None, agent="antigravity")

    mock_handle = MagicMock(return_value={"decision": "allow"})
    monkeypatch.setattr("voicefi.cli.handle_antigravity_stop_hook", mock_handle)
    monkeypatch.setattr("voicefi.integrations.daemon_client.forward_hook_to_daemon", lambda *args, **kwargs: None)

    # Simulate stdin with select returning True
    pipe_r, pipe_w = os.pipe()
    try:
        os.write(pipe_w, b'{"conversationId": "pipe-conv-123"}\n')
        # Leave pipe_w open (do not close)

        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(os.fdopen(pipe_r, "rb")))
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        cmd_hook(args)
        mock_handle.assert_called_once()
        call_payload = mock_handle.call_args[0][0]
        assert call_payload.get("conversationId") == "pipe-conv-123"
    finally:
        try:
            os.close(pipe_w)
        except Exception:
            pass




