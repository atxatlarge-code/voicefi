"""
Unit tests for text injector, clipboard preservation, and voice macros.
"""

from unittest.mock import MagicMock, patch
import pytest
from voicefi.integrations.injector import (
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
    with patch("voicefi.integrations.injector.get_clipboard_text", return_value="PREVIOUS_CLIPBOARD"), \
         patch("voicefi.integrations.injector.set_clipboard_text", return_value=True) as mock_set, \
         patch("voicefi.integrations.injector.restore_clipboard_delayed") as mock_restore, \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0)

        success = inject_text_to_active_app(
            "Hello from dictation",
            submit_enter=False,
            preserve_clipboard=True,
        )
        assert success is True
        mock_set.assert_called_with("Hello from dictation")
        mock_restore.assert_called_once_with("PREVIOUS_CLIPBOARD", delay=0.4)


def test_inject_text_to_active_app_cancelled_macro():
    """Test injection returns False when speech is a cancel macro."""
    with patch("subprocess.run") as mock_run:
        success = inject_text_to_active_app("scratch that", submit_enter=False)
        assert success is False
        mock_run.assert_not_called()


def test_inject_text_to_active_app_failure():
    """Test injector returns False and leaves text on clipboard when osascript fails."""
    with patch("subprocess.run") as mock_run, \
         patch("voicefi.integrations.injector.set_clipboard_text", return_value=True):
        mock_run.return_value = MagicMock(returncode=1, stderr="System Events got an error (1002)")
        success = inject_text_to_active_app("hello world", submit_enter=False)
        assert success is False


def test_send_message_to_antigravity_via_agentapi():
    """Test send_message_to_antigravity uses agentapi directly without stealing window focus."""
    from voicefi.integrations.injector import send_message_to_antigravity

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("voicefi.integrations.injector.inject_text_to_active_app") as mock_inject:

        mock_run.return_value = MagicMock(returncode=0)

        delivered = send_message_to_antigravity(
            conv_id="14007fc9-1e0d-4278-90a4-1dad4c3236fd",
            text="Let's proceed with the plan",
            sender_name="Jake",
        )

        assert delivered is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "send-message" in cmd
        assert "--title=Message from Jake" in cmd
        assert "14007fc9-1e0d-4278-90a4-1dad4c3236fd" in cmd
        assert "Let's proceed with the plan" in cmd
        # inject_text_to_active_app should NOT have been called as agentapi succeeded
        mock_inject.assert_not_called()
