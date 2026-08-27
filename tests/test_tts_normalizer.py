"""
Unit tests for TTS Text & Phonetic Normalizer (Heteronym Disambiguation & Tech Jargon).
"""

import pytest
from voicefi.tts.normalizer import normalize_tts_text
from voicefi.integrations.antigravity import clean_markdown_for_speech


def test_heteronym_live_adjective_and_adverb():
    """Verify that adjective/adverb/tech uses of 'live' are normalized to /laɪv/ ('lyve')."""
    # Linking / state verbs
    assert "now lyve" in normalize_tts_text("The website is now live.")
    assert "is lyve" in normalize_tts_text("The website is live.")
    assert "was lyve" in normalize_tts_text("The server was live all night.")
    assert "are lyve" in normalize_tts_text("All services are live.")
    assert "went lyve" in normalize_tts_text("The deployment went live at noon.")
    assert "go lyve" in normalize_tts_text("We are ready to go live.")
    assert "currently lyve" in normalize_tts_text("The port is currently live.")
    assert "running lyve" in normalize_tts_text("The background daemon is running live.")
    assert "deployed lyve" in normalize_tts_text("The model is deployed live.")

    # Preceding nouns
    assert "lyve streaming" in normalize_tts_text("Let's start live streaming.")
    assert "lyve stream" in normalize_tts_text("Audio from the live stream.")
    assert "lyve dev mode" in normalize_tts_text("Running in live dev mode.")
    assert "lyve session" in normalize_tts_text("Joined the live session.")
    assert "lyve server" in normalize_tts_text("Connecting to the live server.")
    assert "lyve demo" in normalize_tts_text("Starting the live demo.")
    assert "lyve code" in normalize_tts_text("Editing live code.")
    assert "lyve logs" in normalize_tts_text("Tailing live logs.")
    assert "lyve updates" in normalize_tts_text("Streaming live updates.")
    assert "lyve status" in normalize_tts_text("Reporting live status.")


def test_heteronym_live_verb_preserved():
    """Verify that verb uses of 'live' (/lɪv/) are preserved without alteration."""
    assert "want to live" in normalize_tts_text("Where do you want to live?")
    assert "how we live" in normalize_tts_text("This is how we live.")
    assert "I live in Austin" in normalize_tts_text("I live in Austin.")
    assert "They live together" in normalize_tts_text("They live together.")
    assert "Long live" in normalize_tts_text("Long live the king.")


def test_heteronym_mixed_context():
    """Test mixed sentences containing both verb and adjective forms of 'live'."""
    text = "I want to live in Austin, but the website is now live and we have a live demo."
    normalized = normalize_tts_text(text)
    assert "want to live in Austin" in normalized
    assert "website is now lyve" in normalized
    assert "a lyve demo" in normalized


def test_developer_jargon_phonetics():
    """Verify developer acronyms, CLI tools, and file extensions are expanded."""
    assert "koob control" in normalize_tts_text("Run kubectl apply -f deployment.yaml")
    assert "N P M" in normalize_tts_text("Install with npm install")
    assert "P N P M" in normalize_tts_text("Run pnpm build")
    assert "U U I D" in normalize_tts_text("Generated a new UUID for session")
    assert "standard out" in normalize_tts_text("Check stdout for errors")
    assert "standard error" in normalize_tts_text("Redirect stderr to a log file")
    assert "a-sync a-wait" in normalize_tts_text("Refactor using async/await")
    assert "dot T S X" in normalize_tts_text("Created App.tsx")
    assert "dot pie" in normalize_tts_text("Saved to config.py")
    assert "dot J-S-O-N lines" in normalize_tts_text("Saved to transcript.jsonl")
    assert "Postgres Q L" in normalize_tts_text("Connecting to PostgreSQL")
    assert "O Auth" in normalize_tts_text("Configure OAuth credentials")


def test_clean_markdown_for_speech_integration():
    """Verify clean_markdown_for_speech incorporates TTS phonetic normalization."""
    raw = "The server is now live. Run `kubectl get pods` to verify."
    clean = clean_markdown_for_speech(raw)
    assert "now lyve" in clean
    assert "koob control" in clean
