import json
from pathlib import Path
from unittest.mock import MagicMock

from voicefi.config import VoiceFiConfig
from voicefi.integrations.watcher import TranscriptWatcher


def test_watcher_suppresses_working_and_thinking_by_default(tmp_path: Path):
    """Verify that TranscriptWatcher does not notify 'working' or 'thinking' line items by default."""
    cfg = VoiceFiConfig()
    assert cfg.hud.show_working_steps is False

    events = []

    def mock_notify(state, **kwargs):
        events.append((state, kwargs))

    watcher = TranscriptWatcher(config=cfg, on_state_change=mock_notify)

    tfile = tmp_path / "transcript.jsonl"
    with open(tfile, "w", encoding="utf-8") as f:
        # Tool call
        f.write(
            json.dumps({
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "source": "MODEL",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "pytest"}}],
            })
            + "\n"
        )
        # Command output
        f.write(
            json.dumps({
                "step_index": 2,
                "type": "GENERIC",
                "source": "SYSTEM",
                "content": "Running test suite...",
            })
            + "\n"
        )
        # Background task
        f.write(
            json.dumps({
                "step_index": 3,
                "type": "SYSTEM_MESSAGE",
                "source": "SYSTEM",
                "content": 'Task id "task-1" finished with result: OK',
            })
            + "\n"
        )
        # Thinking
        f.write(
            json.dumps({
                "step_index": 4,
                "type": "PLANNER_RESPONSE",
                "source": "MODEL",
                "thinking": "Analyzing code changes...",
            })
            + "\n"
        )
        # User input (should still be processed!)
        f.write(
            json.dumps({
                "step_index": 5,
                "type": "USER_INPUT",
                "source": "USER_EXPLICIT",
                "content": "Please check the status.",
            })
            + "\n"
        )

    watcher._processed_steps[str(tfile)] = 0
    watcher._file_offsets[str(tfile)] = 0
    watcher._check_transcript_update(tfile)

    # Only USER_INPUT should trigger an event
    assert len(events) == 1
    state, kwargs = events[0]
    assert state == "user_prompt"
    assert "Please check the status." in kwargs.get("prompt", "")
    assert watcher._processed_steps[str(tfile)] == 5


def test_watcher_emits_working_and_thinking_when_enabled(tmp_path: Path):
    """Verify that TranscriptWatcher emits 'working' and 'thinking' when show_working_steps is True."""
    cfg = VoiceFiConfig()
    cfg.hud.show_working_steps = True

    events = []

    def mock_notify(state, **kwargs):
        events.append((state, kwargs))

    watcher = TranscriptWatcher(config=cfg, on_state_change=mock_notify)

    tfile = tmp_path / "transcript.jsonl"
    with open(tfile, "w", encoding="utf-8") as f:
        f.write(
            json.dumps({
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "source": "MODEL",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "pytest"}}],
            })
            + "\n"
        )
        f.write(
            json.dumps({
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "source": "MODEL",
                "thinking": "Planning next step...",
            })
            + "\n"
        )

    watcher._processed_steps[str(tfile)] = 0
    watcher._file_offsets[str(tfile)] = 0
    watcher._check_transcript_update(tfile)

    assert len(events) == 2
    assert events[0][0] == "working"
    assert events[1][0] == "thinking"
