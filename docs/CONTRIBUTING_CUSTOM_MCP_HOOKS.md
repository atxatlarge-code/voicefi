# Contributing Agent Lifecycle Hooks & Custom MCP Tools

VoiceFi functions as the universal voice and command layer for AI coding agents. It connects deeply with agents via two primary interfaces:
1. **Agent Lifecycle Hooks** (Antigravity Stop Hooks and Claude Code hooks) for hands-free spoken feedback loops and zero-flicker background IPC.
2. **Native MCP Server** (Model Context Protocol stdio JSON-RPC 2.0) exposing voice synthesis, VAD recording, sound effects, and cross-agent dispatching tools to Antigravity, Claude Code, Cursor, Windsurf, and Zed.

This guide provides the complete architectural breakdown and developer tutorial for authoring custom lifecycle hooks, speech cleansing pipelines, and new MCP tools.

---

## 1. Architectural Overview

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               AI Agent Lifecycle & MCP Bridge                          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│   ┌─────────────────────────────────┐           ┌──────────────────────────────────┐   │
│   │     Agent Stop Hook Flow        │           │    Native MCP Server (stdio)     │   │
│   │   (Antigravity / Claude Code)   │           │      (src/voicefi/mcp_server.py) │   │
│   └────────────────┬────────────────┘           └────────────────┬─────────────────┘   │
│                    │                                             │                     │
│                    ▼                                             ▼                     │
│       Stdin Hook JSON Payload                     JSON-RPC 2.0 `tools/call`            │
│       {"agent": "...", "last_message": "..."}      {"name": "voicefi_...", ...}         │
│                    │                                             │                     │
│                    ▼                                             ▼                     │
│       `clean_markdown_for_speech()`               `execute_tool(name, args)`           │
│       (Strips code, paths, tables)                               │                     │
│                    │                                             ▼                     │
│                    ▼                              `_tool_<name>(self, args)`           │
│       `get_tts_engine().speak()`                                 │                     │
│       (Dynamic Island HUD Visualizer)                            ▼                     │
│                    │                              Structured Response Payload          │
│                    ▼                              {"content": [...], "isError": bool}  │
│       `AudioRecorder().record_speech_auto()`                     │                     │
│       (Silero VAD + Whisper STT)                                 ▼                     │
│                    │                              `capture_mcp_tool_call()`            │
│                    ▼                              (Sanitized Zero-PII Telemetry)       │
│       Zero-Flicker Background IPC                                                      │
│       `send_message_to_antigravity()`                                                  │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Agent Lifecycle Hooks Architecture

### 2.1 The Antigravity Stop Hook Lifecycle

When an Antigravity agent finishes its turn, it triggers the registered stop hook script configured via `vifi setup`. The payload is delivered via `stdin` as JSON:

```json
{
  "agent": "antigravity",
  "conv_id": "80fcf29a-86be-4661-9413-d58e09f7e1fb",
  "last_message": "### Implementation Summary\nI've updated `auth.py` and all 14 unit tests are passing.\n\nWould you like me to push the branch and open a PR?"
}
```

The hook handler in `src/voicefi/integrations/antigravity.py` executes the full-duplex conversational loop:
1. **Turn Claiming (`claim_turn`)**: Deduplicates incoming turns to ensure the user isn't prompted multiple times for the same event.
2. **Markdown Cleansing (`clean_markdown_for_speech`)**: Filters dense code, tables, and markup into a punchy 1-2 sentence spoken soundbite.
3. **Spoken Announcement (`speak`)**: Synthesizes speech using the agent's assigned voice persona (e.g. `Viv` or `Ava (Premium)`) while displaying the morphing waveform on the Dynamic Island HUD.
4. **Autonomous Microphone Handoff (`record_speech_auto`)**: Opens the microphone, monitors for human speech using Silero VAD, and streams live transcripts to the HUD.
5. **Zero-Flicker Background IPC (`send_message_to_antigravity`)**: Directly submits the transcribed prompt back to the originating Antigravity conversation without stealing window focus or touching the clipboard.

---

## 3. Markdown Cleansing for Voice Synthesis

Raw agent outputs often contain hundreds of lines of code, markdown tables, stack traces, and terminal logs. Feeding raw markdown to a TTS engine produces incomprehensible audio (reading backtick symbols, brackets, and raw hex addresses).

VoiceFi provides `clean_markdown_for_speech(text, max_words=60)` in `src/voicefi/integrations/antigravity.py` to extract concise, natural spoken soundbites.

### Cleansing Pipeline Stages

```python
from voicefi.integrations.antigravity import clean_markdown_for_speech

raw_agent_message = """
### Test Results
| Test Name | Status |
|---|---|
| test_auth_login | PASSED |
| test_jwt_token | PASSED |

```python
def verify_token(token: str) -> bool:
    return True
```

Refactored authentication middleware in `/Users/developer/Projects/VoiceFi/src/voicefi/auth.py`.
Should I proceed with deploying the changes to staging?
"""

cleaned = clean_markdown_for_speech(raw_agent_message, max_words=60)
print(cleaned)
# Output: "Refactored authentication middleware in auth.py. Should I proceed with deploying the changes to staging?"
```

### Cleansing Rules:
1. **Size Bounding**: If input exceeds 4,000 characters, it retains the initial context (first 1,000 chars) and conclusion (last 2,000 chars) to maintain regex performance.
2. **Error & Stack Trace Extraction**: Raw Python stack traces are condensed to: `"The agent encountered an error: <ErrorName>: <Detail>."`
3. **Code & Table Stripping**: Regex removes triple backtick blocks (```` ```...``` ````) and markdown table rows (`| ... |`).
4. **Path Normalization**: Absolute file paths are shortened to file basenames (`/path/to/auth.py` -> `auth.py`).
5. **Header & Bullet Cleanup**: Leading hashes (`###`), bullets (`-`, `*`, `1.`), and blockquotes (`>`) are stripped, ensuring terminal punctuation (`.`) on line boundaries.
6. **Emoji & Unicode Stripping**: Unicode emojis and symbols are stripped to prevent TTS engines from vocalizing emoji names.
7. **Trailing Question Prioritization**: If the agent ended its turn with a question (`?`), the cleanser pairs the first summarizing sentence with the final question within the word budget (`max_words=60`).

---

## 4. Zero-Flicker Background IPC Dispatching

Unlike traditional voice assistants that hijack the system clipboard and simulate `Cmd+V` keystrokes (causing screen flicker and stealing keyboard focus), VoiceFi delivers transcribed voice prompts directly via native Inter-Process Communication (IPC).

In `src/voicefi/integrations/injector.py`:

```python
from voicefi.integrations.injector import send_message_to_antigravity, DispatchResult

result: DispatchResult = send_message_to_antigravity(
    conv_id="80fcf29a-86be-4661-9413-d58e09f7e1fb",
    text="Deploy to staging and run the smoke tests.",
    sender_name="Developer Voice",
    title="Voice Turn Handoff",
)

if result.success:
    print(f"Message delivered via {result.delivery_type} to conversation {result.target_conv_id}")
else:
    print(f"Delivery failed: {result.error}")
```

### How `send_message_to_antigravity` Operates:
1. **Binary Discovery**: Locates the native Antigravity CLI binary at `~/.gemini/antigravity/bin/agentapi`.
2. **Conversation Correlation**: Automatically resolves `"reply"` keywords to the active or originating conversation ID via `ConversationTracker`.
3. **Subprocess Execution**: Invokes `agentapi send-message --title="..." <conv_id> <text>` with authentication environment headers.
4. **Zero Window Manipulation**: Executes 100% in the background. The developer can keep typing in another window without losing focus.

---

## 5. Extending the Native MCP Server

VoiceFi includes a high-performance Stdio JSON-RPC 2.0 server (`src/voicefi/mcp_server.py`) compliant with the Model Context Protocol (MCP 2024-11-05 standard).

### Step-by-Step: Adding a New Tool to `mcp_server.py`

Let's implement a new MCP tool: **`voicefi_ask_confirmation`**.  
This tool allows AI agents to speak a confirmation question aloud to the developer and wait for a spoken `"yes"` / `"no"` / `"proceed"` response before taking destructive actions (like dropping a database or deleting files).

---

### Step 1: Define Tool Schema in `MCP_TOOLS`

In `src/voicefi/mcp_server.py`, add your tool definition to `MCP_TOOLS`:

```python
# In src/voicefi/mcp_server.py

MCP_TOOLS: List[Dict[str, Any]] = [
    # ... existing tools (voicefi_speak, voicefi_listen, etc.) ...
    {
        "name": "voicefi_ask_confirmation",
        "description": "Speak a confirmation question aloud to the user and wait for a spoken affirmative/negative response.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The question to ask aloud (e.g. 'Are you sure you want to delete database records?').",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Maximum seconds to wait for user to speak (default: 8).",
                },
                "persona": {
                    "type": "string",
                    "description": "Optional voice persona to use for the prompt.",
                },
            },
            "required": ["prompt"],
        },
    },
]
```

---

### Step 2: Route Tool in `execute_tool()`

In `VoiceFiMCPServer.execute_tool()`, add the dispatcher branch:

```python
# In src/voicefi/mcp_server.py -> VoiceFiMCPServer.execute_tool()


def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    start_t = time.time()
    res = None
    err_type = None
    agent_name = args.get("agent_name") or args.get("agent") or "antigravity"
    persona = args.get("persona")

    try:
        if name == "voicefi_speak":
            res = self._tool_speak(args)
        elif name == "voicefi_listen":
            res = self._tool_listen(args)
        elif name == "voicefi_stop":
            res = self._tool_stop(args)
        elif name == "voicefi_status":
            res = self._tool_status(args)
        elif name == "voicefi_set_voice":
            res = self._tool_set_voice(args)
        elif name == "voicefi_ping_voice":
            res = self._tool_ping_voice(args)
        elif name == "voicefi_send":
            res = self._tool_send(args)
        elif name == "voicefi_sfx":
            res = self._tool_sfx(args)
        # --- Add new tool branch ---
        elif name == "voicefi_ask_confirmation":
            res = self._tool_ask_confirmation(args)
        else:
            res = {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }
        return res
    except Exception as e:
        err_type = type(e).__name__
        logger.exception("Error executing tool %s: %s", name, e)
        return {
            "content": [{"type": "text", "text": f"Error executing {name}: {str(e)}"}],
            "isError": True,
        }
    finally:
        dur_ms = max(1, int((time.time() - start_t) * 1000))
        is_error = bool(res and res.get("isError", False))
        try:
            from voicefi.telemetry import capture_mcp_tool_call

            capture_mcp_tool_call(
                tool_name=name,
                duration_ms=dur_ms,
                caller_agent=agent_name,
                persona=persona,
                success=(not is_error and err_type is None),
                error_type=err_type,
            )
        except Exception:
            pass
```

---

### Step 3: Implement Tool Handler Method

Implement `_tool_ask_confirmation` in `VoiceFiMCPServer`:

```python
# In src/voicefi/mcp_server.py -> VoiceFiMCPServer


def _tool_ask_confirmation(self, args: Dict[str, Any]) -> Dict[str, Any]:
    from voicefi.config import load_config
    from voicefi.tts import get_tts_engine
    from voicefi.audio.recorder import AudioRecorder
    from voicefi.stt import get_stt_engine

    prompt_text = args.get("prompt", "").strip()
    if not prompt_text:
        return {
            "content": [{"type": "text", "text": "Missing required argument 'prompt'."}],
            "isError": True,
        }

    persona = args.get("persona")
    timeout = float(args.get("timeout", 8.0))
    cfg = load_config()

    # 1. Speak question aloud
    tts = get_tts_engine(cfg, agent_name="antigravity", voice_override=persona)
    tts.speak(prompt_text, block=True)

    # 2. Open mic and listen for response
    recorder = AudioRecorder(
        sample_rate=cfg.vad.sample_rate,
        energy_threshold=cfg.vad.energy_threshold,
        silence_duration=cfg.vad.silence_duration,
        max_record_seconds=10,
        barge_in=False,
    )
    audio_data, temp_wav = recorder.record_speech_auto(timeout=timeout)

    if not temp_wav or not Path(temp_wav).is_file():
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "confirmed": False,
                            "spoken_text": "",
                            "reason": "Timed out waiting for response.",
                        }
                    ),
                }
            ],
            "isError": False,
        }

    try:
        stt = get_stt_engine(cfg)
        spoken_response = (stt.transcribe(temp_wav) or "").strip().lower()
    finally:
        Path(temp_wav).unlink(missing_ok=True)

    # 3. Classify intent
    affirmative_tokens = {
        "yes",
        "yeah",
        "yep",
        "sure",
        "proceed",
        "go ahead",
        "do it",
        "confirm",
        "ok",
        "okay",
    }
    negative_tokens = {"no", "nope", "cancel", "stop", "don't", "abort", "wait"}

    words = set(re.findall(r"\b\w+\b", spoken_response))
    confirmed = bool(words & affirmative_tokens) and not bool(words & negative_tokens)

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "confirmed": confirmed,
                        "spoken_text": spoken_response,
                        "confidence": "high"
                        if (confirmed or words & negative_tokens)
                        else "ambiguous",
                    }
                ),
            }
        ],
        "isError": False,
    }
```

---

## 6. Unit Testing Custom MCP Tools

Create `tests/test_custom_mcp_tool.py` to verify the JSON-RPC interface and handler behavior:

```python
"""
Unit tests for custom MCP tools in VoiceFiMCPServer.
"""

import json
from unittest.mock import patch, MagicMock
import pytest

from voicefi.mcp_server import VoiceFiMCPServer, MCP_TOOLS


@pytest.fixture
def server():
    return VoiceFiMCPServer()


def test_custom_tool_in_tools_list(server):
    """Verify tool is exposed in tools/list response."""
    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/list",
        "params": {},
    }
    resp = server.handle_request(req)
    assert resp is not None
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    assert "voicefi_ask_confirmation" in tool_names

    schema = next(t for t in tools if t["name"] == "voicefi_ask_confirmation")
    assert "prompt" in schema["inputSchema"]["required"]


def test_ask_confirmation_tool_call_affirmative(server):
    """Verify affirmative user response evaluates to confirmed: True."""
    mock_tts = MagicMock()
    mock_recorder = MagicMock()
    mock_recorder.record_speech_auto.return_value = (b"...", "/tmp/test_affirm.wav")

    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "Yes, proceed with the deployment."

    with (
        patch("voicefi.tts.get_tts_engine", return_value=mock_tts),
        patch("voicefi.audio.recorder.AudioRecorder", return_value=mock_recorder),
        patch("voicefi.stt.get_stt_engine", return_value=mock_stt),
        patch("pathlib.Path.is_file", return_value=True),
        patch("pathlib.Path.unlink"),
    ):
        req = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "voicefi_ask_confirmation",
                "arguments": {
                    "prompt": "Should I push changes?",
                },
            },
        }
        resp = server.handle_request(req)

        assert resp is not None
        assert resp["id"] == 11
        assert "result" in resp

        content = resp["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data["confirmed"] is True
        assert data["spoken_text"] == "yes, proceed with the deployment."


def test_ask_confirmation_tool_call_negative(server):
    """Verify negative user response evaluates to confirmed: False."""
    mock_tts = MagicMock()
    mock_recorder = MagicMock()
    mock_recorder.record_speech_auto.return_value = (b"...", "/tmp/test_neg.wav")

    mock_stt = MagicMock()
    mock_stt.transcribe.return_value = "No, stop that right now."

    with (
        patch("voicefi.tts.get_tts_engine", return_value=mock_tts),
        patch("voicefi.audio.recorder.AudioRecorder", return_value=mock_recorder),
        patch("voicefi.stt.get_stt_engine", return_value=mock_stt),
        patch("pathlib.Path.is_file", return_value=True),
        patch("pathlib.Path.unlink"),
    ):
        req = {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "voicefi_ask_confirmation",
                "arguments": {
                    "prompt": "Delete database?",
                },
            },
        }
        resp = server.handle_request(req)
        content = resp["result"]["content"][0]["text"]
        data = json.loads(content)
        assert data["confirmed"] is False
```

Run tests:
```bash
pytest tests/test_custom_mcp_tool.py -v
```

---

## 7. Interactive Stdio Debugging with `vifi mcp`

You can test your tool interactively via terminal standard input:

```bash
vifi mcp
```

Paste JSON-RPC requests directly into the terminal:
```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0"}}}
{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "voicefi_ask_confirmation", "arguments": {"prompt": "Ready to run tests?"}}}
```
