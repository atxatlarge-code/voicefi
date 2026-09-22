"""
Tests for Web Bot Auth request signing, verification, and JWKS thumbprint.
"""

import time
import pytest
from voicefi.network.web_bot_auth import (
    WebBotKeyPair,
    compute_jwk_thumbprint,
    sign_bot_headers,
    verify_bot_request,
    DEFAULT_KEY_ID,
    DEFAULT_PUBLIC_KEY_X,
    DEFAULT_DIRECTORY_URL,
)


def test_jwk_thumbprint_calculation():
    """Verify RFC 7638 SHA-256 thumbprint matching known vectors."""
    # Test known vector from RFC 9421 / Cloudflare docs:
    # x: "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"
    # kid: "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"
    cf_x = "JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"
    cf_kid = "poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"
    assert compute_jwk_thumbprint(cf_x) == cf_kid

    # Verify VoiceFi production key thumbprint
    assert compute_jwk_thumbprint(DEFAULT_PUBLIC_KEY_X) == DEFAULT_KEY_ID


def test_keypair_generation_and_export():
    """Test dynamic Ed25519 keypair generation and JWK format."""
    kp = WebBotKeyPair.generate()
    assert kp.kid == compute_jwk_thumbprint(kp.public_key_x)
    assert kp.private_key_d is not None

    jwk_pub = kp.to_jwk(include_private=False)
    assert jwk_pub["kty"] == "OKP"
    assert jwk_pub["crv"] == "Ed25519"
    assert jwk_pub["kid"] == kp.kid
    assert "d" not in jwk_pub

    jwk_priv = kp.to_jwk(include_private=True)
    assert jwk_priv["d"] == kp.private_key_d


def test_sign_and_verify_roundtrip():
    """Test generating signed request headers and verifying them locally."""
    kp = WebBotKeyPair.generate()
    url = "https://api.recipient.test/v1/agent-endpoint"
    headers = sign_bot_headers(
        url=url,
        method="GET",
        keypair=kp,
        directory_url="https://voicefi.org/.well-known/http-message-signatures-directory",
        ttl_seconds=300,
    )

    assert "Signature-Agent" in headers
    assert "Signature-Input" in headers
    assert "Signature" in headers

    assert headers["Signature-Agent"] == '"https://voicefi.org/.well-known/http-message-signatures-directory"'
    assert 'tag="web-bot-auth"' in headers["Signature-Input"]
    assert f'keyid="{kp.kid}"' in headers["Signature-Input"]
    assert headers["Signature"].startswith("sig1=:")
    assert headers["Signature"].endswith(":")

    # Verify signature
    valid, reason = verify_bot_request(
        headers=headers,
        authority="api.recipient.test",
        public_key_x=kp.public_key_x,
    )
    assert valid is True
    assert "verified successfully" in reason


def test_verify_rejects_expired_signature():
    """Test that expired signatures are rejected."""
    kp = WebBotKeyPair.generate()
    url = "https://api.recipient.test/v1/agent-endpoint"
    # Expired 500 seconds ago
    headers = sign_bot_headers(
        url=url,
        keypair=kp,
        ttl_seconds=-500,
    )
    valid, reason = verify_bot_request(
        headers=headers,
        authority="api.recipient.test",
        public_key_x=kp.public_key_x,
    )
    assert valid is False
    assert "expired" in reason.lower()


def test_verify_rejects_tampered_authority():
    """Test that modifying authority breaks signature verification."""
    kp = WebBotKeyPair.generate()
    url = "https://api.recipient.test/v1/agent-endpoint"
    headers = sign_bot_headers(url=url, keypair=kp)

    # Verify against different authority
    valid, reason = verify_bot_request(
        headers=headers,
        authority="attacker.test",
        public_key_x=kp.public_key_x,
    )
    assert valid is False
    assert "failed" in reason.lower()
