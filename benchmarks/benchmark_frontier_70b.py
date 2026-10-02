#!/usr/bin/env python3
"""
Frontier 70B Parameter Model Benchmark Suite for Apple Silicon Metal.
Tests prompt prefill throughput, autoregressive token generation, Time-To-First-Token (TTFT),
and effective memory bandwidth across Ollama (GGUF Metal) and Apple MLX frameworks.
"""

import argparse
import json
import os
import platform
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional
import psutil

# Ensure src is in python path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

REPORT_FILE = repo_root / "benchmarks" / "frontier_70b_report.json"


def check_ollama_available(base_url: str = "http://localhost:11434") -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def query_ollama_generate(
    model: str,
    prompt: str,
    num_ctx: int = 4096,
    num_predict: int = 128,
    temperature: float = 0.0,
    base_url: str = "http://localhost:11434",
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """Execute a single generation request against Ollama and return timing metrics."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    wall_time = time.perf_counter() - t0
    res["wall_time_sec"] = wall_time
    return res


def run_ollama_benchmark(model: str = "llama3.3:70b", num_ctx: int = 4096, num_predict: int = 128) -> Dict[str, Any]:
    print("=" * 70)
    print(f"🚀 Benchmarking Frontier 70B on Ollama (Metal GGUF)")
    print(f"   Model: {model} | Context Limit: {num_ctx} tokens | Gen: {num_predict} tokens")
    print("=" * 70)

    # 1. Warmup / Ingest pass
    print("🔥 Warmup pass (loading 42 GB weights into unified memory)...")
    t_start_load = time.perf_counter()
    warmup_res = query_ollama_generate(model, "Reply with 'ready'.", num_ctx=num_ctx, num_predict=5)
    load_time = (warmup_res.get("load_duration", 0) / 1e9) or (time.perf_counter() - t_start_load)
    print(f"   Model weight ingestion complete in {load_time:.2f}s\n")

    test_tiers = [
        ("Short Prompt (Code Analysis)", "Review this function: def add(a, b): return a + b. Explain its complexity and performance implications in detail.", 128),
        ("Medium Prompt (System Design)", "You are a principal systems architect. Design a high-throughput, distributed event-streaming bus for 100,000 events/sec. Provide architectural trade-offs, storage layout, partitioning strategy, and failure recovery protocols.", 256),
    ]

    results = []

    for name, prompt, gen_len in test_tiers:
        print(f"⚡ Testing: {name} (Gen: {gen_len} tokens)")
        res = query_ollama_generate(model, prompt, num_ctx=num_ctx, num_predict=gen_len)

        prompt_eval_count = res.get("prompt_eval_count", 0)
        prompt_eval_dur_s = res.get("prompt_eval_duration", 0) / 1e9
        prompt_eval_rate = prompt_eval_count / prompt_eval_dur_s if prompt_eval_dur_s > 0 else 0.0

        eval_count = res.get("eval_count", 0)
        eval_dur_s = res.get("eval_duration", 0) / 1e9
        eval_rate = eval_count / eval_dur_s if eval_dur_s > 0 else 0.0

        total_dur_s = res.get("total_duration", 0) / 1e9

        # Approximate memory bandwidth (Model Size GB * generation eval_rate)
        # 42.5 GB model streamed from RAM on every token
        effective_bandwidth_gbps = 42.5 * eval_rate

        metrics = {
            "tier_name": name,
            "prompt_tokens": prompt_eval_count,
            "prompt_eval_rate_tps": round(prompt_eval_rate, 2),
            "generated_tokens": eval_count,
            "eval_rate_tps": round(eval_rate, 2),
            "total_duration_sec": round(total_dur_s, 2),
            "effective_bandwidth_gbps": round(effective_bandwidth_gbps, 1),
            "response_preview": res.get("response", "").strip()[:80] + "...",
        }
        results.append(metrics)
        print(f"   Prefill / TTFT: {prompt_eval_rate:.2f} tokens/s ({prompt_eval_count} tokens in {prompt_eval_dur_s:.3f}s)")
        print(f"   Generation:     {eval_rate:.2f} tokens/s ({eval_count} tokens in {eval_dur_s:.2f}s)")
        print(f"   Bandwidth Est:  {effective_bandwidth_gbps:.1f} GB/s unified memory throughput\n")

    return {
        "engine": "Ollama (GGUF / Metal)",
        "model": model,
        "num_ctx": num_ctx,
        "weights_size_gb": 42.5,
        "load_duration_sec": round(load_time, 2),
        "tiers": results,
    }


def main():
    parser = argparse.ArgumentParser(description="VoiceFi Frontier 70B Metal Benchmark")
    parser.add_argument("--model", type=str, default="llama3.3:70b", help="Model name on Ollama")
    parser.add_argument("--num-ctx", type=int, default=4096, help="Context size (prevents 131k KV swap)")
    parser.add_argument("--num-predict", type=int, default=128, help="Number of tokens to generate")
    args = parser.parse_args()

    print("Checking Ollama daemon...")
    if not check_ollama_available():
        print("❌ Error: Ollama daemon is not responding on http://localhost:11434.")
        sys.exit(1)

    report = run_ollama_benchmark(model=args.model, num_ctx=args.num_ctx, num_predict=args.num_predict)

    # Persist report
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("=" * 70)
    print("📊 Summary Scorecard")
    print("=" * 70)
    print(f"{'Workload Tier':<32} | {'Prefill (t/s)':<14} | {'Gen (t/s)':<12} | {'Mem Bandwidth':<14}")
    print("-" * 78)
    for t in report["tiers"]:
        print(f"{t['tier_name'][:32]:<32} | {t['prompt_eval_rate_tps']:<14.2f} | {t['eval_rate_tps']:<12.2f} | {t['effective_bandwidth_gbps']:<8.1f} GB/s")
    print("=" * 78)
    print(f"Report saved to: {REPORT_FILE}\n")


if __name__ == "__main__":
    main()
