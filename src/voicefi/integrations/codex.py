"""
OpenAI Codex and ChatGPT Desktop lifecycle hook and MCP integration for VoiceFi.
Provides automatic MCP server registration in ~/.codex/config.toml,
CLI discovery, and lifecycle hook handling.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts import get_tts_engine
from voicefi.tts.base import (
    set_cross_process_hud_state,
    clear_cross_process_hud_state,
    escape_to_stop_speech,
)
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.integrations.conversations import (
    claim_turn,
    save_session_cookie,
    pop_mobile_turn_origin,
    has_active_companion_client,
)
from voicefi.integrations.injector import inject_text_to_chatgpt


def get_codex_cli_path() -> Optional[str]:
    """Find the path to the Codex CLI binary."""
    bundled = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
    if bundled.is_file() and os.access(str(bundled), os.X_OK):
        return str(bundled)
    return shutil.which("codex")


def install_codex_mcp(
    bin_path: Optional[str] = None,
    config_path: Optional[Path] = None,
) -> bool:
    """
    Register VoiceFi MCP server in ~/.codex/config.toml for Codex and ChatGPT Desktop.
    Uses the official codex CLI if available, with TOML file update fallback.
    """
    codex_home = Path.home() / ".codex"
    target_config = config_path or (codex_home / "config.toml")
    codex_home.mkdir(parents=True, exist_ok=True)

    executable = bin_path or shutil.which("voicefi") or shutil.which("vifi") or "voicefi"

    # 1. Try CLI registration first if codex binary is available
    cli_path = get_codex_cli_path()
    if cli_path:
        try:
            res = subprocess.run(
                [cli_path, "mcp", "add", "voicefi", "--", executable, "mcp"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

    # 2. Fallback to editing config.toml directly
    try:
        content = ""
        if target_config.is_file():
            content = target_config.read_text(encoding="utf-8")

        if "[mcp_servers.voicefi]" not in content:
            block = f'\n[mcp_servers.voicefi]\ncommand = "{executable}"\nargs = ["mcp"]\n'
            target_config.write_text(content + block, encoding="utf-8")
        return True
    except Exception as e:
        print(f"[Codex] Error registering MCP in config.toml: {e}", file=sys.stderr)
        return False


def install_codex_hook(
    bin_path: Optional[str] = None,
    hooks_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Register VoiceFi Stop hook in ~/.codex/hooks.json and ~/.codex/config.toml (notify).
    """
    codex_home = Path.home() / ".codex"
    target_hooks = hooks_path or (codex_home / "hooks.json")
    target_config = config_path or (codex_home / "config.toml")
    codex_home.mkdir(parents=True, exist_ok=True)

    executable = bin_path or shutil.which("voicefi") or shutil.which("vifi") or "voicefi"
    hook_command = f"{executable} hook --agent codex"

    # 1. Update ~/.codex/hooks.json
    data: Dict[str, Any] = {}
    if target_hooks.is_file():
        try:
            with open(target_hooks, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            data = {}

    if "hooks" not in data or not isinstance(data["hooks"], dict):
        data["hooks"] = {}

    stop_hooks = data["hooks"].get("Stop", [])
    if not isinstance(stop_hooks, list):
        stop_hooks = []

    has_voicefi = False
    for group in stop_hooks:
        if isinstance(group, dict):
            for h in group.get("hooks", []):
                if isinstance(h, dict) and "voicefi" in h.get("command", ""):
                    h["command"] = hook_command
                    has_voicefi = True

    if not has_voicefi:
        stop_hooks.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command,
                        "timeout": 60,
                    }
                ]
            }
        )

    data["hooks"]["Stop"] = stop_hooks

    temp_file = target_hooks.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, target_hooks)

    # 2. Update notify in ~/.codex/config.toml
    try:
        if target_config.is_file():
            toml_text = target_config.read_text(encoding="utf-8")
            notify_entry = f'notify = [\n    "{executable}",\n    "hook",\n    "--agent",\n    "codex",\n    "turn-ended",\n]\n'
            import re

            if re.search(r"notify\s*=\s*\[[^\]]*\]", toml_text):
                toml_text = re.sub(r"notify\s*=\s*\[[^\]]*\]\s*", notify_entry, toml_text, count=1)
            else:
                toml_text = notify_entry + toml_text
            target_config.write_text(toml_text, encoding="utf-8")
    except Exception as e:
        print(f"[Codex] Notice updating notify in config.toml: {e}", file=sys.stderr)

    return target_hooks


def remove_codex_hook(
    hooks_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> bool:
    """Remove VoiceFi hooks from ~/.codex/hooks.json and ~/.codex/config.toml."""
    codex_home = Path.home() / ".codex"
    target_hooks = hooks_path or (codex_home / "hooks.json")
    target_config = config_path or (codex_home / "config.toml")

    # 1. Clean hooks.json
    if target_hooks.is_file():
        try:
            with open(target_hooks, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            if "hooks" in data and "Stop" in data["hooks"]:
                stop_hooks = data["hooks"]["Stop"]
                new_stop = []
                for group in stop_hooks:
                    if isinstance(group, dict):
                        inner = [
                            h
                            for h in group.get("hooks", [])
                            if isinstance(h, dict) and "voicefi" not in h.get("command", "")
                        ]
                        if inner:
                            group["hooks"] = inner
                            new_stop.append(group)
                    else:
                        new_stop.append(group)
                data["hooks"]["Stop"] = new_stop

            temp_file = target_hooks.with_suffix(".json.tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, target_hooks)
        except Exception:
            pass

    # 2. Clean notify from config.toml if pointing to voicefi
    if target_config.is_file():
        try:
            toml_text = target_config.read_text(encoding="utf-8")
            import re

            if "voicefi" in toml_text:
                toml_text = re.sub(r"notify\s*=\s*\[[^\]]*voicefi[^\]]*\]\s*", "", toml_text)
                target_config.write_text(toml_text, encoding="utf-8")
        except Exception:
            pass

    return True


def handle_codex_stop_hook(
    payload: Dict[str, Any],
    config: Optional[VoiceFiConfig] = None,
) -> Dict[str, Any]:
    """
    Handle OpenAI Codex turn-completion Stop / notify hook.
    1. Extracts latest assistant message
    2. Speaks aloud in Codex's voice persona (Emma)
    3. Auto-opens microphone with VAD and transcribes if auto_listen enabled
    4. Injects voice transcription into ChatGPT Desktop / Codex prompt
    """
    cfg = config or load_config()

    # Guard: Instant kill-switch check
    if (
        not cfg.enabled
        or not getattr(cfg.hooks, "enabled", True)
        or not getattr(cfg.hooks, "codex", True)
    ):
        return {"status": "paused"}
    if not getattr(cfg.integrations, "codex", True) and not getattr(
        cfg.integrations, "chatgpt", True
    ):
        return {"status": "disabled"}

    codex_cfg = getattr(cfg, "codex", None)
    read_aloud = getattr(codex_cfg, "read_summary_aloud", True) if codex_cfg else True
    auto_listen = getattr(codex_cfg, "auto_listen", False) if codex_cfg else False
    max_words = getattr(codex_cfg, "max_spoken_words", 60) if codex_cfg else 60

    if not auto_listen and not read_aloud:
        return {"status": "disabled"}

    # Extract summary text from payload
    text_to_speak = ""
    thread_id = "codex_active"

    if isinstance(payload, dict):
        thread_id = str(
            payload.get("thread-id")
            or payload.get("thread_id")
            or payload.get("conversationId")
            or "codex_active"
        )
        if payload.get("last-assistant-message"):
            text_to_speak = str(payload["last-assistant-message"])
        elif payload.get("message"):
            text_to_speak = str(payload["message"])
        elif payload.get("text"):
            text_to_speak = str(payload["text"])
        elif payload.get("content"):
            text_to_speak = str(payload["content"])

    if not text_to_speak:
        return {"status": "empty_turn"}

    # Clean markdown for natural speech
    cleaned = clean_markdown_for_speech(text_to_speak)
    words = cleaned.split()
    if len(words) > max_words:
        cleaned = " ".join(words[:max_words]) + "..."

    # Deduplicate turn
    cid_key = f"codex_{thread_id}" if not thread_id.startswith("codex_") else thread_id
    if not claim_turn(thread_id, cleaned) and not claim_turn(cid_key, cleaned):
        return {"status": "skipped_duplicate"}

    # Update session cookie so Mobile Companion knows Codex is the active agent
    save_session_cookie(
        conv_id=cid_key,
        title=f"Codex ({thread_id[:8]})",
        engine="codex",
    )

    print(f'\n✳️ [Codex Hook] Turn complete: "{cleaned}"')

    try:
        from voicefi.audio.echo_canceller import record_agent_spoken

        record_agent_spoken(cleaned)
    except Exception:
        pass

    # Check Mobile Companion audio routing
    routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
    mute_mac_active = getattr(
        getattr(cfg, "companion", None), "mute_mac_when_companion_active", False
    )
    is_mobile = pop_mobile_turn_origin(thread_id) or pop_mobile_turn_origin(cid_key)

    if routing == "phone_only":
        return {"status": "phone_only", "agent": "codex"}
    elif routing in ("smart", "origin_only"):
        if is_mobile:
            return {"status": "mobile_handled", "agent": "codex"}
        if routing == "smart" and mute_mac_active and has_active_companion_client():
            return {"status": "mac_muted", "agent": "codex"}

    # Speak the soundbite aloud using Codex's voice persona (Emma)
    hook_start_time = time.time()
    tts_engine = None
    if read_aloud:
        tts_engine = get_tts_engine(cfg, agent_name="codex")
        try:
            with escape_to_stop_speech():
                tts_engine.speak(cleaned, block=True)
        except Exception as e:
            print(f"[Codex Hook] Speech error: {e}", file=sys.stderr)

        from voicefi.tts.base import is_speech_interrupted

        if is_speech_interrupted(hook_start_time):
            clear_cross_process_hud_state()
            return {"status": "interrupted", "agent": "codex"}

    # If auto_listen is disabled, finish early
    if not auto_listen:
        if read_aloud:
            dur_ms = int((time.time() - hook_start_time) * 1000)
            try:
                from voicefi.telemetry import capture_voice_interaction

                capture_voice_interaction(
                    trigger="hook",
                    duration_ms=dur_ms,
                    success=True,
                    agent="codex",
                    voice=getattr(tts_engine, "voice", "Emma"),
                    chars_count=len(cleaned),
                )
            except Exception:
                pass
        return {"status": "spoken", "agent": "codex"}

    # Play start listening chime
    if cfg.audio_cues.enabled:
        play_chime(cfg.audio_cues.start_chime, block=False)

    # Record user response with VAD
    print("🎙️ Listening for response to Codex... (speak and then pause)")
    set_cross_process_hud_state("listening", agent_name="codex", user_name=cfg.user_name)
    recorder = AudioRecorder(
        sample_rate=cfg.vad.sample_rate,
        energy_threshold=cfg.vad.energy_threshold,
        silence_duration=cfg.vad.silence_duration,
        max_record_seconds=cfg.vad.max_record_seconds,
    )

    def _on_live(txt: str):
        set_cross_process_hud_state(
            "listening", text=txt, agent_name="codex", user_name=cfg.user_name, live_stream=True
        )
        try:
            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

            UnifiedDynamicIslandHUD.get_instance().update_live_transcription(
                txt, user_name=cfg.user_name
            )
        except Exception:
            pass

    recorder.on_live_transcript = _on_live
    audio_path = recorder.record()
    clear_cross_process_hud_state()

    if is_speech_interrupted(hook_start_time):
        if audio_path and audio_path.exists():
            audio_path.unlink(missing_ok=True)
        return {"status": "cancelled"}

    if not audio_path or not audio_path.exists():
        print("⚠️ No speech captured.")
        return {"status": "no_audio"}

    # Transcribe speech
    print("⏳ Transcribing speech...")
    set_cross_process_hud_state(
        "thinking", text="Transcribing...", agent_name="codex", user_name=cfg.user_name
    )
    stt_engine = get_stt_engine(cfg)
    try:
        transcribed_text = stt_engine.transcribe(audio_path)
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink(missing_ok=True)
    clear_cross_process_hud_state()

    if is_speech_interrupted(hook_start_time):
        return {"status": "cancelled"}

    if not transcribed_text or not transcribed_text.strip():
        print("⚠️ Empty transcription.")
        return {"status": "empty_transcript"}

    print(f'🗣️ User: "{transcribed_text}"')

    # Inject into ChatGPT / Codex Desktop
    auto_sub = getattr(codex_cfg, "auto_submit", False) if codex_cfg else False
    inject_text_to_chatgpt(transcribed_text, submit_enter=auto_sub)

    return {"status": "injected", "text": transcribed_text, "agent": "codex"}
