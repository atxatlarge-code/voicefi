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

# Or use the shortcut alias:
vifi remote
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
