"""
VoiceFi Local IPC & Bridge Protocol Package.
Provides low-latency Unix domain socket (/tmp/voicefi.sock) and WebSocket (:8765)
JSON-RPC 2.0 communication for AI coding agents and ambient runtime.
"""

from voicefi.ipc.protocol import (
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCNotification,
    METHOD_PROMPT_DISPATCH,
    METHOD_SIGNAL_INTERRUPT,
    METHOD_VAD_SPEECH,
    METHOD_AGENT_EVENT,
    EVENT_TURN_START,
    EVENT_TOOL_START,
    EVENT_TOOL_COMPLETE,
    EVENT_TURN_COMPLETE,
    EVENT_TURN_ERROR,
    EVENT_TURN_INTERRUPTED,
    build_agent_event,
    build_prompt_dispatch_event,
    build_signal_interrupt_event,
    parse_jsonrpc_message,
)
from voicefi.ipc.server import VoiceFiIPCServer
from voicefi.ipc.bridge import VoiceFiIPCBridge

__all__ = [
    "JSONRPCRequest",
    "JSONRPCResponse",
    "JSONRPCNotification",
    "METHOD_PROMPT_DISPATCH",
    "METHOD_SIGNAL_INTERRUPT",
    "METHOD_VAD_SPEECH",
    "METHOD_AGENT_EVENT",
    "EVENT_TURN_START",
    "EVENT_TOOL_START",
    "EVENT_TOOL_COMPLETE",
    "EVENT_TURN_COMPLETE",
    "EVENT_TURN_ERROR",
    "EVENT_TURN_INTERRUPTED",
    "build_agent_event",
    "build_prompt_dispatch_event",
    "build_signal_interrupt_event",
    "parse_jsonrpc_message",
    "VoiceFiIPCServer",
    "VoiceFiIPCBridge",
]
