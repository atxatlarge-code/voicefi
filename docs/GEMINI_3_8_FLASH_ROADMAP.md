# 🗺️ VoiceFi™ × Gemini 3.8 Flash Engineering Roadmap
> **Autonomous Agentic Engineering, 0ms Offline Audio Resiliency, and Cross-Agent Orchestration**  
> *Target Model: Gemini 3.8 Flash (High Thinking)* • *Status: Active* • *Date: September 2026*

---

## 🌟 Executive Overview & Model Synergy

On September 2, 2026, Google DeepMind released **Gemini 3.8 Flash**, introducing record-setting benchmarks for autonomous software engineering:
- **Terminal-Bench 2.1**: **90.8%** (up from 81.6% in 3.7 Flash) for shell execution, diagnostics, and self-healing.
- **DeepSWE v1.1**: Industry-leading frontier capability in multi-file long-horizon software engineering.
- **Reasoning & Tool Verification**: Explicit iterative self-critique before and after tool calls.
- **1M Token Context**: High-fidelity cross-workspace synthesis across `VoiceFi`, `vifi.co`, and `voicefi.org`.

VoiceFi is a high-performance, multi-threaded acoustic and command platform spanning macOS CoreAudio, PortAudio C bindings, PyObjC AppKit runloops, Unix domain sockets (`/tmp/voicefi.sock`), WebSockets, and cross-agent IPC. Operating with **Gemini 3.8 Flash (High)** unlocks autonomous resolution of complex race conditions, seamless zero-latency audio failover, and end-to-end multi-agent orchestration.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                             VOICEFI × GEMINI 3.8 FLASH ROADMAP MATRIX                            │
├──────────────────────────────┬───────────────────────────────────┬───────────────────────────────┤
│           TRACK A            │              TRACK B              │            TRACK C            │
│   Engine Hardening & 100%    │      0ms Offline Resiliency &     │    Cross-Agent Bridge 2.0 &   │
│      Green Test Suite        │      Code Speech Normalizer       │      Mobile Companion Hub     │
│         (Immediate)          │            (Sprint 1)             │          (Sprint 2)           │
├──────────────────────────────┼───────────────────────────────────┼───────────────────────────────┤
│ • 820/820 Tests Green        │ • 0ms Midstream Neural Failover   │ • Antigravity ↔ Claude Debates│
│ • Storm Concurrency (20-wk)  │ • Ava (Premium) CoreAudio Buffer  │ • WebSockets Audio Companion  │
│ • Cloud TTS Abort Recovery   │ • Spoken Code Normalizer 2.0      │ • Dynamic Island PWA Sync     │
│ • Telemetry / Gate Fixes     │ • Math / Diffs / Schemas to Voice │ • Cross-Agent Banter & SFX    │
└──────────────────────────────┴───────────────────────────────────┴───────────────────────────────┘
```

---

## 🎯 Strategic Tracks & Deliverables

### Track 1: Engine Hardening & 100% Green Test Suite (820/820)
**Objective**: Leverage 3.8 Flash's 90.8% Terminal-Bench precision and async reasoning to systematically resolve all 12 failing tests, achieving 100% green test suite status.

#### 1.1 High-Concurrency Storm Isolation
- **Files**: [`tests/test_challenger_m5_2.py`](../tests/test_challenger_m5_2.py), [`tests/test_challenger_m2_2.py`](../tests/test_challenger_m2_2.py)
- **Problem**: `test_interleaved_multi_surface_storm_20_workers` and `test_rapid_concurrent_rest_flood` experience thread-pool lock contention and ephemeral port recycling races under 20-worker load.
- **Solution**:
  - Implement adaptive socket retry backoff with jitter in [`src/voicefi/companion/server.py`](../src/voicefi/companion/server.py).
  - Add thread-safe turn queue eviction in `claim_turn()` when load exceeds threshold.
  - Formalize mutex lock ordering between `/tmp/voicefi_audio_output.lock` and `/tmp/voicefi_active_turns.json`.

#### 1.2 Cloud TTS Midstream Network Abort Recovery
- **Files**: [`tests/test_challenger_m4_empirical.py`](../tests/test_challenger_m4_empirical.py), [`tests/test_fault_tolerance_resilience.py`](../tests/test_fault_tolerance_resilience.py)
- **Problem**: `test_edge_tts_midstream_socket_abort_preserves_remaining_speech` drops subsequent sentences if WebSocket connection aborts mid-stream.
- **Solution**:
  - Pipelined sentence queue exception interception: if sentence $N$ fails with socket error, gracefully reroute sentence $N$ and remaining sentences to local `MacSayTTS` / `Ava (Premium)` without cutting off audio output.

#### 1.3 Feature Gates, Telemetry & Speech HUD Fixes
- **Files**: [`tests/test_updater.py`](../tests/test_updater.py), [`tests/test_cli_telemetry.py`](../tests/test_cli_telemetry.py), [`tests/test_learning.py`](../tests/test_learning.py), [`tests/test_speech_hud.py`](../tests/test_speech_hud.py), [`tests/test_feedback.py`](../tests/test_feedback.py)
- **Fixes**: Update assertions for Pro auto-updater license verification, telemetry opt-out environment variable propagation, and mock AppKit HUD window visibility checks in headless CI.

---

### Track 2: Zero-Latency 0ms Apple Silicon Offline Fallback Engine
**Objective**: Make VoiceFi completely impervious to cloud TTS outages by providing instant, private, local neural speech.

```
                         [Speech Request Incoming]
                                    │
                                    ▼
                     [Pre-fetch Sentence 1 via EdgeTTS]
                                    │
                     ┌──────────────┴──────────────┐
             [Network Success]             [Socket / Timeout Drop]
                     │                             │
                     ▼                             ▼
             [Pipelined afplay]            [⚡ Instant 0ms Failover]
                     │                             │
                     ▼                             ▼
          [Stream to CoreAudio]           [Apple Neural Ava (SayTTS)]
                                                   │
                                                   ▼
                                          [Stream to CoreAudio]
```

#### 2.1 Instant Midstream Neural Failover
- Intercept any EdgeTTS chunk failure and swap the active audio buffer to Apple Silicon native neural speech (`Ava (Premium)`) in $<15\text{ms}$.
- Ensure zero audible stutter, pop, or volume mismatch between cloud and local playback.

#### 2.2 Spoken Code Normalizer 2.0
- **File**: [`src/voicefi/tts/normalizer.py`](../src/voicefi/tts/normalizer.py)
- Expand AST and regex rules to convert dense programming artifacts into spoken natural language:
  - Git Diffs (`+12, -4`) ➔ Spoken summary of modified symbols.
  - Hex memory addresses (`0x7ffee...`) ➔ Compressed pointer references.
  - JSON / Pydantic schemas ➔ Key structure highlights.
  - KaTeX math (`\sum_{i=1}^n x_i`) ➔ Natural spoken math formulas.

---

### Track 3: Cross-Agent Bridge 2.0 (Antigravity ↔ Claude Code)
**Objective**: Build full-duplex, multi-turn pair programming and automated verification between Google Antigravity and Anthropic Claude Code.

```
┌─────────────────────────┐                            ┌─────────────────────────┐
│    Google Antigravity   │                            │    Anthropic Claude     │
│   (Gemini 3.8 Flash)    │                            │    (Claude Code CLI)    │
└────────────┬────────────┘                            └────────────┬────────────┘
             │                                                      │
             │ 1. `vifi send "Review auth middleware" --to claude`  │
             ├─────────────────────────────────────────────────────►│
             │    (Enriched with ConvID & Return Instructions)      │
             │                                                      │
             │                                                      │ 2. Claude analyzes &
             │                                                      │    runs unit tests
             │                                                      │
             │ 3. `vifi send "All 14 tests pass!" --to agy --reply` │
             │◄─────────────────────────────────────────────────────┤
             │    (Native agentapi IPC waking; 0 screen flicker)    │
             ▼                                                      ▼
     [Ba-Dum-Tss! 🥁 SFX]                                   [Turn Soundbite Spoken]
```

#### 3.1 Streaming Bi-Directional Dialogue
- Support multi-turn conversational exchanges where agents critique code, identify edge cases, and negotiate architectural designs.
- Automatic soundbite distillation: rather than reading entire pages of markdown, agents speak concise 2-sentence conversational summaries over speakers.

#### 3.2 Contextual SFX Dispatch
- Map agent events to procedural and sampled audio cues in [`src/voicefi/audio/sfx.py`](../src/voicefi/audio/sfx.py):
  - Test suite pass: Chime / fanfare.
  - Test suite fail: Subtle low-tone alert.
  - Humorous / satirical quips: Drum rimshot, honk, or gong strike.

---

### Track 4: Mobile Remote Companion Hub (`vifi companion` / `vifi.co`)
**Objective**: Enable hands-free untethered agent monitoring from iOS/Android mobile browsers via WebSockets and PWA.

#### 4.1 Low-Latency Audio Streaming
- Stream microphone audio directly from mobile Safari/Chrome via WebSockets (`/ws/audio_stream`) into VoiceFi's VAD and STT pipeline.
- Return live agent speech over mobile HTML5 Audio with dynamic waveform visualization.

#### 4.2 Real-Time Control Sheet & Dynamic Island PWA
- Synchronize status with macOS Dynamic Island HUD in real-time.
- Mobile quick-action controls:
  - **Stop Speech (<kbd>Esc</kbd>)**
  - **Turbo Speed-Talk Toggle (1.5x / 2.0x / 2.5x)**
  - **Persona Selector (Viv / Ava / Steffan / Christopher / Samantha)**
  - **Microphone Push-to-Talk / Hands-Free VAD**

---

### Track 5: Speed-Talking Productivity Engine 2.0 (`vifi turbo`)
**Objective**: Maximize developer listening throughput with fatigue-free 1.25x – 3.0x speech compression.

#### 5.1 Dynamic Velocity Ramping
- Automatically start spoken turns at 1.25x to prime developer comprehension, then dynamically accelerate to 2.25x–2.75x across long explanations.
- Automatically compress silent pauses between sentences from ~400ms down to ~120ms.

#### 5.2 Pitch-Preserving Acoustic Time-Stretching
- Implement Phase Vocoder / WSOLA audio stretching to prevent high-pitched "chipmunk" distortion at $2.5\times$ speeds.
- Local developer analytics: track cumulative developer hours saved across speaking turns (`vifi speed-talk stats`).

---

### Track 6: Automated Multi-Agent Social Reel Pipeline (`voicefi.org`)
**Objective**: End-to-end automated authoring and rendering of high-engagement 9:16 and 1:1 developer reels.

#### 6.1 Scriptwriting & Dialogue Synthesis
- Combine `reel-scriptwriter` and `social-reel-producer` skills to generate punchy, humorous scripts between Viv (Antigravity) and Steffan (Claude).
- Align speaker pauses, punchline sound effects (crickets, gongs, cackles), and slide transitions down to $\pm10\text{ms}$.

#### 6.2 Headless AppKit & FFmpeg Compilation
- Render pixel-perfect vector slides via headless WebKit/AppKit.
- Compile broadcast-ready MP4s and update [`REELS_LOG.md`](../marketing/social/REELS_LOG.md) and `reels.json` automatically.

---

## 📅 Phased Execution Schedule

| Sprint | Phase | Key Milestone Deliverable | Validation Metric |
| :--- | :--- | :--- | :--- |
| **Sprint 1 (Now)** | **Engine Hardening** | Resolve all 12 failing tests; harden concurrency & cloud TTS fallback. | `pytest` 820/820 passed (100% green). |
| **Sprint 2** | **Acoustic Fallback** | Instant 0ms failover to Apple Neural Ava; code normalizer 2.0. | Network cut test $<15\text{ms}$ switchover. |
| **Sprint 3** | **Agent Swarm IPC** | Cross-Agent Bridge 2.0 with bi-directional Antigravity ↔ Claude debates. | Multi-turn hands-free voice dialogue loop. |
| **Sprint 4** | **Companion & PWA** | Mobile WebSocket companion streaming audio to/from phone. | End-to-end iPhone ➔ Antigravity prompt cycle. |
| **Sprint 5** | **Turbo & Reels** | Dynamic ramping speed-talk & automated social reel publishing. | Real-time time-saved telemetry & 4K 9:16 reels. |

---

## 🛠️ Verification & Diagnostic Tooling

```bash
# Run full test suite with concurrency isolation
pytest -v

# Validate cloud TTS disruption fallback
pytest tests/test_challenger_m4_empirical.py -v

# Run 20-worker concurrency storm benchmark
pytest tests/test_challenger_m5_2.py -k "storm" -v

# Test instant local Ava synthesis
vifi voice test "Ava (Premium)" -t "Verifying instant 0ms offline latency."

# Inspect active locks and turn claims
ls -l /tmp/voicefi*
