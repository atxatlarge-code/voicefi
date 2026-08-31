"""
Feedback and diagnostics subsystem for VoiceFi.
Allows AI agents and developers to submit bug reports, voice quality tickets, and feature requests.
"""

import json
import os
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from voicefi import __version__
from voicefi.config import load_config, get_default_config_path


def get_feedback_dir() -> Path:
    """Return the feedback directory (~/.voicefi/feedback/)."""
    fb_dir = Path.home() / ".voicefi" / "feedback"
    fb_dir.mkdir(parents=True, exist_ok=True)
    return fb_dir


def collect_system_diagnostics() -> Dict[str, Any]:
    """Collect non-sensitive environment diagnostics for troubleshooting."""
    config = load_config()
    from voicefi.audio.device import get_audio_device_profile

    audio_prof = get_audio_device_profile()

    diagnostics: Dict[str, Any] = {
        "voicefi_version": __version__,
        "python_version": sys.version.split()[0],
        "os_platform": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.machine(),
        "default_input": audio_prof.get("default_input"),
        "default_output": audio_prof.get("default_output"),
        "is_builtin_speakers": audio_prof.get("is_builtin_speakers"),
        "is_headphones_active": audio_prof.get("is_headphones_active"),
        "tts_provider": config.tts.provider,
        "tts_voice": config.tts.voice,
        "tts_rate": config.tts.rate,
        "stt_provider": config.stt.provider,
        "stt_model": config.stt.model_size,
        "vad_mode": config.vad.mode,
        "vad_barge_in": config.vad.barge_in,
        "vad_energy_threshold": config.vad.energy_threshold,
        "configured_agents": list(config.agents.keys()),
        "configured_subagents": list(config.subagents.keys()),
    }
    return diagnostics


def submit_feedback(
    title: str,
    details: str = "",
    category: str = "general",
    agent_id: Optional[str] = None,
    include_diagnostics: bool = True,
) -> Dict[str, Any]:
    """
    Submit and record a feedback / bug report item.

    Args:
        title: Summary of the issue or feature request.
        details: Detailed explanation or reproduction steps.
        category: 'bug' | 'feature' | 'voice_quality' | 'latency' | 'general'
        agent_id: Identifier of the agent submitting (e.g. 'antigravity', 'claude_code', or None)
        include_diagnostics: Whether to attach hardware/OS diagnostics.
    """
    if not title or not title.strip():
        raise ValueError("Feedback title cannot be empty.")

    feedback_id = f"fb_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    record: Dict[str, Any] = {
        "id": feedback_id,
        "timestamp": now_iso,
        "category": category.lower(),
        "title": title.strip(),
        "details": details.strip() if details else "",
        "agent_id": agent_id or "user",
    }

    if include_diagnostics:
        try:
            record["diagnostics"] = collect_system_diagnostics()
        except Exception as e:
            record["diagnostics"] = {"error": f"Failed to collect diagnostics: {e}"}

    # 1. Save individual JSON record
    fb_dir = get_feedback_dir()
    fb_dir.mkdir(parents=True, exist_ok=True)
    item_path = fb_dir / f"{feedback_id}.json"
    item_path.parent.mkdir(parents=True, exist_ok=True)
    with open(item_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)

    # 2. Append to centralized feedback.jsonl log
    log_path = Path.home() / ".voicefi" / "feedback.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # 3. Dispatch sanitized event to remote telemetry if enabled
    try:
        from voicefi.telemetry import capture_event

        capture_event("feedback_submitted", record)
    except Exception:
        pass

    return record


def list_feedback(limit: int = 10) -> List[Dict[str, Any]]:
    """List recent feedback records from newest to oldest."""
    log_path = Path.home() / ".voicefi" / "feedback.jsonl"
    if not log_path.is_file():
        return []

    records = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return []

    records.reverse()
    return records[:limit]
