"""
VoiceFi Web & Mobile Voice Companion.
Enables hands-free mobile PWA voice interaction with Antigravity agents over local Wi-Fi.
"""

from voicefi.companion.server import CompanionServer, run_companion_server
from voicefi.companion.qr import get_local_ip, get_companion_urls, print_qr_code

__all__ = [
    "CompanionServer",
    "run_companion_server",
    "get_local_ip",
    "get_companion_urls",
    "print_qr_code",
]
