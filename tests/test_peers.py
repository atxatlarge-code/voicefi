"""
Unit tests for VoiceFi Local Network Peer Discovery & Vandelay Industries Handoff.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from voicefi.network.peers import (
    PeerDevice,
    PeerDiscoveryEngine,
    PeerClient,
    get_computer_name,
    get_local_peer_info,
)


def test_peer_device_serialization():
    """Verify PeerDevice serialization to/from dictionary."""
    device = PeerDevice(
        hostname="jakes-mba.local",
        friendly_name="Jake's MacBook Air",
        ip="192.168.1.82",
        port=5141,
        os_info="macOS 15.3 (arm64)",
        agents=["antigravity", "claude"],
        tier="Pro (Perpetual)",
        latency_ms=12.4,
        is_local=False,
    )

    data = device.to_dict()
    assert data["hostname"] == "jakes-mba.local"
    assert data["friendly_name"] == "Jake's MacBook Air"
    assert data["ip"] == "192.168.1.82"
    assert data["tier"] == "Pro (Perpetual)"
    assert "antigravity" in data["agents"]

    restored = PeerDevice.from_dict(data)
    assert restored.hostname == device.hostname
    assert restored.friendly_name == device.friendly_name
    assert restored.ip == device.ip
    assert restored.latency_ms == device.latency_ms


def test_get_local_peer_info():
    """Verify local machine profile generation."""
    info = get_local_peer_info()
    assert "hostname" in info
    assert "friendly_name" in info
    assert "ip" in info
    assert "port" in info
    assert "tier" in info
    assert isinstance(info["agents"], list)


def test_resolve_peer_target():
    """Verify fuzzy peer name and IP resolution."""
    peers = [
        PeerDevice(
            hostname="jakes-mbp.local",
            friendly_name="Jake's MacBook Pro M3",
            ip="192.168.1.45",
            is_local=True,
        ),
        PeerDevice(
            hostname="jakes-mba.local",
            friendly_name="Jake's MacBook Air",
            ip="192.168.1.82",
            is_local=False,
        ),
    ]

    # Test exact IP match
    assert PeerDiscoveryEngine.resolve_target("192.168.1.82", peers=peers).ip == "192.168.1.82"

    # Test substring match: 'mba'
    mba_match = PeerDiscoveryEngine.resolve_target("mba", peers=peers)
    assert mba_match is not None
    assert "Air" in mba_match.friendly_name

    # Test substring match: 'pro'
    pro_match = PeerDiscoveryEngine.resolve_target("pro", peers=peers)
    assert pro_match is not None
    assert "Pro" in pro_match.friendly_name

    # Test non-matching query
    assert PeerDiscoveryEngine.resolve_target("nonexistent_device", peers=peers) is None


@patch("urllib.request.urlopen")
def test_peer_client_send_task(mock_urlopen):
    """Verify PeerClient sends structured task payload to peer HTTP endpoint."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "success": True,
        "delivered": True,
        "device": "Jake's MacBook Air"
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    target_peer = PeerDevice(
        hostname="jakes-mba.local",
        friendly_name="Jake's MacBook Air",
        ip="192.168.1.82",
    )

    result = PeerClient.send_task(
        peer=target_peer,
        text="Refactor authentication middleware",
        target_engine="claude",
        sender_name="Jake @ MBP",
    )

    assert result["success"] is True
    assert result["delivered"] is True


@patch("urllib.request.urlopen")
def test_peer_client_push_and_pull_clipboard(mock_urlopen):
    """Verify PeerClient clipboard push and pull mechanisms."""
    # 1. Test Push Clipboard
    mock_resp_push = MagicMock()
    mock_resp_push.read.return_value = json.dumps({"success": True, "chars": 42}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp_push

    peer = PeerDevice(hostname="mba.local", friendly_name="MBA", ip="192.168.1.82")
    push_res = PeerClient.push_clipboard(peer, "console.log('Hello Vandelay!');")
    assert push_res["success"] is True
    assert push_res["chars"] == 42

    # 2. Test Pull Clipboard
    mock_resp_pull = MagicMock()
    mock_resp_pull.read.return_value = json.dumps({
        "success": True,
        "text": "const vandelay = 'latex';",
        "chars": 26
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp_pull

    pull_res = PeerClient.pull_clipboard(peer)
    assert pull_res["success"] is True
    assert "vandelay" in pull_res["text"]
