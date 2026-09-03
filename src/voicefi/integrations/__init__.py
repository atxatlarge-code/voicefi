"""Antigravity and OS integrations for VoiceFi."""

from voicefi.integrations.antigravity import handle_antigravity_stop_hook, clean_markdown_for_speech
from voicefi.integrations.injector import (
    inject_text_to_active_app,
    focus_antigravity,
    focus_app_by_name,
    focus_speaking_agent_window,
)
from voicefi.integrations.conversations import ConversationTracker, ConversationInfo
from voicefi.integrations.tool_formatter import format_tool_details, extract_log_summary

__all__ = [
    "handle_antigravity_stop_hook",
    "clean_markdown_for_speech",
    "inject_text_to_active_app",
    "focus_antigravity",
    "focus_app_by_name",
    "focus_speaking_agent_window",
    "ConversationTracker",
    "ConversationInfo",
    "format_tool_details",
    "extract_log_summary",
]
