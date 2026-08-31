"""
Native Antigravity Input & Mic Observer.
Monitors native Antigravity in-chat dictation (Ctrl+M / native mic button) and mirrors
transcription tokens live into the VoiceFi Dynamic Island HUD (pure minimalist Apple design, no emoji).
"""

import subprocess
import threading
import time
from typing import Optional, Callable
from voicefi.config import VoiceFiConfig, load_config
from voicefi.tts.base import set_cross_process_hud_state, clear_cross_process_hud_state


class NativeAntigravityInputObserver:
    """
    Monitors Antigravity's active chat prompt element to mirror native speech-to-text
    into the VoiceFi Dynamic Island HUD in real-time.
    """

    def __init__(
        self,
        config: Optional[VoiceFiConfig] = None,
        on_dictation_update: Optional[Callable[[str], None]] = None,
    ):
        self.config = config or load_config()
        self.on_dictation_update = on_dictation_update
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_observed_text = ""
        self._is_active_dictation = False

    def start(self):
        """Start the background observer thread."""
        if self._running:
            return
        if not getattr(self.config.antigravity, "mirror_native_mic", False):
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._observe_loop, daemon=True, name="AntigravityInputObserver"
        )
        self._thread.start()

    def stop(self):
        """Stop the background observer."""
        self._running = False
        if self._is_active_dictation:
            self._is_active_dictation = False
            clear_cross_process_hud_state()

    def _query_focused_input_text(self) -> Optional[str]:
        """
        Query the current text value of the focused input element in Antigravity via AppleScript Accessibility.
        Returns None if Antigravity is not frontmost or not focused.
        """
        applescript = """
        tell application "System Events"
            set frontApps to name of every application process whose frontmost is true
            if (count of frontApps) is 0 then return ""
            set fName to item 1 of frontApps
            if (fName contains "Antigravity") then
                try
                    set focusedElem to value of attribute "AXFocusedUIElement" of application process fName
                    if focusedElem is not missing value then
                        set elemVal to value of focusedElem
                        if elemVal is not missing value then
                            return (elemVal as text)
                        end if
                    end if
                end try
            end if
            return ""
        end tell
        """
        try:
            res = subprocess.run(
                ["osascript", "-e", applescript],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.5,
            )
            return res.stdout.strip()
        except Exception:
            return None

    def _observe_loop(self):
        """Background polling loop for active dictation detection."""
        idle_sleep = 0.5
        active_sleep = 0.15
        last_change_time = 0.0

        while self._running:
            try:
                text = self._query_focused_input_text()
                now = time.time()

                if text is not None and text != "":
                    if text != self._last_observed_text:
                        diff_len = abs(len(text) - len(self._last_observed_text))
                        self._last_observed_text = text
                        last_change_time = now

                        # Incremental streaming text growth indicates voice dictation (Ctrl+M)
                        # Exclude single character edits and large clipboard pastes (>100 chars at once)
                        is_streaming_growth = (2 <= diff_len <= 80) or self._is_active_dictation
                        if is_streaming_growth:
                            self._is_active_dictation = True
                            user_name = getattr(self.config, "user_name", "Jake")
                            set_cross_process_hud_state(
                                "listening",
                                text=text,
                                user_name=user_name,
                                live_stream=True,
                            )
                            if self.on_dictation_update:
                                self.on_dictation_update(text)
                            try:
                                from voicefi.ui.unified_hud import UnifiedDynamicIslandHUD

                                hud = UnifiedDynamicIslandHUD.get_instance()
                                hud.set_listening(
                                    prompt_preview=text,
                                    user_name=user_name,
                                    live_stream=True,
                                    source="Antigravity (⌃M)",
                                )
                            except Exception:
                                pass
                    elif self._is_active_dictation and (now - last_change_time > 2.0):
                        # Dictation paused/finished: clean up HUD state
                        self._is_active_dictation = False
                        clear_cross_process_hud_state()
                else:
                    if self._is_active_dictation:
                        self._is_active_dictation = False
                        clear_cross_process_hud_state()
                    self._last_observed_text = ""

                time.sleep(active_sleep if self._is_active_dictation else idle_sleep)
            except Exception:
                time.sleep(idle_sleep)
