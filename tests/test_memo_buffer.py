"""
Unit and integration tests for Voice Memo Buffer and Stream-of-Consciousness Synthesizer.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from voicegency.config import VoicegencyConfig
from voicegency.memo.models import (
    MemoChunk,
    MemoRecording,
    ImplementationPlan,
    ImplementationStep,
    ProposedFileChange,
    ArchitecturalDiagram,
    PRChecklist,
    SynthesizedMemo,
    MemoStore,
)
from voicegency.memo.recorder import MemoBufferRecorder
from voicegency.memo.synthesizer import MemoSynthesizer
from voicegency.cli import cmd_memo


def test_memo_models_and_markdown():
    """Test data models serialization and markdown rendering."""
    plan = ImplementationPlan(
        goal_summary="Build background video worker",
        problem_context="Processing video thumbnails asynchronously",
        architectural_decisions=["Use SQLite queue instead of Redis", "Retry 3 times on failure"],
        proposed_files=[
            ProposedFileChange(action="NEW", path="src/worker.py", description="Worker daemon"),
            ProposedFileChange(action="MODIFY", path="src/models.py", description="State models"),
        ],
        steps=[
            ImplementationStep(
                step_number=1,
                title="Define Job Schemas",
                details="Add job status enum and table",
                target_files=["src/models.py"],
            ),
            ImplementationStep(
                step_number=2,
                title="Worker Queue",
                details="Consume tasks and process frames",
                target_files=["src/worker.py"],
            ),
        ],
    )

    diagram = ArchitecturalDiagram(
        diagram_type="graph TD",
        mermaid_code="graph TD\n    User --> API\n    API --> Worker",
        description="Architecture flow",
    )

    checklist = PRChecklist(
        core_tasks=["Implement worker loop", "Add POST /jobs endpoint"],
        testing_and_verification=["Add unit test for retry logic", "Verify 100% pass rate"],
        edge_cases_and_security=["Handle SIGINT cleanly", "Cleanup temp files"],
        documentation_and_ops=["Update README", "Add CLI command"],
    )

    synth = SynthesizedMemo(
        memo_id="test1234",
        title="Background Video Worker",
        executive_summary="Build an async video worker for thumbnails.",
        raw_transcript="So I am thinking we need a video worker. Actually wait, let's use SQLite queue.",
        key_requirements=["Need worker for video", "Extract frames with ffmpeg"],
        course_corrections=["Course correction: let's use SQLite queue"],
        implementation_plan=plan,
        architectural_diagram=diagram,
        pr_checklist=checklist,
    )

    md = synth.to_markdown()

    assert "# 🧠 Voice Memo: Background Video Worker" in md
    assert "ID: `test1234`" in md
    assert "## 📋 Executive Summary" in md
    assert "Course correction: let's use SQLite queue" in md
    assert "```mermaid" in md
    assert "graph TD" in md
    assert "## 🚀 Implementation Plan" in md
    assert "**[NEW]** `src/worker.py`" in md
    assert "## ✅ PR Checklist & Acceptance Criteria" in md
    assert "- [ ] Implement worker loop" in md
    assert "- [ ] Add unit test for retry logic" in md
    assert "## 🎙️ Raw Voice Transcript" in md


def test_memo_store_crud(tmp_path):
    """Test MemoStore saving, loading, listing, and deletion."""
    store = MemoStore(root_dir=tmp_path)

    rec = MemoRecording(
        id="memo001",
        title="Payment Gateway Integration",
        duration_seconds=124.5,
        target_duration_seconds=180.0,
        raw_transcript="We need Stripe webhooks handled securely with signature validation.",
        word_count=9,
    )

    synth = MemoSynthesizer().synthesize(rec.raw_transcript, memo_id="memo001", custom_title=rec.title)

    memo_dir = store.save_memo(rec, synth)
    assert memo_dir.is_dir()
    assert (memo_dir / "recording.json").is_file()
    assert (memo_dir / "synthesis.json").is_file()
    assert (memo_dir / "plan.md").is_file()

    # Load by ID
    loaded_rec, loaded_synth = store.get_memo("memo001")
    assert loaded_rec is not None
    assert loaded_rec.id == "memo001"
    assert loaded_rec.title == "Payment Gateway Integration"
    assert loaded_synth is not None
    assert loaded_synth.memo_id == "memo001"

    # Load by prefix
    prefix_rec, _ = store.get_memo("memo0")
    assert prefix_rec is not None
    assert prefix_rec.id == "memo001"

    # List memos
    memos_list = store.list_memos()
    assert len(memos_list) == 1
    assert memos_list[0]["id"] == "memo001"
    assert memos_list[0]["has_synthesis"] is True

    # Delete memo
    assert store.delete_memo("memo001") is True
    assert store.get_memo("memo001") is None
    assert len(store.list_memos()) == 0


def test_synthesizer_cleaning_and_entities():
    """Test thought synthesizer NLP parsing and entity detection."""
    synth = MemoSynthesizer()

    raw_text = "Um, so basically, uh, I think we should, like, add an API endpoint GET /metrics and store counters in sqlite. Actually wait, let's also cache in redis. We need pytest tests in test_metrics.py."

    cleaned = synth.clean_raw_rambles(raw_text)
    assert "um" not in cleaned.lower()
    assert "basically" not in cleaned.lower()

    corrections, _ = synth.detect_pivots_and_corrections(cleaned)
    assert len(corrections) >= 1
    assert "Course correction" in corrections[0]

    entities = synth.extract_technical_entities(cleaned)
    assert "sqlite" in entities["databases_and_storage"] or "redis" in entities["databases_and_storage"]
    assert "GET /metrics" in entities["api_endpoints"]
    assert "test_metrics.py" in entities["files"]


def test_synthesizer_full_generation():
    """Test full synthesis output generation."""
    synth = MemoSynthesizer()
    speech = "So I am thinking we need an async task queue. Tasks should be processed by background workers. We need POST /tasks and GET /tasks/:id. If it fails, retry 3 times. We need models.py and worker.py."

    res = synth.synthesize(speech, custom_title="Task Queue Engine")

    assert res.title == "Task Queue Engine"
    assert res.architectural_diagram is not None
    assert "graph TD" in res.architectural_diagram.mermaid_code
    assert len(res.implementation_plan.steps) >= 3
    assert len(res.pr_checklist.core_tasks) >= 1
    assert len(res.pr_checklist.testing_and_verification) >= 1


def test_memo_recorder_timer_formatting():
    """Test timer formatting and visual meter in MemoBufferRecorder."""
    rec = MemoBufferRecorder(target_duration_seconds=180.0)

    assert rec.format_time(65) == "01:05"
    assert rec.format_time(180) == "03:00"
    assert rec.format_time(300) == "05:00"

    meter_low = rec.render_meter(0.001)
    assert meter_low == "▱▱▱▱▱▱▱▱▱▱"

    meter_high = rec.render_meter(0.05)
    assert "▰" in meter_high


def test_memo_recorder_session_mock():
    """Test recorder session loop with mocked sounddevice stream."""
    rec = MemoBufferRecorder(target_duration_seconds=0.1)

    fake_chunk = np.zeros((800, 1), dtype="float32")

    mock_stream = MagicMock()
    mock_stream.read.return_value = (fake_chunk, False)
    mock_stream.__enter__.return_value = mock_stream
    mock_stream.__exit__.return_value = False

    ticks = []
    state_changes = []

    with patch("sounddevice.InputStream", return_value=mock_stream):
        with patch("voicegency.audio.chimes.play_chime"):
            audio, wav_path, duration = rec.record_memo_session(
                interactive=False,
                on_tick=lambda e, r, l: ticks.append((e, r)),
                on_state_change=lambda s: state_changes.append(s),
            )

            assert isinstance(audio, np.ndarray)
            assert wav_path.is_file()
            assert duration > 0.0
            assert "recording" in state_changes

            wav_path.unlink(missing_ok=True)


def test_cli_memo_synth_and_list(tmp_path, capsys):
    """Test CLI commands: synth, list, show, and delete."""
    with patch("voicegency.memo.models.get_memos_dir", return_value=tmp_path):
        # 1. Synthesize text via CLI
        args_synth = MagicMock()
        args_synth.config = None
        args_synth.memo_action = "synth"
        args_synth.memo_id = None
        args_synth.text = "We need an export CLI tool for markdown docs. Let's make sure it copies to clipboard."
        args_synth.file = None
        args_synth.title = "Markdown Export Tool"
        args_synth.out = None
        args_synth.clipboard = False

        cmd_memo(args_synth)
        captured = capsys.readouterr()
        assert "Markdown Export Tool" in captured.out
        assert "Implementation Plan" in captured.out

        # 2. List memos
        args_list = MagicMock()
        args_list.config = None
        args_list.memo_action = "list"
        args_list.limit = 10

        cmd_memo(args_list)
        captured = capsys.readouterr()
        assert "Markdown Export" in captured.out
        assert "✅ Yes" in captured.out

        # Get generated memo ID from store
        store = MemoStore(root_dir=tmp_path)
        memos = store.list_memos()
        assert len(memos) == 1
        mid = memos[0]["id"]

        # 3. Show memo
        args_show = MagicMock()
        args_show.config = None
        args_show.memo_action = "show"
        args_show.memo_id = mid
        args_show.transcript_only = False
        args_show.diagram_only = False
        args_show.checklist_only = False

        cmd_memo(args_show)
        captured = capsys.readouterr()
        assert "Executive Summary" in captured.out

        # 4. Delete memo
        args_del = MagicMock()
        args_del.config = None
        args_del.memo_action = "delete"
        args_del.memo_id = mid

        cmd_memo(args_del)
        captured = capsys.readouterr()
        assert f"Deleted voice memo `{mid}`" in captured.out
        assert len(store.list_memos()) == 0
