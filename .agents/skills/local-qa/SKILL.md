---
name: local-qa
description: On-device verification, diff auditing, and test synthesis. Runs local test suites (pytest, ruff), audits pending git diffs for syntax regressions and edge cases, and synthesizes missing unit tests without cloud token burn.
---

# 🧪 Local-QA: On-Device Verification, Diff Auditing & Test Synthesis

The **`local-qa`** skill serves as the on-device test gatekeeper and quality auditor. It ingests thousands of lines of raw test runner outputs, compiler errors, and lint traces in unified memory (0.04 ms latency), validates git diffs before merging, and synthesizes missing unit tests locally on Apple Silicon Metal GPU.

Use this skill whenever:
- You need to verify a pending git diff for syntax errors, typing mismatches, or regression risks before cloud acceptance.
- You have large test suites (`pytest`) or lint runs (`ruff check`) producing massive output that would blow out cloud context.
- You want to synthesize targeted unit test cases for newly added functions or uncovered branches.
- You want to benchmark on-device inference speed, RAM ingress, or WAN transfer deltas.

---

## ⚡ Architecture: The On-Device Verification Gate

```
Pending Git Diff or Test Failure Stream (>5,000 lines)
         │
         ▼ (Zero WAN upload; local unified RAM)
┌───────────────────────────────────────┐
│  Tier 1: Local Test / Lint Runner     │  --> Executes pytest / ruff in local environment
└──────────────────┬────────────────────┘
                   │
                   ▼ (Failure Trace / AST Delta)
┌───────────────────────────────────────┐
│  Tier 2: Gemma 4 QA Auditor           │  --> Checks edge cases, type hints, regressions;
└──────────────────┬────────────────────┘      synthesizes parameterized unit tests
                   │
                   ▼ (Verdict & Test Patch)
┌───────────────────────────────────────┐
│  Cloud Orchestrator (Antigravity)     │  --> Receives clean PASS/FAIL verdict + minimal repro
└───────────────────────────────────────┘
```

---

## 🛠️ How to Trigger

### 1. In Antigravity & Claude Code (MCP Tools)
- Check local hardware status and model readiness:
  ```json
  // Tool: voicefi_local_status
  {}
  ```
- Run on-device performance benchmarks:
  ```json
  // Tool: voicefi_benchmark
  {
    "model_name": "gemma4-26b",
    "prompt": "Evaluate AST boundary conditions for socket timeouts",
    "runs": 3
  }
  ```

### 2. From CLI & Test Harnesses
```bash
# 🧪 Run full local test suite with self-healing feedback
pytest tests/ -v | vifi fix

# 🔍 Benchmark unified memory vs cloud ingress
vifi bench

# 📊 Check local model readiness and Metal GPU utilization
vifi local status
```

### 3. In Python Code
```python
import asyncio
from voicefi.local import LocalBenchmarkRunner

async def run():
    runner = LocalBenchmarkRunner()
    result = await runner.run_tot_comparison(
        prompt="Synthesize unit test for websocket reconnection retry",
        model_name="gemma4-26b",
    )
    print("Local latency ms:", result.local_duration_ms)
    print("Ingress speedup:", result.ingress_speedup_factor)

asyncio.run(run())
```

---

## 🛡️ Guardrails

1. **Dry-Run Syntax Guard**: Never accept a diff until AST parsing (`ast.parse`) or `py_compile` passes cleanly.
2. **Circuit Breaker**: When running test loops, limit auto-fix retries to a maximum of 3 turns to prevent infinite repair loops.
3. **Escalation Protocol**: If local test healing cannot resolve after 3 iterations, bundle the minimal failing reproduction case and escalate to the cloud orchestrator.
