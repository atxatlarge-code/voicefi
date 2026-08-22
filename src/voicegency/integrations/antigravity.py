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

from voicegency.config import VoicegencyConfig, load_config
from voicegency.tts import get_tts_engine, stop_all_speech
from voicegency.stt import get_stt_engine
from voicegency.audio.recorder import AudioRecorder
from voicegency.audio.chimes import play_chime
from voicegency.integrations.injector import inject_text_to_active_app
from voicegency.integrations.conversations import save_session_cookie, claim_turn


def clean_markdown_for_speech(text: str, max_words: int = 25) -> str:
    """
    Clean markdown formatting and extract punchy 1-2 sentence spoken updates/questions.
    """
    if not text:
        return ""

    # Remove code blocks ```...```
    text = re.sub(r"```[\s\S]*?```", " [code snippet] ", text)

    # Remove inline code `...`
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Remove markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remove markdown headers (#, ##, etc.) with optional leading whitespace
    text = re.sub(r"^\s*#{1,6}\s*", "", text, flags=re.MULTILINE)

    # Remove bold/italic markers (*, _, ~)
    text = re.sub(r"[*_~]{1,3}", "", text)

    # Remove blockquotes
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)

    # Remove bullet markers (- , * , 1. )
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)

    # Remove excessive whitespace
    text = " ".join(text.split()).strip()

    # If there are multiple sentences, look for questions or concluding statements
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if sentences:
        # Check if the last sentence is a question
        last_sentence = sentences[-1].strip()
        if last_sentence.endswith("?") and len(last_sentence.split()) <= max_words:
            # If previous sentence is also short, combine them
            if len(sentences) >= 2 and len((sentences[-2] + " " + last_sentence).split()) <= max_words:
                return f"{sentences[-2]} {last_sentence}"
            return last_sentence
        
        # Otherwise take the first 1-2 sentences up to max_words
        first_part = ""
        for s in sentences:
            if not first_part:
                first_part = s
            elif len((first_part + " " + s).split()) <= max_words:
                first_part += " " + s
            else:
                break
        text = first_part

    # Split into words and limit length
    words = text.split()
    if len(words) > max_words:
        truncated = " ".join(words[:max_words])
        last_punct = max(truncated.rfind("."), truncated.rfind("?"), truncated.rfind("!"))
        if last_punct > len(truncated) // 2:
            return truncated[: last_punct + 1]
        return truncated + "..."

    return text


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

                    if (step_type == "PLANNER_RESPONSE" or step_source == "MODEL") and content:
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


def handle_antigravity_stop_hook(payload: Dict[str, Any], config: Optional[VoicegencyConfig] = None) -> Dict[str, Any]:
    """
    Execute the Voicegency loop on Antigravity Stop event.
    
    1. Summarize agent turn.
    2. Speak summary via TTS (using agent or subagent persona).
    3. Open mic, record speech with VAD.
    4. Transcribe via STT.
    5. Inject transcribed text into active window.
    """
    cfg = config or load_config()

    conv_id = payload.get("conversationId", "")
    transcript_path_str = payload.get("transcriptPath", "")
    workspace_paths = payload.get("workspacePaths", [])
    workspace_path = workspace_paths[0] if workspace_paths else None
    transcript_path = Path(transcript_path_str) if transcript_path_str else Path("")
    hook_agent_role = payload.get("agent_role") or payload.get("role")

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

    turn_sig = f"{conv_id}:{summary[:35]}"
    if not claim_turn(conv_id, turn_sig):
        # Already handled by menu bar watcher
        return {}

    should_speak = bool(cfg.antigravity.read_summary_aloud and summary)
    should_listen = bool(cfg.antigravity.auto_listen)
    barge_in_active = bool(should_speak and should_listen and getattr(cfg.vad, "barge_in", True))

    if cfg.antigravity.show_speech_popup and summary:
        try:
            from voicegency.ui.speech_hud import AgentSpeechHUD
            from voicegency.tts import find_persona
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
                        from voicegency.ui.speech_hud import AgentSpeechHUD
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
                    from voicegency.ui.speech_hud import AgentSpeechHUD
                    AgentSpeechHUD.get_instance().hide()
                except Exception:
                    pass

        recorder = AudioRecorder(
            sample_rate=cfg.vad.sample_rate,
            energy_threshold=cfg.vad.energy_threshold,
            silence_duration=cfg.vad.silence_duration,
            max_record_seconds=cfg.vad.max_record_seconds,
            barge_in=True,
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
                from voicegency.ui.speech_hud import AgentSpeechHUD
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
            if cfg.antigravity.inject_to_active_window:
                inject_text_to_active_app(transcription, submit_enter=True, target_antigravity=True)

            if cfg.audio_cues.enabled:
                play_chime(cfg.audio_cues.sent_chime, block=False)

    return {}
