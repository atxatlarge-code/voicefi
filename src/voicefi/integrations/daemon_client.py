"""
Fast localhost daemon IPC client for VoiceFi.
Provides sub-millisecond hook forwarding from ephemeral CLI commands to the running background daemon.
Uses Python standard library (urllib.request / json) for zero import overhead.
"""

import json
import uuid
import urllib.request
import urllib.error
from typing import Dict, Any, Optional
from voicefi.config import VoiceFiConfig, load_config


def is_daemon_running(port: int = 5141, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    """Check if VoiceFi daemon / companion server is running on localhost."""
    url = f"http://{host}:{port}/api/status"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def forward_hook_to_daemon(
    payload: Dict[str, Any],
    config: Optional[VoiceFiConfig] = None,
    timeout: float = 1.5,
) -> Optional[Dict[str, Any]]:
    """
    Forward lifecycle hook event payload to the running VoiceFi background daemon.
    Returns response dict if successfully received and handled by daemon, or None if offline.
    """
    cfg = config or load_config()
    companion_cfg = getattr(cfg, "companion", None)
    port = getattr(companion_cfg, "port", 5141) if companion_cfg else 5141
    host = "127.0.0.1"

    if "request_id" not in payload:
        payload["request_id"] = str(uuid.uuid4())

    url = f"http://{host}:{port}/api/hook/event"
    data_bytes = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                return json.loads(body)
    except Exception:
        return None

    return None
