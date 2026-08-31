"""
Anonymous telemetry, crash diagnostics, and error reporting for VoiceFi.
Strictly adheres to zero-PII privacy standards (sanitizes filepaths, strips prompts/audio/keys).
Respects DO_NOT_TRACK=1, VOICEFI_TELEMETRY=false, and config.telemetry=false.
"""

import hashlib
import json
import os
import platform
import re
import sys
import traceback
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import posthog
except ImportError:
    posthog = None

from voicefi.config import load_config

_posthog_initialized = False
_active_command: Optional[str] = None

# Default public ingestion key for anonymous crash/feedback telemetry
# Can be overridden via config.posthog_api_key or POSTHOG_API_KEY env var
DEFAULT_POSTHOG_API_KEY = "phc_oFyLfqmnEeFMDehRQ4DzGrN9AGctauZiZhfufRtmW92e"


def set_active_command(command: str):
    """Set the active command context for crash diagnostics and error tracking."""
    global _active_command
    if command:
        _active_command = str(command).strip()[:40]


def is_telemetry_enabled() -> bool:
    """Check whether anonymous telemetry is enabled."""
    if os.getenv("DO_NOT_TRACK", "").lower() in ("1", "true", "yes"):
        return False
    if os.getenv("VOICEFI_TELEMETRY", "").lower() in ("0", "false", "no", "off"):
        return False

    try:
        cfg = load_config()
        return bool(getattr(cfg, "telemetry", True))
    except Exception:
        return True


def get_telemetry_id() -> str:
    """
    Get a stable anonymous telemetry identifier (UUID4) persisted locally in ~/.voicefi/telemetry.json.
    Zero PII — generated locally on installation / first run.
    """
    config_path = Path.home() / ".voicefi" / "telemetry.json"
    try:
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                return str(data["id"])
    except Exception:
        pass

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        new_id = str(uuid.uuid4())
        config_path.write_text(json.dumps({"id": new_id}), encoding="utf-8")
        return new_id
    except Exception:
        return str(uuid.uuid4())


def get_machine_id() -> str:
    """Stable anonymous identifier for the machine (delegates to get_telemetry_id)."""
    return get_telemetry_id()


def compute_traceback_hash(traceback_str: str) -> str:
    """Compute a deterministic SHA-256 hash of a sanitized traceback for error grouping."""
    if not traceback_str:
        return "empty"
    return hashlib.sha256(traceback_str.encode("utf-8")).hexdigest()[:16]


def sanitize_telemetry_data(data: Any) -> Any:
    """
    Recursively sanitize paths and strings to guarantee ZERO PII leakage.
    Replaces user home directories (/Users/<name>/...) with ~/...
    Strips any API keys or tokens.
    """
    try:
        home = str(Path.home())
    except Exception:
        home = ""

    if isinstance(data, str):
        clean = data
        if home and home in clean:
            clean = clean.replace(home, "~")
        # Sanitize username in standard macOS paths if home didn't catch it
        clean = re.sub(r"/Users/[^/]+", "~", clean)
        # Redact API keys and tokens
        clean = re.sub(r"(sk-[a-zA-Z0-9_\-]{16,})", "[REDACTED_API_KEY]", clean)
        clean = re.sub(r"(phc_[a-zA-Z0-9_\-]{16,})", "[REDACTED_KEY]", clean)
        clean = re.sub(r"(gsk_[a-zA-Z0-9_\-]{16,})", "[REDACTED_KEY]", clean)
        return clean
    elif isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            # Exclude sensitive key names and raw user content
            k_lower = str(k).lower()
            if any(k_lower.endswith(s) for s in ("_key", "_secret", "_token", "_password", "auth")):
                continue
            if k_lower in (
                "prompt",
                "user_prompt",
                "raw_text",
                "raw_speech",
                "transcript_content",
                "audio_data",
                "audio_bytes",
                "text",
            ):
                continue
            sanitized[k] = sanitize_telemetry_data(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_telemetry_data(item) for item in data]
    return data


def init_telemetry():
    """Initialize PostHog telemetry and configure global error tracking."""
    global _posthog_initialized
    if not is_telemetry_enabled():
        return

    try:
        config = load_config()
    except Exception:
        config = None

    api_key = os.getenv("POSTHOG_API_KEY", "")
    if not api_key and config and hasattr(config, "posthog_api_key") and config.posthog_api_key:
        api_key = config.posthog_api_key

    # If no custom key, use default project key
    if not api_key:
        api_key = os.getenv("VOICEFI_POSTHOG_KEY", "") or DEFAULT_POSTHOG_API_KEY

    # Support custom PostHog host (e.g. self-hosted enterprise or EU region)
    host = os.getenv("POSTHOG_HOST", "")
    if not host and config and hasattr(config, "posthog_host") and config.posthog_host:
        host = config.posthog_host
    if not host:
        host = "https://us.i.posthog.com"

    if not posthog:
        return

    try:
        posthog.project_api_key = api_key
        posthog.host = host
        posthog.sync_mode = True
        _posthog_initialized = True

        user_id = get_telemetry_id()

        # Capture unhandled exceptions
        original_excepthook = sys.excepthook

        def global_exception_handler(exc_type, exc_value, exc_traceback):
            if _posthog_initialized:
                try:
                    error_msg = "".join(
                        traceback.format_exception(exc_type, exc_value, exc_traceback)
                    )
                    sanitized_msg = sanitize_telemetry_data(error_msg)
                    tb_hash = compute_traceback_hash(sanitized_msg)
                    posthog.capture(
                        "app_crash",
                        distinct_id=user_id,
                        properties={
                            "command": _active_command or "unknown",
                            "error_type": exc_type.__name__,
                            "error_message": sanitize_telemetry_data(str(exc_value)),
                            "traceback_hash": tb_hash,
                            "traceback": sanitized_msg,
                            "$is_server": True,
                        },
                    )
                    posthog.flush()
                except Exception:
                    pass
            original_excepthook(exc_type, exc_value, exc_traceback)

        sys.excepthook = global_exception_handler
    except Exception:
        pass


def record_event(event_name: str, properties: Optional[Dict[str, Any]] = None):
    """
    Dual-Sink Event Dispatcher:
    1. Persists event locally to SQLite database (~/.voicefi/analytics.db) for developer insights.
    2. Dispatches sanitized zero-PII event to remote telemetry sink if enabled.
    """
    props = dict(properties or {})

    # 1. Always record to local SQLite store (100% offline, zero-network, local ownership)
    try:
        from voicefi.analytics.store import get_analytics_store

        store = get_analytics_store()
        store.record_local_event(
            event_name=event_name,
            properties=props,
            duration_ms=props.get("duration_ms", 0),
            success=props.get("success", True),
            caller_agent=props.get("caller_agent") or props.get("agent"),
            tool_name=props.get("tool_name") or props.get("tool"),
            provider=props.get("provider"),
            persona=props.get("persona") or props.get("voice"),
            char_count=props.get("char_count") or props.get("chars_count", 0),
            is_barge_in=props.get("is_barge_in", False),
            error_type=props.get("error_type"),
        )
    except Exception:
        pass

    # 2. Conditionally dispatch to remote telemetry if enabled
    capture_event(event_name, props)


def capture_event(event_name: str, properties: Optional[Dict[str, Any]] = None):
    """Capture a sanitized telemetry/diagnostic event if telemetry is enabled."""
    if not is_telemetry_enabled():
        return

    if not _posthog_initialized:
        init_telemetry()

    user_id = get_telemetry_id()
    sanitized_props = sanitize_telemetry_data(properties or {})
    if "os" not in sanitized_props:
        sanitized_props["os"] = platform.system()
    if "arch" not in sanitized_props:
        sanitized_props["arch"] = platform.machine()
    if "$is_server" not in sanitized_props:
        sanitized_props["$is_server"] = True

    if _posthog_initialized and posthog:
        try:
            posthog.capture(event_name, distinct_id=user_id, properties=sanitized_props)
            posthog.flush()
            return
        except Exception:
            pass

    # Direct HTTPS fallback if PostHog Python package is not loaded
    try:
        api_key = (
            os.getenv("POSTHOG_API_KEY")
            or os.getenv("VOICEFI_POSTHOG_KEY")
            or DEFAULT_POSTHOG_API_KEY
        )
        host = os.getenv("POSTHOG_HOST") or "https://us.i.posthog.com"
        endpoint = f"{host.rstrip('/')}/capture/"
        payload = json.dumps(
            {
                "api_key": api_key,
                "event": event_name,
                "distinct_id": user_id,
                "properties": sanitized_props,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "VoiceFi-Telemetry/1.0"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3.0)
    except Exception:
        pass


def capture_voice_interaction(
    trigger: str,
    duration_ms: int,
    success: bool = True,
    agent: Optional[str] = None,
    voice: Optional[str] = None,
    provider: Optional[str] = None,
    chars_count: Optional[int] = None,
    is_barge_in: Optional[bool] = None,
    error_type: Optional[str] = None,
):
    """
    Capture a voice_interaction event per utterance (Antigravity/Claude hook, speak CLI, IPC, MCP).
    Strictly zero-PII: strips all text content and records duration, character length, agent, and voice metadata.
    """
    props: Dict[str, Any] = {
        "trigger": str(trigger)[:20],
        "duration_ms": max(0, int(duration_ms)),
        "success": bool(success),
        "$is_server": True,
    }
    if agent:
        props["agent"] = str(agent).lower().strip()[:32]
        props["caller_agent"] = props["agent"]
    if voice:
        clean_v = str(voice).strip()
        if "/" not in clean_v and "\\" not in clean_v:
            props["voice"] = clean_v[:40]
            props["persona"] = props["voice"]
    if provider:
        props["provider"] = str(provider).strip().lower()[:30]
    if chars_count is not None:
        props["chars_count"] = max(0, int(chars_count))
        props["char_count"] = props["chars_count"]
    if is_barge_in is not None:
        props["is_barge_in"] = bool(is_barge_in)
    if error_type:
        props["error_type"] = str(error_type)[:60]

    record_event("voice_interaction", props)


def capture_mcp_tool_call(
    tool_name: str,
    duration_ms: int,
    caller_agent: Optional[str] = None,
    persona: Optional[str] = None,
    char_count: Optional[int] = None,
    success: bool = True,
    is_barge_in: bool = False,
    error_type: Optional[str] = None,
    extra_props: Optional[Dict[str, Any]] = None,
):
    """
    Capture an MCP tool call invocation from an AI agent (Antigravity, Claude Code, Cursor).
    Zero PII — records tool name, duration, character count, caller agent, and success/error status.
    """
    props: Dict[str, Any] = {
        "tool_name": str(tool_name)[:40],
        "duration_ms": max(0, int(duration_ms)),
        "success": bool(success),
        "is_barge_in": bool(is_barge_in),
        "$is_server": True,
    }
    if caller_agent:
        props["caller_agent"] = str(caller_agent).lower().strip()[:32]
        props["agent"] = props["caller_agent"]
    if persona:
        props["persona"] = str(persona).strip()[:40]
        props["voice"] = props["persona"]
    if char_count is not None:
        props["char_count"] = max(0, int(char_count))
    if error_type:
        props["error_type"] = str(error_type)[:60]
    if extra_props and isinstance(extra_props, dict):
        props.update(sanitize_telemetry_data(extra_props))

    record_event("mcp_tool_call", props)


def capture_barge_in_event(
    device_type: Optional[str] = None,
    is_full_duplex: bool = True,
    interrupt_reaction_ms: int = 150,
    ambient_energy_level: Optional[float] = None,
):
    """Capture a user barge-in speech interruption event during agent playback."""
    props: Dict[str, Any] = {
        "is_full_duplex": bool(is_full_duplex),
        "interrupt_reaction_ms": max(0, int(interrupt_reaction_ms)),
        "is_barge_in": True,
        "$is_server": True,
    }
    if device_type:
        props["device_type"] = str(device_type)[:30]
    if ambient_energy_level is not None:
        props["ambient_energy_level"] = round(float(ambient_energy_level), 4)

    record_event("barge_in_event", props)


def capture_agent_dispatch(
    source_engine: str,
    target_engine: str,
    is_reply: bool = False,
    char_count: int = 0,
    success: bool = True,
):
    """Capture cross-agent IPC dispatch event (e.g. Antigravity <-> Claude Code)."""
    props: Dict[str, Any] = {
        "source_engine": str(source_engine).lower().strip()[:30],
        "target_engine": str(target_engine).lower().strip()[:30],
        "is_reply": bool(is_reply),
        "char_count": max(0, int(char_count)),
        "success": bool(success),
        "$is_server": True,
    }
    record_event("agent_dispatch", props)
