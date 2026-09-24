"""
Progressive Lifecycle Reminders, Educational Nudges & Milestone Engine for VoiceFi.
Schedules context-driven, non-spammy macOS Notification Center tips to guide developers
through hotkey discovery, power features (Speed Talking, Wake Word), milestone celebrations,
and respectful Pro trial countdowns.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from voicefi.config import load_config
from voicefi.license import FeatureGate
from voicefi.ui.notifications import show_notification


def is_headless() -> bool:
    """Check if running in headless testing environment."""
    return bool(
        os.getenv("VOICEFI_HEADLESS") == "1"
        or os.getenv("HEADLESS") == "1"
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("VOICEFI_TESTING") == "1"
    )


def get_lifecycle_file_path() -> Path:
    """Return Path to local lifecycle state JSON file."""
    return Path.home() / ".voicefi" / "lifecycle.json"


def load_lifecycle_state() -> Dict[str, Any]:
    """Load internal lifecycle state tracking dictionary."""
    path = get_lifecycle_file_path()
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Default initialized state
    now = time.time()
    state = {
        "installed_at": now,
        "last_notification_ts": 0.0,
        "delivered_nudges": [],
        "trial_notified_days": [],
    }
    save_lifecycle_state(state)
    return state


def save_lifecycle_state(state: Dict[str, Any]) -> None:
    """Save lifecycle state to ~/.voicefi/lifecycle.json atomically."""
    path = get_lifecycle_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except Exception as e:
        print(f"⚠️ [Lifecycle] Error saving state: {e}")


def is_in_quiet_hours(
    now_dt: Optional[datetime] = None,
    start_hour: int = 22,
    end_hour: int = 8,
) -> bool:
    """Check if the given local datetime falls within do-not-disturb hours."""
    dt = now_dt or datetime.now()
    hour = dt.hour
    if start_hour > end_hour:
        # e.g. 22:00 to 08:00
        return hour >= start_hour or hour < end_hour
    return start_hour <= hour < end_hour


def can_deliver_nudge(
    nudge_id: str,
    state: Dict[str, Any],
    now_ts: Optional[float] = None,
    min_interval_hours: float = 24.0,
    force: bool = False,
) -> bool:
    """
    Check if a nudge is eligible for delivery:
    1. Has not already been delivered.
    2. Respects the minimum sliding interval (default 24h between tips).
    """
    if force:
        return True

    delivered = state.get("delivered_nudges", [])
    if nudge_id in delivered:
        return False

    current_ts = now_ts or time.time()
    last_ts = state.get("last_notification_ts", 0.0)

    # Only enforce sliding interval if a prior notification was actually sent
    if last_ts > 0.0 and (current_ts - last_ts < (min_interval_hours * 3600.0)):
        return False

    return True


def record_nudge_delivered(
    nudge_id: str, state: Dict[str, Any], now_ts: Optional[float] = None
) -> None:
    """Record that a nudge was shown and update the last notification timestamp."""
    delivered = set(state.get("delivered_nudges", []))
    delivered.add(nudge_id)
    state["delivered_nudges"] = sorted(list(delivered))
    state["last_notification_ts"] = now_ts or time.time()
    save_lifecycle_state(state)


def check_and_trigger_lifecycle_nudges(
    config=None,
    now_ts: Optional[float] = None,
    turns_override: Optional[int] = None,
    trial_days_override: Optional[int] = None,
    force_nudge: Optional[str] = None,
    min_interval_hours: float = 24.0,
    ignore_quiet_hours: bool = False,
) -> Optional[str]:
    """
    Evaluate pending lifecycle rules against current usage and system state.
    Triggers at most one notification per evaluation cycle.
    Returns the ID of the delivered nudge, or None.
    """
    state = load_lifecycle_state()
    current_ts = now_ts or time.time()
    eval_dt = datetime.fromtimestamp(current_ts)

    # Respect quiet hours unless forced or ignored
    if not force_nudge and not ignore_quiet_hours and is_in_quiet_hours(eval_dt):
        return None

    # Resolve total spoken turns
    if turns_override is not None:
        total_turns = turns_override
    else:
        try:
            from voicefi.analytics.store import get_analytics_store

            store = get_analytics_store()
            total_turns = store.get_total_spoken_turns()
        except Exception:
            total_turns = 0

    cfg = config or load_config()
    tier_info = FeatureGate.get_tier_summary(cfg)
    is_trial = tier_info.get("is_trial", False) or (trial_days_override is not None)
    days_left = (
        trial_days_override
        if trial_days_override is not None
        else tier_info.get("trial_days_remaining", 14)
    )

    installed_at = state.get("installed_at", current_ts)
    elapsed_seconds = current_ts - installed_at

    # --- Rule Evaluation in Priority Order ---

    # 1. Milestone 25 Turns
    if (total_turns >= 25 or force_nudge == "milestone_turn_25") and can_deliver_nudge(
        "milestone_turn_25", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="⚡ Productivity Milestone: 25 Turns",
            subtitle="VoiceFi Analytics",
            message="You've saved ~20 minutes of gaze fatigue this week. Run 'vifi stats' to inspect your metrics!",
        )
        record_nudge_delivered("milestone_turn_25", state, current_ts)
        return "milestone_turn_25"

    # 2. Milestone 5 Turns (GitHub Star Celebration)
    if (total_turns >= 5 or force_nudge == "milestone_turn_5") and can_deliver_nudge(
        "milestone_turn_5", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="🎉 5 Spoken Agent Turns Completed!",
            subtitle="Pair Programming Hands-Free",
            message="Loving VoiceFi? Drop a star on GitHub to support open-source voice: github.com/atxatlarge-code/voicefi ⭐",
        )
        record_nudge_delivered("milestone_turn_5", state, current_ts)
        return "milestone_turn_5"

    # 3. Pro Trial Day 14 (Expiry / Fallback)
    if (is_trial and days_left <= 1 or force_nudge == "trial_day_14") and can_deliver_nudge(
        "trial_day_14", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="VoiceFi Pro Trial Ends Today 🎙️",
            subtitle="Free Forever Fallback Active",
            message="Your Pro trial concludes today. Upgrade to retain neural voices, or continue 100% free with local Apple Ava (0ms).",
        )
        record_nudge_delivered("trial_day_14", state, current_ts)
        return "trial_day_14"

    # 4. Pro Trial Day 11 (3 Days Remaining)
    if (is_trial and days_left <= 3 or force_nudge == "trial_day_11") and can_deliver_nudge(
        "trial_day_11", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="⏳ 3 Days Left on Pro Trial",
            subtitle="VoiceFi Developer Pro",
            message="Keep 20+ neural voices & cross-agent routing with Developer Pro ($9/mo). Local Community Core stays free forever.",
        )
        record_nudge_delivered("trial_day_11", state, current_ts)
        return "trial_day_11"

    # 5. Pro Trial Day 7 (Halfway Check-in)
    if (is_trial and days_left <= 7 or force_nudge == "trial_day_7") and can_deliver_nudge(
        "trial_day_7", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="✨ 7 Days Remaining on Pro Trial",
            subtitle="VoiceFi Developer Pro",
            message="All 20+ neural voices & cloud relays are unlocked. Run 'vifi tier' anytime to inspect your status.",
        )
        record_nudge_delivered("trial_day_7", state, current_ts)
        return "trial_day_7"

    # 6. Speed Talking Discovery (after 10 normal-speed turns)
    speed_cfg = getattr(cfg, "speed_talk", None)
    speed_enabled = getattr(speed_cfg, "enabled", False)
    if (
        total_turns >= 10 and not speed_enabled or force_nudge == "nudge_speed_talk"
    ) and can_deliver_nudge(
        "nudge_speed_talk", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="⚡ Save 40% of Listening Time",
            subtitle="VoiceFi Speed Talking",
            message="Accelerate agent speech (1.5x–2.5x) with zero pitch distortion. Run 'vifi speed-talk on' or click the menu bar.",
        )
        record_nudge_delivered("nudge_speed_talk", state, current_ts)
        return "nudge_speed_talk"

    # 7. Wake Word Discovery (Day 3 of usage)
    if (
        elapsed_seconds >= 2 * 86400 and total_turns >= 3 or force_nudge == "nudge_wakeword"
    ) and can_deliver_nudge(
        "nudge_wakeword", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="Hands-Free Wake Word 🗣️",
            subtitle="Say 'Hey Viv'",
            message="Summon the Quick Prompt Bar without touching your keyboard. Just say 'Hey Viv' or press Control+Space.",
        )
        record_nudge_delivered("nudge_wakeword", state, current_ts)
        return "nudge_wakeword"

    # 8. First Agent Turn Completion Tip
    if (total_turns >= 1 or force_nudge == "nudge_first_turn_tips") and can_deliver_nudge(
        "nudge_first_turn_tips", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="🎙️ Spoken Turn Active",
            subtitle="VoiceFi Shortcuts",
            message="Press Esc anytime to stop agent speech, or Option+Tab to jump straight to the active conversation window.",
        )
        record_nudge_delivered("nudge_first_turn_tips", state, current_ts)
        return "nudge_first_turn_tips"

    # 9. First Hotkey Reminder (15 minutes after install if 0 turns taken)
    if (
        elapsed_seconds >= 900 and total_turns == 0 or force_nudge == "nudge_first_hotkey"
    ) and can_deliver_nudge(
        "nudge_first_hotkey", state, current_ts, min_interval_hours, force=bool(force_nudge)
    ):
        show_notification(
            title="VoiceFi is Live & Ready 🎙️",
            subtitle="Universal Dictation Hotkey",
            message="Press Control+T in any editor, terminal, or browser to speak your prompt hands-free.",
        )
        record_nudge_delivered("nudge_first_hotkey", state, current_ts)
        return "nudge_first_hotkey"

    return None
