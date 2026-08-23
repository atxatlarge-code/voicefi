"""
Unit tests for Acoustic Echo Cancellation and Self-Hearing Prevention.
"""

import time
import pytest
from voicefi.audio.echo_canceller import (
    record_agent_spoken,
    get_recent_spoken_texts,
    clear_agent_spoken_history,
    is_acoustic_echo,
)


@pytest.fixture(autouse=True)
def clean_history():
    """Clear spoken history before and after each test."""
    clear_agent_spoken_history()
    yield
    clear_agent_spoken_history()


def test_record_and_get_recent_spoken():
    """Verify recording spoken text stores history and retrieves within window."""
    record_agent_spoken("Stage on Railway or ship straightaway?")
    texts = get_recent_spoken_texts(max_age_seconds=10.0)
    assert len(texts) >= 1
    assert "Stage on Railway or ship straightaway?" in texts


def test_exact_echo_detection():
    """Verify exact transcript match is detected as acoustic echo."""
    agent_msg = "Done! The designs are now ready."
    record_agent_spoken(agent_msg)

    assert is_acoustic_echo("Done! The designs are now ready.") is True
    assert is_acoustic_echo("done the designs are now ready") is True


def test_substring_and_phrase_echo_detection():
    """Verify partial phrases of agent questions are detected as echoes."""
    agent_msg = "Stage on Railway or ship straightaway?"
    record_agent_spoken(agent_msg)

    # Substring matches
    assert is_acoustic_echo("Stage on Railway") is True
    assert is_acoustic_echo("ship straightaway") is True
    assert is_acoustic_echo("railway or ship straightaway") is True


def test_word_overlap_echo_detection():
    """Verify transcripts with heavy token overlap (>50%) are detected as echoes."""
    agent_msg = "I have finalized the database migration and user auth middleware."
    record_agent_spoken(agent_msg)

    assert is_acoustic_echo("database migration and user auth middleware") is True
    assert is_acoustic_echo("finalized database migration user auth") is True


def test_legitimate_user_speech_not_filtered():
    """Verify user developer commands are not mistakenly classified as echo."""
    agent_msg = "Stage on Railway or ship straightaway?"
    record_agent_spoken(agent_msg)

    # Distinct user instructions
    assert is_acoustic_echo("Run full test suite") is False
    assert is_acoustic_echo("Deploy to staging now") is False
    assert is_acoustic_echo("Scaffold JWT middleware") is False
    assert is_acoustic_echo("Check system health") is False
    assert is_acoustic_echo("Summarize git commits") is False


def test_explicit_reference_text():
    """Verify passing direct reference_text argument works without global history."""
    clear_agent_spoken_history()
    prompt = "Would you like me to push the changes to origin main?"

    assert is_acoustic_echo("push the changes to origin main", reference_text=prompt) is True
    assert is_acoustic_echo("delete temporary files", reference_text=prompt) is False


def test_expired_echo_window():
    """Verify spoken texts outside the max_age_seconds window expire."""
    record_agent_spoken("Old prompt from several minutes ago.")

    # With max_age_seconds=0, history is considered expired
    assert is_acoustic_echo("Old prompt from several minutes ago.", max_age_seconds=0.0) is False
