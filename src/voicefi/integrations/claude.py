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
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts import get_tts_engine, stop_all_speech
from voicefi.tts.base import (
    set_cross_process_hud_state,
    clear_cross_process_hud_state,
    get_cross_process_hud_state,
    escape_to_stop_speech,
)
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder, resolve_barge_in_mode
from voicefi.audio.chimes import play_chime
from voicefi.integrations.injector import (
    inject_text_to_active_app,
    inject_text_to_claude,
    send_message_to_antigravity,
    is_frontmost_app_a_terminal,
    get_frontmost_app_name,
    set_clipboard_text,
)
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.integrations.conversations import (
    claim_turn,
    mark_turn_completed,
    save_session_cookie,
    pop_mobile_turn_origin,
    peek_mobile_turn_origin,
    get_claimed_turn_origin,
    has_active_companion_client,
    mark_turn_spoken_on_mac,
)
from voicefi.integrations.active_listening import (
    ActiveListeningEngine,
    SpokenIntentCategory,
    SpokenTargetChannel,
)
from voicefi.audio.echo_canceller import is_acoustic_echo


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
    max_words: Optional[int] = None,
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
    if (
        not cfg.enabled
        or not getattr(cfg.hooks, "enabled", True)
        or not getattr(cfg.hooks, "claude", True)
    ):
        return {"status": "paused"}
    if not getattr(cfg.integrations, "claude_code", True):
        return {"status": "disabled"}
    if not cfg.claude.auto_listen and not cfg.claude.read_summary_aloud:
        return {"status": "disabled"}

    from voicefi.audio.meeting_detection import is_user_on_call

    if is_user_on_call():
        print("[ClaudeHook] User is on a call. Skipping spoken feedback and auto-listen.")
        return {"status": "on_call"}

    respect_media = getattr(getattr(cfg, "tts", None), "respect_media_playback", True)
    if respect_media:
        try:
            from voicefi.audio.media_detection import is_active_media_playing, wait_for_media_completion

            if is_active_media_playing():
                media_timeout = getattr(getattr(cfg, "tts", None), "media_pause_timeout", 600.0)
                cleared = wait_for_media_completion(max_wait_seconds=media_timeout)
                if not cleared:
                    print(
                        "[ClaudeHook] 🎬 Media clip still playing after timeout. Skipping spoken feedback and auto-listen."
                    )
                    return {"status": "media_playing"}
        except Exception:
            pass

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

    if not claim_turn(conv_id, text_to_speak, delivered_via="hook") and not claim_turn(cid_key, text_to_speak, delivered_via="hook"):
        return {"status": "skipped_duplicate"}

    try:
        print(f'\n🎭 [Claude Hook] Turn complete: "{text_to_speak}"')

        if text_to_speak:
            try:
                from voicefi.audio.echo_canceller import record_agent_spoken

                record_agent_spoken(text_to_speak)
            except Exception:
                pass

        # Check Mobile Companion audio routing
        routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
        mute_mac_active = getattr(
            getattr(cfg, "companion", None), "mute_mac_when_companion_active", True
        )
        is_mobile = (
            get_claimed_turn_origin(conv_id, text_to_speak) == "mobile"
            or get_claimed_turn_origin(cid_key, text_to_speak) == "mobile"
            or peek_mobile_turn_origin(conv_id)
            or peek_mobile_turn_origin(cid_key)
            or pop_mobile_turn_origin(conv_id)
            or pop_mobile_turn_origin(cid_key)
        )

        if routing == "phone_only":
            return {"status": "phone_only", "agent": "claude"}
        elif routing == "origin_only":
            if is_mobile:
                # Turn originated from mobile phone companion and user requested origin_only
                return {"status": "mobile_handled", "agent": "claude"}
        elif routing == "smart":
            if is_mobile:
                # Turn originated from mobile companion -> only speak on phone, suppress Mac
                return {"status": "mobile_handled", "agent": "claude"}
            if mute_mac_active and has_active_companion_client(require_mobile=True):
                # Mac suppressed when mobile companion client is actively connected and mute_mac enabled
                return {"status": "mac_muted", "agent": "claude"}

        # 2. Speak the soundbite aloud using Claude's voice persona (Guy / Steffan)
        hook_start_time = time.time()
        agent_name = (
            payload.get("agent")
            if isinstance(payload, dict) and payload.get("agent")
            else "claude"
        )
        voice_override = payload.get("voice") if isinstance(payload, dict) else None
        if cfg.claude.read_summary_aloud:
            mark_turn_spoken_on_mac(conv_id, text_to_speak)
            mark_turn_spoken_on_mac(cid_key, text_to_speak)
            tts_engine = get_tts_engine(
                cfg,
                agent_name=agent_name,
                voice_override=voice_override,
                app_name="Claude",
                conv_id=conv_id,
            )
            try:
                set_cross_process_hud_state(
                    "speaking",
                    text=text_to_speak,
                    agent_name=agent_name,
                    persona_name=getattr(tts_engine, "voice", "Guy"),
                    app_name="Claude",
                    conv_id=conv_id,
                )
                with escape_to_stop_speech(
                    agent_name=agent_name, app_name="Claude", conv_id=conv_id
                ):
                    tts_engine.stream_speak(text_to_speak, block=True)
            finally:
                clear_cross_process_hud_state()

        # 3. Check if we should auto-open microphone
        try:
            from voicefi.audio.media_detection import is_active_media_playing

            if is_active_media_playing():
                print(
                    "[Claude Hook] 🎬 Media playback active. Skipping auto-listen handoff to avoid feedback."
                )
                return {"status": "media_playing", "agent": "claude"}
        except Exception:
            pass

        if not cfg.claude.auto_listen or is_mobile:
            if is_mobile:
                print(
                    "[Claude Hook] 📱 Turn originated from mobile companion — skipping Mac desktop mic auto-listen."
                )
            if cfg.claude.read_summary_aloud:
                dur_ms = int((time.time() - hook_start_time) * 1000)
                try:
                    from voicefi.telemetry import capture_voice_interaction

                    capture_voice_interaction(
                        trigger="hook",
                        duration_ms=dur_ms,
                        success=True,
                        agent="claude",
                        voice=getattr(tts_engine, "voice", "Guy"),
                        chars_count=len(text_to_speak) if text_to_speak else 0,
                    )
                except Exception:
                    pass
            return {"status": "mobile_handled" if is_mobile else "spoken", "agent": "claude"}

        # 4. Play start listening chime with settle window to avoid mic bleed
        if cfg.audio_cues.enabled:
            play_chime(cfg.audio_cues.start_chime, block=True)
            time.sleep(0.15)

        # 5. Record user response with VAD
        print("🎙️ Listening for response to Claude... (speak and then pause)")
        fb_loop = getattr(getattr(cfg, "proactive", None), "feedback_loop", None)
        listen_timeout = getattr(fb_loop, "timeout_seconds", 12.0) if fb_loop else 12.0

        recorder = AudioRecorder(
            sample_rate=cfg.vad.sample_rate,
            energy_threshold=cfg.vad.energy_threshold,
            silence_duration=cfg.vad.silence_duration,
            max_record_seconds=cfg.vad.max_record_seconds,
            vad_engine=getattr(cfg.vad, "engine", "auto"),
            speech_threshold=getattr(cfg.vad, "speech_threshold", 0.37),
        )

        def _on_live(txt: str):
            set_cross_process_hud_state(
                "listening",
                text=txt,
                agent_name="claude",
                user_name=cfg.user_name,
                live_stream=True,
                app_name="Claude",
                conv_id=conv_id,
            )
            try:
                from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

                UnifiedDynamicIslandHUD.get_instance().update_live_transcription(
                    txt, user_name=cfg.user_name
                )
            except Exception:
                pass

        def _on_tick(energy: float, conf: float = 0.0, is_spk: bool = False):
            try:
                from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

                UnifiedDynamicIslandHUD.get_instance().update_audio_level(energy, conf, is_spk)
            except Exception:
                pass

        try:
            audio_data, temp_wav = recorder.record_speech_auto(
                on_speech_start=lambda: set_cross_process_hud_state(
                    "hearing",
                    agent_name="claude",
                    user_name=cfg.user_name,
                    app_name="Claude",
                    conv_id=conv_id,
                ),
                on_live_transcript=_on_live,
                on_listening_tick=_on_tick,
                timeout=listen_timeout,
            )
        except Exception as e:
            print(f"[Claude Hook] Recording error: {e}", file=sys.stderr)
        from voicefi.tts.base import is_speech_interrupted

        if is_speech_interrupted(hook_start_time):
            if temp_wav and Path(temp_wav).is_file():
                Path(temp_wav).unlink(missing_ok=True)
            clear_cross_process_hud_state()
            return {"status": "cancelled"}

        if not temp_wav or not Path(temp_wav).is_file():
            print("⚠️ No speech detected.")
            clear_cross_process_hud_state()
            return {"status": "no_speech"}

        # 6. Transcribe user speech
        set_cross_process_hud_state("transcribing", agent_name="claude")
        stt_engine = get_stt_engine(cfg)
        try:
            transcription = stt_engine.transcribe(temp_wav)
        finally:
            if temp_wav and Path(temp_wav).is_file():
                Path(temp_wav).unlink(missing_ok=True)

        if is_speech_interrupted(hook_start_time):
            clear_cross_process_hud_state()
            return {"status": "cancelled"}

        if not transcription or not transcription.strip():
            print("⚠️ No speech detected.")
            clear_cross_process_hud_state()
            return {"status": "no_speech"}

        clean_t = transcription.strip()
        print(f"\n📝 Transcribed: {clean_t}\n")

        # Suppress acoustic self-echo if microphone picked up Claude's own voice
        if is_acoustic_echo(clean_t, reference_text=text_to_speak):
            print(
                f'[Claude Hook] 🛡️ Suppressed acoustic self-echo: "{clean_t}" (matched agent output)',
                flush=True,
            )
            clear_cross_process_hud_state()
            return {"status": "self_echo_suppressed"}

        eval_res = ActiveListeningEngine.evaluate(clean_t, is_ambient=False)
        print(
            f"[ActiveListening/Claude] Intent evaluation: {eval_res.category.value}",
            flush=True,
        )

        if eval_res.category == SpokenIntentCategory.CONVERSATIONAL_FILLER:
            print(f"[Claude Hook] 🤫 Ignored conversational filler: '{clean_t}'", flush=True)
            clear_cross_process_hud_state()
            return {"status": "filler_ignored"}

        target_channel = getattr(eval_res, "target_channel", SpokenTargetChannel.CLAUDE)
        routed_text = getattr(eval_res, "routed_prompt", None) or eval_res.normalized_text or clean_t

        # 7. Safe Window Injection / Cross-Agent Routing
        set_cross_process_hud_state("done", text=routed_text[:20], agent_name="claude")
        if (eval_res.target_metadata or {}).get("routed_to") == "antigravity":
            print(f"[Claude Hook] 🔀 Routing spoken prompt to Antigravity: '{routed_text}'", flush=True)
            from voicefi.integrations.conversations import get_latest_antigravity_conversation_id

            target_conv = get_latest_antigravity_conversation_id()
            send_message_to_antigravity(conv_id=target_conv, text=routed_text, sender_name="Claude")
        elif cfg.claude.inject_to_active_window:
            success = inject_text_to_claude(routed_text, submit_enter=cfg.claude.auto_submit)
            if success:
                print("Sent to active conversation.")
            else:
                print("⚠️ Injection failed — text left on clipboard.")

        # 8. Play sent chime
        if cfg.audio_cues.enabled:
            play_chime(cfg.audio_cues.sent_chime, block=False)

        if cfg.claude.read_summary_aloud:
            dur_ms = int((time.time() - hook_start_time) * 1000)
            try:
                from voicefi.telemetry import capture_voice_interaction

                capture_voice_interaction(
                    trigger="hook",
                    duration_ms=dur_ms,
                    success=True,
                    agent="claude",
                    voice="Guy",
                    chars_count=len(text_to_speak) if text_to_speak else 0,
                    user_chars=len(transcription) if transcription else 0,
                )
            except Exception:
                pass

        clear_cross_process_hud_state()
        return {"status": "transcribed", "text": transcription, "agent": "claude"}
    finally:
        try:
            state_info = get_cross_process_hud_state()
            if state_info and state_info.get("state") in ("listening", "hearing", "transcribing"):
                clear_cross_process_hud_state()
        except Exception:
            pass
        try:
            mark_turn_completed(cid_key)
        except Exception:
            pass


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
                print(
                    f"[Claude Hook] Notice: could not write settings backup: {e}", file=sys.stderr
                )

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
        stop_hooks.append(
            {
                "matcher": ".*",
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command,
                        "timeout": 60,
                    }
                ],
            }
        )

    settings_data["hooks"]["Stop"] = stop_hooks

    # Atomic write via temp file
    temp_file = target_path.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(settings_data, f, indent=2)
    os.replace(temp_file, target_path)

    return target_path


def remove_claude_hook(settings_path: Optional[Path] = None) -> bool:
    """
    Remove VoiceFi Stop hook from ~/.claude/settings.json.
    """
    target_path = settings_path or (Path.home() / ".claude" / "settings.json")
    if not target_path.is_file():
        return False

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            settings_data = json.load(f) or {}
    except Exception:
        return False

    if "hooks" not in settings_data or not isinstance(settings_data["hooks"], dict):
        return True

    stop_hooks = settings_data["hooks"].get("Stop", [])
    if isinstance(stop_hooks, list):
        new_stop_hooks = []
        for item in stop_hooks:
            item_str = json.dumps(item) if isinstance(item, dict) else str(item)
            if "voicefi" not in item_str and "vifi" not in item_str:
                new_stop_hooks.append(item)
        if new_stop_hooks:
            settings_data["hooks"]["Stop"] = new_stop_hooks
        else:
            del settings_data["hooks"]["Stop"]
            if not settings_data["hooks"]:
                del settings_data["hooks"]

    temp_file = target_path.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(settings_data, f, indent=2)
    os.replace(temp_file, target_path)
    return True


def install_claude_desktop_mcp(
    config_path: Optional[Path] = None,
    bin_path: Optional[str] = None,
) -> Optional[Path]:
    """
    Register VoiceFi MCP server in Claude Desktop's claude_desktop_config.json.
    Exposes voicefi_speak, voicefi_send, voicefi_sfx, voicefi_listen tools directly to Claude.
    """
    import shutil

    target_path = config_path or (
        Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    data: Dict[str, Any] = {}
    if target_path.is_file():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}

    executable = bin_path or shutil.which("vifi") or shutil.which("voicefi") or "vifi"
    mcp_entry = {
        "command": executable,
        "args": ["mcp"],
    }

    if "mcpServers" not in data or not isinstance(data["mcpServers"], dict):
        data["mcpServers"] = {}

    data["mcpServers"]["voicefi"] = mcp_entry

    temp_file = target_path.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, target_path)

    return target_path
