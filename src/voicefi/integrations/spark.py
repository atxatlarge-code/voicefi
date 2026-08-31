"""
Gemini Spark & Antigravity Agent Integration with Spoken Turn-End Hooks.
Provides model-assisted spoken soundbite distillation via Gemini Flash,
manages agent execution turns, and emits structured turn_complete events to VoiceFi daemon.
"""

import asyncio
import logging
import re
from typing import Any, Callable, Dict, Optional, Union

from voicefi.config import VoiceFiConfig, load_config
from voicefi.integrations.antigravity import clean_markdown_for_speech
from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine
from voicefi.integrations.injector import send_message_to_antigravity
from voicefi.ipc.bridge import VoiceFiIPCBridge
from voicefi.ipc.protocol import (
    EVENT_TOOL_COMPLETE,
    EVENT_TOOL_START,
    EVENT_TURN_COMPLETE,
    EVENT_TURN_ERROR,
    EVENT_TURN_START,
    build_agent_event,
)

logger = logging.getLogger("voicefi.integrations.spark")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[Gemini Spark] %(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class SparkTurnEndHook:
    """
    Manages turn-end lifecycle hooks and model-assisted spoken soundbite distillation for Gemini Spark.
    """

    def __init__(
        self,
        bridge: Optional[VoiceFiIPCBridge] = None,
        config: Optional[VoiceFiConfig] = None,
        default_persona: str = "Viv",
        agent_name: str = "Spark",
    ):
        self.bridge = bridge
        self.config = config or load_config()
        self.default_persona = default_persona
        self.agent_name = agent_name
        self._intelligence_engine = GeminiIntelligenceEngine(self.config)

    def distill_spoken_soundbite(self, text: str, max_words: int = 30) -> str:
        """
        Distill raw agent execution output, markdown, or tool responses into a punchy spoken soundbite (<30 words).
        Uses Gemini Flash model intelligence if available; falls back to deterministic regex extraction.
        """
        if not text or not text.strip():
            return "Task completed."

        # 1. Try Gemini Flash distillation if available
        if self._intelligence_engine.is_available():
            try:
                distilled = self._intelligence_engine.distill_spoken_soundbite(
                    text, max_words=max_words, timeout=0.8
                )
                if distilled and len(distilled.strip()) > 3:
                    logger.debug('✨ Model-distilled soundbite: "%s"', distilled)
                    return distilled
            except Exception as e:
                logger.debug("Gemini distillation fallback: %s", e)

        # 2. Fallback to clean deterministic heuristic distillation
        cleaned = clean_markdown_for_speech(text, max_words=max_words)
        if not cleaned:
            cleaned = "Task completed successfully."
        return cleaned

    async def on_turn_start(self, prompt: str, session_id: Optional[str] = None):
        """Emit turn_start lifecycle event."""
        logger.info('🎬 Spark turn start: "%s"', prompt[:50])
        if self.bridge and self.bridge.is_connected:
            await self.bridge.emit_agent_event(
                event_type=EVENT_TURN_START,
                agent_name=self.agent_name,
                persona=self.default_persona,
                spoken_summary=f"Starting: {prompt[:30]}",
                status="running",
                details={"session_id": session_id, "prompt": prompt},
            )

    async def on_tool_start(self, tool_name: str, tool_args: Optional[Dict[str, Any]] = None):
        """Emit tool_start lifecycle event."""
        logger.debug("🔧 Spark tool start: %s", tool_name)
        if self.bridge and self.bridge.is_connected:
            await self.bridge.emit_agent_event(
                event_type=EVENT_TOOL_START,
                agent_name=self.agent_name,
                persona=self.default_persona,
                spoken_summary=f"Running tool {tool_name}",
                status="running",
                details={"tool_name": tool_name, "args": tool_args or {}},
            )

    async def on_tool_complete(
        self, tool_name: str, tool_result: Optional[Any] = None, success: bool = True
    ):
        """Emit tool_complete lifecycle event."""
        logger.debug("✅ Spark tool complete: %s (success=%s)", tool_name, success)
        if self.bridge and self.bridge.is_connected:
            await self.bridge.emit_agent_event(
                event_type=EVENT_TOOL_COMPLETE,
                agent_name=self.agent_name,
                persona=self.default_persona,
                spoken_summary=f"Completed tool {tool_name}",
                status="success" if success else "error",
                details={"tool_name": tool_name, "success": success},
            )

    async def on_turn_end(
        self,
        raw_output: str,
        status: str = "success",
        persona: Optional[str] = None,
        custom_spoken_summary: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Handle turn completion:
        1. Distill spoken soundbite using Gemini Flash.
        2. Emit turn_complete payload back to VoiceFi daemon.
        Returns the spoken soundbite string.
        """
        spoken_summary = (
            custom_spoken_summary
            if custom_spoken_summary is not None
            else self.distill_spoken_soundbite(raw_output)
        )
        resolved_persona = persona or self.default_persona

        logger.info(
            '🏁 Spark turn end [%s] (%s persona): "%s"',
            status,
            resolved_persona,
            spoken_summary,
        )

        if self.bridge and self.bridge.is_connected:
            await self.bridge.emit_agent_event(
                event_type=EVENT_TURN_COMPLETE if status == "success" else EVENT_TURN_ERROR,
                agent_name=self.agent_name,
                persona=resolved_persona,
                spoken_summary=spoken_summary,
                status=status,
                details=details or {"raw_output_length": len(raw_output)},
            )
        else:
            # Standalone fallback: speak directly and update HUD
            from voicefi.tts import get_tts_engine
            from voicefi.tts.base import set_cross_process_hud_state

            set_cross_process_hud_state("speaking", text=spoken_summary, agent_name=self.agent_name)
            try:
                loop = asyncio.get_running_loop()

                def _speak():
                    tts = get_tts_engine(self.config, agent_name=self.agent_name)
                    if hasattr(tts, "persona_name") and resolved_persona:
                        tts.persona_name = resolved_persona
                    tts.stream_speak(spoken_summary, block=True)

                await loop.run_in_executor(None, _speak)
            except Exception as e:
                logger.debug("Standalone TTS playback exception: %s", e)
            finally:
                set_cross_process_hud_state("done", agent_name=self.agent_name)

        return spoken_summary


class GeminiSparkRunner:
    """
    Executes spoken prompts against Gemini Spark / Antigravity and manages the full voice feedback loop.
    """

    def __init__(
        self,
        bridge: Optional[VoiceFiIPCBridge] = None,
        config: Optional[VoiceFiConfig] = None,
        persona: str = "Viv",
        executor: Optional[Callable[[str], Any]] = None,
    ):
        self.config = config or load_config()
        self.persona = persona
        self.executor = executor
        self.bridge = bridge or VoiceFiIPCBridge(
            agent_name="Spark",
            persona=persona,
            config=self.config,
        )
        self.turn_hook = SparkTurnEndHook(
            bridge=self.bridge,
            config=self.config,
            default_persona=persona,
            agent_name="Spark",
        )

        # Wire bridge prompt runner to spark execution turn
        self.bridge.prompt_runner = self.execute_prompt

    async def start(self):
        """Start the IPC bridge and wait for inbound spoken prompts."""
        await self.bridge.start()
        logger.info("🚀 Gemini Spark Runner active (persona: %s)", self.persona)

    async def stop(self):
        """Stop the runner and bridge."""
        await self.bridge.stop()

    async def execute_prompt(self, prompt: str, session_id: Optional[str] = None) -> str:
        """
        Execute an incoming prompt:
        1. Notify turn_start.
        2. Run executor (or dispatch to Antigravity).
        3. Notify turn_complete with model-distilled spoken summary.
        """
        await self.turn_hook.on_turn_start(prompt, session_id=session_id)

        try:
            if self.executor:
                res = self.executor(prompt)
                if asyncio.iscoroutine(res):
                    raw_result = await res
                else:
                    raw_result = str(res)
            else:
                # Default executor: Dispatch to Antigravity background API
                dispatch_res = send_message_to_antigravity(
                    conv_id=session_id or "active",
                    text=prompt,
                    sender_name="VoiceFi",
                    title="Spoken Voice Prompt",
                )
                if dispatch_res:
                    raw_result = f"Dispatched prompt to Antigravity: {prompt}"
                else:
                    raw_result = f"Failed to dispatch prompt: {prompt}"

            spoken_summary = await self.turn_hook.on_turn_end(
                raw_output=raw_result,
                status="success",
                persona=self.persona,
            )
            return spoken_summary

        except asyncio.CancelledError:
            logger.info("Spark prompt execution cancelled due to barge-in interrupt.")
            raise
        except Exception as e:
            logger.error("Error during Spark prompt execution: %s", e)
            await self.turn_hook.on_turn_end(
                raw_output=str(e),
                status="error",
                persona=self.persona,
                custom_spoken_summary=f"The agent encountered an error: {str(e)[:40]}.",
            )
            raise
