# 🚦 Active Workspace Pipelines

This registry maintains cross-thread pipeline state across sessions. When jumping into a fresh thread or asking "what's next?", agents read this file to immediately locate active and queued tasks without scrolling through past transcripts.

---

## ⚡ Active Pipelines

### 🛠️ Local-First Agent Suite & Hardware Guardrail Integration
- **Objective**: Harden, calibrate, and document the on-device intelligence stack on Apple Silicon Metal GPU (Ollama + LiteRT + MLX), guarded by hardware telemetry and zero cloud token burn.
- **Branch**: `main`
- **Current Status**: `PHASE 10 COMPLETED • FULL-DUPLEX COREAUDIO S2S READY`

#### Phase Breakdown & Milestones
- [x] **Phase 1: Apple Silicon Thermal & Memory Supervisor (`src/voicefi/local/supervisor.py`)**
  - Integrated `pmset -g therm` thermal pressure parsing (`NORMAL`, `FAIR`, `SERIOUS`, `CRITICAL`).
  - Unified memory tracking (free GB, total GB, % used) and 1m CPU load monitoring.
  - Non-blocking backoff via `wait_if_throttled()` and `@supervisor.guarded()` decorator.
- [x] **Phase 2: Active Recon Scout (`src/voicefi/local/scout.py`)**
  - Wired directly to local Ollama auto-discovery (`qwen2.5-coder:1.5b`, `gemma2:2b`, `llama3.2:1b`, `tev1:latest`, `nimble:latest`).
  - Ingress latency: `<0.2 ms` (measured `0.04–0.08 ms` in unified RAM).
  - Context compression: `85%+` tokens saved with sub-6s local turnaround.
  - Dedicated CLI entrypoint: `uv run python -m voicefi.local.scout <target> -q "<query>" [--json]`.
- [x] **Phase 3: Local QA Diff Auditor & Test Synthesizer (`scripts/local_qa.py`)**
  - 5-stage automated gate: Diff extraction (`--staged`, `--rev`), `ruff` lint check, targeted `pytest`, local Ollama architectural code review & test synthesis.
  - Emits automated markdown scorecard to `.agents/QA_AUDIT.md`.
  - Guarded by `ThermalSupervisor.wait_if_throttled()`.
- [x] **Phase 4: Autonomous Content Factory with Native JSON Mode (`src/voicefi/factory/generator.py` & `scripts/run_content_factory.py`)**
  - Dynamic Ollama model auto-discovery (`PREFERRED_CREATIVE_MODELS`).
  - Native JSON mode (`format: "json"`) for zero-prompt-leak structured `ContentManifest` output.
  - Autonomous background loop polling `ContentFactoryQueue` (SQLite WAL mode).
  - Guarded by `default_supervisor.wait_if_throttled()`.
- [x] **Phase 5: Agent Skills & Workspace Documentation Alignment**
  - Synchronized skills: `local-scout`, `local-qa`, `local-content`, `local-dev` across `.agents/skills/` and `.gemini/config/plugins/voicefi-plugin/skills/`.
  - Documented exact CLI flags, Python APIs, model tiers, and guardrails.
  - Aligned `ROADMAP.md` (Phase 6 / Phase 3) and `docs/AGENT_DEVELOPER_AND_TROUBLESHOOTING_GUIDE.md`.
- [x] **Phase 6: Multi-Worker Concurrency Stress & Air-Gapped Benchmarking**
  - Concurrently executed Content Factory workers (`gemma2:2b`) and Recon Scout (`qwen2.5-coder:1.5b`) under Apple Silicon Metal load.
  - Hardened directory recon scanning to filter noise directories, bounded scout context window, and added 15s timeout protection against agent step-retries.
  - Zero lock errors, sub-2ms unified RAM ingress, 50.1% context compression, and verified thermal stability under `ThermalSupervisor`.
- [x] **Phase 7: Hybrid Cloud + Apple Silicon Telemetry Ledger & Dynamic Router (`src/voicefi/local/router.py` & `src/voicefi/local/telemetry.py`)**
  - Implemented `HybridRouter` (`70B -> 32B/26B -> 7B -> 1.5B/2B -> Cloud Flash`) gated by `ThermalSupervisor` Unified RAM headroom, swap pressure, and thermal state.
  - Wired automatic `record_hybrid_step` hooks across `ReconScout`, `ReconImplementer`, `LocalAutonomousLoop`, and `scripts/local_qa.py` correlated via `VOICEFI_PIPELINE_ID`.
  - Extended `~/.voicefi/analytics.db` (`get_hybrid_orchestration_analytics`), `vifi stats` CLI dashboard, zero-PII PostHog `capture_hybrid_step`, `.agents/HYBRID_TELEMETRY.md` scorecard, and `.agents/hybrid_telemetry_dashboard.html`.
- [x] **Phase 8: Sub-80ms Acoustic Cognitive Safety & `-12dB` Dynamic Volume Ducking (`src/voicefi/audio/cognitive_safety.py`, `src/voicefi/audio/player.py`, `src/voicefi/integrations/active_listening.py`)**
  - Executed via 3-Stage Hybrid Pipeline (`boost-20261013-cognitive-safety`): Stage 1 `ReconScout` pre-digest (4,064 tokens saved in `<0.13ms` RAM ingress) $\to$ Stage 2 Parallel `/boost` Subagents $\to$ Stage 3 `local_qa.py` verification gate (23/23 tests passing in 0.57s, `<1.5ms` classification latency).
  - Implemented 3-way spectral FFT + ZCR + lexical discriminator (`INTENTIONAL_INTERRUPTION`, `CONVERSATIONAL_BACKCHANNEL`, `NON_SPEECH_ARTIFACT`) and real-time `-12dB` (`~0.2512x` linear gain) onset ducking & restoration in `StreamingAudioPlayer`.
- [x] **Phase 9: Gemini Live Persistent Socket Resilience, PCM Ringbuffer Replay & Proactive Session Rollover (`src/voicefi/audio/live_stream.py` & `src/voicefi/live_studio.py`)**
  - Full-duplex WebSocket keep-alive resilience with adaptive ping/pong heartbeats to eliminate unexpected socket closures.
  - Micro-buffering ringbuffer of 20ms 16kHz PCM chunks during socket re-negotiation with automatic zero-drop replay on reconnection.
  - Proactive session rollover before provider session limits (9 minutes / 540s max duration) with mid-utterance turn protection.
  - Runtime routing mode selection (`standard` task dispatch vs `live` direct neural voice streaming) and dynamic `-12dB` volume ducking.
- [x] **Phase 10: Voice Vault Q&A ("Talk to Your Notes") — Sub-20ms Spoken RAG & Socratic Brainstorming Partner (`src/voicefi/integrations/vault_index.py` & `src/voicefi/integrations/vault_agent.py`)**
  - Unified RAM + SQLite FTS5 WAL knowledge indexing over Obsidian notes, voice memos, and recent git history with heading-scoped line citations (`note.md#Lstart-Lend`).
  - Incremental mtime cache invalidation and sub-20ms retrieval SLA (`VaultRAGIndex.search`).
  - Dual conversational synthesis modes via `LocalVaultSynthesizer`: deterministic spoken Q&A with exact quote attribution, and Socratic Brainstorming Partner cross-examining assumptions out loud.
  - Studio Neural Persona voice playback (`Christopher`, `Sonia`, `Guy`, `Aria`, `Ava`), automatic secret redaction, and Hybrid Telemetry ledger recording.
- [x] **Phase 11: Tier 0 Edge Vector Grounding & Reflex Arbitration (EmbeddingGemma 2 + TEV 0.8B) (`src/voicefi/local/embed.py` & `docs/TIER0_EDGE_VECTOR_GROUNDING_GUIDE.md`)**
  - Engineered 3-Tier Edge Architecture delivering sub-40ms perception-to-action on Apple Silicon Unified Memory (~1.14 GB static footprint).
  - Integrated `embedding-gemma-2:740m` (INT8 768-d normalized vectors) and `tev1:0.8b` (Q4_K_M structured reflex arbiter) with `ThermalSupervisor` `is_tier0` reflex exemption under `SERIOUS` thermal pressure.
  - Built `LocalGroundingStore` with ephemeral SQLite WAL mode, automated TTL pruning (5m UI OCR, 30s clipboard), and pre-embedding secret redaction choke point.
  - Connected Tier 0 direct window focus and OS telemetry into `LocalIntentRouter.route_prompt()`, and wired Foresight-style local file grounding into `cmd_ambient`.
  - Comprehensive test suite (`tests/test_tier0_embed.py`) with 15/15 passing tests in 1.95s.

#### Next Resume Prompt
```markdown
Produce Issue #3 of the 1980s/1990s Editorial Magazine Carousel Series: "When Your Client Is an AI" (The 66-Round Autonomous Audit War / "Don't Ask an LLM to Do Arithmetic") following .agents/skills/editorial-director/SKILL.md and docs/EDITORIAL_CAROUSEL_SERIES_PLAN.md.
```

---

### 📰 1980s/1990s Editorial Magazine Carousel Series (`@orenmeetsworld` + Print Spread Engine)
- **Master Plan**: [`docs/EDITORIAL_CAROUSEL_SERIES_PLAN.md`](../docs/EDITORIAL_CAROUSEL_SERIES_PLAN.md)
- **Interactive Studio**: [`docs/editorial_carousel_studio.html`](../docs/editorial_carousel_studio.html)
- **Current Status**: `ISSUES #1 & #2 COMPLETED • ISSUE #3 ("WHEN YOUR CLIENT IS AN AI") QUEUED NEXT`

#### Edition Tracker
- [x] **Issue #1: *"Local Models: The Lost Frontier"* (`Tev & Jev` / Small Models, Sharp Code)**
  - Exported full-bleed 4:5 PDF (`marketing/social/carousels/Local_Models_The_Lost_Frontier.pdf`) and 1080×1350 PNGs (`v2_small_models_slide_1..7.png`) with Jacob's likeness and 1990s magazine center-fold spreads.
- [x] **Issue #2: *"Stop Babysitting Terminals"* (`The Silent Terminal Crisis` / `Give voice to your agents`)**
  - Exported full-bleed 4:5 PDF (`marketing/social/carousels/Stop_Babysitting_Terminals_Issue_2.pdf`) and 1080×1350 PNGs (`issue2_silent_terminal_slide_1..7.png`) with *Office Space* ("I'm a people person!") staging, closed/rear-facing MacBook Pros, smooth crease-free & flat studio backdrops, and live HTML `Newsreader` serif typography.
- [ ] **Issue #3 (ACTIVE NEXT): *"When Your Client Is an AI"* (The 66-Round Autonomous Audit War)**
- [ ] **Issue #4: *"Context Bloat Is a Tax"* (The 200-Token Recon Scout Diet)**
- [ ] **Issue #5: *"Read With Your Ears"* (2.5x Speed Listening & High-Bandwidth I/O)**
- [ ] **Issue #6: *"Ramble First. Compile Second."* (The 3-Minute Voice Memo Buffer)**

---

## 📋 Completed Pipelines (Archive)

* `[2026-10-02]` **Local Agent Suite & Hardware Guardrail Architecture**: Implemented and verified `ThermalSupervisor`, `ReconScout` with Ollama auto-discovery, `local_qa.py` diff auditor and test synthesizer, and Content Factory native JSON generation.
* `[2026-10-02]` **Autonomous Overnight Concurrency, Duplex & Content Factory Soak + Architecture Hardening**: Executed 6.5h continuous soak test on branch `test/overnight-duplex-concurrency-stress` (1,408 cycles, 4,224 jobs, 1.48M tokens saved locally, 0 underruns, 0 deadlocks). Subagents audited and resolved MCP hot-path latency (>3,700x speedup down to 0.17ms), standardized lock hierarchy, hardened SQLite queue backoff jitter, mounted `/factory` Studio UI, and achieved 100% green test suite.
* `[2026-10-01]` **Thread Handoff & Next Steps Protocol Setup**: Global handoff rule installed, `/next` skill configured, and VoiceFi HUD Next-Up acoustic handoff added to high-priority roadmap.
