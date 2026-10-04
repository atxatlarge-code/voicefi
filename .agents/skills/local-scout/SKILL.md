---
name: local-scout
description: Fast on-device reconnaissance and context compression. Pre-digests massive files, logs, tracebacks, and air-gapped secrets locally using Ollama (Qwen 2.5 Coder, Gemma 2, Tev1) and LiteRT on Apple Silicon Metal GPU, guarded by ThermalSupervisor to prevent context bloat and extract concise, actionable insights.
---

# 🔭 Local-Scout: Zero-Bloat Context Compression & Air-Gapped Recon

The **`local-scout`** skill provides pure, read-only reconnaissance and context compression. By executing on-device via local Ollama and LiteRT on Apple Silicon Metal GPU, it inspects multi-megabyte log files, crash dumps, and codebases in unified memory with **sub-0.2ms ingress latency** (typically 0.04–0.08 ms), returning distilled signals down to ~200 tokens (delivering **85%+ context compression**).

Use this skill whenever:
- You need to inspect files (>80 lines), crash logs, compiler outputs, or test failure traces before pulling them into cloud context.
- You want to pre-digest raw code to isolate specific functions, symbols, or anomaly root causes.
- You are working on sensitive or air-gapped files (`.env`, credentials, auth tokens, database dumps) that must **never** be transmitted over WAN.
- You want to eliminate cloud prompt degradation and save thousands of cloud tokens ($0 API cost).

---

## ⚡ Architecture: Zero-Copy Unified Memory Ingress

```
Raw File / Directory / Massive Log (>500 KB)
         │
         ▼ (<0.2 ms Unified Memory Ingress)
┌────────────────────────────────────────────────────────┐
│  ThermalSupervisor (pmset -g therm & Unified RAM Check) │  --> Blocks if thermal state is SERIOUS/CRITICAL
└──────────────────────────┬─────────────────────────────┘      or free unified RAM < 4.0 GB
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Active Recon Scout (Ollama / LiteRT on Metal GPU)     │  --> Ingests up to 500 KB locally;
│  • Primary: Ollama (qwen2.5-coder:1.5b, gemma2:2b,     │      extracts symbols, call traces, root causes
│             llama3.2:1b, tev1:latest, nimble:latest)   │
│  • Secondary: In-process LiteRT (gemma4-2b)            │
│  • Fallback: Fast AST/Regex Heuristic Extraction       │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Distilled Insight ~200 tokens | 85%+ Context Saved)
┌────────────────────────────────────────────────────────┐
│  Cloud Orchestrator (Antigravity / Claude Code)        │  --> Reads ONLY the concentrated summary!
└────────────────────────────────────────────────────────┘      Preserves 85–98% context window
```

---

## 🛠️ How to Trigger

### 1. Direct Python Module CLI (`voicefi.local.scout`)
Run directly with `uv run`:

```bash
# Scout a source file for key logic and anomalies
uv run python -m voicefi.local.scout src/voicefi/local/supervisor.py -q "Summarize thermal thresholds and guard decorator"

# Scout an entire directory structure
uv run python -m voicefi.local.scout src/voicefi/tts/ -q "List all supported TTS backend classes"

# Scout system or application crash logs
uv run python -m voicefi.local.scout /var/log/system.log -q "Find CoreAudio crashes and audio buffer underruns"

# Emit structured JSON output (includes tokens_saved, duration, read_latency_ms, model_name)
uv run python -m voicefi.local.scout src/voicefi/cli.py -q "Where are audio commands routed?" --json
```

### 2. High-Level CLI (`vifi scout`)
```bash
# Scout a source file
vifi scout src/voicefi/local/scout.py -q "Explain Ollama model discovery and fallback hierarchy"

# Scout crash or error log
vifi scout .agents/QA_AUDIT.md -q "Summarize the latest test and lint failure causes"
```

### 3. In Antigravity & Claude Code (MCP Tool: `voicefi_scout`)
To scout or pre-digest a file or directory before reading into cloud context:

```json
{
  "target_path": "src/voicefi/local/supervisor.py",
  "query": "Check how pmset -g therm parses thermal pressure states",
  "max_bytes": 500000
}
```

### 4. In Python Code
```python
import asyncio
from voicefi.local.scout import ReconScout
from voicefi.local.supervisor import default_supervisor

async def run():
    # Hardware check: ensure thermals and RAM are safe
    default_supervisor.wait_if_throttled(poll_interval=2.0, max_wait=10.0)

    scout = ReconScout()
    result = await scout.scout(
        target_path="src/voicefi/local/supervisor.py",
        query="Explain thermal and memory safety guardrails",
        max_bytes=500_000,
    )

    print(f"Model Used:      {result.model_name}")
    print(f"Read Latency:    {result.read_latency_ms} ms (Ingress: {result.ingress_mode})")
    print(f"Duration:        {result.duration_seconds} s")
    print(f"Tokens Saved:    {result.tokens_saved} ({result.savings_pct}% compression)")
    print("\nFindings:\n", result.findings)

asyncio.run(run())
```

---

## 🔬 Model Tier Hierarchy & Auto-Discovery

The Recon Scout evaluates local inference engines in prioritized order:
1. **Local Ollama Daemon (`http://127.0.0.1:11434`)**: Automatically queries `/api/tags` and selects the fastest installed coder/reasoning model:
   - `qwen2.5-coder:1.5b` (ultra-fast coding recon, ~980MB RAM)
   - `gemma2:2b` (Google high-density general recon, ~1.6GB RAM)
   - `llama3.2:1b` (Meta lightweight recon, ~1.3GB RAM)
   - `tev1:latest` / `tev1:0.8b` (Qwen 3.5 edge fine-tunes)
   - `nimble:latest` (Qwen 3.5 9B reasoning)
2. **In-Process LiteRT Engine**: Apple Silicon Metal GPU execution via `litert_lm.Engine` or `google.antigravity.Agent` if model weights exist under `~/.litert-lm/models/`.
3. **Deterministic Heuristic Extractor**: Sub-millisecond regex and stack-trace parser if local LLM servers are offline, ensuring scout calls never fail.

---

## 🛡️ Guardrails & Best Practices

1. **Read-Only Invariant**: `local-scout` is strictly non-mutating. Never modifies files on disk. To execute code edits or generate diffs, transition to the **`local-dev`** skill (`voicefi_implement` or `vifi implement`).
2. **Thermal & RAM Protection**: Local inference is guarded by `ThermalSupervisor`. If macOS reports `SERIOUS` or `CRITICAL` thermal pressure (`pmset -g therm`) or available unified RAM drops below 4.0 GB, execution automatically pauses until hardware cools down.
3. **Air-Gapped Confidentiality**: Always route `.env` secrets, authentication tokens, customer data, and proprietary patent disclosures through `local-scout` so that raw content remains in unified RAM and is never sent to cloud model providers.
