"""
Companion route handlers for Gemini 3.8 Live dialogue, demo studio, and real-time WebSockets.
"""

import asyncio
import collections
import json
import logging
import time
from pathlib import Path
from typing import Optional, Any, Set
from aiohttp import web, WSMsgType
import numpy as np

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class LiveHandlersMixin:
    """Mixin providing real-time Gemini 3.8 Live studio and WebSocket handlers."""

    async def handle_live(self, request: web.Request) -> web.Response:
        """
        Execute real-time Gemini 3.8 Live dialogue or comedy session.
        POST /api/live {"prompt": "...", "voice": "Puck", "mode": "comedy", "play_audio": true}
        """
        try:
            try:
                data = await request.json()
            except Exception:
                return web.json_response({"error": "Invalid JSON", "status": "error"}, status=400)

            prompt = (data.get("prompt") or data.get("text") or "").strip()
            if not prompt:
                return web.json_response({"error": "Missing prompt", "status": "error"}, status=400)

            voice = data.get("voice", "Puck")
            mode = data.get("mode", "comedy")
            use_thinking = bool(data.get("use_thinking", False))
            thinking_level = data.get("thinking_level", "LOW")
            enable_sfx = bool(data.get("enable_sfx", True))
            play_audio = bool(data.get("play_audio_on_server", data.get("play_audio", False)))

            from voicefi.integrations.gemini_live import GeminiLiveRunner

            intent_mode = data.get("intent_mode") or ("comic" if mode == "comedy" else "speed")
            self.broadcast_event(
                {
                    "type": "agent_thinking",
                    "engine": "gemini_live",
                    "intent_mode": intent_mode,
                    "avatar": "🎭" if intent_mode == "comic" else "⚡",
                    "text": "Puck is roasting..."
                    if intent_mode == "comic"
                    else "Gemini Live is thinking...",
                }
            )

            runner = GeminiLiveRunner(
                voice=voice,
                mode=mode,
                use_thinking=use_thinking,
                thinking_level=thinking_level,
                enable_sfx=enable_sfx,
                play_audio=play_audio,
            )

            result = await runner.run_prompt(prompt)

            self.broadcast_event(
                {
                    "type": "agent_speaking_started",
                    "engine": "gemini_live",
                    "intent_mode": intent_mode,
                    "text": result.get("transcript", ""),
                    "audio_data_uri": result.get("audio_data_uri"),
                    "triggered_sfx": result.get("triggered_sfx", []),
                    "avatar": "🎭" if intent_mode == "comic" else "⚡",
                }
            )

            return web.json_response({"status": "ok", "result": result})
        except Exception as e:
            logger.error("Error in handle_live: %s", e, exc_info=True)
            return web.json_response({"error": str(e), "status": "error"}, status=500)

    async def handle_live_demo(self, request: web.Request) -> web.Response:
        """Serve the interactive Gemini 3.8 Live showcase and demo studio page."""
        demo_file = STATIC_DIR / "live_demo.html"
        if not demo_file.is_file():
            return web.Response(text="Live demo page not found", status=404)
        return web.FileResponse(demo_file)

    async def handle_live_providers(self, request: web.Request) -> web.Response:
        """
        Return configured status and catalogs for all live voice providers (Gemini, OpenAI, Grok).
        GET /api/live/providers
        """
        from voicefi.config import (
            resolve_gemini_api_key,
            resolve_openai_api_key,
            resolve_xai_api_key,
            VALID_GEMINI_LIVE_VOICES,
            VALID_OPENAI_LIVE_VOICES,
            VALID_OPENAI_LIVE_MODELS,
            VALID_GROK_LIVE_VOICES,
            VALID_GROK_LIVE_MODELS,
            VALID_PERSONAPLEX_LIVE_VOICES,
            VALID_PERSONAPLEX_LIVE_MODELS,
        )

        cfg = getattr(self, "config", None)
        return web.json_response(
            {
                "status": "ok",
                "providers": {
                    "gemini": {
                        "configured": bool(resolve_gemini_api_key(cfg)),
                        "env_var": "GEMINI_API_KEY",
                        "voices": sorted(list(VALID_GEMINI_LIVE_VOICES)),
                    },
                    "openai": {
                        "configured": bool(resolve_openai_api_key(cfg)),
                        "env_var": "OPENAI_API_KEY",
                        "models": list(VALID_OPENAI_LIVE_MODELS),
                        "voices": list(VALID_OPENAI_LIVE_VOICES),
                    },
                    "grok": {
                        "configured": bool(resolve_xai_api_key(cfg)),
                        "env_var": "XAI_API_KEY",
                        "models": list(VALID_GROK_LIVE_MODELS),
                        "voices": list(VALID_GROK_LIVE_VOICES),
                    },
                    "personaplex": {
                        "configured": True,
                        "local": True,
                        "models": list(VALID_PERSONAPLEX_LIVE_MODELS),
                        "voices": sorted(list(VALID_PERSONAPLEX_LIVE_VOICES)),
                    },
                },
            }
        )

    async def handle_live_key(self, request: web.Request) -> web.Response:
        """
        Save an API key for a live voice provider (gemini, openai, grok) to config and runtime env.
        POST /api/live/key {"provider": "openai", "api_key": "sk-..."}
        """
        if hasattr(self, "_is_loopback_request") and not self._is_loopback_request(request):
            return web.json_response(
                {"status": "error", "error": "API key configuration is restricted to local loopback."},
                status=403,
            )
        import os
        from voicefi.config import (
            load_config,
            save_config,
            resolve_gemini_api_key,
            resolve_openai_api_key,
            resolve_xai_api_key,
        )

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"status": "error", "error": "Invalid JSON"}, status=400)

        provider = str(data.get("provider", "")).strip().lower()
        api_key = str(data.get("api_key", "")).strip()

        if provider == "xai":
            provider = "grok"

        if provider not in ("gemini", "openai", "grok") or not api_key:
            return web.json_response(
                {"status": "error", "error": "Both valid provider and api_key are required."},
                status=400,
            )

        cfg = getattr(self, "config", None) or load_config()
        if provider == "openai":
            cfg.openai.api_key = api_key
            os.environ["OPENAI_API_KEY"] = api_key
        elif provider == "grok":
            cfg.xai.api_key = api_key
            os.environ["XAI_API_KEY"] = api_key
        elif provider == "gemini":
            cfg.gemini.api_key = api_key
            os.environ["GEMINI_API_KEY"] = api_key

        self.config = cfg
        try:
            save_config(cfg)
        except Exception as e:
            logger.warning("Could not persist config to disk in handle_live_key: %s", e)

        return web.json_response(
            {
                "status": "ok",
                "provider": provider,
                "configured": True,
                "providers": {
                    "gemini": {"configured": bool(resolve_gemini_api_key(cfg))},
                    "openai": {"configured": bool(resolve_openai_api_key(cfg))},
                    "grok": {"configured": bool(resolve_xai_api_key(cfg))},
                },
            }
        )

    async def handle_live_ws(self, request: web.Request) -> web.WebSocketResponse:
        """
        Bidirectional WebSocket proxy connecting client browser Web Audio to Gemini Live.
        Hardened with dual-locking (client & upstream), guaranteed FunctionResponse on tool errors,
        epoch-based stale tool invalidation, and WebSocket heartbeats.
        """
        from voicefi.config import resolve_gemini_api_key, VALID_GEMINI_LIVE_VOICES
        from voicefi.integrations.live_tools import get_live_tools, execute_live_tool

        api_key = resolve_gemini_api_key(self.config)
        # Enable 15s heartbeat to prevent half-open socket leaks on mobile/Wi-Fi drops
        ws = web.WebSocketResponse(heartbeat=15.0)
        await ws.prepare(request)

        provider = request.query.get("provider", "").lower()
        req_model = request.query.get("model", "")
        if not provider:
            if req_model:
                if "gpt" in req_model.lower():
                    provider = "openai"
                elif "grok" in req_model.lower():
                    provider = "grok"
                elif "personaplex" in req_model.lower() or "moshi" in req_model.lower():
                    provider = "personaplex"
                else:
                    provider = "gemini"
            else:
                provider = "gemini"

        if provider in ("openai", "grok", "xai", "personaplex", "moshi"):
            return await self._handle_realtime_ws(request, ws, provider=provider)

        if not api_key:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "Gemini API key not found. Please set GEMINI_API_KEY or configure in ~/.voicefi/config.yaml",
                }
            )
            await ws.close()
            return ws

        voice = request.query.get("voice", "Puck")
        if voice not in VALID_GEMINI_LIVE_VOICES:
            voice = "Puck"
        use_thinking = request.query.get("thinking", "0").lower() in ("1", "true", "yes")
        thinking_level = request.query.get("thinking_level", "LOW").upper()
        enable_tools = request.query.get("tools", "1").lower() in ("1", "true", "yes")
        req_model = request.query.get("model", "gemini-2.5-flash-native-audio-latest")
        model = req_model

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "google-genai package is missing on the server.",
                }
            )
            await ws.close()
            return ws

        client = genai.Client(api_key=api_key)
        tools = get_live_tools() if enable_tools else None

        thinking_cfg = None
        if use_thinking:
            level_enum = getattr(types, "ThinkingLevel", None)
            t_level = getattr(level_enum, thinking_level, "LOW") if level_enum else thinking_level
            thinking_cfg = types.ThinkingConfig(thinking_level=t_level)

        persona = request.query.get("persona", "default").lower()
        hold_space = request.query.get("hold_space", "0").lower() in ("1", "true", "yes") or persona in (
            "listen",
            "hold_space",
            "listening",
        )
        if persona in ("brok", "roast"):
            from voicefi.live_studio import BROK_SYSTEM_INSTRUCTION

            system_instruction = BROK_SYSTEM_INSTRUCTION
        elif hold_space:
            from voicefi.live_studio import HOLD_SPACE_SYSTEM_INSTRUCTION

            system_instruction = HOLD_SPACE_SYSTEM_INSTRUCTION
        else:
            from voicefi.live_studio import DEFAULT_SYSTEM_INSTRUCTION

            system_instruction = DEFAULT_SYSTEM_INSTRUCTION

        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part.from_text(text=system_instruction)]),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
            thinking_config=thinking_cfg,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            enable_affective_dialog=True,
            tools=tools,
        )

        is_alive = True
        session_send_lock = asyncio.Lock()
        client_ws_lock = asyncio.Lock()
        active_tool_tasks: Set = set()
        turn_epoch = 0

        # Mark live session active to prevent background desktop agent audio collisions
        live_lockfile = Path("/tmp/voicefi_live_session_active")
        try:
            live_lockfile.write_text(str(time.time()), encoding="utf-8")
        except Exception:
            pass

        async def safe_client_send_json(payload: dict):
            """Thread-safe and coroutine-safe JSON dispatch to browser WebSocket."""
            if not is_alive or ws.closed:
                return
            async with client_ws_lock:
                try:
                    await ws.send_json(payload)
                except Exception as err:
                    logger.debug("Client ws send_json error: %s", err)

        async def safe_client_send_bytes(data: bytes):
            """Thread-safe and coroutine-safe PCM audio dispatch to browser WebSocket."""
            if not is_alive or ws.closed:
                return
            async with client_ws_lock:
                try:
                    await ws.send_bytes(data)
                except Exception as err:
                    logger.debug("Client ws send_bytes error: %s", err)

        async def execute_and_reply_tool(session, call, captured_epoch: int):
            name = call.name
            args = dict(call.args) if call.args else {}
            await safe_client_send_json(
                {
                    "type": "tool_start",
                    "name": name,
                    "id": call.id,
                    "args": args,
                }
            )
            t0 = time.time()
            res = None
            has_error = False

            try:
                # Strict 6.0s timeout to avoid freezing live conversations
                res = await asyncio.wait_for(execute_live_tool(name, args), timeout=6.0)
            except asyncio.TimeoutError:
                has_error = True
                res = f"Error: Tool '{name}' timed out after 6.0 seconds."
            except Exception as ex:
                has_error = True
                res = f"Error executing tool '{name}': {ex}"

            duration_ms = int((time.time() - t0) * 1000)

            # If user barged in while tool was executing, inform Gemini cleanly rather than dropping response
            is_stale = captured_epoch != turn_epoch
            if is_stale:
                logger.info(
                    "Tool result for %s was interrupted/superseded (epoch %d -> %d)",
                    name,
                    captured_epoch,
                    turn_epoch,
                )
                response_payload = {
                    "result": "Action cancelled or superseded by developer interruption."
                }
            else:
                response_payload = {"result": res} if not has_error else {"error": res}

            # ALWAYS return FunctionResponse to Gemini Live (prevents conversational deadlock & 1007 protocol errors)
            try:
                async with session_send_lock:
                    if is_alive:
                        await session.send_tool_response(
                            function_responses=[
                                types.FunctionResponse(
                                    name=name,
                                    id=call.id,
                                    response=response_payload,
                                )
                            ]
                        )
            except Exception as send_err:
                logger.error("Failed to send FunctionResponse to Gemini for %s: %s", name, send_err)

            if has_error:
                await safe_client_send_json(
                    {
                        "type": "tool_error",
                        "name": name,
                        "id": call.id,
                        "error": res,
                    }
                )
            else:
                await safe_client_send_json(
                    {
                        "type": "tool_done",
                        "name": name,
                        "id": call.id,
                        "result": res,
                        "duration_ms": duration_ms,
                    }
                )

        needs_stt_bridge = "3.8" in model or "3.1" in model
        stt_engine = None
        if needs_stt_bridge:
            try:
                from voicefi.stt import get_stt_engine

                stt_engine = get_stt_engine(self.config)
            except Exception as e:
                logger.warning("Failed to initialize live STT bridge engine: %s", e)

        from voicefi.audio.live_stream import calculate_rms

        speech_buffer: list[bytes] = []
        preroll_buffer = collections.deque(maxlen=35)  # 700ms @ 20ms chunks (preserves soft initial consonants)
        is_user_speaking = False
        silence_count = 0

        try:
            async with client.aio.live.connect(model=model, config=live_config) as session:
                await safe_client_send_json(
                    {
                        "type": "connected",
                        "provider": "gemini",
                        "model": model,
                        "voice": voice,
                        "thinking": use_thinking,
                        "tools": enable_tools,
                        "hold_space": hold_space,
                    }
                )

                async def from_gemini():
                    nonlocal turn_epoch
                    try:
                        while is_alive and not ws.closed:
                            try:
                                response = await session._receive()
                            except Exception as recv_err:
                                if is_alive and not ws.closed:
                                    logger.debug("Live session receive end: %s", recv_err)
                                break

                            if not is_alive or ws.closed:
                                break

                            # Tools
                            if response.tool_call:
                                for call in response.tool_call.function_calls:
                                    t = asyncio.create_task(
                                        execute_and_reply_tool(session, call, turn_epoch)
                                    )
                                    active_tool_tasks.add(t)
                                    t.add_done_callback(active_tool_tasks.discard)

                            # Server content
                            if response.server_content:
                                sc = response.server_content
                                if getattr(sc, "interrupted", False):
                                    turn_epoch += 1
                                    await safe_client_send_json({"type": "interrupted"})

                                it = getattr(sc, "input_transcription", None)
                                if it and it.text:
                                    await safe_client_send_json(
                                        {"type": "user_transcript", "text": it.text}
                                    )

                                ot = getattr(sc, "output_transcription", None)
                                if ot and ot.text:
                                    await safe_client_send_json(
                                        {"type": "model_transcript", "text": ot.text}
                                    )

                                # Forward thinking chunks and streaming audio
                                if sc.model_turn:
                                    for part in sc.model_turn.parts:
                                        if getattr(part, "thought", False) and part.text:
                                            await safe_client_send_json(
                                                {"type": "model_thinking", "text": part.text}
                                            )
                                        elif part.inline_data and part.inline_data.data:
                                            await safe_client_send_bytes(part.inline_data.data)

                                if getattr(sc, "turn_complete", False):
                                    turn_epoch += 1
                                    await safe_client_send_json({"type": "turn_complete"})
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        if is_alive and not ws.closed:
                            logger.error("Gemini live receive error: %s", e)

                gemini_task = asyncio.create_task(from_gemini())

                try:
                    async for msg in ws:
                        if msg.type == WSMsgType.BINARY:
                            chunk = msg.data
                            if not needs_stt_bridge:
                                # Gate audio streaming while tool call is awaiting FunctionResponse (prevents 1007 CONTENT_TYPE_AUDIO error)
                                if not active_tool_tasks:
                                    async with session_send_lock:
                                        await session.send_realtime_input(
                                            media=types.Blob(
                                                data=chunk,
                                                mime_type="audio/pcm;rate=16000",
                                            )
                                        )
                            else:
                                # Models lacking server-side audio VAD (e.g. 3.8 preview):
                                # Run real-time RMS VAD and local fast STT bridge
                                energy = calculate_rms(chunk)
                                speech_thresh = 0.007
                                if energy > speech_thresh:
                                    if not is_user_speaking:
                                        is_user_speaking = True
                                        turn_epoch += 1
                                        speech_buffer.extend(preroll_buffer)
                                        async with session_send_lock:
                                            try:
                                                await session.send_realtime_input(
                                                    activity_start=types.ActivityStart()
                                                )
                                            except Exception:
                                                pass
                                        await safe_client_send_json({"type": "interrupted"})
                                    speech_buffer.append(chunk)
                                    silence_count = 0
                                else:
                                    preroll_buffer.append(chunk)
                                    if is_user_speaking:
                                        speech_buffer.append(chunk)
                                        silence_count += 1
                                        # 65 chunks * 20ms = 1.3s pause allowance for standard speech;
                                        # 250 chunks * 20ms = 5.0s contemplative pause allowance in Hold Space (True Listening) mode
                                        pause_allowance_chunks = 250 if hold_space else 65
                                        max_buffer_chunks = 1500 if hold_space else 600
                                        if (
                                            silence_count >= pause_allowance_chunks
                                            or len(speech_buffer) >= max_buffer_chunks
                                        ):
                                            is_user_speaking = False
                                            audio_bytes = b"".join(speech_buffer)
                                            speech_buffer.clear()
                                            if stt_engine and len(audio_bytes) >= 9600:
                                                try:
                                                    samples = (
                                                        np.frombuffer(
                                                            audio_bytes, dtype=np.int16
                                                        ).astype(np.float32)
                                                        / 32768.0
                                                    )
                                                    text = await asyncio.to_thread(
                                                        stt_engine.transcribe, samples
                                                    )
                                                    text = text.strip() if text else ""
                                                    if text and is_alive:
                                                        logger.info(
                                                            "Live STT bridge transcribed: %s", text
                                                        )
                                                        await safe_client_send_json(
                                                            {
                                                                "type": "user_transcript",
                                                                "text": text,
                                                            }
                                                        )
                                                        async with session_send_lock:
                                                            await session.send_realtime_input(
                                                                text=text
                                                            )
                                                except Exception as stt_err:
                                                    logger.debug(
                                                        "Live STT bridge error: %s", stt_err
                                                    )
                        elif msg.type == WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                                ptype = payload.get("type")
                                if ptype == "barge_in":
                                    turn_epoch += 1
                                    async with session_send_lock:
                                        await session.send_realtime_input(
                                            activity_start=types.ActivityStart()
                                        )
                                elif ptype == "set_hold_space":
                                    hold_space = bool(payload.get("enabled", True))
                                    await safe_client_send_json(
                                        {
                                            "type": "hold_space_updated",
                                            "hold_space": hold_space,
                                        }
                                    )
                                elif ptype == "text":
                                    text_msg = payload.get("text", "")
                                    if text_msg:
                                        async with session_send_lock:
                                            await session.send_realtime_input(text=text_msg)
                            except Exception as ex:
                                logger.debug("Error processing client text msg: %s", ex)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.ERROR):
                            break
                finally:
                    is_alive = False
                    gemini_task.cancel()
                    for task in list(active_tool_tasks):
                        task.cancel()
                    active_tool_tasks.clear()

        except Exception as e:
            logger.error("Error in live WebSocket proxy: %s", e)
            await safe_client_send_json({"type": "error", "message": str(e)})
        finally:
            try:
                live_lockfile.unlink(missing_ok=True)
            except Exception:
                pass

        return ws

    async def _handle_realtime_ws(
        self, request: web.Request, ws: web.WebSocketResponse, provider: str
    ) -> web.WebSocketResponse:
        """
        Proxy browser Web Audio to OpenAI Realtime, xAI Grok Live Voice, or local NVIDIA PersonaPlex APIs.
        """
        from voicefi.config import resolve_openai_api_key, resolve_xai_api_key
        from voicefi.integrations.realtime_live import (
            OpenAILiveAdapter,
            GrokLiveAdapter,
            PersonaPlexLiveAdapter,
        )
        from voicefi.audio.live_stream import resample_pcm16

        prov_lower = provider.lower()
        is_openai = prov_lower == "openai"
        is_personaplex = prov_lower in ("personaplex", "moshi")

        if is_personaplex:
            api_key = ""
        else:
            api_key = (
                resolve_openai_api_key(self.config)
                if is_openai
                else resolve_xai_api_key(self.config)
            )
            if not api_key:
                prov_name = "OpenAI" if is_openai else "xAI Grok"
                env_var = "OPENAI_API_KEY" if is_openai else "XAI_API_KEY"
                await ws.send_json(
                    {
                        "type": "error",
                        "message": f"{prov_name} API key not found. Please set {env_var} or configure in ~/.voicefi/config.yaml",
                    }
                )
                await ws.close()
                return ws

        if is_personaplex:
            model = request.query.get("model") or "personaplex-7b-mlx-4bit"
            voice = request.query.get("voice") or "NATF2"
        else:
            model = request.query.get("model") or (
                "gpt-live-1.1" if is_openai else "grok-voice-latest"
            )
            voice = request.query.get("voice") or ("bubbie" if is_openai else "eve")
        persona = request.query.get("persona", "default").lower()
        enable_tools = request.query.get("tools", "1").lower() in ("1", "true", "yes")

        if persona in ("brok", "roast"):
            from voicefi.live_studio import BROK_SYSTEM_INSTRUCTION

            system_instruction = BROK_SYSTEM_INSTRUCTION
        else:
            from voicefi.live_studio import DEFAULT_SYSTEM_INSTRUCTION

            system_instruction = DEFAULT_SYSTEM_INSTRUCTION

        client_ws_lock = asyncio.Lock()
        is_alive = True

        live_lockfile = Path("/tmp/voicefi_live_session_active")
        try:
            live_lockfile.write_text(str(time.time()), encoding="utf-8")
        except Exception:
            pass

        async def safe_client_send_json(payload: dict):
            if not is_alive or ws.closed:
                return
            async with client_ws_lock:
                try:
                    await ws.send_json(payload)
                except Exception:
                    pass

        async def safe_client_send_bytes(data: bytes):
            if not is_alive or ws.closed:
                return
            async with client_ws_lock:
                try:
                    await ws.send_bytes(data)
                except Exception:
                    pass

        def on_audio_delta(audio_bytes: bytes):
            asyncio.create_task(safe_client_send_bytes(audio_bytes))

        def on_transcript_delta(text: str, is_user: bool):
            if is_user:
                asyncio.create_task(safe_client_send_json({"type": "user_transcript", "text": text}))
            else:
                asyncio.create_task(safe_client_send_json({"type": "model_transcript", "text": text}))

        def on_interrupted():
            asyncio.create_task(safe_client_send_json({"type": "interrupted"}))

        def on_turn_complete():
            asyncio.create_task(safe_client_send_json({"type": "turn_complete"}))

        def on_error(err_msg: str):
            asyncio.create_task(safe_client_send_json({"type": "error", "message": err_msg}))

        async def on_tool_call(call_id: str, name: str, args: dict):
            from voicefi.integrations.live_tools import execute_live_tool

            await safe_client_send_json(
                {
                    "type": "tool_start",
                    "name": name,
                    "id": call_id,
                    "args": args,
                }
            )
            t0 = time.time()
            try:
                res = await asyncio.wait_for(execute_live_tool(name, args), timeout=6.0)
                duration_ms = int((time.time() - t0) * 1000)
                await adapter.send_tool_response(call_id, name, res)
                await safe_client_send_json(
                    {
                        "type": "tool_done",
                        "name": name,
                        "id": call_id,
                        "result": res,
                        "duration_ms": duration_ms,
                    }
                )
            except Exception as ex:
                err_str = f"Error executing tool '{name}': {ex}"
                await adapter.send_tool_response(call_id, name, err_str)
                await safe_client_send_json(
                    {
                        "type": "tool_error",
                        "name": name,
                        "id": call_id,
                        "error": err_str,
                    }
                )

        if is_personaplex:
            adapter = PersonaPlexLiveAdapter(
                model=model,
                voice=voice,
                instructions=system_instruction,
                enable_tools=enable_tools,
                on_audio_delta=on_audio_delta,
                on_transcript_delta=on_transcript_delta,
                on_turn_complete=on_turn_complete,
                on_interrupted=on_interrupted,
                on_tool_call=on_tool_call,
                on_error=on_error,
            )
        else:
            adapter_cls = OpenAILiveAdapter if is_openai else GrokLiveAdapter
            adapter = adapter_cls(
                api_key=api_key,
                model=model,
                voice=voice,
                instructions=system_instruction,
                enable_tools=enable_tools,
                on_audio_delta=on_audio_delta,
                on_transcript_delta=on_transcript_delta,
                on_turn_complete=on_turn_complete,
                on_interrupted=on_interrupted,
                on_tool_call=on_tool_call,
                on_error=on_error,
            )

        try:
            await adapter.connect()
            await safe_client_send_json(
                {
                    "type": "connected",
                    "model": model,
                    "voice": voice,
                    "provider": provider,
                }
            )

            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    chunk = msg.data
                    # Browser mic sends 16kHz PCM; adapter expects 24kHz
                    chunk_24k = resample_pcm16(chunk, 16000, 24000)
                    await adapter.send_audio(chunk_24k)
                elif msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        t = data.get("type")
                        if t in ("barge_in", "interrupt"):
                            await adapter.interrupt()
                        elif t == "text":
                            await adapter.send_text(data.get("text", ""))
                        elif t == "update_voice":
                            new_v = data.get("voice", "")
                            if new_v:
                                await adapter.update_voice(new_v)
                    except Exception:
                        pass
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.ERROR):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Realtime live WebSocket proxy error: %s", e)
            await safe_client_send_json({"type": "error", "message": str(e)})
        finally:
            is_alive = False
            try:
                live_lockfile.unlink(missing_ok=True)
            except Exception:
                pass
            await adapter.close()
            if not ws.closed:
                await ws.close()

        return ws
