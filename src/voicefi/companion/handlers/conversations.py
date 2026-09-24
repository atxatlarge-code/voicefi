"""
Companion route handlers for agent conversations, artifacts, reviews, and prompt dispatching.
"""

import asyncio
import base64
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from aiohttp import web

import sys
from voicefi.integrations.conversations import (
    set_mobile_turn_origin,
)
from voicefi.integrations.injector import (
    create_new_antigravity_conversation,
    send_message_to_agent,
    send_message_to_antigravity,
)

logger = logging.getLogger(__name__)


def _resolve_send_message_to_agent(*args, **kwargs):
    server_mod = sys.modules.get("voicefi.companion.server")
    fn = (
        getattr(server_mod, "send_message_to_agent", send_message_to_agent)
        if server_mod
        else send_message_to_agent
    )
    return fn(*args, **kwargs)


def _resolve_send_message_to_antigravity(*args, **kwargs):
    server_mod = sys.modules.get("voicefi.companion.server")
    fn = (
        getattr(server_mod, "send_message_to_antigravity", send_message_to_antigravity)
        if server_mod
        else send_message_to_antigravity
    )
    return fn(*args, **kwargs)


def _resolve_create_new_antigravity_conversation(*args, **kwargs):
    server_mod = sys.modules.get("voicefi.companion.server")
    fn = (
        getattr(
            server_mod, "create_new_antigravity_conversation", create_new_antigravity_conversation
        )
        if server_mod
        else create_new_antigravity_conversation
    )
    return fn(*args, **kwargs)


class ConversationsHandlersMixin:
    """Mixin containing conversation listing, detail, artifacts, reviews, and prompt submission."""

    async def handle_plan_action(self, request: web.Request) -> web.Response:
        """Handle 1-tap quick action on implementation plans."""
        try:
            data = await request.json()
            action = data.get("action", "approve")
            conv_id = data.get("conv_id")
            custom_feedback = data.get("text", "").strip()

            if action == "approve":
                prompt_text = "Approved. Please proceed with the implementation plan."
            elif action == "reject":
                prompt_text = (
                    f"Plan rejected: {custom_feedback}"
                    if custom_feedback
                    else "Plan rejected. Please revise the approach."
                )
            else:
                prompt_text = custom_feedback or "Please review and adjust the implementation plan."

            set_mobile_turn_origin(conv_id)
            delivered = bool(_resolve_send_message_to_agent(conv_id=conv_id, text=prompt_text))
            self.broadcast_event(
                {
                    "type": "plan_action_dispatched",
                    "conv_id": conv_id or "active",
                    "action": action,
                    "text": prompt_text,
                    "delivered": delivered,
                }
            )
            return web.json_response(
                {
                    "success": True,
                    "action": action,
                    "prompt": prompt_text,
                    "delivered": delivered,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_conversations(self, request: web.Request) -> web.Response:
        convs = self.tracker.get_all_conversations(limit=12)
        active = self.tracker.get_active_or_latest()
        active_id = active.id if active else ""

        vault_info = None
        try:
            from voicefi.integrations.obsidian import get_primary_vault

            pv = get_primary_vault(self.config)
            if pv:
                vault_info = {
                    "name": pv.name,
                    "path": str(pv),
                }
        except Exception:
            pass

        return web.json_response(
            {
                "conversations": [
                    {
                        "id": c.id,
                        "title": c.title,
                        "status": c.status,
                        "mtime": c.mtime,
                        "engine": getattr(c, "engine", "antigravity"),
                        "project_name": getattr(c, "project_name", None),
                    }
                    for c in convs
                ],
                "active_id": active_id,
                "vault": vault_info,
            }
        )

    async def handle_conversation_detail(self, request: web.Request) -> web.Response:
        conv_id = request.match_info.get("conv_id")
        if not conv_id:
            return web.json_response({"error": "Missing conv_id"}, status=400)
        details = self.tracker.get_conversation_details(conv_id)
        if not details:
            return web.json_response({"error": "Conversation not found"}, status=404)
        return web.json_response(details)

    async def handle_conversation_artifact(self, request: web.Request) -> web.Response:
        conv_id = request.match_info.get("conv_id")
        filename = request.match_info.get("filename")
        if not conv_id or not filename:
            return web.json_response({"error": "Missing conv_id or filename"}, status=400)
        art = self.tracker.get_artifact(conv_id, filename)
        if not art:
            return web.json_response({"error": "Artifact not found"}, status=404)
        return web.json_response(art)

    async def handle_new_conversation(self, request: web.Request) -> web.Response:
        """Create and focus a new conversation (Antigravity or Claude Code)."""
        try:
            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    data = {}

            prompt = data.get("prompt", "Hello")
            title = data.get("title")
            model = data.get("model")
            engine = data.get("engine", "antigravity")
            active = None

            if engine == "codex":
                from voicefi.integrations.codex import execute_codex_cli, get_codex_cli_path
                from voicefi.integrations.injector import inject_text_to_chatgpt

                cli_path = get_codex_cli_path()
                if cli_path:
                    disp = execute_codex_cli(
                        prompt=prompt,
                        conv_id=None,
                        origin="mobile",
                        async_execution=True,
                    )
                    active_id = getattr(disp, "target_conv_id", None) or f"codex_{int(time.time())}"
                else:
                    inject_text_to_chatgpt(prompt, submit_enter=True)
                    active_id = f"codex_session_{int(time.time())}"
            elif engine == "claude":
                from voicefi.integrations.claude_runner import ClaudeHeadlessRunner

                runner = ClaudeHeadlessRunner.get_instance()
                disp = runner.dispatch(
                    text=prompt,
                    conv_id=None,
                    config=self.config,
                    async_execution=True,
                )
                active_id = getattr(disp, "target_conv_id", None) or "claude_active"
            else:
                new_id = _resolve_create_new_antigravity_conversation(
                    prompt=prompt, title=title, model=model
                )
                await asyncio.sleep(0.5)
                active = self.tracker.get_active_or_latest()
                active_id = new_id or (active.id if active else "")

            if active_id:
                self.tracker.set_active_focus(active_id)
                if not active:
                    active = self.tracker.get_active_or_latest()
                self.broadcast_event(
                    {
                        "type": "conversation_created",
                        "conv_id": active_id,
                        "title": active.title if active else (title or "New Conversation"),
                        "engine": engine,
                    }
                )

            convs = self.tracker.get_all_conversations(limit=12)
            return web.json_response(
                {
                    "success": True,
                    "conv_id": active_id,
                    "conversations": [
                        {
                            "id": c.id,
                            "title": c.title,
                            "status": c.status,
                            "mtime": c.mtime,
                            "engine": getattr(c, "engine", "antigravity"),
                            "project_name": getattr(c, "project_name", None),
                        }
                        for c in convs
                    ],
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_switch(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            conv_id = data.get("conv_id")
            if conv_id:
                self.tracker.set_active_focus(conv_id)
                self.broadcast_event(
                    {
                        "type": "conversation_switched",
                        "conv_id": conv_id,
                    }
                )
                return web.json_response({"success": True, "active_id": conv_id})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"error": "Missing conv_id"}, status=400)

    async def handle_send(self, request: web.Request) -> web.Response:
        try:
            try:
                data = await request.json()
            except Exception:
                return web.json_response(
                    {
                        "error": "Invalid JSON payload",
                        "success": False,
                        "delivered": False,
                        "delivered_ipc": False,
                        "pasted_to_foreground": False,
                    },
                    status=400,
                )

            if not isinstance(data, dict):
                return web.json_response(
                    {
                        "error": "JSON body must be an object",
                        "success": False,
                        "delivered": False,
                        "delivered_ipc": False,
                        "pasted_to_foreground": False,
                    },
                    status=400,
                )

            raw_text = data.get("text")
            if raw_text is None or not isinstance(raw_text, str) or not raw_text.strip():
                return web.json_response(
                    {
                        "error": "Empty text prompt",
                        "success": False,
                        "delivered": False,
                        "delivered_ipc": False,
                        "pasted_to_foreground": False,
                    },
                    status=400,
                )

            text = raw_text.strip()
            conv_id = data.get("conv_id") or data.get("conversation_id")
            reply_to = data.get("reply_to") or data.get("reply_to_conv_id")
            if not conv_id and reply_to:
                conv_id = reply_to
            sender_name = data.get("sender_name") or "ViFi Companion"
            title = data.get("title") or f"Message from {sender_name}"
            target_engine = data.get("engine") or data.get("to_engine")
            from_conv_id = data.get("from_conv_id")
            from_engine = data.get("from_engine")
            include_envelope = bool(data.get("include_envelope", False))

            lower_text = text.lower().strip()
            if not target_engine:
                if conv_id and (conv_id.startswith("claude_") or "claude" in conv_id.lower()):
                    target_engine = "claude"
                elif conv_id and (conv_id.startswith("codex_") or "codex" in conv_id.lower()):
                    target_engine = "codex"
                elif bool(
                    re.search(
                        r"\b(?:hey|ask|tell|can\s+you\s+ask|could\s+you\s+ask|send\s+to|talk\s+to|switch\s+to)\s+codex\b",
                        lower_text,
                    )
                ):
                    target_engine = "codex"
                    if (
                        conv_id
                        and not conv_id.startswith("codex_")
                        and "codex" not in conv_id.lower()
                    ):
                        conv_id = None
                elif bool(
                    re.search(
                        r"\b(?:hey|ask|tell|can\s+you\s+ask|could\s+you\s+ask|send\s+to|talk\s+to|switch\s+to)\s+claude\b",
                        lower_text,
                    )
                ):
                    target_engine = "claude"
                    if (
                        conv_id
                        and not conv_id.startswith("claude_")
                        and "claude" not in conv_id.lower()
                    ):
                        conv_id = None

            set_mobile_turn_origin(conv_id)

            intent_mode = data.get("intent_mode")
            if intent_mode in ("speed", "comic") or target_engine in (
                "speed",
                "comic",
                "gemini_live",
            ):
                from voicefi.integrations.gemini_live import GeminiLiveRunner

                is_comic = intent_mode == "comic" or target_engine == "comic"
                voice = data.get("voice") or ("Puck" if is_comic else "Aoede")
                mode = "comedy" if is_comic else "assistant"
                enable_sfx = is_comic
                self.broadcast_event(
                    {
                        "type": "agent_thinking",
                        "engine": "gemini_live",
                        "intent_mode": intent_mode or ("comic" if is_comic else "speed"),
                        "avatar": "🎭" if is_comic else "⚡",
                        "text": "Puck is roasting..." if is_comic else "Gemini Live is thinking...",
                    }
                )
                play_audio = bool(data.get("play_audio_on_server", data.get("play_audio", False)))
                runner = GeminiLiveRunner(
                    voice=voice, mode=mode, enable_sfx=enable_sfx, play_audio=play_audio
                )
                res = await runner.run_prompt(text)
                self.broadcast_event(
                    {
                        "type": "agent_speaking_started",
                        "engine": "gemini_live",
                        "intent_mode": intent_mode or ("comic" if is_comic else "speed"),
                        "text": res.get("transcript", ""),
                        "audio_data_uri": res.get("audio_data_uri"),
                        "triggered_sfx": res.get("triggered_sfx", []),
                        "avatar": "🎭" if is_comic else "⚡",
                    }
                )
                return web.json_response(
                    {
                        "success": True,
                        "delivered": True,
                        "delivered_ipc": True,
                        "engine": "gemini_live",
                        "intent_mode": intent_mode or ("comic" if is_comic else "speed"),
                        "result": res,
                    }
                )

            if target_engine == "obsidian" or conv_id == "obsidian":
                from voicefi.integrations.obsidian import append_quick_capture_to_vault
                from voicefi.integrations.vault_agent import VaultAgent, is_vault_question

                # A spoken question is answered out of the vault and read back.
                # Anything else is a thought, and goes into today's daily note.
                if is_vault_question(text):
                    agent = VaultAgent(self.config)
                    answer = await asyncio.to_thread(agent.answer_vault_query, text)
                    spoken = answer.get("spoken_response", "")
                    if spoken:
                        self.broadcast_event(
                            {
                                "type": "vault_answer",
                                "text": spoken,
                                "query": text,
                                "sources": answer.get("sources", []),
                                "provider": answer.get("provider"),
                            }
                        )
                        self._speak_in_background(spoken)
                    return web.json_response(
                        {
                            "success": True,
                            "delivered": True,
                            "delivered_ipc": True,
                            "engine": "obsidian",
                            "mode": "query",
                            "res": answer,
                        }
                    )

                res = append_quick_capture_to_vault(text=text, config=self.config)
                if res.get("status") == "ok":
                    self.broadcast_event(
                        {
                            "type": "vault_capture_appended",
                            "vault_name": res.get("vault_name"),
                            "daily_note_name": res.get("daily_note_name"),
                            "entry": res.get("entry"),
                            "time": res.get("time"),
                        }
                    )
                    return web.json_response(
                        {
                            "success": True,
                            "delivered": True,
                            "delivered_ipc": True,
                            "engine": "obsidian",
                            "res": res,
                        }
                    )
                else:
                    return web.json_response(
                        {
                            "success": False,
                            "delivered": False,
                            "error": res.get("error", "Vault write failed"),
                            "engine": "obsidian",
                        },
                        status=500,
                    )

            cwd_arg = data.get("cwd") or data.get("vault_path")
            if not cwd_arg and target_engine in ("claude_obsidian", "obsidian_claude"):
                from voicefi.integrations.obsidian import get_primary_vault

                cwd_arg = get_primary_vault(self.config)
                target_engine = "claude"

            result = await asyncio.to_thread(
                _resolve_send_message_to_agent,
                conv_id=conv_id,
                text=text,
                sender_name=sender_name,
                title=title,
                target_engine=target_engine,
                from_conv_id=from_conv_id,
                from_engine=from_engine,
                include_envelope=include_envelope,
                allow_foreground_fallback=False,  # Strict: never blind-paste for API sends
                use_headless=True,
                cwd=Path(cwd_arg) if cwd_arg else None,
            )
            is_success = bool(result)
            delivery_type = getattr(result, "delivery_type", "ipc" if is_success else "none")
            err_msg = getattr(result, "error", None)
            target_cid = getattr(result, "target_conv_id", conv_id) or conv_id

            self.broadcast_event(
                {
                    "type": "user_command_injected",
                    "conv_id": target_cid or conv_id or "active",
                    "text": text,
                    "delivered": is_success,
                }
            )
            resp_data = {
                "success": is_success,
                "delivered": is_success,
                "delivered_ipc": (delivery_type == "ipc"),
                "delivered_headless": (delivery_type == "headless"),
                "pasted_to_foreground": (delivery_type == "foreground_paste"),
                "target_engine": target_engine or getattr(result, "engine", "antigravity"),
                "conv_id": target_cid,
            }
            if err_msg:
                resp_data["error"] = err_msg

            status_code = 200 if is_success else 500
            return web.json_response(resp_data, status=status_code)
        except Exception as e:
            return web.json_response(
                {
                    "error": str(e),
                    "success": False,
                    "delivered": False,
                    "delivered_ipc": False,
                    "pasted_to_foreground": False,
                },
                status=500,
            )

    async def handle_turn_notify(self, request: web.Request) -> web.Response:
        """
        Receives turn completion notification from background headless runners (e.g. Claude Code)
        and immediately broadcasts the turn completion to mobile and web companion clients.
        """
        try:
            try:
                data = await request.json()
            except Exception:
                return web.json_response(
                    {"error": "Invalid JSON payload", "status": "error"}, status=400
                )

            if not isinstance(data, dict):
                return web.json_response(
                    {"error": "JSON body must be an object", "status": "error"}, status=400
                )

            summary = data.get("summary", "")
            conv_id = data.get("conv_id", "")
            agent_role = data.get("agent_role", "claude")
            full_response = data.get("full_response", "")
            origin = data.get("origin", "mobile")
            delivered_via = data.get("delivered_via", "hook")
            spoken_on_mac = data.get("spoken_on_mac", False)
            step_index = data.get("step_index")

            self.broadcast_turn_completion(
                summary=summary,
                conv_id=conv_id,
                agent_role=agent_role,
                full_response=full_response,
                origin=origin,
                delivered_via=delivered_via,
                spoken_on_mac=spoken_on_mac,
                step_index=step_index,
            )
            return web.json_response({"status": "ok", "broadcast": True})
        except Exception as e:
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    async def handle_artifact_review(self, request: web.Request) -> web.Response:
        """Process structured markdown comments/review feedback from mobile companion."""
        try:
            data = await request.json()
            conv_id = request.match_info.get("conv_id") or data.get("conv_id")
            if not conv_id:
                active = self.tracker.get_active_or_latest()
                conv_id = active.id if active else "default"

            filename = data.get("filename", "document.md")
            comments = data.get("comments", [])
            general_feedback = data.get("general_feedback", "").strip()
            sender_name = data.get("sender_name", "Mobile Review")

            if not comments and not general_feedback:
                return web.json_response({"error": "No comments or feedback provided"}, status=400)

            # Build markdown review body matching Antigravity review format
            lines = [f"### Review Comments on `{filename}`:\n"]
            for idx, c in enumerate(comments, 1):
                snippet = c.get("snippet", "").strip()
                comment_text = c.get("comment", "").strip()
                if snippet:
                    clean_snippet = "\n> ".join(snippet.splitlines())
                    lines.append(f"{idx}. **Regarding excerpt:**\n> {clean_snippet}")
                else:
                    lines.append(f"{idx}. **Comment:**")
                if comment_text:
                    lines.append(f"   **Feedback:** {comment_text}\n")

            if general_feedback:
                lines.append(f"**Overall Notes:**\n{general_feedback}\n")

            lines.append("Please update the artifact document or source files accordingly.")
            formatted_prompt = "\n".join(lines)

            set_mobile_turn_origin(conv_id)
            delivered = _resolve_send_message_to_antigravity(
                conv_id=conv_id,
                text=formatted_prompt,
                sender_name=sender_name,
                title=f"Review on {filename}",
            )

            self.broadcast_event(
                {
                    "type": "artifact_reviewed",
                    "conv_id": conv_id,
                    "filename": filename,
                    "comments_count": len(comments),
                    "delivered": delivered,
                }
            )

            return web.json_response(
                {
                    "success": True,
                    "conv_id": conv_id,
                    "filename": filename,
                    "comments_count": len(comments),
                    "delivered": delivered,
                    "message": formatted_prompt,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_image_feedback(self, request: web.Request) -> web.Response:
        """Process finger drawing/annotation and spoken/typed visual feedback on an image."""
        try:
            data = await request.json()
            conv_id = request.match_info.get("conv_id") or data.get("conv_id")
            if not conv_id:
                active = self.tracker.get_active_or_latest()
                conv_id = active.id if active else "default"

            original_filename = data.get("original_filename", "image.jpg")
            annotated_b64 = data.get("annotated_image_base64") or data.get("image_base64", "")
            feedback_text = data.get("feedback_text", "").strip()
            sender_name = data.get("sender_name", "Visual Review")

            if not annotated_b64:
                return web.json_response({"error": "Missing annotated image data"}, status=400)

            if "," in annotated_b64:
                annotated_b64 = annotated_b64.split(",", 1)[1]

            import base64

            img_bytes = base64.b64decode(annotated_b64)

            bdir = self.tracker.brain_dir / conv_id
            bdir.mkdir(parents=True, exist_ok=True)

            orig_stem = Path(original_filename).stem
            orig_stem_clean = re.sub(r"[^a-zA-Z0-9_\-]", "_", orig_stem)
            ts_str = time.strftime("%Y%m%d_%H%M%S")
            unique_id = uuid.uuid4().hex[:6]
            filename = f"annotated_{orig_stem_clean}_{ts_str}_{unique_id}.jpg"
            target_path = bdir / filename
            target_path.write_bytes(img_bytes)

            art = self.tracker.get_artifact(conv_id, filename)

            # Build feedback message
            lines = [f"### Visual Markup & Feedback on `{original_filename}`:\n"]
            lines.append(
                f"I've circled and drawn notes directly on the image: [{filename}](file://{target_path})\n"
            )
            if feedback_text:
                lines.append(f"**Notes / Instructions:**\n{feedback_text}\n")
            lines.append(
                "Please inspect the marked-up image and adjust the code/design accordingly."
            )
            formatted_prompt = "\n".join(lines)

            set_mobile_turn_origin(conv_id)
            delivered = _resolve_send_message_to_antigravity(
                conv_id=conv_id,
                text=formatted_prompt,
                sender_name=sender_name,
                title=f"Visual Feedback on {original_filename}",
            )

            self.broadcast_event(
                {
                    "type": "conversation_updated",
                    "conv_id": conv_id,
                }
            )

            return web.json_response(
                {
                    "success": True,
                    "conv_id": conv_id,
                    "original_filename": original_filename,
                    "filename": filename,
                    "path": str(target_path),
                    "url": f"/api/conversation/{conv_id}/artifact/{filename}",
                    "delivered": delivered,
                    "message": formatted_prompt,
                    "artifact": art,
                }
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
