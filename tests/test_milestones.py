"""
Tests for VoiceFi turn milestone engine and GitHub Star / feedback prompts.
"""

import json
from pathlib import Path

from voicefi.telemetry import check_and_prompt_milestones


def test_milestone_not_triggered_under_five_turns(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    marker = fake_home / ".voicefi" / ".milestone_star_prompted"
    assert not marker.exists()

    # Under 5 turns
    triggered = check_and_prompt_milestones(turn_count_override=4)
    assert triggered is False
    assert not marker.exists()


def test_milestone_triggers_at_five_turns_and_is_idempotent(tmp_path, monkeypatch, capsys):
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    marker = fake_home / ".voicefi" / ".milestone_star_prompted"
    assert not marker.exists()

    events_captured = []

    def mock_record_event(evt, props=None):
        events_captured.append((evt, props))

    monkeypatch.setattr("voicefi.telemetry.record_event", mock_record_event)

    # 1. Trigger at 5 turns
    triggered = check_and_prompt_milestones(turn_count_override=5)
    assert triggered is True
    assert marker.exists()

    # Verify marker content
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["total_turns"] == 5
    assert data["milestone"] == "turn_5"

    # Verify event recorded
    milestone_events = [e for e in events_captured if e[0] == "milestone_turn_5"]
    assert len(milestone_events) == 1
    assert milestone_events[0][1]["total_turns"] == 5

    # Verify printed banner
    captured = capsys.readouterr()
    assert "Milestone: 5 Spoken Agent Turns Completed!" in captured.out
    assert "github.com/atxatlarge-code/voicefi" in captured.out

    # 2. Subsequent call (idempotency check)
    triggered_again = check_and_prompt_milestones(turn_count_override=6)
    assert triggered_again is False
    assert len([e for e in events_captured if e[0] == "milestone_turn_5"]) == 1


def test_stats_dashboard_footer_contains_star_prompt():
    from voicefi.analytics.terminal import format_stats_dashboard

    output = format_stats_dashboard(days=7)
    assert "Star on GitHub:" in output
    assert "https://github.com/atxatlarge-code/voicefi" in output
    assert "vifi feedback submit" in output
