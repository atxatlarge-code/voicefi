"""
Antigravity lifecycle hook and transcript integration.
Listens to agent Stop events, summarizes output, speaks aloud, and captures voice response.
"""

import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts import get_tts_engine, stop_all_speech
from voicefi.tts.base import (
    set_cross_process_hud_state,
    clear_cross_process_hud_state,
    escape_to_stop_speech,
)
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.injector import inject_text_to_active_app, send_message_to_antigravity
from voicefi.integrations.conversations import (
    save_session_cookie,
    claim_turn,
    pop_mobile_turn_origin,
    get_claimed_turn_origin,
    has_active_companion_client,
    set_pending_question,
    get_pending_question,
    resolve_pending_question,
    clear_pending_question,
)
from voicefi.integrations.active_listening import (
    ActiveListeningEngine,
    SpokenIntentCategory,
    SpokenTargetChannel,
)
from voicefi.tts.normalizer import normalize_tts_text


def clean_markdown_for_speech(text: str, max_words: Optional[int] = None) -> str:
    """
    Clean markdown formatting and extract punchy 1-2 sentence spoken updates/questions.
    Dynamically constrained by BrevityLearner cognitive memory.
    Prioritizes trailing questions and status outcomes while stripping code/paths/tables/stacktraces.
    """
    if not text or not text.strip():
        return ""

    # Dynamically resolve optimal word budget from BrevityLearner if not explicitly pinned
    target_max_words = max_words
    if target_max_words is None or target_max_words <= 0:
        try:
            from voicefi.learning.brevity import BrevityLearner

            target_max_words = BrevityLearner.get_instance().get_optimal_max_words()
        except Exception:
            target_max_words = 24

    # 0. Check for Gemini Flash / Local LLM distillation if available and enabled
    try:
        from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine

        gemini_engine = GeminiIntelligenceEngine()
        if gemini_engine.is_available() and getattr(
            getattr(gemini_engine.config, "gemini", None), "enable_soundbite_distillation", True
        ):
            distilled = gemini_engine.distill_spoken_soundbite(
                text, max_words=target_max_words, timeout=0.8
            )
            if distilled and len(distilled.strip()) > 3:
                return distilled
    except Exception:
        pass

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

    # 5. Clean Markdown markup & ensure clean sentence boundaries across lines/lists/headers
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        l = line.strip()
        if not l:
            continue
        # Strip header markers: ### Heading -> Heading
        l = re.sub(r"^#{1,6}\s*", "", l)
        # Strip list markers: - Item, * Item, 1. Item -> Item
        l = re.sub(r"^[-*+]\s+", "", l)
        l = re.sub(r"^\d+\.\s+", "", l)
        # Strip horizontal rules
        if re.match(r"^[-*_]{3,}$", l):
            continue
        # Strip blockquotes
        l = re.sub(r"^>\s*", "", l)
        l = l.strip()
        if not l:
            continue
        # If line does not end with terminal punctuation, append a period so sentences don't fuse into run-on blobs
        if not l.endswith((".", "!", "?", ":", ";", ",")):
            l += "."
        cleaned_lines.append(l)

    text = " ".join(cleaned_lines)

    # Clean remaining inline Markdown markup
    text = re.sub(r"`([^`]+)`", r"\1", text)  # Inline code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # Links -> text only
    text = re.sub(r"[*_~]{1,3}", "", text)  # Bold/Italic

    # 6. Strip emojis and decorative Unicode symbols
    text = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]", "", text)

    # 7. Normalize whitespace
    text = " ".join(text.split()).strip()
    text = re.sub(r"^[-—–\s]+", "", text).strip()
    if not text:
        return ""

    # 8. Extract sentences & assemble punchy natural spoken summary
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return normalize_tts_text(text[: target_max_words * 6])

    def _truncate_sentence(s: str, budget: int) -> str:
        words = s.split()
        if len(words) <= budget:
            return s
        truncated = " ".join(words[:budget])
        last_punct = max(
            truncated.rfind("."), truncated.rfind("?"), truncated.rfind("!"), truncated.rfind(",")
        )
        if last_punct > len(truncated) // 2:
            return truncated[: last_punct + 1]
        return truncated + "..."

    # Handle trailing question pairing
    if sentences[-1].endswith("?") and len(sentences) > 1:
        last_s = sentences[-1]
        last_words_count = len(last_s.split())

        # If entire text up to question fits in target_max_words, assemble as many sentences as fit
        candidate_sentences = []
        current_words = last_words_count
        for s in sentences[:-1]:
            count = len(s.split())
            if current_words + count <= target_max_words:
                candidate_sentences.append(s)
                current_words += count
            else:
                break

        if candidate_sentences:
            candidate_sentences.append(last_s)
            return normalize_tts_text(" ".join(candidate_sentences))

        # If not even first sentence fits with question, allocate budget to first sentence + question
        first_s = sentences[0]
        first_budget = target_max_words - last_words_count
        if first_budget >= 5:
            trunc_first = _truncate_sentence(first_s, first_budget)
            return normalize_tts_text(f"{trunc_first} {last_s}")
        return normalize_tts_text(last_s)

    # Standard sentence assembly up to target_max_words
    result = []
    current_words = 0
    for i, s in enumerate(sentences):
        count = len(s.split())
        if current_words + count <= target_max_words:
            result.append(s)
            current_words += count
        else:
            # If we only have very few words so far (e.g. "Yes!", "Sure!", "Done!", total < 6 words),
            # don't stop prematurely — take the next sentence up to remaining budget!
            if current_words < 6 and (target_max_words - current_words) >= 5:
                trunc = _truncate_sentence(s, target_max_words - current_words)
                if trunc:
                    result.append(trunc)
            break

    if result:
        return normalize_tts_text(" ".join(result))

    # Fallback to truncated first sentence
    return normalize_tts_text(_truncate_sentence(sentences[0], max_words))


def extract_latest_agent_summary(
    transcript_path: Path,
    max_words: int = 60,
    return_role: bool = False,
    return_step_index: bool = False,
):
    """
    Extract the latest assistant response or question from transcript.jsonl.
    Scans the transcript backwards to locate the latest turn's model response.
    If return_role and return_step_index are True, returns (summary_text, agent_role, step_index).
    If return_role is True, returns (summary_text, agent_role).
    Else returns summary_text.
    """
    if not transcript_path.is_file():
        default_msg = "I have finished the task. What would you like to do next?"
        if return_role and return_step_index:
            return (default_msg, None, None)
        return (default_msg, None) if return_role else default_msg

    lines = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception as e:
        print(f"[Antigravity] Error reading transcript: {e}", file=sys.stderr)
        default_msg = "The process is complete and ready for your input."
        if return_role and return_step_index:
            return (default_msg, None, None)
        return (default_msg, None) if return_role else default_msg

    last_model_content = ""
    detected_role: Optional[str] = None
    detected_step_index: Optional[int] = None

    # Traverse backwards to find the latest turn's model message
    for line in reversed(lines):
        try:
            step = json.loads(line)
            step_type = step.get("type", "")
            step_source = step.get("source", "")
            content = step.get("content", "")
            role = step.get("role") or step.get("agent_role")
            idx = step.get("step_index")

            if step_type == "PLANNER_RESPONSE" and content and not step.get("tool_calls"):
                last_model_content = content
                detected_step_index = idx
                if role:
                    detected_role = str(role).lower()
                break
            elif step_type == "USER_INPUT" or step_source == "USER_EXPLICIT":
                # Reached turn boundary without model text
                break
        except json.JSONDecodeError:
            continue

    if not last_model_content:
        # If the current turn does not have a completed model response yet (e.g. intermediate tool execution),
        # do not speak stale messages from prior turns.
        if return_role and return_step_index:
            return ("", detected_role, detected_step_index)
        return ("", detected_role) if return_role else ""

    cleaned = clean_markdown_for_speech(last_model_content, max_words=max_words)
    if return_role and return_step_index:
        return (cleaned, detected_role, detected_step_index)
    return (cleaned, detected_role) if return_role else cleaned


def handle_antigravity_stop_hook(
    payload: Dict[str, Any], config: Optional[VoiceFiConfig] = None
) -> Dict[str, Any]:
    """
    Execute the VoiceFi loop on Antigravity Stop event.

    1. Summarize agent turn.
    2. Speak summary via TTS (using agent or subagent persona).
    3. Open mic, record speech with VAD.
    4. Transcribe via STT.
    5. Inject transcribed text into active window.
    """
    cfg = config or load_config()

    # Guard: Return immediately if globally disabled, hooks disabled, or antigravity hooks disabled
    if (
        not cfg.enabled
        or not getattr(cfg.hooks, "enabled", True)
        or not getattr(cfg.hooks, "antigravity", True)
    ):
        return {}
    if not getattr(cfg.integrations, "antigravity", True):
        return {}
    if not cfg.antigravity.auto_listen and not cfg.antigravity.read_summary_aloud:
        return {}

    conv_id = (
        payload.get("conversationId")
        or payload.get("conversation_id")
        or payload.get("conv_id")
        or ""
    )
    transcript_path_str = payload.get("transcriptPath") or payload.get("transcript_path") or ""
    workspace_paths = payload.get("workspacePaths") or payload.get("workspace_paths") or []
    workspace_path = workspace_paths[0] if workspace_paths else None
    transcript_path = Path(transcript_path_str) if transcript_path_str else Path("")
    hook_agent_role = payload.get("agent_role") or payload.get("role")

    if not transcript_path_str or not transcript_path.is_file():
        if conv_id:
            cand = (
                Path.home()
                / ".gemini"
                / "antigravity"
                / "brain"
                / conv_id
                / ".system_generated"
                / "logs"
                / "transcript.jsonl"
            )
            if cand.is_file():
                transcript_path = cand
        if not transcript_path or not transcript_path.is_file():
            from voicefi.integrations.watcher import find_latest_transcript_path

            cand = find_latest_transcript_path()
            if cand and cand.is_file():
                transcript_path = cand

    if not conv_id and transcript_path.is_file():
        try:
            cand = transcript_path.parent.parent.parent.name
            if len(cand) >= 8:
                conv_id = cand
        except Exception:
            pass

    if not transcript_path or not transcript_path.is_file():
        from voicefi.integrations.conversations import ConversationTracker

        tracker = ConversationTracker()
        recent = tracker.get_recent_transcripts(limit=1)
        if recent:
            transcript_path = recent[0]
            transcript_path_str = str(transcript_path)
            if not conv_id:
                try:
                    cand = transcript_path.parent.parent.parent.name
                    if len(cand) >= 8:
                        conv_id = cand
                except Exception:
                    pass

    if not workspace_path:
        from voicefi.integrations.conversations import ConversationTracker, load_session_cookie

        cookie = load_session_cookie()
        if cookie and cookie.get("workspacePath"):
            workspace_path = cookie.get("workspacePath")
        elif transcript_path and transcript_path.is_file():
            tracker = ConversationTracker()
            c_info = tracker.parse_conversation(transcript_path)
            if c_info and c_info.workspace_path:
                workspace_path = c_info.workspace_path

    project_name = payload.get("projectName") or payload.get("project_name")
    if not project_name and workspace_path:
        project_name = Path(workspace_path).name

    if conv_id:
        save_session_cookie(
            conv_id=conv_id,
            transcript_path=str(transcript_path),
            workspace_path=workspace_path,
            engine="antigravity",
        )

    summary_res = extract_latest_agent_summary(
        transcript_path,
        max_words=cfg.antigravity.max_spoken_words,
        return_role=True,
        return_step_index=True,
    )
    if isinstance(summary_res, tuple) and len(summary_res) == 3:
        summary, detected_role, step_index = summary_res
    elif isinstance(summary_res, tuple) and len(summary_res) == 2:
        summary, detected_role = summary_res
        step_index = None
    else:
        summary = str(summary_res)
        detected_role = None
        step_index = None

    if not summary or not summary.strip():
        # Intermediate tool step or turn in progress with no final model text yet
        return {}

    active_agent = hook_agent_role or detected_role or "antigravity"

    turn_sig = f"{conv_id}:{summary[:35]}"
    try:
        claimed = claim_turn(conv_id, turn_sig, step_index=step_index)
    except TypeError:
        claimed = claim_turn(conv_id, turn_sig)

    if not claimed:
        # Already claimed and handled by watcher or another process
        return {}

    # Track pending clarifying question / options if present
    if summary and (summary.endswith("?") or " or " in summary.lower()):
        set_pending_question(conv_id, summary)

    if summary:
        from voicefi.audio.echo_canceller import record_agent_spoken

        record_agent_spoken(summary)

    routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
    mute_mac_active = getattr(
        getattr(cfg, "companion", None), "mute_mac_when_companion_active", False
    )
    is_mobile = get_claimed_turn_origin(conv_id, turn_sig, step_index=step_index) == "mobile"

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
    should_listen = bool(cfg.antigravity.auto_listen and summary)
    hook_start_time = time.time()

    from voicefi.audio.recorder import resolve_barge_in_mode

    is_barge_in_on, _ = resolve_barge_in_mode(getattr(cfg.vad, "barge_in", "auto"))
    barge_in_active = bool(should_speak and should_listen and is_barge_in_on)

    if cfg.antigravity.show_speech_popup and summary:
        try:
            from voicefi.ui.speech_hud import AgentSpeechHUD
            from voicefi.tts import find_persona

            _, resolved_voice, _ = cfg.resolve_voice(
                active_agent,
                project_name=project_name,
                workspace_path=workspace_path,
            )
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
        # Active Barge-In: set speaking state immediately, start TTS in background thread, and listen on mic
        from voicefi.tts.base import set_agent_speaking

        set_agent_speaking(True, text=summary, agent_name=active_agent)

        tts = get_tts_engine(
            cfg,
            agent_name=active_agent,
            project_name=project_name,
            workspace_path=workspace_path,
        )

        def _speak_and_finish():
            try:
                with escape_to_stop_speech():
                    tts.stream_speak(summary, block=True)
            finally:
                from voicefi.tts.base import set_agent_speaking

                set_agent_speaking(False)
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

        def _on_live(txt: str):
            set_cross_process_hud_state(
                "listening",
                text=txt,
                agent_name=active_agent,
                user_name=cfg.user_name,
                live_stream=True,
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

        audio_data, temp_wav = recorder.record_speech_auto(
            on_speech_start=lambda: set_cross_process_hud_state(
                "hearing", agent_name=active_agent, user_name=cfg.user_name
            ),
            on_barge_in=_on_barge_in,
            on_live_transcript=_on_live,
            on_listening_tick=_on_tick,
        )
    else:
        if should_speak:
            tts = get_tts_engine(
                cfg,
                agent_name=active_agent,
                project_name=project_name,
                workspace_path=workspace_path,
            )
            with escape_to_stop_speech():
                tts.stream_speak(summary, block=True)

        from voicefi.tts.base import is_speech_interrupted

        if is_speech_interrupted(hook_start_time):
            clear_cross_process_hud_state()
            return {}

        if cfg.antigravity.show_speech_popup:
            try:
                from voicefi.ui.speech_hud import AgentSpeechHUD

                linger = getattr(cfg.antigravity, "speech_popup_linger_seconds", 3.0)
                AgentSpeechHUD.get_instance().finish_speech(linger_seconds=linger)
            except Exception:
                pass

        if should_listen:
            if cfg.audio_cues.enabled:
                play_chime("start", block=True)
                time.sleep(0.1)

            set_cross_process_hud_state(
                "listening", agent_name=active_agent, user_name=cfg.user_name
            )

            def _on_live(txt: str):
                set_cross_process_hud_state(
                    "listening",
                    text=txt,
                    agent_name=active_agent,
                    user_name=cfg.user_name,
                    live_stream=True,
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


            recorder = AudioRecorder(
                sample_rate=cfg.vad.sample_rate,
                energy_threshold=cfg.vad.energy_threshold,
                silence_duration=cfg.vad.silence_duration,
                max_record_seconds=cfg.vad.max_record_seconds,
                barge_in=False,
            )

            audio_data, temp_wav = recorder.record_speech_auto(
                on_speech_start=lambda: set_cross_process_hud_state(
                    "hearing", agent_name=active_agent, user_name=cfg.user_name
                ),
                on_live_transcript=_on_live,
                on_listening_tick=_on_tick,
            )


    from voicefi.tts.base import is_speech_interrupted

    if is_speech_interrupted(hook_start_time):
        if temp_wav and Path(temp_wav).is_file():
            Path(temp_wav).unlink(missing_ok=True)
        clear_cross_process_hud_state()
        return {}

    if temp_wav and Path(temp_wav).is_file():
        set_cross_process_hud_state("transcribing", agent_name=active_agent)
        stt = get_stt_engine(cfg)
        try:
            transcription = stt.transcribe(temp_wav)
        finally:
            Path(temp_wav).unlink(missing_ok=True)

        if is_speech_interrupted(hook_start_time):
            clear_cross_process_hud_state()
            return {}

        if transcription and transcription.strip():
            clean_t = transcription.strip()
            print(f'[Antigravity] 🎙️ Transcribed speech: "{clean_t}"', flush=True)
            from voicefi.audio.echo_canceller import is_acoustic_echo

            if is_acoustic_echo(clean_t, reference_text=summary):
                print(
                    f'[Antigravity] 🛡️ Suppressed acoustic self-echo: "{clean_t}" (matched agent output)',
                    flush=True,
                )
                return {}

            pending_q = get_pending_question(conv_id)
            eval_res = ActiveListeningEngine.evaluate(
                clean_t, pending_question=pending_q, is_ambient=False
            )
            print(
                f"[ActiveListening] Intent evaluation: {eval_res.category.value} (is_actionable={eval_res.is_actionable})",
                flush=True,
            )

            if eval_res.category == SpokenIntentCategory.PENDING_ANSWER:
                print(
                    f"[ActiveListening] 🎯 Matched pending choice: '{eval_res.selected_option}' (from '{clean_t}')",
                    flush=True,
                )
                resolve_pending_question(conv_id, selected_option=eval_res.selected_option)
                text_to_send = eval_res.selected_option or eval_res.normalized_text
            else:
                clear_pending_question(conv_id)
                text_to_send = eval_res.normalized_text or clean_t

            is_auto_send = getattr(getattr(cfg, "hud", None), "auto_send", True) and getattr(
                cfg.antigravity, "auto_send", True
            )

            def _dispatch_prompt(final_text: str):
                if cfg.antigravity.inject_to_active_window:
                    target_channel = getattr(
                        eval_res, "target_channel", SpokenTargetChannel.ANTIGRAVITY
                    )
                    routed_text = getattr(eval_res, "routed_prompt", None) or final_text

                    if (
                        target_channel == SpokenTargetChannel.CLAUDE
                        and cfg.proactive.intent_routing.route_to_claude
                    ):
                        set_cross_process_hud_state(
                            "done", text=f"Claude: {routed_text[:20]}", agent_name="Claude"
                        )
                        print(
                            f"[IntentRouter] 🔀 Routing spoken prompt to Claude Code: '{routed_text}'",
                            flush=True,
                        )
                        from voicefi.integrations.claude import inject_text_to_claude

                        delivered = inject_text_to_claude(routed_text, submit_enter=True)
                    elif (
                        target_channel == SpokenTargetChannel.SLACK
                        and cfg.proactive.intent_routing.route_to_slack
                    ):
                        set_cross_process_hud_state(
                            "done", text=f"Slack: {routed_text[:20]}", agent_name="Slack"
                        )
                        ch = (eval_res.target_metadata or {}).get("channel", "general")
                        slack_prompt = f"Please post this to Slack (#{ch}): {routed_text}"
                        print(
                            f"[IntentRouter] 🔀 Routing spoken prompt to Slack via Antigravity: '{slack_prompt}'",
                            flush=True,
                        )
                        delivered = send_message_to_antigravity(
                            conv_id=conv_id, text=slack_prompt, sender_name=cfg.user_name
                        )
                    elif (
                        target_channel == SpokenTargetChannel.LINEAR
                        and cfg.proactive.intent_routing.route_to_linear
                    ):
                        set_cross_process_hud_state(
                            "done", text=f"Linear: {routed_text[:20]}", agent_name="Linear"
                        )
                        linear_prompt = f"Please create a Linear issue for: {routed_text}"
                        print(
                            f"[IntentRouter] 🔀 Routing spoken prompt to Linear via Antigravity: '{linear_prompt}'",
                            flush=True,
                        )
                        delivered = send_message_to_antigravity(
                            conv_id=conv_id, text=linear_prompt, sender_name=cfg.user_name
                        )
                    else:
                        set_cross_process_hud_state(
                            "done", text=final_text[:20], agent_name=active_agent
                        )
                        print(
                            f"[Antigravity] 🚀 Dispatching prompt to conversation {str(conv_id)[:8]}: '{final_text}'",
                            flush=True,
                        )
                        delivered = send_message_to_antigravity(
                            conv_id=conv_id, text=final_text, sender_name=cfg.user_name
                        )

            if is_auto_send:
                _dispatch_prompt(text_to_send)
            else:
                try:
                    from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

                    hud = UnifiedDynamicIslandHUD.get_instance()
                    hud.set_editing(
                        text_to_send, on_submit=_dispatch_prompt, target_name="Antigravity"
                    )
                except Exception:
                    _dispatch_prompt(text_to_send)

                if delivered:
                    print(
                        f"[Antigravity] ✅ Delivered successfully to {target_channel.value} ({str(conv_id)[:8]}).",
                        flush=True,
                    )
                else:
                    print("[Antigravity] ⚠️ Delivery failed — text left on clipboard.", flush=True)

            if cfg.audio_cues.enabled:
                play_chime(cfg.audio_cues.sent_chime, block=False)
    if should_speak:
        turn_dur_ms = int((time.time() - hook_start_time) * 1000)
        try:
            from voicefi.telemetry import capture_voice_interaction

            _, resolved_voice, resolved_provider = cfg.resolve_voice(
                active_agent,
                project_name=project_name,
                workspace_path=workspace_path,
            )
            capture_voice_interaction(
                trigger="hook",
                duration_ms=turn_dur_ms,
                success=True,
                agent=active_agent,
                voice=resolved_voice,
                provider=resolved_provider,
                chars_count=len(summary) if summary else 0,
                is_barge_in=barge_in_active,
            )
        except Exception:
            pass

    return {}


def remove_antigravity_hook(plugin_dir: Optional[Path] = None) -> bool:
    """
    Remove VoiceFi Stop hook from ~/.gemini/config/plugins/voicefi-plugin/hooks.json
    and ~/.gemini/config/hooks.json.
    """
    target_dir = plugin_dir or (Path.home() / ".gemini" / "config" / "plugins" / "voicefi-plugin")
    hook_file = target_dir / "hooks.json"
    if hook_file.is_file():
        try:
            with open(hook_file, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2)
        except Exception:
            pass

    global_hooks = Path.home() / ".gemini" / "config" / "hooks.json"
    if global_hooks.is_file():
        try:
            with open(global_hooks, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            if "voicefi-voice-layer" in data:
                del data["voicefi-voice-layer"]
                with open(global_hooks, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except Exception:
            pass
    return True
