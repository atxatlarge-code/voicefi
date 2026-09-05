---
name: remote-companion
description: Connect and stream hands-free two-way voice conversations with Antigravity and Claude Code over mobile PWA, WebSockets, or Cloudflare Relay.
---

# 📱 VoiceFi Remote Companion & Mobile Voice Bridge

Use this skill when the developer wants to pair a mobile phone, tablet, or Apple Watch, conduct pacing voice sessions away from the desk, or inspect live agent turns on a remote device.

---

## 🌟 Overview

The **VoiceFi Remote Companion** (`https://companion.voicefi.app`) is a progressive web app (PWA) that connects your mobile device directly to your local development environment via a secure full-duplex WebSocket relay.

- **Pacing Thought & Voice Memos:** Dictate tasks, ask questions, or ramble about architecture while walking around.
- **Hands-Free Agent Loops:** Hear the agent's concise spoken responses through your AirPods or phone speakers, and have the mic automatically open for your follow-up.
- **Live Output & Artifacts:** View formatted markdown responses, syntax-highlighted code diffs, and tool execution status on your mobile screen in real time.

---

## 🚀 Quick Pairing & Connection

### 1. Launch Companion from Terminal
Run the companion command from your project root:

```bash
# Launch companion server and print pairing QR code:
vifi companion

# Or use the shortcut aliases:
vifi rc
vifi remote

# Open companion directly to the Spicewood, Texas lead sheet & audio beat:
vifi rc sheet
```

This starts the background WebSocket hub on Port `5141` and prints an ASCII QR code directly into your terminal.

### 2. Connect via Mobile PWA
Scan the QR code with your phone camera or navigate to:
- **Cloud Relay (Recommended):** `https://companion.voicefi.app`
- **Local Network Web UI:** `http://<your-mac-ip>:5141/companion` (or `http://localhost:5141/companion`)

Once paired, your phone session binds to your local agent environment with zero port forwarding required.

---

## 🔒 Relay Architecture & Endpoints

VoiceFi supports two complementary transport layers for companion connectivity:

| Layer | URL Endpoint | Transport Protocol | Use Case |
| :--- | :--- | :--- | :--- |
| **Cloud Relay** | `wss://companion.voicefi.app/v1/relay` | Cloudflare Durable Objects | Secure TLS-encrypted cloud relay for mobile connectivity on cellular data or outside networks. |
| **Local Hub** | `ws://localhost:5141/api/relay` (or `ws://<your-mac-ip>:5141/api/relay`) | Local WebSocket Server (Port 5141) | Ultra-low latency local LAN streaming with zero external internet egress. |

---

## 🎙️ Mobile Voice Capabilities

### 1. Hands-Free Turn Handoffs
When you send a voice message from your mobile companion:
1. Mobile microphone records your spoken query with client-side VAD (Voice Activity Detection).
2. Transcribed audio is injected directly into Antigravity or Claude Code with zero screen flicker.
3. When the agent completes its turn, the spoken response streams back over the WebSocket and plays aloud on your phone or connected AirPods.
4. The mobile microphone automatically reactivates for your next prompt.

### 2. Apple Watch Trigger
Tap the VoiceFi complication on your Apple Watch or lock screen to trigger an immediate dictation turn to your active IDE agent.

### 3. Voice Memos & Architectural Brain Dumps
Capture 2–5 minute stream-of-consciousness rambles directly from mobile. The transcript is buffered and automatically converted into an implementation plan and Mermaid diagram.

---

## 🛡️ Synchronization & Concurrency Invariants (Lessons Learned)

*(Comprehensive architecture documentation: [`docs/COMPANION_VOICE_LOOP_LESSONS_LEARNED.md`](file:///Users/jaketrigg/Projects/VoiceFi/docs/COMPANION_VOICE_LOOP_LESSONS_LEARNED.md))*

When extending, debugging, or operating the Remote Companion voice loop, all agents and developers must uphold these **6 architectural invariants**:

1. **No "Stop Echo" on Telemetry Reception:**
   - When the client receives `speech_stopped` or `stop` from the server, it must only run local audio/UI teardown: `stopAllAgentSpeech(broadcastServer = false)`.
   - Never allow handling a server event to emit an outbound `POST /api/stop` or `{ type: "stop" }` back to the server, which creates an infinite 90ms cancellation ping-pong loop.

2. **Concurrency Timestamps Bound Inside Mutexes:**
   - In queued synthesis pipelines (`edge_tts.py`, `mac_say.py`, `gemini_tts.py`), `turn_start_time = time.time()` and `_stop_requested = False` must be re-initialized **inside** `with speech_turn_lock(...)`.
   - Never sample the start timestamp prior to acquiring the mutex, or turns waiting in line will evaluate stale timestamps against previous stops.

3. **Multi-Sentence Sentence Pipelining Canary:**
   - Single-sentence responses may mask timing bugs. Multi-sentence structures (like jokes with a setup and punchline separated by punctuation) stream chunk-by-chunk through background fetcher threads and queue workers, exposing timestamp race conditions. Always validate with multi-sentence dialogue.

4. **Server-Side Debouncing on Destructive Endpoints:**
   - Endpoints modifying lifecycle state (`POST /api/stop`, WebSocket `stop`) must enforce a 500ms sliding debounce threshold on the server to absorb mobile network packet retry storms and rapid UI taps.

5. **PWA & Service Worker Invalidation Protocol:**
   - Any client-side patch requires an atomic cache version bump (`CACHE_NAME = 'voicefi-companion-vXX'`) in `sw.js` and an immediate Cloudflare edge deployment. Mobile Safari PWAs aggressively retain stale cached application code unless the cache version changes.

6. **Dual-Acoustic Ground Truth Canary:**
   - Retain `mute_mac_when_companion_active: false` in `~/.voicefi/config.yaml` during testing. Mac desktop speakers act as an independent physical canary, isolating audio delivery failures between server-side generation and mobile transport.

