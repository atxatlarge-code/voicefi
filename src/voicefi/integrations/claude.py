"""
Claude Code lifecycle hook and transcript integration.
Listens to Claude Code Stop events, extracts assistant turns, speaks aloud with Guy persona,
and captures voice response with hands-free microphone turn-handoff.
Hardened with recursion guards, kill switch, terminal window focus verification,
and atomic backup handling.
"""

import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts import get_tts_engine, stop_all_speech
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder, resolve_barge_in_mode
from voicefi.audio.chimes import play_chime
from voicefi.integrations.injector import (
    inject_text_to_active_app,
    inject_text_to_claude,
    is_frontmost_app_a_terminal,
    get_frontmost_app_name,
    set_clipboard_text,
)
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.integrations.conversations import (
    claim_turn,
    save_session_cookie,
    pop_mobile_turn_origin,
    has_active_companion_client,
)


def find_recent_claude_sessions(limit: int = 10, base_dir: Optional[Path] = None) -> list[Path]:
    """Find the most recently modified Claude Code session JSONL files."""
    claude_dir = base_dir or (Path.home() / ".claude")
    projects_dir = claude_dir / "projects"

    if not projects_dir.is_dir():
        return []

    candidate_files = []
    try:
        for p in projects_dir.glob("*/*.jsonl"):
            if p.is_file() and p.stat().st_size > 0:
                candidate_files.append((p.stat().st_mtime, p))
    except Exception as e:
        print(f"[Claude] Error finding project sessions: {e}", file=sys.stderr)
        return []

    if not candidate_files:
        return []

    candidate_files.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in candidate_files[:limit]]


def find_latest_claude_session(base_dir: Optional[Path] = None) -> Optional[Path]:
    """Find the most recently modified Claude Code session JSONL file."""
    sessions = find_recent_claude_sessions(limit=1, base_dir=base_dir)
    return sessions[0] if sessions else None


def extract_latest_claude_summary(
    session_path: Optional[Path] = None,
    max_words: int = 25,
) -> str:
    """
    Extract the latest assistant response from a Claude Code session JSONL file.
    Cleans markdown and code blocks to produce a crisp spoken soundbite.
    """
    target_path = session_path or find_latest_claude_session()
    if not target_path or not target_path.is_file():
        return "Claude finished the task. Ready for your input."

    last_assistant_text = ""
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "assistant":
                        msg = obj.get("message", {})
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            text_parts = []
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    text_parts.append(block.get("text", ""))
                                elif isinstance(block, str):
                                    text_parts.append(block)
                            if text_parts:
                                last_assistant_text = " ".join(text_parts).strip()
                        elif isinstance(content, str):
                            last_assistant_text = content.strip()
                except Exception:
                    continue
    except Exception as e:
        print(f"[Claude] Error reading session JSONL: {e}", file=sys.stderr)

    if not last_assistant_text:
        return "Claude is ready for your next instruction."

    return clean_markdown_for_speech(last_assistant_text, max_words=max_words)


def handle_claude_stop_hook(
    payload: Dict[str, Any],
    config: Optional[VoiceFiConfig] = None,
) -> Dict[str, Any]:
    """
    Handle Claude Code turn-completion Stop hook.
    1. Checks recursion & enabled guards
    2. Extracts latest assistant message
    3. Speaks aloud in Claude's voice persona (default: Guy)
    4. Auto-opens microphone with VAD and transcribes
    5. Checks terminal focus before pasting to prevent misdirected text
    """
    # Guard 1: Prevent recursive loop if Stop hook was triggered during hook processing
    if isinstance(payload, dict) and payload.get("stop_hook_active"):
        return {"status": "skipped_recursive"}

    cfg = config or load_config()

    # Guard 2: Instant pause kill-switch check
    if not cfg.enabled:
        return {"status": "paused"}

    # 1. Extract summary text from payload or session file
    text_to_speak = ""
    session_file = None
    if isinstance(payload, dict):
        if payload.get("session_path"):
            session_file = Path(payload["session_path"])
        if payload.get("message"):
            text_to_speak = str(payload["message"])
        elif payload.get("text"):
            text_to_speak = str(payload["text"])
        elif payload.get("content"):
            text_to_speak = str(payload["content"])

    if not session_file:
        session_file = find_latest_claude_session()

    if not text_to_speak:
        text_to_speak = extract_latest_claude_summary(
            session_path=session_file,
            max_words=cfg.claude.max_spoken_words,
        )

    # Guard 3: Session turn deduplication
    conv_id = session_file.stem if session_file else "claude_active"
    cid_key = f"claude_{conv_id}" if not conv_id.startswith("claude_") else conv_id

    # Update session cookie so Mobile Companion knows Claude is the active agent
    save_session_cookie(
        conv_id=cid_key,
        transcript_path=str(session_file) if session_file else None,
        title=f"Claude ({conv_id[:8]})",
        engine="claude",
    )

    if not claim_turn(conv_id, text_to_speak) and not claim_turn(cid_key, text_to_speak):
        return {"status": "skipped_duplicate"}

    print(f"\n🎭 [Claude Hook] Turn complete: \"{text_to_speak}\"")

    if text_to_speak:
        try:
            from voicefi.audio.echo_canceller import record_agent_spoken
            record_agent_spoken(text_to_speak)
        except Exception:
            pass

    # Check Mobile Companion audio routing
    routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
    mute_mac_active = getattr(getattr(cfg, "companion", None), "mute_mac_when_companion_active", False)
    is_mobile = pop_mobile_turn_origin(conv_id) or pop_mobile_turn_origin(cid_key)

    if routing == "phone_only":
        return {"status": "phone_only", "agent": "claude"}
    elif routing in ("smart", "origin_only"):
        if is_mobile:
            # Turn originated from mobile phone companion -> phone handles speech & mic exclusively.
            return {"status": "mobile_handled", "agent": "claude"}
        if routing == "smart" and mute_mac_active and has_active_companion_client():
            # Mac suppressed because mobile companion is actively connected
            return {"status": "mac_muted", "agent": "claude"}

    # 2. Speak the soundbite aloud using Claude's voice persona (Guy)
    if cfg.claude.read_summary_aloud:
        tts_engine = get_tts_engine(cfg, agent_name="claude")
        try:
            tts_engine.speak(text_to_speak, block=True)
        except Exception as e:
            print(f"[Claude Hook] Speech error: {e}", file=sys.stderr)

    # 3. If auto_listen is disabled, finish early
    if not cfg.claude.auto_listen:
        return {"status": "spoken", "agent": "claude"}

    # 4. Play start listening chime
    if cfg.audio_cues.enabled:
        play_chime(cfg.audio_cues.start_chime, block=False)

    # 5. Record user response with VAD
    print("🎙️ Listening for response to Claude... (speak and then pause)")
    recorder = AudioRecorder(
        sample_rate=cfg.vad.sample_rate,
        energy_threshold=cfg.vad.energy_threshold,
        silence_duration=cfg.vad.silence_duration,
        max_record_seconds=cfg.vad.max_record_seconds,
    )

    try:
        audio_data, temp_wav = recorder.record_speech_auto(
            on_speech_start=lambda: print("🗣️ Speech detected..."),
        )
    except Exception as e:
        print(f"[Claude Hook] Recording error: {e}", file=sys.stderr)
        return {"status": "error", "error": str(e)}

    # 6. Transcribe user speech
    stt_engine = get_stt_engine(cfg)
    try:
        transcription = stt_engine.transcribe(temp_wav)
    finally:
        temp_wav.unlink(missing_ok=True)

    if not transcription or not transcription.strip():
        print("⚠️ No speech detected.")
        return {"status": "no_speech"}

    print(f"\n📝 Transcribed: {transcription}\n")

    # 7. Safe Window Injection: Inject directly into Claude terminal/app
    if cfg.claude.inject_to_active_window:
        success = inject_text_to_claude(transcription, submit_enter=cfg.claude.auto_submit)
        if success:
            print("Sent to active conversation.")
        else:
            print("⚠️ Injection failed — text left on clipboard.")

    # 8. Play sent chime
    if cfg.audio_cues.enabled:
        play_chime(cfg.audio_cues.sent_chime, block=False)

    return {"status": "transcribed", "text": transcription, "agent": "claude"}


def install_claude_hook(
    settings_path: Optional[Path] = None,
    bin_path: Optional[str] = None,
) -> Path:
    """
    Register VoiceFi Stop hook in ~/.claude/settings.json.
    Creates .bak backup and writes atomically via os.replace.
    """
    import shutil
    target_path = settings_path or (Path.home() / ".claude" / "settings.json")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    settings_data: Dict[str, Any] = {}
    if target_path.is_file():
        # Backup original settings.json once if no backup exists
        backup_path = target_path.with_name(f"{target_path.stem}.json.bak")
        if not backup_path.exists():
            try:
                import shutil
                shutil.copy2(target_path, backup_path)
            except Exception as e:
                print(f"[Claude Hook] Notice: could not write settings backup: {e}", file=sys.stderr)

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                settings_data = json.load(f) or {}
        except Exception:
            settings_data = {}

    executable = bin_path or shutil.which("vifi") or shutil.which("voicefi") or "vifi"
    hook_command = f"{executable} hook --agent claude"

    # Ensure hooks dict exists
    if "hooks" not in settings_data or not isinstance(settings_data["hooks"], dict):
        settings_data["hooks"] = {}

    # Register Stop hook for Claude Code
    stop_hooks = settings_data["hooks"].get("Stop", [])
    if not isinstance(stop_hooks, list):
        stop_hooks = []

    # Check if voicefi hook is already present
    already_installed = False
    for item in stop_hooks:
        if isinstance(item, dict):
            if "voicefi" in str(item) or "vifi" in str(item):
                already_installed = True
                break

    if not already_installed:
        stop_hooks.append({
            "matcher": ".*",
            "hooks": [
                {
                    "type": "command",
                    "command": hook_command,
                    "timeout": 60,
                }
            ],
        })

    settings_data["hooks"]["Stop"] = stop_hooks

    # Atomic write via temp file
    temp_file = target_path.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(settings_data, f, indent=2)
    os.replace(temp_file, target_path)

    return target_path
