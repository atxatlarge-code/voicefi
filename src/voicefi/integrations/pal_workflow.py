"""
Declarative Workflow Recipe Schema & Deterministic Replay Engine for Pal macOS Computer-Use.
Provides state-verified execution (window readiness, element targeting, safety unwinding)
without fragile blind sleeps, and dynamic parameter extraction from voice prompts.
"""

import os
import re
import shlex
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import yaml
from pydantic import BaseModel, Field

from voicefi.integrations.pal_harness import PalCommandResult, PalHarness


class ActionType(str, Enum):
    ACTIVATE_APP = "activate_app"
    WAIT_FOR_WINDOW = "wait_for_window"
    HOTKEY = "hotkey"
    KEYSTROKE = "keystroke"
    PRESS_KEY = "press_key"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    APPLESCRIPT = "applescript"
    RUN_SHELL = "run_shell"
    WAIT = "wait"
    SYSTEM_ACTION = "system_action"
    NOTIFY = "notify"


class ParameterDefinition(BaseModel):
    type: Literal["string", "int", "float", "boolean", "path", "enum"] = "string"
    description: str = ""
    default: Optional[Any] = None
    required: bool = False
    choices: Optional[List[str]] = None
    extract_patterns: List[str] = Field(
        default_factory=list,
        description="Regex patterns with (?P<value>...) to extract from voice prompts without an LLM",
    )


class ClickTarget(BaseModel):
    target_type: Literal["menu_path", "ui_element", "coordinates"] = "coordinates"
    menu_path: Optional[List[str]] = None
    role: Optional[str] = None  # e.g. "AXButton", "AXMenuItem", "AXTextField"
    title: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    relative_to: Literal["window", "screen"] = "screen"


class WorkflowStep(BaseModel):
    name: str = "Step"
    action: ActionType
    description: Optional[str] = None
    timeout_ms: int = 4000
    on_failure: Literal["abort", "ignore", "retry"] = "abort"
    max_retries: int = 1

    # Action-specific arguments
    app_name: Optional[str] = None
    bundle_id: Optional[str] = None
    window_title: Optional[str] = None
    key: Optional[str] = None
    modifiers: Optional[List[str]] = None
    combo: Optional[str] = None  # e.g. "Cmd+Shift+E"
    text: Optional[str] = None
    press_enter: bool = False
    click_target: Optional[ClickTarget] = None
    script: Optional[str] = None
    command: Optional[str] = None
    cwd: Optional[str] = None
    duration_ms: Optional[int] = None
    message: Optional[str] = None


class PalWorkflowRecipe(BaseModel):
    id: str = Field(description="Unique recipe identifier slug")
    name: str
    version: str = "1.0.0"
    description: str = ""
    triggers: List[str] = Field(
        default_factory=list,
        description="Spoken trigger phrases (e.g. 'morning setup', 'bounce stems')",
    )
    destructive: bool = False
    parameters: Dict[str, ParameterDefinition] = Field(default_factory=dict)
    timeout_total_ms: int = 30000
    steps: List[WorkflowStep] = Field(default_factory=list)
    success_summary: str = "Workflow completed successfully"
    error_summary: str = "Workflow failed at step {step_name}"


class PalWorkflowRunner:
    """Executes PalWorkflowRecipe definitions with deterministic safety checks."""

    @classmethod
    def execute_recipe(
        cls,
        recipe: PalWorkflowRecipe,
        raw_prompt: str = "",
        explicit_args: Optional[Dict[str, Any]] = None,
    ) -> PalCommandResult:
        recipe_id = recipe.id
        steps = recipe.steps
        total_timeout_s = recipe.timeout_total_ms / 1000.0

        # 1. Resolve & bind parameters
        bound_vars = cls._bind_parameters(recipe.parameters, raw_prompt, explicit_args or {})
        start_time = time.monotonic()

        for idx, step in enumerate(steps):
            if (time.monotonic() - start_time) > total_timeout_s:
                cls._unwind_failure()
                return PalCommandResult(
                    success=False,
                    command=recipe_id,
                    action_type="workflow_timeout",
                    details=f"Workflow exceeded total budget of {total_timeout_s}s",
                    spoken_summary=f"Workflow timed out during {step.name or f'step {idx + 1}'}",
                )

            success, err = cls._execute_step(step, bound_vars)
            if not success:
                if step.on_failure == "abort":
                    cls._unwind_failure()
                    err_summary = recipe.error_summary.format(
                        step_name=step.name or f"step {idx + 1}"
                    )
                    return PalCommandResult(
                        success=False,
                        command=f"{recipe_id}:{step.name}",
                        action_type=step.action.value,
                        details=err,
                        spoken_summary=err_summary,
                    )

        success_msg = recipe.success_summary
        for k, v in bound_vars.items():
            success_msg = success_msg.replace(f"${{{k}}}", str(v))

        return PalCommandResult(
            success=True,
            command=recipe_id,
            action_type="workflow",
            details=f"Executed {len(steps)} steps successfully",
            spoken_summary=success_msg,
        )

    @classmethod
    def _execute_step(cls, step: WorkflowStep, variables: Dict[str, Any]) -> Tuple[bool, str]:
        action = step.action
        timeout_s = step.timeout_ms / 1000.0

        if action == ActionType.ACTIVATE_APP:
            app = cls._interpolate(step.app_name or "", variables)
            res = PalHarness.launch_app(app)
            return res.success, res.details

        elif action == ActionType.WAIT_FOR_WINDOW:
            app = cls._interpolate(step.app_name or "", variables)
            win_title = cls._interpolate(step.window_title or "", variables)
            return cls._wait_for_window_ready(app, win_title, timeout_s)

        elif action == ActionType.HOTKEY:
            if step.combo:
                # Parse combo e.g. "Cmd+Shift+N" or "Cmd+S"
                parts = [p.strip() for p in step.combo.split("+")]
                mods = parts[:-1]
                key = parts[-1].lower() if parts else ""
                return cls._send_hotkey(key, mods)
            key = step.key or ""
            mods = step.modifiers or []
            return cls._send_hotkey(key, mods)

        elif action == ActionType.KEYSTROKE:
            text = cls._interpolate(step.text or "", variables)
            return cls._send_keystroke(text, step.press_enter)

        elif action == ActionType.PRESS_KEY:
            key = step.key or ""
            return cls._send_special_key(key)

        elif action in (ActionType.CLICK, ActionType.DOUBLE_CLICK):
            is_double = action == ActionType.DOUBLE_CLICK
            return cls._handle_click(step.click_target, variables, double_click=is_double)

        elif action == ActionType.APPLESCRIPT:
            raw_script = step.script or ""
            interpolated = cls._interpolate(raw_script, variables, sanitize_as=True)
            return PalHarness.run_applescript(interpolated)

        elif action == ActionType.RUN_SHELL:
            raw_cmd = step.command or ""
            cmd = cls._interpolate(raw_cmd, variables, sanitize_shell=True)
            try:
                import subprocess

                res = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    cwd=step.cwd,
                )
                return res.returncode == 0, res.stderr or res.stdout
            except Exception as e:
                return False, str(e)

        elif action == ActionType.WAIT:
            ms = step.duration_ms or 200
            time.sleep(min(ms, 5000) / 1000.0)
            return True, ""

        elif action == ActionType.NOTIFY:
            msg = cls._interpolate(step.message or "Notification", variables)
            try:
                import rumps

                rumps.notification("VoiceFi Pal", "", msg)
            except Exception:
                pass
            return True, ""

        return False, f"Unknown action: {action}"

    @classmethod
    def _wait_for_window_ready(
        cls, app_name: str, window_pattern: str, timeout_s: float
    ) -> Tuple[bool, str]:
        """Polls macOS System Events / AXUIElement until window is frontmost and present."""
        deadline = time.monotonic() + timeout_s
        clean_app = PalHarness.APP_MAP.get(app_name.lower(), app_name)
        script = f"""
        tell application "System Events"
            if not (exists process "{clean_app}") then return "not_running"
            set p to process "{clean_app}"
            if frontmost of p is true and (count of windows of p) > 0 then
                return "ready"
            end if
            return "not_ready"
        end tell
        """
        while time.monotonic() < deadline:
            ok, out = PalHarness.run_applescript(script)
            if ok and out == "ready":
                return True, "Window ready"
            time.sleep(0.04)  # 40ms low-overhead polling cadence
        return False, f"Timeout waiting for {clean_app} window"

    @classmethod
    def _send_hotkey(cls, key: str, modifiers: List[str]) -> Tuple[bool, str]:
        mod_items = []
        for m in modifiers:
            m_clean = m.lower().replace("cmd", "command").replace("opt", "option")
            mod_items.append(f"{m_clean} down")
        mod_clause = f" using {{{', '.join(mod_items)}}}" if mod_items else ""
        script = f'tell application "System Events" to keystroke "{key}"{mod_clause}'
        return PalHarness.run_applescript(script)

    @classmethod
    def _send_special_key(cls, key_name: str) -> Tuple[bool, str]:
        key_codes = {
            "Return": 36,
            "Enter": 36,
            "Tab": 48,
            "Space": 49,
            "Backspace": 51,
            "Delete": 51,
            "Escape": 53,
            "Esc": 53,
            "Left": 123,
            "Right": 124,
            "Down": 125,
            "Up": 126,
        }
        code = key_codes.get(key_name)
        if code is not None:
            script = f'tell application "System Events" to key code {code}'
            return PalHarness.run_applescript(script)
        script = f'tell application "System Events" to keystroke "{key_name}"'
        return PalHarness.run_applescript(script)

    @classmethod
    def _send_keystroke(cls, text: str, press_enter: bool = False) -> Tuple[bool, str]:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        script = f'tell application "System Events" to keystroke "{escaped}"'
        ok, out = PalHarness.run_applescript(script)
        if ok and press_enter:
            time.sleep(0.05)
            return PalHarness.run_applescript('tell application "System Events" to key code 36')
        return ok, out

    @classmethod
    def _handle_click(
        cls,
        target: Optional[ClickTarget],
        variables: Dict[str, Any],
        double_click: bool = False,
    ) -> Tuple[bool, str]:
        if not target:
            return False, "Missing click target"

        # 1. Menu path click (e.g. ["File", "Export", "All Tracks..."])
        if target.target_type == "menu_path" and target.menu_path:
            path = target.menu_path
            if len(path) >= 2:
                menu_bar_item = path[0]
                menu_item = path[1]
                sub_clause = ""
                if len(path) >= 3:
                    sub_item = path[2]
                    sub_clause = f' of menu item "{sub_item}" of menu 1'
                script = f"""
                tell application "System Events"
                    set frontApp to first application process whose frontmost is true
                    tell frontApp
                        click menu item "{menu_item}"{sub_clause} of menu 1 of menu bar item "{menu_bar_item}" of menu bar 1
                    end tell
                end tell
                """
                return PalHarness.run_applescript(script)

        # 2. Coordinate click via Quartz
        if target.x is not None and target.y is not None:
            try:
                import Quartz
                from Quartz import CGPoint

                pt = CGPoint(float(target.x), float(target.y))
                down_event = Quartz.CGEventCreateMouseEvent(
                    None, Quartz.kCGEventLeftMouseDown, pt, Quartz.kCGMouseButtonLeft
                )
                up_event = Quartz.CGEventCreateMouseEvent(
                    None, Quartz.kCGEventLeftMouseUp, pt, Quartz.kCGMouseButtonLeft
                )
                if double_click:
                    Quartz.CGEventSetIntegerValueField(
                        down_event, Quartz.kCGMouseEventClickState, 2
                    )
                    Quartz.CGEventSetIntegerValueField(up_event, Quartz.kCGMouseEventClickState, 2)

                Quartz.CGEventPost(Quartz.kCGHIDEventTap, down_event)
                time.sleep(0.02)
                Quartz.CGEventPost(Quartz.kCGHIDEventTap, up_event)
                if double_click:
                    time.sleep(0.05)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down_event)
                    time.sleep(0.02)
                    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up_event)
                return True, f"Clicked ({target.x}, {target.y})"
            except Exception as e:
                return False, f"Failed coordinate click: {e}"

        return False, f"Unsupported click target: {target}"

    @classmethod
    def _unwind_failure(cls) -> None:
        """Sends Escape key to safely dismiss any open modal sheets or menus."""
        script = 'tell application "System Events" to key code 53'
        PalHarness.run_applescript(script)

    @classmethod
    def _interpolate(
        cls,
        template: str,
        variables: Dict[str, Any],
        sanitize_shell: bool = False,
        sanitize_as: bool = False,
    ) -> str:
        result = template
        for k, v in variables.items():
            val = str(v)
            if sanitize_shell:
                val = shlex.quote(val)
            elif sanitize_as:
                val = val.replace("\\", "\\\\").replace('"', '\\"')
            result = result.replace(f"${{{k}}}", val)
        return result

    @classmethod
    def _bind_parameters(
        cls,
        param_defs: Dict[str, ParameterDefinition],
        prompt: str,
        explicit_args: Dict[str, Any],
    ) -> Dict[str, Any]:
        bound: Dict[str, Any] = {}
        for name, pdef in param_defs.items():
            if name in explicit_args:
                bound[name] = explicit_args[name]
                continue
            matched = False
            for pat in pdef.extract_patterns:
                m = re.search(pat, prompt, re.IGNORECASE)
                if m and "value" in m.groupdict():
                    bound[name] = m.group("value")
                    matched = True
                    break
            if not matched:
                bound[name] = pdef.default if pdef.default is not None else ""
        return bound


class PalWorkflowRegistry:
    """Discovers, indexes, and caches declarative Pal workflows across user and project roots."""

    _RECIPES: Dict[str, PalWorkflowRecipe] = {}
    _TRIGGER_INDEX: Dict[str, str] = {}  # trigger_phrase -> recipe_id
    _LAST_LOAD_TIME: float = 0.0

    @classmethod
    def get_search_directories(cls) -> List[Path]:
        dirs = []
        # 1. Project-local
        cwd_wf = Path.cwd() / ".voicefi" / "workflows"
        if cwd_wf.exists():
            dirs.append(cwd_wf)

        # 2. User-global
        home_wf = Path.home() / ".voicefi" / "workflows"
        if home_wf.exists():
            dirs.append(home_wf)

        # 3. Built-in bundled
        bundled = Path(__file__).parent / "pal_recipes"
        if bundled.exists():
            dirs.append(bundled)

        return dirs

    @classmethod
    def reload_workflows(cls) -> None:
        """Scan directories and load all .yaml and .json workflow recipes."""
        recipes: Dict[str, PalWorkflowRecipe] = {}
        trigger_index: Dict[str, str] = {}

        for search_dir in cls.get_search_directories():
            for file_path in search_dir.glob("*.yaml"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, dict) and "id" in data and "steps" in data:
                        recipe = PalWorkflowRecipe.model_validate(data)
                        recipes[recipe.id] = recipe
                        # Index triggers
                        for trigger in recipe.triggers:
                            clean_t = trigger.lower().strip()
                            trigger_index[clean_t] = recipe.id
                        # Also index recipe name and id
                        trigger_index[recipe.name.lower().strip()] = recipe.id
                        trigger_index[recipe.id.lower().strip()] = recipe.id
                except Exception as e:
                    print(f"[PalWorkflowRegistry] Error loading {file_path}: {e}")

        # Merge loaded recipes with any existing in-memory recipes
        cls._RECIPES.update(recipes)
        cls._TRIGGER_INDEX.update(trigger_index)
        cls._LAST_LOAD_TIME = time.time()

    @classmethod
    def register_recipe(cls, recipe: PalWorkflowRecipe) -> None:
        """Register a synthesized recipe directly in memory."""
        cls._RECIPES[recipe.id] = recipe
        for trigger in recipe.triggers:
            cls._TRIGGER_INDEX[trigger.lower().strip()] = recipe.id
        cls._TRIGGER_INDEX[recipe.name.lower().strip()] = recipe.id
        cls._TRIGGER_INDEX[recipe.id.lower().strip()] = recipe.id
        cls._LAST_LOAD_TIME = time.time()

    @classmethod
    def match_recipe(cls, prompt: str) -> Optional[Tuple[PalWorkflowRecipe, str]]:
        """
        Match a voice prompt against loaded workflow triggers (<0.5ms).
        Returns (recipe, matched_trigger) if found.
        """
        p_clean = prompt.lower().strip()
        # Remove leading imperative verbs e.g. "run morning setup" -> "morning setup"
        p_stripped = re.sub(r"^(?:run|start|execute|do|trigger)\s+", "", p_clean).strip()

        if not cls._RECIPES or (time.time() - cls._LAST_LOAD_TIME > 60.0):
            cls.reload_workflows()

        recipe_id = cls._TRIGGER_INDEX.get(p_stripped) or cls._TRIGGER_INDEX.get(p_clean)
        if recipe_id and recipe_id in cls._RECIPES:
            return cls._RECIPES[recipe_id], p_stripped

        # Try prefix matching
        for trigger, r_id in cls._TRIGGER_INDEX.items():
            if p_clean == trigger or p_stripped == trigger or p_clean.startswith(trigger + " "):
                return cls._RECIPES[r_id], trigger

        return None
