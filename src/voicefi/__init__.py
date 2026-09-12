"""
VoiceFi - Giving your agents a voice, and your voice agency. Hands-free voice layer for AI coding agents and macOS desktop use.
"""

__version__ = "0.2.1"
__author__ = "Jake Trigg"

from voicefi.compat import patch_pynput_darwin

patch_pynput_darwin()

