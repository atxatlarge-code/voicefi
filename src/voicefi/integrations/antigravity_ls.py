"""
Automatic Language Server discovery and credentials resolver for Antigravity.
Discovers running Antigravity language_server processes, extracts CSRF tokens,
probes TCP LISTEN ports for active gRPC endpoints, and caches valid credentials.
"""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

_CACHED_LS_CREDS: Optional[Tuple[str, str, float]] = None  # (address, csrf_token, timestamp)
_CACHE_TTL_SECONDS = 300.0  # 5 minutes


def invalidate_antigravity_ls_cache() -> None:
    """Clear cached language server credentials."""
    global _CACHED_LS_CREDS
    _CACHED_LS_CREDS = None


def discover_antigravity_ls_credentials(
    target_conv_id: Optional[str] = None,
    force_refresh: bool = False,
) -> Optional[Tuple[str, str]]:
    """
    Discover ANTIGRAVITY_LS_ADDRESS and ANTIGRAVITY_CSRF_TOKEN from running language_server processes.
    Returns (ls_address, csrf_token) or None.
    """
    global _CACHED_LS_CREDS
    now = time.time()

    # If environment already has both explicitly set and not forcing refresh, use them
    env_addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS")
    env_token = os.environ.get("ANTIGRAVITY_CSRF_TOKEN")
    if env_addr and env_token and not force_refresh:
        return env_addr, env_token

    if not force_refresh and _CACHED_LS_CREDS:
        addr, token, ts = _CACHED_LS_CREDS
        if (now - ts) < _CACHE_TTL_SECONDS:
            return addr, token

    # 1. Find all running language_server processes
    try:
        ps_res = subprocess.run(
            ["ps", "-eo", "pid,command"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        lines = ps_res.stdout.splitlines()
    except Exception:
        return None

    candidates: List[Dict[str, Any]] = []
    csrf_pattern = re.compile(r"--csrf_token\s+([a-zA-Z0-9_-]+)")

    for line in lines:
        if "language_server" in line and "--csrf_token" in line:
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            pid_str, cmdline = parts[0], parts[1]
            try:
                pid = int(pid_str)
            except ValueError:
                continue

            m = csrf_pattern.search(cmdline)
            if not m:
                continue
            token = m.group(1)

            # Prioritize standalone Antigravity over IDE extension if multiple
            priority = 0
            if "Antigravity.app" in cmdline:
                priority = 10
            elif "Antigravity IDE.app" in cmdline:
                priority = 5

            candidates.append(
                {
                    "pid": pid,
                    "token": token,
                    "priority": priority,
                    "cmdline": cmdline,
                }
            )

    if not candidates:
        return None

    # Sort by priority descending
    candidates.sort(key=lambda x: x["priority"], reverse=True)

    agentapi_bin = Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi"

    # 2. For each candidate process, find its listening TCP ports and probe with agentapi
    for cand in candidates:
        pid = cand["pid"]
        token = cand["token"]

        try:
            lsof_res = subprocess.run(
                ["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
            ports = re.findall(r":(\d+)\s+\(LISTEN\)", lsof_res.stdout)
        except Exception:
            ports = []

        for port in ports:
            addr = f"127.0.0.1:{port}"
            env = os.environ.copy()
            env["ANTIGRAVITY_LS_ADDRESS"] = addr
            env["ANTIGRAVITY_CSRF_TOKEN"] = token

            probe_cmd = [str(agentapi_bin), "get-conversation-metadata"]
            if target_conv_id:
                probe_cmd.append(str(target_conv_id))
            else:
                probe_cmd.append("probe")

            try:
                probe_res = subprocess.run(
                    probe_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True,
                    timeout=2,
                )
                out = probe_res.stdout.strip()

                # If the port is an active gRPC endpoint, agentapi won't fail with connection error / EOF
                if (
                    "conversationMetadata" in out
                    or "trajectory not found" in out
                    or probe_res.returncode == 0
                    or ("rpc error" in out and "Unavailable" not in out and "EOF" not in out)
                ):
                    _CACHED_LS_CREDS = (addr, token, now)
                    return addr, token
            except Exception:
                continue

    return None


def get_agentapi_env(
    target_conv_id: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, str]:
    """
    Get os.environ dictionary populated with discovered ANTIGRAVITY_LS_ADDRESS and ANTIGRAVITY_CSRF_TOKEN.
    """
    env = os.environ.copy()
    creds = discover_antigravity_ls_credentials(
        target_conv_id=target_conv_id, force_refresh=force_refresh
    )
    if creds:
        env["ANTIGRAVITY_LS_ADDRESS"] = creds[0]
        env["ANTIGRAVITY_CSRF_TOKEN"] = creds[1]
    return env
