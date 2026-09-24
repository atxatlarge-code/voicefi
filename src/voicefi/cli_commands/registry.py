"""
CLI command dispatch registry and alias mapping for VoiceFi.
"""

import argparse
from typing import Callable, Dict, Any

from voicefi.cli_commands.hooks import cmd_hook
from voicefi.cli_commands.audio import (
    cmd_speak,
    cmd_listen,
    cmd_loop,
    cmd_vad,
    cmd_record,
    cmd_bias,
)
from voicefi.cli_commands.setup import (
    cmd_setup,
    cmd_mcp,
    cmd_onboarding,
    cmd_permissions,
)
from voicefi.cli_commands.knowledge import (
    cmd_ambient,
    cmd_meeting,
    cmd_obsidian,
    cmd_capture,
)
from voicefi.cli_commands.dispatch import (
    cmd_send,
    cmd_peers,
    cmd_vandelay,
    cmd_clip,
    cmd_new,
    cmd_companion,
    cmd_panel,
)
from voicefi.cli_commands.ui import (
    cmd_hud,
    cmd_tray,
    cmd_quick_bar,
    cmd_welcome,
)
from voicefi.cli_commands.system import (
    cmd_dev,
    cmd_wake,
    cmd_update,
    cmd_feedback,
    cmd_tier,
    cmd_license,
    cmd_learn,
    cmd_info,
    cmd_stats,
)
from voicefi.cli_commands.server import (
    cmd_server,
    cmd_clean,
    cmd_autostart,
    cmd_stop_autostart,
    cmd_pause,
    cmd_resume,
)
from voicefi.cli_commands.troubleshoot import (
    cmd_troubleshoot,
    cmd_hearing_test,
    cmd_feedback_loop,
    cmd_loopback,
    cmd_barge_in,
    cmd_ping,
)
from voicefi.cli_commands.voice import (
    cmd_voice,
    cmd_clone,
    cmd_download_ava,
)
from voicefi.cli_commands.speed_talk import cmd_speed_talk
from voicefi.cli_commands.memo import cmd_memo
from voicefi.cli_commands.media import (
    cmd_duel,
    cmd_sfx,
    cmd_fx,
    cmd_reel,
    cmd_trim,
)
from voicefi.cli_commands.live import (
    cmd_live,
    cmd_bridge,
)
from voicefi.cli_commands.local import (
    cmd_spark,
    cmd_scout,
    cmd_benchmark,
    cmd_local,
)


def get_command_handlers(parser: Any = None) -> Dict[str, Callable[[Any], Any]]:
    """Return dictionary of CLI subcommand names and aliases mapped to handlers."""
    handlers: Dict[str, Callable[[Any], Any]] = {
        "fx": cmd_fx,
        "voice-fx": cmd_fx,
        "effects": cmd_fx,
        "trim": cmd_trim,
        "cut": cmd_trim,
        "slice": cmd_trim,
        "reel": cmd_reel,
        "video": cmd_reel,
        "compile-reel": cmd_reel,
        "bridge": cmd_bridge,
        "ipc-bridge": cmd_bridge,
        "ipc": cmd_bridge,
        "spark": cmd_spark,
        "live": cmd_live,
        "comedy": cmd_live,
        "gemini-live": cmd_live,
        "sfx": cmd_sfx,
        "sound": cmd_sfx,
        "duel": cmd_duel,
        "banter": cmd_duel,
        "stats": cmd_stats,
        "analytics": cmd_stats,
        "insights": cmd_stats,
        "send": cmd_send,
        "dispatch": cmd_send,
        "peers": cmd_peers,
        "peer": cmd_peers,
        "discover": cmd_peers,
        "vandelay": cmd_vandelay,
        "clip": cmd_clip,
        "clipboard": cmd_clip,
        "update": cmd_update,
        "upgrade": cmd_update,
        "download-ava": cmd_download_ava,
        "install-ava": cmd_download_ava,
        "setup-ava": cmd_download_ava,
        "get-ava": cmd_download_ava,
        "setup-offline": cmd_download_ava,
        "offline-ava": cmd_download_ava,
        "scout": cmd_scout,
        "recon": cmd_scout,
        "benchmark": cmd_benchmark,
        "bench": cmd_benchmark,
        "eval": cmd_benchmark,
        "local": cmd_local,
        "litert": cmd_local,
        "gemma": cmd_local,
        "help": lambda a: parser.print_help() if parser else None,
        "new": cmd_new,
        "new-conversation": cmd_new,
        "hook": cmd_hook,
        "speak": cmd_speak,
        "listen": cmd_listen,
        "loop": cmd_loop,
        "tray": cmd_tray,
        "dev": cmd_dev,
        "setup": cmd_setup,
        "onboarding": cmd_onboarding,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "permissions": cmd_permissions,
        "autostart": cmd_autostart,
        "stop-autostart": cmd_stop_autostart,
        "companion": cmd_companion,
        "remote": cmd_companion,
        "pair": cmd_companion,
        "rc": cmd_companion,
        "RC": cmd_companion,
        "panel": cmd_panel,
        "info": cmd_info,
        "tier": cmd_tier,
        "pricing": cmd_tier,
        "trial": cmd_tier,
        "plan": cmd_tier,
        "license": cmd_license,
        "learn": cmd_learn,
        "learning": cmd_learn,
        "obsidian": cmd_obsidian,
        "capture": cmd_capture,
        "voice": cmd_voice,
        "speed-talk": cmd_speed_talk,
        "speedtalk": cmd_speed_talk,
        "speed_talk": cmd_speed_talk,
        "fast": cmd_speed_talk,
        "turbo": cmd_speed_talk,
        "ping": cmd_ping,
        "speed-test": cmd_ping,
        "check-voice": cmd_ping,
        "hud": cmd_hud,
        "hearing-test": cmd_hearing_test,
        "hearing": cmd_hearing_test,
        "feedback": cmd_feedback,
        "feedback-loop": cmd_feedback_loop,
        "feedback_loop": cmd_feedback_loop,
        "voice-loop": cmd_feedback_loop,
        "loopback": cmd_loopback,
        "barge-in": cmd_barge_in,
        "barge_in": cmd_barge_in,
        "test-barge-in": cmd_barge_in,
        "troubleshoot": cmd_troubleshoot,
        "test": cmd_troubleshoot,
        "clone": cmd_clone,
        "clean": cmd_clean,
        "purge": cmd_clean,
        "reset-cache": cmd_clean,
        "server": cmd_server,
        "service": cmd_server,
        "daemon": cmd_server,
        "status": lambda a: cmd_server(
            argparse.Namespace(server_action="status", config=getattr(a, "config", None))
        ),
        "stop": lambda a: cmd_server(
            argparse.Namespace(server_action="stop", config=getattr(a, "config", None))
        ),
        "start": lambda a: cmd_server(
            argparse.Namespace(server_action="start", config=getattr(a, "config", None))
        ),
        "restart": lambda a: cmd_server(
            argparse.Namespace(server_action="restart", config=getattr(a, "config", None))
        ),
        "kill": lambda a: cmd_server(
            argparse.Namespace(server_action="stop", config=getattr(a, "config", None))
        ),
        "memo": cmd_memo,
        "buffer": cmd_memo,
        "record": cmd_record,
        "voice-note": cmd_record,
        "mic-record": cmd_record,
        "wake": cmd_wake,
        "wakeword": cmd_wake,
        "hey-viv": cmd_wake,
        "bar": cmd_quick_bar,
        "prompt": cmd_quick_bar,
        "quick": cmd_quick_bar,
        "welcome": cmd_welcome,
        "welcome-gui": cmd_welcome,
        "license-gui": cmd_welcome,
        "activate-gui": cmd_welcome,
        "ambient": cmd_ambient,
        "meeting": cmd_meeting,
        "feedbackloop": cmd_feedback_loop,
        "bias": cmd_bias,
        "vad": cmd_vad,
        "mcp": cmd_mcp,
        "mcp-server": cmd_mcp,
    }
    return handlers
