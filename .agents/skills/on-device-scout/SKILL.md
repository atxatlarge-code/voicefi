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

### 4. Empirical Time on Task (ToT) Benchmark (`vifi eval`)
Run side-by-side empirical comparisons of on-device Local Models (Gemma 4 on Metal 4 / Recon Scout) vs All-Cloud Models (Gemini / Claude over WAN):

```bash
# Run 3-turn side-by-side comparison on a repo file
vifi eval --target src/voicefi/local/benchmark.py --turns 3

# Benchmark against Claude instead of Gemini
vifi benchmark --compare --target src/voicefi/cli.py --cloud claude

# Output machine-readable JSON profile
vifi eval --target src/voicefi/local/engine.py --json

# View past ToT benchmark runs
vifi eval --history
```

---

## 📊 Empirical Performance Proof (Local vs All-Cloud)

Live empirical benchmarks on repository files demonstrate dramatic efficiency gains:

| Metric | Local (Gemma 4 / Scout) | All-Cloud (Gemini / WAN) | Advantage |
| :--- | :--- | :--- | :--- |
| **Ingress / Transport Latency** | **0.04 ms** (Unified RAM) | 31.92 ms (WAN RTT) | **709x Faster** |
| **Time to First Byte (TTFT)** | **48.0 ms** | 633.3 ms | **13.2x Faster** |
| **Turn 1 Latency** | 56.40s (Full 2B pre-digest) | 5.67s | Cloud Faster (Cold Load) |
| **Turn 2 Latency (Compounding)** | **0.36s** (Lean ~250 tok context) | 6.11s (Bloated context) | **17.0x Faster** |
| **Turn 3 Latency (Compounding)** | **0.42s** (Lean ~400 tok context) | 6.55s (Bloated context) | **15.6x Faster** |
| **Context Bloat (Final Prompt)** | **1,033 tokens** | 8,033 tokens | **87.1% Leaner (7.8x)** |
| **WAN Bandwidth Consumed** | **0 KB** (100% Air-Gapped) | 86.9 KB | **100% Saved** |
| **Total Cost (USD)** | **$0.0000** | $0.0020 / file | **$0 Cloud Cost** |

---

## 🛡️ Best Practices & Guardrails

1. **Pre-Digest First**: For files over 200 lines, run `vifi scout` first. Only read the specific lines pinpointed by the scout rather than loading the entire file into the chat window.
2. **Eliminate Multi-Turn Bloat**: In multi-turn refactoring sessions, pass the on-device scout's concise findings rather than re-transmitting raw 200KB+ files, avoiding quadratic context degradation.
3. **Air-Gapped Privacy**: For client secrets, auth middleware, or sensitive tokens, use the local scout to verify correctness on-device without passing code to external cloud endpoints.
4. **Check Status & Benchmark**: Use `vifi local status` to verify LiteRT and Metal GPU acceleration, and `vifi eval` to quantify ToT and bandwidth saved.
