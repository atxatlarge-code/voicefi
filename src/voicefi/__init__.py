"""
VoiceFi - Giving your agents a voice, and your voice agency. Hands-free voice layer for AI coding agents and macOS desktop use.
"""

__version__ = "0.3.0"
__author__ = "Jake Trigg"

import os
import sys

if os.environ.get("PYTHONHASHSEED") == "":
    os.environ.pop("PYTHONHASHSEED", None)

_FAST_CLI_COMMANDS = ("doctor", "health", "check", "hook", "hooks", "--version", "-h", "--help")
if not (len(sys.argv) >= 2 and sys.argv[1] in _FAST_CLI_COMMANDS):
    from voicefi.compat import patch_pynput_darwin

    patch_pynput_darwin()

__all__ = ["tool", "live_tool", "__version__", "__author__"]


def __getattr__(name: str):
    if name in ("tool", "live_tool"):
        from voicefi.integrations.live_tools import tool, live_tool

        return tool if name == "tool" else live_tool
    raise AttributeError(f"module 'voicefi' has no attribute {name!r}")
