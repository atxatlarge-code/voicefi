"""
Unit tests for TTS Normalizer, App Style Context Adaptation, and Verbal Filler Stripping.
"""

import pytest
from voicefi.tts.normalizer import (
    normalize_tts_text,
    strip_verbal_fillers,
    classify_app_context,
    format_for_app_context,
    AppStyleContext,
)


def test_heteronym_normalization():
    # 'live' as /laɪv/
    assert "lyve" in normalize_tts_text("The site is live")
    assert "lyve" in normalize_tts_text("We are going live tonight")
    assert "lyve" in normalize_tts_text("Live dev mode activated")

    # 'read'
    assert "reed-only" in normalize_tts_text("This is a read-only token")


def test_strip_verbal_fillers():
    # 1. Standalone fillers
    raw1 = "Um, we need to deploy the new auth service, uh, today."
    cleaned1 = strip_verbal_fillers(raw1)
    assert "Um" not in cleaned1
    assert "uh" not in cleaned1
    assert "We need to deploy the new auth service today." in cleaned1

    # 2. Filler phrases ("you know", "basically")
    raw2 = "Basically, you know, the server is running out of memory."
    cleaned2 = strip_verbal_fillers(raw2)
    assert "Basically" not in cleaned2
    assert "you know" not in cleaned2
    assert "The server is running out of memory." in cleaned2

    # 3. Repeated stutter duplicates
    raw3 = "We need the the token in in the database."
    cleaned3 = strip_verbal_fillers(raw3)
    assert "the the" not in cleaned3
    assert "in in" not in cleaned3
    assert "The token in the database." in cleaned3 or "We need the token in the database." in cleaned3


def test_classify_app_context():
    assert classify_app_context("Slack") == AppStyleContext.CHAT
    assert classify_app_context("Discord") == AppStyleContext.CHAT
    assert classify_app_context("Mail") == AppStyleContext.EMAIL
    assert classify_app_context("Microsoft Outlook") == AppStyleContext.EMAIL
    assert classify_app_context("Cursor") == AppStyleContext.CODE
    assert classify_app_context("Visual Studio Code") == AppStyleContext.CODE
    assert classify_app_context("Terminal") == AppStyleContext.CODE
    assert classify_app_context("iTerm2") == AppStyleContext.CODE
    assert classify_app_context("Notion") == AppStyleContext.DOCS
    assert classify_app_context("Obsidian") == AppStyleContext.DOCS
    assert classify_app_context("Google Chrome") == AppStyleContext.GENERAL


def test_format_for_app_context():
    # 1. Code IDE context
    code_raw = "Check if user id double equals 42 and use dash dash force"
    code_fmt = format_for_app_context(code_raw, app_name="Cursor")
    assert "==" in code_fmt
    assert "--force" in code_fmt

    # 2. Chat context with list
    chat_raw = "First update the schema, second run tests, third deploy"
    chat_fmt = format_for_app_context(chat_raw, app_name="Slack")
    assert "• " in chat_fmt

    # 3. Email context
    email_raw = "Please find the updated financial report attached"
    email_fmt = format_for_app_context(email_raw, app_name="Mail")
    assert email_fmt.endswith(".")
