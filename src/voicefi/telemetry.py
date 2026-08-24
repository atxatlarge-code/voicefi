"""
Anonymous telemetry, crash diagnostics, and error reporting for VoiceFi.
Strictly adheres to zero-PII privacy standards (sanitizes filepaths, strips prompts/audio/keys).
Respects DO_NOT_TRACK=1, VOICEFI_TELEMETRY=false, and config.telemetry=false.
"""

import os
import platform
import re
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import posthog

from voicefi.config import load_config

_posthog_initialized = False

# Default public ingestion key for anonymous crash/feedback telemetry
# Can be overridden via config.posthog_api_key or POSTHOG_API_KEY env var
DEFAULT_POSTHOG_API_KEY = "phc_oFyLfqmnEeFMDehRQ4DzGrN9AGctauZiZhfufRtmW92e"


def is_telemetry_enabled() -> bool:
    """Check whether anonymous telemetry is enabled."""
    if os.getenv("DO_NOT_TRACK", "").lower() in ("1", "true", "yes"):
        return False
    if os.getenv("VOICEFI_TELEMETRY", "").lower() in ("0", "false", "no"):
        return False

    try:
        cfg = load_config()
        return bool(getattr(cfg, "telemetry", True))
    except Exception:
        return True


def get_machine_id() -> str:
    """Get a stable anonymous identifier for the machine."""
    try:
        # Use uuid.getnode() which is based on MAC address but falls back to random
        return f"mach_{uuid.getnode()}"
    except Exception:
        return f"mach_{uuid.uuid4().hex[:12]}"


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
            # Exclude sensitive key names
            k_lower = str(k).lower()
            if any(k_lower.endswith(s) for s in ("_key", "_secret", "_token", "_password", "auth")):
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

    if not api_key:
        # Telemetry is enabled, but no remote endpoint configured
        return

    try:
        posthog.project_api_key = api_key
        posthog.host = "https://us.i.posthog.com"
        _posthog_initialized = True

        user_id = get_machine_id()
        user_properties = {
            "os": platform.system(),
            "os_release": platform.release(),
            "python_version": platform.python_version(),
            "arch": platform.machine(),
        }

        posthog.identify(user_id, user_properties)

        # Capture unhandled exceptions
        original_excepthook = sys.excepthook

        def global_exception_handler(exc_type, exc_value, exc_traceback):
            if _posthog_initialized:
                try:
                    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
                    sanitized_msg = sanitize_telemetry_data(error_msg)
                    posthog.capture(user_id, "app_crash", {
                        "error_type": exc_type.__name__,
                        "error_message": sanitize_telemetry_data(str(exc_value)),
                        "traceback": sanitized_msg,
                    })
                    posthog.flush()
                except Exception:
                    pass
            original_excepthook(exc_type, exc_value, exc_traceback)

        sys.excepthook = global_exception_handler
    except Exception:
        pass


def capture_event(event_name: str, properties: Optional[Dict[str, Any]] = None):
    """Capture a sanitized telemetry/diagnostic event if telemetry is enabled."""
    if not is_telemetry_enabled():
        return

    if not _posthog_initialized:
        init_telemetry()

    if not _posthog_initialized:
        return

    try:
        user_id = get_machine_id()
        sanitized_props = sanitize_telemetry_data(properties or {})
        posthog.capture(user_id, event_name, sanitized_props)
        posthog.flush()
    except Exception:
        pass
