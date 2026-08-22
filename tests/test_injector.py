"""
Unit tests for text injector, clipboard preservation, and voice macros.
"""

from unittest.mock import MagicMock, patch
import pytest
from voicegency.integrations.injector import (
    process_dictation_macros,
    inject_text_to_active_app,
    get_clipboard_text,
    set_clipboard_text,
)


def test_process_dictation_macros_cancel():
    """Test verbal cancel commands cleanly abort injection."""
    assert process_dictation_macros("scratch that") is None
    assert process_dictation_macros("Scratch That.") is None
    assert process_dictation_macros("cancel dictation") is None
    assert process_dictation_macros("clear dictation") is None
    assert process_dictation_macros("never mind") is None


def test_process_dictation_macros_formatting():
    """Test formatting macros like new line, punctuation, and paragraphs."""
    res1 = process_dictation_macros("Hello world new line How are you question mark")
    assert res1 == "Hello world\nHow are you?"

    res2 = process_dictation_macros("First paragraph new paragraph Second paragraph period")
    assert res2 == "First paragraph\n\nSecond paragraph."

    res3 = process_dictation_macros("Wait comma here is an exclamation point")
    assert res3 == "Wait, here is an!"


def test_inject_text_to_active_app_with_clipboard_preservation():
    """Test text injection preserves previous clipboard content."""
    with patch("voicegency.integrations.injector.get_clipboard_text", return_value="PREVIOUS_CLIPBOARD"), \
         patch("voicegency.integrations.injector.set_clipboard_text", return_value=True) as mock_set, \
         patch("voicegency.integrations.injector.restore_clipboard_delayed") as mock_restore, \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0)

        success = inject_text_to_active_app(
            "Hello from dictation",
            submit_enter=False,
            preserve_clipboard=True,
        )
        assert success is True
        mock_set.assert_called_with("Hello from dictation")
        mock_restore.assert_called_once_with("PREVIOUS_CLIPBOARD", delay=0.18)


def test_inject_text_to_active_app_cancelled_macro():
    """Test injection returns False when speech is a cancel macro."""
    with patch("subprocess.run") as mock_run:
        success = inject_text_to_active_app("scratch that", submit_enter=False)
        assert success is False
        mock_run.assert_not_called()
