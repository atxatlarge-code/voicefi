"""
Model Context Protocol (MCP) server for VoiceFi.
Provides native stdio JSON-RPC 2.0 tool interface for AI agents (Antigravity, Claude Code, Cursor, etc.).
"""

import sys
import os
import json
import logging
import time
from contextlib import redirect_stdout
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
                "conv_id": {
                    "type": "string",
                    "description": "Optional conversation ID to link speech turn with active agent turn",
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
    {
        "name": "voicefi_send",
        "description": "Send a message, task finding, or joke to Antigravity or Claude Code across agents with correlation tracking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The message text or prompt to dispatch.",
                },
                "to": {
                    "type": "string",
                    "enum": ["antigravity", "claude"],
                    "description": "Target agent engine (default: 'antigravity').",
                },
                "conv_id": {
                    "type": "string",
                    "description": "Target conversation ID, or 'reply' to reply directly to the originating conversation.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional title or header for the message.",
                },
                "sender": {
                    "type": "string",
                    "description": "Sender attribution (e.g. 'Claude', 'Antigravity').",
                },
                "reply": {
                    "type": "boolean",
                    "description": "Set true to automatically reply to the originating conversation ID.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "voicefi_sfx",
        "description": "Play a comedy sound effect (drum_smash / ba-dum-tss, honk, sad_trombone, applause, boing, crickets).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": ["drum_smash", "drums", "honk", "sad_trombone", "applause", "cheer", "boing", "crickets"],
                    "description": "Name of the sound effect to play (default: 'drum_smash').",
                },
                "volume": {
                    "type": "number",
                    "description": "Volume multiplier (0.0 to 1.0, default: 1.0).",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "voicefi_meeting_start",
        "description": "Start an intelligent ProActive Meeting Note Taker session with Granola-style live markdown distillation and real-time action listener.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Optional title or agenda for the meeting session.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional custom file path to save the generated markdown notes.",
                },
                "auto_execute": {
                    "type": "boolean",
                    "description": "Whether to auto-execute detected actions (Linear tickets, Slack posts, branch scaffolds) along the way (default: true).",
                },
                "speaker": {
                    "type": "string",
                    "description": "Optional primary speaker name.",
                },
            },
        },
    },
    {
        "name": "voicefi_meeting_stop",
        "description": "Finalize active meeting note taker session, compile structured Granola-style notes, save markdown artifact, and return summary + actions.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "voicefi_meeting_status",
        "description": "Get real-time meeting note taker status, elapsed time, decisions made, and staged/executed action items.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "voicefi_meeting_action",
        "description": "Record an architectural decision or execute a meeting action item (Linear issue, Slack post, branch scaffold, research query) into active notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "enum": ["linear_ticket", "slack_message", "subagent_scaffold", "research", "decision", "todo"],
                    "description": "Type of action to record or execute.",
                },
                "title": {
                    "type": "string",
                    "description": "Title, description, or content of the action item or decision.",
                },
                "details": {
                    "type": "object",
                    "description": "Optional parameters (e.g. channel, assignee, branch, query).",
                },
            },
            "required": ["action_type", "title"],
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
                        "resources": {},
                        "prompts": {},
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

        elif method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resources": [],
                },
            }

        elif method == "resources/templates/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resourceTemplates": [],
                },
            }

        elif method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "prompts": [],
                },
            }

        elif method == "roots/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "roots": [],
                },
            }

        elif method == "logging/setLevel":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
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
        start_t = time.time()
        res = None
        err_type = None
        agent_name = args.get("agent_name") or args.get("agent") or "antigravity"
        persona = args.get("persona")
        text_arg = args.get("text", "")
        char_count = len(str(text_arg)) if text_arg else None

        # Support aliases: both canonical 'voicefi_*' and short 'vifi_*' / bare names
        canonical_name = name
        if name.startswith("vifi_"):
            canonical_name = "voicefi_" + name[5:]
        elif name in (
            "speak",
            "listen",
            "stop",
            "status",
            "set_voice",
            "ping_voice",
            "send",
            "sfx",
            "meeting_start",
            "meeting_stop",
            "meeting_status",
            "meeting_action",
        ):
            canonical_name = "voicefi_" + name

        try:
            if canonical_name == "voicefi_speak":
                res = self._tool_speak(args)
            elif canonical_name == "voicefi_listen":
                res = self._tool_listen(args)
            elif canonical_name == "voicefi_stop":
                res = self._tool_stop(args)
            elif canonical_name == "voicefi_status":
                res = self._tool_status(args)
            elif canonical_name == "voicefi_set_voice":
                res = self._tool_set_voice(args)
            elif canonical_name == "voicefi_ping_voice":
                res = self._tool_ping_voice(args)
            elif canonical_name == "voicefi_send":
                res = self._tool_send(args)
            elif canonical_name == "voicefi_sfx":
                res = self._tool_sfx(args)
            elif canonical_name == "voicefi_meeting_start":
                res = self._tool_meeting_start(args)
            elif canonical_name == "voicefi_meeting_stop":
                res = self._tool_meeting_stop(args)
            elif canonical_name == "voicefi_meeting_status":
                res = self._tool_meeting_status(args)
            elif canonical_name == "voicefi_meeting_action":
                res = self._tool_meeting_action(args)
            else:
                res = {
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                    "isError": True,
                }
            return res
        except Exception as e:
            err_type = type(e).__name__
            logger.exception("Error executing tool %s: %s", name, e)
            res = {
                "content": [{"type": "text", "text": f"Error executing {name}: {str(e)}"}],
                "isError": True,
            }
            return res
        finally:
            dur_ms = max(1, int((time.time() - start_t) * 1000))
            is_error = bool(res and res.get("isError", False))
            resolved_persona = persona or args.get("_resolved_persona")
            resolved_provider = args.get("_resolved_provider")
            tts_latency = args.get("_tts_latency_ms")
            extra_props = {}
            if resolved_provider:
                extra_props["provider"] = resolved_provider
            if tts_latency is not None:
                extra_props["tts_latency_ms"] = float(tts_latency)
                extra_props["ttfb_ms"] = float(tts_latency)
            try:
                from voicefi.telemetry import capture_mcp_tool_call
                capture_mcp_tool_call(
                    tool_name=canonical_name,
                    duration_ms=dur_ms,
                    caller_agent=agent_name,
                    persona=resolved_persona,
                    char_count=char_count,
                    success=(not is_error and err_type is None),
                    error_type=err_type,
                    extra_props=extra_props if extra_props else None,
                )
            except Exception:
                pass


    def _tool_speak(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.config import load_config
        from voicefi.tts import get_tts_engine

        raw_text = args.get("text")
        if raw_text is None or not isinstance(raw_text, str):
            return {"content": [{"type": "text", "text": "No text provided to speak."}], "isError": True}
        if not raw_text.strip():
            return {"content": [{"type": "text", "text": "No text provided to speak."}], "isError": True}
        text = raw_text

        raw_persona = args.get("persona")
        persona = str(raw_persona).strip() if raw_persona is not None and str(raw_persona).strip() else None
        raw_agent = args.get("agent_name") or args.get("agent") or "antigravity"
        agent_name = str(raw_agent).strip() if raw_agent is not None and str(raw_agent).strip() else "antigravity"
        block = bool(args.get("block", True))

        cfg = load_config()
        tts = get_tts_engine(cfg, agent_name=agent_name, voice_override=persona)
        args["_resolved_persona"] = getattr(tts, "persona_name", None) or getattr(tts, "voice", None)
        args["_resolved_provider"] = getattr(tts, "provider", None)

        try:
            from voicefi.integrations.conversations import claim_active_conversation_turn
            claim_active_conversation_turn(text, conv_id=args.get("conv_id"))
        except Exception:
            pass

        try:
            tts.stream_speak(text, block=block)
        except Exception:
            raise

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
        timeout_arg = args.get("timeout")
        timeout = None
        if timeout_arg is not None:
            try:
                timeout = float(timeout_arg)
            except (ValueError, TypeError) as e:
                return {
                    "content": [{"type": "text", "text": f"Error executing voicefi_listen: could not convert string to float: {timeout_arg}"}],
                    "isError": True,
                }

        recorder = AudioRecorder(
            sample_rate=cfg.vad.sample_rate,
            energy_threshold=cfg.vad.energy_threshold,
            silence_duration=cfg.vad.silence_duration,
            max_record_seconds=max_sec,
            barge_in=False,
        )

        audio_data, temp_wav = recorder.record_speech_auto(timeout=timeout)
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
        port_num = 5141
        if hasattr(cfg, "companion") and cfg.companion and hasattr(cfg.companion, "port"):
            port_num = cfg.companion.port or 5141
        port_info = get_port_listener(port_num) or get_port_listener(8765)
        running_procs = find_running_voicefi_processes()
        server_active = bool(port_info is not None or running_procs)

        antigravity_voice = cfg.tts.voice
        if hasattr(cfg, "agents") and isinstance(cfg.agents, dict) and "antigravity" in cfg.agents:
            ag_profile = cfg.agents.get("antigravity")
            if ag_profile and hasattr(ag_profile, "voice"):
                antigravity_voice = ag_profile.voice

        status_info = {
            "server_running": server_active,
            "daemon_running": server_active,
            "port": port_num,
            "port_listener": port_info.get("pid") if port_info else None,
            "input_device": in_dev.get("name") if in_dev else "Default Microphone",
            "output_device": out_dev.get("name") if out_dev else "Default Output",
            "primary_tts_voice": cfg.tts.voice,
            "primary_tts_provider": cfg.tts.provider,
            "antigravity_voice": antigravity_voice,
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

        raw_agent = args.get("agent", "antigravity")
        agent = str(raw_agent).strip().lower() if raw_agent is not None else "antigravity"
        raw_persona = args.get("persona", "")
        persona_name = str(raw_persona).strip() if raw_persona is not None else ""
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
        raw_voice = args.get("voice")
        voice = str(raw_voice).strip() if raw_voice is not None and str(raw_voice).strip() else None
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
            args["_resolved_persona"] = p_name
            args["_resolved_provider"] = res.provider
            args["_tts_latency_ms"] = res.latency_ms
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

    def _tool_send(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.integrations.injector import send_message_to_agent

        raw_text = args.get("text")
        if raw_text is None or not isinstance(raw_text, str):
            return {"content": [{"type": "text", "text": "Empty message text."}], "isError": True}
        text = raw_text.strip()
        if not text:
            return {"content": [{"type": "text", "text": "Empty message text."}], "isError": True}

        raw_engine = args.get("to") or "antigravity"
        target_engine = str(raw_engine).lower().strip() if raw_engine is not None else "antigravity"
        conv_id = str(args.get("conv_id")).strip() if args.get("conv_id") is not None else None
        if args.get("reply", False):
            conv_id = "reply"

        sender_name = str(args.get("sender", "Claude")).strip() if args.get("sender") is not None else "Claude"
        title = str(args.get("title")).strip() if args.get("title") is not None else None

        result = send_message_to_agent(
            conv_id=conv_id,
            text=text,
            sender_name=sender_name,
            title=title,
            target_engine=target_engine,
            from_engine="claude" if target_engine == "antigravity" else "antigravity",
        )

        if result.success:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Successfully dispatched message to {target_engine.capitalize()} (Target ID: {result.target_conv_id or 'active'}).",
                    }
                ],
                "isError": False,
            }
        else:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Failed to dispatch to {target_engine.capitalize()}: {result.error}",
                    }
                ],
                "isError": True,
            }

    def _tool_sfx(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.audio.sfx import play_sfx, list_available_sfx

        raw_name = args.get("name")
        if raw_name is None or not isinstance(raw_name, str):
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Missing or invalid sound effect name. Available: {', '.join(list_available_sfx())}",
                    }
                ],
                "isError": True,
            }
        name = raw_name.strip()
        if not name:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Missing or invalid sound effect name. Available: {', '.join(list_available_sfx())}",
                    }
                ],
                "isError": True,
            }

        try:
            volume = float(args.get("volume", 1.0))
            volume = max(0.0, min(volume, 2.0))
        except (ValueError, TypeError):
            volume = 1.0

        clean_name = name.strip()
        success = play_sfx(clean_name, block=True, volume=volume)
        if success:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Successfully played sound effect '{clean_name}'.",
                    }
                ],
                "isError": False,
            }
        else:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Unknown sound effect '{clean_name}'. Available: {', '.join(list_available_sfx())}",
                    }
                ],
                "isError": True,
            }

    def _tool_meeting_start(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.integrations.meeting import MeetingNoteTaker
        note_taker = MeetingNoteTaker.get_instance()
        title = args.get("title")
        output_path = args.get("output_path")
        auto_exec = args.get("auto_execute", True)
        speaker = args.get("speaker")

        session = note_taker.start_session(
            title=title,
            output_path=output_path,
            auto_execute_actions=auto_exec,
            speaker_name=speaker,
        )

        res_msg = (
            f"✅ ProActive Meeting Note Taker started successfully!\n"
            f"• Title: {session.title}\n"
            f"• Notes File: {session.markdown_path}\n"
            f"• Auto-Execute Actions: {'Enabled' if auto_exec else 'Disabled'}\n"
            f"• Status: 🟢 Active"
        )
        return {"content": [{"type": "text", "text": res_msg}], "isError": False}

    def _tool_meeting_stop(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.integrations.meeting import MeetingNoteTaker, ActionStatus
        note_taker = MeetingNoteTaker.get_instance()
        session = note_taker.stop_session()

        if not session:
            return {
                "content": [{"type": "text", "text": "No active meeting note taker session was found to stop."}],
                "isError": True,
            }

        executed_actions = [a for a in session.action_items if a.status == ActionStatus.COMPLETED]
        res_msg = (
            f"🏁 Meeting Session Finalized!\n"
            f"• Title: {session.title}\n"
            f"• Duration: {session.duration_formatted}\n"
            f"• Spoken Turns: {len(session.utterances)}\n"
            f"• Decisions Recorded: {len(session.decisions)}\n"
            f"• Actions Executed: {len(executed_actions)}\n"
            f"• Notes Artifact: {session.markdown_path}\n\n"
            f"### Executive Summary\n{session.executive_summary or 'Completed.'}\n\n"
        )
        if session.decisions:
            res_msg += "### Key Decisions Made\n"
            for d in session.decisions:
                res_msg += f"- [x] **{d.topic}:** {d.decision}\n"
            res_msg += "\n"

        res_msg += "### Real-Time Actions Taken Along The Way\n"
        if session.action_items:
            for a in session.action_items:
                res_msg += f"- [{a.category.value}] {a.title} -> {a.result_summary or a.status.value}\n"
        else:
            res_msg += "_No actions recorded during session._\n"

        return {"content": [{"type": "text", "text": res_msg}], "isError": False}

    def _tool_meeting_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.integrations.meeting import MeetingNoteTaker, ActionStatus
        note_taker = MeetingNoteTaker.get_instance()
        session = note_taker.active_session

        if not session or session.status != "active":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"status": "inactive", "message": "No active meeting session."}, indent=2),
                    }
                ],
                "isError": False,
            }

        executed_count = len([a for a in session.action_items if a.status == ActionStatus.COMPLETED])
        staged_count = len([a for a in session.action_items if a.status == ActionStatus.STAGED])
        status_data = {
            "session_id": session.session_id,
            "title": session.title,
            "status": session.status,
            "duration": session.duration_formatted,
            "duration_seconds": session.duration_seconds,
            "utterance_count": len(session.utterances),
            "decisions_count": len(session.decisions),
            "decisions": [{"topic": d.topic, "decision": d.decision, "time": d.timestamp_str} for d in session.decisions],
            "actions_executed_count": executed_count,
            "actions_staged_count": staged_count,
            "action_items": [
                {"id": a.id, "title": a.title, "category": a.category.value, "status": a.status.value, "result": a.result_summary}
                for a in session.action_items
            ],
            "markdown_path": session.markdown_path,
        }

        return {"content": [{"type": "text", "text": json.dumps(status_data, indent=2)}], "isError": False}

    def _tool_meeting_action(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from voicefi.integrations.meeting import (
            MeetingNoteTaker,
            MeetingActionExecutor,
            MeetingActionItem,
            MeetingDecision,
            ActionCategory,
            ActionStatus,
        )
        import uuid
        import datetime

        note_taker = MeetingNoteTaker.get_instance()
        session = note_taker.active_session

        action_type = args.get("action_type", "").lower()
        title = args.get("title", "").strip()
        details = args.get("details", {}) or {}

        if not title:
            return {"content": [{"type": "text", "text": "Action title is required."}], "isError": True}

        # If no session is active, auto-start one
        if not session or session.status != "active":
            session = note_taker.start_session(title=f"Ad-hoc Meeting ({datetime.date.today().isoformat()})")

        if action_type == "decision":
            dec = MeetingDecision(
                topic=details.get("topic", "Architecture"),
                decision=title,
                rationale=details.get("rationale"),
                timestamp_str=datetime.datetime.now().strftime("%H:%M:%S"),
            )
            session.decisions.append(dec)
            session.save_to_disk()
            return {
                "content": [{"type": "text", "text": f"✅ Recorded Decision: {title} (Topic: {dec.topic})"}],
                "isError": False,
            }

        cat_map = {
            "linear_ticket": ActionCategory.LINEAR_TICKET,
            "slack_message": ActionCategory.SLACK_MESSAGE,
            "subagent_scaffold": ActionCategory.SUBAGENT_SCAFFOLD,
            "research": ActionCategory.CODEBASE_RESEARCH,
            "todo": ActionCategory.GENERAL_TODO,
        }
        category = cat_map.get(action_type, ActionCategory.GENERAL_TODO)
        act_id = f"act_{uuid.uuid4().hex[:6]}"
        action_item = MeetingActionItem(
            id=act_id,
            raw_utterance=f"[MCP] {title}",
            title=title,
            category=category,
            status=ActionStatus.STAGED,
            assignee=details.get("assignee"),
            target_channel_or_branch=details.get("channel") or details.get("branch"),
            details=details,
        )
        session.action_items.append(action_item)
        res_summary = MeetingActionExecutor.execute_action(action_item)
        session.save_to_disk()

        return {
            "content": [{"type": "text", "text": f"⚡ Executed Meeting Action [{category.value}]: {title} -> {res_summary}"}],
            "isError": False,
        }

    def run_stdio(self):
        """Main stdio loop reading JSON-RPC requests from sys.stdin and writing to sys.stdout."""
        logger.info("Starting VoiceFi MCP Server on stdio...")
        self._running = True

        raw_stdout = sys.stdout
        # Redirect global sys.stdout to sys.stderr so print statements from libraries or VAD do not corrupt JSON-RPC
        sys.stdout = sys.stderr

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
                raw_stdout.write(json.dumps(err_resp) + "\n")
                raw_stdout.flush()
                continue

            try:
                resp = self.handle_request(req)
            except Exception as e:
                logger.exception("Unhandled error processing MCP request: %s", e)
                req_id = req.get("id") if isinstance(req, dict) else None
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}",
                    },
                } if req_id is not None else None

            if resp is not None:
                raw_stdout.write(json.dumps(resp) + "\n")
                raw_stdout.flush()


def run_mcp_server():
    """Entrypoint function for CLI `vifi mcp`."""
    server = VoiceFiMCPServer()
    server.run_stdio()
