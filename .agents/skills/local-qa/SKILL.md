---
name: local-qa
description: On-device verification, diff auditing, and test synthesis. Runs local test suites (pytest, ruff), audits pending git diffs for syntax regressions and edge cases, and synthesizes missing unit tests without cloud token burn using Ollama and ThermalSupervisor on Apple Silicon.
---

# 🧪 Local-QA: On-Device Verification, Diff Auditing & Test Synthesis

The **`local-qa`** skill serves as the on-device test gatekeeper and quality auditor. It ingests thousands of lines of raw test runner outputs, compiler errors, and lint traces in unified memory (sub-0.2ms latency), validates git diffs before merging, synthesizes missing unit tests locally on Apple Silicon Metal GPU, and generates a structured scorecard to `.agents/QA_AUDIT.md`.

Use this skill whenever:
- You need to verify a pending git diff for syntax errors, typing mismatches, or regression risks before cloud acceptance.
- You have large test suites (`pytest`) or lint runs (`ruff check`) producing massive output that would blow out cloud context.
- You want to synthesize targeted unit test cases for newly added functions or uncovered branches.
- You want to benchmark on-device inference speed, RAM ingress, or WAN transfer deltas with zero cloud API token cost.

---

## ⚡ Architecture: The 5-Stage Verification Gate

```
Pending Git Diff (Working Tree, Staged, or Revision Range)
         │
         ▼ (<0.2 ms Unified Memory Ingress)
┌────────────────────────────────────────────────────────┐
│  Stage 1: ThermalSupervisor Telemetry Guard            │  --> Verifies pmset -g therm is NORMAL/FAIR
│           (wait_if_throttled)                          │      and free unified RAM >= 4.0 GB
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Stage 2: Fast Linter Gate (`uvx ruff check`)          │  --> Lints only modified Python files in diff
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Stage 3: Targeted Unit Tests (`uv run pytest`)        │  --> Runs targeted test suite with --maxfail=3
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Stage 4: On-Device Model Audit & Test Synthesis       │  --> Ollama (qwen2.5-coder:1.5b, gemma2:2b)
│           (Risk Assessment, Edge Cases, Test Code)     │      performs deep code review & test synthesis
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Stage 5: Scorecard Emission (`.agents/QA_AUDIT.md`)   │  --> Emits actionable markdown report;
└────────────────────────────────────────────────────────┘      Antigravity inspects ONLY the scorecard
```

---

## 🛠️ How to Trigger

### 1. Dedicated Local QA Runner (`scripts/local_qa.py`)
Run directly via `uv run`:

```bash
# 🔍 Audit current working tree changes (or fallback to HEAD~1 if clean)
uv run python scripts/local_qa.py

# 📋 Audit only staged changes prior to git commit
uv run python scripts/local_qa.py --staged

# 🔄 Audit a specific git commit range or branch comparison
uv run python scripts/local_qa.py --rev HEAD~1
uv run python scripts/local_qa.py --rev main..HEAD

# 🎯 Run with a targeted test suite
uv run python scripts/local_qa.py --test-target tests/test_content_factory.py

# ⚡ Skip pytest to run fast linter + local code review only
uv run python scripts/local_qa.py --skip-tests

# 📝 Output to a custom audit scorecard file
uv run python scripts/local_qa.py --output-file .agents/QA_AUDIT.md
```

### 2. High-Level CLI & Test Harnesses
```bash
# 🧪 Run full local test suite with self-healing feedback loop
pytest tests/ -v | vifi fix

# 🔍 Benchmark unified memory vs cloud ingress
vifi bench

# 📊 Check local model readiness and Metal GPU utilization
vifi local status

# 📈 Run empirical Time on Task (ToT) benchmark comparing local vs cloud
vifi eval --target src/voicefi/local/engine.py --turns 3
vifi eval --history
```

### 3. In Antigravity & Claude Code (MCP Tools)
- Check local hardware status and model readiness:
  ```json
  // Tool: voicefi_local_status
  {}
  ```
- Run on-device performance benchmarks:
  ```json
  // Tool: voicefi_benchmark
  {
    "prompt": "Evaluate AST boundary conditions for socket timeouts",
    "test_name": "Socket Boundary Audit"
  }
  ```
- Trigger an autonomous local repair loop:
  ```json
  // Tool: voicefi_auto
  {
    "task": "Fix ruff lint errors and missing type annotations in src/voicefi/local/scout.py",
    "model": "qwen2.5-coder:1.5b",
    "max_turns": 5
  }
  ```

---

## 📊 Scorecard Output (`.agents/QA_AUDIT.md`)

When `local_qa.py` completes, it generates a comprehensive verification scorecard containing:
1. **Model & Hardware Metadata**: Model identifier (e.g. `qwen2.5-coder:1.5b`), inference duration, and local tokens processed ($0 cloud spend).
2. **Automated Test Gates**: Status of `ruff` lint check and `pytest` test run.
3. **Architectural Review & Risk Assessment**: Risk classification (`Low`, `Medium`, `High`).
4. **Edge Cases & Vulnerabilities**: Boundary conditions, unhandled exceptions, and concurrency concerns.
5. **Proposed Missing Unit Test Cases**: Complete copy-pasteable `def test_*` functions ready to paste into `tests/`.

---

## 🛡️ Guardrails & Best Practices

1. **Hardware Telemetry Check**: `local_qa.py` invokes `default_supervisor.wait_if_throttled(poll_interval=2.0, max_wait=10.0)` before executing tests or inference. If the machine is experiencing heavy thermal pressure (`pmset -g therm`) or unified memory is below 4.0 GB, it pauses execution until nominal.
2. **Deterministic Pre-Commit Gate**: Always run `uv run python scripts/local_qa.py --staged` before submitting a pull request or finalizing a multi-file refactor.
3. **Escalation Protocol**: If local tests fail and cannot be repaired within 3 autonomous turns, inspect `.agents/QA_AUDIT.md` and escalate the minimal failing test reproduction to the cloud orchestrator.
