---
name: on-device-scout
description: Pre-digests large files, logs, and stack traces, and implements surgical code changes using local Gemma 4 (2B Scout + 26B Coder) on Apple Silicon Metal GPU to prevent context bloat, accelerate comprehension, and save >90% of cloud tokens.
---

# 🔭 On-Device Recon Scout & Implementer Skill (LiteRT + Gemma on Metal GPU)

Use this skill whenever:
- You need to inspect or modify files (>80 lines), crash logs, compiler outputs, or test failure traces.
- You want to pre-digest raw code before reading it into the main chat context to avoid context bloat.
- You want to surgically edit code on-device using local Gemma 4 and review **only the clean unified git diff**.
- You are working on sensitive files (credentials, billing, auth, `.env`) that should not leave the local machine.
- You want to eliminate multi-turn cloud prompt degradation and token costs.

---

## ⚡ Architecture: The 2-Tier On-Device Cascade

```
Target File (>80 lines)
        │
        ▼ (0.04 ms Unified Memory)
┌───────────────────────────────────────┐
│  Tier 1: Gemma 4 2B (Recon Scout)     │  --> 2.8s turnaround: Pinpoints exact function
└──────────────────┬────────────────────┘      and lines needing modification
                   │
                   ▼ (Targeted Slice ~250 tokens)
┌───────────────────────────────────────┐
│  Tier 2: Gemma 4 26B (Code Craftsman) │  --> Generates exact SEARCH/REPLACE blocks
└──────────────────┬────────────────────┘      and applies changes locally
                   │
                   ▼ (difflib / git diff)
┌───────────────────────────────────────┐
│  Cloud Reviewer (Antigravity/Gemini)  │  --> Reads ONLY the 30-line git diff!
└───────────────────────────────────────┘      Saves 92-98% cloud context tokens
```

---

## 🛠️ How to Trigger

### 1. In Antigravity (MCP Tool)
To implement an edit on a file without ingesting the whole file into cloud context:

```json
{
  "target_path": "src/voicefi/ipc/bridge.py",
  "instruction": "Add exponential backoff retry to socket reconnection",
  "context": "Executing on-device 2-tier implementation cascade to modify bridge socket retry logic while keeping cloud context lean."
}
```

To scout/read a file or directory:
```json
{
  "target_path": "src/voicefi/ipc/bridge.py",
  "query": "Explain socket fallback and barge-in signal handling",
  "context": "Scouting file on-device to isolate signal handling logic before cloud reasoning turn."
}
```

### 2. From CLI (`vifi fix`, `vifi implement` & `vifi scout`)
Run directly from any terminal on your Mac:

```bash
# 🎯 Instant Bug Solving with 2-turn self-healing test loop
vifi fix src/voicefi/engine.py -e "TypeError: 'NoneType' object is not subscriptable" -t "pytest tests/test_engine.py"

# 📋 Solve directly from macOS clipboard (Cmd+C any traceback)
vifi fix --clip

# 🚰 Pipe directly from a failing test suite
pytest tests/test_engine.py | vifi fix

# 🔍 Dry run preview (does not write to disk)
vifi fix src/voicefi/cli.py -e "Fix typo in help string" --dry-run

# Implement a feature/refactor
vifi implement src/voicefi/cli.py -i "Add --dry-run flag to compile command"

# Scout a file or crash log
vifi scout src/voicefi/cli.py -q "Where are audio commands routed?"
vifi scout /var/log/system.log -q "Find CoreAudio crashes"
```

### 3. In Python Code
```python
import asyncio
from voicefi.local import ReconImplementer, ReconScout

async def run():
    # 1. Scout
    scout = ReconScout()
    findings = await scout.scout("src/voicefi/engine.py", query="Identify memory leaks")
    print("Scout savings:", findings.savings_pct)

    # 2. Implement
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

## 📊 Empirical Savings Across Factors

| Factor | Full Cloud Ingestion | Local Scout (2B) + 26B $\rightarrow$ Diff | Advantage |
| :--- | :--- | :--- | :--- |
| **Cloud Prompt Tokens** | 25,000 – 80,000+ tokens / turn | 300 – 1,200 tokens (diff only) | **92% – 98% Token Reduction** |
| **Direct API Cost** | \$0.05 – \$0.50+ per coding turn | \$0.0005 per turn (Local GPU = \$0) | **95%+ Cost Savings** |
| **Attention Sharpness** | Attention dilution across giant files | 100% focused on the patch delta | **Zero Context Drift** |
| **Transport Ingress** | 30 ms – 150 ms WAN upload | 0.04 ms (Unified RAM) | **700x Ingress Speedup** |
| **Air-Gapped Privacy** | Proprietary code transmitted over WAN | 100% on-device; only diff leaves | **Complete Privacy** |

---

## 🛡️ Best Practices & Guardrails

1. **Diff-First Protocol**: For existing files over 80 lines, always prefer calling `voicefi_implement` or `vifi implement` instead of loading entire files into the conversation transcript.
2. **Review the Unified Diff**: When the implementer returns the diff, carefully check line additions and deletions for edge cases, typing correctness, and potential regressions.
3. **Local Self-Healing**: Run test commands (`pytest`, `ruff check`) on the modified file immediately after applying. If tests fail, feed the error back to `voicefi_implement`.
