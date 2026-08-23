"""
Unit and integration tests for Voice Memo Buffer and Stream-of-Consciousness Synthesizer.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from voicefi.config import VoiceFiConfig
from voicefi.memo.models import (
    MemoChunk,
    MemoRecording,
    CleanedMemo,
    SynthesizedMemo,
    MemoStore,
)
from voicefi.memo.cleaner import MemoCleaner
from voicefi.memo.recorder import MemoBufferRecorder
from voicefi.memo.synthesizer import MemoSynthesizer
from voicefi.cli import cmd_memo


def test_memo_models_and_markdown():
    """Test data models serialization and markdown rendering."""
    memo = CleanedMemo(
        memo_id="test1234",
        title="Background Video Worker",
        duration_seconds=120.0,
        raw_transcript="Um so I am thinking we need a video worker. Let's use SQLite queue.",
        cleaned_transcript="So I am thinking we need a video worker. Let's use SQLite queue.",
        word_count=13,
    )

    md = memo.to_markdown()

    assert "# 🎙️ Voice Memo: Background Video Worker" in md
    assert "ID: `test1234`" in md
    assert "## 📝 Cleaned Transcript" in md
    assert "So I am thinking we need a video worker" in md
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

    cleaner = MemoCleaner()
    memo = cleaner.process(rec.raw_transcript, memo_id="memo001", custom_title=rec.title)

    memo_dir = store.save_memo(rec, memo)
    assert memo_dir.is_dir()
    assert (memo_dir / "recording.json").is_file()
    assert (memo_dir / "memo.json").is_file()
    assert (memo_dir / "memo.md").is_file()

    # Load by ID
    loaded_rec, loaded_memo = store.get_memo("memo001")
    assert loaded_rec is not None
    assert loaded_rec.id == "memo001"
    assert loaded_rec.title == "Payment Gateway Integration"
    assert loaded_memo is not None
    assert loaded_memo.memo_id == "memo001"

    # Load by prefix
    prefix_rec, _ = store.get_memo("memo0")
    assert prefix_rec is not None
    assert prefix_rec.id == "memo001"

    # List memos
    memos_list = store.list_memos()
    assert len(memos_list) == 1
    assert memos_list[0]["id"] == "memo001"
    assert memos_list[0]["has_cleaned_memo"] is True
    assert memos_list[0]["has_synthesis"] is True

    # Delete memo
    assert store.delete_memo("memo001") is True
    assert store.get_memo("memo001") is None
    assert len(store.list_memos()) == 0


def test_cleaner_disfluencies_and_fidelity():
    """Test non-destructive cleaner removes true disfluencies while preserving developer meaning."""
    cleaner = MemoCleaner()

    raw_text = "Um, so basically, uh, I think we should, like, add an API endpoint GET /metrics. We we need redis caching."
    cleaned = cleaner.clean_transcript(raw_text)

    # Disfluencies stripped
    assert "um" not in cleaned.lower()
    assert "uh" not in cleaned.lower()
    # Stutter collapsed
    assert "We need" in cleaned or "we need" in cleaned
    # Semantic words preserved
    assert "basically" in cleaned.lower()
    assert "like" in cleaned.lower()
    assert "GET /metrics" in cleaned


def test_cleaner_title_inference():
    """Test title inference from speech."""
    cleaner = MemoCleaner()

    title1 = cleaner.infer_title("I'm thinking we should build a real-time event pipeline for telemetry.")
    assert "Real-Time Event" in title1 or "Event" in title1

    title2 = cleaner.infer_title("Random text", custom_title="Custom Feature Plan")
    assert title2 == "Custom Feature Plan"


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
        with patch("voicefi.audio.chimes.play_chime"):
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
    with patch("voicefi.memo.models.get_memos_dir", return_value=tmp_path):
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
        assert "Cleaned Transcript" in captured.out

        # 4. Delete memo
        args_del = MagicMock()
        args_del.config = None
        args_del.memo_action = "delete"
        args_del.memo_id = mid

        cmd_memo(args_del)
        captured = capsys.readouterr()
        assert f"Deleted voice memo `{mid}`" in captured.out
        assert len(store.list_memos()) == 0
