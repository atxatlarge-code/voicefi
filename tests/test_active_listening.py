"""
Unit and integration tests for Active Listening, Mic Check Short-Circuiting,
VAD Speech Onset Qualification, and Stateful Pending Question Disambiguation.
"""

from pathlib import Path
import pytest
import json
import time

from voicefi.integrations.active_listening import (
    ActiveListeningEngine,
    SpokenIntentCategory,
    ActiveListeningResult,
)
from voicefi.integrations.conversations import (
    set_pending_question,
    get_pending_question,
    resolve_pending_question,
    clear_pending_question,
    extract_choice_options,
    claim_turn,
)


class TestActiveListeningEngine:
    """Test acoustic safety, mic check detection, and intent filtering."""

    def test_mic_check_detection_and_reassurance_reply(self):
        cases = [
            "okay can you hear me",
            "can you hear me?",
            "you hear me",
            "mic check",
            "mic check 1 2 3",
            "check check check check check check check check",
            "testing one two three",
            "audio check",
        ]
        for phrase in cases:
            res = ActiveListeningEngine.evaluate(phrase, is_ambient=False)
            assert res.category == SpokenIntentCategory.MIC_CHECK
            assert res.is_actionable is False
            assert res.quick_spoken_reply is not None
            assert "loud and clear" in res.quick_spoken_reply.lower()

    def test_mic_check_in_ambient_mode_is_quietly_ignored(self):
        res = ActiveListeningEngine.evaluate("okay can you hear me", is_ambient=True)
        assert res.category == SpokenIntentCategory.MIC_CHECK
        assert res.is_actionable is False
        assert res.quick_spoken_reply is None

    def test_mic_check_with_active_pending_question(self):
        pending_q = {
            "question_text": "Stage on Railway or ship straightaway?",
            "options": ["stage on railway", "ship straightaway"],
        }
        res = ActiveListeningEngine.evaluate("okay can you hear me", pending_question=pending_q, is_ambient=False)
        assert res.category == SpokenIntentCategory.MIC_CHECK
        assert res.is_actionable is False
        assert "Stage on Railway or ship straightaway?" in res.quick_spoken_reply

    def test_conversational_filler_filtering(self):
        fillers = [
            "okay nice that sounds great",
            "sounds good",
            "sounds great",
            "looks good",
            "perfect",
            "thanks",
            "cool",
        ]
        for f in fillers:
            res = ActiveListeningEngine.evaluate(f, is_ambient=False)
            assert res.category == SpokenIntentCategory.CONVERSATIONAL_FILLER
            assert res.is_actionable is False

    def test_pending_choice_matching_with_affirmatory_lead_in(self):
        pending_q = {
            "question_text": "Stage on Railway or ship straightaway?",
            "options": ["stage on railway", "ship straightaway"],
        }

        # Scenario: "Looks great, deploy to staging now" -> matches "stage on railway"
        res = ActiveListeningEngine.evaluate(
            "Looks great, deploy to staging now",
            pending_question=pending_q,
            is_ambient=False,
        )
        assert res.category == SpokenIntentCategory.PENDING_ANSWER
        assert res.is_actionable is True
        assert res.selected_option == "stage on railway"

        # Scenario: "Ship straightaway"
        res2 = ActiveListeningEngine.evaluate(
            "Ship straightaway",
            pending_question=pending_q,
            is_ambient=False,
        )
        assert res2.category == SpokenIntentCategory.PENDING_ANSWER
        assert res2.is_actionable is True
        assert res2.selected_option == "ship straightaway"

    def test_actionable_dev_commands(self):
        commands = [
            "run pie test on tests auth",
            "scaffold a user profile route",
            "fix the css padding on header",
        ]
        for cmd in commands:
            res = ActiveListeningEngine.evaluate(cmd, is_ambient=False)
            assert res.category == SpokenIntentCategory.ACTIONABLE_COMMAND
            assert res.is_actionable is True


class TestPendingQuestionTracker:
    """Test extracting choices and storing pending question state."""

    def test_extract_choice_options(self):
        assert extract_choice_options("Stage on Railway or ship straightaway?") == [
            "stage on railway",
            "ship straightaway",
        ]
        assert extract_choice_options('Choose "Staging" or "Production"') == [
            "staging",
            "production",
        ]
        assert extract_choice_options("Would you like to deploy to staging or run tests first?") == [
            "deploy to staging",
            "run tests first",
        ]

    def test_set_get_and_resolve_pending_question(self, tmp_path, monkeypatch):
        qfile = tmp_path / "pending_q.json"
        monkeypatch.setattr("voicefi.integrations.conversations._PENDING_QUESTIONS_FILE", qfile)

        cid = "test-session-42"
        set_pending_question(cid, "Stage on Railway or ship straightaway?")

        pending = get_pending_question(cid)
        assert pending is not None
        assert pending["status"] == "pending"
        assert pending["options"] == ["stage on railway", "ship straightaway"]

        resolve_pending_question(cid, selected_option="stage on railway")
        updated = json.loads(qfile.read_text())
        assert updated[cid]["status"] == "answered"
        assert updated[cid]["resolved_option"] == "stage on railway"

        clear_pending_question(cid)
        assert get_pending_question(cid) is None


class TestTurnDeduplicationAndLocking:
    """Verify cross-process turn claim atomic locking."""

    def test_claim_turn_deduplication(self, tmp_path, monkeypatch):
        turn_file = tmp_path / "active_turns.json"
        lock_file = tmp_path / "active_turns.lock"
        monkeypatch.setattr("voicefi.integrations.conversations.Path", lambda p: turn_file if "active_turns.json" in str(p) else lock_file if "active_turns.lock" in str(p) else Path(p))

        sig1 = "conv-123:I have created the implementation"
        sig2 = "conv-123:I have created the implementation"
        sig_alt_prefix = ":I have created the implementation"

        assert claim_turn("conv-123", sig1) is True
        # Second identical claim within 60s should be rejected
        assert claim_turn("conv-123", sig2) is False
        # Normalized text match should also be rejected even with different conv_id prefix
        assert claim_turn("", sig_alt_prefix) is False
