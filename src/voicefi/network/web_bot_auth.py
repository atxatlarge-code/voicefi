"""
Web Bot Auth — Cryptographic HTTP Message Signatures for AI Agents & Bots.

Implements IETF WebBotAuth Working Group and RFC 9421 specifications:
- Publishes and resolves JSON Web Key Set (JWKS) directories
- Signs outbound HTTP requests with Signature-Agent, Signature-Input, and Signature headers
- Cryptographically verifies incoming signed requests using Ed25519 (OKP)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Union
from urllib.parse import urlparse
import urllib.request

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

DEFAULT_DIRECTORY_URL = "https://voicefi.org/.well-known/http-message-signatures-directory"
DEFAULT_KEY_ID = "OM_hua4CsdxBMMXHbCnmOTBNqXT89AFCOAF0FkXK1GI"
DEFAULT_PUBLIC_KEY_X = "SSZLM3GclE8GFi_IyxJKhz-eearLfVcJD_vR5OfSSdI"
DEFAULT_PRIVATE_KEY_D = "vMP2V6ptUaR14QnmNwm695n-5rRtmVOJtRrNSqzV-vE"
DEFAULT_TAG = "web-bot-auth"
DIRECTORY_TAG = "http-message-signatures-directory"


def compute_jwk_thumbprint(x_b64: str) -> str:
    """
    Calculate base64url-encoded SHA-256 JWK thumbprint per RFC 7638 & RFC 8037 Appendix A.3.
    Canonical JSON: {"crv":"Ed25519","kty":"OKP","x":"..."}
    """
    canonical = json.dumps({"crv": "Ed25519", "kty": "OKP", "x": x_b64}, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


@dataclass
class WebBotKeyPair:
    """Ed25519 keypair for Web Bot Auth signing and verification."""
    kid: str
    public_key_x: str
    private_key_d: Optional[str] = None

    @classmethod
    def generate(cls) -> "WebBotKeyPair":
        """Generate a new Ed25519 keypair."""
        if not HAS_CRYPTOGRAPHY:
            raise RuntimeError("cryptography package is required to generate new keys")
        priv = ed25519.Ed25519PrivateKey.generate()
        pub = priv.public_key()
        raw_priv = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        raw_pub = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        x_b64 = base64.urlsafe_b64encode(raw_pub).decode("ascii").rstrip("=")
        d_b64 = base64.urlsafe_b64encode(raw_priv).decode("ascii").rstrip("=")
        kid = compute_jwk_thumbprint(x_b64)
        return cls(kid=kid, public_key_x=x_b64, private_key_d=d_b64)

    @classmethod
    def default(cls) -> "WebBotKeyPair":
        """Returns the default VoiceFi production Web Bot Auth keypair."""
        return cls(
            kid=DEFAULT_KEY_ID,
            public_key_x=DEFAULT_PUBLIC_KEY_X,
            private_key_d=DEFAULT_PRIVATE_KEY_D,
        )

    def to_jwk(self, include_private: bool = False) -> Dict[str, str]:
        """Export as JSON Web Key dict."""
        jwk = {
            "kid": self.kid,
            "kty": "OKP",
            "crv": "Ed25519",
            "x": self.public_key_x,
        }
        if include_private and self.private_key_d:
            jwk["d"] = self.private_key_d
        return jwk


def sign_bot_headers(
    url: str,
    method: str = "GET",
    keypair: Optional[WebBotKeyPair] = None,
    directory_url: str = DEFAULT_DIRECTORY_URL,
    ttl_seconds: int = 180,
    nonce: Optional[str] = None,
) -> Dict[str, str]:
    """
    Construct Web Bot Auth RFC 9421 signature headers for an outbound request.

    Returns a dict with:
      - 'Signature-Agent': Quoted URL to directory
      - 'Signature-Input': Input parameters specifying authority & signature-agent components
      - 'Signature': Cryptographic Ed25519 signature
    """
    if not HAS_CRYPTOGRAPHY:
        raise RuntimeError("cryptography package is required for Web Bot Auth request signing")

    kp = keypair or WebBotKeyPair.default()
    if not kp.private_key_d:
        raise ValueError("Cannot sign requests without a private key")

    # Decode Ed25519 private key
    d_raw = base64.urlsafe_b64decode(kp.private_key_d + "==")
    priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(d_raw)

    parsed = urlparse(url)
    authority = parsed.netloc

    now = int(time.time())
    expires = now + ttl_seconds
    if not nonce:
        nonce = base64.b64encode(os.urandom(64)).decode("ascii")

    # Double quote directory_url per Cloudflare structured header requirement
    sig_agent_value = f'"{directory_url}"'

    sig_input = (
        f'sig1=("@authority" "signature-agent");'
        f'created={now};'
        f'keyid="{kp.kid}";'
        f'alg="ed25519";'
        f'expires={expires};'
        f'nonce="{nonce}";'
        f'tag="{DEFAULT_TAG}"'
    )

    sig_base = (
        f'"@authority": {authority}\n'
        f'"signature-agent": "{directory_url}"\n'
        f'"@signature-params": {sig_input}'
    )

    sig_bytes = priv_key.sign(sig_base.encode("utf-8"))
    sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

    return {
        "Signature-Agent": sig_agent_value,
        "Signature-Input": sig_input,
        "Signature": f"sig1=:{sig_b64}:",
    }


def sign_urllib_request(
    req: urllib.request.Request,
    keypair: Optional[WebBotKeyPair] = None,
    directory_url: str = DEFAULT_DIRECTORY_URL,
    ttl_seconds: int = 180,
) -> urllib.request.Request:
    """
    Signs a urllib.request.Request in place by attaching Web Bot Auth signature headers.
    """
    headers = sign_bot_headers(
        url=req.full_url,
        method=req.get_method(),
        keypair=keypair,
        directory_url=directory_url,
        ttl_seconds=ttl_seconds,
    )
    for k, v in headers.items():
        req.add_header(k, v)
    return req


def verify_bot_request(
    headers: Dict[str, str],
    authority: str,
    public_key_x: Optional[str] = None,
    tolerance_seconds: int = 60,
) -> Tuple[bool, str]:
    """
    Verify incoming Web Bot Auth HTTP Message Signatures.
    
    Returns (is_valid, reason).
    """
    if not HAS_CRYPTOGRAPHY:
        return False, "cryptography package not installed"

    # Normalize header keys to lowercase
    h = {k.lower(): v for k, v in headers.items()}

    sig_agent = h.get("signature-agent")
    sig_input = h.get("signature-input")
    signature = h.get("signature")

    if not sig_agent or not sig_input or not signature:
        return False, "Missing required Web Bot Auth headers"

    # Signature-Agent must be quoted string
    if not (sig_agent.startswith('"') and sig_agent.endswith('"')):
        return False, "Signature-Agent header must be a quoted structured string"
    clean_agent = sig_agent.strip('"')

    # Parse Signature header: sig1=:<base64>:
    sig_match = re.search(r"sig1=:([A-Za-z0-9+/=]+):", signature)
    if not sig_match:
        return False, "Malformed Signature header format"
    sig_bytes = base64.b64decode(sig_match.group(1))

    # Parse timestamps
    created_match = re.search(r"created=(\d+)", sig_input)
    expires_match = re.search(r"expires=(\d+)", sig_input)
    if not created_match or not expires_match:
        return False, "Missing created or expires parameter in Signature-Input"

    now = int(time.time())
    created = int(created_match.group(1))
    expires = int(expires_match.group(1))

    if now > expires + tolerance_seconds:
        return False, "Signature has expired"
    if created > now + tolerance_seconds:
        return False, "Signature created in the future"

    # Reconstruct signature base
    # Check if signature-input matched components
    sig_base = (
        f'"@authority": {authority}\n'
        f'"signature-agent": "{clean_agent}"\n'
        f'"@signature-params": {sig_input}'
    )

    x_key = public_key_x or DEFAULT_PUBLIC_KEY_X
    try:
        raw_pub = base64.urlsafe_b64decode(x_key + "==")
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(raw_pub)
        pub_key.verify(sig_bytes, sig_base.encode("utf-8"))
        return True, "Signature verified successfully"
    except Exception as e:
        return False, f"Signature verification failed: {e}"
