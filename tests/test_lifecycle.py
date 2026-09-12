"""
Unit tests for VoiceFi progressive lifecycle reminders & milestone engine.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from voicefi.lifecycle import (
    load_lifecycle_state,
    save_lifecycle_state,
    is_in_quiet_hours,
    can_deliver_nudge,
    record_nudge_delivered,
    check_and_trigger_lifecycle_nudges,
)


def test_lifecycle_state_persistence(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    state = load_lifecycle_state()
    assert "installed_at" in state
    assert state["delivered_nudges"] == []

    # Record a nudge
    record_nudge_delivered("test_nudge", state, now_ts=1000.0)
    reloaded = load_lifecycle_state()
    assert "test_nudge" in reloaded["delivered_nudges"]
    assert reloaded["last_notification_ts"] == 1000.0


def test_quiet_hours_logic():
    # 23:30 is in quiet hours (22:00 - 08:00)
    late_night = datetime(2026, 9, 11, 23, 30)
    assert is_in_quiet_hours(late_night) is True

    # 05:00 is in quiet hours
    early_morning = datetime(2026, 9, 11, 5, 0)
    assert is_in_quiet_hours(early_morning) is True

    # 14:00 is active working hours
    mid_day = datetime(2026, 9, 11, 14, 0)
    assert is_in_quiet_hours(mid_day) is False


def test_can_deliver_nudge_debounce():
    state = {
        "delivered_nudges": ["old_nudge"],
        "last_notification_ts": 10000.0,
    }

    # Already delivered
    assert can_deliver_nudge("old_nudge", state, now_ts=200000.0) is False

    # Within 24h of last notification (e.g. +2 hours)
    assert can_deliver_nudge("new_nudge", state, now_ts=17200.0, min_interval_hours=24.0) is False

    # After 24h (+25 hours)
    assert can_deliver_nudge("new_nudge", state, now_ts=100000.0, min_interval_hours=24.0) is True

    # Forced bypass
    assert can_deliver_nudge("old_nudge", state, now_ts=10000.0, force=True) is True


def test_first_hotkey_nudge_trigger(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    now = 10000.0
    state = {
        "installed_at": now - 1000.0,  # 16 mins ago (> 900s)
        "last_notification_ts": 0.0,
        "delivered_nudges": [],
        "trial_notified_days": [],
    }
    save_lifecycle_state(state)

    notifications_sent = []
    def mock_notify(title, subtitle="", message=""):
        notifications_sent.append((title, subtitle, message))

    monkeypatch.setattr("voicefi.lifecycle.show_notification", mock_notify)
    monkeypatch.setattr("voicefi.lifecycle.is_in_quiet_hours", lambda: False)

    delivered = check_and_trigger_lifecycle_nudges(
        now_ts=now,
        turns_override=0,
        ignore_quiet_hours=True,
    )

    assert delivered == "nudge_first_hotkey"
    assert len(notifications_sent) == 1
    assert "Control+T" in notifications_sent[0][2]


def test_turn_milestone_triggers(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    now = 200000.0
    state = {
        "installed_at": 10000.0,
        "last_notification_ts": 0.0,
        "delivered_nudges": ["nudge_first_hotkey", "nudge_first_turn_tips"],
        "trial_notified_days": [],
    }
    save_lifecycle_state(state)

    notifications_sent = []
    def mock_notify(title, subtitle="", message=""):
        notifications_sent.append((title, subtitle, message))

    monkeypatch.setattr("voicefi.lifecycle.show_notification", mock_notify)

    # 5 turns milestone
    delivered = check_and_trigger_lifecycle_nudges(
        now_ts=now,
        turns_override=5,
        ignore_quiet_hours=True,
    )

    assert delivered == "milestone_turn_5"
    assert "github.com/atxatlarge-code/voicefi" in notifications_sent[0][2]


def test_trial_countdown_nudge(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    now = 500000.0
    state = {
        "installed_at": 10000.0,
        "last_notification_ts": 0.0,
        "delivered_nudges": ["nudge_first_hotkey", "nudge_first_turn_tips"],
        "trial_notified_days": [],
    }
    save_lifecycle_state(state)

    notifications_sent = []
    def mock_notify(title, subtitle="", message=""):
        notifications_sent.append((title, subtitle, message))

    monkeypatch.setattr("voicefi.lifecycle.show_notification", mock_notify)

    from voicefi.config import VoiceFiConfig
    cfg = VoiceFiConfig()
    cfg.trial_started_at = now - (7 * 86400)  # Day 7

    delivered = check_and_trigger_lifecycle_nudges(
        config=cfg,
        now_ts=now,
        turns_override=2,
        trial_days_override=7,
        ignore_quiet_hours=True,
    )

    assert delivered == "trial_day_7"
    assert "7 Days Remaining" in notifications_sent[0][0]
