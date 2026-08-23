"""
Native macOS Pure Apple-Style Unified Dynamic Island HUD.
Provides a clean, borderless, frosted-glass capsule HUD anchored directly beneath
the top-center screen / camera notch, smoothly morphing across 5 agent lifecycle states:
- IDLE: Compact pill ("🎙️ VoiceFi • Ready")
- THINKING: Reasoning indicator ("🧠 Antigravity • Thinking...")
- WORKING: Tool action pill ("⚡ Antigravity • Running pytest...")
- SPEAKING: Live speech subtitles ("🔊 Christopher: '...'")
- LISTENING: Microphone VAD indicator ("🎙️ Listening to Jake...")
"""

import math
import threading
import time
from typing import Optional

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSPanel,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSBackingStoreBuffered,
    NSRect,
    NSPoint,
    NSSize,
    NSTextField,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSScreen,
    NSView,
    NSVisualEffectView,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectBlendingModeBehindWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSAnimationContext,
)
from PyObjCTools import AppHelper

from voicefi.config import load_config


class UnifiedDynamicIslandHUD:
    """
    Singleton Native Apple-Style Unified Dynamic Island HUD for macOS.
    Thread-safe and main-runloop safe.
    """

    _instance: Optional["UnifiedDynamicIslandHUD"] = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "UnifiedDynamicIslandHUD":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self.config = load_config()
        self._current_state = "idle"
        self._panel: Optional[NSPanel] = None
        self._root_view: Optional[NSView] = None
        self._effect_view: Optional[NSVisualEffectView] = None
        self._label: Optional[NSTextField] = None
        self._subtitle_label: Optional[NSTextField] = None
        self._hide_timer: Optional[threading.Timer] = None
        self._is_visible = False

        self._init_native_window()

    def _init_native_window(self):
        """Build the borderless NSPanel with native Apple HUD blur."""
        try:
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )
        except Exception:
            pass

        w, h = 180, 36
        rect = NSRect(NSPoint(500, 800), NSSize(w, h))
        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel

        self._panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        self._panel.setOpaque_(False)
        self._panel.setBackgroundColor_(NSColor.clearColor())
        self._panel.setLevel_(NSFloatingWindowLevel + 20)
        self._panel.setFloatingPanel_(True)
        self._panel.setHidesOnDeactivate_(False)
        self._panel.setCanHide_(False)
        self._panel.setWorksWhenModal_(True)
        self._panel.setBecomesKeyOnlyIfNeeded_(True)
        self._panel.setReleasedWhenClosed_(False)
        self._panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        # Root view container
        self._root_view = NSView.alloc().initWithFrame_(NSRect(NSPoint(0, 0), NSSize(w, h)))
        self._root_view.setWantsLayer_(True)
        self._root_view.layer().setCornerRadius_(h / 2.0)
        self._root_view.layer().setMasksToBounds_(True)

        # Apple standard HUD frosted blur
        self._effect_view = NSVisualEffectView.alloc().initWithFrame_(
            NSRect(NSPoint(0, 0), NSSize(w, h))
        )
        self._effect_view.setMaterial_(NSVisualEffectMaterialHUDWindow)
        self._effect_view.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        self._effect_view.setState_(1)
        self._effect_view.setWantsLayer_(True)
        self._effect_view.layer().setCornerRadius_(h / 2.0)
        self._root_view.addSubview_(self._effect_view)

        # Main text label
        self._label = NSTextField.alloc().initWithFrame_(
            NSRect(NSPoint(14, 4), NSSize(w - 28, h - 8))
        )
        self._label.setStringValue_("🎙️ VoiceFi • Ready")
        self._label.setFont_(NSFont.systemFontOfSize_(13))
        self._label.setTextColor_(NSColor.whiteColor())
        self._label.setBezeled_(False)
        self._label.setDrawsBackground_(False)
        self._label.setEditable_(False)
        self._label.setSelectable_(False)
        self._root_view.addSubview_(self._label)

        self._panel.setContentView_(self._root_view)

    def _get_target_frame(self, width: float, height: float) -> NSRect:
        """Calculate screen positioning anchored top-center below the camera notch."""
        screen = NSScreen.mainScreen()
        if screen:
            visible = screen.visibleFrame()
            x = visible.origin.x + (visible.size.width - width) / 2.0
            y = visible.origin.y + visible.size.height - height - 8.0
        else:
            x, y = 500, 800
        return NSRect(NSPoint(x, y), NSSize(width, height))

    def _apply_state(
        self,
        state: str,
        text: str,
        width: float,
        height: float,
        font_size: float = 13.0,
        linger: Optional[float] = None,
    ):
        """Update window geometry, text, and presentation on main thread."""
        with self._lock:
            self._current_state = state
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

        def _update():
            if not self._panel or not self._root_view or not self._effect_view or not self._label:
                return

            target_rect = self._get_target_frame(width, height)

            # Animate frame resizing with smooth Apple spring curve
            try:
                NSAnimationContext.beginGrouping()
                NSAnimationContext.currentContext().setDuration_(0.22)
                self._panel.animator().setFrame_display_(target_rect, True)
                NSAnimationContext.endGrouping()
            except Exception:
                self._panel.setFrame_display_(target_rect, True)

            self._root_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            self._root_view.layer().setCornerRadius_(height / 2.0 if height <= 48 else 20.0)
            self._effect_view.setFrame_(NSRect(NSPoint(0, 0), NSSize(width, height)))
            self._effect_view.layer().setCornerRadius_(height / 2.0 if height <= 48 else 20.0)

            self._label.setFrame_(NSRect(NSPoint(14, 4), NSSize(width - 28, height - 8)))
            self._label.setFont_(NSFont.systemFontOfSize_(font_size))
            self._label.setStringValue_(text)

            self._panel.orderFrontRegardless()
            self._is_visible = True

            if linger and linger > 0:
                with self._lock:
                    self._hide_timer = threading.Timer(linger, self.hide)
                    self._hide_timer.daemon = True
                    self._hide_timer.start()

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    # -------------------------------------------------------------------------
    # 5 Lifecycle State Handlers
    # -------------------------------------------------------------------------

    def set_idle(self, linger: Optional[float] = None):
        """Set to Idle State (Compact Pill)."""
        self._apply_state(
            state="idle",
            text="🎙️ VoiceFi • Ready",
            width=180,
            height=36,
            font_size=13,
            linger=linger,
        )

    def set_thinking(self, agent_name: str = "Antigravity", detail: str = "Thinking..."):
        """Set to Thinking State."""
        display = f"🧠 {agent_name.capitalize()} • {detail}"
        width = max(260, min(420, len(display) * 8 + 40))
        self._apply_state(
            state="thinking",
            text=display,
            width=width,
            height=36,
            font_size=13,
        )

    def set_working(self, agent_name: str = "Antigravity", tool_action: str = "Running tool..."):
        """Set to Working / Tool Execution State."""
        display = f"⚡ {agent_name.capitalize()} • {tool_action}"
        width = max(280, min(450, len(display) * 8 + 40))
        self._apply_state(
            state="working",
            text=display,
            width=width,
            height=36,
            font_size=13,
        )

    def set_speaking(
        self,
        text: str,
        agent_name: str = "Antigravity",
        persona_name: Optional[str] = None,
        linger: Optional[float] = 2.5,
    ):
        """Set to Speaking State with live speech subtitle text."""
        clean = text.strip()
        speaker = persona_name if persona_name else agent_name.capitalize()
        # Measure height based on text length
        lines = max(1, min(4, math.ceil(len(clean) / 48.0)))
        height = 42 + (lines * 18) if lines > 1 else 38
        width = 460 if lines > 1 else max(280, min(460, len(clean) * 8 + 60))

        if lines > 1:
            display_text = f"🔊 {speaker}:\n\"{clean}\""
        else:
            display_text = f"🔊 {speaker}: \"{clean}\""

        self._apply_state(
            state="speaking",
            text=display_text,
            width=width,
            height=height,
            font_size=12.5,
            linger=linger,
        )

    def set_listening(self, prompt_preview: str = "", user_name: str = "Jake"):
        """Set to Listening State (Mic Active with VAD)."""
        if prompt_preview:
            display = f"🎙️ Listening: \"{prompt_preview}\""
        else:
            display = f"🎙️ Listening to {user_name}..."
        width = max(260, min(420, len(display) * 8 + 40))
        self._apply_state(
            state="listening",
            text=display,
            width=width,
            height=36,
            font_size=13,
        )

    def update_live_text(self, text: str):
        """Update the subtitle or transcription text dynamically."""
        def _update():
            if self._label and self._panel and self._panel.isVisible():
                self._label.setStringValue_(text)

        if threading.current_thread() is threading.main_thread():
            _update()
        else:
            AppHelper.callAfter(_update)

    def finish_speech(self, linger_seconds: float = 2.0):
        """Conclude speech turn and auto-hide or return to idle."""
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
            self._hide_timer = threading.Timer(linger_seconds, self.hide)
            self._hide_timer.daemon = True
            self._hide_timer.start()

    def hide(self):
        """Hide the HUD panel."""
        def _do_hide():
            if self._panel and self._panel.isVisible():
                self._panel.orderOut_(None)
                self._is_visible = False

        if threading.current_thread() is threading.main_thread():
            _do_hide()
        else:
            AppHelper.callAfter(_do_hide)

    # -------------------------------------------------------------------------
    # Backward Compatibility Delegates (AgentSpeechHUD & DictationHUD)
    # -------------------------------------------------------------------------

    def show_speech(
        self,
        text: str,
        agent_name: str = "Antigravity",
        role: Optional[str] = None,
        persona_name: Optional[str] = None,
        is_speaking: bool = True,
        position: str = "top_center",
    ):
        """Compatibility bridge for AgentSpeechHUD.show_speech."""
        self.set_speaking(
            text=text,
            agent_name=agent_name,
            persona_name=persona_name,
            linger=None,
        )

    def show_listening(self):
        """Compatibility bridge for DictationHUD.show_listening."""
        self.set_listening(user_name=getattr(self.config, "user_name", "Jake"))

    def show_paused(self, message: str = "⏸️ Agent Speaking (Paused)..."):
        """Compatibility bridge for DictationHUD.show_paused."""
        self._apply_state(
            state="paused",
            text=message,
            width=300,
            height=36,
            font_size=13,
        )

    def show_transcribing(self):
        """Compatibility bridge for DictationHUD.show_transcribing."""
        self._apply_state(
            state="transcribing",
            text="⏳ Transcribing voice...",
            width=240,
            height=36,
            font_size=13,
        )

    def show_done(self, preview_text: str = ""):
        """Compatibility bridge for DictationHUD.show_done."""
        disp = f"✅ {preview_text[:25]}..." if preview_text else "✅ Done"
        self._apply_state(
            state="done",
            text=disp,
            width=240,
            height=36,
            font_size=13,
            linger=1.2,
        )
