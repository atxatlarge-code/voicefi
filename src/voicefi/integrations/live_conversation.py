"""
Live API Spoken Turn Handler for VoiceFi.

Coordinates multi-turn full-duplex conversational voice turns with Gemini Live
when turn_end_mode is 'gemini_live'. Dispatches coding instructions to Antigravity
and speaks dialogue back to the user via gemini-3.8-live with Dynamic Island HUD synchronization.
"""

import asyncio
import logging
import os
import subprocess
import time
from typing import Optional

from voicefi.config import (
    VoiceFiConfig,
    load_config,
    resolve_gemini_api_key,
    VALID_GEMINI_LIVE_VOICES,
)
from voicefi.integrations.live_tools import get_live_tools, execute_live_tool
from voicefi.tts.base import (
    speech_turn_lock,
    set_agent_audio_playing,
    set_cross_process_hud_state,
    clear_cross_process_hud_state,
    is_speech_interrupted,
)

logger = logging.getLogger("voicefi.integrations.live_conversation")


async def _async_query_live_api(
    user_prompt: str,
    context: Optional[str] = None,
    conv_id: Optional[str] = None,
    persona_name: Optional[str] = None,
    config: Optional[VoiceFiConfig] = None,
) -> bool:
    """Connect to Gemini Live, stream user prompt, speak live audio response, and execute live tools."""
    cfg = config or load_config()
    api_key = resolve_gemini_api_key(cfg)
    if not api_key:
        logger.warning("No Gemini API key available for live turn query.")
        return False

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("google-genai package not installed.")
        return False

    voice = persona_name or getattr(cfg.tts, "voice", "Fenrir")
    if voice not in VALID_GEMINI_LIVE_VOICES:
        voice = "Fenrir"

    live_model = getattr(getattr(cfg, "gemini", None), "live_model", "gemini-3.8-live")
    user_name = getattr(cfg, "user_name", "Jake")

    sys_text = (
        f"You are a lightning-fast, articulate, and friendly AI voice partner powered by Google Gemini Live "
        f"communicating in VoiceFi with {user_name}.\n"
        f"Recent agent outcome:\n{context[:400] if context else 'None'}\n\n"
        "Guidelines:\n"
        "1. Keep spoken responses concise, witty, and natural (1-3 sentences) in your chosen persona.\n"
        "2. When the user asks you to write code, edit files, fix bugs, or execute any multi-step coding task, "
        "invoke 'dispatch_to_antigravity' with their request so Antigravity can execute the task in their workspace, "
        "and give a brief spoken acknowledgment to the user that it's on it.\n"
        "3. If the user asks for sound effects (rimshot, applause), invoke 'trigger_sound_effect'.\n"
        '4. For conversational remarks, questions, banter, or clarifications (such as "You\'re joking" or "What did you do?"), '
        "respond directly in spoken dialogue."
    )

    tools = get_live_tools()
    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part.from_text(text=sys_text)]),
        tools=tools,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
            )
        ),
    )

    client = genai.Client(api_key=api_key)
    turn_start_time = time.time()

    set_cross_process_hud_state(
        "gemini_live_speaking",
        text=user_prompt[:45],
        agent_name="Gemini Live",
        persona_name=voice,
        tag_text="● LIVE",
        live_stream=True,
    )

    proc = None
    try:
        proc = subprocess.Popen(
            [
                "ffplay",
                "-f",
                "s16le",
                "-ar",
                "24000",
                "-ch_layout",
                "mono",
                "-nodisp",
                "-autoexit",
                "-probesize",
                "32",
                "-sync",
                "audio",
                "-i",
                "pipe:0",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        async with client.aio.live.connect(model=live_model, config=live_config) as session:
            await session.send(input=user_prompt, end_of_turn=True)
            set_agent_audio_playing(True)

            transcribed_chunks = []
            async for response in session.receive():
                if is_speech_interrupted(turn_start_time):
                    break

                # Handle live tool calls (e.g. dispatch_to_antigravity)
                if response.tool_call:
                    for call in response.tool_call.function_calls:
                        res = await execute_live_tool(call.name, call.args or {})
                        await session.send_tool_response(
                            function_responses=[
                                types.FunctionResponse(
                                    name=call.name,
                                    id=call.id,
                                    response={"result": res},
                                )
                            ]
                        )

                # Handle server content (audio + transcription)
                if response.server_content:
                    sc = response.server_content

                    ot = getattr(sc, "output_transcription", None)
                    if ot and ot.text:
                        transcribed_chunks.append(ot.text)
                        full_spoken = "".join(transcribed_chunks).strip()
                        set_cross_process_hud_state(
                            "gemini_live_speaking",
                            text=full_spoken,
                            agent_name="Gemini Live",
                            persona_name=voice,
                            tag_text="● LIVE",
                            live_stream=True,
                        )

                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                if proc and proc.stdin:
                                    try:
                                        proc.stdin.write(part.inline_data.data)
                                        proc.stdin.flush()
                                    except (BrokenPipeError, OSError):
                                        pass

                    if getattr(sc, "turn_complete", False):
                        break

    except Exception as e:
        logger.error("Error during live WebSocket session: %s", e)
        return False
    finally:
        set_agent_audio_playing(False)
        if proc:
            try:
                if proc.stdin:
                    proc.stdin.close()
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    return True


def query_live_api_spoken_turn(
    user_prompt: str,
    context: Optional[str] = None,
    conv_id: Optional[str] = None,
    persona_name: Optional[str] = None,
    config: Optional[VoiceFiConfig] = None,
) -> bool:
    """
    Synchronous entrypoint called from stop hooks when the user speaks in Live API mode.
    Reroutes speech to Gemini Live with cross-process speech lock and graceful fallback.
    """
    cfg = config or load_config()
    voice = persona_name or getattr(cfg.tts, "voice", "Fenrir")

    try:
        with speech_turn_lock(
            text=user_prompt,
            agent_name="Gemini Live",
            persona_name=voice,
            app_name="Antigravity",
            conv_id=conv_id,
            tag_text="● LIVE",
            is_live=True,
        ):
            return asyncio.run(
                _async_query_live_api(
                    user_prompt=user_prompt,
                    context=context,
                    conv_id=conv_id,
                    persona_name=voice,
                    config=cfg,
                )
            )
    except Exception as e:
        logger.warning("Live turn execution failed: %s. Falling back to Antigravity injection.", e)
        try:
            from voicefi.integrations.injector import send_message_to_antigravity

            return send_message_to_antigravity(
                conv_id=conv_id, text=user_prompt, sender_name=cfg.user_name
            ).success
        except Exception:
            return False
