"""UI components for Voicegency."""

from voicegency.ui.tray import run_tray
from voicegency.ui.panel import open_control_panel, start_panel_server, parse_voice_command
from voicegency.ui.speech_hud import AgentSpeechHUD
from voicegency.ui.dictation_hud import DictationHUD
from voicegency.ui.hub import ConversationHubWindow

__all__ = [
    "run_tray",
    "open_control_panel",
    "start_panel_server",
    "parse_voice_command",
    "AgentSpeechHUD",
    "DictationHUD",
    "ConversationHubWindow",
]

