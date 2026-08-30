---
name: voicefi-speak
description: Synthesize and speak text aloud in curated voice personas using VoiceFi MCP tools, CLI, or Edge TTS API, with strict guardrails against unsolicited speech.
---

# 🔊 VoiceFi Agent Speech Protocol & Synthesis Skill

Use this skill whenever the user asks you to speak aloud, read text, explain something verbally, audition voice synthesis, or interact in live spoken dialogues.

---

## 🚦 Golden Rules for Agent Speech

### 1. No Unsolicited In-Turn Speech
- **Strict Guardrail:** AI agents **MUST NOT** spontaneously call `voicefi_speak` or TTS tools on ordinary text responses, code explanations, or bug fixes.
- **Zero Response Latency:** Keep written text streaming immediately without blocking on audio playback.
- **When to Invoke `voicefi_speak`:**
  - When the user explicitly requests verbal speech (e.g. *"speak to me"*, *"read this out loud"*, *"say hello"*, *"explain this verbally"*).
  - When explicitly auditing or demonstrating voice synthesis capabilities upon user prompt.
  - During structured interactive dialogues (e.g. cross-agent comedy duels, roleplay).

### 2. Spoken Text Formatting & Clean-Up
Never send raw code blocks, diffs, backticks, JSON blobs, or URLs directly into TTS synthesis. Always convert the message into a concise conversational summary:
- ❌ *Bad:* Sending ````json {"status": 200, "data": [1, 2, 3]} ```` to TTS (reads out *"left curly brace quote status quote colon two hundred..."*).
- ✅ *Good:* Synthesizing *"The API returned status two hundred with three records."*
- ❌ *Bad:* Sending `https://voicefi.org/api/v1/stream?voice=Viv` to TTS.
- ✅ *Good:* Synthesizing *"The stream endpoint on VoiceFi."*

### 3. Phonetic Normalization & Heteronym Polish
- Use phonetic spelling for technical words that TTS engines mispronounce (e.g., `lyve` for live streams/servers vs `liv` for reside).
- Normalize acronyms when natural (e.g., *"S-S-E"* for Server-Sent Events, *"K-8-s"* or *"Kubernetes"* for `k8s`).

---

## 🔄 Autonomous Turn-End Hooks vs. Explicit `voicefi_speak`

VoiceFi features two complementary audio channels. Understanding their relationship prevents double-speaking:

| Channel | Mechanism | When It Occurs | Who Triggers It? |
| :--- | :--- | :--- | :--- |
| **1. Autonomous Turn-End Hooks** *(Passive)* | IDE/CLI Stop Hooks (`antigravity.py`, `claude.py`) | Automatically at turn completion | **VoiceFi Platform** intercepts the final output, speaks a concise soundbite, and opens the mic for hands-free reply. |
| **2. Explicit In-Turn Speech** *(Active)* | `voicefi_speak` MCP tool / `vifi say` | During agent reasoning | **Agent LLM** explicitly calls the tool only when the user requested spoken output. |

### 🛡️ Turn Deduplication Ledger (`claim_turn`)
When you explicitly call `voicefi_speak` during your turn, VoiceFi marks your turn signature as claimed in its cross-process deduplication ledger (`claim_turn`). When your turn finishes, the lifecycle Stop hook detects that speech already occurred and **will not double-speak**.
- **TTL & Expiry Safety:** Claims have a default 30-second TTL to ensure that if an agent crashes or aborts before the turn hook fires, the mute lock is automatically released and never permanently blocks future audio turns.

### ⚙️ Hook Controls
- `vifi hook status`: Check active status of Antigravity & Claude Code Stop hooks.
- `vifi pause` / `vifi resume`: Globally toggle voice feedback and microphone handoffs.
- `vifi hook disable` / `vifi hook enable`: Enable or disable turn-end hooks without editing configuration files.

---

## 🛠️ Execution Methods

### 1. Model Context Protocol (`voicefi_speak`)
When using MCP, call `voicefi_speak`:

```json
{
  "name": "voicefi_speak",
  "arguments": {
    "text": "Hello! I am speaking to you using VoiceFi's neural voice engine.",
    "persona": "Viv",
    "agent_name": "antigravity",
    "agent_role": "pair_programmer",
    "conv_id": "b19db885-9c42-4d80-b588-02621156d448",
    "block": true
  }
}
```

- **`text`** *(string, required)*: Spoken soundbite (plain conversational prose).
- **`persona`** / **`voice`** *(string, optional)*: Persona name (e.g. `Ava (Premium)`, `Viv`, `Stefan`, `Christopher`, `Emily`, `Aria`, `Sonia`). Defaults to active agent persona.
- **`agent_name`** *(string, optional)*: Agent identifier (`antigravity`, `claude`, `cursor`).
- **`agent_role`** *(string, optional)*: Role descriptor passed for logging and context routing (`pair_programmer`, `code_reviewer`).
- **`conv_id`** *(string, optional)*: Conversation ID for tracking multi-agent thread provenance and deduplication.
- **`block`** *(boolean, optional, default: `true`)*: Hold tool execution until audio playback completes on macOS speakers/AirPods.

---

### 2. Command-Line Interface (CLI)

```bash
# Speak text in active agent persona:
vifi say "Build succeeded. All fourteen unit tests are passing."

# Test or audition a specific persona:
vifi voice test "Viv" -t "Hey! Checking instant neural synthesis."
vifi voice test "Ava (Premium)" -t "Hello from zero-millisecond offline Apple Silicon speech."

# Silent TTFB ping / throughput benchmark:
vifi ping "Viv"
```

---

### 3. High-Fidelity 48kHz Edge TTS REST API
For web applications and remote agents:

```bash
# GET stream
curl -s "https://voicefi.org/api/tts?voice=Viv&text=VoiceFi+ambient+protocol+ready." --output speech.mp3

# POST JSON payload
curl -s -X POST "https://voicefi.org/api/tts" \
  -H "Content-Type: application/json" \
  -d '{"voice": "Christopher", "text": "Architectural refactoring complete.", "agent_role": "antigravity"}' \
  --output speech.mp3
```

---

### 4. Halting Active Speech (Barge-In & Stop)
If speech must be halted immediately:
- **MCP:** Call `voicefi_stop()`
- **CLI:** Run `vifi stop` / `vifi voice stop`
- **Acoustic Safe Mode:** Speaking firmly into the microphone triggers automatic hardware barge-in interruption.
