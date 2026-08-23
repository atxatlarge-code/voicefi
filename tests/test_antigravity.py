"""Unit tests for Antigravity transcript parsing and markdown speech cleaner."""

import json
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

    mock_inject = MagicMock()
    monkeypatch.setattr("voicefi.integrations.antigravity.inject_text_to_active_app", mock_inject)
    monkeypatch.setattr("voicefi.integrations.antigravity.claim_turn", lambda cid, sig: True)

    payload = {"conversationId": "test-123", "transcriptPath": str(tfile)}
    handle_antigravity_stop_hook(payload, config=cfg)

    mock_inject.assert_called_once_with("Run the tests next", submit_enter=True, target_antigravity=True)

