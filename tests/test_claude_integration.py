import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from voicefi.config import VoiceFiConfig
from voicefi.integrations.claude import (
    find_latest_claude_session,
    extract_latest_claude_summary,
    install_claude_hook,
    handle_claude_stop_hook,
)


def test_find_latest_claude_session(tmp_path):
    projects_dir = tmp_path / "projects" / "test-project"
    projects_dir.mkdir(parents=True)

    session_1 = projects_dir / "session-1.jsonl"
    session_2 = projects_dir / "session-2.jsonl"

    session_1.write_text('{"type": "user", "message": {"content": "hello"}}\n')
    session_2.write_text('{"type": "user", "message": {"content": "world"}}\n')

    # Update mtime of session_2 so it is newer
    session_2.touch()

    found = find_latest_claude_session(base_dir=tmp_path)
    assert found == session_2


def test_extract_latest_claude_summary(tmp_path):
    session_file = tmp_path / "session.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Run the tests"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "### Test Results\n\nAll unit tests passed with 100% coverage! Would you like me to deploy to production now?",
                    }
                ],
            },
        },
    ]
    with open(session_file, "w") as f:
        for l in lines:
            f.write(json.dumps(l) + "\n")

    summary = extract_latest_claude_summary(session_path=session_file, max_words=30)
    assert "Would you like me to deploy to production now?" in summary
    assert "###" not in summary


def test_install_claude_hook_backup_and_preservation(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"env": {"FOO": "BAR"}}))

    target = install_claude_hook(settings_path=settings_file, bin_path="/custom/bin/vifi")
    assert target == settings_file

    # Check that backup file was created
    backup_file = tmp_path / "settings.json.bak"
    assert backup_file.is_file()
    assert "FOO" in backup_file.read_text()

    with open(settings_file, "r") as f:
        data = json.load(f)

    assert "hooks" in data
    assert "Stop" in data["hooks"]
    stop_hooks = data["hooks"]["Stop"]
    assert len(stop_hooks) >= 1
    assert any("vifi hook --agent claude" in str(h) for h in stop_hooks)
    # Check that existing settings were preserved
    assert data["env"]["FOO"] == "BAR"


def test_handle_claude_stop_hook_recursive_guard():
    payload = {"stop_hook_active": True}
    result = handle_claude_stop_hook(payload)
    assert result["status"] == "skipped_recursive"


def test_handle_claude_stop_hook_paused_guard():
    cfg = VoiceFiConfig()
    cfg.enabled = False
    payload = {"message": "Test message"}
    result = handle_claude_stop_hook(payload, cfg)
    assert result["status"] == "paused"


def test_handle_claude_stop_hook_auto_submit_false(tmp_path):
    cfg = VoiceFiConfig()
    cfg.claude.auto_listen = True
    cfg.claude.auto_submit = False
    cfg.claude.inject_to_active_window = True
    cfg.audio_cues.enabled = False

    mock_tts = MagicMock()
    mock_recorder = MagicMock()
    fake_wav = tmp_path / "test.wav"
    fake_wav.write_text("audio")
    mock_recorder.record_speech_auto.return_value = (b"data", fake_wav)

    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "git status and run tests"

    with patch("voicefi.integrations.claude.get_tts_engine", return_value=mock_tts), \
         patch("voicefi.integrations.claude.AudioRecorder", return_value=mock_recorder), \
         patch("voicefi.integrations.claude.get_stt_engine", return_value=mock_stt), \
         patch("voicefi.integrations.claude.inject_text_to_claude") as mock_inject, \
         patch("voicefi.integrations.claude.claim_turn", return_value=True):

        payload = {"message": "Claude is ready."}
        result = handle_claude_stop_hook(payload, cfg)

        assert result["status"] == "transcribed"
        assert result["text"] == "git status and run tests"
        # Verify submit_enter is False when cfg.claude.auto_submit is False
        mock_inject.assert_called_once_with("git status and run tests", submit_enter=False)


def test_handle_claude_stop_hook_direct_injection(tmp_path):
    cfg = VoiceFiConfig()
    cfg.claude.auto_listen = True
    cfg.claude.auto_submit = True
    cfg.claude.inject_to_active_window = True
    cfg.audio_cues.enabled = False

    mock_tts = MagicMock()
    mock_recorder = MagicMock()
    fake_wav = tmp_path / "test.wav"
    fake_wav.write_text("audio")
    mock_recorder.record_speech_auto.return_value = (b"data", fake_wav)

    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "check the database migration"

    with patch("voicefi.integrations.claude.get_tts_engine", return_value=mock_tts), \
         patch("voicefi.integrations.claude.AudioRecorder", return_value=mock_recorder), \
         patch("voicefi.integrations.claude.get_stt_engine", return_value=mock_stt), \
         patch("voicefi.integrations.claude.inject_text_to_claude") as mock_inject, \
         patch("voicefi.integrations.claude.claim_turn", return_value=True):

        payload = {"message": "Claude finished."}
        result = handle_claude_stop_hook(payload, cfg)

        assert result["status"] == "transcribed"
        assert result["text"] == "check the database migration"
        mock_inject.assert_called_once_with("check the database migration", submit_enter=True)

