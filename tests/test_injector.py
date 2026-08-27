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

        assert bool(delivered) is True
        assert delivered.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "send-message" in cmd
        assert "--title=Message from Jake" in cmd
        assert "14007fc9-1e0d-4278-90a4-1dad4c3236fd" in cmd
        assert "Let's proceed with the plan" in cmd
        # inject_text_to_active_app should NOT have been called as agentapi succeeded
        mock_inject.assert_not_called()


def test_send_message_to_antigravity_reply_routing():
    """Test send_message_to_antigravity resolves 'reply' to recorded origin conversation."""
    from voicefi.integrations.injector import send_message_to_antigravity

    mock_route = {
        "from_engine": "antigravity",
        "from_conv_id": "origin-conv-12345",
        "to_engine": "claude",
    }

    with patch("voicefi.integrations.conversations.get_return_route", return_value=mock_route), \
         patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True), \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0)

        delivered = send_message_to_antigravity(
            conv_id="reply",
            text="Claude findings response",
            sender_name="Claude",
        )

        assert bool(delivered) is True
        assert delivered.success is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "origin-conv-12345" in cmd
        assert "Claude findings response" in cmd



def test_inject_text_to_claude_with_envelope():
    """Test inject_text_to_claude formats provenance envelope when requested."""
    from voicefi.integrations.injector import inject_text_to_claude

    with patch("voicefi.integrations.injector.set_clipboard_text") as mock_clip, \
         patch("voicefi.integrations.injector.focus_terminal_app", return_value="Ghostty"), \
         patch("voicefi.integrations.conversations.record_agent_route") as mock_route, \
         patch("subprocess.run") as mock_run:

        mock_run.return_value = MagicMock(returncode=0, stdout="true")

        success = inject_text_to_claude(
            "Fix the authentication bug",
            from_conv_id="conv-agy-999",
            from_engine="antigravity",
            include_envelope=True,
        )

        assert success is True
        mock_route.assert_called_once_with(
            from_engine="antigravity",
            from_conv_id="conv-agy-999",
            to_engine="claude",
        )
        mock_clip.assert_called_once()
        clipped_text = mock_clip.call_args[0][0]
        assert "[From: Antigravity | Conversation: conv-agy-999]" in clipped_text
        assert "Fix the authentication bug" in clipped_text
        assert "vifi send --to antigravity --reply" in clipped_text


def test_send_message_to_antigravity_failure_never_blind_pastes():
    """Test send_message_to_antigravity NEVER falls back to foreground paste when agentapi fails."""
    from voicefi.integrations.injector import send_message_to_antigravity

    with patch("pathlib.Path.is_file", return_value=True), \
         patch("os.access", return_value=True), \
         patch("subprocess.run") as mock_run, \
         patch("voicefi.integrations.injector.inject_text_to_active_app") as mock_inject:

        # agentapi fails with connection error
        mock_run.return_value = MagicMock(returncode=1, stderr="rpc error: code = Unavailable desc = connection error")

        result = send_message_to_antigravity(
            conv_id="14007fc9-1e0d-4278-90a4-1dad4c3236fd",
            text="Dangerous sensitive report",
            sender_name="Claude",
            allow_foreground_fallback=False,
        )

        assert bool(result) is False
        assert result.delivery_type == "none"
        assert "Unavailable" in str(result.error)
        # CRITICAL ASSERTION: foreground paste must NEVER be called
        mock_inject.assert_not_called()


