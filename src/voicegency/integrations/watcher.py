"""
Live transcript watcher for Antigravity.
Monitors transcript.jsonl in real-time across active conversations to trigger speech & mic on turn completion.
"""

import glob
import json
import os
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, Callable, List

from voicegency.config import VoicegencyConfig, load_config
from voicegency.tts import get_tts_engine, stop_all_speech
from voicegency.tts.base import is_system_audio_playing
from voicegency.stt import get_stt_engine
from voicegency.audio.recorder import AudioRecorder
from voicegency.audio.chimes import play_chime
from voicegency.integrations.antigravity import clean_markdown_for_speech
from voicegency.integrations.injector import inject_text_to_active_app, focus_antigravity, send_message_to_antigravity
from voicegency.integrations.conversations import ConversationTracker, ConversationInfo, claim_turn


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
        config: Optional[VoicegencyConfig] = None,
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
            from voicegency.ui.speech_hud import AgentSpeechHUD
            AgentSpeechHUD.get_instance().hide()
        except Exception:
            pass
        if self.active_recorder:
            self.active_recorder.stop()
        self._is_handling_turn = False
        if self.on_state_change:
            self.on_state_change("idle")

    def _notify_state(self, state: str):
        if self.on_state_change:
            try:
                self.on_state_change(state)
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

        if (
            step_type == "PLANNER_RESPONSE"
            and step_source == "MODEL"
            and last_step.get("status") == "DONE"
            and not tool_calls
            and content
        ):
            self._processed_steps[path_str] = highest_idx
            conv_info = self.tracker.parse_conversation(path)
            
            active_conv = self.tracker.get_active_or_latest()
            active_id = active_conv.id if active_conv else None
            if active_id is None and conv_info:
                self.tracker.set_active_focus(conv_info.id)
                active_id = conv_info.id

            is_active = (conv_info is not None and conv_info.id == active_id)
            detected_role = last_step.get("role") or last_step.get("agent_role") or "antigravity"
            self._handle_turn_ready(content, conv_info, agent_role=str(detected_role), is_active=is_active)
        elif step_type == "USER_INPUT":
            self._processed_steps[path_str] = highest_idx

    def _handle_turn_ready(
        self,
        agent_message: str,
        conv_info: Optional[ConversationInfo] = None,
        agent_role: Optional[str] = None,
        is_active: bool = True,
    ):
        """Execute speech and microphone loop for the finished turn with Active Barge-In."""
        self._is_handling_turn = True
        self._interrupted = False
        try:
            cfg = load_config()
            self.config = cfg
            summary = clean_markdown_for_speech(agent_message, max_words=cfg.antigravity.max_spoken_words)

            turn_cid = conv_info.id if conv_info else "unknown"
            turn_sig = f"{turn_cid}:{summary[:35]}"
            if not claim_turn(turn_cid, turn_sig):
                # Already claimed and handled by CLI hook
                return

            spoken_text = summary
            if not is_active and conv_info:
                if getattr(cfg.antigravity, "unfocused_voice_prefix", True):
                    short_title = conv_info.title[:24] if conv_info.title else "background agent"
                    spoken_text = f"Update from {short_title}: {summary}"

            target_agent = agent_role or "antigravity"
            should_speak = bool(cfg.antigravity.read_summary_aloud and spoken_text and not self._interrupted)
            should_listen = bool(is_active and cfg.antigravity.auto_listen and not self._interrupted)
            barge_in_active = bool(should_speak and should_listen and getattr(cfg.vad, "barge_in", True))

            # Trigger Native Floating Speech HUD if enabled
            if cfg.antigravity.show_speech_popup and spoken_text and not self._interrupted:
                try:
                    from voicegency.ui.speech_hud import AgentSpeechHUD
                    from voicegency.tts import find_persona
                    _, resolved_voice, _ = cfg.resolve_voice(target_agent, is_focused=is_active)
                    persona = find_persona(resolved_voice)
                    pname = persona.name if persona else resolved_voice
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
                self._notify_state("speaking")
                tts = get_tts_engine(cfg, agent_name=target_agent, is_focused=is_active)
                
                def _speak_and_finish_hud():
                    try:
                        tts.stream_speak(spoken_text, block=True)
                    finally:
                        if cfg.antigravity.show_speech_popup:
                            try:
                                from voicegency.ui.speech_hud import AgentSpeechHUD
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
                    self._notify_state("hearing")
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
                self.active_recorder = recorder

                audio_data, temp_wav = recorder.record_speech_auto(
                    on_speech_start=lambda: self._notify_state("hearing"),
                    on_pause_change=lambda paused: self._notify_state("speaking" if paused else "listening"),
                    on_barge_in=_on_barge_in,
                )
                self.active_recorder = None
            else:
                # Standard sequential speech then auto-listen
                if should_speak:
                    self._notify_state("speaking")
                    tts = get_tts_engine(cfg, agent_name=target_agent, is_focused=is_active)
                    tts.stream_speak(spoken_text, block=True)

                if cfg.antigravity.show_speech_popup:
                    try:
                        from voicegency.ui.speech_hud import AgentSpeechHUD
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

                    self._notify_state("listening")
                    time.sleep(0.2)

                    recorder = AudioRecorder(
                        sample_rate=cfg.vad.sample_rate,
                        energy_threshold=cfg.vad.energy_threshold,
                        silence_duration=cfg.vad.silence_duration,
                        max_record_seconds=cfg.vad.max_record_seconds,
                        barge_in=False,
                    )
                    self.active_recorder = recorder

                    audio_data, temp_wav = recorder.record_speech_auto(
                        on_speech_start=lambda: self._notify_state("hearing"),
                        on_pause_change=lambda paused: self._notify_state("paused_agent_speaking" if paused else "listening"),
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
                if cfg.antigravity.inject_to_active_window:
                    conv_id = conv_info.id if conv_info else None
                    send_message_to_antigravity(conv_id=conv_id, text=text)

                if cfg.audio_cues.enabled:
                    play_chime(cfg.audio_cues.sent_chime, block=False)

                try:
                    import rumps
                    title = conv_info.title if conv_info else "Antigravity Agent"
                    rumps.notification(f"Voicegency • {title[:30]}", "Transcribed Voice", text[:100])
                except Exception:
                    pass
        finally:
            self._is_handling_turn = False
            self._notify_state("idle")
