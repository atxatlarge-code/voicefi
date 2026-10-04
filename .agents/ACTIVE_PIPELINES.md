# 🚦 Active Workspace Pipelines

This registry maintains cross-thread pipeline state across sessions. When jumping into a fresh thread or asking "what's next?", agents read this file to immediately locate active and queued tasks without scrolling through past transcripts.

---

## ⚡ Active Pipelines

### 🛠️ Local-First Agent Suite & Hardware Guardrail Integration
- **Objective**: Harden, calibrate, and document the on-device intelligence stack on Apple Silicon Metal GPU (Ollama + LiteRT + MLX), guarded by hardware telemetry and zero cloud token burn.
- **Branch**: `main`
- **Current Status**: `PHASE 5 COMPLETED • PHASE 6 READY`

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

#### Next Resume Prompt
```markdown
All core phases of the Local-First Agent Suite & Hardware Guardrail Integration pipeline are complete. Proceed to stage and commit the verified changes to main.
```

---

## 📋 Completed Pipelines (Archive)

* `[2026-10-02]` **Local Agent Suite & Hardware Guardrail Architecture**: Implemented and verified `ThermalSupervisor`, `ReconScout` with Ollama auto-discovery, `local_qa.py` diff auditor and test synthesizer, and Content Factory native JSON generation.
* `[2026-10-02]` **Autonomous Overnight Concurrency, Duplex & Content Factory Soak + Architecture Hardening**: Executed 6.5h continuous soak test on branch `test/overnight-duplex-concurrency-stress` (1,408 cycles, 4,224 jobs, 1.48M tokens saved locally, 0 underruns, 0 deadlocks). Subagents audited and resolved MCP hot-path latency (>3,700x speedup down to 0.17ms), standardized lock hierarchy, hardened SQLite queue backoff jitter, mounted `/factory` Studio UI, and achieved 100% green test suite.
* `[2026-10-01]` **Thread Handoff & Next Steps Protocol Setup**: Global handoff rule installed, `/next` skill configured, and VoiceFi HUD Next-Up acoustic handoff added to high-priority roadmap.
