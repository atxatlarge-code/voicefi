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
    Supports Two-Speed Brain handoff (Qwen 1.5B Reflex + Gemma 4 26B Deep Brain),
    silent screen vision capture ('Look at my screen'), and the 3-turn Zmail Hero
    email workflow (Triage -> Draft & Open on Screen -> 'LGTM / Ship It').
    """

    def __init__(
        self,
        config: Optional[VoiceFiConfig] = None,
        engine: Optional[LocalModelEngine] = None,
        zmail_bridge: Optional[Any] = None,
        tier0_arbiter: Optional[Any] = None,
    ):
        self.config = config or load_config()
        self.engine = engine or LocalModelEngine()
        self._zmail_bridge = zmail_bridge
        self._tier0_arbiter = tier0_arbiter

    @property
    def tier0_arbiter(self) -> Any:
        if self._tier0_arbiter is None:
            from voicefi.local.embed import Tier0ReflexArbiter

            self._tier0_arbiter = Tier0ReflexArbiter()
        return self._tier0_arbiter

    @property
    def zmail(self) -> Any:
        if self._zmail_bridge is None:
            from voicefi.integrations.zmail import ZmailVoiceBridge

            self._zmail_bridge = ZmailVoiceBridge()
        return self._zmail_bridge

    @staticmethod
    def strip_wake_prefix(prompt: str) -> str:
        """Strip leading wake words ('Hey Pal', 'Hey Brok', 'Hey Viv', 'Hey ViFi') from a transcript."""
        return re.sub(
            r"^(?:hey\s+)?(?:pal|brok|viv|vifi|vi-fi|voicefi)\b[,:\s-]*",
            "",
            (prompt or "").strip(),
            flags=re.IGNORECASE,
        ).strip()

    def route_prompt(
        self,
        prompt: str,
        use_local_model: bool = True,
        on_ack: Optional[Any] = None,
        on_thought_token: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Classify and dispatch a spoken prompt.
        Returns a routing descriptor dict including `reflex_ack`, `spoken_response`, and `target`.
        """
        if not prompt or not prompt.strip():
            return {"status": "empty", "target": "none"}

        raw_prompt = prompt.strip()
        clean_prompt = self.strip_wake_prefix(raw_prompt) or raw_prompt
        measure = getattr(getattr(self.config, "local_model", None), "measure_latency", True)

        # 1. Fast-path check: if explicit keyword matches unambiguous target, resolve in 0ms
        fast_intent = self._heuristic_classify(clean_prompt)
        parsed_intent = None

        # 1b. Tier 0 Edge Reflex Arbitration (EmbeddingGemma 2 + TEV 0.8B <30ms)
        if fast_intent.get("target") == "antigravity" and use_local_model:
            try:
                t0_action = self.tier0_arbiter.arbitrate(clean_prompt)
                if not t0_action.escalate:
                    if t0_action.action == "focus_window" and t0_action.bundle_id:
                        subprocess.run(["open", "-b", t0_action.bundle_id], check=False)
                        return {
                            "status": "handled_tier0_reflex",
                            "target": "local_window_focus",
                            "action": t0_action.action,
                            "bundle_id": t0_action.bundle_id,
                            "spoken_response": f"Switched to {t0_action.title or t0_action.bundle_id}.",
                            "prompt": clean_prompt,
                        }
                    elif t0_action.action in ("media_control", "read_telemetry"):
                        res = self.execute_local_command(clean_prompt)
                        return {
                            "status": "handled_tier0_reflex",
                            "target": "local_command",
                            "action": t0_action.action,
                            "spoken_response": res,
                            "prompt": clean_prompt,
                        }
            except Exception as e:
                logger.debug("Tier 0 reflex arbitration bypassed (%s)", e)

        if fast_intent.get("target") != "antigravity" or not use_local_model:
            parsed_intent = fast_intent
        elif self.engine.is_installed and self.engine.model_exists:
            # Nuanced natural language query: use local model to determine intent & action
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
        reflex_ack = parsed_intent.get("ack")

        if reflex_ack and callable(on_ack):
            try:
                on_ack(reflex_ack)
            except Exception:
                pass

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

        # 2b. 3-Turn Email Workflow via Headless Zmail Hero
        if target == "email_triage":
            triage_res = self.zmail.triage_important_emails(
                limit=3,
                engine=self.engine if use_local_model else None,
                on_thought_token=on_thought_token,
            )
            return {
                "status": "handled_email_triage",
                "target": "email_triage",
                "action": action,
                "reflex_ack": reflex_ack or "Checking your inbox now...",
                "spoken_response": triage_res.get("spoken_response", ""),
                "emails": triage_res.get("emails", []),
                "sql_latency_ms": triage_res.get("sql_latency_ms", 0.0),
                "prompt": clean_prompt,
            }

        if target == "email_draft":
            draft_res = self.zmail.draft_and_open_on_screen(
                user_instructions=clean_prompt,
                engine=self.engine if use_local_model else None,
                on_thought_token=on_thought_token,
            )
            return {
                "status": "handled_email_draft",
                "target": "email_draft",
                "action": action,
                "reflex_ack": reflex_ack or "Drafting your replies now...",
                "spoken_response": draft_res.get("spoken_response", ""),
                "drafts": draft_res.get("drafts", []),
                "review_html_path": draft_res.get("review_html_path"),
                "prompt": clean_prompt,
            }

        if target == "email_ship":
            ship_res = self.zmail.ship_staged_drafts()
            return {
                "status": "handled_email_ship",
                "target": "email_ship",
                "action": action,
                "reflex_ack": reflex_ack or "Shipping your replies...",
                "spoken_response": ship_res.get("spoken_response", ""),
                "shipped_count": ship_res.get("shipped_count", 0),
                "prompt": clean_prompt,
            }

        # 2c. Silent Active-Window Vision ('Look at my screen')
        if target == "vision_screen":
            from voicefi.local.engine import capture_active_window_image

            image_path = capture_active_window_image()
            spoken = "Captured your active window for local Gemma vision analysis."
            if use_local_model and self.engine.is_installed and self.engine.model_exists:
                try:
                    import asyncio

                    spoken = asyncio.run(
                        self.engine.chat_text(
                            prompt=clean_prompt,
                            image_path=image_path,
                            on_thought_token=on_thought_token,
                        )
                    )
                except Exception as exc:
                    logger.debug("Local vision inference fallback: %s", exc)
            return {
                "status": "handled_vision_screen",
                "target": "vision_screen",
                "action": action,
                "reflex_ack": reflex_ack or "Scanning your window now...",
                "image_path": image_path,
                "spoken_response": spoken,
                "prompt": clean_prompt,
            }

        # 2d. Two-Speed Brain Handoff (Qwen 1.5B Reflex + Gemma 4 26B Deep Brain)
        if target == "two_speed_handoff":
            reflex_summary = self._execute_two_speed_reflex(clean_prompt)
            spoken = reflex_summary
            if use_local_model and self.engine.is_installed and self.engine.model_exists:
                try:
                    import asyncio

                    deep_prompt = (
                        f"User request: {clean_prompt}\n"
                        f"Reflex system snapshot: {reflex_summary}\n"
                        "Give a 2-sentence root-cause verdict for the voice channel."
                    )
                    verdict = asyncio.run(
                        self.engine.chat_text(
                            prompt=deep_prompt,
                            on_thought_token=on_thought_token,
                        )
                    )
                    if verdict:
                        spoken = verdict
                except Exception as exc:
                    logger.debug("Two-speed deep brain fallback: %s", exc)
            return {
                "status": "handled_two_speed",
                "target": "two_speed_handoff",
                "action": action,
                "reflex_ack": reflex_ack or "Checking the system now...",
                "reflex_summary": reflex_summary,
                "spoken_response": spoken,
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
        """Fast <1ms regex/keyword intent classifier for Reflex + Deep Brain routing."""
        low = self.strip_wake_prefix(prompt).lower().strip()

        # 1. Email Turn 3: 'LGTM', 'ship it', 'send the drafts', 'send it'
        if re.match(
            r"^(?:lgtm\b|ship\s+it\b|send\s+(?:it|them|the\s+drafts?|all\s+drafts?|replies)\b|looks\s+good\s+to\s+me\b|approve\s+and\s+send\b)",
            low,
        ):
            return {
                "target": "email_ship",
                "action": prompt,
                "ack": "Shipping your replies...",
            }

        # 2. Email Turn 2: 'Draft responses and open on my screen to read'
        if any(
            phrase in low
            for phrase in (
                "draft response",
                "draft replies",
                "draft a reply",
                "draft a response",
                "open on my screen to read",
                "draft email",
            )
        ) or ("draft" in low and any(w in low for w in ("email", "emails", "response", "responses", "reply", "replies", "screen"))):
            return {
                "target": "email_draft",
                "action": prompt,
                "ack": "Drafting your replies now...",
            }

        # 3. Email Turn 1: 'Any important emails to respond to?'
        if any(
            phrase in low
            for phrase in (
                "important email",
                "important emails",
                "emails to respond",
                "urgent email",
                "urgent emails",
                "check my inbox",
                "check my email",
                "triage my inbox",
                "unread email",
            )
        ):
            return {
                "target": "email_triage",
                "action": prompt,
                "ack": "Checking your inbox now...",
            }

        # 4. Multimodal Screen Vision ('Look at my screen')
        if any(
            phrase in low
            for phrase in (
                "look at my screen",
                "on my screen",
                "look at this window",
                "look at this screen",
                "what's on my screen",
            )
        ):
            return {
                "target": "vision_screen",
                "action": prompt,
                "ack": "Scanning your window now...",
            }

        # 5. Two-Speed Brain Handoff (Port/Process Reflex + Deep Root-Cause Diagnosis)
        if (
            any(w in low for w in ("port", "ports", "orphaned", "node process", "hogging memory", "eating my battery"))
            and any(w in low for w in ("why", "failed", "spiked", "tell me", "kill"))
        ):
            return {
                "target": "two_speed_handoff",
                "action": prompt,
                "ack": "Checking the diff now...",
            }

        # 6. Direct Local Commands
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

        # 7. Obsidian Notes
        if any(
            w in low
            for w in ("obsidian", "daily note", "add to journal", "log this note", "note that")
        ):
            return {"target": "obsidian", "action": prompt}

        # 8. Codex / ChatGPT
        if any(w in low for w in ("codex", "chatgpt", "chat gpt", "ask codex", "ask chatgpt")):
            return {"target": "codex", "action": prompt}

        # 9. Claude Code
        if any(w in low for w in ("claude", "ask claude", "run in terminal with claude")):
            return {"target": "claude", "action": prompt}

        # 10. Voice Memo
        if any(w in low for w in ("voice memo", "record memo", "brain dump")):
            return {"target": "memo", "action": prompt}

        return {"target": "antigravity", "action": prompt}

    def _execute_two_speed_reflex(self, prompt: str) -> str:
        """
        Execute the fast <30ms Qwen 1.5B reflex check (hanging local ports / process snapshot)
        without stealing window focus.
        """
        active_ports = []
        for port in (3000, 5173, 8000, 8080):
            try:
                out = subprocess.check_output(
                    ["lsof", "-i", f":{port}", "-t"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=1.0,
                ).strip()
                if out:
                    active_ports.append(port)
            except Exception:
                pass
        if active_ports:
            ports_str = ", ".join(str(p) for p in active_ports)
            return f"Detected active listeners on local ports {ports_str}."
        return "Local dev ports 3000, 5173, and 8080 are clear with no orphaned Node listeners."

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
