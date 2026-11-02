"""
Unit tests for VoiceFi Cloud Relay Client and Session Credentials.
"""

import json
import pytest
from voicefi.companion.relay_client import RelaySessionCredentials, RelayClient


def test_relay_session_credentials_generation(tmp_path):
    creds = RelaySessionCredentials(session_id="test_sess_123", token="test_token_abc")
    assert creds.session_id == "test_sess_123"
    assert creds.token == "test_token_abc"
    
    url = creds.get_pairing_url("https://voicefi.org/companion")
    assert "s=test_sess_123" in url
    assert "t=test_token_abc" in url
    
    # Save & reload from disk
    file_path = tmp_path / "creds.json"
    creds.save_to_disk(file_path)
    assert file_path.is_file()
    
    loaded = RelaySessionCredentials.load_or_create(file_path)
    assert loaded.session_id == "test_sess_123"
    assert loaded.token == "test_token_abc"


def test_relay_client_initialization():
    creds = RelaySessionCredentials(session_id="sess_demo", token="tok_demo")
    client = RelayClient(credentials=creds, local_port=5141)
    assert client.credentials.session_id == "sess_demo"
    assert client.local_port == 5141
    assert "sess_demo" in client.pairing_url
    assert "tok_demo" in client.pairing_url


def test_relay_credentials_rotates_legacy_hardcoded_token(tmp_path):
    """Ensure legacy hardcoded session/token is automatically rotated on load."""
    file_path = tmp_path / "legacy_creds.json"
    file_path.write_text(
        json.dumps({"session_id": "vifi_4d098c55", "token": "MkNCI_F2Wczaf18jX4ZORQ"}),
        encoding="utf-8",
    )
    loaded = RelaySessionCredentials.load_or_create(file_path)
    assert loaded.session_id != "vifi_4d098c55"
    assert loaded.token != "MkNCI_F2Wczaf18jX4ZORQ"


def test_relay_rpc_path_validation_blocks_ssrf_and_admin_routes():
    """Verify _validate_rpc_path blocks SSRF payloads, path traversal, and local-only endpoints."""
    assert RelayClient._validate_rpc_path("/api/status") == "/api/status"
    assert RelayClient._validate_rpc_path("/api/conversations?limit=10") == "/api/conversations?limit=10"

    # SSRF / authority confusion payloads
    assert RelayClient._validate_rpc_path("@evil.example.com/pwn") is None
    assert RelayClient._validate_rpc_path("//evil.example.com/pwn") is None
    assert RelayClient._validate_rpc_path("/\\evil.example.com/pwn") is None
    assert RelayClient._validate_rpc_path("http://evil.example.com/api/status") is None
    assert RelayClient._validate_rpc_path("/api/../../etc/passwd") is None
    assert RelayClient._validate_rpc_path("/api/status\r\nX-Injected: 1") is None

    # Local-only endpoints blocked over cloud relay RPC
    assert RelayClient._validate_rpc_path("/api/fix") is None
    assert RelayClient._validate_rpc_path("/vifi/fix") is None
    assert RelayClient._validate_rpc_path("/api/hook/event") is None
    assert RelayClient._validate_rpc_path("/api/live/key") is None
    assert RelayClient._validate_rpc_path("/api/tunnel/start") is None
