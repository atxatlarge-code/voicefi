"""
VoiceFi Local Network, Peer Discovery & Web Bot Auth Module.
"""

from voicefi.network.web_bot_auth import (
    WebBotKeyPair,
    compute_jwk_thumbprint,
    sign_bot_headers,
    sign_urllib_request,
    verify_bot_request,
)

__all__ = [
    "WebBotKeyPair",
    "compute_jwk_thumbprint",
    "sign_bot_headers",
    "sign_urllib_request",
    "verify_bot_request",
]
