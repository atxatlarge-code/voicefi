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

from talk2me.config import Talk2MeConfig, load_config
from talk2me.tts import get_tts_engine, stop_all_speech
from talk2me.stt import get_stt_engine
from talk2me.audio.recorder import AudioRecorder
from talk2me.audio.chimes import play_chime
from talk2me.integrations.antigravity import clean_markdown_for_speech
from talk2me.integrations.injector import inject_text_to_active_app, focus_antigravity


def get_recent_transcript_paths(limit: int = 5) -> List[Path]:
    """Find recently modified transcript.jsonl files in ~/.gemini/antigravity/brain/."""
    brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
    if not brain_dir.is_dir():
        return []

    pattern = str(brain_dir / "*" / ".system_generated" / "logs" / "transcript.jsonl")
    files = glob.glob(pattern)
    if not files:
        return []

    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return [Path(f) for f in files[:limit]]


def find_latest_transcript_path() -> Optional[Path]:
    paths = get_recent_transcript_paths(limit=1)
    return paths[0] if paths else None


class TranscriptWatcher:
    """Watches active Antigravity transcripts for completed turns."""

    def __init__(
        self,
        config: Optional[Talk2MeConfig] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
    ):
        self.config = config or load_config()
        self.on_state_change = on_state_change
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._processed_steps: Dict[str, int] = {}
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

        # Initialize existing highest step indices so we only trigger on NEW turns
        for p in get_recent_transcript_paths(limit=5):
            self._processed_steps[str(p)] = self._get_highest_step_index(p)

        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background watcher thread."""
        self._running = False

    def interrupt(self):
        """Interrupt active turn handling and stop speaking."""
        self._interrupted = True
        stop_all_speech()
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
        """Inspect file for new completed agent turns."""
        path_str = str(path)
        last_processed = self._processed_steps.get(path_str, -1)

        last_step: Optional[Dict[str, Any]] = None
        highest_idx = -1

        try:
            with open(path, "r", encoding="utf-8") as f:
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
            self._handle_turn_ready(content)
        elif step_type == "USER_INPUT":
            self._processed_steps[path_str] = highest_idx

    def _handle_turn_ready(self, agent_message: str):
        """Execute speech and microphone loop for the finished turn."""
        self._is_handling_turn = True
        self._interrupted = False
        try:
            cfg = self.config
            summary = clean_markdown_for_speech(agent_message, max_words=cfg.antigravity.max_spoken_words)

            # 1. Speak summary
            if cfg.antigravity.read_summary_aloud and summary and not self._interrupted:
                self._notify_state("speaking")
                tts = get_tts_engine(cfg)
                tts.speak(summary, block=True)

            if self._interrupted:
                return

            # Brief pause for speaker acoustics to clear before opening mic
            time.sleep(0.4)

            # 2. Auto-listen
            if cfg.antigravity.auto_listen and not self._interrupted:
                if cfg.audio_cues.enabled:
                    play_chime("start", block=True)

                self._notify_state("listening")
                time.sleep(0.1)

                recorder = AudioRecorder(
                    sample_rate=cfg.vad.sample_rate,
                    energy_threshold=cfg.vad.energy_threshold,
                    silence_duration=1.3,
                    max_record_seconds=cfg.vad.max_record_seconds,
                )
                self.active_recorder = recorder

                audio_data, temp_wav = recorder.record_speech_auto(
                    on_speech_start=lambda: self._notify_state("hearing")
                )
                self.active_recorder = None

                if self._interrupted:
                    temp_wav.unlink(missing_ok=True)
                    return

                self._notify_state("transcribing")
                stt = get_stt_engine(cfg)
                try:
                    text = stt.transcribe(temp_wav)
                finally:
                    temp_wav.unlink(missing_ok=True)

                if text and text.strip() and not self._interrupted:
                    if cfg.antigravity.inject_to_active_window:
                        inject_text_to_active_app(text, submit_enter=True, target_antigravity=True)

                    if cfg.audio_cues.enabled:
                        play_chime(cfg.audio_cues.sent_chime, block=False)

                    try:
                        import rumps
                        rumps.notification("Talk 2 Me", "Transcribed Voice", text[:100])
                    except Exception:
                        pass
        finally:
            self._is_handling_turn = False
            self._notify_state("idle")
