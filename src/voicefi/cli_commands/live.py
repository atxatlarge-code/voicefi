"""
CLI command for Gemini 3.8 Live direct full-duplex speech-to-speech studio and comedy runner.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def cmd_live(args: Any) -> None:
    """Run real-time Gemini 3.8 Live voice/comedy session."""
    from voicefi.integrations.gemini_live import GeminiLiveRunner, VALID_GEMINI_LIVE_VOICES

    prompt = " ".join(args.prompt).strip() if getattr(args, "prompt", None) else None
    voice = getattr(args, "voice", "Puck") or "Puck"
    mode = getattr(args, "mode", "comedy") or "comedy"
    use_thinking = getattr(args, "thinking", False)
    thinking_level = getattr(args, "thinking_level", "LOW") or "LOW"
    enable_sfx = not getattr(args, "no_sfx", False)
    play_audio = not getattr(args, "no_play", False)
    direct_live = getattr(args, "direct_live", False) or getattr(args, "root_live", False)
    enable_tools = getattr(args, "tools", True)
    model = getattr(args, "model", None) or (
        "gemini-3.8-live-extended-thinking"
        if use_thinking
        else "gemini-2.5-flash-native-audio-latest"
    )

    if direct_live:
        from voicefi.live_studio import GeminiLiveStudio

        try:
            studio = GeminiLiveStudio(
                model=model,
                voice=voice,
                use_thinking=use_thinking,
                thinking_level=thinking_level,
                enable_tools=enable_tools,
            )
            asyncio.run(studio.run())
        except KeyboardInterrupt:
            pass
        return

    try:
        runner = GeminiLiveRunner(
            voice=voice,
            mode=mode,
            use_thinking=use_thinking,
            thinking_level=thinking_level,
            enable_sfx=enable_sfx,
            play_audio=play_audio,
        )
    except Exception as e:
        print(f"❌ Error initializing Gemini 3.8 Live runner: {e}")
        return

    if prompt:
        asyncio.run(runner.run_prompt(prompt))
    else:
        print(
            f"\n🎭 Gemini 3.8 Live Studio (Model: {runner.model} | Voice: {runner.voice} | Mode: {runner.mode})"
        )
        print("Type your joke prompt or topic below. Type 'exit' to quit.\n")
        while True:
            try:
                line = input("🎤 You > ").strip()
                if not line:
                    continue
                if line.lower() in ("exit", "quit", "q"):
                    print("👋 Exiting Gemini Live Studio.")
                    break
                asyncio.run(runner.run_prompt(line))
            except (KeyboardInterrupt, EOFError):
                print("\n👋 Exiting Gemini Live Studio.")
                break


def cmd_bridge(args: Any) -> None:
    """Run or manage the VoiceFi local IPC bridge service."""
    import asyncio
    from voicefi.config import load_config
    from voicefi.ipc import VoiceFiIPCBridge, VoiceFiIPCServer

    config = load_config(getattr(args, "config", None))
    sock_path = getattr(args, "socket", None) or config.ipc.socket_path
    ws_port = getattr(args, "ws_port", None) or config.ipc.ws_port
    agent_name = getattr(args, "agent", None) or "Spark"
    persona = getattr(args, "persona", None) or getattr(config.spark, "persona", "Viv")

    if getattr(args, "server", False):
        print(f"🚀 Starting VoiceFi IPC Server at {sock_path} (WS: ws://127.0.0.1:{ws_port})...")
        server = VoiceFiIPCServer(
            socket_path=sock_path,
            ws_port=ws_port,
            config=config,
        )

        async def _run_srv():
            await server.start()
            while server.is_running:
                await asyncio.sleep(1)

        try:
            asyncio.run(_run_srv())
        except KeyboardInterrupt:
            print("\n🛑 Stopping IPC Server...")
            asyncio.run(server.stop())
        return

    print(f"🔗 Starting VoiceFi IPC Bridge for {agent_name} ({persona} persona) -> {sock_path}...")
    bridge = VoiceFiIPCBridge(
        socket_path=sock_path,
        ws_url=f"ws://127.0.0.1:{ws_port}/ws",
        agent_name=agent_name,
        persona=persona,
        config=config,
    )

    async def _run():
        await bridge.start()
        print("✅ IPC Bridge connected and listening for spoken prompts. Press Ctrl+C to exit.")
        while True:
            await asyncio.sleep(1)

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n🛑 Disconnecting IPC Bridge...")
        asyncio.run(bridge.stop())
