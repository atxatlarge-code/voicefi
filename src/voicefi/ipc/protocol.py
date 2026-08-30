"""
VoiceFi JSON-RPC 2.0 Protocol Specification & Message Framing.
Defines message schemas, constants, serialization helpers, and payload builders.
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union


# Protocol Methods
METHOD_PROMPT_DISPATCH = "vifi.prompt.dispatch"
METHOD_SIGNAL_INTERRUPT = "vifi.signal.interrupt"
METHOD_VAD_SPEECH = "vifi.vad.speech_detected"
METHOD_AGENT_EVENT = "vifi.agent.event"

# Agent Event Types
EVENT_TURN_START = "turn_start"
EVENT_TOOL_START = "tool_start"
EVENT_TOOL_COMPLETE = "tool_complete"
EVENT_TURN_COMPLETE = "turn_complete"
EVENT_TURN_ERROR = "turn_error"
EVENT_TURN_INTERRUPTED = "turn_interrupted"

# Supported Event Types Set
VALID_EVENT_TYPES = {
    EVENT_TURN_START,
    EVENT_TOOL_START,
    EVENT_TOOL_COMPLETE,
    EVENT_TURN_COMPLETE,
    EVENT_TURN_ERROR,
    EVENT_TURN_INTERRUPTED,
}


@dataclass
class JSONRPCRequest:
    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    id: Optional[Union[str, int]] = None
    jsonrpc: str = "2.0"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
            "params": self.params,
        }
        if self.id is not None:
            d["id"] = self.id
        return d

    def encode(self) -> bytes:
        return (json.dumps(self.to_dict()) + "\n").encode("utf-8")


@dataclass
class JSONRPCResponse:
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    jsonrpc: str = "2.0"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return d

    def encode(self) -> bytes:
        return (json.dumps(self.to_dict()) + "\n").encode("utf-8")


@dataclass
class JSONRPCNotification:
    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    jsonrpc: str = "2.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
            "params": self.params,
        }

    def encode(self) -> bytes:
        return (json.dumps(self.to_dict()) + "\n").encode("utf-8")


def parse_jsonrpc_message(data: Union[str, bytes]) -> Dict[str, Any]:
    """Parse a raw JSON-RPC 2.0 message string or bytes into a dictionary."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    data = data.strip()
    if not data:
        raise ValueError("Empty message data")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("JSON-RPC message must be a JSON object")
    if payload.get("jsonrpc") != "2.0":
        raise ValueError("Missing or invalid 'jsonrpc' version; expected '2.0'")
    return payload


def build_prompt_dispatch_event(
    transcript: str,
    session_id: Optional[str] = None,
    source: str = "whisperkit",
    confidence: float = 1.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a vifi.prompt.dispatch notification payload."""
    params: Dict[str, Any] = {
        "transcript": transcript.strip(),
        "source": source,
        "confidence": confidence,
    }
    if session_id:
        params["session_id"] = session_id
    if metadata:
        params["metadata"] = metadata

    return {
        "jsonrpc": "2.0",
        "method": METHOD_PROMPT_DISPATCH,
        "params": params,
    }


def build_signal_interrupt_event(
    reason: str = "speech_detected",
    energy: float = 0.0,
    timestamp: Optional[float] = None,
) -> Dict[str, Any]:
    """Construct a vifi.signal.interrupt notification payload."""
    import time
    return {
        "jsonrpc": "2.0",
        "method": METHOD_SIGNAL_INTERRUPT,
        "params": {
            "reason": reason,
            "energy": energy,
            "timestamp": timestamp or time.time(),
        },
    }


def build_agent_event(
    event_type: str = EVENT_TURN_COMPLETE,
    agent_name: str = "Spark",
    persona: str = "Viv",
    spoken_summary: str = "",
    status: str = "success",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a vifi.agent.event notification payload."""
    params: Dict[str, Any] = {
        "event_type": event_type,
        "agent_name": agent_name,
        "persona": persona,
        "spoken_summary": spoken_summary.strip(),
        "status": status,
    }
    if details:
        params["details"] = details

    return {
        "jsonrpc": "2.0",
        "method": METHOD_AGENT_EVENT,
        "params": params,
    }
