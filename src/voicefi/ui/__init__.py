"""UI components for VoiceFi."""


def run_tray(*args, **kwargs):
    from voicefi.ui.tray import run_tray as _run_tray

    return _run_tray(*args, **kwargs)


from voicefi.ui.panel import open_control_panel, start_panel_server, parse_voice_command


def __getattr__(name: str):
    if name == "AgentSpeechHUD":
        from voicefi.ui.speech_hud import AgentSpeechHUD

        return AgentSpeechHUD
    elif name == "DictationHUD":
        from voicefi.ui.dictation_hud import DictationHUD

        return DictationHUD
    elif name == "UnifiedDynamicIslandHUD":
        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

        return UnifiedDynamicIslandHUD
    elif name == "ConversationHubWindow":
        from voicefi.ui.hub import ConversationHubWindow

        return ConversationHubWindow
    elif name == "run_tray":
        from voicefi.ui.tray import run_tray

        return run_tray
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "run_tray",
    "open_control_panel",
    "start_panel_server",
    "parse_voice_command",
    "AgentSpeechHUD",
    "DictationHUD",
    "UnifiedDynamicIslandHUD",
    "ConversationHubWindow",
]
