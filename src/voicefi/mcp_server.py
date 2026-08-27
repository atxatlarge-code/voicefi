"""
Model Context Protocol (MCP) server for VoiceFi.
Provides native stdio JSON-RPC 2.0 tool interface for AI agents (Antigravity, Claude Code, Cursor, etc.).
"""

import sys
import os
import json
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, List

# Configure logger to output only to stderr so stdout is reserved for JSON-RPC
logger = logging.getLogger("voicefi.mcp")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[VoiceFi MCP] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "voicefi"
SERVER_VERSION = "0.1.0"

# Standard tool definitions exposed to MCP clients
MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "voicefi_speak",
        "description": "Speak text aloud to the user using VoiceFi TTS with live Dynamic Island HUD visualization.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text content to synthesize and speak aloud.",
                },
                "persona": {
                    "type": "string",
                    "description": "Optional persona or voice name (e.g. 'Ava (Premium)', 'Viv', 'Samantha', 'Christopher'). If omitted, uses active agent configuration.",
                },
                "agent_name": {
                    "type": "string",
                    "description": "Optional agent identifier (e.g. 'antigravity', 'claude', 'researcher') for persona resolution.",
                },
                "block": {
                    "type": "boolean",
                    "description": "Whether to wait for playback to complete before returning (default: true).",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "voicefi_listen",
        "description": "Open the microphone, record user speech with Voice Activity Detection (VAD), and transcribe to text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds to wait for user to begin speaking (default: 10).",
                },
                "max_seconds": {
                    "type": "integer",
                    "description": "Maximum recording duration in seconds (default: 30).",
                },
            },
        },
    },
    {
        "name": "voicefi_stop",
        "description": "Immediately stop all active Text-to-Speech (TTS) audio playback and dismiss the speech popup.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "voicefi_status",
        "description": "Get VoiceFi system status including audio devices, configured agent voice personas, VAD thresholds, and daemon state.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "voicefi_set_voice",
        "description": "Configure the voice persona or provider for a specific AI agent or subagent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "description": "Agent or subagent name (e.g. 'antigravity', 'claude', 'default', 'researcher').",
                },
                "persona": {
                    "type": "string",
                    "description": "Voice persona name or ID (e.g. 'Ava (Premium)', 'Viv', 'Samantha', 'Christopher', 'Onyx').",
                },
            },
            "required": ["agent", "persona"],
        },
    },
    {
        "name": "voicefi_ping_voice",
        "description": "Measure silent TTS synthesis latency (Time to First Byte / TTFB), throughput, and payload size without audio playback.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "voice": {
                    "type": "string",
                    "description": "Voice name or persona to benchmark (default: active Antigravity voice).",
                },
            },
        },
    },
]


class VoiceFiMCPServer:
    """Stdio JSON-RPC 2.0 Server implementing the Model Context Protocol (MCP)."""

    def __init__(self):
        self._running = False

    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC request and return a response object (or None for notifications)."""
        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params", {}) or {}

        # Handle notifications (no id)
        if req_id is None:
            if method == "notifications/initialized":
                logger.info("Client initialized successfully.")
            return None

        # Standard RPC Methods
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": MCP_TOOLS,
                },
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {}) or {}
            result = self.execute_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not found",
                },
            }

    def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and format the response according to MCP specification."""
        try:
            if name == "voicefi_speak":
                return self._tool_speak(args)
            elif name == "voicefi_listen":
                return self._tool_listen(args)
            elif name == "voicefi_stop":
                return self._tool_stop(args)
            elif name == "voicefi_status":
                return self._tool_status(args)
            elif name == "voicefi_set_voice":
                return self._tool_set_voice(args)
            elif name == "voicefi_ping_voice":
                return self._tool_ping_voice(args)
            else:
                return {
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                    "isError": True,
                }
        except Exception as e:
            logger.exception("Error executing tool %s: %s", name, e)
            return {
                "content": [{"type": "text", "text": f"Error executing {name}: {str(e)}"}],
                "isError": True,
            }

    def _tool_speak(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.config import load_config
        from voicefi.tts import get_tts_engine

        text = args.get("text", "")
        if not text or not text.strip():
            return {"content": [{"type": "text", "text": "No text provided to speak."}], "isError": True}

        persona = args.get("persona")
        agent_name = args.get("agent_name") or "antigravity"
        block = args.get("block", True)

        cfg = load_config()
        tts = get_tts_engine(cfg, agent_name=agent_name, voice_override=persona)
        
        start_t = time.time()
        err = None
        try:
            tts.stream_speak(text, block=block)
        except Exception as ex:
            err = type(ex).__name__
            raise
        finally:
            dur_ms = int((time.time() - start_t) * 1000)
            try:
                from voicefi.telemetry import capture_voice_interaction
                capture_voice_interaction(
                    trigger="mcp",
                    duration_ms=dur_ms,
                    success=(err is None),
                    agent=agent_name,
                    voice=getattr(tts, "voice", None),
                    provider=getattr(tts, "provider", None),
                    chars_count=len(text) if text else 0,
                    error_type=err,
                )
            except Exception:
                pass

        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Successfully synthesized and spoke aloud using persona '{tts.persona_name}': \"{text}\"",
                }
            ],
            "isError": False,
        }

    def _tool_listen(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.config import load_config
        from voicefi.audio.recorder import AudioRecorder
        from voicefi.stt import get_stt_engine

        cfg = load_config()
        max_sec = args.get("max_seconds", cfg.vad.max_record_seconds)

        recorder = AudioRecorder(
            sample_rate=cfg.vad.sample_rate,
            energy_threshold=cfg.vad.energy_threshold,
            silence_duration=cfg.vad.silence_duration,
            max_record_seconds=max_sec,
            barge_in=False,
        )

        audio_data, temp_wav = recorder.record_speech_auto()
        if not temp_wav or not Path(temp_wav).is_file():
            return {
                "content": [{"type": "text", "text": "No speech detected or recording was cancelled."}],
                "isError": False,
            }

        try:
            stt = get_stt_engine(cfg)
            transcription = stt.transcribe(temp_wav)
        finally:
            Path(temp_wav).unlink(missing_ok=True)

        clean_text = (transcription or "").strip()
        return {
            "content": [
                {
                    "type": "text",
                    "text": clean_text if clean_text else "No audible words were recognized.",
                }
            ],
            "isError": False,
        }

    def _tool_stop(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.tts import stop_all_speech

        stop_all_speech()
        try:
            from voicefi.ui.speech_hud import AgentSpeechHUD
            AgentSpeechHUD.get_instance().hide()
        except Exception:
            pass

        return {
            "content": [{"type": "text", "text": "Stopped all active speech playback and dismissed speech HUD."}],
            "isError": False,
        }

    def _tool_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.config import load_config
        from voicefi.audio.device import get_default_audio_devices
        from voicefi.server import get_port_listener, find_running_voicefi_processes

        cfg = load_config()
        in_dev, out_dev = get_default_audio_devices()
        port_num = getattr(cfg, "companion", None) and cfg.companion.port or 5141
        port_info = get_port_listener(port_num) or get_port_listener(8765)
        running_procs = find_running_voicefi_processes()
        server_active = bool(port_info is not None or running_procs)

        status_info = {
            "server_running": server_active,
            "daemon_running": server_active,
            "port": port_num,
            "port_listener": port_info.get("pid") if port_info else None,
            "input_device": in_dev.get("name") if in_dev else "Default Microphone",
            "output_device": out_dev.get("name") if out_dev else "Default Output",
            "primary_tts_voice": cfg.tts.voice,
            "primary_tts_provider": cfg.tts.provider,
            "antigravity_voice": cfg.agents.get("antigravity").voice if "antigravity" in cfg.agents else cfg.tts.voice,
            "barge_in": cfg.vad.barge_in,
            "energy_threshold": cfg.vad.energy_threshold,
        }

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(status_info, indent=2),
                }
            ],
            "isError": False,
        }

    def _tool_set_voice(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.config import load_config, save_config, AgentVoiceProfile
        from voicefi.tts import find_persona

        agent = args.get("agent", "antigravity").strip().lower()
        persona_name = args.get("persona", "").strip()
        if not persona_name:
            return {"content": [{"type": "text", "text": "Persona name is required."}], "isError": True}

        cfg = load_config()
        persona = find_persona(persona_name)
        resolved_voice = persona.id if persona else persona_name
        resolved_provider = persona.provider if persona else "edge_tts"

        if agent in ("default", "global", "tts"):
            cfg.tts.voice = resolved_voice
            cfg.tts.provider = resolved_provider
        else:
            cfg.agents[agent] = AgentVoiceProfile(
                voice=resolved_voice,
                provider=resolved_provider,
                offline_voice=persona.offline_voice if persona and getattr(persona, "offline_voice", None) else persona_name,
                description=f"{agent.title()} Voice Profile",
            )

        save_config(cfg)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Successfully updated voice for '{agent}' to '{persona_name}' ({resolved_provider}).",
                }
            ],
            "isError": False,
        }

    def _tool_ping_voice(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.config import load_config
        from voicefi.troubleshoot import AudioTroubleshooter
        from voicefi.tts import find_persona

        cfg = load_config()
        voice = args.get("voice")
        persona = find_persona(voice) if voice else None
        target_voice = persona.id if persona else (voice or cfg.tts.voice)
        target_provider = persona.provider if persona else (getattr(cfg.tts, "provider", "edge_tts"))

        troubleshooter = AudioTroubleshooter(cfg)
        res = troubleshooter.ping_voice_silently(
            voice_name_or_id=target_voice,
            provider=target_provider,
        )

        if res.success:
            p_name = persona.name if persona else target_voice
            kb_size = round(res.audio_bytes / 1024.0, 1)
            lat = round(res.latency_ms, 1)
            spd = round(res.chars_per_sec, 1)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Voice: {p_name} | Provider: {res.provider} | Status: {res.status} | TTFB: {lat}ms | Speed: {spd} char/s | Payload: {kb_size} KB",
                    }
                ],
                "isError": False,
            }
        else:
            return {
                "content": [{"type": "text", "text": f"Ping benchmark failed for {voice}: {res.error or res.status}"}],
                "isError": True,
            }

    def run_stdio(self):
        """Main stdio loop reading JSON-RPC requests from sys.stdin and writing to sys.stdout."""
        logger.info("Starting VoiceFi MCP Server on stdio...")
        self._running = True

        for line in sys.stdin:
            line_str = line.strip()
            if not line_str:
                continue

            try:
                req = json.loads(line_str)
            except json.JSONDecodeError as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {str(e)}",
                    },
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
                continue

            resp = self.handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


def run_mcp_server():
    """Entrypoint function for CLI `vifi mcp`."""
    server = VoiceFiMCPServer()
    server.run_stdio()
