"""
Pal Teach Mode Event Observer & Demonstration Synthesizer for VoiceFi.
Unified, passive, thread-safe macOS event capture with in-process AXUIElement resolution.
Captures user desktop demonstrations into clean, declarative PalWorkflow recipes.
"""

import math
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCopyElementAtPosition,
    AXUIElementCreateApplication,
    AXUIElementCreateSystemWide,
)
import Quartz

from voicefi.integrations.pal_workflow import (
    ActionType,
    ClickTarget,
    PalWorkflowRecipe,
    PalWorkflowRegistry,
    WorkflowStep,
)

# Standard Carbon virtual keycodes for macOS hotkey normalization
VK_MAP = {
    36: "Return",
    48: "Tab",
    49: "Space",
    51: "Backspace",
    53: "Escape",
    123: "Left",
    124: "Right",
    125: "Down",
    126: "Up",
    0: "A",
    1: "S",
    2: "D",
    3: "F",
    4: "H",
    5: "G",
    6: "Z",
    7: "X",
    8: "C",
    9: "V",
    11: "B",
    12: "Q",
    13: "W",
    14: "E",
    15: "R",
    16: "Y",
    17: "T",
    31: "O",
    32: "U",
    34: "I",
    35: "P",
    37: "L",
    38: "J",
    40: "K",
    45: "N",
    46: "M",
    43: ",",
    47: ".",
    44: "/",
    24: "=",
    27: "-",
}


@dataclass
class PalTeachRawStep:
    step_number: int
    action: str  # "click", "double_click", "type_text", "hotkey", "press_key", "drag", "switch_app"
    app_name: str
    window_title: Optional[str]
    params: Dict[str, Any]
    spoken_summary: str
    voice_note: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class PalTeachRecorder:
    """
    Passive macOS event observer that captures and denoises user demonstrations
    into clean discrete steps for Pal and VoiceFi ReAct loops.
    """

    def __init__(self, on_step: Optional[Callable[[PalTeachRawStep], None]] = None):
        self.on_step = on_step
        self.steps: List[PalTeachRawStep] = []
        self._running = False
        self._tap = None
        self._loop = None
        self._loop_source = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Denoising & State Machine
        self._current_app = ""
        self._current_window: Optional[str] = None
        self._pending_text: List[str] = []
        self._mouse_down_pos: Optional[Tuple[float, float]] = None
        self._flush_timer: Optional[threading.Timer] = None
        self._last_voice_note: Optional[str] = None

    def start(self) -> None:
        """Start passive background event tap."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_tap, daemon=True, name="PalTeachRecorder"
        )
        self._thread.start()

    def stop(self) -> List[PalTeachRawStep]:
        """Stop observer and return consolidated steps."""
        self._running = False
        with self._lock:
            self._flush_text_buffer()
        if self._tap is not None:
            try:
                Quartz.CGEventTapEnable(self._tap, False)
                Quartz.CFMachPortInvalidate(self._tap)
            except Exception:
                pass
        if self._loop is not None:
            try:
                Quartz.CFRunLoopStop(self._loop)
            except Exception:
                pass
        return list(self.steps)

    def attach_voice_note(self, note: str) -> None:
        """Attach active speech note from Whisper stream to next or most recent step."""
        with self._lock:
            self._last_voice_note = note
            if self.steps:
                self.steps[-1].voice_note = note

    def _emit_step(self, action: str, params: Dict[str, Any], spoken: str) -> None:
        step = PalTeachRawStep(
            step_number=len(self.steps) + 1,
            action=action,
            app_name=self._current_app,
            window_title=self._current_window,
            params=params,
            spoken_summary=spoken,
            voice_note=self._last_voice_note,
        )
        self._last_voice_note = None
        self.steps.append(step)
        if self.on_step:
            try:
                self.on_step(step)
            except Exception as e:
                print(f"[PalTeachRecorder] on_step error: {e}")

    def _refresh_active_context(self) -> None:
        """Query frontmost app and window title via AppKit + AXUIElement (<0.1ms)."""
        ws = NSWorkspace.sharedWorkspace()
        front = ws.frontmostApplication()
        if not front:
            return
        app_name = front.localizedName() or ""
        pid = front.processIdentifier()
        window_title = None

        try:
            app_ax = AXUIElementCreateApplication(pid)
            err, win = AXUIElementCopyAttributeValue(app_ax, "AXFocusedWindow", None)
            if err == 0 and win:
                err, title = AXUIElementCopyAttributeValue(win, "AXTitle", None)
                if err == 0 and title:
                    window_title = str(title)
        except Exception:
            pass

        if app_name != self._current_app:
            self._flush_text_buffer()
            self._current_app = app_name
            self._current_window = window_title
            self._emit_step(
                action="switch_app",
                params={"app_name": app_name, "bundle_id": front.bundleIdentifier() or ""},
                spoken=f"Switched to {app_name}",
            )
        else:
            self._current_window = window_title

    def _flush_text_buffer(self) -> None:
        if not self._pending_text:
            return
        text = "".join(self._pending_text)
        self._pending_text.clear()
        if text.strip() or "\n" in text:
            self._emit_step(
                action="type_text",
                params={"text": text},
                spoken=f"Typed '{text.strip()}'",
            )

    def _schedule_flush(self) -> None:
        if self._flush_timer:
            self._flush_timer.cancel()
        self._flush_timer = threading.Timer(0.8, self._flush_text_buffer)
        self._flush_timer.start()

    def _inspect_element_at(self, x: float, y: float) -> Dict[str, Any]:
        """Resolve UI role and title at coordinates using system-wide AXUIElement."""
        try:
            sys_elem = AXUIElementCreateSystemWide()
            err, elem = AXUIElementCopyElementAtPosition(sys_elem, x, y, None)
            if err == 0 and elem:
                _, role = AXUIElementCopyAttributeValue(elem, "AXRole", None)
                _, title = AXUIElementCopyAttributeValue(elem, "AXTitle", None)
                return {"role": str(role or ""), "title": str(title or "")}
        except Exception:
            pass
        return {}

    def _event_callback(self, proxy, event_type, event, refcon):
        with self._lock:
            self._refresh_active_context()

            # 1. Keyboard Events
            if event_type == Quartz.kCGEventKeyDown:
                flags = Quartz.CGEventGetFlags(event)
                keycode = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode
                )
                is_cmd = bool(flags & Quartz.kCGEventFlagMaskCommand)
                is_ctrl = bool(flags & Quartz.kCGEventFlagMaskControl)
                is_alt = bool(flags & Quartz.kCGEventFlagMaskAlternate)
                is_shift = bool(flags & Quartz.kCGEventFlagMaskShift)

                # Hotkey check (Cmd or Ctrl present)
                if is_cmd or is_ctrl:
                    self._flush_text_buffer()
                    key_name = VK_MAP.get(keycode, f"Key_{keycode}")
                    mods = []
                    if is_cmd:
                        mods.append("Cmd")
                    if is_ctrl:
                        mods.append("Ctrl")
                    if is_alt:
                        mods.append("Option")
                    if is_shift:
                        mods.append("Shift")
                    combo = "+".join(mods + [key_name])
                    self._emit_step(
                        action="hotkey",
                        params={"combo": combo, "keycode": keycode, "key": key_name, "modifiers": mods},
                        spoken=f"Pressed {combo}",
                    )
                    return event

                # Navigation keys
                if keycode in (36, 48, 53):  # Return, Tab, Escape
                    self._flush_text_buffer()
                    key_name = VK_MAP.get(keycode, "Key")
                    self._emit_step(
                        action="press_key",
                        params={"key": key_name, "keycode": keycode},
                        spoken=f"Pressed {key_name}",
                    )
                    return event

                if keycode == 51:  # Backspace
                    if self._pending_text:
                        self._pending_text.pop()
                    self._schedule_flush()
                    return event

                # Safe Unicode extraction (no Carbon TIS asserts on macOS 15)
                _, chars = Quartz.CGEventKeyboardGetUnicodeString(event, 4, None, None)
                if chars:
                    self._pending_text.append(chars)
                    self._schedule_flush()

            # 2. Mouse Events
            elif event_type == Quartz.kCGEventLeftMouseDown:
                self._flush_text_buffer()
                loc = Quartz.CGEventGetLocation(event)
                self._mouse_down_pos = (loc.x, loc.y)

            elif event_type == Quartz.kCGEventLeftMouseUp:
                loc = Quartz.CGEventGetLocation(event)
                click_state = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGMouseEventClickState
                )
                if self._mouse_down_pos:
                    dx = loc.x - self._mouse_down_pos[0]
                    dy = loc.y - self._mouse_down_pos[1]
                    dist = math.hypot(dx, dy)
                    if dist < 5:
                        elem_info = self._inspect_element_at(loc.x, loc.y)
                        action_type = "double_click" if click_state == 2 else "click"
                        label = elem_info.get("title") or elem_info.get("role") or "screen"
                        self._emit_step(
                            action=action_type,
                            params={
                                "x": round(loc.x),
                                "y": round(loc.y),
                                "click_count": click_state,
                                "element": elem_info,
                            },
                            spoken=f"{action_type.replace('_', ' ').capitalize()}ed {label}",
                        )
                    else:
                        self._emit_step(
                            action="drag",
                            params={
                                "start_x": round(self._mouse_down_pos[0]),
                                "start_y": round(self._mouse_down_pos[1]),
                                "end_x": round(loc.x),
                                "end_y": round(loc.y),
                            },
                            spoken="Dragged and dropped",
                        )
                self._mouse_down_pos = None

        return event

    def _run_tap(self) -> None:
        mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventLeftMouseUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventRightMouseDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventScrollWheel)
        )
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._event_callback,
            None,
        )
        if not self._tap:
            print("[PalTeachRecorder] Failed to create Quartz Event Tap. Check Accessibility permissions.")
            return

        self._loop_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, self._loop_source, Quartz.kCFRunLoopDefaultMode)
        Quartz.CGEventTapEnable(self._tap, True)

        while self._running:
            res = Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.5, False)
            if res not in (Quartz.kCFRunLoopRunTimedOut, Quartz.kCFRunLoopRunHandledSource):
                break


class PalTrainer:
    """
    Session orchestrator for Demonstration-Based Learning ('Hey Pal, watch me do this').
    Synthesizes recorded OS event streams into clean, declarative YAML workflows.
    """

    def __init__(self, workflow_name: str, on_step: Optional[Callable[[PalTeachRawStep], None]] = None):
        self.workflow_name = workflow_name.strip()
        self.workflow_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", self.workflow_name.lower()).strip("_")
        self.recorder = PalTeachRecorder(on_step=on_step)
        self.start_time: float = 0.0

    def start(self) -> None:
        """Start the training session."""
        self.start_time = time.time()
        self.recorder.start()

    def record_voice_note(self, text: str) -> None:
        """Attach spoken commentary to the active demonstration."""
        self.recorder.attach_voice_note(text)

    def cancel(self) -> None:
        """Abort without saving."""
        self.recorder.stop()

    def finish(self, save_dir: Optional[Path] = None) -> PalWorkflowRecipe:
        """
        Stop recording, denoise the action stream, compile to a PalWorkflowRecipe,
        save to ~/.voicefi/workflows/<slug>.yaml, and hot-reload into the registry.
        """
        raw_steps = self.recorder.stop()
        compiled_steps: List[WorkflowStep] = []

        for s in raw_steps:
            action = s.action
            step_name = s.spoken_summary
            desc = s.voice_note

            if action == "switch_app":
                compiled_steps.append(
                    WorkflowStep(
                        name=f"Focus {s.params.get('app_name')}",
                        action=ActionType.ACTIVATE_APP,
                        app_name=s.params.get("app_name"),
                        bundle_id=s.params.get("bundle_id"),
                        description=desc,
                    )
                )
            elif action == "hotkey":
                compiled_steps.append(
                    WorkflowStep(
                        name=f"Press {s.params.get('combo')}",
                        action=ActionType.HOTKEY,
                        combo=s.params.get("combo"),
                        key=s.params.get("key"),
                        modifiers=s.params.get("modifiers"),
                        description=desc,
                    )
                )
            elif action == "press_key":
                compiled_steps.append(
                    WorkflowStep(
                        name=f"Press {s.params.get('key')}",
                        action=ActionType.PRESS_KEY,
                        key=s.params.get("key"),
                        description=desc,
                    )
                )
            elif action == "type_text":
                text = s.params.get("text", "")
                compiled_steps.append(
                    WorkflowStep(
                        name=f"Type '{text[:20]}...'" if len(text) > 20 else f"Type '{text}'",
                        action=ActionType.KEYSTROKE,
                        text=text,
                        description=desc,
                    )
                )
            elif action in ("click", "double_click"):
                elem = s.params.get("element", {})
                role = elem.get("role")
                title = elem.get("title")
                target = ClickTarget(
                    target_type="coordinates",
                    x=s.params.get("x"),
                    y=s.params.get("y"),
                    role=role,
                    title=title,
                )
                act_type = ActionType.DOUBLE_CLICK if action == "double_click" else ActionType.CLICK
                compiled_steps.append(
                    WorkflowStep(
                        name=f"Click {title or role or 'screen'}",
                        action=act_type,
                        click_target=target,
                        description=desc,
                    )
                )

        # Build recipe
        triggers = [
            self.workflow_name.lower(),
            f"run {self.workflow_name.lower()}",
            f"do {self.workflow_name.lower()}",
            f"start {self.workflow_name.lower()}",
        ]
        # Remove duplicates while preserving order
        unique_triggers = list(dict.fromkeys(triggers))

        recipe = PalWorkflowRecipe(
            id=self.workflow_slug,
            name=self.workflow_name,
            description=f"Demonstrated workflow for '{self.workflow_name}' ({len(compiled_steps)} steps)",
            triggers=unique_triggers,
            steps=compiled_steps,
            success_summary=f"Completed {self.workflow_name} successfully",
            error_summary=f"Failed during {self.workflow_name} at {{step_name}}",
        )

        # Save to disk
        target_dir = save_dir or (Path.home() / ".voicefi" / "workflows")
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{self.workflow_slug}.yaml"

        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(recipe.model_dump(), f, sort_keys=False)

        # Hot-reload in memory
        PalWorkflowRegistry.register_recipe(recipe)

        return recipe
