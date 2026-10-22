"""
Companion WebSocket connection lifecycle, message handling, and client event broadcasting.
"""

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Dict, Any, Optional

from aiohttp import web, WSMsgType

from voicefi.integrations.conversations import (
    record_companion_heartbeat,
    set_mobile_turn_origin,
)
import sys
from voicefi.integrations.injector import send_message_to_agent

logger = logging.getLogger(__name__)


def _resolve_send_message_to_agent(*args, **kwargs):
    server_mod = sys.modules.get("voicefi.companion.server")
    fn = (
        getattr(server_mod, "send_message_to_agent", send_message_to_agent)
        if server_mod
        else send_message_to_agent
    )
    return fn(*args, **kwargs)


class WebSocketHandlersMixin:
    """Mixin containing WebSocket connection handler and client broadcasting methods."""

    def _update_companion_heartbeat(self) -> None:
        has_relay = bool(self.relay_client and getattr(self.relay_client, "has_peer", False))
        total_clients = len(self.active_websockets) + (1 if has_relay else 0)
        total_mobile = len(self.mobile_websockets) + (1 if has_relay else 0)
        record_companion_heartbeat(
            total_clients,
            num_mobile_clients=total_mobile,
            has_mobile=(total_mobile > 0),
        )

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.active_websockets.add(ws)

        # Detect whether connected client is mobile/remote vs local desktop browser
        ua = request.headers.get("User-Agent", "")
        is_mobile_ua = bool(re.search(r"iPhone|iPad|iPod|Android", ua, re.IGNORECASE))
        remote = request.remote or ""
        is_remote_ip = remote not in ("127.0.0.1", "::1", "localhost")
        client_mobile_param = request.query.get("mobile", "").lower() in ("1", "true", "yes")
        is_mobile_client = is_mobile_ua or is_remote_ip or client_mobile_param
        if is_mobile_client:
            self.mobile_websockets.add(ws)

        self._update_companion_heartbeat()

        # Send initial status handshake
        active = self.tracker.get_active_or_latest()
        await ws.send_str(
            json.dumps(
                {
                    "type": "status_update",
                    "active_conversation": {
                        "id": active.id if active else "",
                        "title": active.title if active else "",
                        "status": active.status if active else "idle",
                        "engine": getattr(active, "engine", "antigravity")
                        if active
                        else "antigravity",
                    }
                    if active
                    else None,
                    "audio_routing": getattr(
                        getattr(self.config, "companion", None), "audio_routing", "smart"
                    ),
                }
            )
        )

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                        msg_type = payload.get("type")
                        if msg_type == "user_voice_command":
                            text = payload.get("text", "").strip()
                            cid = payload.get("conv_id")
                            engine = payload.get("engine") or payload.get("target_engine")
                            sender_name = payload.get("sender_name") or "ViFi Companion"
                            title = payload.get("title") or f"Message from {sender_name}"
                            if text:
                                intent_mode = payload.get("intent_mode")
                                if intent_mode in ("speed", "comic") or engine in (
                                    "speed",
                                    "comic",
                                    "gemini_live",
                                ):
                                    try:
                                        from voicefi.integrations.gemini_live import (
                                            GeminiLiveRunner,
                                        )

                                        is_comic = intent_mode == "comic" or engine == "comic"
                                        voice = payload.get("voice") or (
                                            "Puck" if is_comic else "Aoede"
                                        )
                                        mode = "comedy" if is_comic else "assistant"
                                        enable_sfx = is_comic
                                        self.broadcast_event(
                                            {
                                                "type": "agent_thinking",
                                                "engine": "gemini_live",
                                                "intent_mode": intent_mode
                                                or ("comic" if is_comic else "speed"),
                                                "avatar": "🎭" if is_comic else "⚡",
                                                "text": "Puck is roasting..."
                                                if is_comic
                                                else "Gemini Live is thinking...",
                                            }
                                        )
                                        play_audio = bool(
                                            payload.get(
                                                "play_audio_on_server",
                                                payload.get("play_audio", False),
                                            )
                                        )
                                        runner = GeminiLiveRunner(
                                            voice=voice,
                                            mode=mode,
                                            enable_sfx=enable_sfx,
                                            play_audio=play_audio,
                                        )
                                        res = await runner.run_prompt(text)
                                        self.broadcast_event(
                                            {
                                                "type": "agent_speaking_started",
                                                "engine": "gemini_live",
                                                "intent_mode": intent_mode
                                                or ("comic" if is_comic else "speed"),
                                                "text": res.get("transcript", ""),
                                                "audio_data_uri": res.get("audio_data_uri"),
                                                "triggered_sfx": res.get("triggered_sfx", []),
                                                "avatar": "🎭" if is_comic else "⚡",
                                            }
                                        )
                                    except Exception as e:
                                        logger.error(
                                            "Error running Gemini Live via WS: %s", e, exc_info=True
                                        )
                                    continue

                                if engine == "obsidian" or cid == "obsidian":
                                    from voicefi.integrations.obsidian import (
                                        append_quick_capture_to_vault,
                                    )

                                    res = append_quick_capture_to_vault(
                                        text=text, config=self.config
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
                                else:
                                    lower_text = text.lower().strip()
                                    has_gemma_intent = bool(
                                        re.search(
                                            r"\b(?:hey|ask|tell|all\s+right|alright|okay|so|can\s+you\s+ask|could\s+you\s+ask|send\s+to|talk\s+to|switch\s+to|have|message)?\s*(?:gemma|local\s+gemma|local\s+model|local\s+intelligence|ollama|qwen)\b",
                                            lower_text,
                                        )
                                    )
                                    is_gemma = (
                                        engine in ("gemma", "local", "ollama", "gemma4-2b", "gemma4-26b", "auto")
                                        or ":" in str(engine or "")
                                        or (cid and "gemma" in str(cid).lower())
                                        or has_gemma_intent
                                    )
                                    if is_gemma:
                                        req_model = payload.get("model") or (
                                            engine
                                            if engine not in ("gemma", "local", "ollama")
                                            else None
                                        )
                                        await self.execute_local_voice_turn(
                                            prompt=text,
                                            conv_id=cid,
                                            model=req_model,
                                            mode=payload.get("local_mode") or payload.get("mode"),
                                            origin=payload.get("origin", "mobile"),
                                            title=title,
                                        )
                                        continue

                                    if cid and (
                                        cid.startswith("claude_") or "claude" in cid.lower()
                                    ):
                                        engine = "claude"
                                    elif cid and (
                                        cid.startswith("codex_") or "codex" in cid.lower()
                                    ):
                                        engine = "codex"

                                    has_claude_intent = bool(
                                        re.search(
                                            r"\b(?:hey|ask|tell|all\s+right|alright|okay|so|can\s+you\s+ask|could\s+you\s+ask|send\s+to|talk\s+to|switch\s+to|have|message)?\s*claude\b",
                                            lower_text,
                                        )
                                    )
                                    has_codex_intent = bool(
                                        re.search(
                                            r"\b(?:hey|ask|tell|all\s+right|alright|okay|so|can\s+you\s+ask|could\s+you\s+ask|send\s+to|talk\s+to|switch\s+to|have|message)?\s*codex\b",
                                            lower_text,
                                        )
                                    )
                                    if has_codex_intent:
                                        engine = "codex"
                                        if (
                                            cid
                                            and not cid.startswith("codex_")
                                            and "codex" not in cid.lower()
                                        ):
                                            cid = None
                                    elif has_claude_intent:
                                        engine = "claude"
                                        if (
                                            cid
                                            and not cid.startswith("claude_")
                                            and "claude" not in cid.lower()
                                        ):
                                            cid = None

                                    set_mobile_turn_origin(cid)
                                    cwd_arg = (
                                        payload.get("cwd")
                                        or payload.get("workspace_path")
                                        or payload.get("vault_path")
                                    )
                                    if not cwd_arg and engine in (
                                        "claude_obsidian",
                                        "obsidian_claude",
                                    ):
                                        from voicefi.integrations.obsidian import get_primary_vault

                                        cwd_arg = get_primary_vault(self.config)
                                        engine = "claude"

                                    kwargs = {
                                        "conv_id": cid,
                                        "text": text,
                                        "sender_name": sender_name,
                                        "title": title,
                                        "use_headless": True,
                                    }
                                    if engine:
                                        kwargs["target_engine"] = engine
                                    if cwd_arg:
                                        kwargs["cwd"] = Path(cwd_arg)
                                    res = await asyncio.to_thread(
                                        _resolve_send_message_to_agent, **kwargs
                                    )
                                    target_cid = getattr(res, "target_conv_id", cid) or cid
                                    self.broadcast_event(
                                        {
                                            "type": "user_command_injected",
                                            "conv_id": target_cid or cid or "active",
                                            "text": text,
                                            "delivered": True,
                                            "engine": engine or getattr(res, "engine", "claude"),
                                        }
                                    )
                        elif msg_type == "vault_capture":
                            text = payload.get("text", "").strip()
                            if text:
                                from voicefi.integrations.obsidian import (
                                    append_quick_capture_to_vault,
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
                        elif msg_type == "vault_memo":
                            raw_text = payload.get("raw_text") or payload.get("text", "")
                            markdown = payload.get("markdown", "").strip()
                            title = payload.get("title", "").strip()
                            if raw_text or markdown:
                                from voicefi.integrations.obsidian import save_memo_to_vault
                                from voicefi.memo import MemoSynthesizer

                                if not markdown and raw_text:
                                    synthesizer = MemoSynthesizer(self.config)
                                    synth = await asyncio.to_thread(
                                        synthesizer.synthesize_memo, raw_text
                                    )
                                    title = title or synth.title
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
                                res = await asyncio.to_thread(
                                    save_memo_to_vault,
                                    memo_markdown=markdown,
                                    title=title,
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
                        elif msg_type == "ambient_start":
                            source = payload.get("source", "mic")
                            self.start_ambient(source=source)
                        elif msg_type == "ambient_stop":
                            self.stop_ambient()
                        elif msg_type == "ambient_task_action":
                            tid = payload.get("task_id")
                            action = payload.get("action", "dispatch")
                            if self._ambient_dispatcher and tid:
                                if action == "dismiss":
                                    self._ambient_dispatcher.dismiss_task(tid)
                                    self.broadcast_event(
                                        {
                                            "type": "ambient_task_updated",
                                            "task_id": tid,
                                            "status": "dismissed",
                                            "timestamp": time.time(),
                                        }
                                    )
                                elif action == "dispatch":
                                    tasks = {
                                        t.id: t for t in self._ambient_dispatcher.get_staged_tasks()
                                    }
                                    task = tasks.get(tid)
                                    if task:
                                        set_mobile_turn_origin(None)
                                        prompt = f"[{task.category.value}] {task.action_prompt}"
                                        delivered = bool(
                                            _resolve_send_message_to_agent(
                                                conv_id=None, text=prompt
                                            )
                                        )
                                        self._ambient_dispatcher.complete_task(
                                            tid, result_summary="Dispatched to agent"
                                        )
                                        self.broadcast_event(
                                            {
                                                "type": "ambient_task_updated",
                                                "task_id": tid,
                                                "status": "completed",
                                                "delivered": delivered,
                                                "timestamp": time.time(),
                                            }
                                        )
                        elif msg_type == "memo_start":
                            dur = float(
                                payload.get("duration", self.config.memo.default_duration_seconds)
                            )
                            ttl = payload.get("title", "Voice Memo")
                            self.start_memo_session(target_duration=dur, title=ttl)
                        elif msg_type == "memo_extend":
                            secs = float(payload.get("seconds", 60.0))
                            self.extend_memo(secs)
                        elif msg_type == "memo_pause":
                            self.pause_memo()
                        elif msg_type == "memo_stop":
                            self.stop_memo()
                        elif msg_type == "stop":
                            now = time.time()
                            last_stop = getattr(self, "_last_stop_handle_time", 0.0)
                            if (now - last_stop) >= 0.5:
                                self._last_stop_handle_time = now
                                from voicefi.tts.base import stop_all_speech

                                stop_all_speech()
                                if (
                                    hasattr(self, "_active_mac_recorder")
                                    and self._active_mac_recorder
                                ):
                                    try:
                                        self._active_mac_recorder.stop()
                                    except Exception:
                                        pass
                                self.broadcast_event(
                                    {
                                        "type": "speech_stopped",
                                        "timestamp": time.time(),
                                    }
                                )
                        elif msg_type == "ping":
                            if payload.get("is_mobile") is True:
                                self.mobile_websockets.add(ws)
                            elif (
                                payload.get("is_mobile") is False
                                and not is_remote_ip
                                and not is_mobile_ua
                            ):
                                self.mobile_websockets.discard(ws)
                            self._update_companion_heartbeat()
                            await ws.send_str(json.dumps({"type": "pong"}))
                    except Exception as e:
                        print(f"[Companion WS] Error processing message: {e}")
                elif msg.type == WSMsgType.ERROR:
                    print(f"[Companion WS] Connection error: {ws.exception()}")
        finally:
            self.active_websockets.discard(ws)
            self.mobile_websockets.discard(ws)
            self._update_companion_heartbeat()

        return ws

    def broadcast_event(self, event_data: Dict[str, Any]):
        """Broadcast event to all connected mobile clients."""
        loop = self.loop
        try:
            running = asyncio.get_running_loop()
            if running and running.is_running():
                loop = running
        except RuntimeError:
            pass

        if not loop or loop.is_closed():
            return

        def _json_safe(o):
            if hasattr(o, "to_dict") and callable(o.to_dict):
                return o.to_dict()
            if hasattr(o, "success"):
                return bool(o.success)
            return str(o)

        try:
            msg = json.dumps(event_data, default=_json_safe)
        except Exception as e:
            logger.debug(f"Failed to serialize broadcast event: {e}")
            return

        is_same_loop = False
        try:
            if asyncio.get_running_loop() is loop:
                is_same_loop = True
        except RuntimeError:
            pass

        if self.active_websockets:
            for ws in list(self.active_websockets):
                if not ws.closed:
                    try:
                        if is_same_loop:
                            loop.create_task(ws.send_str(msg))
                        else:
                            asyncio.run_coroutine_threadsafe(ws.send_str(msg), loop)
                    except Exception as e:
                        logger.debug(f"Failed to send to local websocket: {e}")
        if self.relay_client and self.relay_client.is_running:
            try:
                if is_same_loop:
                    loop.create_task(self.relay_client.broadcast(event_data))
                else:
                    asyncio.run_coroutine_threadsafe(self.relay_client.broadcast(event_data), loop)
            except Exception as e:
                logger.debug(f"Failed to broadcast to relay client: {e}")

    def broadcast_turn_completion(
        self,
        summary: str,
        conv_id: str,
        agent_role: str = "antigravity",
        full_response: str = "",
        origin: str = "desktop",
        delivered_via: str = "otherwise",
        spoken_on_mac: bool = False,
        step_index: Optional[int] = None,
    ):
        """Called when an Antigravity or Claude agent completes a turn."""
        now = time.time()
        # Clean up old turn signatures older than 45s
        self._recent_broadcast_turns = {
            sig: ts for sig, ts in self._recent_broadcast_turns.items() if now - ts < 45.0
        }

        # Deduplication Guard: Check signature across conv_id + normalized summary text
        clean_summ = (summary or "").strip()
        norm_key = re.sub(r"[^a-zA-Z0-9]", "", clean_summ.lower())[:60]
        turn_sig = (
            f"{conv_id}:{norm_key}:step_{step_index}"
            if step_index is not None
            else f"{conv_id}:{norm_key}"
        )
        generic_sig = f"{conv_id}:{norm_key}"

        if (
            turn_sig in self._recent_broadcast_turns
            and (now - self._recent_broadcast_turns[turn_sig]) < 30.0
        ):
            logger.info(
                f"[CompanionServer] 🛡️ Suppressing duplicate turn completion broadcast ({now - self._recent_broadcast_turns[turn_sig]:.2f}s): {turn_sig}"
            )
            return

        if (
            step_index is None
            and generic_sig in self._recent_broadcast_turns
            and (now - self._recent_broadcast_turns[generic_sig]) < 3.0
        ):
            logger.info(
                f"[CompanionServer] 🛡️ Suppressing duplicate unindexed turn completion broadcast: {generic_sig}"
            )
            return

        self._recent_broadcast_turns[turn_sig] = now
        self._recent_broadcast_turns[generic_sig] = now

        if summary:
            from voicefi.audio.echo_canceller import record_agent_spoken

            record_agent_spoken(summary)

        # Resolve configured voice for agent/conversation
        resolved_voice = (
            "Christopher"
            if "antigravity" in str(agent_role).lower()
            else (
                "Andrew"
                if "gemma" in str(agent_role).lower()
                else ("Emma" if "codex" in str(agent_role).lower() else "Viv")
            )
        )
        try:
            fresh_cfg = self.config
            try:
                from voicefi.config import load_config

                fresh_cfg = load_config()
            except Exception:
                pass
            global_voice = getattr(getattr(fresh_cfg, "tts", None), "voice", "")
            if global_voice and ("continental" in global_voice.lower() or "walken" in global_voice.lower() or "acting" in str(getattr(getattr(fresh_cfg, "tts", None), "provider", "")).lower()):
                resolved_voice = global_voice
            else:
                _, v_id, _ = fresh_cfg.resolve_voice(agent_role)
                if v_id:
                    resolved_voice = v_id
        except Exception:
            pass

        # Broadcast visual start event immediately (0ms) before TTS synthesis so UI transitions without delay
        self.broadcast_event(
            {
                "type": "agent_speaking_started",
                "text": summary,
                "conv_id": conv_id,
                "agent_role": agent_role,
                "voice": resolved_voice,
            }
        )

        audio_data_uri = None
        try:
            cache_m4a = Path("/tmp/voicefi_last_spoken_turn.m4a")
            if spoken_on_mac and cache_m4a.is_file() and (now - cache_m4a.stat().st_mtime) < 45.0:
                import base64
                b64 = base64.b64encode(cache_m4a.read_bytes()).decode("ascii")
                audio_data_uri = f"data:audio/mp4;base64,{b64}"
            elif summary and summary.strip():
                import base64
                import tempfile
                from voicefi.companion.handlers.audio import (
                    _resolve_tts_engine,
                    get_cached_tts_audio,
                    set_cached_tts_audio,
                )
                cache_voice_key = str(resolved_voice or agent_role or "default")
                cached = get_cached_tts_audio(cache_voice_key, summary)
                if cached:
                    b64 = base64.b64encode(cached[0]).decode("ascii")
                    audio_data_uri = f"data:{cached[1]};base64,{b64}"
                else:
                    tts_inst = _resolve_tts_engine(
                        fresh_cfg, agent_name=agent_role, voice_override=resolved_voice
                    )
                    temp_mp3 = Path(tempfile.gettempdir()) / f"vifi_turn_{int(now*1000)}.mp3"
                    if hasattr(tts_inst, "speak_to_file") and tts_inst.speak_to_file(summary, temp_mp3):
                        if temp_mp3.is_file() and temp_mp3.stat().st_size > 0:
                            raw_bytes = temp_mp3.read_bytes()
                            set_cached_tts_audio(cache_voice_key, summary, raw_bytes, "audio/mpeg")
                            b64 = base64.b64encode(raw_bytes).decode("ascii")
                            audio_data_uri = f"data:audio/mpeg;base64,{b64}"
                            temp_mp3.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"[CompanionServer] Failed to generate audio_data_uri: {e}")

        self.broadcast_event(
            {
                "type": "agent_turn_completed",
                "summary": summary,
                "full_response": full_response or summary,
                "conv_id": conv_id,
                "step_index": step_index,
                "agent_role": agent_role,
                "voice": resolved_voice,
                "audio_data_uri": audio_data_uri,
                "origin": origin,
                "delivered_via": delivered_via,
                "delivered_via_hook": (delivered_via == "hook"),
                "spoken_on_mac": spoken_on_mac,
                "timestamp": now,
            }
        )

    broadcast_agent_turn_completed = broadcast_turn_completion

