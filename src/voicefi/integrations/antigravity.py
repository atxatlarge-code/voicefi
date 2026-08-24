"""
Antigravity lifecycle hook and transcript integration.
Listens to agent Stop events, summarizes output, speaks aloud, and captures voice response.
"""

import json
import re
import sys
import threading
from pathlib import Path
from typing import Dict, Any, Optional

from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts import get_tts_engine, stop_all_speech
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.injector import inject_text_to_active_app
from voicefi.integrations.conversations import (
    save_session_cookie,
    claim_turn,
    pop_mobile_turn_origin,
    has_active_companion_client,
    set_pending_question,
    get_pending_question,
    resolve_pending_question,
    clear_pending_question,
)
from voicefi.integrations.active_listening import ActiveListeningEngine, SpokenIntentCategory


def clean_markdown_for_speech(text: str, max_words: int = 30) -> str:
    """
    Clean markdown formatting and extract punchy 1-2 sentence spoken updates/questions.
    Prioritizes trailing questions and status outcomes while stripping code/paths/tables/stacktraces.
    """
    if not text or not text.strip():
        return ""

    # 1. Bound text size to avoid regex performance bottlenecks on massive outputs
    if len(text) > 4000:
        text = text[:1000] + "\n" + text[-2000:]

    # 2. Check for raw stack traces / errors first
    if "Traceback (most recent call last):" in text or "Error:" in text:
        err_match = re.search(r"(\b[A-Za-z0-9_]*Error:\s+[^\n]+)", text)
        if err_match:
            return f"The agent encountered an error: {err_match.group(1)}."

    # 3. Strip code blocks and Markdown tables
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"\|[^\n]+\|", " ", text)  # Tables

    # 4. Normalize file paths to basenames only (/path/to/file.py -> file.py)
    text = re.sub(r"(?:/[\w.-]+)+/([\w.-]+\.[a-zA-Z0-9]+)", r"\1", text)

    # 5. Clean Markdown markup
    text = re.sub(r"`([^`]+)`", r"\1", text)             # Inline code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text) # Links -> text only
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE) # Headers
    text = re.sub(r"[*_~]{1,3}", "", text)                # Bold/Italic
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE) # Blockquotes
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)  # Unordered lists
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)  # Numbered lists

    # 6. Normalize whitespace
    text = " ".join(text.split()).strip()
    if not text:
        return ""

    # 7. Extract sentences & prioritize question/confirmation at the end
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return text[: max_words * 6]

    last_s = sentences[-1]
    
    # If the last sentence is a question, collect context backwards from the question
    if last_s.endswith("?"):
        collected = []
        current_words = 0
        for s in reversed(sentences):
            count = len(s.split())
            if current_words + count <= max_words:
                collected.insert(0, s)
                current_words += count
            else:
                break
        if collected:
            return " ".join(collected)
        words = last_s.split()
        return " ".join(words[:max_words]) + "..."

    # Otherwise assemble first 1-2 sentences up to max_words
    result = []
    current_words = 0
    for s in sentences:
        count = len(s.split())
        if current_words + count <= max_words:
            result.append(s)
            current_words += count
        else:
            break

    if result:
        return " ".join(result)
    
    # Fallback to truncated first sentence
    words = sentences[0].split()
    if len(words) > max_words:
        truncated = " ".join(words[:max_words])
        last_punct = max(truncated.rfind("."), truncated.rfind("?"), truncated.rfind("!"))
        if last_punct > len(truncated) // 2:
            return truncated[: last_punct + 1]
        return truncated + "..."
    return sentences[0]


def extract_latest_agent_summary(
    transcript_path: Path,
    max_words: int = 60,
    return_role: bool = False,
):
    """
    Extract the latest assistant response or question from transcript.jsonl.
    If return_role is True, returns (summary_text, agent_role), else returns summary_text.
    """
    if not transcript_path.is_file():
        default_msg = "I have finished the task. What would you like to do next?"
        return (default_msg, None) if return_role else default_msg

    last_model_content = ""
    detected_role: Optional[str] = None
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    step = json.loads(line)
                    step_type = step.get("type", "")
                    step_source = step.get("source", "")
                    content = step.get("content", "")
                    role = step.get("role") or step.get("agent_role")

                    if step_type == "PLANNER_RESPONSE" and content and not step.get("tool_calls"):
                        last_model_content = content
                        if role:
                            detected_role = str(role).lower()
                    elif (step_type == "PLANNER_RESPONSE" or step_source == "MODEL") and content and not last_model_content:
                        last_model_content = content
                        if role:
                            detected_role = str(role).lower()
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[Antigravity] Error reading transcript: {e}", file=sys.stderr)

    if not last_model_content:
        fallback_msg = "The process is complete and ready for your input."
        return (fallback_msg, detected_role) if return_role else fallback_msg

    cleaned = clean_markdown_for_speech(last_model_content, max_words=max_words)
    return (cleaned, detected_role) if return_role else cleaned


def handle_antigravity_stop_hook(payload: Dict[str, Any], config: Optional[VoiceFiConfig] = None) -> Dict[str, Any]:
    """
    Execute the VoiceFi loop on Antigravity Stop event.
    
    1. Summarize agent turn.
    2. Speak summary via TTS (using agent or subagent persona).
    3. Open mic, record speech with VAD.
    4. Transcribe via STT.
    5. Inject transcribed text into active window.
    """
    cfg = config or load_config()

    conv_id = payload.get("conversationId") or payload.get("conversation_id") or payload.get("conv_id") or ""
    transcript_path_str = payload.get("transcriptPath") or payload.get("transcript_path") or ""
    workspace_paths = payload.get("workspacePaths") or payload.get("workspace_paths") or []
    workspace_path = workspace_paths[0] if workspace_paths else None
    transcript_path = Path(transcript_path_str) if transcript_path_str else Path("")
    hook_agent_role = payload.get("agent_role") or payload.get("role")

    if not conv_id and transcript_path_str:
        try:
            cand = Path(transcript_path_str).parent.parent.parent.name
            if len(cand) >= 8:
                conv_id = cand
        except Exception:
            pass

    if conv_id:
        save_session_cookie(
            conv_id=conv_id,
            transcript_path=transcript_path_str,
            workspace_path=workspace_path,
        )

    summary, detected_role = extract_latest_agent_summary(
        transcript_path,
        max_words=cfg.antigravity.max_spoken_words,
        return_role=True,
    )
    active_agent = hook_agent_role or detected_role or "antigravity"

    # Track pending clarifying question / options if present
    if summary and (summary.endswith("?") or " or " in summary.lower()):
        set_pending_question(conv_id, summary)

    if summary:
        from voicefi.audio.echo_canceller import record_agent_spoken
        record_agent_spoken(summary)

    turn_sig = f"{conv_id}:{summary[:35]}"
    if not claim_turn(conv_id, turn_sig):
        # Already handled by menu bar watcher
        return {}

    routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
    mute_mac_active = getattr(getattr(cfg, "companion", None), "mute_mac_when_companion_active", False)
    is_mobile = pop_mobile_turn_origin(conv_id)

    if routing == "phone_only":
        return {}
    elif routing in ("smart", "origin_only"):
        if is_mobile:
            # Turn originated from mobile phone companion -> phone handles speech & mic exclusively.
            return {}
        if routing == "smart" and mute_mac_active and has_active_companion_client():
            # Mac suppressed because mobile companion is actively connected
            return {}

    should_speak = bool(cfg.antigravity.read_summary_aloud and summary)
    should_listen = bool(cfg.antigravity.auto_listen)
    
    from voicefi.audio.recorder import resolve_barge_in_mode
    is_barge_in_on, _ = resolve_barge_in_mode(getattr(cfg.vad, "barge_in", "auto"))
    barge_in_active = bool(should_speak and should_listen and is_barge_in_on)

    if cfg.antigravity.show_speech_popup and summary:
        try:
            from voicefi.ui.speech_hud import AgentSpeechHUD
            from voicefi.tts import find_persona
            _, resolved_voice, _ = cfg.resolve_voice(active_agent)
            persona = find_persona(resolved_voice)
            pname = persona.name if persona else resolved_voice
            pos = getattr(cfg.antigravity, "speech_popup_position", "top_center")
            AgentSpeechHUD.get_instance().show_speech(
                summary,
                agent_name=active_agent,
                role=detected_role,
                persona_name=pname,
                is_speaking=True,
                position=pos,
            )
        except Exception:
            pass

    temp_wav: Optional[Path] = None

    if barge_in_active:
        # Active Barge-In: start TTS in background thread and listen on mic for interruption
        tts = get_tts_engine(cfg, agent_name=active_agent)
        def _speak_and_finish():
            try:
                tts.stream_speak(summary, block=True)
            finally:
                if cfg.antigravity.show_speech_popup:
                    try:
                        from voicefi.ui.speech_hud import AgentSpeechHUD
                        linger = getattr(cfg.antigravity, "speech_popup_linger_seconds", 3.0)
                        AgentSpeechHUD.get_instance().finish_speech(linger_seconds=linger)
                    except Exception:
                        pass

        tts_thread = threading.Thread(
            target=_speak_and_finish,
            daemon=True,
        )
        tts_thread.start()

        def _on_barge_in():
            stop_all_speech()
            if cfg.antigravity.show_speech_popup:
                try:
                    from voicefi.ui.speech_hud import AgentSpeechHUD
                    AgentSpeechHUD.get_instance().hide()
                except Exception:
                    pass

        recorder = AudioRecorder(
            sample_rate=cfg.vad.sample_rate,
            energy_threshold=cfg.vad.energy_threshold,
            silence_duration=cfg.vad.silence_duration,
            max_record_seconds=cfg.vad.max_record_seconds,
            barge_in=cfg.vad.barge_in,
            barge_in_sensitivity=getattr(cfg.vad, "barge_in_sensitivity", 1.0),
        )

        audio_data, temp_wav = recorder.record_speech_auto(
            on_barge_in=_on_barge_in,
        )
    else:
        if should_speak:
            tts = get_tts_engine(cfg, agent_name=active_agent)
            tts.stream_speak(summary, block=True)

        if cfg.antigravity.show_speech_popup:
            try:
                from voicefi.ui.speech_hud import AgentSpeechHUD
                linger = getattr(cfg.antigravity, "speech_popup_linger_seconds", 3.0)
                AgentSpeechHUD.get_instance().finish_speech(linger_seconds=linger)
            except Exception:
                pass

        if should_listen:
            if cfg.audio_cues.enabled:
                play_chime("start", block=False)

            recorder = AudioRecorder(
                sample_rate=cfg.vad.sample_rate,
                energy_threshold=cfg.vad.energy_threshold,
                silence_duration=cfg.vad.silence_duration,
                max_record_seconds=cfg.vad.max_record_seconds,
                barge_in=False,
            )

            audio_data, temp_wav = recorder.record_speech_auto()

    if temp_wav and Path(temp_wav).is_file():
        stt = get_stt_engine(cfg)
        try:
            transcription = stt.transcribe(temp_wav)
        finally:
            Path(temp_wav).unlink(missing_ok=True)

        if transcription and transcription.strip():
            clean_t = transcription.strip()
            from voicefi.audio.echo_canceller import is_acoustic_echo
            if is_acoustic_echo(clean_t, reference_text=summary):
                print(f"[Antigravity] 🛡️ Suppressed acoustic self-echo: \"{clean_t}\" (matched agent output)")
                return {}

            pending_q = get_pending_question(conv_id)
            eval_res = ActiveListeningEngine.evaluate(clean_t, pending_question=pending_q, is_ambient=False)

            if eval_res.category == SpokenIntentCategory.MIC_CHECK:
                print(f"[ActiveListening] 🎙️ Mic check detected: '{clean_t}' -> fast reassurance")
                if eval_res.quick_spoken_reply:
                    tts = get_tts_engine(cfg, agent_name=active_agent)
                    tts.stream_speak(eval_res.quick_spoken_reply, block=True)
                return {}

            if eval_res.category == SpokenIntentCategory.CONVERSATIONAL_FILLER:
                print(f"[ActiveListening] 💬 Conversational filler detected: '{clean_t}' -> acknowledge")
                if eval_res.quick_spoken_reply:
                    tts = get_tts_engine(cfg, agent_name=active_agent)
                    tts.stream_speak(eval_res.quick_spoken_reply, block=True)
                return {}

            if eval_res.category == SpokenIntentCategory.PENDING_ANSWER:
                print(f"[ActiveListening] 🎯 Matched pending choice: '{eval_res.selected_option}' (from '{clean_t}')")
                resolve_pending_question(conv_id, selected_option=eval_res.selected_option)
                text_to_send = eval_res.selected_option or eval_res.normalized_text
            else:
                clear_pending_question(conv_id)
                text_to_send = eval_res.normalized_text

            if cfg.antigravity.inject_to_active_window:
                if inject_text_to_active_app(text_to_send, submit_enter=True, target_antigravity=True):
                    print("Sent to active conversation.")
                else:
                    print("⚠️ Injection failed — text left on clipboard.")

            if cfg.audio_cues.enabled:
                play_chime(cfg.audio_cues.sent_chime, block=False)

    return {}

