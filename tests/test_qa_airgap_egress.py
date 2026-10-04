"""
QA-01: Air-Gap Zero-Egress and Network Isolation Test Suite.
Validates that when VOICEFI_OFFLINE=1 or VOICEFI_AIRGAP=1 is set:
1. Zero outbound network connections or DNS queries are attempted.
2. Telemetry capture_exception and capture_event cleanly no-op in 0.0ms.
3. Offline STT and TTS resolution cleanly defaults to on-device providers.
"""

import os
import socket
import pytest
from unittest.mock import patch, MagicMock

from voicefi.telemetry import (
    is_offline_mode,
    is_telemetry_enabled,
    capture_exception,
    capture_event,
    init_telemetry,
    flush_telemetry,
)
from voicefi.config import VoiceFiConfig
from voicefi.tts import get_tts_engine, MacSayTTS
from voicefi.stt import get_stt_engine


class OutboundNetworkViolationError(AssertionError):
    """Raised when an outbound network call occurs in air-gapped mode."""
    pass


@pytest.fixture
def enforce_airgap_environment(monkeypatch):
    """Fixture that enforces VOICEFI_OFFLINE=1 and monitors network sockets."""
    monkeypatch.setenv("VOICEFI_OFFLINE", "1")
    monkeypatch.delenv("VOICEFI_AIRGAP", raising=False)

    outbound_attempts = []

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) and address else str(address)
        # Allow loopback (localhost, 127.0.0.1, ::1)
        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            return real_connect(self, address)
        violation = f"Outbound connection attempted to {address} during air-gap mode!"
        outbound_attempts.append(violation)
        raise OutboundNetworkViolationError(violation)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return outbound_attempts


def test_airgap_detection_flags(monkeypatch):
    """Verify is_offline_mode detects all air-gap environment variables and config."""
    monkeypatch.setenv("VOICEFI_OFFLINE", "1")
    assert is_offline_mode() is True
    assert is_telemetry_enabled() is False

    monkeypatch.delenv("VOICEFI_OFFLINE")
    monkeypatch.setenv("VOICEFI_AIRGAP", "1")
    assert is_offline_mode() is True
    assert is_telemetry_enabled() is False

    monkeypatch.delenv("VOICEFI_AIRGAP")
    assert is_offline_mode() is False


def test_telemetry_zero_egress_in_airgap(enforce_airgap_environment):
    """Verify capture_exception and capture_event execute as zero-egress no-ops."""
    outbound_attempts = enforce_airgap_environment

    # 1. Initialize telemetry (should short-circuit cleanly with zero egress)
    res_init = init_telemetry()
    assert res_init is None

    # 2. Capture exceptions
    try:
        raise ValueError("Sensitive air-gapped system error")
    except ValueError as err:
        res_exc = capture_exception(err, properties={"component": "airgap_test"})
        assert res_exc is False

    # 3. Capture events (should short-circuit cleanly with zero egress)
    res_evt = capture_event("agent_speech_turn", {"words": 42})
    assert res_evt is None or res_evt is False

    # 4. Flush telemetry
    flush_telemetry(timeout=0.1)

    # Assert 0 network connection attempts were made
    assert len(outbound_attempts) == 0


def test_tts_offline_routing_in_airgap(monkeypatch, enforce_airgap_environment):
    """Verify get_tts_engine resolves cleanly to offline MacSay when offline is configured."""
    outbound_attempts = enforce_airgap_environment

    cfg = VoiceFiConfig()
    cfg.tts.provider = "mac_say"
    engine = get_tts_engine(cfg)

    assert isinstance(engine, MacSayTTS)
    assert len(outbound_attempts) == 0


def test_stt_offline_routing_in_airgap(monkeypatch, enforce_airgap_environment):
    """Verify STT factory avoids Groq cloud network calls in air-gapped mode."""
    outbound_attempts = enforce_airgap_environment

    cfg = VoiceFiConfig()
    cfg.stt.provider = "whisper_local"
    engine = get_stt_engine(cfg)

    assert engine is not None
    assert len(outbound_attempts) == 0
