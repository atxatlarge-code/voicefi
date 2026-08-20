"""Antigravity and OS integrations for Talk 2 Me."""

from talk2me.integrations.antigravity import handle_antigravity_stop_hook, clean_markdown_for_speech
from talk2me.integrations.injector import inject_text_to_active_app

__all__ = ["handle_antigravity_stop_hook", "clean_markdown_for_speech", "inject_text_to_active_app"]
