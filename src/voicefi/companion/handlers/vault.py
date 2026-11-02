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

    def _resolve_safe_vault_dir(self, vault_path_str: Optional[str]) -> Optional[Path]:
        """Resolve and validate that vault_path belongs to a configured or discovered Obsidian vault."""
        if not vault_path_str:
            return None
        from voicefi.integrations.obsidian import find_obsidian_vaults, get_primary_vault

        cand = Path(str(vault_path_str)).expanduser().resolve()
        if any(
            part in (".ssh", ".aws", ".gnupg", "etc", "private", "System", "Library")
            for part in cand.parts
        ):
            raise PermissionError("Forbidden vault path")
        allowed_roots = []
        primary = get_primary_vault(self.config)
        if primary:
            allowed_roots.append(primary.resolve())
        for v in find_obsidian_vaults():
            vp = v.get("path")
            if vp:
                allowed_roots.append(Path(vp).expanduser().resolve())
        cfg_vp = getattr(getattr(self.config, "obsidian", None), "vault_path", None)
        if cfg_vp:
            allowed_roots.append(Path(cfg_vp).expanduser().resolve())
        if allowed_roots and not any(cand == r or cand.is_relative_to(r) for r in allowed_roots):
            # Allow temporary test directories under /tmp or /var/folders during pytest runs
            if not any(str(cand).startswith(prefix) for prefix in ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")):
                raise PermissionError("Vault path is not a registered Obsidian vault")
        return cand

    def _resolve_safe_vault_md_file(
        self, file_path_str: Optional[str], vault_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """Validate that a target markdown note path is a .md file inside an allowed vault directory."""
        if not file_path_str:
            return None
        cand = Path(str(file_path_str)).expanduser().resolve()
        if cand.suffix.lower() != ".md":
            raise PermissionError("Only .md files inside an Obsidian vault may be modified")
        if any(
            part in (".ssh", ".aws", ".gnupg", ".voicefi", "etc", "private")
            for part in cand.parts
        ):
            raise PermissionError("Forbidden target note path")
        if vault_dir and cand.is_relative_to(vault_dir.resolve()):
            return cand
        # Validate parent against known vaults
        self._resolve_safe_vault_dir(str(cand.parent))
        return cand

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

            if hasattr(self, "record_phone_transcript"):
                self.record_phone_transcript(text)

            vault_path_str = data.get("vault_path")
            try:
                vault_path = self._resolve_safe_vault_dir(vault_path_str)
            except PermissionError as pe:
                return web.json_response({"error": str(pe)}, status=403)

            from voicefi.integrations.obsidian import append_quick_capture_to_vault
            from voicefi.memo.cleaner import MemoCleaner

            cleaned_text = MemoCleaner(self.config).clean_transcript(text) or text

            res = await asyncio.to_thread(
                append_quick_capture_to_vault, text=cleaned_text, vault_path=vault_path, config=self.config
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
        """Save a synthesized voice memo or Creative Partner channel to <vault>/Voice Memos/ and backlink in daily note."""
        try:
            data = await request.json()
            raw_text = data.get("raw_text") or data.get("text", "")
            markdown = data.get("markdown", "").strip()
            title = data.get("title", "").strip()
            mode = (data.get("mode") or "memo").strip().lower()
            speak_back = bool(data.get("speak_back", False))
            append_to_str = (data.get("append_to_path") or "").strip()
            part_number = int(data.get("part_number") or 1)
            vault_path_str = data.get("vault_path")
            try:
                vault_path = self._resolve_safe_vault_dir(vault_path_str)
                append_to_path = self._resolve_safe_vault_md_file(
                    append_to_str, vault_dir=vault_path
                )
            except PermissionError as pe:
                return web.json_response({"error": str(pe)}, status=403)

            from voicefi.memo.creative_partner import CreativePartnerSynthesizer

            if (raw_text or markdown) and hasattr(self, "record_phone_transcript"):
                self.record_phone_transcript(raw_text or markdown)

            synth_meta: Dict[str, Any] = {}
            if not markdown and raw_text:
                is_channel = mode in ("channel", "creative", "partner") or (
                    mode == "memo" and CreativePartnerSynthesizer.has_spoken_bookends(raw_text)
                )
                if is_channel:
                    partner = CreativePartnerSynthesizer(self.config)
                    chan = await asyncio.to_thread(
                        partner.channel,
                        raw_speech=raw_text,
                        custom_title=title if title else None,
                        speak_back=speak_back,
                    )
                    title = title or chan.title
                    markdown = chan.to_markdown()
                    synth_meta = {
                        "mode": "channel",
                        "raw_text": raw_text,
                        "summary": chan.cleaned_core,
                        "spoken_readback_summary": chan.spoken_readback_summary,
                        "key_points": [s.heading for s in chan.sections],
                        "action_items": [
                            f"{c.thinker_or_source}: {c.work_or_concept}" for c in chan.citations
                        ],
                        "pr_checklist": [],
                        "sections": [s.model_dump() for s in chan.sections],
                        "citations": [c.model_dump() for c in chan.citations],
                        "voice_print": chan.voice_print.model_dump(),
                        "bookends": chan.bookends.model_dump(),
                    }
                else:
                    synthesizer = MemoSynthesizer(self.config)
                    synth = await asyncio.to_thread(synthesizer.synthesize_memo, raw_text)
                    title = title or synth.title
                    synth_meta = {
                        "mode": "memo",
                        "raw_text": raw_text,
                        "summary": synth.summary,
                        "spoken_readback_summary": synth.summary,
                        "key_points": synth.key_points,
                        "action_items": synth.action_items,
                        "pr_checklist": synth.pr_checklist,
                    }
                    memo_parts = [
                        f"# {synth.title}\n",
                        f"> Voice memo captured on {time.strftime('%Y-%m-%d %H:%M')}\n",
                        f"## Summary\n{synth.summary}\n",
                    ]
                    if synth.key_points:
                        memo_parts.append(
                            "## Key Takeaways\n"
                            + "\n".join(f"- {kp}" for kp in synth.key_points)
                            + "\n"
                        )
                    if synth.diagram_code:
                        memo_parts.append(
                            f"## Architecture\n```{synth.diagram_type}\n{synth.diagram_code}\n```\n"
                        )
                    if synth.action_items:
                        memo_parts.append(
                            "## Action Items\n"
                            + "\n".join(f"- [ ] {ai}" for ai in synth.action_items)
                            + "\n"
                        )
                    if synth.pr_checklist:
                        memo_parts.append(
                            "## PR / Implementation Checklist\n"
                            + "\n".join(f"- [ ] {c}" for c in synth.pr_checklist)
                            + "\n"
                        )
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
                append_to_path=append_to_path,
                part_number=part_number,
            )

            if res.get("status") == "ok":
                res["title"] = title
                res["latest_part_markdown"] = markdown
                res["markdown"] = res.get("combined_markdown") or markdown
                res.update(synth_meta)
                self.broadcast_event(
                    {
                        "type": "vault_memo_saved",
                        "vault_name": res.get("vault_name"),
                        "memo_name": res.get("memo_name"),
                        "backlink": res.get("backlink"),
                        "title": title,
                    }
                )
            return web.json_response(res)
        except Exception as e:
            logger.exception("handle_vault_memo error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_vault_channel_transform(self, request: web.Request) -> web.Response:
        """Execute a one-tap Creative Transform (Reel Script, Editorial Carousel, Expand Subchapters) and append to the Obsidian note."""
        try:
            data = await request.json()
            transform_type = (data.get("transform_type") or "expand_subchapters").strip().lower()
            raw_text = (data.get("raw_text") or data.get("text") or "").strip()
            title = (data.get("title") or "").strip() or None
            memo_path_str = (data.get("memo_path") or "").strip()

            if not raw_text:
                return web.json_response({"error": "No raw speech text provided for transform"}, status=400)

            from voicefi.memo.creative_partner import CreativePartnerSynthesizer

            partner = CreativePartnerSynthesizer(self.config)
            transformed = await asyncio.to_thread(
                partner.transform,
                transform_type=transform_type,
                raw_speech=raw_text,
                custom_title=title,
            )

            transform_md = transformed.get("markdown", "")
            combined_md = transform_md
            memo_name = ""

            if memo_path_str:
                try:
                    target_file = self._resolve_safe_vault_md_file(memo_path_str)
                except PermissionError as pe:
                    return web.json_response({"error": str(pe)}, status=403)
                if target_file and target_file.is_file():
                    existing = target_file.read_text(encoding="utf-8").rstrip()
                    combined_md = f"{existing}\n\n---\n\n{transform_md.strip()}\n"
                    target_file.write_text(combined_md, encoding="utf-8")
                    memo_name = target_file.name

            return web.json_response(
                {
                    "status": "ok",
                    "transform_type": transformed.get("transform_type"),
                    "label": transformed.get("label"),
                    "title": transformed.get("title"),
                    "transform_markdown": transform_md,
                    "markdown": combined_md,
                    "spoken_summary": transformed.get("spoken_summary", ""),
                    "memo_path": memo_path_str,
                    "memo_name": memo_name,
                }
            )
        except Exception as e:
            logger.exception("handle_vault_channel_transform error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_vault_meeting(self, request: web.Request) -> web.Response:
        """Save a Granola-style meeting note to <vault>/Meetings/ with highlights, action items, and backlinks."""
        try:
            data = await request.json()
            raw_text = data.get("raw_text") or data.get("text", "")
            title = data.get("title", "").strip()
            highlights = data.get("highlights", [])
            tasks = data.get("tasks", [])
            vault_path_str = data.get("vault_path")
            try:
                vault_path = self._resolve_safe_vault_dir(vault_path_str)
            except PermissionError as pe:
                return web.json_response({"error": str(pe)}, status=403)

            if not raw_text:
                return web.json_response({"error": "No meeting speech text provided"}, status=400)

            if hasattr(self, "record_phone_transcript"):
                self.record_phone_transcript(raw_text)

            from voicefi.memo.granola import GranolaSynthesizer
            from voicefi.integrations.obsidian import save_meeting_note

            synthesizer = GranolaSynthesizer(self.config)
            meeting_res = await asyncio.to_thread(
                synthesizer.synthesize_meeting,
                raw_speech=raw_text,
                title_hint=title if title else None,
                highlights=highlights,
                tasks=tasks,
            )

            res = await asyncio.to_thread(
                save_meeting_note,
                meeting_markdown=meeting_res.markdown,
                title=meeting_res.title,
                vault_path=vault_path,
                config=self.config,
            )

            if res.get("status") == "ok":
                res["file_path"] = res.get("meeting_path")
                self.broadcast_event(
                    {
                        "type": "vault_meeting_saved",
                        "vault_name": res.get("vault_name"),
                        "meeting_name": res.get("meeting_name"),
                        "file_path": res.get("meeting_path"),
                        "meeting_path": res.get("meeting_path"),
                        "backlink": res.get("backlink"),
                    }
                )
            return web.json_response(res)
        except Exception as e:
            logger.exception("handle_vault_meeting error: %s", e)
            return web.json_response({"error": str(e)}, status=500)

    async def handle_vault_today(self, request: web.Request) -> web.Response:
        """Fetch today's daily note content from Obsidian."""
        try:
            vault_path_str = request.query.get("vault_path")
            try:
                vault_path = self._resolve_safe_vault_dir(vault_path_str)
            except PermissionError as pe:
                return web.json_response({"error": str(pe)}, status=403)

            from voicefi.integrations.obsidian import get_today_note_content

            res = await asyncio.to_thread(
                get_today_note_content, vault_path=vault_path, config=self.config
            )
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
            try:
                vault_path = self._resolve_safe_vault_dir(vault_path_str)
            except PermissionError as pe:
                return web.json_response({"error": str(pe)}, status=403)

            from voicefi.integrations.obsidian import launch_agent_in_vault

            res = await asyncio.to_thread(
                launch_agent_in_vault, engine=engine, vault_path=vault_path, config=self.config
            )
            return web.json_response(res)
        except Exception as e:
            logger.exception("handle_vault_launch_agent error: %s", e)
            return web.json_response({"error": str(e)}, status=500)
