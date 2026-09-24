"""
CLI interface for VoiceFi.
Universal Voice Layer for AI Agents, MCP, and macOS.
Lightweight entrypoint and command dispatcher (<200 lines).
"""

import os
import sys
import time
from typing import Optional

from voicefi import __version__
from voicefi.cli_format import VoiceFiArgumentParser, resolve_prog_name, render_categorized_help
from voicefi.cli_parser import build_parser
from voicefi.cli_metadata import extract_cli_metadata
from voicefi.cli_commands.registry import get_command_handlers

# Modularized subcommand implementations re-exported for 100% backward compatibility
from voicefi.cli_commands.hooks import cmd_hook
from voicefi.cli_commands.audio import (
    cmd_speak,
    cmd_listen,
    cmd_loop,
    cmd_vad,
    cmd_record,
    cmd_bias,
)
from voicefi.cli_commands.setup import cmd_setup, cmd_mcp, cmd_onboarding, cmd_permissions
from voicefi.cli_commands.knowledge import cmd_ambient, cmd_meeting, cmd_obsidian, cmd_capture
from voicefi.cli_commands.dispatch import (
    cmd_send,
    cmd_peers,
    cmd_vandelay,
    cmd_clip,
    cmd_new,
    cmd_companion,
    cmd_panel,
)
from voicefi.cli_commands.ui import cmd_hud, cmd_tray, cmd_quick_bar, cmd_welcome
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
    cmd_daemon,
)
from voicefi.cli_commands.troubleshoot import (
    cmd_troubleshoot,
    cmd_hearing_test,
    cmd_feedback_loop,
    cmd_loopback,
    cmd_barge_in,
    cmd_ping,
    run_silent_voice_ping,
)
from voicefi.cli_commands.voice import cmd_voice, cmd_clone, cmd_download_ava
from voicefi.cli_commands.speed_talk import cmd_speed_talk
from voicefi.cli_commands.memo import cmd_memo
from voicefi.cli_commands.media import cmd_duel, cmd_sfx, cmd_fx, cmd_reel, cmd_trim
from voicefi.cli_commands.live import cmd_live, cmd_bridge
from voicefi.cli_commands.local import cmd_spark, cmd_scout, cmd_benchmark, cmd_local
from voicefi.tts import get_tts_engine
from voicefi.config import load_config, save_config


def main():
    try:
        from voicefi.telemetry import init_telemetry

        init_telemetry()
    except Exception:
        pass

    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "root_live", False):
        cmd_live(args)
        return

    if not args.command:
        if getattr(sys, "frozen", False):
            # Launched from macOS .app bundle without CLI arguments
            try:
                from voicefi.ui.translocation import check_and_prompt_move_to_applications

                check_and_prompt_move_to_applications()
            except Exception:
                pass
            cmd_tray(args)
            return
        parser.print_help()
        sys.exit(0)

    commands = get_command_handlers(parser)

    # Asynchronously trigger background update check
    try:
        from voicefi.updater import trigger_background_update_check

        trigger_background_update_check()
    except Exception:
        pass

    handler = commands.get(args.command)
    if handler:
        cli_mod = sys.modules.get("voicefi.cli")
        if cli_mod and hasattr(handler, "__name__") and hasattr(cli_mod, handler.__name__):
            handler = getattr(cli_mod, handler.__name__)
        props = extract_cli_metadata(args)
        try:
            from voicefi.telemetry import set_active_command

            set_active_command(args.command)
        except Exception:
            pass
        start_time = time.time()
        success = True
        exit_code = 0
        error_type = None

        try:
            handler(args)
        except SystemExit as se:
            exit_code = se.code if isinstance(se.code, int) else (0 if se.code is None else 1)
            success = exit_code == 0
            raise
        except KeyboardInterrupt:
            success = False
            exit_code = 130
            error_type = "KeyboardInterrupt"
            raise
        except BrokenPipeError:
            exit_code = 0
            success = True
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                try:
                    devnull = os.open(os.devnull, os.O_WRONLY)
                    os.dup2(devnull, sys.stdout.fileno())
                except Exception:
                    pass
            sys.exit(0)
        except Exception as e:
            success = False
            exit_code = 1
            error_type = type(e).__name__
            raise
        finally:
            duration_ms = int((time.time() - start_time) * 1000)
            props["duration_ms"] = duration_ms
            props["success"] = success
            props["exit_code"] = exit_code
            if error_type:
                props["error_type"] = error_type

            # Enrich with hook/runtime details if attached to args
            if hasattr(args, "_telemetry_extra") and isinstance(args._telemetry_extra, dict):
                props.update(args._telemetry_extra)

            try:
                from voicefi.telemetry import capture_event

                capture_event("cli_command", props)
            except Exception:
                pass


if __name__ == "__main__":
    main()
