# 🗺️ VoiceFi™ Product & Engineering Roadmap
> **"Give voice to your agents, and agency for your voice."**  
> *The Universal Voice & Agency Layer for Autonomous AI Agents, MCP, and Knowledge Systems.*

***

## 🌟 Vision
VoiceFi gives **voice to AI agents** and **agency to human voice**:

1. **Voice to Agents:** Giving autonomous coding agents, IDEs, and background subagents distinct acoustic presence, studio-quality neural personas, and zero-latency spoken dialogue.
2. **Agency for Voice:** Elevating human speech from passive transcription into direct, high-leverage agent dispatch, multi-agent orchestration, and hands-free developer flow state.

---

## 📍 Milestones & Execution Status

```mermaid
flowchart LR
    subgraph P1["Phase 1: Core Voice Bridge (Done)"]
        A1["2.7ms Streaming STT Engine"]
        A2["0ms Offline Apple Ava"]
        A3["AppKit Dynamic Island HUD"]
    end

    subgraph P2["Phase 2: Agent Voice & Agency (Active)"]
        B1["Antigravity & Claude Hooks"]
        B2["Native MCP Server (voicefi_*)"]
        B3["Cross-Agent Bridge (vifi send)"]
    end

    subgraph P_DUPLEX["Dedicated: Full-Duplex S2S (Planned)"]
        FX1["CoreAudio VoiceProcessingIO AEC"]
        FX2["Moshi / Mimi Metal MLX Engine"]
        FX3["Sub-80ms Acoustic Cognitive Safety"]
    end

    subgraph P3["Phase 3: Multi-IDE & Dispatch"]
        C1["Cursor & Windsurf Rules"]
        C2["Ambient Standup & Linear Sync"]
        C3["Voice-to-Subagent Dispatch"]
    end

    subgraph P4["Phase 4: Synthesis & Pacing"]
        D1["5-Min Walking Voice Memos"]
        D2["Spoken PR & Morning Briefings"]
    end

    subgraph P6["Phase 6: Unified Memory Metal Studio"]
        E1["Air-Gapped 32B/70B Triad"]
        E2["Metal LivePortrait Lip-Sync"]
        E3["Local Demucs Mastering"]
    end

    P1 --> P2 --> P_DUPLEX --> P3 --> P4 --> P6
```

---

## 🚀 Phase 1: Real-Time Dictation & Vault Bridge *(COMPLETED ✅)*
- [x] **2.7ms Real-Time Streaming STT:** Pre-warmed local Whisper engine on Apple Silicon Neural Engine with zero cloud roundtrips.
- [x] **Obsidian Ribbon Plugin & Custom Brand Icon:** Fused studio shockmount & smiling robot face ribbon icon registered in Obsidian.
- [x] **Spoken Markdown Shortcuts:** Hands-free voice formatting (`"New line"`, `"New paragraph"`, `"Bullet [text]"`, `"Task [text]"`, `"Heading one/two"`).
- [x] **Atomic Anchor Replacement:** Seamless live ghost text streaming without flickering or accidental text deletion.
- [x] **Self-Healing Background Server:** Automatic background engine auto-spawn upon clicking the Obsidian ribbon icon.
- [x] **Modular 1-Line Installer:** Interactive `[Y/n]` Obsidian vault auto-discovery in `install.sh` and dedicated `vifi obsidian install` CLI.

---

## 🟡 Phase 2: Two-Way Conversational Vault ("Talk to Your Notes") *(IN PROGRESS)*
- [ ] **Voice Vault Q&A (Sub-20ms Spoken RAG):**
  - Ask questions about your notes out loud (*"VoiceFi, what did I decide on the audio pipeline last Thursday?"*).
  - Sub-20ms zero-copy vector search via embedded local LanceDB/DuckDB + Whisper on Apple Neural Engine (ANE), citing exact quotes and line numbers.
  - Scans active vault markdown notes, voice memos, and recent git diffs into unified RAM.
- [ ] **Studio Neural Persona Audio Playback:**
  - Full voice synthesis spoken directly by **Christopher** (default), **Sonia** (analyst), **Guy** (pair programmer), or **Aria** (energetic QA).
  - Hotkey / ribbon button: *"VoiceFi: Read Selection Aloud"* with variable playback speed control.
- [ ] **Socratic Brainstorming Partner:**
  - Interactive back-and-forth conversational mode where VoiceFi challenges assumptions, identifies logical gaps, and asks clarifying questions out loud while you pace.
- [ ] **Gemini Live Persistent Socket & Keep-Alive Resilience:**
  - Full-duplex WebSocket connection (`gemini-3.8-live`) with adaptive ping/pong keep-alive heartbeats to eliminate unexpected socket closures.
  - Micro-buffering of PCM audio chunks during socket re-negotiation so speech is never dropped during reconnects.
  - Proactive session rollover before upstream provider session timeouts.
  - Seamless turn-end routing: toggle between Standard (chat injection into Antigravity) and Gemini Live (direct neural voice streaming).

---

## ⚡ Dedicated Milestone: Full-Duplex Speech-to-Speech (S2S) & Acoustic Cognitive Safety *(PLANNED • TABLED FOR DEDICATED SPRINT)*
> **Core Objective:** Transition VoiceFi from turn-based request/response speech to an **always-listening, simultaneous bidirectional conversational channel** with zero acoustic feedback and sub-80ms interruption handling.
> **Intellectual Property Reference:** U.S. Patent Application No. 64/137,300.

### 1. Hardware Echo Cancellation & Duplex Audio Loopback
- [x] **6.5-Hour Duplex Concurrency & Buffer Underrun Validation:**
  - Validated 168,960 audio buffer lock acquisitions across 1,408 cycles with **0 buffer underruns** and **0 lock deadlocks** under continuous 2x concurrent contender contention.
  - Standardized turn lock hierarchy in `speech_turn_lock()` and verified barge-in audio isolation in `scripts/overnight_stress.py` (see [`benchmarks/OVERNIGHT_CONCURRENCY_REPORT.md`](benchmarks/OVERNIGHT_CONCURRENCY_REPORT.md)).
- [ ] **CoreAudio `VoiceProcessingIO` DSP Integration:**
  - Initialize input/output audio units via macOS `kAudioOutputUnitSubType_VoiceProcessingIO`.
  - Harness Apple Silicon's hardware DSP acoustic echo cancellation (AEC) and automatic ducking.
  - Eliminates "speaker bleed" (agent hearing its own voice played over MacBook speakers and falsely triggering self-interruption).

### 2. Dual Full-Duplex Engine Architecture
- [ ] **Cloud Frontier Engine: Persistent Bidirectional `gemini-3.8-live` WebSockets:**
  - Continuous 16kHz/24kHz raw PCM audio streaming over bidirectional WebSocket.
  - Sub-150ms roundtrip conversational responsiveness with theatrical voice personalities.
  - Adaptive keep-alive ping/pong, automatic session rollover, and audio ringbuffer replay during network handoffs.
- [ ] **Local On-Device Engine: Kyutai Moshi / Mimi Discrete Codec via Apple MLX:**
  - 100% air-gapped, zero-cloud speech-to-speech engine running natively on Apple Silicon Metal GPU.
  - Dual 12.5Hz discrete acoustic token streams (input stream interleaved with output stream).
  - Sub-100ms local turn latency without emitting text tokens.

### 3. Sub-80ms Acoustic Cognitive Safety & Intent Verification
- [ ] **Vocal Pitch & Intent Discrimination (U.S. Patent 64/137,300):**
  - Instantaneous spectral classifier running on Apple Neural Engine (ANE) to discriminate:
    - **Intentional Interruption:** Direct commands (*"Wait"*, *"Stop"*, *"Cancel that"*, *"Actually change..."*) $\to$ halts agent execution and TTS within 80ms.
    - **Conversational Backchanneling:** Passive affirmation (*"Right"*, *"Uh-huh"*, *"Makes sense"*) $\to$ agent continues speaking smoothly without halting.
    - **Non-Speech Acoustic Artifacts:** Keyboard clicks, dog barking, throat clearing, sighing $\to$ fully filtered by Silero VAD + spectral mask.
- [ ] **Dynamic Volume Ducking:**
  - Automatically attenuate agent speech volume by -12dB the instant human vocal onset is detected, allowing the human voice to cut through cleanly before hard stopping.

### 4. AppKit Dynamic Island HUD Full-Duplex States
- [ ] **Real-Time Duplex Waveform Telemetry:**
  - Visual HUD state representation:
    - `🟢 Duplex Active`: Dual animated waveforms indicating simultaneous listening and speaking.
    - `🟡 Backchannel Detected`: Subtle pulse without interrupting current agent speech.
    - `🔴 Interrupted & Ducked`: Instantaneous snap to red wave, flushing audio buffers and listening for developer follow-up.

---

## 📋 Phase 3: Autonomous Agent Dispatch & MCP Architecture *(IN PROGRESS • [Architecture Spec](docs/MCP_ARCHITECTURE.md))*
- [x] **Universal `voicefi-mcp` Server:**
  - Standardized Model Context Protocol server exposing `voicefi_speak`, `voicefi_ask_confirmation`, `voicefi_send`, `voicefi_sfx`, `voicefi_ping_voice`, and `voicefi_get_ambient_context` to Antigravity, Claude Code, Cursor, Windsurf, and Zed.
  - Multi-agent neural acoustic personas (Christopher, Sonia, Guy, Aria) for distinct subagent auditory feedback.
  - **Sub-Millisecond Probe Latency (0.17 ms):** Pre-cached schema definitions and non-blocking background telemetry dispatch (`sync_mode = False`), verified across 6.5-hour soak test.
- [ ] **Voice-to-MCP Client Dispatcher:**
  - Ambient speech directly triggers external MCP servers (Slack, Linear, Postgres, GitHub, DevTools) without manual typing.
  - Dedicated hands-free Slack workflows (morning standups, thread catch-up summaries, polished DM dispatch).
- [ ] **Voice-to-Subagent Orchestration:**
  - Command background coding agents directly from speech (*"VoiceFi, dispatch a subagent to write unit tests for the auth module"*).
  - Real-time spoken auditory confirmation (*"Starting QA subagent on branch auth-tests..."*).
- [ ] **Hands-Free Task Triage & Linear Sync:**
  - Spoken action items automatically parsed into `- [ ]` markdown checkboxes in Obsidian.
  - 1-click or voice-triggered synchronization to **Linear tickets** or GitHub Issues.
- [ ] **Auditory Build & Test Status Alerts:**
  - Spoken notifications when long-running background tasks or CI builds finish (*"All 48 tests passed on branch feat/streaming"*).

---

## 📋 Phase 4: Smart Brain Dump Synthesis & "Podcast Mode" *(PLANNED)*
- [ ] **5-Minute Walking Voice Memo Synthesis:**
  - Record raw, unstructured, stream-of-consciousness brain dumps on iPhone/Mac while walking.
  - VoiceFi strips filler words, extracts key insights, creates structured markdown sections, and saves directly to `Vault/Voice Memos/YYYY-MM-DD-Brainstorm.md`.
- [ ] **"Daily Briefing" Podcast Mode:**
  - Generates a customized 2–3 minute audio briefing every morning summarizing open tasks, yesterday's modified notes, and priority items.
- [ ] **Mobile Companion PWA & Apple Watch Trigger:**
  - Remote dictation and listening from phone / smartwatch synced over WebSocket to desktop Obsidian vault.

---

## 📋 Phase 5: Vault-Aware Semantic Biasing & Auto-Wikilinking *(PLANNED)*
- [ ] **Vault Vocabulary Biasing:**
  - Scans active vault note titles, aliases, YAML frontmatter, and code identifiers to bias the speech recognizer in real time.
  - 100% accurate spelling for proprietary concepts, company names (*LienLogic*), and project titles (*VikingTrail*).
- [ ] **Hands-Free Auto-[[Wikilinking]]:**
  - Automatically identifies concepts in spoken sentences and converts them into clickable `[[Note Title]]` links on the fly.
- [ ] **Obsidian Community Plugin Directory Submission:**
  - Official release submission to Obsidian's native community plugin registry for 1-click install inside Obsidian Settings.

---

## 📋 Phase 6: Unified Memory Metal Studio & Air-Gapped Agent Suite *(PLANNED)*

### 1. The 100% Air-Gapped Local "Developer Studio" (Zero Cloud, Zero Token Bills)
- [x] **Local-First Agent Suite Delivery:** Migrated monolithic on-device scout into 4 specialized edge skills (`local-dev`, `local-scout`, `local-qa`, `local-content`) with direct MCP tool attribution (`voicefi_implement`, `voicefi_scout`, `voicefi_auto`, `voicefi_benchmark`), CLI aliases (`vifi local-dev`, `vifi verify`), and unified diff returns preserving >95% cloud tokens.
- [x] **Apple Silicon Thermal & Hardware Supervisor (`src/voicefi/local/supervisor.py`):**
  - Continuous telemetry across macOS thermal pressure states (`pmset -g therm`), unified RAM headroom, and CPU load.
  - Sleep-safe circuit breaker (`wait_if_throttled()`) and `@supervisor.guarded()` decorator preventing thermal throttling, fan noise, and memory exhaustion during heavy inference and batch runs.
- [x] **Active Recon Scout Engine (`src/voicefi/local/scout.py`):**
  - On-device file and log pre-digestion wired directly to local Ollama auto-discovery (`qwen2.5-coder:1.5b`, `gemma2:2b`, `llama3.2:1b`, `tev1:latest`, `nimble:latest`) with LiteRT Metal GPU fallback.
  - Sub-0.2ms unified RAM ingress (measured 0.04–0.08ms) and 85%+ context compression (<200 tokens return). Dedicated CLI: `uv run python -m voicefi.local.scout <target> -q "<query>" [--json]`.
- [x] **Local QA Diff Auditor & Test Synthesizer (`scripts/local_qa.py`):**
  - 5-stage automated gate: git diff extraction (`--staged`, `--rev`), `ruff` lint check, targeted `pytest`, local Ollama architectural code review, edge case vulnerability diagnosis, and proposed unit test synthesis.
  - Emits automated markdown scorecard to `.agents/QA_AUDIT.md`. Guarded by `ThermalSupervisor`.
- [x] **Autonomous Content Creation Factory (`src/voicefi/factory/generator.py` & `scripts/run_content_factory.py`):**
  - Dynamic Ollama model auto-discovery with native JSON mode (`format: "json"`) for zero-prompt-leak structured dialogue manifests.
  - Autonomous background loop polling `ContentFactoryQueue` (SQLite WAL mode), generating reel manifests in 1–3s with $0 cloud API cost. Guarded by `ThermalSupervisor`.
- [ ] **Simultaneous Multi-Model RAM Triad:**
  - Leverage 64 GB unified memory to keep the complete local intelligence stack resident concurrently:
    - **Reasoning/Coding Agent:** Qwen 2.5 Coder 32B / DeepSeek-R1-Distill 32B (~20–22 GB)
    - **Zero-Shot Voice Cloning:** F5-TTS / CosyVoice on Metal MPS (~3.5 GB)
    - **Streaming STT & VAD:** Whisper Large-v3 Turbo + Silero on Apple Neural Engine (~1.8 GB)
    - **Embedded Vector Store:** LanceDB in-memory index (~1.2 GB)
    - **Total Active Footprint:** ~28–30 GB RAM, leaving >34 GB free for macOS, IDEs, and browser.
- [ ] **End-to-End Hands-Free Coding Loop:**
  - Voice in (Whisper on ANE) $\to$ Local Antigravity Agent (Metal GPU) $\to$ Surgical Search/Replace Diff $\to$ Automated Pytest Verification $\to$ Voice Out (MLX Qwen3-TTS). Completely offline with zero internet connectivity.
- [ ] **Host Safety & Execution Sandboxing for Autonomous `vifi fix`:**
  - **Strict AST / Slice Boundary Enforcement:** Automatically reject SEARCH/REPLACE patches that attempt to modify lines outside the Scout's isolated function slice.
  - **Subprocess Command Whitelisting:** Enforce strict execution policies on verification commands (permitting read-only test runners like `pytest`, `cargo test`, `npm test`, while strictly intercepting and blocking dangerous shell commands like `rm -rf`, system directory writes, or unbound network egress).
  - **Isolated Git Worktree Staging:** Execute autonomous test-fix iteration loops in detached temporary worktrees before presenting the final unified diff to the developer.

### 2. Local 70B Heavyweight Reasoning Tier
- [ ] **Frontier 70B / 72B Execution (Llama 3.3 70B / Qwen 2.5 72B Q4_K_M):**
  - Allocate ~42–44 GB RAM for 4-bit quantized frontier models delivering 14–18 tokens/sec on M5 Pro Metal GPU.
  - Multi-file architectural refactoring, complex AST AST rewriting, and confidential patent claim expansion (U.S. Patent App. No. 64/137,300) with complete on-device privacy.

### 3. Local Photorealistic Lip-Sync & Avatar Video Synthesis (`social-reel-producer`)
- [ ] **On-Device LivePortrait / MuseTalk on Metal:**
  - Drive still character avatars (Christopher, Ricky Bobby, Alex Trebek, custom brand avatars) with real-time facial dynamics and phonetic lip-sync directly from synthesized speech.
- [ ] **Zero-Copy Apple VideoToolbox Hardware Pipeline:**
  - Metal frame buffers passed directly to VideoToolbox (H.265 / AV1 / ProRes hardware encoders) with 0 CPU roundtrips, rendering full 60fps 9:16 vertical reels in seconds without cloud GPU rentals.

### 4. Full-Duplex On-Device Speech-to-Speech (Moshi / Mini-Omni via MLX)
- [ ] **Sub-150ms Direct Speech-to-Speech Engine:**
  - Native Apple MLX implementation of duplex audio-in/audio-out models (Kyutai Moshi / Mini-Omni).
  - True conversational barge-in: interrupts agent speech instantly upon human vocal onset with zero WebSocket keep-alive dependencies or cloud latency.

### 5. Always-On 24/7 Ambient Vault & Audio Memory
- [ ] **Low-Power ANE Background Listener:**
  - Continuously transcribes standups, pair-programming discussions, and brainstorms using Apple Neural Engine at <2W power draw.
  - Real-time chunking and vector embedding into embedded LanceDB.
  - Sub-20ms natural language query resolution (*"VoiceFi, what did I decide on the audio pipeline last Thursday?"*) with cited quotes and line numbers.

### 6. Local Stem Separation & Studio Audio Mastering
- [ ] **Metal-Accelerated Demucs / HT-Demucs:**
  - Run stem separation on Apple Silicon at >10x real-time speed.
  - Automated room reverb removal, coffee shop noise suppression, and broadcast vocal mastering (multi-band compression, dynamic EQ) at <5ms latency.
- [ ] **Procedural Beat Cadence Alignment:**
  - Beat-grid and BPM analysis of local audio tracks, snapping neural rap lyrics and conversational timing dynamically to musical downbeats.

### 7. Interface Connectors & Maintenance Architecture
- [ ] **Multi-Surface Agent Interfaces:**
  - **Antigravity IDE & CLI:** Point `LiteRTAgentConfig` and local API providers directly to M5 Pro Metal endpoints (`http://localhost:11434/v1`).
  - **Aider Pair Programmer:** Bridge VoiceFi streaming STT/TTS directly into `aider --model ollama/qwen2.5-coder:32b`.
  - **VoiceFi Cockpit (`./factory cockpit`):** Terminal TUI and AppKit Dynamic Island HUD for real-time task queues and speech telemetry.
- [ ] **Thin-Client Distribution & Dynamic Hardware Profiling:**
  - Keep open-source PyPI (~35 MB) and macOS DMG (~120 MB) lean; models download on-demand to `~/.voicefi/models` or bridge to existing system Ollama/MLX daemons.
  - Dynamic discovery of Apple Silicon chip tier and RAM (16GB / 32GB / 64GB / 128GB), auto-configuring the optimal local model execution profile.

### 8. Neural Voice-to-Voice (RVC / Seed-VC) Audio Style Transfer
- [ ] **Direct Waveform-to-Waveform Vocal Conversion:**
  - Replace vocal tract timbre directly from raw audio stems without intermediate STT (speech-to-text) or TTS (text-to-speech).
  - Preserves 100.00% of source performance, breath intakes, laughing/inflections, and millisecond-accurate pauses.
- [ ] **Apple Silicon Metal / MPS Acceleration:**
  - Fast local inference via PyTorch MPS or native MLX RVC runtime.
- [ ] **CLI & Video Dubbing Workflow:**
  - `vifi convert <input.wav> --voice <target_voice> --output <converted.wav>`
  - True zero-render video dubbing: directly remuxes converted vocal stem into source footage with perfect lip-sync and 0 manual timing edits.

### 9. Acoustic Calibration & Human-in-the-Loop Voice Tuning (Lower Priority)
- [ ] **A/B Acoustic Calibration Loop (`vifi calibrate`):**
  - Audition 3 rapid acoustic cadence & prosody variations for notifications and speech synthesis (e.g., 1.25x vs. 1.5x with short vs. long pause compression).
  - Single-key interactive selection (`[1]`, `[2]`, or `[3]`) to lock personalized acoustic profiles into `~/.voicefi/config.json`.
  - Practical, zero-hallucination human-in-the-loop alternative to recursive prompt auto-tuning.

---

## 📜 Intellectual Property
* **U.S. Patent Application No.:** 64/137,300 (*Ambient Voice-Driven Autonomous AI Agent Orchestration, Intent Verification, and Acoustic Cognitive Safety*)
* **Copyright:** © 2026 LienLogic Data LLC. All Rights Reserved.
