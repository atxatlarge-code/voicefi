"""
Live transcript watcher for Antigravity.
Monitors transcript.jsonl in real-time across active conversations to trigger speech & mic on turn completion.
"""

import glob
import json
import os
import re
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, Callable, List

from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts import get_tts_engine, stop_all_speech
from voicefi.tts.base import is_system_audio_playing
from voicefi.stt import get_stt_engine
from voicefi.audio.recorder import AudioRecorder
from voicefi.audio.chimes import play_chime
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.integrations.injector import inject_text_to_active_app, focus_antigravity, send_message_to_antigravity
from voicefi.integrations.conversations import (
    ConversationTracker,
    ConversationInfo,
    claim_turn,
    pop_mobile_turn_origin,
    get_claimed_turn_origin,
    has_active_companion_client,
    set_pending_question,
    get_pending_question,
    resolve_pending_question,
    clear_pending_question,
)
from voicefi.integrations.active_listening import ActiveListeningEngine, SpokenIntentCategory


def extract_thought_summary(thinking_text: str, max_words: int = 14) -> str:
    """
    Extract the model's verbatim thought header or opening reasoning line without translation.
    Strips markdown formatting, bold tags, and emojis.
    """
    if not thinking_text or not thinking_text.strip():
        return ""
    text = thinking_text.strip()

    # 1. Look for bold header like **Analyzing the Core Issue** or **Inspecting watcher.py**
    bold_match = re.search(r"\*\*([^*]+)\*\*", text)
    if bold_match:
        header = bold_match.group(1).strip()
        cleaned_header = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]", "", header)
        cleaned_header = cleaned_header.strip(":.- ")
        if cleaned_header:
            words = cleaned_header.split()
            if len(words) > max_words:
                return " ".join(words[:max_words]) + "..."
            return cleaned_header

    # 2. Otherwise extract first non-empty line
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        first_line = lines[0]
        first_line = re.sub(r"^[#*`_\s-]+", "", first_line).strip()
        first_line = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]", "", first_line).strip()
        if first_line:
            words = first_line.split()
            if len(words) > max_words:
                return " ".join(words[:max_words]) + "..."
            return first_line

    return ""


def get_recent_transcript_paths(limit: int = 5) -> List[Path]:
    """Find recently modified transcript.jsonl files in ~/.gemini/antigravity/brain/."""
    tracker = ConversationTracker()
    return tracker.get_recent_transcripts(limit=limit)


def find_latest_transcript_path() -> Optional[Path]:
    paths = get_recent_transcript_paths(limit=1)
    return paths[0] if paths else None


class TranscriptWatcher:
    """Watches active Antigravity transcripts for completed turns across multiple conversations."""

    def __init__(
        self,
        config: Optional[VoiceFiConfig] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
    ):
        self.config = config or load_config()
        self.on_state_change = on_state_change
        self.tracker = ConversationTracker()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_steps: Dict[str, int] = {}
        self._file_offsets: Dict[str, int] = {}
        self._is_handling_turn = False
        self._interrupted = False
        self.active_recorder: Optional[AudioRecorder] = None

    def finish_listening(self):
        """Immediately finish recording and send captured audio (e.g. Enter key pressed)."""
        if self.active_recorder:
            self.active_recorder.stop()

    def start(self):
        """Start the background watcher thread."""
        if self._running:
            return
        self._running = True

        # Initialize existing highest step indices and file sizes so we only trigger on NEW turns
        for p in get_recent_transcript_paths(limit=5):
            path_str = str(p)
            self._processed_steps[path_str] = self._get_highest_step_index(p)
            try:
                self._file_offsets[path_str] = p.stat().st_size
            except Exception:
                self._file_offsets[path_str] = 0

        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background watcher thread."""
        self._running = False

    def interrupt(self):
        """Interrupt active turn handling and stop speaking."""
        self._interrupted = True
        stop_all_speech()
        try:
            from voicefi.ui.speech_hud import AgentSpeechHUD
            AgentSpeechHUD.get_instance().hide()
        except Exception:
            pass
        if self.active_recorder:
            self.active_recorder.stop()
        self._is_handling_turn = False
        if self.on_state_change:
            self.on_state_change("idle")

    def _notify_state(self, state: str, **kwargs):
        if self.on_state_change:
            try:
                self.on_state_change(state, **kwargs)
            except TypeError:
                try:
                    self.on_state_change(state)
                except Exception:
                    pass
            except Exception:
                pass

    def _watch_loop(self):
        """Continuous polling loop watching recent transcript.jsonl files."""
        while self._running:
            try:
                if not self._is_handling_turn:
                    recent_paths = get_recent_transcript_paths(limit=3)
                    for path in recent_paths:
                        self._check_transcript_update(path)
                        if self._is_handling_turn:
                            break
            except Exception:
                pass

            time.sleep(0.5)

    def _get_highest_step_index(self, path: Path) -> int:
        highest = -1
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                        idx = step.get("step_index", -1)
                        if idx > highest:
                            highest = idx
                    except Exception:
                        pass
        except Exception:
            pass
        return highest

    def _check_transcript_update(self, path: Path):
        """Inspect file for newly appended agent turns using byte offsets."""
        path_str = str(path)
        try:
            current_size = path.stat().st_size
        except Exception:
            return

        last_offset = self._file_offsets.get(path_str, 0)
        # Fast exit if no new bytes were appended to file
        if current_size == last_offset and path_str in self._processed_steps:
            return

        # Reset offset if file was truncated or replaced
        if current_size < last_offset:
            last_offset = 0

        last_processed = self._processed_steps.get(path_str, -1)
        last_step: Optional[Dict[str, Any]] = None
        highest_idx = last_processed

        try:
            with open(path, "r", encoding="utf-8") as f:
                if last_offset > 0:
                    f.seek(last_offset)
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        step = json.loads(line)
                        idx = step.get("step_index", -1)
                        if idx > highest_idx:
                            highest_idx = idx
                        last_step = step
                    except Exception:
                        continue
                self._file_offsets[path_str] = f.tell()
        except Exception:
            return

        if highest_idx <= last_processed or last_step is None:
            return

        step_type = last_step.get("type", "")
        step_source = last_step.get("source", "")
        content = last_step.get("content", "")
        tool_calls = last_step.get("tool_calls", [])
        thinking = last_step.get("thinking", "")

        if (
            step_type == "PLANNER_RESPONSE"
            and step_source == "MODEL"
            and last_step.get("status") == "DONE"
            and not tool_calls
            and content
        ):
            self._processed_steps[path_str] = highest_idx
            conv_info = self.tracker.parse_conversation(path)
            if conv_info:
                self.tracker.set_active_focus(conv_info.id, transcript_path=path, title=conv_info.title)

            detected_role = last_step.get("role") or last_step.get("agent_role") or "antigravity"
            self._handle_turn_ready(
                content,
                conv_info,
                agent_role=str(detected_role),
                is_active=True,
                step_index=highest_idx,
                transcript_path=path,
            )
        elif step_type == "PLANNER_RESPONSE" and tool_calls:
            self._processed_steps[path_str] = highest_idx
            detected_role = last_step.get("role") or last_step.get("agent_role") or "antigravity"
            first_tool = tool_calls[0] if isinstance(tool_calls, list) and tool_calls else {}
            tool_name = first_tool.get("name") or "tool"
            tool_summary = first_tool.get("toolSummary") or first_tool.get("toolAction") or f"Running {tool_name}..."
            tool_summary = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]", "", str(tool_summary)).strip()
            self._notify_state(
                "working",
                agent_name=str(detected_role),
                tool_action=tool_summary,
            )
        elif step_type == "PLANNER_RESPONSE" and thinking:
            self._processed_steps[path_str] = highest_idx
            detected_role = last_step.get("role") or last_step.get("agent_role") or "antigravity"
            thought_summary = extract_thought_summary(str(thinking))
            self._notify_state(
                "thinking",
                agent_name=str(detected_role),
                detail=thought_summary or "Reasoning...",
            )
        elif step_type == "USER_INPUT":
            self._processed_steps[path_str] = highest_idx
            user_content = last_step.get("content", "")
            if isinstance(user_content, str) and user_content.strip():
                clean_prompt = clean_markdown_for_speech(user_content, max_words=18)
                cues_cfg = getattr(self.config, "audio_cues", None)
                if cues_cfg and getattr(cues_cfg, "enabled", True):
                    sent_chime = getattr(cues_cfg, "sent_chime", "")
                    if sent_chime:
                        play_chime(sent_chime, block=False)

                user_name = getattr(self.config, "user_name", "Jake")
                self._notify_state(
                    "user_prompt",
                    prompt=clean_prompt,
                    user_name=user_name,
                    source="Antigravity",
                    linger=1.8,
                )
            else:
                self._notify_state(
                    "thinking",
                    agent_name="Antigravity",
                    detail="Processing...",
                )

    def _handle_turn_ready(
        self,
        agent_message: str,
        conv_info: Optional[ConversationInfo] = None,
        agent_role: Optional[str] = None,
        is_active: bool = True,
        step_index: Optional[int] = None,
        transcript_path: Optional[Path] = None,
    ):
        """Execute speech and microphone loop for the finished turn with Active Barge-In."""
        self._is_handling_turn = True
        self._interrupted = False
        try:
            cfg = load_config()
            self.config = cfg
            summary = clean_markdown_for_speech(agent_message, max_words=cfg.antigravity.max_spoken_words)

            if not is_active and not getattr(cfg.antigravity, "unfocused_agent_voice", None):
                # Unfocused turns should not be claimed or spoken by watcher
                return

            turn_cid = conv_info.id if conv_info else "unknown"
            if turn_cid == "unknown" and transcript_path:
                try:
                    cand = Path(transcript_path).parent.parent.parent.name
                    if len(cand) >= 8:
                        turn_cid = cand
                except Exception:
                    pass
            if turn_cid == "unknown":
                active_conv = self.tracker.get_active_or_latest()
                if active_conv:
                    turn_cid = active_conv.id

            turn_sig = f"{turn_cid}:{summary[:35]}"
            try:
                claimed = claim_turn(turn_cid, turn_sig, step_index=step_index)
            except TypeError:
                claimed = claim_turn(turn_cid, turn_sig)

            if not claimed:
                # Already claimed and handled by CLI hook
                return

            # Track pending clarifying question / options if present
            if summary and (summary.endswith("?") or " or " in summary.lower()):
                set_pending_question(turn_cid, summary)

            routing = getattr(getattr(cfg, "companion", None), "audio_routing", "smart")
            mute_mac_active = getattr(getattr(cfg, "companion", None), "mute_mac_when_companion_active", False)
            is_mobile = (get_claimed_turn_origin(turn_cid, turn_sig, step_index=step_index) == "mobile")

            if routing == "phone_only":
                # Suppress local Mac playback when all speech is routed to phone
                return
            elif routing in ("smart", "origin_only"):
                if is_mobile:
                    # Turn originated from mobile companion -> mobile phone handles speech & mic exclusively.
                    # Suppress local Mac playback to eliminate dual speaker echo.
                    return
                if routing == "smart" and mute_mac_active and has_active_companion_client():
                    # Mac suppressed because mobile companion is actively connected and mute_mac_when_companion_active is enabled.
                    return

            spoken_text = summary
            if not is_active:
                if conv_info and getattr(cfg.antigravity, "unfocused_voice_prefix", True):
                    short_title = conv_info.title[:24] if conv_info.title else "background agent"
                    spoken_text = f"Update from {short_title}: {summary}"

            target_agent = agent_role or "antigravity"
            should_speak = bool(cfg.antigravity.read_summary_aloud and spoken_text and not self._interrupted)
            should_listen = bool(is_active and cfg.antigravity.auto_listen and not self._interrupted)

            from voicefi.tts import find_persona
            _, resolved_voice, _ = cfg.resolve_voice(target_agent, is_focused=is_active)
            persona = find_persona(resolved_voice)
            pname = persona.name if persona else resolved_voice

            from voicefi.audio.recorder import resolve_barge_in_mode
            is_barge_in_on, _ = resolve_barge_in_mode(getattr(cfg.vad, "barge_in", "auto"))
            barge_in_active = bool(should_speak and should_listen and is_barge_in_on)

            # Trigger Native Floating Speech HUD if enabled
            if cfg.antigravity.show_speech_popup and spoken_text and not self._interrupted:
                try:
                    from voicefi.ui.speech_hud import AgentSpeechHUD
                    pos = getattr(cfg.antigravity, "speech_popup_position", "top_center")
                    AgentSpeechHUD.get_instance().show_speech(
                        spoken_text,
                        agent_name=target_agent,
                        role=agent_role,
                        persona_name=pname,
                        is_speaking=True,
                        position=pos,
                    )
                except Exception as e:
                    print(f"[Watcher] Speech HUD display notice: {e}")

            temp_wav: Optional[Path] = None

            if barge_in_active:
                # Active Barge-In: Start speech in background and monitor mic for user interruption
                from voicefi.tts.base import set_agent_speaking
                set_agent_speaking(True, text=spoken_text, agent_name=target_agent, persona_name=pname)
                self._notify_state(
                    "speaking",
                    text=spoken_text,
                    agent_name=target_agent,
                    persona_name=pname,
                )
                tts = get_tts_engine(cfg, agent_name=target_agent, is_focused=is_active)
                
                def _speak_and_finish_hud():
                    try:
                        tts.stream_speak(spoken_text, block=True)
                    finally:
                        if cfg.antigravity.show_speech_popup:
                            try:
                                from voicefi.ui.speech_hud import AgentSpeechHUD
                                linger = getattr(cfg.antigravity, "speech_popup_linger_seconds", 3.0)
                                AgentSpeechHUD.get_instance().finish_speech(linger_seconds=linger)
                            except Exception:
                                pass

                tts_thread = threading.Thread(
                    target=_speak_and_finish_hud,
                    daemon=True,
                )
                tts_thread.start()

                def _on_barge_in():
                    self._notify_state("hearing", user_name=cfg.user_name)
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
                    barge_in=True,
                    barge_in_sensitivity=getattr(cfg.vad, "barge_in_sensitivity", 1.0),
                )
                def _on_tick(energy: float, conf: float = 0.0, is_spk: bool = False):
                    try:
                        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
                        UnifiedDynamicIslandHUD.get_instance().update_audio_level(energy, conf, is_spk)
                    except Exception:
                        pass

                audio_data, temp_wav = recorder.record_speech_auto(
                    on_speech_start=lambda: self._notify_state("hearing", user_name=cfg.user_name),
                    on_pause_change=lambda paused: self._notify_state("speaking" if paused else "listening", user_name=cfg.user_name),
                    on_barge_in=_on_barge_in,
                    on_listening_tick=_on_tick,
                )
                self.active_recorder = None
            else:
                # Standard sequential speech then auto-listen
                if should_speak:
                    self._notify_state(
                        "speaking",
                        text=spoken_text,
                        agent_name=target_agent,
                        persona_name=pname,
                    )
                    tts = get_tts_engine(cfg, agent_name=target_agent, is_focused=is_active)
                    tts.stream_speak(spoken_text, block=True)

                if cfg.antigravity.show_speech_popup:
                    try:
                        from voicefi.ui.speech_hud import AgentSpeechHUD
                        linger = getattr(cfg.antigravity, "speech_popup_linger_seconds", 3.0)
                        AgentSpeechHUD.get_instance().finish_speech(linger_seconds=linger)
                    except Exception:
                        pass

                if self._interrupted:
                    return

                # Wait for speaker audio playback to 100% stop and acoustic reverb to decay
                max_audio_wait = 40
                while is_system_audio_playing() and max_audio_wait > 0 and not self._interrupted:
                    time.sleep(0.1)
                    max_audio_wait -= 1
                time.sleep(0.3)

                if should_listen:
                    if cfg.audio_cues.enabled:
                        play_chime("start", block=True)

                    self._notify_state("listening", user_name=cfg.user_name)
                    time.sleep(0.2)

                    def _on_live(txt: str):
                        try:
                            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
                            UnifiedDynamicIslandHUD.get_instance().update_live_transcription(txt, user_name=cfg.user_name)
                        except Exception:
                            pass

                    recorder = AudioRecorder(
                        sample_rate=cfg.vad.sample_rate,
                        energy_threshold=cfg.vad.energy_threshold,
                        silence_duration=cfg.vad.silence_duration,
                        max_record_seconds=cfg.vad.max_record_seconds,
                        barge_in=False,
                    )
                    self.active_recorder = recorder

                    def _on_tick(energy: float, conf: float = 0.0, is_spk: bool = False):
                        try:
                            from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
                            UnifiedDynamicIslandHUD.get_instance().update_audio_level(energy, conf, is_spk)
                        except Exception:
                            pass

                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=lambda: self._notify_state("hearing", user_name=cfg.user_name),
                        on_pause_change=lambda paused: self._notify_state("paused_agent_speaking" if paused else "listening", user_name=cfg.user_name),
                        on_live_transcript=_on_live,
                        on_listening_tick=_on_tick,
                    )
                    self.active_recorder = None
                else:
                    return

            if self._interrupted or not temp_wav or not Path(temp_wav).is_file():
                if temp_wav and Path(temp_wav).is_file():
                    Path(temp_wav).unlink(missing_ok=True)
                return

            self._notify_state("transcribing")
            stt = get_stt_engine(cfg)
            try:
                text = stt.transcribe(temp_wav)
            finally:
                Path(temp_wav).unlink(missing_ok=True)

            if text and text.strip() and not self._interrupted:
                clean_t = text.strip()
                from voicefi.audio.echo_canceller import is_acoustic_echo
                if is_acoustic_echo(clean_t, reference_text=spoken_text):
                    print(f"[Watcher] 🛡️ Suppressed acoustic self-echo: \"{clean_t}\" (matched agent output)")
                    return

                pending_q = get_pending_question(turn_cid)
                eval_res = ActiveListeningEngine.evaluate(clean_t, pending_question=pending_q, is_ambient=False)

                if eval_res.category == SpokenIntentCategory.PENDING_ANSWER:
                    print(f"[ActiveListening/Watcher] 🎯 Matched pending choice: '{eval_res.selected_option}'")
                    resolve_pending_question(turn_cid, selected_option=eval_res.selected_option)
                    text_to_send = eval_res.selected_option or eval_res.normalized_text
                else:
                    clear_pending_question(turn_cid)
                    text_to_send = eval_res.normalized_text or clean_t

                is_auto_send = getattr(getattr(cfg, "hud", None), "auto_send", True) and getattr(cfg.antigravity, "auto_send", True)

                def _send_payload(content: str):
                    if cfg.antigravity.inject_to_active_window:
                        cid = turn_cid if (turn_cid and turn_cid != "unknown") else (conv_info.id if conv_info else None)
                        send_message_to_antigravity(conv_id=cid, text=content, sender_name=cfg.user_name)

                    if cfg.audio_cues.enabled:
                        play_chime(cfg.audio_cues.sent_chime, block=False)

                    try:
                        if not os.environ.get("PYTEST_CURRENT_TEST"):
                            import rumps
                            title = conv_info.title if conv_info else "Antigravity Agent"
                            rumps.notification(f"VoiceFi • {title[:30]}", "Transcribed Voice", content[:100])
                    except Exception:
                        pass

                if is_auto_send:
                    _send_payload(text_to_send)
                    try:
                        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
                        UnifiedDynamicIslandHUD.get_instance().show_done(preview_text=text_to_send[:20])
                    except Exception:
                        pass
                else:
                    try:
                        from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD
                        hud = UnifiedDynamicIslandHUD.get_instance()
                        target_title = conv_info.title[:20] if (conv_info and conv_info.title) else "Antigravity"
                        hud.set_editing(text_to_send, on_submit=_send_payload, target_name=target_title)
                    except Exception:
                        _send_payload(text_to_send)
        finally:
            self._is_handling_turn = False
            self._notify_state("idle")
