"""UI components for VoiceFi."""

from voicefi.ui.tray import run_tray
from voicefi.ui.panel import open_control_panel, start_panel_server, parse_voice_command
from voicefi.ui.speech_hud import AgentSpeechHUD
from voicefi.ui.dictation_hud import DictationHUD
from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
from voicefi.ui.hub import ConversationHubWindow

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

