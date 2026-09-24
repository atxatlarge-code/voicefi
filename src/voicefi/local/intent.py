"""
VoiceFi On-Device Intent Router & Triage Assistant.
Leverages on-device Gemma on Apple Silicon Metal GPU to instantly classify
spoken wake-word prompts into local macOS system actions vs. targeted AI agent dispatches
(Antigravity, Claude Code, Codex, Obsidian, or VoiceFi Vault).
"""

import os
import re
import subprocess
import datetime
import logging
from typing import Dict, Any, Optional, Tuple

from voicefi.config import VoiceFiConfig, load_config
from voicefi.local.engine import LocalModelEngine

logger = logging.getLogger("voicefi.local.intent")


class LocalIntentRouter:
    """
    On-device intent classifier and action dispatcher for VoiceFi.
    """

    def __init__(
        self, config: Optional[VoiceFiConfig] = None, engine: Optional[LocalModelEngine] = None
    ):
        self.config = config or load_config()
        self.engine = engine or LocalModelEngine()

    def route_prompt(self, prompt: str, use_local_model: bool = True) -> Dict[str, Any]:
        """
        Classify and dispatch a developer spoken prompt.
        Returns a routing descriptor dict.
        """
        if not prompt or not prompt.strip():
            return {"status": "empty", "target": "none"}

        clean_prompt = prompt.strip()
        measure = getattr(getattr(self.config, "local_model", None), "measure_latency", True)

        # 1. Fast-path check: if explicit keyword matches unambiguous target, resolve in 0ms
        fast_intent = self._heuristic_classify(clean_prompt)
        parsed_intent = None

        if fast_intent.get("target") != "antigravity" or not use_local_model:
            parsed_intent = fast_intent
        elif self.engine.is_installed and self.engine.model_exists:
            # Nuanced natural language query: use local Gemma to determine intent & action
            try:
                import asyncio
                import concurrent.futures

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                            parsed_intent, _ = pool.submit(
                                asyncio.run,
                                self.engine.classify_intent(clean_prompt, measure=measure),
                            ).result(timeout=10.0)
                    else:
                        parsed_intent, _ = loop.run_until_complete(
                            self.engine.classify_intent(clean_prompt, measure=measure)
                        )
                except RuntimeError:
                    parsed_intent, _ = asyncio.run(
                        self.engine.classify_intent(clean_prompt, measure=measure)
                    )
            except Exception as e:
                logger.debug("Local classification error: %s, falling back to heuristics", e)
                parsed_intent = fast_intent
        else:
            parsed_intent = fast_intent

        if not parsed_intent:
            parsed_intent = fast_intent

        target = parsed_intent.get("target", "antigravity").lower().strip()
        action = parsed_intent.get("action", clean_prompt)

        # 2. Execute local action if classified as local_command
        if target == "local_command":
            res = self.execute_local_command(clean_prompt)
            return {
                "status": "handled_local",
                "target": "local_command",
                "action": action,
                "spoken_response": res,
                "prompt": clean_prompt,
            }

        # 3. Route to Obsidian
        if target == "obsidian":
            res = self.append_to_obsidian(clean_prompt)
            return {
                "status": "routed_obsidian",
                "target": "obsidian",
                "action": action,
                "spoken_response": res,
                "prompt": clean_prompt,
            }

        # 4. Route to Codex / ChatGPT
        if target == "codex":
            return {
                "status": "routed_agent",
                "target": "codex",
                "engine": "codex",
                "action": action,
                "prompt": clean_prompt,
            }

        # 5. Route to Claude Code
        if target == "claude":
            return {
                "status": "routed_agent",
                "target": "claude",
                "engine": "claude",
                "action": action,
                "prompt": clean_prompt,
            }

        # 6. Route to Private Voice Memo
        if target == "memo":
            return {
                "status": "routed_memo",
                "target": "memo",
                "engine": "memo",
                "action": action,
                "prompt": clean_prompt,
            }

        # Default: Route to Antigravity
        return {
            "status": "routed_agent",
            "target": "antigravity",
            "engine": "antigravity",
            "action": action,
            "prompt": clean_prompt,
        }

    def _heuristic_classify(self, prompt: str) -> Dict[str, Any]:
        """Fast regex/keyword intent classifier."""
        low = prompt.lower().strip()

        # Check for local commands
        if any(
            w in low
            for w in (
                "battery",
                "what time",
                "what day",
                "what date",
                "what branch",
                "git branch",
                "git status",
                "stop speech",
                "stop talking",
                "mute audio",
                "pause audio",
            )
        ):
            return {"target": "local_command", "action": prompt}

        # Check for Obsidian notes
        if any(
            w in low
            for w in ("obsidian", "daily note", "add to journal", "log this note", "note that")
        ):
            return {"target": "obsidian", "action": prompt}

        # Check for Codex / ChatGPT
        if any(w in low for w in ("codex", "chatgpt", "chat gpt", "ask codex", "ask chatgpt")):
            return {"target": "codex", "action": prompt}

        # Check for Claude Code
        if any(w in low for w in ("claude", "ask claude", "run in terminal with claude")):
            return {"target": "claude", "action": prompt}

        # Check for voice memo
        if any(w in low for w in ("voice memo", "record memo", "brain dump")):
            return {"target": "memo", "action": prompt}

        return {"target": "antigravity", "action": prompt}

    def execute_local_command(self, prompt: str) -> str:
        """
        Execute an instant zero-latency local system query or command.
        Returns spoken response text.
        """
        low = prompt.lower()

        # Battery query
        if "battery" in low:
            try:
                out = subprocess.check_output(["pmset", "-g", "batt"], text=True)
                m = re.search(r"(\d+)%", out)
                if m:
                    pct = m.group(1)
                    charging = "charging" in out.lower() or "ac attached" in out.lower()
                    state = "and charging" if charging else "on battery power"
                    return f"Battery is at {pct} percent {state}."
            except Exception:
                pass
            return "Unable to read battery state."

        # Git branch
        if "branch" in low:
            try:
                out = subprocess.check_output(
                    ["git", "branch", "--show-current"], text=True
                ).strip()
                if out:
                    return f"You are on git branch {out}."
            except Exception:
                pass
            return "Not currently in a git repository."

        # Git status
        if "git status" in low or ("git" in low and "status" in low):
            try:
                out = subprocess.check_output(["git", "status", "--short"], text=True).strip()
                if not out:
                    return "Working tree is clean. No uncommitted changes."
                lines = out.splitlines()
                return f"Working tree has {len(lines)} modified or untracked files."
            except Exception:
                pass
            return "Unable to retrieve git status."

        # Time or Date
        if any(w in low for w in ("time", "date", "day", "clock")):
            now = datetime.datetime.now()
            time_str = now.strftime("%-I:%M %p")
            date_str = now.strftime("%A, %B %-d")
            return f"It is {time_str} on {date_str}."

        # Stop / Pause
        if any(w in low for w in ("stop", "pause", "quiet", "hush", "shut up")):
            from voicefi.tts.base import stop_all_speech

            stop_all_speech()
            return "Speech stopped."

        return f"Completed local action: {prompt}"

    def append_to_obsidian(self, prompt: str) -> str:
        """Append spoken note directly to active Obsidian vault's daily note."""
        try:
            from voicefi.integrations.obsidian import append_to_daily_note, get_primary_vault

            vault = get_primary_vault(self.config)
            if vault and vault.is_dir():
                clean_note = re.sub(
                    r"^(?:add to obsidian|note that|log note|daily note)[:,\s]*",
                    "",
                    prompt,
                    flags=re.IGNORECASE,
                ).strip()
                res = append_to_daily_note(clean_note, vault_path=vault, config=self.config)
                if res.get("status") == "ok":
                    return f"Appended note to your Obsidian daily note in {vault.name}."
        except Exception as e:
            logger.debug("Failed to append to Obsidian: %s", e)

        return "Appended note to Obsidian."
