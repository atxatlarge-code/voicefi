"""
Unit tests for Granola-style meeting note synthesis, alert word interception, and Obsidian routing.
"""

import pytest
from voicefi.config import VoiceFiConfig
from voicefi.memo.granola import GranolaSynthesizer
from voicefi.integrations.obsidian import save_meeting_note


class TestGranolaSynthesizer:
    def test_alert_word_interception_and_sanitization(self, monkeypatch):
        monkeypatch.setattr("voicefi.integrations.injector.send_message_to_agent", lambda **kwargs: None)
        synth = GranolaSynthesizer()
        raw = "We discussed the roadmap. VoiceFi, file an issue on token caching. Everyone agreed on Q4 delivery."

        # By default (strip_commands=False), verbatim transcript is preserved
        sanitized, dispatched = synth.intercept_and_sanitize(raw)
        assert "VoiceFi, file an issue" in sanitized
        assert "We discussed the roadmap" in sanitized
        assert "Everyone agreed on Q4 delivery" in sanitized
        assert len(dispatched) == 1
        assert "file an issue on token caching" in dispatched[0]

        # When strip_commands=True, command is stripped
        sanitized_stripped, dispatched_stripped = synth.intercept_and_sanitize(raw, strip_commands=True)
        assert "VoiceFi, file an issue" not in sanitized_stripped
        assert "We discussed the roadmap" in sanitized_stripped
        assert "Everyone agreed on Q4 delivery" in sanitized_stripped
        assert len(dispatched_stripped) == 1

    def test_vifi_alert_word_interception(self, monkeypatch):
        monkeypatch.setattr("voicefi.integrations.injector.send_message_to_agent", lambda **kwargs: None)
        synth = GranolaSynthesizer()
        raw = "Vi-Fi, dispatch a test run on auth module. The client was happy with progress."

        # By default, speech is preserved
        sanitized, dispatched = synth.intercept_and_sanitize(raw)
        assert "Vi-Fi, dispatch" in sanitized
        assert "The client was happy with progress." in sanitized
        assert len(dispatched) == 1
        assert "dispatch a test run on auth module" in dispatched[0]

        # When strip_commands=True, command is stripped
        sanitized_stripped, dispatched_stripped = synth.intercept_and_sanitize(raw, strip_commands=True)
        assert "Vi-Fi, dispatch" not in sanitized_stripped
        assert "The client was happy with progress." in sanitized_stripped
        assert len(dispatched_stripped) == 1

    def test_synthesize_meeting_markdown_structure(self, monkeypatch):
        monkeypatch.setattr("voicefi.integrations.injector.send_message_to_agent", lambda **kwargs: None)
        synth = GranolaSynthesizer()
        raw = "We reviewed the Q3 API budget. Vi-Fi, track this action item for Sarah. We approved the M5 chip upgrade."
        result = synth.synthesize_meeting(raw, title_hint="Q3 Review")

        assert "Executive Summary" in result.markdown
        assert "Action Items" in result.markdown
        assert "⚡ **Dispatched via VoiceFi**" in result.markdown
        assert "track this action item for Sarah" in result.markdown
        assert "Clean Transcript" in result.markdown
        assert "Vi-Fi, track this action item for Sarah" in result.markdown

    def test_save_meeting_note_to_obsidian_meetings_folder(self, tmp_path):
        cfg = VoiceFiConfig()
        cfg.obsidian.vault_path = str(tmp_path)
        cfg.obsidian.meetings_folder = "Meetings"

        res = save_meeting_note(
            "# 🎙️ 2026-09-30 - Client Standup\n\n## 📌 Summary\nGreat call.",
            title="Client Standup",
            vault_path=tmp_path,
            config=cfg,
        )

        assert res["status"] == "ok"
        expected_file = tmp_path / "Meetings" / "2026-09-30 - Client Standup.md"
        assert expected_file.is_file()
        content = expected_file.read_text(encoding="utf-8")
        assert "Client Standup" in content
