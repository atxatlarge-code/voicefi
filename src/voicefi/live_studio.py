"""
Gemini Live Interactive Studio for VoiceFi.

Full-duplex real-time speech-to-speech studio connecting microphone input directly
to Google Gemini Live over WebSockets with parallel background tool execution
and instant acoustic barge-in (<150ms).
"""

import asyncio
import collections
import logging
import sys
import time
from typing import Optional, Dict, Any, List

from voicefi.config import load_config, resolve_gemini_api_key, VALID_GEMINI_LIVE_VOICES
from voicefi.audio.live_stream import LiveAudioStream
from voicefi.integrations.live_tools import get_live_tools, execute_live_tool

logger = logging.getLogger("voicefi.live_studio")

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are a lightning-fast, articulate, and friendly AI voice partner powered by Google Gemini Live "
    "running inside VoiceFi. You communicate in spoken dialogue over a real-time full-duplex audio stream. "
    "Guidelines:\n"
    "1. Keep your spoken responses concise, conversational, and direct (1-3 sentences) unless asked to elaborate.\n"
    "2. You have access to real-time tools: 'read_code_file', 'search_codebase', 'run_shell_check', and 'trigger_sound_effect'.\n"
    "3. You can execute these tools in parallel while speaking or before answering. Use them proactively whenever the user "
    "asks about files, code, git status, system status, or asks for comedic sound effects (like rimshot or applause).\n"
    "4. If interrupted by the user speaking over you, stop immediately and listen to their new input."
)


class GeminiLiveStudio:
    """
    Interactive full-duplex speech-to-speech session runner.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.5-flash-native-audio-latest",
        voice: str = "Puck",
        system_instruction: Optional[str] = None,
        use_thinking: bool = False,
        thinking_level: str = "LOW",
        enable_tools: bool = True,
        barge_in_threshold: float = 0.018,
    ):
        self.config = load_config()
        self.api_key = api_key or resolve_gemini_api_key(self.config)
        if not self.api_key:
            raise ValueError(
                "Gemini API Key not found. Please set GEMINI_API_KEY environment variable "
                "or configure in ~/.voicefi/config.yaml."
            )

        try:
            from google import genai
            from google.genai import types
            self._genai = genai
            self._types = types
        except ImportError:
            raise ImportError("google-genai is required. Install with: pip install google-genai>=1.65.0")

        self.model = "gemini-3.8-live-extended-thinking" if use_thinking else model
        self.voice = voice if voice in VALID_GEMINI_LIVE_VOICES else "Puck"
        self.system_instruction = system_instruction or DEFAULT_SYSTEM_INSTRUCTION
        self.use_thinking = use_thinking
        self.thinking_level = thinking_level.upper()
        self.enable_tools = enable_tools
        self.barge_in_threshold = barge_in_threshold

        self.client = self._genai.Client(api_key=self.api_key)
        self.stream: Optional[LiveAudioStream] = None
        self.session = None
        self.is_running = False
        self._pending_tool_tasks: set = set()
        self._send_lock: Optional[asyncio.Lock] = None

        # STT bridge for preview models (e.g. 3.8) lacking server-side audio-in VAD
        self.needs_stt_bridge = "3.8" in self.model or "3.1" in self.model
        self._stt_engine = None
        if self.needs_stt_bridge:
            try:
                from voicefi.stt import get_stt_engine
                self._stt_engine = get_stt_engine(self.config)
            except Exception as e:
                logger.warning("Failed to initialize STT bridge engine: %s", e)

        self._speech_buffer: List[bytes] = []
        self._preroll_buffer = collections.deque(maxlen=15)  # 300ms @ 20ms chunks
        self._is_speaking_user: bool = False
        self._silence_count: int = 0

    def _build_live_config(self):
        tools = get_live_tools() if self.enable_tools else None

        thinking_cfg = None
        if self.use_thinking or "extended-thinking" in self.model:
            level_enum = getattr(self._types, "ThinkingLevel", None)
            t_level = getattr(level_enum, self.thinking_level, "LOW") if level_enum else self.thinking_level
            thinking_cfg = self._types.ThinkingConfig(thinking_level=t_level)

        return self._types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self._types.Content(
                parts=[self._types.Part.from_text(text=self.system_instruction)]
            ),
            speech_config=self._types.SpeechConfig(
                voice_config=self._types.VoiceConfig(
                    prebuilt_voice_config=self._types.PrebuiltVoiceConfig(
                        voice_name=self.voice
                    )
                )
            ),
            thinking_config=thinking_cfg,
            input_audio_transcription=self._types.AudioTranscriptionConfig(),
            output_audio_transcription=self._types.AudioTranscriptionConfig(),
            enable_affective_dialog=True,
            tools=tools,
        )

    def _on_local_barge_in(self):
        """Called by LiveAudioStream when user speech energy exceeds threshold during playback."""
        print("\n⚡ [Barge-in Interruption]")
        if self.session and self.is_running:
            try:
                asyncio.create_task(self._safe_send_barge_in())
            except Exception as e:
                logger.debug("Failed to send activity_start on barge in: %s", e)

    async def _safe_send_barge_in(self):
        if not self._send_lock:
            self._send_lock = asyncio.Lock()
        async with self._send_lock:
            if self.session and self.is_running:
                await self.session.send_realtime_input(
                    activity_start=self._types.ActivityStart()
                )

    async def _safe_send_media(self, chunk: bytes):
        if not self._send_lock:
            self._send_lock = asyncio.Lock()
        async with self._send_lock:
            if self.session and self.is_running:
                await self.session.send_realtime_input(
                    media=self._types.Blob(
                        data=chunk,
                        mime_type="audio/pcm;rate=16000",
                    )
                )

    async def _handle_tool_call(self, call):
        """Execute a tool asynchronously in the background and return response to Gemini."""
        name = call.name
        call_id = call.id
        args = dict(call.args) if call.args else {}

        arg_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
        print(f"\n🛠️  [Executing Tool] {name}({arg_str})...")

        try:
            res = await asyncio.wait_for(execute_live_tool(name, args), timeout=6.0)
            res_preview = (res[:80] + "...") if len(res) > 80 else res
            print(f"✅ [Tool Finished] {name} -> {res_preview}")

            if self.session and self.is_running:
                if not self._send_lock:
                    self._send_lock = asyncio.Lock()
                async with self._send_lock:
                    await self.session.send_tool_response(
                        function_responses=[
                            self._types.FunctionResponse(
                                name=name,
                                id=call_id,
                                response={"result": res},
                            )
                        ]
                    )
        except Exception as e:
            logger.error("Tool execution failed for %s: %s", name, e)
            print(f"❌ [Tool Failed] {name}: {e}")
            # ALWAYS send FunctionResponse to prevent conversational deadlock
            if self.session and self.is_running:
                if not self._send_lock:
                    self._send_lock = asyncio.Lock()
                try:
                    async with self._send_lock:
                        await self.session.send_tool_response(
                            function_responses=[
                                self._types.FunctionResponse(
                                    name=name,
                                    id=call_id,
                                    response={"error": str(e)},
                                )
                            ]
                        )
                except Exception as send_err:
                    logger.debug("Failed sending tool error to Gemini: %s", send_err)

    async def _safe_send_text(self, text: str):
        if not self._send_lock:
            self._send_lock = asyncio.Lock()
        async with self._send_lock:
            if self.session and self.is_running:
                await self.session.send_realtime_input(text=text)

    async def _transcribe_and_send(self, audio_bytes: bytes):
        """Transcribe speech buffer via cached STT singleton and inject text into Gemini preview model."""
        if not self._stt_engine:
            return
        try:
            import numpy as np

            audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if len(audio_array) < 1600 * 3:  # Ignore blips shorter than 300ms
                return
            text = await asyncio.to_thread(self._stt_engine.transcribe, audio_array)
            text = text.strip() if text else ""
            if text and self.is_running:
                print(f"\n🎤 You: {text}")
                await self._safe_send_text(text)
        except Exception as e:
            logger.debug("STT bridge error: %s", e)

    async def _mic_loop(self):
        """Continuously capture 20ms 16kHz PCM audio chunks and stream to Gemini."""
        logger.debug("Starting mic streaming loop...")
        from voicefi.audio.live_stream import calculate_rms
        MAX_SPEECH_CHUNKS = 500  # Cap utterance at 10 seconds (500 * 20ms)

        while self.is_running and self.stream and self.stream.is_running:
            try:
                chunk = await self.stream.get_mic_chunk()
                if not self.is_running:
                    break

                # Stream audio directly if model supports native audio
                if not self.needs_stt_bridge and self.session:
                    await self._safe_send_media(chunk)

                # For models without server-side audio-in VAD (e.g. 3.8 preview):
                if self.needs_stt_bridge:
                    self._preroll_buffer.append(chunk)
                    energy = calculate_rms(chunk)
                    speech_thresh = max(0.010, self.barge_in_threshold * 0.7)
                    if energy > speech_thresh:
                        if not self._is_speaking_user:
                            # Prepend pre-roll chunks to preserve onset consonants
                            self._speech_buffer.extend(self._preroll_buffer)
                            self._is_speaking_user = True
                        self._speech_buffer.append(chunk)
                        self._silence_count = 0
                    elif self._is_speaking_user:
                        self._speech_buffer.append(chunk)
                        self._silence_count += 1
                        # 25 chunks @ 20ms = 500ms trailing silence
                        if self._silence_count >= 25 or len(self._speech_buffer) >= MAX_SPEECH_CHUNKS:
                            self._is_speaking_user = False
                            audio_bytes = b"".join(self._speech_buffer)
                            self._speech_buffer.clear()
                            asyncio.create_task(self._transcribe_and_send(audio_bytes))
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.is_running:
                    logger.debug("Mic send error: %s", e)
                await asyncio.sleep(0.01)

    async def _receive_loop(self):
        """Receive streaming audio, transcriptions, and tool calls from Gemini."""
        logger.debug("Starting receive loop...")
        try:
            while self.is_running and self.session:
                try:
                    response = await self.session._receive()
                except Exception as recv_err:
                    if self.is_running:
                        logger.debug("Live receive error: %s", recv_err)
                    break

                if not self.is_running:
                    break

                # 1. Handle live tool calls
                if response.tool_call:
                    for call in response.tool_call.function_calls:
                        task = asyncio.create_task(self._handle_tool_call(call))
                        self._pending_tool_tasks.add(task)
                        task.add_done_callback(self._pending_tool_tasks.discard)

                # 2. Handle server content (audio + transcription)
                if response.server_content:
                    sc = response.server_content

                    # Server-side interruption detection
                    if getattr(sc, "interrupted", False):
                        if self.stream:
                            self.stream.flush_speaker()
                        print("\n[⚡ Interrupted by server]")

                    # User speech transcription
                    it = getattr(sc, "input_transcription", None)
                    if it and it.text:
                        print(f"\n🎤 You: {it.text}")

                    # Model speech transcription
                    ot = getattr(sc, "output_transcription", None)
                    if ot and ot.text:
                        sys.stdout.write(ot.text)
                        sys.stdout.flush()

                    # Model audio playback (24kHz PCM)
                    if sc.model_turn:
                        for part in sc.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                if self.stream:
                                    self.stream.play_audio_chunk(part.inline_data.data)

                    # Turn completed
                    if getattr(sc, "turn_complete", False):
                        sys.stdout.write("\n")
                        sys.stdout.flush()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if self.is_running:
                logger.error("Live receive loop error: %s", e)

    async def run(self):
        """Run the full-duplex speech-to-speech studio."""
        loop = asyncio.get_running_loop()
        self._send_lock = asyncio.Lock()

        # Initialize audio I/O stream with 20ms chunks
        self.stream = LiveAudioStream(
            on_barge_in=self._on_local_barge_in,
            barge_in_threshold=self.barge_in_threshold,
        )
        self.stream.start(loop=loop)
        self.is_running = True

        config = self._build_live_config()

        # Print banner
        tools_desc = "read_code_file, search_codebase, run_shell_check, trigger_sound_effect" if self.enable_tools else "None"
        print("\n" + "=" * 68)
        print("🎙️   VoiceFi — Gemini Live Studio (Direct Audio Loop)")
        print("=" * 68)
        print(f"  • Model:            {self.model}")
        print(f"  • Persona Voice:    {self.voice}")
        print(f"  • Thinking Level:   {self.thinking_level if self.use_thinking else 'Disabled'}")
        print(f"  • Background Tools: {tools_desc}")
        print(f"  • Full-Duplex I/O:  16kHz Mic In ──► Gemini ──► 24kHz Speaker Out (20ms frames)")
        print(f"  • Barge-In:         Enabled (<150ms cut-off)")
        print("=" * 68)
        print("\nSpeak into your microphone. Say 'Tell me a joke', 'Check git status',")
        print("or ask any question about your codebase.")
        print("Interrupt at any time by speaking firmly.\n")
        print("Press Ctrl+C to exit.\n")

        try:
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                self.session = session
                print(f"🟢 Connected to {self.model}! Listening...\n")

                mic_task = asyncio.create_task(self._mic_loop())
                recv_task = asyncio.create_task(self._receive_loop())

                # Exit cleanly if either task finishes, cancelling the sibling
                done, pending = await asyncio.wait(
                    [mic_task, recv_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()

        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            self.stop()

    def stop(self):
        """Cleanly stop streams and tasks."""
        self.is_running = False
        if self.stream:
            self.stream.stop()
            self.stream = None
        for task in list(self._pending_tool_tasks):
            task.cancel()
        self._pending_tool_tasks.clear()
        print("\n👋 Exited Live Studio.")


def start_live_studio(
    model: str = "gemini-2.5-flash-native-audio-latest",
    voice: str = "Puck",
    use_thinking: bool = False,
    thinking_level: str = "LOW",
    enable_tools: bool = True,
):
    """Synchronous entrypoint to run the live studio."""
    studio = GeminiLiveStudio(
        model=model,
        voice=voice,
        use_thinking=use_thinking,
        thinking_level=thinking_level,
        enable_tools=enable_tools,
    )
    try:
        asyncio.run(studio.run())
    except KeyboardInterrupt:
        studio.stop()


if __name__ == "__main__":
    start_live_studio()
