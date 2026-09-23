"""
Companion route handlers for Obsidian Vault integration, note Q&A, and quick capture.
"""

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Dict, Any, Optional

from aiohttp import web

from voicefi.memo.synthesizer import MemoSynthesizer
from voicefi.tts import get_tts_engine

logger = logging.getLogger(__name__)


class VaultHandlersMixin:
    """Mixin containing Obsidian vault querying, memo appending, and capture endpoints."""

    async def handle_vault_query(self, request: web.Request) -> web.Response:
        """Process conversational Q&A and active note queries from Obsidian."""
        try:
            data = await request.json()
            query = data.get("query", "").strip()
            note_title = data.get("note_title", "")
            note_content = data.get("note_content", "")
            speak = data.get("speak", True)

            from voicefi.integrations.vault_agent import VaultAgent

            agent = VaultAgent(self.config)
            result = agent.answer_vault_query(
                query=query, note_title=note_title, note_content=note_content
            )
            spoken = result.get("spoken_response", "")

            if speak and spoken:
                # Notify connected Obsidian / web clients that agent is speaking
                self.broadcast_event(
                    {
                        "type": "agent_speaking_started",
                        "text": spoken,
                    }
                )

                def _speak_worker():
                    try:
                        tts = get_tts_engine(self.config)
                        tts.speak(spoken)
                    except Exception as ex:
                        print(f"[VaultAgent] TTS playback error: {ex}")
                    finally:
                        self.broadcast_event({"type": "agent_speaking_finished"})

                threading.Thread(target=_speak_worker, daemon=True).start()

            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_vault_capture(self, request: web.Request) -> web.Response:
        """Append a quick voice capture note directly into today's Obsidian daily note."""
        try:
            data = await request.json()
            text = data.get("text", "").strip()
            if not text:
                return web.json_response({"error": "No text provided"}, status=400)

            vault_path_str = data.get("vault_path")
            vault_path = Path(vault_path_str) if vault_path_str else None

            from voicefi.integrations.obsidian import append_quick_capture_to_vault

            res = await asyncio.to_thread(
                append_quick_capture_to_vault, text=text, vault_path=vault_path, config=self.config
            )

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
            return web.json_response(res)
        except Exception as e:
            logger.exception("handle_vault_capture error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_vault_memo(self, request: web.Request) -> web.Response:
        """Save a synthesized voice memo to <vault>/Voice Memos/ and backlink in daily note."""
        try:
            data = await request.json()
            raw_text = data.get("raw_text") or data.get("text", "")
            markdown = data.get("markdown", "").strip()
            title = data.get("title", "").strip()
            vault_path_str = data.get("vault_path")
            vault_path = Path(vault_path_str) if vault_path_str else None

            if not markdown and raw_text:
                synthesizer = MemoSynthesizer(self.config)
                synth = await asyncio.to_thread(synthesizer.synthesize_memo, raw_text)
                title = title or synth.title
                memo_parts = [
                    f"# {synth.title}\n",
                    f"> Voice memo captured on {time.strftime('%Y-%m-%d %H:%M')}\n",
                    f"## Summary\n{synth.summary}\n",
                ]
                if synth.key_points:
                    memo_parts.append("## Key Takeaways\n" + "\n".join(f"- {kp}" for kp in synth.key_points) + "\n")
                if synth.diagram_code:
                    memo_parts.append(f"## Architecture\n```{synth.diagram_type}\n{synth.diagram_code}\n```\n")
                if synth.action_items:
                    memo_parts.append("## Action Items\n" + "\n".join(f"- [ ] {ai}" for ai in synth.action_items) + "\n")
                if synth.pr_checklist:
                    memo_parts.append("## PR / Implementation Checklist\n" + "\n".join(f"- [ ] {c}" for c in synth.pr_checklist) + "\n")
                markdown = "\n".join(memo_parts)

            if not title:
                title = "Voice Memo"
            if not markdown:
                return web.json_response({"error": "No memo content or text provided"}, status=400)

            from voicefi.integrations.obsidian import save_memo_to_vault

            res = await asyncio.to_thread(
                save_memo_to_vault,
                memo_markdown=markdown,
                title=title,
                vault_path=vault_path,
                config=self.config,
            )

            if res.get("status") == "ok":
                self.broadcast_event(
                    {
                        "type": "vault_memo_saved",
                        "vault_name": res.get("vault_name"),
                        "memo_name": res.get("memo_name"),
                        "backlink": res.get("backlink"),
                    }
                )
            return web.json_response(res)
        except Exception as e:
            logger.exception("handle_vault_memo error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_vault_today(self, request: web.Request) -> web.Response:
        """Fetch today's daily note content from Obsidian."""
        try:
            vault_path_str = request.query.get("vault_path")
            vault_path = Path(vault_path_str) if vault_path_str else None

            from voicefi.integrations.obsidian import get_today_note_content

            res = await asyncio.to_thread(get_today_note_content, vault_path=vault_path, config=self.config)
            return web.json_response(res)
        except Exception as e:
            logger.exception("handle_vault_today error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_vault_status(self, request: web.Request) -> web.Response:
        """Get Obsidian installation, vault discovery, and plugin status."""
        try:
            from voicefi.integrations.obsidian import (
                is_obsidian_installed,
                find_obsidian_vaults,
                get_primary_vault,
                get_daily_note_path,
                is_plugin_installed,
            )

            def _get_status():
                installed = is_obsidian_installed()
                vaults = find_obsidian_vaults()
                primary = get_primary_vault(self.config)
                primary_info = None
                if primary:
                    daily_p = get_daily_note_path(primary, config=self.config)
                    plugin_ok = is_plugin_installed(primary)
                    primary_info = {
                        "name": primary.name,
                        "path": str(primary),
                        "daily_note_path": str(daily_p),
                        "daily_note_exists": daily_p.is_file(),
                        "plugin_installed": plugin_ok,
                    }
                return {
                    "status": "ok",
                    "installed": installed,
                    "primary_vault": primary_info,
                    "vaults": [
                        {
                            "id": v.get("id"),
                            "name": v.get("name"),
                            "path": str(v.get("path")),
                            "open": v.get("open", False),
                        }
                        for v in vaults
                    ],
                }

            data = await asyncio.to_thread(_get_status)
            return web.json_response(data)
        except Exception as e:
            logger.exception("handle_vault_status error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_vault_launch_agent(self, request: web.Request) -> web.Response:
        """Launch an AI agent (Antigravity or Claude Code) rooted in the Obsidian vault."""
        try:
            data = await request.json()
            engine = data.get("engine", "antigravity")
            vault_path_str = data.get("vault_path")
            vault_path = Path(vault_path_str) if vault_path_str else None

            from voicefi.integrations.obsidian import launch_agent_in_vault

            res = await asyncio.to_thread(
                launch_agent_in_vault, engine=engine, vault_path=vault_path, config=self.config
            )
            return web.json_response(res)
        except Exception as e:
            logger.exception("handle_vault_launch_agent error: %s", e)
            return web.json_response({"error": str(e)}, status=500)
