"""
Live transcript watcher for Antigravity.
Monitors transcript.jsonl in real-time to automatically trigger speech & mic on turn completion.
"""

import glob
import json
import os
import time
import threading
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from talk2me.config import Talk2MeConfig, load_config
from talk2me.tts import get_tts_engine
from talk2me.stt import get_stt_engine
from talk2me.audio.recorder import AudioRecorder
from talk2me.audio.chimes import play_chime
from talk2me.integrations.antigravity import clean_markdown_for_speech
from talk2me.integrations.injector import inject_text_to_active_app


def find_latest_transcript_path() -> Optional[Path]:
    """Find the most recently modified transcript.jsonl in ~/.gemini/antigravity/brain/."""
    brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
    if not brain_dir.is_dir():
        return None

    pattern = str(brain_dir / "*" / ".system_generated" / "logs" / "transcript.jsonl")
    files = glob.glob(pattern)
    if not files:
        return None

    # Sort by modification time, newest first
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    return Path(files[0])


class TranscriptWatcher:
    """Watches active Antigravity transcript for completed turns."""

    def __init__(self, config: Optional[Talk2MeConfig] = None):
        self.config = config or load_config()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_processed_step_idx = -1
        self._last_transcript_path: Optional[Path] = None
        self._is_handling_turn = False

    def start(self):
        """Start the background watcher thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the background watcher thread."""
        self._running = False

    def _watch_loop(self):
        """Continuous polling loop watching transcript.jsonl."""
        while self._running:
            try:
                latest_path = find_latest_transcript_path()
                if latest_path and latest_path.is_file():
                    if latest_path != self._last_transcript_path:
                        self._last_transcript_path = latest_path
                        # Initialize step index on new file to the last line
                        self._last_processed_step_idx = self._get_highest_step_index(latest_path)

                    self._check_transcript_update(latest_path)
            except Exception as e:
                pass

            time.sleep(1.0)

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
        if self._is_handling_turn:
            return

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

        if highest_idx <= self._last_processed_step_idx or last_step is None:
            return

        step_type = last_step.get("type", "")
        step_source = last_step.get("source", "")
        content = last_step.get("content", "")
        tool_calls = last_step.get("tool_calls", [])

        # An agent turn is ready when:
        # 1. Source is MODEL / PLANNER_RESPONSE
        # 2. Status is DONE
        # 3. No pending tool calls in this step
        # 4. Content exists (agent response to user)
        if (
            step_type == "PLANNER_RESPONSE"
            and step_source == "MODEL"
            and last_step.get("status") == "DONE"
            and not tool_calls
            and content
        ):
            self._last_processed_step_idx = highest_idx
            self._handle_turn_ready(content)
        elif step_type == "USER_INPUT":
            # Update last processed on user input
            self._last_processed_step_idx = highest_idx

    def _handle_turn_ready(self, agent_message: str):
        """Execute speech and microphone loop for the finished turn."""
        self._is_handling_turn = True
        try:
            cfg = self.config
            summary = clean_markdown_for_speech(agent_message, max_words=cfg.antigravity.max_spoken_words)

            # 1. Speak summary
            if cfg.antigravity.read_summary_aloud and summary:
                tts = get_tts_engine(cfg)
                tts.speak(summary, block=True)

            # 2. Auto-listen
            if cfg.antigravity.auto_listen:
                if cfg.audio_cues.enabled:
                    play_chime("start", block=False)

                recorder = AudioRecorder(
                    sample_rate=cfg.vad.sample_rate,
                    energy_threshold=cfg.vad.energy_threshold,
                    silence_duration=cfg.vad.silence_duration,
                    max_record_seconds=cfg.vad.max_record_seconds,
                )

                audio_data, temp_wav = recorder.record_speech_auto()

                stt = get_stt_engine(cfg)
                try:
                    text = stt.transcribe(temp_wav)
                finally:
                    temp_wav.unlink(missing_ok=True)

                if text and text.strip():
                    if cfg.audio_cues.enabled:
                        play_chime("done", block=False)

                    if cfg.antigravity.inject_to_active_window:
                        inject_text_to_active_app(text, submit_enter=True)
        finally:
            self._is_handling_turn = False
