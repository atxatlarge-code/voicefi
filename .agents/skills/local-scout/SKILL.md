---
name: local-scout
description: Fast on-device reconnaissance and context compression. Pre-digests massive files, logs, tracebacks, and air-gapped secrets locally using Gemma 4 (2B) on Apple Silicon Metal GPU to prevent context bloat and extract concise, actionable insights.
---

# 🔭 Local-Scout: Zero-Bloat Context Compression & Air-Gapped Recon

The **`local-scout`** skill provides pure, read-only reconnaissance and context compression. By executing on-device via LiteRT and Apple Silicon Metal GPU, it inspects multi-megabyte log files, crash dumps, and codebases in unified memory (0.04 ms latency), returning distilled signals down to ~200 tokens.

Use this skill whenever:
- You need to inspect files (>80 lines), crash logs, compiler outputs, or test failure traces before pulling them into cloud context.
- You want to pre-digest raw code to isolate specific functions, symbols, or anomaly root causes.
- You are working on sensitive or air-gapped files (`.env`, credentials, auth tokens, database dumps) that must **never** be transmitted over WAN.
- You want to eliminate cloud prompt degradation and token costs.

---

## ⚡ Architecture: Zero-Copy Unified Memory Ingress

```
Raw File / Directory / Massive Log (>500 KB)
         │
         ▼ (0.04 ms Unified Memory Ingress)
┌───────────────────────────────────────┐
│  Gemma 4 2B (On-Device Recon Scout)   │  --> Ingests up to 500k bytes locally;
└──────────────────┬────────────────────┘      extracts symbols, call traces, root causes
                   │
                   ▼ (Distilled Insight ~200 tokens)
┌───────────────────────────────────────┐
│  Cloud Orchestrator (Antigravity)     │  --> Reads ONLY the concentrated summary!
└───────────────────────────────────────┘      Preserves 95-98% context window
```

---

## 🛠️ How to Trigger

### 1. In Antigravity & Claude Code (MCP Tool: `voicefi_scout`)
To scout or pre-digest a file or directory:

```json
{
  "target_path": "src/voicefi/ipc/bridge.py",
  "query": "Explain socket fallback and barge-in signal handling",
  "context": "Scouting file on-device to isolate signal handling logic before cloud reasoning turn."
}
```

To pre-digest a crash log or test failure:
```json
{
  "target_path": "/var/log/system.log",
  "query": "Find CoreAudio crashes and audio buffer underruns",
  "context": "Extracting audio failure events on-device."
}
```

### 2. From CLI (`vifi scout`)
Run directly in your terminal:

```bash
# Scout a source file for key logic
vifi scout src/voicefi/cli.py -q "Where are audio commands routed?"

# Scout a system crash log
vifi scout /var/log/system.log -q "Find CoreAudio crashes"

# Scout an entire directory structure
vifi scout src/voicefi/tts/ -q "List all supported TTS backend classes"
```

### 3. In Python Code
```python
import asyncio
from voicefi.local import ReconScout

async def run():
    scout = ReconScout()
    findings = await scout.scout(
        target_path="src/voicefi/engine.py",
        query="Identify memory leaks or unclosed sockets",
        max_bytes=500_000,
    )
    print("Tokens saved:", findings.tokens_saved)
    print("Summary:", findings.findings)

asyncio.run(run())
```

---

## 🛡️ Guardrails

1. **Read-Only Invariant**: `local-scout` is strictly non-mutating. If you need to make code edits or generate diffs, transition to the **`local-dev`** skill.
2. **Privacy Assurance**: Always use `local-scout` when inspecting files with sensitive keys, `.env` files, or customer records so the content never leaves Apple Silicon memory.
