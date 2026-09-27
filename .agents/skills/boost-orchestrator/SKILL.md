---
name: boost-orchestrator
description: Orchestrates complex software engineering, multi-surface refactors, and root-cause debugging using multi-agent /boost pipelines with specialized subagent roles (Scout, Core Implementer, Surface Adapter, Verifier), branch isolation, and calibrated model tiering.
---

# Boost Orchestrator Skill

This skill formalizes the standard operating architecture for **`/boost`** and multi-agent coordination across **VoiceFi**, **vifi.co**, and **voicefi.org**.

Whenever the user invokes `/boost <task>` or asks for an orchestrated multi-agent workflow on a complex feature, refactor, or bug investigation, use the principles and roles defined in this document.

---

## 1. The 3-Phase Boost Pipeline

```
[Developer: /boost <complex task>]
       │
       ▼
[Phase 1: Strategic Planning & Decomposition]
       │  • Analyze entire architecture and file dependencies
       │  • Formulate milestone checklist and interface invariants
       │  • Partition work into isolated, non-colliding subtasks
       ▼
[Phase 2: Parallel Subagent Execution]
       │  • Dispatch specialized subagents with branch isolation (`Workspace: "branch"`)
       │  • Scout / Investigator -> read-only audits & log analysis
       │  • Core Implementer -> backend/audio/daemon modifications
       │  • Surface Adapter -> CLI/MCP/Web synchronization
       ▼
[Phase 3: Adversarial Verification & Merging]
       │  • Verifier subagent runs automated test suite & linting
       │  • Root Orchestrator inspects git diffs and reconciles branches
       │  • Developer summary & completion report (silent execution throughout)
```

---

## 2. Calibrated Model Tiering

To maximize speed, conserve quota, and maintain rock-solid reasoning:

| Layer | Recommended Model | Rationale |
| :--- | :--- | :--- |
| **Root Orchestrator** | **Gemini 3.8 Flash (High)** or **Gemini 3.1 Pro** | Handles deep planning, decomposition, diff merging, and high-level architecture. |
| **Worker Subagents** (Code / Surfaces) | `Model: "flash"` | Rapid execution, fast tool iterations, low latency. |
| **Scout / Investigator** (Audits / Logs) | `Model: "flash"` or `Model: "flash_lite"` | Scans logs and source files, distills into bulleted takeaways. |
| **Adversarial Verifier** | `Model: "flash"` | Runs test commands, parses test failures, and checks edge cases. |

---

## 3. The 4 Standard Subagent Roles

When invoking subagents via `invoke_subagent`, assign one of these standardized roles:

### Role 1: Scout / Investigator
* **Purpose**: Codebase exploration, stack trace analysis, and dependency audits.
* **Workspace**: `Workspace: "inherit"` (read-only; does not modify code).
* **Model**: `flash` or `flash_lite`.
* **Guardrail**: Must use `vifi scout <file>` or summarize findings into <= 200 tokens. Never dumps raw source files into the parent context.

### Role 2: Core Implementer
* **Purpose**: Implements core daemon logic, audio pipeline changes, state machines, or C/Python bindings.
* **Workspace**: `Workspace: "branch"` (isolated git branch to prevent concurrent write collisions).
* **Model**: `flash`.
* **Output**: Returns only the list of modified files, rationale, and diff overview.

### Role 3: Surface Adapter
* **Purpose**: Synchronizes secondary surfaces (CLI commands in `cli.py`, FastMCP tools in `mcp_server.py`, Cocoa AppKit HUD, or Web PWA frontends).
* **Workspace**: `Workspace: "branch"`.
* **Model**: `flash`.
* **Output**: Returns schema validation confirmations and updated flag lists.

### Role 4: Adversarial Verifier
* **Purpose**: Automated regression testing, linters, and edge-case verification.
* **Workspace**: `Workspace: "inherit"` or `Workspace: "branch"`.
* **Model**: `flash`.
* **Mandatory Testing Flags**: Must always execute tests with headless/mock guards:
  ```bash
  VOICEFI_MOCK_AUDIO=1 VOICEFI_HEADLESS=1 pytest tests/ -k <affected_area>
  ```
* **Output**: Returns pass/fail metrics, caught regressions, or lint issues.

---

## 4. High-Leverage Boost Recipes

### Recipe A: Multi-Surface Feature Rollout
Use when adding or modifying capabilities that span the daemon, CLI, MCP server, and HUD.
1. **Root Agent**: Defines the interface contract (Pydantic models, CLI syntax, MCP schema).
2. **Subagent 1 (Core)**: Implements changes in `src/voicefi/`.
3. **Subagent 2 (MCP & CLI)**: Updates `src/voicefi/cli.py` and `src/voicefi/mcp_server.py`.
4. **Subagent 3 (Docs & Tests)**: Updates test suites and user-facing docs.
5. **Verifier**: Runs test suite to verify 0 regressions across all surfaces.

### Recipe B: Race Condition & Audio Mutex Triangulation
Use when chasing intermittent deadlocks, lock contention (`/tmp/voicefi_audio_output.lock`), or PortAudio device issues.
1. **Subagent 1 (Mutex Auditor)**: Inspects lock acquisition order across `tts/`, `audio/`, and `integrations/`.
2. **Subagent 2 (Git Historian)**: Audits recent commits touching locking logic.
3. **Subagent 3 (Stress Tester)**: Constructs a minimal reproduction script in `scratch/` hammering concurrent calls.
4. **Root Agent**: Synthesizes the root cause and merges the definitive lock fix.

---

## 5. Execution Rules & Audio Policies

1. **Strict Audio Silence During Subagent Runs**:
   * Multi-agent execution must remain **completely silent** while subagents are running in the background. No chime triggers or partial TTS synthesis until the entire root plan finishes.
2. **Workspace Isolation**:
   * Never dispatch multiple write-enabled subagents on `Workspace: "inherit"`. Always use `Workspace: "branch"`.
3. **Concurrency Cap**:
   * Launch a maximum of 3 concurrent subagents at a time to prevent CPU/memory thrashing and rate limits.
4. **Concise Return Summaries**:
   * Subagents must return distilled, structured summaries. Never stream full file contents back to the root orchestrator.
