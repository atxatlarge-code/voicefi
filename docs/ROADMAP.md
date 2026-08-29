# 🗺️ VoiceFi™ Open Source Developer Adoption Roadmap
> **The Universal Voice & Command Layer for AI Coding Agents, MCP Tools, and Terminals**  
> *Last Updated: August 2026* • *Version: 1.0.0*

---

## 🌟 Executive Vision & Core Philosophy

VoiceFi transforms how software engineers and autonomous AI coding agents collaborate. Instead of silent terminal walls of text and screen-hijacking popups, VoiceFi establishes a **sub-millisecond acoustic layer** that brings AI pair programming to life through instant offline neural synthesis, intelligent ambient listening, cross-agent comedy sound effects, and seamless multi-tool command routing.

Our open-source roadmap is structured around three transformative phases designed to drive developer delight, rapid ecosystem expansion, and decentralized voice innovation:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    VOICEFI 3-PHASE ROADMAP                                       │
├──────────────────────────────┬───────────────────────────────────┬───────────────────────────────┤
│          PHASE 1             │             PHASE 2               │            PHASE 3            │
│   Zero-Friction Launch &     │   Agent Ecosystem Expansion &     │   Open Voice Store, Cloning   │
│        Core Bridge           │         Acoustic Banter           │        & Edge Hardware        │
│       (Current Focus)        │         (Months 2 – 4)            │         (Months 5 – 8)        │
├──────────────────────────────┼───────────────────────────────────┼───────────────────────────────┤
│ • 0ms Apple Neural Ava       │ • Cross-Agent Joke Duels          │ • Community Persona Registry  │
│ • 1-Command Agent Setup      │ • Cursor / Zed / Windsurf Plugins │ • F5-TTS Zero-Shot Cloning    │
│ • Antigravity ↔ Claude IPC   │ • Kokoro 82M Offline Linux TTS    │ • Edge Hardware / ESP32 Hub   │
│ • 8 Native MCP Stdio Tools   │ • Streaming STT WebSockets        │ • Multimodal Acoustic Vision  │
│ • Floating Dynamic Island HUD│ • HTML5 Web Audio Companion       │ • Global Latency Leaderboards │
└──────────────────────────────┴───────────────────────────────────┴───────────────────────────────┘
```

---

## 🚀 Phase 1: Zero-Friction Launch & Core Bridge (Current)

The primary goal of Phase 1 is delivering an **effortless, sub-60-second developer setup** on macOS while establishing bulletproof audio primitives across CLI, MCP, REST, and Python SDK access surfaces.

```
                  ┌──────────────────────────────────────────────┐
                  │           Developer / Terminal User          │
                  └──────┬──────────────────────┬──────────────┬─┘
                         │ (CLI / Shortcuts)    │ (MCP Stdio)  │ (HTTP REST)
                         ▼                      ▼              ▼
              ┌────────────────────────────────────────────────────────┐
              │              VoiceFi Universal Interface               │
              │  - CLI: `vifi setup`, `vifi speak`, `vifi listen`      │
              │  - MCP: `voicefi_speak`, `voicefi_send`, `voicefi_sfx` │
              │  - REST: `http://localhost:5141/api/*`                 │
              └──────────────────────────┬─────────────────────────────┘
                                         │
                                         ▼
              ┌────────────────────────────────────────────────────────┐
              │             Core Acoustic & IPC Engine                 │
              │  • 0ms Offline Apple Silicon Neural Ava Engine         │
              │  • Full-Duplex VAD & Acoustic Safe-Mode Barge-In       │
              │  • AppKit Floating Dynamic Island HUD Window           │
              │  • Antigravity ↔ Claude Code IPC Protocol Envelope     │
              └────────────────────────────────────────────────────────┘
```

### 1.1 Key Deliverables & Capabilities

| Capability | Technical Specification | Developer Impact |
| :--- | :--- | :--- |
| **0ms Offline Neural Ava** | Native macOS Apple Silicon SpeechSynthesis engine binding (`vifi voice download-ava`). Zero network hops, 100% offline, 0ms TTFB. | Zero lag, private, natural pair programming companion without cloud API keys. |
| **1-Command Agent Pairing** | `vifi setup --dev` or `vifi setup --all` auto-registers lifecycle hooks and MCP entries in Antigravity (`~/.gemini/config/plugins/`) and Claude Code (`~/.claude/`). | From git clone to active voice-enabled agent in under 60 seconds. |
| **Antigravity ↔ Claude Code IPC Bridge** | Standardized JSON-RPC & CLI message envelope (`vifi send --to claude`, `voicefi_send`) with correlation tracking and reactive waking. | True multi-agent swarms where agents delegate tasks and return results seamlessly. |
| **8 Native MCP Stdio Tools** | `voicefi_speak`, `voicefi_listen`, `voicefi_stop`, `voicefi_status`, `voicefi_set_voice`, `voicefi_ping_voice`, `voicefi_send`, `voicefi_sfx`. | Plug-and-play MCP compatibility for Antigravity, Claude Desktop, Cursor, and Windsurf. |
| **Floating Dynamic Island HUD** | AppKit Cocoa borderless floating window (`UnifiedDynamicIslandHUD`) with real-time waveform oscillations, speech popups, and dictation. | Non-intrusive visual feedback anchored to the macOS status bar without focus stealing. |
| **Acoustic Safe Mode & Barge-In** | Dynamic hardware sensing (`AudioDeviceManager`) distinguishing headphones (full duplex) from speakers (anti-bleed safe mode). | Zero premature cutoffs or feedback loops when playing through laptop speakers. |

### 1.2 Phase 1 Milestone Verification Checklist
- [x] Sub-60s pairing with Antigravity and Claude Code via `vifi setup`.
- [x] Complete test suite execution across 62+ test suites with mocked audio isolation.
- [x] 8 MCP tools fully registered with JSON Schema validation in `src/voicefi/mcp_server.py`.
- [x] Homebrew distribution formula available in `Formula/vifi.rb`.

---

## ⚡ Phase 2: Agent Ecosystem Expansion & Acoustic Banter (Months 2 – 4)

Phase 2 broadens VoiceFi's reach across popular code editors (Cursor, Zed, Windsurf, Neovim), introduces cross-platform offline neural TTS via Kokoro 82M on Linux & Intel Macs, and brings playful personality to multi-agent collaboration with cross-agent joke duels and sound effects.

```
   ┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
   │  Cursor / Zed /  │      │ Antigravity Core │      │ Claude Code CLI  │
   │  Windsurf / Nvim │      │  Agent (Viv/Ava) │      │ (Christopher)    │
   └────────┬─────────┘      └────────┬─────────┘      └────────┬─────────┘
            │                         │                         │
            │                         │ `vifi duel --challenge` │
            │                         ├────────────────────────►│
            │                         │                         │
            │                         │ `vifi send --joke`      │
            │                         │◄────────────────────────┤
            │                         │                         │
            │                         │ `voicefi_sfx(rimshot)`  │
            │                         ├────────────────────────►│ [Ba-Dum-Tss! 🥁]
            ▼                         ▼                         ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                  VoiceFi Streaming & Audio Engine                    │
   │  • Kokoro 82M ONNX Neural Engine (Linux, Windows, Intel Macs)        │
   │  • WebSocket Streaming STT Gateway (`/ws/transcribe`)                │
   │  • Web Audio Interactive HUD & Visualizer (`http://localhost:5141`)  │
   └──────────────────────────────────────────────────────────────────────┘
```

### 2.1 Key Deliverables & Capabilities

#### A. Cross-Agent Joke Duels & Comedy Banter Engine
- **Command & Protocol**: `vifi duel --topic "refactoring" --rounds 3` and `voicefi_sfx(name="drum_smash")`.
- **Acoustic Soundboard**: Procedural NumPy sound effects (rimshot, horn honk, sad trombone, applause, boing, crickets) played autonomously when tests fail, linters complain, or PRs merge.
- **Specification**: Fully adheres to [CROSS_AGENT_COMEDY_SPEC.md](./CROSS_AGENT_COMEDY_SPEC.md).

#### B. Native Editor Integrations & MCP Setup Generators
- **Cursor**: Automated generation and updating of `.cursor/mcp.json` with project-isolated virtual environments.
- **Zed Editor**: Automatic injection into `~/.config/zed/settings.json` under `context_servers.voicefi`.
- **Windsurf Cascade**: Native integration for Cascade prompt hooks and audio turn handoffs.
- **Neovim (`voicefi.nvim`)**: Community Lua plugin providing statusline audio waveforms and floating acoustic transcript buffers.

#### C. Kokoro 82M Offline Neural TTS Provider (Linux & Windows Support)
- **Engine**: Lightweight 82-million parameter ONNX neural voice model (`kokoro-onnx`).
- **Target Performance**: <180ms Time-to-First-Byte (TTFB) on Linux x86_64, Windows, and Intel Macs.
- **Implementation Path**: `src/voicefi/tts/kokoro.py` implementing `BaseTTS`.

#### D. Streaming STT WebSocket Protocol (`/ws/transcribe`)
- **Protocol**: Real-time bidirectional WebSocket streaming raw PCM 16kHz audio chunks.
- **Backends**: Pluggable streaming Whisper, Groq Whisper API, or local faster-whisper.
- **Low Latency**: Emits live interim transcript tokens (`on_live_transcript`) to HUDs and editors with <80ms latency.

#### E. Web Audio Companion & Interactive HTML5 HUD
- **Web Interface**: Lightweight web companion served at `http://localhost:5141/panel`.
- **Visualizers**: Web Audio API canvas frequency analyzers, audio meter rings, and interactive persona audition carousel.

---

## 🌐 Phase 3: Open Voice Store, Voice Cloning & Edge Hardware (Months 5 – 8)

Phase 3 transitions VoiceFi into a **decentralized, community-driven voice ecosystem**, allowing developers to create, share, and clone voice personas, deploy VoiceFi to standalone edge hardware, and interact with agents through multimodal acoustic vision prompts.

```
       ┌─────────────────────────────────────────────────────────────┐
       │             Open Voice Store & Persona Registry             │
       │           (community-voices.voicefi.org / YAML Packs)        │
       └──────────────────────────────┬──────────────────────────────┘
                                      │ `vifi persona install cyberpunk-coder`
                                      ▼
┌─────────────────────────┐   ┌───────────────────────────┐   ┌───────────────────────────┐
│   Zero-Shot Voice Clone │   │   Edge Hardware Voice Hub │   │ Multimodal Acoustic Vision│
│   (F5-TTS 5s Reference) │   │  (Raspberry Pi 5 / ESP32) │   │ (Voice-Directed DOM & UI) │
│                         │   │                           │   │                           │
│ • Record 5-second sample│   │ • Standalone Desk Mic Hub │   │ • Spoken UI Debugging     │
│ • Local ONNX embedding  │   │ • Home Assistant Satellite│   │ • DevTools MCP OCR Audits │
│ • Instant custom voice  │   │ • 0-screen voice node     │   │ • Audible layout fixes    │
└─────────────────────────┘   └───────────────────────────┘   └───────────────────────────┘
```

### 3.1 Key Deliverables & Capabilities

#### A. Open Voice Store & Community Persona Registry
- **Decentralized Catalog**: Git-based community registry (`voicefi/community-voices`) for curated voice personas.
- **Packaging Format**: Declarative `persona.yaml` defining pitch, rate, system prompt bias, acoustic chime triggers, and fallback voice mappings.
- **CLI Management**:
  ```bash
  vifi persona search "cyberpunk"
  vifi persona install "jake-trigg/cyberpunk-coder"
  vifi persona test "cyberpunk-coder"
  ```

#### B. Custom F5-TTS Zero-Shot Voice Cloning
- **Local Clone Engine**: Zero-shot voice cloning utilizing 5 to 10 seconds of reference audio (`vifi clone`).
- **Privacy First**: 100% local ONNX/PyTorch inference without cloud transmission.
- **Workflow**:
  ```bash
  vifi clone record "my-voice" --seconds 10
  vifi clone set antigravity "my-voice"
  ```

#### C. Edge Hardware & Home Assistant Voice Satellite Hub
- **Raspberry Pi 5 Hub**: Headless Linux daemon turning a Raspberry Pi and USB conference mic into an ambient coding hub.
- **ESP32 Audio Satellite Bridge**: Ultra-low-power microcontrollers acting as remote acoustic microphones and speakers over Wi-Fi/UDP.
- **Home Assistant Integration**: Auto-discovery of VoiceFi nodes as media players and voice assist satellites.

#### D. Multimodal Acoustic Vision Prompts
- **Hands-Free UI Inspection**: "VoiceFi, why is the hero image overflowing on mobile?"
- **Chrome DevTools MCP Bridge**: VoiceFi triggers Chrome DevTools MCP tools, performs DOM audits, and speaks concise acoustic remediation summaries.

#### E. Global Acoustic Telemetry & Latency Leaderboard
- **Public Benchmark Portal**: Automated benchmarking suite running against cloud and local engines (`vifi ping --all --benchmark`).
- **Public Dashboard**: Live ranking at `voicefi.org/benchmarks` comparing TTFB, throughput (chars/sec), and MOS audio quality across TTS providers.

---

## 🔒 Architecture & Cross-Cutting Guarantees

Throughout all three roadmap phases, VoiceFi adheres to strict architectural principles:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 CROSS-CUTTING DESIGN PRINCIPLES                                  │
├──────────────────────────┬───────────────────────────────────┬───────────────────────────────────┤
│    Zero-PII Privacy      │       Sub-Millisecond TTFB        │     Fault-Tolerant Fallback       │
│ Audio recordings and     │ Local synthesis executes with     │ If any cloud provider fails,      │
│ transcripts never leave  │ <50ms latency. No unnecessary     │ VoiceFi instantly falls back to   │
│ localhost unless cloud   │ network roundtrips for local      │ local Apple Ava or Samantha       │
│ TTS is explicitly chosen.│ agent turns.                      │ with zero audio deadlocks.        │
└──────────────────────────┴───────────────────────────────────┴───────────────────────────────────┘
```

1. **Zero-PII Privacy & Local Security**: Transcripts, audio buffers, and agent IPC envelopes reside strictly in memory and temporary local sockets. Telemetry is anonymized and strictly opt-in (`DO_NOT_TRACK=1` compliant).
2. **Deterministic Locking & Hardware Safety**: All audio channels use POSIX advisory locking (`fcntl.flock`) and threading locks to prevent overlapping speech or hardware device freezes.
3. **Open Standards Alignment**: VoiceFi builds strictly on standard specifications: Model Context Protocol (MCP), W3C Web Audio API, and OpenAI/Edge-compatible REST payloads.

---

## 🤝 How to Contribute to the Roadmap

We welcome contributions across all phases of the roadmap!
- 🛠️ **Looking for a starter task?** Explore our curated [Good First Issues](./GOOD_FIRST_ISSUES.md).
- 💰 **Want to earn bounties?** Check out the [VoiceFi Plugin Bounty Program](./COMMUNITY_GROWTH.md).
- 📖 **Extending VoiceFi?** Review our contributor guides for [Custom TTS](./CONTRIBUTING_CUSTOM_TTS.md), [Sound Effects](./CONTRIBUTING_CUSTOM_SFX.md), and [MCP Architecture](./MCP_ARCHITECTURE.md).
