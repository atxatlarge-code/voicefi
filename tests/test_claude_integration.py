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


def test_install_claude_hook(tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"env": {"FOO": "BAR"}}))

    target = install_claude_hook(settings_path=settings_file, bin_path="/custom/bin/vifi")
    assert target == settings_file

    with open(settings_file, "r") as f:
        data = json.load(f)

    assert "hooks" in data
    assert "Stop" in data["hooks"]
    stop_hooks = data["hooks"]["Stop"]
    assert len(stop_hooks) >= 1
    assert any("vifi hook --agent claude" in str(h) for h in stop_hooks)
    # Check that existing settings were preserved
    assert data["env"]["FOO"] == "BAR"


def test_handle_claude_stop_hook(tmp_path):
    cfg = VoiceFiConfig()
    cfg.antigravity.auto_listen = False  # Only test TTS part

    mock_tts = MagicMock()
    with patch("voicefi.integrations.claude.get_tts_engine", return_value=mock_tts):
        payload = {"message": "All unit tests passed successfully."}
        result = handle_claude_stop_hook(payload, cfg)

        assert result["status"] == "spoken"
        assert result["agent"] == "claude"
        mock_tts.speak.assert_called_once_with("All unit tests passed successfully.", block=True)
