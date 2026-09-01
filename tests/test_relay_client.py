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
