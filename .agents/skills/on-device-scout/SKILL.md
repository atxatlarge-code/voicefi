---
name: on-device-scout
description: Pre-digests large files, logs, stack traces, and codebases on-device using local Gemma 4 on Apple Silicon Metal GPU to prevent context bloat, accelerate comprehension, and save cloud tokens.
---

# 🔭 On-Device Recon Scout Skill (LiteRT + Gemma on Metal GPU)

Use this skill whenever:
- You need to inspect large files (>150 lines), crash logs, compiler outputs, or test failure traces.
- You want to pre-digest raw code before reading it into the main chat context to avoid context bloat.
- You are working on sensitive files (credentials, billing, auth, `.env`) that should not leave the local machine.
- You want to benchmark on-device inference speed (TTFB, tokens/sec) on Apple Silicon Metal GPUs.

---

## ⚡ How to Trigger

### 1. In Antigravity 2.0 (MCP Tool)
Call the `voicefi_scout` tool via VoiceFi's MCP server:

```json
{
  "target_path": "src/voicefi/ipc/bridge.py",
  "query": "Explain socket fallback and barge-in signal handling"
}
```

### 2. From CLI (`vifi scout`)
Run the scout directly from the shell for instant background execution:

```bash
# Scout a single file with a query
vifi scout src/voicefi/cli.py -q "Where are audio commands routed?"

# Scout a crash or system log
vifi scout /var/log/system.log -q "Find CoreAudio crashes"

# Scout an entire directory
vifi scout tests/ -q "Summarize available test fixtures"
```

### 3. In Python Code
```python
import asyncio
from voicefi.local import ReconScout

async def inspect():
    scout = ReconScout()
    result = await scout.scout(
        target_path="path/to/large_file.py",
        query="Identify uncaught exceptions and exported functions",
    )
    print(f"Tokens Saved: {result.tokens_saved} ({result.savings_pct}%)")
    print(result.findings)

asyncio.run(inspect())
```

---

## 🛡️ Best Practices & Guardrails

1. **Pre-Digest First**: For files over 200 lines, run `vifi scout` first. Only read the specific lines pinpointed by the scout rather than loading the entire file into the chat window.
2. **Air-Gapped Privacy**: For client secrets, auth middleware, or sensitive tokens, use the local scout to verify correctness on-device without passing code to external cloud endpoints.
3. **Check Status**: Use `vifi local status` to verify that LiteRT is loaded and check active GPU memory and imported models.
