"""
VoiceFi Local Network Peer Discovery & Cross-Mac Data Handoff Engine.
Enables instant, zero-configuration discovery and bidirectional prompt/clipboard
exchange across Macs running VoiceFi on the local Wi-Fi / LAN network.
"""

import asyncio
import json
import logging
import os
import platform
import socket
import subprocess
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

PEERS_CACHE_FILE = Path.home() / ".voicefi" / "peers.json"
DEFAULT_PORT = 5141


@dataclass
class PeerDevice:
    """Represents a discovered VoiceFi instance on the local network."""
    hostname: str
    friendly_name: str
    ip: str
    port: int = DEFAULT_PORT
    os_info: str = ""
    agents: List[str] = field(default_factory=list)
    tier: str = "Community"
    version: str = "1.0.0"
    latency_ms: float = 0.0
    last_seen: float = field(default_factory=time.time)
    is_local: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PeerDevice":
        return cls(
            hostname=data.get("hostname", "unknown.local"),
            friendly_name=data.get("friendly_name", "VoiceFi Mac"),
            ip=data.get("ip", "127.0.0.1"),
            port=data.get("port", DEFAULT_PORT),
            os_info=data.get("os_info", ""),
            agents=data.get("agents", []),
            tier=data.get("tier", "Community"),
            version=data.get("version", "1.0.0"),
            latency_ms=data.get("latency_ms", 0.0),
            last_seen=data.get("last_seen", time.time()),
            is_local=data.get("is_local", False),
        )


def get_computer_name() -> str:
    """Get friendly macOS Computer Name (e.g. 'Jake’s MacBook Pro')."""
    try:
        res = subprocess.run(
            ["scutil", "--get", "ComputerName"],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return "VoiceFi Mac"


def get_local_ip() -> str:
    """Get the primary local LAN IP of this machine."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def get_local_peer_info(config=None) -> Dict[str, Any]:
    """Return local device profile dictionary for /api/peer/info endpoint."""
    from voicefi.config import load_config
    from voicefi.license import FeatureGate
    from voicefi.integrations.discovery import AgentToolDetector

    cfg = config or load_config()
    tier_info = FeatureGate.get_tier_summary(cfg)
    detected_tools = AgentToolDetector.get_all_detected_tools()
    active_agents = [k for k, v in detected_tools.items() if v.get("detected")]

    return {
        "hostname": socket.gethostname(),
        "friendly_name": get_computer_name(),
        "ip": get_local_ip(),
        "port": getattr(cfg.companion, "port", DEFAULT_PORT) if hasattr(cfg, "companion") else DEFAULT_PORT,
        "os_info": f"macOS {platform.mac_ver()[0]} ({platform.machine()})",
        "agents": active_agents,
        "tier": f"{tier_info.get('tier', 'Community')} ({tier_info.get('status', 'Active')})",
        "version": "1.0.0",
        "timestamp": time.time(),
    }


class PeerDiscoveryEngine:
    """Scans and discovers VoiceFi peer instances on the local network."""

    @staticmethod
    def load_cached_peers() -> List[PeerDevice]:
        """Load previously discovered peers from disk cache."""
        if not PEERS_CACHE_FILE.exists():
            return []
        try:
            with open(PEERS_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [PeerDevice.from_dict(p) for p in data if isinstance(p, dict)]
        except Exception as e:
            logger.debug(f"Failed to load cached peers: {e}")
            return []

    @staticmethod
    def save_cached_peers(peers: List[PeerDevice]) -> None:
        """Persist discovered peers to disk cache."""
        try:
            PEERS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PEERS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump([p.to_dict() for p in peers], f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save cached peers: {e}")

    @classmethod
    async def probe_host(cls, ip: str, port: int = DEFAULT_PORT, timeout: float = 0.5) -> Optional[PeerDevice]:
        """Probe a specific IP address for VoiceFi peer endpoints."""
        import urllib.request
        import urllib.error

        local_ip = get_local_ip()
        start_time = time.time()

        ports_to_try = [port]
        if port != 8765:
            ports_to_try.append(8765)
        if port != 5141 and 5141 not in ports_to_try:
            ports_to_try.insert(0, 5141)

        loop = asyncio.get_running_loop()

        for p in ports_to_try:
            for endpoint in ("/api/peer/info", "/api/status"):
                url = f"http://{ip}:{p}{endpoint}"

                def _fetch(u=url):
                    req = urllib.request.Request(u, headers={"User-Agent": "VoiceFi-PeerDiscovery/1.0"})
                    try:
                        with urllib.request.urlopen(req, timeout=timeout) as response:
                            if response.status == 200:
                                return json.loads(response.read().decode("utf-8"))
                    except Exception:
                        pass
                    return None

                data = await loop.run_in_executor(None, _fetch)
                if data and isinstance(data, dict):
                    latency = round((time.time() - start_time) * 1000, 1)
                    is_local = (ip == "127.0.0.1" or ip == "localhost" or ip == local_ip)
                    friendly_name = data.get("friendly_name")
                    if not friendly_name:
                        # Fallback heuristic from hostname or status
                        hostname = data.get("hostname", f"{ip}.local")
                        friendly_name = f"Peer Mac ({ip})" if not is_local else "This Mac"
                    return PeerDevice(
                        hostname=data.get("hostname", f"{ip}.local"),
                        friendly_name=friendly_name,
                        ip=ip if not is_local else local_ip,
                        port=data.get("port", p),
                        os_info=data.get("os_info", "macOS"),
                        agents=data.get("agents", ["antigravity"]),
                        tier=data.get("tier", "Pro Trial"),
                        version=data.get("version", "1.0.0"),
                        latency_ms=latency,
                        last_seen=time.time(),
                        is_local=is_local,
                    )
        return None

    @classmethod
    async def discover_all(cls, timeout: float = 1.2, port: int = DEFAULT_PORT) -> List[PeerDevice]:
        """Scan local loopback, cached hosts, mDNS candidates, and current /24 subnet."""
        local_ip = get_local_ip()
        targets = set()

        # 1. Always check localhost and current local IP
        targets.add("127.0.0.1")
        if local_ip != "127.0.0.1":
            targets.add(local_ip)

        # 2. Check previously cached peers
        cached = cls.load_cached_peers()
        for p in cached:
            if p.ip:
                targets.add(p.ip)

        # 3. Add local subnet IPs if on a standard LAN
        if local_ip.startswith("192.168.") or local_ip.startswith("10.") or local_ip.startswith("172."):
            parts = local_ip.split(".")
            if len(parts) == 4:
                prefix = f"{parts[0]}.{parts[1]}.{parts[2]}"
                current_host = int(parts[3])
                for offset in range(-50, 51):
                    candidate = current_host + offset
                    if 1 <= candidate <= 254:
                        targets.add(f"{prefix}.{candidate}")

        tasks = [cls.probe_host(target, port=port, timeout=timeout) for target in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        found_peers: Dict[str, PeerDevice] = {}
        for res in results:
            if isinstance(res, PeerDevice):
                key = res.ip
                found_peers[key] = res

        peer_list = list(found_peers.values())
        peer_list.sort(key=lambda p: (not p.is_local, p.latency_ms))

        cls.save_cached_peers(peer_list)
        return peer_list

    @classmethod
    def resolve_target(cls, target_query: str, peers: Optional[List[PeerDevice]] = None) -> Optional[PeerDevice]:
        """Fuzzy match a peer name, substring, or IP address (e.g. 'mba', 'pro', '192.168.1.45')."""
        target_clean = target_query.strip().lower()
        if not target_clean:
            return None

        candidates = peers if peers is not None else cls.load_cached_peers()
        if not candidates:
            # Quick fallback probe of target as direct hostname / IP
            try:
                loop = asyncio.new_event_loop()
                dev = loop.run_until_complete(cls.probe_host(target_query, timeout=0.8))
                loop.close()
                if dev:
                    return dev
            except Exception:
                pass
            return None

        # 1. Exact IP match
        for p in candidates:
            if p.ip.lower() == target_clean or f"http://{p.ip}:{p.port}" == target_clean:
                return p

        # 2. Exact hostname or friendly name match
        for p in candidates:
            if p.hostname.lower() == target_clean or p.friendly_name.lower() == target_clean:
                return p

        # 3. Substring match on friendly name or hostname
        for p in candidates:
            if target_clean in p.friendly_name.lower() or target_clean in p.hostname.lower():
                return p

        # 4. Direct probe if user passed an IP or hostname not yet cached
        try:
            loop = asyncio.new_event_loop()
            dev = loop.run_until_complete(cls.probe_host(target_query, timeout=0.8))
            loop.close()
            if dev:
                return dev
        except Exception:
            pass

        return None


class PeerClient:
    """Dispatches tasks, clipboards, and voice sync across peer Macs."""

    @staticmethod
    def send_task(
        peer: PeerDevice,
        text: str,
        target_engine: str = "auto",
        sender_name: Optional[str] = None,
        reply: bool = False,
        from_conv_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Dispatch an AI prompt or task to a remote peer Mac over LAN."""
        import urllib.request
        import urllib.error

        sender = sender_name or get_computer_name()
        url = f"http://{peer.ip}:{peer.port}/api/peer/send"

        payload = {
            "text": text,
            "target_engine": target_engine,
            "sender_name": sender,
            "sender_device": get_computer_name(),
            "sender_ip": get_local_ip(),
            "reply": reply,
            "from_conv_id": from_conv_id,
            "timestamp": time.time(),
        }

        endpoints = ["/api/peer/send", "/api/send", "/api/message"]
        last_err = None

        for ep in endpoints:
            url = f"http://{peer.ip}:{peer.port}{ep}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "VoiceFi-PeerClient/1.0"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    data = resp.read()
                    if isinstance(data, (bytes, bytearray)):
                        data = data.decode("utf-8")
                    return json.loads(data)
            except urllib.error.HTTPError as e:
                if e.code in (404, 405):
                    last_err = e
                    continue
                return {"success": False, "error": f"HTTP {e.code} from {peer.friendly_name}: {e.reason}"}
            except Exception as e:
                last_err = e

        return {"success": False, "error": f"Connection failed to {peer.friendly_name} ({peer.ip}): {last_err}"}

    @staticmethod
    def push_clipboard(peer: PeerDevice, text: str) -> Dict[str, Any]:
        """Push clipboard text or code snippet to a remote peer Mac."""
        import urllib.request
        import urllib.error

        url = f"http://{peer.ip}:{peer.port}/api/peer/clip"
        payload = {
            "text": text,
            "sender_device": get_computer_name(),
            "sender_ip": get_local_ip(),
            "timestamp": time.time(),
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def pull_clipboard(peer: PeerDevice) -> Dict[str, Any]:
        """Fetch current clipboard from a remote peer Mac."""
        import urllib.request
        import urllib.error

        url = f"http://{peer.ip}:{peer.port}/api/peer/clip"
        req = urllib.request.Request(url, headers={"User-Agent": "VoiceFi-PeerClient/1.0"})

        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def sync_config(peer: PeerDevice, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sync voice personas, speed settings, and brevity dictionary to peer Mac."""
        import urllib.request
        import urllib.error

        url = f"http://{peer.ip}:{peer.port}/api/peer/sync"
        req = urllib.request.Request(
            url,
            data=json.dumps(config_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"success": False, "error": str(e)}
