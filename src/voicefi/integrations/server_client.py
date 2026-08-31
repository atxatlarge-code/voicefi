"""
Fast localhost server IPC client for VoiceFi.
Provides sub-millisecond hook forwarding from ephemeral CLI commands to the running background server.
Uses Python standard library (urllib.request / json) for zero import overhead.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional
from voicefi.config import VoiceFiConfig, load_config


def _raw_is_server_running(
    port: int = 5141, host: str = "127.0.0.1", timeout: float = 0.25
) -> bool:
    url = f"http://{host}:{port}/api/status"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def is_server_running(port: int = 5141, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    """Check if VoiceFi server / companion server is running on localhost."""
    for mod_name in ("voicefi.integrations.daemon_client", "voicefi.integrations.server_client"):
        mod = sys.modules.get(mod_name)
        if mod:
            for attr in ("is_daemon_running", "is_server_running"):
                fn = getattr(mod, attr, None)
                if (
                    fn is not None
                    and fn is not is_server_running
                    and fn is not _raw_is_server_running
                ):
                    return fn(port=port, host=host, timeout=timeout)
    return _raw_is_server_running(port=port, host=host, timeout=timeout)


# Backwards compatibility alias
is_daemon_running = is_server_running


def _raw_ensure_server_running(
    config: Optional[VoiceFiConfig] = None, timeout: float = 1.5
) -> bool:
    cfg = config or load_config()
    companion_cfg = getattr(cfg, "companion", None)
    port = getattr(companion_cfg, "port", 5141) if companion_cfg else 5141

    if is_server_running(port=port):
        return True

    # Find the appropriate voicefi executable or python module
    bin_path = None
    ws_candidates = [
        Path.cwd() / ".venv" / "bin" / "voicefi",
        Path(__file__).resolve().parent.parent.parent / ".venv" / "bin" / "voicefi",
        Path(sys.executable).parent / "voicefi",
        Path.home() / ".voicefi" / "venv" / "bin" / "voicefi",
    ]
    for cand in ws_candidates:
        if cand.is_file() and os.access(str(cand), os.X_OK):
            bin_path = str(cand)
            break
    if not bin_path:
        bin_path = shutil.which("voicefi") or sys.executable

    cmd = (
        [bin_path, "tray"]
        if bin_path.endswith("voicefi")
        else [bin_path, "-m", "voicefi.cli", "tray"]
    )
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return False

    start_t = time.time()
    while (time.time() - start_t) < timeout:
        if is_server_running(port=port, timeout=0.15):
            return True
        time.sleep(0.1)

    return is_server_running(port=port)


def ensure_server_running(config: Optional[VoiceFiConfig] = None, timeout: float = 1.5) -> bool:
    """
    Ensure VoiceFi background tray server is running so the Unified Dynamic Island HUD
    and global Escape key controls are active. Spawns server if currently offline.
    """
    for mod_name in ("voicefi.integrations.daemon_client", "voicefi.integrations.server_client"):
        mod = sys.modules.get(mod_name)
        if mod:
            for attr in ("ensure_daemon_running", "ensure_server_running"):
                fn = getattr(mod, attr, None)
                if (
                    fn is not None
                    and fn is not ensure_server_running
                    and fn is not _raw_ensure_server_running
                ):
                    return fn(config=config, timeout=timeout)
    return _raw_ensure_server_running(config=config, timeout=timeout)


# Backwards compatibility alias
ensure_daemon_running = ensure_server_running


def _raw_forward_hook_to_server(
    payload: Dict[str, Any],
    config: Optional[VoiceFiConfig] = None,
    timeout: float = 1.5,
) -> Optional[Dict[str, Any]]:
    cfg = config or load_config()
    companion_cfg = getattr(cfg, "companion", None)
    port = getattr(companion_cfg, "port", 5141) if companion_cfg else 5141
    host = "127.0.0.1"

    if not is_server_running(port=port):
        return None

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


def forward_hook_to_server(
    payload: Dict[str, Any],
    config: Optional[VoiceFiConfig] = None,
    timeout: float = 1.5,
) -> Optional[Dict[str, Any]]:
    """
    Forward lifecycle hook event payload to the running VoiceFi background server.
    Returns response dict if successfully received and handled by server, or None if offline.
    """
    for mod_name in ("voicefi.integrations.daemon_client", "voicefi.integrations.server_client"):
        mod = sys.modules.get(mod_name)
        if mod:
            for attr in ("forward_hook_to_daemon", "forward_hook_to_server"):
                fn = getattr(mod, attr, None)
                if (
                    fn is not None
                    and fn is not forward_hook_to_server
                    and fn is not _raw_forward_hook_to_server
                ):
                    return fn(payload, config=config, timeout=timeout)
    return _raw_forward_hook_to_server(payload, config=config, timeout=timeout)


# Backwards compatibility alias
forward_hook_to_daemon = forward_hook_to_server
