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
    DuplicateSpeechSuppressed,
)
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.injector import inject_text_to_active_app, send_message_to_antigravity
from voicefi.integrations.conversations import (
    save_session_cookie,
    claim_turn,
    pop_mobile_turn_origin,
    peek_mobile_turn_origin,
    get_claimed_turn_origin,
    has_active_companion_client,
    mark_turn_spoken_on_mac,
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


def clean_markdown_for_speech(
    text: str,
    max_words: Optional[int] = None,
    full_read: bool = False,
    first_sentence_only: Optional[bool] = None,
) -> str:
    """
    Clean markdown formatting and extract spoken text.
    If full_read is True (Live API response), cleans code/markup/tables/embeds
    and normalizes text for speech, but preserves the complete text verbatim
    without word limits, truncation, or sentence extraction.
    If full_read is False (standard turn end), extracts punchy 1st sentence / soundbite
    constrained by BrevityLearner cognitive memory or first_sentence_only setting.
    """
    if not text or not text.strip():
        return ""

    if first_sentence_only is None:
        try:
            from voicefi.config import load_config

            _cfg = load_config()
            first_sentence_only = bool(
                getattr(getattr(_cfg, "antigravity", None), "first_sentence_only", False)
                or getattr(getattr(_cfg, "tts", None), "first_sentence_only", False)
            )
        except Exception:
            first_sentence_only = False

    if not full_read:
        # Dynamically resolve optimal word budget from BrevityLearner
        target_max_words = max_words
        try:
            from voicefi.learning.brevity import BrevityLearner

            learned_words = BrevityLearner.get_instance().get_optimal_max_words()
            if target_max_words is None or target_max_words <= 0:
                target_max_words = learned_words
            elif target_max_words <= BrevityLearner.MAX_MAX_WORDS:
                target_max_words = min(target_max_words, learned_words)
        except Exception:
            if target_max_words is None or target_max_words <= 0:
                target_max_words = 24

        # 0. Check for Gemini Flash / Local LLM distillation ONLY if explicitly opt-in enabled and not first_sentence_only
        if not first_sentence_only:
            try:
                from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine

                gemini_engine = GeminiIntelligenceEngine()
                if gemini_engine.is_available() and getattr(
                    getattr(gemini_engine.config, "gemini", None), "enable_soundbite_distillation", False
                ):
                    distilled = gemini_engine.distill_spoken_soundbite(
                        text, max_words=target_max_words, timeout=0.8
                    )
                    if distilled and len(distilled.strip()) > 3:
                        return normalize_tts_text(distilled)
            except Exception:
                pass

    # 1. Bound text size to avoid regex performance bottlenecks on massive outputs
    if not full_read and len(text) > 4000:
        text = text[:1000] + "\n" + text[-2000:]
    elif full_read and len(text) > 15000:
        text = text[:15000]

    # 1.5 When extracting first sentence only, strip leading markdown headers so speech starts with the actual sentence
    if first_sentence_only and not full_read:
        body_text = re.sub(r"^(?:#{1,6}\s+[^\n]+(?:\n+|$))+", "", text.strip()).strip()
        if body_text:
            text = body_text

    # 2. Check for raw stack traces / errors first
    if "Traceback (most recent call last):" in text or "Error:" in text:
        err_match = re.search(r"(\b[A-Za-z0-9_]*Error:\s+[^\n]+)", text)
        if err_match:
            return f"The agent encountered an error: {err_match.group(1)}."

    # 2.5 Strip inline SFX tags and emojis early before markdown formatting alters them
    try:
        from voicefi.audio.sfx import strip_inline_sfx_tags

        text = strip_inline_sfx_tags(text)
    except Exception:
        text = re.sub(r"[\[\(\{]\s*sfx:?\s*[\w-]+\s*[\]\)\}]", "", text, flags=re.IGNORECASE)

    # Strip emojis and decorative Unicode symbols early so line endings have clean punctuation
    text = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]", "", text)

    # 3. Strip lead-in colons preceding code blocks, code fences, and Markdown tables
    text = re.sub(
        r"(?i)\b(?:here(?:'s| is| are)|below is|see the|the following is|check out)\s+(?:the\s+)?(?:new\s+|updated\s+)?(?:code|endpoint|snippet|changes|diff|implementation|example|output|results?|file|function|patch)?\s*:\s*(?=\s*```)",
        "",
        text,
    )
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Strip <agent-embed> tags and generic XML/HTML tags from speech
    text = re.sub(r"<agent-embed[^>]*>[\s\S]*?</agent-embed>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</?agent-embed[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\|[^\n]+\|", " ", text)  # Tables
    text = re.sub(
        r"(?i)(?:^|\n)\s*(?:here(?:'s| is| are)|below is|see the|the following is|check out)\s+(?:the\s+)?(?:new\s+|updated\s+)?(?:code|endpoint|snippet|changes|diff|implementation|example|output|results?|file|function|patch)?\s*:\s*(?=\n|$)",
        "",
        text,
    )

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
        is_header = bool(re.match(r"^#{1,6}\s*", l))
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
        # If line is a header, ensure terminal period so it cannot fuse with following paragraphs
        if is_header and not l.endswith((".", "!", "?")):
            l += "."
        # If line does not end with terminal punctuation, append a period so sentences don't fuse into run-on blobs
        elif not l.endswith((".", "!", "?", ":", ";", ",", '"', "'", "”", "’", "*", ")", "]", "}")):
            l += "."
        cleaned_lines.append(l)

    text = " ".join(cleaned_lines)

    # Clean remaining inline Markdown markup
    text = re.sub(r"`([^`]+)`", r"\1", text)  # Inline code
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # Links -> text only
    text = re.sub(r"[*_~]{1,3}", "", text)  # Bold/Italic
    text = re.sub(r"(?:^|\s+)>\s*", " ", text)  # Strip remaining blockquote markers

    # Strip any leftover bracketed/parenthesized SFX tags or punctuation artifacts
    text = re.sub(r"[\[\(\{]\s*sfx:?\s*[\w-]+\s*[\]\)\}]", "", text, flags=re.IGNORECASE)
    text = text.replace("...", "___ELLIPSIS___")
    text = re.sub(r"([!?.,;:])\s*[.]+", r"\1", text)  # Clean "! .", "? .", ". ."
    text = re.sub(r":\s+(?=[A-Z0-9])", ". ", text)  # Clean dangling colons before sentences
    text = text.replace("___ELLIPSIS___", "...")

    # 6. Normalize whitespace
    text = " ".join(text.split()).strip()
    text = re.sub(r"^[-—–\s]+", "", text).strip()
    if not text:
        return ""

    if full_read:
        return normalize_tts_text(text)

    # 8. Extract sentences & assemble punchy natural spoken summary (Standard Turn-End Mode)
    sentences = [s.strip() for s in re.split(r"(?<!\.\.)(?<=[.!?])(?!\.)\s+", text) if s.strip()]
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

    if first_sentence_only:
        first_s = sentences[0]
        filler_tokens = ("sure", "got it", "okay", "ok", "alright", "done", "understood", "all set", "no problem", "look")
        if (
            len(sentences) >= 2
            and len(first_s.split()) <= 2
            and first_s.lower().rstrip(".!?,") in filler_tokens
        ):
            first_s = f"{first_s} {sentences[1]}"
        max_budget = target_max_words if (target_max_words and target_max_words > 0) else 45
        return normalize_tts_text(_truncate_sentence(first_s, max_budget))

    # Handle leading question + answer / joke setup + punchline pairing
    if sentences[0].endswith("?") and len(sentences) >= 2:
        first_s = sentences[0]
        second_s = sentences[1]
        first_cnt = len(first_s.split())
        second_cnt = len(second_s.split())
        pair_cnt = first_cnt + second_cnt

        if pair_cnt <= max(int(target_max_words * 1.5), 38):
            res_sentences = [first_s, second_s]
            cur = pair_cnt
            for extra_s in sentences[2:]:
                extra_cnt = len(extra_s.split())
                if cur + extra_cnt <= target_max_words:
                    res_sentences.append(extra_s)
                    cur += extra_cnt
                else:
                    break
            return normalize_tts_text(" ".join(res_sentences))
        else:
            avail = max(target_max_words - first_cnt, 8)
            trunc_second = _truncate_sentence(second_s, avail)
            return normalize_tts_text(f"{first_s} {trunc_second}")

    # Handle short 2-sentence responses to preserve complete context
    if len(sentences) == 2:
        total_pair = sum(len(s.split()) for s in sentences)
        if total_pair <= max(int(target_max_words * 1.35), 36):
            return normalize_tts_text(" ".join(sentences))

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

        # If not even first sentence fits with question, check if complete first sentence + question fits within modest tolerance
        first_s = sentences[0]
        first_words_count = len(first_s.split())
        if first_words_count + last_words_count <= max(int(target_max_words * 1.45), 32):
            return normalize_tts_text(f"{first_s} {last_s}")

        # Otherwise allocate remaining budget to first sentence + question
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
            # If we only have very few words so far or this is the second sentence,
            # don't stop prematurely — take the next sentence up to remaining budget!
            if (current_words < 8 or i == 1) and (target_max_words - current_words) >= 5:
                trunc = _truncate_sentence(s, target_max_words - current_words)
                if trunc:
                    result.append(trunc)
            break

    if result:
        return normalize_tts_text(" ".join(result))

    # Fallback to truncated first sentence
    return normalize_tts_text(_truncate_sentence(sentences[0], target_max_words or max_words or 32))


extract_spoken_soundbite = clean_markdown_for_speech


def extract_latest_agent_summary(
    transcript_path: Path,
    max_words: int = 60,
    return_role: bool = False,
    return_step_index: bool = False,
    retries: int = 6,
    retry_delay: float = 0.12,
    full_read: bool = False,
    first_sentence_only: Optional[bool] = None,
    return_raw: bool = False,
):
    """
    Extract the latest assistant response or question from transcript.jsonl.
    Scans the transcript backwards to locate the latest turn's model response.
    Includes rapid retry polling to eliminate race conditions while Antigravity
    flushes the final PLANNER_RESPONSE chunk to disk.
    If return_role and return_step_index are True, returns (summary_text, agent_role, step_index).
    If return_role is True, returns (summary_text, agent_role).
    Else returns summary_text.
    """
    if not transcript_path.is_file():
        default_msg = "I have finished the task. What would you like to do next?"
        if return_role and return_step_index:
            return (default_msg, None, None)
        return (default_msg, None) if return_role else default_msg

    last_model_content = ""
    detected_role: Optional[str] = None
    detected_step_index: Optional[int] = None

    attempts_left = max(1, retries)
    while attempts_left > 0:
        lines = []
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
        except Exception as e:
            print(f"[Antigravity] Error reading transcript: {e}", file=sys.stderr)

        # Traverse backwards to find the latest turn's model message
        for line in reversed(lines):
            try:
                step = json.loads(line)
                step_type = step.get("type", "")
                step_source = step.get("source", "")
                content = step.get("content", "")
                role = step.get("role") or step.get("agent_role")
                idx = step.get("step_index")

                if step_type == "PLANNER_RESPONSE":
                    tool_calls = step.get("tool_calls") or []
                    ask_q_tool = None
                    for tc in tool_calls:
                        tc_name = tc.get("name") or tc.get("tool_name") or ""
                        if tc_name == "ask_question":
                            ask_q_tool = tc
                            break
                    if ask_q_tool:
                        args = ask_q_tool.get("args") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        questions = args.get("questions") or []
                        if questions and isinstance(questions, list):
                            q0 = questions[0]
                            q_text = (q0.get("question") or "").strip()
                            raw_opts = q0.get("options") or []
                            clean_opts = [str(o).strip() for o in raw_opts if str(o).strip()]
                            if len(clean_opts) == 2:
                                synthesized_q = f"{q_text} Would you prefer {clean_opts[0]}, or {clean_opts[1]}?"
                            elif len(clean_opts) > 2:
                                opt_str = ". ".join(
                                    f"Option {i + 1}: {opt}" for i, opt in enumerate(clean_opts)
                                )
                                synthesized_q = f"{q_text} {opt_str}."
                            else:
                                synthesized_q = q_text
                            last_model_content = synthesized_q
                            detected_step_index = idx
                            if role:
                                detected_role = str(role).lower()
                            try:
                                from voicefi.integrations.conversations import set_pending_question

                                conv_id = transcript_path.parent.parent.parent.name
                                set_pending_question(conv_id, synthesized_q, options=clean_opts)
                            except Exception:
                                pass
                            break
                    elif content and not tool_calls:
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

        if last_model_content:
            break

        attempts_left -= 1
        if attempts_left > 0:
            time.sleep(retry_delay)

    if not last_model_content:
        # If the current turn does not have a completed model response yet (e.g. intermediate tool execution),
        # do not speak stale messages from prior turns.
        if return_role and return_step_index:
            return ("", detected_role, detected_step_index)
        return ("", detected_role) if return_role else ""

    cleaned = clean_markdown_for_speech(
        last_model_content,
        max_words=max_words,
        full_read=full_read,
        first_sentence_only=first_sentence_only,
    )
    if return_raw:
        if return_role and return_step_index:
            return (cleaned, detected_role, detected_step_index, last_model_content)
        return (cleaned, detected_role, last_model_content) if return_role else (cleaned, last_model_content)
    if return_role and return_step_index:
        return (cleaned, detected_role, detected_step_index)
    return (cleaned, detected_role) if return_role else cleaned


def append_character_quip(
    first_sentence: str,
    active_agent: str = "antigravity",
    instruction: Optional[str] = None,
) -> str:
    """Append a snappy 1-sentence character quip / reaction to the first sentence summary."""
    if not first_sentence or not first_sentence.strip():
        return first_sentence

    fs = first_sentence.strip()
    if not fs.endswith((".", "!", "?")):
        fs += "."

    try:
        from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine

        engine = GeminiIntelligenceEngine()
        if engine.is_available():
            prompt = (
                instruction
                or f"You are {active_agent}. In 1 short punchy sentence, give an in-character reaction to this completed task."
            )
            res = engine.distill_spoken_soundbite(
                f"{prompt}\nTask completed: {fs}", max_words=16, timeout=0.8
            )
            if res and len(res.strip()) > 3:
                return f"{fs} {res.strip()}"
    except Exception:
        pass

    quips = {
        "ricky bobby": "Shake and bake, baby!",
        "christopher": "Right, jolly good then.",
        "viv": "All clean and ready to roll.",
        "guy": "Locked, loaded, and ready to ship.",
        "sonia": "Observations verified.",
        "william": "Architecture holds solid.",
    }
    agent_key = active_agent.lower()
    for k, q in quips.items():
        if k in agent_key:
            return f"{fs} {q}"
    return f"{fs} All set."


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

    is_active = True
    if conv_id:
        from voicefi.integrations.conversations import ConversationTracker

        tracker = ConversationTracker()
        is_active = tracker.is_conversation_focused(conv_id)
        if is_active:
            save_session_cookie(
                conv_id=conv_id,
                transcript_path=str(transcript_path),
                workspace_path=workspace_path,
                engine="antigravity",
            )

    turn_end_mode = getattr(getattr(cfg, "tts", None), "turn_end_mode", "standard")
    tts_provider = getattr(getattr(cfg, "tts", None), "provider", "gemini")
    from voicefi.integrations.turn_lock import peek_live_turn_origin

    is_live_turn = (
        turn_end_mode == "gemini_live"
        or tts_provider == "gemini_live"
        or peek_live_turn_origin(conv_id)
    )

    turn_format = getattr(getattr(cfg, "tts", None), "turn_complete_format", "first_sentence")
    if turn_format == "full" or is_live_turn:
        req_full_read = True
        req_first_sentence = False
    elif turn_format == "first_sentence":
        req_full_read = False
        req_first_sentence = True
    elif turn_format == "distilled":
        req_full_read = False
        req_first_sentence = False
    elif turn_format == "character_quip":
        req_full_read = False
        req_first_sentence = True
    else:  # chime_only
        req_full_read = False
        req_first_sentence = True

    summary_res = extract_latest_agent_summary(
        transcript_path,
        max_words=cfg.antigravity.max_spoken_words,
        return_role=True,
        return_step_index=True,
        return_raw=True,
        full_read=req_full_read,
        first_sentence_only=req_first_sentence,
    )
    if isinstance(summary_res, tuple) and len(summary_res) == 4:
        summary, detected_role, step_index, raw_content = summary_res
    elif isinstance(summary_res, tuple) and len(summary_res) == 3:
        summary, detected_role, step_index = summary_res
        raw_content = summary
    elif isinstance(summary_res, tuple) and len(summary_res) == 2:
        summary, detected_role = summary_res
        step_index = None
        raw_content = summary
    else:
        summary = str(summary_res)
        detected_role = None
        step_index = None
        raw_content = summary

    if not summary or not summary.strip():
        # Intermediate tool step or turn in progress with no final model text yet
        return {}

    active_agent = hook_agent_role or detected_role or "antigravity"

    if turn_format == "character_quip" and summary:
        quip_instruction = getattr(getattr(cfg, "tts", None), "character_quip_instruction", None)
        summary = append_character_quip(
            summary, active_agent=active_agent, instruction=quip_instruction
        )

    # Persist in turn session memory for contextual expansion ("tell me everything")
    try:
        from voicefi.integrations.turn_memory import TurnSessionMemory

        TurnSessionMemory.get_instance().record_turn(
            conv_id=conv_id,
            full_text=raw_content or summary,
            spoken_text=summary,
            agent_name=active_agent,
            format_used=turn_format,
        )
    except Exception:
        pass

    turn_sig = f"{conv_id}:{summary[:35]}"
    try:
        claimed = claim_turn(conv_id, turn_sig, step_index=step_index, delivered_via="hook")
    except TypeError:
        claimed = claim_turn(conv_id, turn_sig)
    if not claimed:
        # Already claimed and handled by watcher or another process
        return {}

    def _safe_cleanup_hud_state():
        try:
            from voicefi.tts.base import get_cross_process_hud_state, clear_cross_process_hud_state

            state_info = get_cross_process_hud_state()
            if state_info and state_info.get("state") in ("listening", "hearing", "transcribing"):
                clear_cross_process_hud_state()
        except Exception:
            pass

    try:
        # Track pending clarifying question / options if present
        if (
            summary
            and summary.strip().endswith("?")
            and (" or " in summary.lower() or '"' in summary)
        ):
            set_pending_question(conv_id, summary)

        if summary:
            from voicefi.audio.echo_canceller import record_agent_spoken

            record_agent_spoken(summary)

        routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
        mute_mac_active = getattr(
            getattr(cfg, "companion", None), "mute_mac_when_companion_active", True
        )
        is_mobile = get_claimed_turn_origin(
            conv_id, turn_sig, step_index=step_index
        ) == "mobile" or peek_mobile_turn_origin(conv_id)

        if routing == "phone_only":
            return {}
        elif routing == "origin_only":
            if is_mobile:
                # Turn originated from mobile phone companion and user requested origin_only
                return {}
        elif routing == "smart":
            if is_mobile:
                # Turn originated from mobile companion -> only speak on phone, suppress Mac
                return {}
            if mute_mac_active and has_active_companion_client(require_mobile=True):
                # Mobile companion client is actively connected and mute_mac is enabled
                return {}

        from voicefi.audio.meeting_detection import is_user_on_call

        if is_user_on_call():
            print("[AntigravityHook] User is on a call. Skipping spoken feedback and auto-listen.")
            return {}

        respect_media = getattr(getattr(cfg, "tts", None), "respect_media_playback", True)
        if respect_media:
            try:
                from voicefi.audio.media_detection import (
                    is_active_media_playing,
                    wait_for_media_completion,
                )

                if is_active_media_playing():
                    media_timeout = getattr(getattr(cfg, "tts", None), "media_pause_timeout", 600.0)
                    cleared = wait_for_media_completion(max_wait_seconds=media_timeout)
                    if not cleared:
                        print(
                            "[AntigravityHook] 🎬 Media clip still playing after timeout. Skipping speech and auto-listen."
                        )
                        return {}
            except Exception:
                pass

        spoken_text = summary
        if not is_active and getattr(cfg.antigravity, "unfocused_voice_prefix", False):
            from voicefi.integrations.conversations import ConversationTracker

            tracker = ConversationTracker()
            pb_titles = tracker._get_pb_titles()
            short_title = pb_titles.get(conv_id, "background agent")[:24]
            spoken_text = f"Update from {short_title}: {summary}"

        # Apply Walken voice acting cadence if Walken / Continental is configured
        active_voice = str(
            (payload.get("voice") if isinstance(payload, dict) else None)
            or getattr(getattr(cfg, "tts", None), "voice", "")
            or ""
        ).lower()
        active_ref = str(
            (getattr(cfg.agents.get("antigravity"), "f5_ref_audio", None) if hasattr(cfg, "agents") and "antigravity" in cfg.agents else None)
            or getattr(getattr(cfg, "tts", None), "f5_ref_audio", "")
            or ""
        ).lower()
        if "walken" in active_voice or "continental" in active_voice or "continental" in active_ref:
            from voicefi.tts.director import TheatricalDirector

            archetype = "continental" if ("continental" in active_voice or "continental" in active_ref) else "standard"
            spoken_text = TheatricalDirector.direct_walken_cadence(
                spoken_text, archetype=archetype, include_prefix=False
            )

        should_speak = bool(cfg.antigravity.read_summary_aloud and spoken_text)
        if turn_format == "chime_only":
            try:
                from voicefi.audio.chimes import play_turn_complete_chime

                chime_name = getattr(getattr(cfg, "tts", None), "turn_complete_chime", "Glass")
                play_turn_complete_chime(chime_name)
            except Exception:
                pass
            should_speak = False

        if should_speak:
            mark_turn_spoken_on_mac(conv_id, turn_sig, step_index=step_index)
            try:
                from voicefi.tts.base import stop_active_playback

                stop_active_playback()
            except Exception:
                pass
        should_listen = bool(is_active and cfg.antigravity.auto_listen and summary)
        from voicefi.integrations.turn_lock import (
            acquire_active_listener_lock,
            release_active_listener_lock,
        )

        hook_start_time = time.time()
        user_transcribed_chars: int = 0
        temp_wav: Optional[Path] = None

        from voicefi.audio.recorder import resolve_barge_in_mode

        is_barge_in_on, _ = resolve_barge_in_mode(getattr(cfg.vad, "barge_in", "auto"))
        barge_in_active = bool(should_speak and should_listen and is_barge_in_on)

        if barge_in_active and not acquire_active_listener_lock(conv_id):
            print(
                "[AntigravityHook] ⏸️ Another conversation is already actively listening. Yielding mic.",
                flush=True,
            )
            should_listen = False
            barge_in_active = False

        voice_override = payload.get("voice") if isinstance(payload, dict) else None
        if barge_in_active:
            tts = get_tts_engine(
                cfg,
                agent_name=active_agent,
                voice_override=voice_override,
                provider_override="gemini_live" if is_live_turn else None,
                project_name=project_name,
                workspace_path=workspace_path,
                app_name="Antigravity",
                conv_id=conv_id,
            )

            def _speak_and_finish():
                try:
                    tts.stream_speak(spoken_text, block=True)
                except DuplicateSpeechSuppressed:
                    pass
                except Exception:
                    pass
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
                vad_engine=getattr(cfg.vad, "engine", "auto"),
                speech_threshold=getattr(cfg.vad, "speech_threshold", 0.37),
            )

            def _on_live(txt: str):
                set_cross_process_hud_state(
                    "listening",
                    text=txt,
                    agent_name=active_agent,
                    user_name=cfg.user_name,
                    live_stream=True,
                    app_name="Antigravity",
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

            fb_loop = getattr(getattr(cfg, "proactive", None), "feedback_loop", None)
            listen_timeout = getattr(fb_loop, "timeout_seconds", 12.0) if fb_loop else 12.0

            try:
                audio_data, temp_wav = recorder.record_speech_auto(
                    on_speech_start=lambda: set_cross_process_hud_state(
                        "hearing",
                        agent_name=active_agent,
                        user_name=cfg.user_name,
                        app_name="Antigravity",
                        conv_id=conv_id,
                    ),
                    on_pause_change=lambda paused: set_cross_process_hud_state(
                        "hearing" if not paused else "listening",
                        agent_name=active_agent,
                        user_name=cfg.user_name,
                        app_name="Antigravity",
                        conv_id=conv_id,
                    ),
                    on_barge_in=_on_barge_in,
                    on_live_transcript=_on_live,
                    on_listening_tick=_on_tick,
                    timeout=listen_timeout,
                    conv_id=conv_id,
                    agent_name=active_agent,
                )
            finally:
                release_active_listener_lock(conv_id)
        else:
            if should_speak:
                tts = get_tts_engine(
                    cfg,
                    agent_name=active_agent,
                    voice_override=voice_override,
                    provider_override="gemini_live" if is_live_turn else None,
                    project_name=project_name,
                    workspace_path=workspace_path,
                    app_name="Antigravity",
                    conv_id=conv_id,
                )
                try:
                    tts.stream_speak(spoken_text, block=True)
                except DuplicateSpeechSuppressed:
                    return {}

            if cfg.antigravity.show_speech_popup:
                try:
                    from voicefi.ui.speech_hud import AgentSpeechHUD

                    linger = getattr(cfg.antigravity, "speech_popup_linger_seconds", 3.0)
                    AgentSpeechHUD.get_instance().finish_speech(linger_seconds=linger)
                except Exception:
                    pass

            if should_listen:
                try:
                    from voicefi.audio.media_detection import is_active_media_playing

                    if is_active_media_playing():
                        print(
                            "[AntigravityHook] 🎬 Media playback active. Skipping auto-listen handoff."
                        )
                        should_listen = False
                except Exception:
                    pass

            if should_listen:
                from voicefi.integrations.turn_lock import acquire_active_listener_lock

                if not acquire_active_listener_lock(conv_id):
                    print(
                        "[AntigravityHook] ⏸️ Another conversation is already actively listening. Yielding mic.",
                        flush=True,
                    )
                    should_listen = False

            if should_listen:
                try:
                    from voicefi.tts.base import is_system_audio_playing

                    max_audio_wait = 30
                    while is_system_audio_playing() and max_audio_wait > 0:
                        time.sleep(0.1)
                        max_audio_wait -= 1

                    # Immediate seamless transition: open mic right after speech finishes
                    time.sleep(0.2)

                    if getattr(cfg.audio_cues, "mic_open_chime", False) and cfg.audio_cues.enabled:
                        play_chime("start", block=True)
                        time.sleep(0.15)

                    set_cross_process_hud_state(
                        "listening",
                        agent_name=active_agent,
                        user_name=cfg.user_name,
                        app_name="Antigravity",
                        conv_id=conv_id,
                    )

                    def _on_live(txt: str):
                        set_cross_process_hud_state(
                            "listening",
                            text=txt,
                            agent_name=active_agent,
                            user_name=cfg.user_name,
                            live_stream=True,
                            app_name="Antigravity",
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

                            UnifiedDynamicIslandHUD.get_instance().update_audio_level(
                                energy, conf, is_spk
                            )
                        except Exception:
                            pass

                    recorder = AudioRecorder(
                        sample_rate=cfg.vad.sample_rate,
                        energy_threshold=cfg.vad.energy_threshold,
                        silence_duration=cfg.vad.silence_duration,
                        max_record_seconds=cfg.vad.max_record_seconds,
                        barge_in=False,
                        vad_engine=getattr(cfg.vad, "engine", "auto"),
                        speech_threshold=getattr(cfg.vad, "speech_threshold", 0.37),
                    )

                    fb_loop = getattr(getattr(cfg, "proactive", None), "feedback_loop", None)
                    listen_timeout = getattr(fb_loop, "timeout_seconds", 12.0) if fb_loop else 12.0

                    listen_start_time = time.time()
                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=lambda: set_cross_process_hud_state(
                            "hearing",
                            agent_name=active_agent,
                            user_name=cfg.user_name,
                            app_name="Antigravity",
                            conv_id=conv_id,
                        ),
                        on_live_transcript=_on_live,
                        on_listening_tick=_on_tick,
                        timeout=listen_timeout,
                        conv_id=conv_id,
                        agent_name=active_agent,
                    )
                finally:
                    release_active_listener_lock(conv_id)

        from voicefi.tts.base import is_speech_interrupted

        check_interrupted_time = (
            listen_start_time
            if ("listen_start_time" in locals() and should_listen)
            else hook_start_time
        )
        if is_speech_interrupted(check_interrupted_time):
            if temp_wav and Path(temp_wav).is_file():
                Path(temp_wav).unlink(missing_ok=True)
            clear_cross_process_hud_state()
            return {}

        if temp_wav and Path(temp_wav).is_file():
            set_cross_process_hud_state(
                "transcribing",
                agent_name=active_agent,
                app_name="Antigravity",
                conv_id=conv_id,
            )
            stt = get_stt_engine(cfg)
            try:
                transcription = stt.transcribe(temp_wav)
            finally:
                Path(temp_wav).unlink(missing_ok=True)

            if is_speech_interrupted(check_interrupted_time):
                clear_cross_process_hud_state()
                return {}

            if not transcription or not transcription.strip():
                clear_cross_process_hud_state()
                _safe_cleanup_hud_state()
                return {}

            clean_t = transcription.strip()
            user_transcribed_chars = len(clean_t)
            print(f'[Antigravity] 🎙️ Transcribed speech: "{clean_t}"', flush=True)
            from voicefi.audio.echo_canceller import is_acoustic_echo

            if is_acoustic_echo(clean_t, reference_text=summary):
                print(
                    f'[Antigravity] 🛡️ Suppressed acoustic self-echo: "{clean_t}" (matched agent output)',
                    flush=True,
                )
                clear_cross_process_hud_state()
                return {}

            pending_q = get_pending_question(conv_id)
            eval_res = ActiveListeningEngine.evaluate(
                clean_t, pending_question=pending_q, is_ambient=False
            )
            print(
                f"[ActiveListening] Intent evaluation: {eval_res.category.value} (is_actionable={eval_res.is_actionable})",
                flush=True,
            )

            if eval_res.category == SpokenIntentCategory.EXPAND_READOUT:
                print(f"[Antigravity] 📖 Spoken intent EXPAND_READOUT detected: '{clean_t}'", flush=True)
                from voicefi.integrations.turn_memory import TurnSessionMemory

                full_raw = TurnSessionMemory.get_instance().get_full_readout_text(conv_id)
                if not full_raw or not full_raw.strip():
                    full_raw = summary or "I don't have additional details for the latest turn."
                expanded_spoken = clean_markdown_for_speech(full_raw, full_read=True)
                set_cross_process_hud_state(
                    "speaking",
                    text=expanded_spoken[:80],
                    agent_name=active_agent,
                    app_name="Antigravity",
                    conv_id=conv_id,
                )
                tts = get_tts_engine(
                    cfg,
                    agent_name=active_agent,
                    voice_override=voice_override,
                    app_name="Antigravity",
                    conv_id=conv_id,
                )
                try:
                    tts.stream_speak(expanded_spoken, block=True)
                except Exception as e:
                    print(f"[Antigravity] Expand speech error: {e}")
                finally:
                    clear_cross_process_hud_state()
                    _safe_cleanup_hud_state()
                return {}

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
                target_channel = getattr(
                    eval_res, "target_channel", SpokenTargetChannel.ANTIGRAVITY
                )
                delivered = False
                if cfg.antigravity.inject_to_active_window:
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

                        delivered = inject_text_to_claude(
                            routed_text,
                            submit_enter=True,
                            from_conv_id=conv_id,
                            from_engine="antigravity",
                            include_envelope=True,
                        )
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
                    elif is_live_turn:
                        # Turn-end Live mode toggle: route spoken turn directly to Gemini Live API
                        from voicefi.integrations.live_conversation import query_live_api_spoken_turn

                        print(
                            f"[Antigravity/GeminiLive] 🎙️ Live mode toggle active -> routing to Gemini Live API: '{final_text}'",
                            flush=True,
                        )
                        delivered = query_live_api_spoken_turn(
                            user_prompt=final_text,
                            context=summary,
                            conv_id=conv_id,
                            persona_name=getattr(cfg.tts, "voice", "Fenrir"),
                            config=cfg,
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

                channel_name = getattr(target_channel, "value", str(target_channel))
                if delivered:
                    print(
                        f"[Antigravity] ✅ Delivered successfully to {channel_name} ({str(conv_id)[:8]}).",
                        flush=True,
                    )
                else:
                    print("[Antigravity] ⚠️ Delivery failed — text left on clipboard.", flush=True)

                if getattr(cfg.audio_cues, "sent_chime_enabled", False) and cfg.audio_cues.enabled:
                    play_chime(cfg.audio_cues.sent_chime, block=False)

                try:
                    from voicefi.telemetry import capture_proactive_feedback_loop

                    capture_proactive_feedback_loop(
                        caller_agent="antigravity",
                        user_chars=len(final_text),
                        target_channel=channel_name,
                    )
                except Exception:
                    pass

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
        else:
            _safe_cleanup_hud_state()

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
                    user_chars=user_transcribed_chars,
                )
            except Exception:
                pass
    finally:
        _safe_cleanup_hud_state()
        try:
            from voicefi.integrations.conversations import mark_turn_completed

            mark_turn_completed(turn_sig, conv_id=conv_id, step_index=step_index)
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
