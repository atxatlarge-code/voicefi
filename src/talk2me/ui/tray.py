"""
macOS Menu Bar Companion App using rumps.
Provides visual status, live transcript watching, conversation jumping, and targeted voice dictation.
"""

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
import rumps

from talk2me.config import load_config, save_config, get_default_config_path
from talk2me.license import FeatureGate
from talk2me.tts import get_tts_engine, stop_all_speech
from talk2me.stt import get_stt_engine
from talk2me.audio.recorder import AudioRecorder
from talk2me.audio.chimes import play_chime
from talk2me.integrations.injector import inject_text_to_active_app, focus_antigravity
from talk2me.integrations.watcher import TranscriptWatcher


class Talk2MeTrayApp(rumps.App):
    """macOS Status Bar Menu Application for Talk 2 Me."""

    def __init__(self):
        super(Talk2MeTrayApp, self).__init__("Talk 2 Me", icon=None, title="🎙️")
        self.config = load_config()

        # Start live Antigravity transcript watcher with UI state callback
        self.watcher = TranscriptWatcher(
            self.config,
            on_state_change=self.handle_state_change,
        )
        self.watcher.start()

        # Build Menu Items
        self.stop_speaking_item = rumps.MenuItem("🛑 Stop Talking (Escape)", callback=self.stop_speaking_now)
        self.talk_to_agent_item = rumps.MenuItem(
            "🎙️ Talk to Antigravity ( ` )",
            callback=self.trigger_talk_to_antigravity,
        )
        self.focus_agent_item = rumps.MenuItem("💬 Switch to Antigravity Window", callback=self.trigger_focus_antigravity)
        self.listen_anywhere_item = rumps.MenuItem(
            "🎤 Dictate to Current Window (Cmd + Option + Space)",
            callback=self.trigger_manual_listen,
        )

        self.auto_listen_item = rumps.MenuItem(
            "Auto-Listen on Agent Turn",
            callback=self.toggle_auto_listen,
        )
        self.auto_listen_item.state = 1 if self.config.antigravity.auto_listen else 0

        self.read_summary_item = rumps.MenuItem(
            "Read Agent Summaries Aloud",
            callback=self.toggle_read_summary,
        )
        self.read_summary_item.state = 1 if self.config.antigravity.read_summary_aloud else 0

        tier_info = FeatureGate.get_tier_summary(self.config)
        self.tier_item = rumps.MenuItem(f"Tier: {tier_info['tier']}", callback=None)

        self.menu = [
            self.stop_speaking_item,
            rumps.separator,
            self.talk_to_agent_item,
            self.focus_agent_item,
            self.listen_anywhere_item,
            rumps.separator,
            self.auto_listen_item,
            self.read_summary_item,
            rumps.separator,
            rumps.MenuItem("⚙️ Open Config File", callback=self.open_config_file),
            self.tier_item,
            rumps.separator,
        ]

        # Start background hotkey listeners
        self._start_hotkey_listeners()

    def handle_state_change(self, state: str):
        """Update menu bar icon based on current voice layer state."""
        if state == "speaking":
            self.title = "🔊"
        elif state == "listening":
            self.title = "🔴"
        elif state == "transcribing":
            self.title = "⏳"
        else:
            self.title = "🎙️"

    def stop_speaking_now(self, _=None):
        """Instantly stop speech synthesis."""
        stop_all_speech()
        if self.watcher:
            self.watcher.interrupt()
        self.title = "🎙️"

    def trigger_focus_antigravity(self, _=None):
        """Switch frontmost window to Antigravity and focus input."""
        focus_antigravity(focus_input=True)

    def trigger_talk_to_antigravity(self, _=None):
        """Focus Antigravity and start listening for a prompt to send."""
        def _worker():
            focus_antigravity(focus_input=True)
            time.sleep(0.3)
            self.title = "🔴"
            if self.config.audio_cues.enabled:
                play_chime("start", block=False)

            recorder = AudioRecorder(
                sample_rate=self.config.vad.sample_rate,
                energy_threshold=self.config.vad.energy_threshold,
                silence_duration=self.config.vad.silence_duration,
            )

            audio_data, temp_wav = recorder.record_speech_auto()
            self.title = "⏳"

            try:
                stt = get_stt_engine(self.config)
                text = stt.transcribe(temp_wav)
                if text:
                    if self.config.audio_cues.enabled:
                        play_chime("done", block=False)
                    inject_text_to_active_app(text, submit_enter=True, target_antigravity=True)
            finally:
                temp_wav.unlink(missing_ok=True)
                self.title = "🎙️"

        threading.Thread(target=_worker, daemon=True).start()

    def _start_hotkey_listeners(self):
        """Register global hotkeys for fast access and Escape interrupt."""
        def _listener():
            try:
                from pynput import keyboard

                def on_press(key):
                    # Escape key stops speaking
                    if key == keyboard.Key.esc:
                        stop_all_speech()
                    # Single backtick ( ` ) key triggers talk to Antigravity
                    elif hasattr(key, "char") and key.char == "`":
                        if self.config.global_hotkey.enabled:
                            self.trigger_talk_to_antigravity()

                # GlobalHotKey for combo shortcuts
                hotkey_map = {}
                if self.config.global_hotkey.enabled and self.config.global_hotkey.dictate_hotkey:
                    hotkey_map[self.config.global_hotkey.dictate_hotkey] = lambda: self.trigger_manual_listen()

                if hotkey_map:
                    try:
                        gh = keyboard.GlobalHotKeys(hotkey_map)
                        gh.start()
                    except Exception:
                        pass

                with keyboard.Listener(on_press=on_press) as listener:
                    listener.join()
            except Exception:
                pass

        threading.Thread(target=_listener, daemon=True).start()

    def toggle_auto_listen(self, sender):
        self.config.antigravity.auto_listen = not self.config.antigravity.auto_listen
        sender.state = 1 if self.config.antigravity.auto_listen else 0
        save_config(self.config)

    def toggle_read_summary(self, sender):
        self.config.antigravity.read_summary_aloud = not self.config.antigravity.read_summary_aloud
        sender.state = 1 if self.config.antigravity.read_summary_aloud else 0
        save_config(self.config)

    def open_config_file(self, _):
        path = get_default_config_path()
        if not path.is_file():
            save_config(self.config)
        subprocess.run(["open", str(path)])

    def trigger_manual_listen(self, _=None):
        def _worker():
            time.sleep(0.4)
            self.title = "🔴"
            if self.config.audio_cues.enabled:
                play_chime("start", block=False)

            recorder = AudioRecorder(
                sample_rate=self.config.vad.sample_rate,
                energy_threshold=self.config.vad.energy_threshold,
                silence_duration=self.config.vad.silence_duration,
            )

            audio_data, temp_wav = recorder.record_speech_auto()
            self.title = "⏳"

            try:
                stt = get_stt_engine(self.config)
                text = stt.transcribe(temp_wav)
                if text:
                    if self.config.audio_cues.enabled:
                        play_chime("done", block=False)
                    inject_text_to_active_app(text, submit_enter=False)
            finally:
                temp_wav.unlink(missing_ok=True)
                self.title = "🎙️"

        threading.Thread(target=_worker, daemon=True).start()


def run_tray():
    """Launch the macOS Tray application."""
    app = Talk2MeTrayApp()
    app.run()
