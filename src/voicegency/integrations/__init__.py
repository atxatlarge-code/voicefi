"""Antigravity and OS integrations for Voicegency."""

from voicegency.integrations.antigravity import handle_antigravity_stop_hook, clean_markdown_for_speech
from voicegency.integrations.injector import inject_text_to_active_app, focus_antigravity
from voicegency.integrations.conversations import ConversationTracker, ConversationInfo

__all__ = [
    "handle_antigravity_stop_hook",
    "clean_markdown_for_speech",
    "inject_text_to_active_app",
    "focus_antigravity",
    "ConversationTracker",
    "ConversationInfo",
]
