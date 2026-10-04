---
name: local-dev
description: The core on-device engineer. Executes surgical code modifications, refactors, AST-aware search/replace, and autonomous self-healing test loops locally using Ollama (Qwen 2.5 Coder, Gemma 2, Llama 3.3 70B) and LiteRT on Apple Silicon Metal GPU, guarded by ThermalSupervisor, returning only the clean unified git diff.
---

# 💻 Local-Dev: On-Device Code Implementation & Self-Healing Loop

The **`local-dev`** skill turns local Apple Silicon (Metal GPU + Ollama / LiteRT) into an active, private software engineer and pair programmer. It replaces expensive cloud file rewriting by performing AST-aware code edits locally and returning **only the unified git diff** to Antigravity and Claude Code.

Use this skill whenever:
- You need to modify or refactor code in existing files (>80 lines) without ingesting entire files into cloud context.
- You want to solve bugs using an autonomous on-device test-fix cycle (`vifi auto` or `vifi fix`) with zero cloud roundtrips.
- You are working on sensitive or proprietary logic that must remain on the local machine.
- You want to eliminate cloud prompt degradation and achieve >90% token cost reduction.

---

## ⚡ Architecture: The 3-Tier Local-Dev Pipeline

```
Target File (>80 lines) + Implementation Instruction
         │
         ▼ (<0.2 ms Unified Memory Ingress)
┌────────────────────────────────────────────────────────┐
│  Stage 0: ThermalSupervisor Telemetry Guard            │  --> Verifies pmset -g therm is NORMAL/FAIR
│           (wait_if_throttled)                          │      and free unified RAM >= 4.0 GB
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Tier 1: AST Symbol Locator & Scout                    │  --> Locates exact target symbol/function
│          (voicefi_symbol_query / scout)                │      via SQLite AST index in <5ms
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Targeted Slice ~250 tokens)
┌────────────────────────────────────────────────────────┐
│  Tier 2: Local Code Craftsman                          │  --> Generates exact SEARCH/REPLACE blocks
│          (Qwen 2.5 Coder / Gemma 2 / Llama 3.3 70B)    │      and applies surgical changes locally
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (AST & Syntax Verification)
┌────────────────────────────────────────────────────────┐
│  Tier 3: Local Self-Healing Sandbox                    │  --> Runs linter / pytest up to 3 turns
│          (ruff check & pytest --maxfail=1)             │      auto-remedying test errors
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Unified Git Diff | 20-40 lines)
┌────────────────────────────────────────────────────────┐
│  Cloud Reviewer (Antigravity / Claude Code)            │  --> Reads ONLY the clean unified diff!
└────────────────────────────────────────────────────────┘      Zero context bloat; 95%+ token savings
```

---

## 🛠️ How to Trigger

### 1. High-Level CLI (`vifi implement`, `vifi auto`, `vifi fix`)
Run directly in your terminal:

```bash
# 🎯 Implement a feature or refactor locally and apply changes
vifi implement src/voicefi/cli.py -i "Add --dry-run flag to compile command"

# 🔍 Dry run preview (outputs diff without writing to disk)
vifi implement src/voicefi/cli.py -i "Refactor error handling" --dry-run

# 🤖 Run autonomous multi-turn engineering loop with test verification
vifi auto --goal "Fix socket reconnection retry backoff" --test "pytest tests/test_bridge.py" --max-turns 5

# 📋 Solve error directly from macOS clipboard (Cmd+C any traceback)
vifi fix --clip

# 🚰 Pipe directly from a failing test suite with 3-turn self-healing
pytest tests/test_engine.py | vifi fix
```

### 2. In Antigravity & Claude Code (MCP Tools)

#### Surgical Implementation (`voicefi_implement`)
Delegate an implementation task on-device without ingesting the file:
```json
{
  "target_path": "src/voicefi/ipc/bridge.py",
  "instruction": "Add exponential backoff retry to socket reconnection logic",
  "apply": true,
  "diff_only": true,
  "context": "Executing local-dev cascade to modify socket retry while keeping cloud context lean."
}
```

#### Autonomous Engineering Loop (`voicefi_auto`)
Run a multi-turn autonomous repair loop:
```json
{
  "task": "Resolve TypeError in engine.py and ensure tests pass",
  "model": "qwen2.5-coder:1.5b",
  "max_turns": 6
}
```

#### Fast AST Symbol Query (`voicefi_symbol_query`)
Search the on-device symbol index:
```json
{
  "query": "ThermalSupervisor",
  "exact": false,
  "limit": 10
}
```

### 3. In Python Code
```python
import asyncio
from voicefi.local import ReconImplementer, LocalAutonomousLoop
from voicefi.local.supervisor import default_supervisor

async def run():
    # Verify hardware safety before heavy loop
    default_supervisor.wait_if_throttled()

    # Surgical code modification returning diff
    implementer = ReconImplementer()
    result = await implementer.implement(
        target_path="src/voicefi/engine.py",
        instruction="Add timeout guard to websocket read loop",
    )
    print("Diff tokens saved:", result.tokens_saved)
    print(result.diff)

asyncio.run(run())
```

---

## 🔬 Supported Local Models

* **`qwen2.5-coder:1.5b`** (Default Fast Coder): Ultra-lightweight on-device coding model (~980MB RAM) delivering sub-3s turn turnaround.
* **`gemma2:2b`**: Google compact model for general syntax cleanup and prompt distillation.
* **`llama3.3:70b`** (Heavyweight Reasoning Tier): 4-bit quantized frontier model running on Apple Silicon unified RAM for complex multi-file architectural reasoning.
* **`gemma4-26b`**: In-process LiteRT Metal GPU engine under `~/.litert-lm/models/gemma4-26b`.

---

## 🛡️ Best Practices & Guardrails

1. **Diff-First Protocol**: For files over 80 lines, always prefer calling `voicefi_implement` or `voicefi_auto` instead of reading entire files into cloud chat and overwriting them with `replace_file_content`.
2. **Thermal & Memory Supervision**: The autonomous loop respects `ThermalSupervisor`. If CPU load exceeds 12.0 or free unified RAM drops below 4.0 GB, operations pause automatically until nominal.
3. **AST & Syntax Guard**: Never accept a diff until AST parsing (`ast.parse`) passes cleanly.
4. **Self-Healing Circuit Breaker**: Auto-fix retries are bounded to a maximum of 3 turns to prevent infinite loops. If unresolved after 3 iterations, bundle the minimal reproduction and escalate to the cloud orchestrator.
