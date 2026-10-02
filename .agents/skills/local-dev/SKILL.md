---
name: local-dev
description: The core on-device engineer. Executes surgical code modifications, refactors, AST-aware search/replace, and autonomous self-healing test loops locally using Gemma 4 (2B Scout + 26B Coder) on Apple Silicon Metal GPU, returning only the clean unified git diff.
---

# 💻 Local-Dev: On-Device Code Implementation & Self-Healing Loop

The **`local-dev`** skill turns local Apple Silicon (Metal GPU + LiteRT) into an active, private software engineer and pair programmer. It replaces expensive cloud file rewriting by performing AST-aware code edits locally and returning **only the unified git diff** to Antigravity and Claude Code.

Use this skill whenever:
- You need to modify or refactor code in existing files (>80 lines) without ingesting entire files into cloud context.
- You want to solve bugs using an autonomous on-device test-fix cycle (`vifi fix`) with zero cloud roundtrips.
- You are working on sensitive or proprietary logic that must remain on the local machine.
- You want to eliminate cloud prompt degradation and achieve >90% token cost reduction.

---

## ⚡ Architecture: The 3-Tier Local-Dev Pipeline

```
Target File (>80 lines) + Instruction
         │
         ▼ (0.04 ms Unified Memory Ingress)
┌───────────────────────────────────────┐
│  Tier 1: Gemma 4 2B (Locus Pinpoint)  │  --> 2.8s: Locates exact target symbol/function
└──────────────────┬────────────────────┘
                   │
                   ▼ (Targeted Slice ~250 tokens)
┌───────────────────────────────────────┐
│  Tier 2: Gemma 4 26B (Code Craftsman) │  --> Generates exact SEARCH/REPLACE blocks
└──────────────────┬────────────────────┘      and applies changes locally
                   │
                   ▼ (AST & Syntax Verification)
┌───────────────────────────────────────┐
│  Tier 3: Local Self-Healing Sandbox   │  --> Runs linter / pytest up to 3 turns
└──────────────────┬────────────────────┘
                   │
                   ▼ (difflib / git diff)
┌───────────────────────────────────────┐
│  Cloud Reviewer (Antigravity/Gemini)  │  --> Reads ONLY the 20-30 line unified diff!
└───────────────────────────────────────┘      Zero context bloat; 95%+ token savings
```

---

## 🛠️ How to Trigger

### 1. In Antigravity & Claude Code (MCP Tool: `voicefi_implement`)
Delegate an implementation task on-device without ingesting the file:

```json
{
  "target_path": "src/voicefi/ipc/bridge.py",
  "instruction": "Add exponential backoff retry to socket reconnection logic",
  "context": "Executing local-dev cascade to modify socket retry while keeping cloud context lean."
}
```

### 2. Autonomous Loop / Bug Fixing (MCP Tool: `voicefi_agent_loop` / `voicefi_auto`)
To run a multi-turn self-healing loop:

```json
{
  "goal": "Fix TypeError: 'NoneType' object is not subscriptable in engine.py and ensure tests pass"
}
```

### 3. From CLI (`vifi implement` / `vifi dev` & `vifi fix`)
Run directly in your terminal:

```bash
# 🎯 Implement a feature or refactor locally
vifi implement src/voicefi/cli.py -i "Add --dry-run flag to compile command"

# 📋 Solve directly from macOS clipboard (Cmd+C any traceback)
vifi fix --clip

# 🚰 Pipe directly from a failing test suite with 3-turn self-healing
pytest tests/test_engine.py | vifi fix

# 🔍 Dry run preview (does not write to disk)
vifi implement src/voicefi/cli.py -i "Refactor error handling" --dry-run
```

### 4. In Python Code
```python
import asyncio
from voicefi.local import ReconImplementer, LocalAutonomousLoop

async def run():
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

## 🛡️ Best Practices & Guardrails

1. **Diff-First Protocol**: For files over 80 lines, always prefer calling `voicefi_implement` instead of reading entire files into cloud chat and overwriting them with `replace_file_content`.
2. **Review the Unified Diff**: When the implementer returns the diff, verify line additions, typing annotations, and edge cases.
3. **Local Self-Healing Sandbox**: When tests fail, let `vifi fix` or `LocalAutonomousLoop` run its 3-turn repair cycle on-device before escalating to cloud models.
