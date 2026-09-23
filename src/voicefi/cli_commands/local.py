"""
CLI commands for on-device local models: LiteRT, Gemma, Recon Scout, benchmarks, and Gemini Spark runner.
"""

import asyncio
import logging
from typing import Any

from voicefi.config import load_config

logger = logging.getLogger(__name__)


def cmd_spark(args: Any) -> None:
    """Run Gemini Spark agent runner with voice IPC bridge and turn-end hooks."""
    from voicefi.integrations.spark import GeminiSparkRunner

    config = load_config(getattr(args, "config", None))
    sock_path = getattr(args, "socket", None) or config.ipc.socket_path
    persona = getattr(args, "persona", None) or getattr(config.spark, "persona", "Viv")
    prompt = " ".join(args.prompt).strip() if getattr(args, "prompt", None) else None

    runner = GeminiSparkRunner(
        config=config,
        persona=persona,
    )

    if prompt:
        print(f'⚡ Executing Spark prompt in {persona} persona: "{prompt}"')

        async def _run_single():
            await runner.bridge.start()
            await asyncio.sleep(0.1)
            soundbite = await runner.execute_prompt(prompt)
            print(f'🏁 Spoken Soundbite: "{soundbite}"')
            await runner.stop()

        asyncio.run(_run_single())
        return

    print(f"🚀 Gemini Spark Voice Agent running (persona: {persona}). Listening on IPC bridge...")

    async def _run_loop():
        await runner.start()
        while True:
            await asyncio.sleep(1)

    try:
        asyncio.run(_run_loop())
    except KeyboardInterrupt:
        print("\n🛑 Stopping Gemini Spark...")
        asyncio.run(runner.stop())


def cmd_scout(args: Any) -> None:
    """Run on-device Recon Scout to pre-digest logs, code, or directories."""
    from voicefi.local import ReconScout

    target = getattr(args, "target", ".") or "."
    query = (
        getattr(args, "query", None)
        or "Analyze this file, identify any errors or anomalies, and extract key functions/logic."
    )
    max_bytes = getattr(args, "max_bytes", 500_000) or 500_000

    print(f"🔭 Launching VoiceFi Recon Scout on `{target}`...")
    scout = ReconScout()
    res = asyncio.run(scout.scout(target_path=target, query=query, max_bytes=max_bytes))

    print(f"\n⚡ Scout Completed in {res.duration_seconds}s ({res.model_name})")
    print(f"💰 Token Savings: {res.tokens_saved} tokens ({res.savings_pct}% context preserved)")
    print("-" * 60)
    print(res.findings)
    print("-" * 60)


def cmd_benchmark(args: Any) -> None:
    """Run on-device model, latency, and side-by-side Time on Task (ToT) benchmark suite."""
    import json
    from voicefi.local import LocalBenchmarkRunner

    runner = LocalBenchmarkRunner()

    is_compare = (
        getattr(args, "compare", False)
        or getattr(args, "command", "") == "eval"
        or getattr(args, "subcommand", "") == "eval"
    )

    if is_compare:
        if getattr(args, "history", False):
            print("\n📊 VoiceFi Time on Task (ToT) Benchmark History\n")
            print(runner.format_tot_history_table())
            return

        target = getattr(args, "target", "src/voicefi/local/engine.py") or "src/voicefi/local/engine.py"
        turns = getattr(args, "turns", 3) or 3
        cloud = getattr(args, "cloud", "gemini") or "gemini"
        prompt_words = getattr(args, "prompt", None)
        prompt = " ".join(prompt_words).strip() if prompt_words else None

        print("\n⚡ Running Empirical Time on Task (ToT) Benchmark...")
        print(f"   Target: {target} | Multi-turn: {turns} turns | Cloud: {cloud.capitalize()}\n")

        res = asyncio.run(
            runner.run_tot_comparison(
                target_path=target,
                prompt=prompt,
                turns=turns,
                cloud_provider=cloud,
            )
        )

        if getattr(args, "json", False):
            print(json.dumps(res.to_dict(), indent=2))
        else:
            print(runner.format_comparison_scorecard(res))
        return

    if getattr(args, "history", False):
        print(runner.format_scorecard_table())
        return

    prompt_words = getattr(args, "prompt", None)
    prompt = (
        " ".join(prompt_words).strip()
        if prompt_words
        else "Explain how distributed locks work in three concise bullet points."
    )
    name = getattr(args, "name", "CLI Benchmark") or "CLI Benchmark"

    print("⚡ Running VoiceFi on-device benchmark...")
    res = asyncio.run(runner.benchmark_prompt(prompt=prompt, test_name=name))
    print("\n" + runner.format_scorecard_table([res]))


def cmd_local(args: Any) -> None:
    """Inspect and manage on-device LiteRT and Gemma models."""
    from voicefi.local import LocalModelEngine

    engine = LocalModelEngine()
    action = getattr(args, "action", "status") or "status"

    if action == "status":
        st = engine.get_status()
        print("\n🤖 VoiceFi Local Model Status")
        print("=" * 45)
        print(
            f"  LiteRT Available:    {'✅ Yes' if st['litert_available'] else '❌ No (install with `uv pip install litert-lm`)'}"
        )
        print(f"  Hardware Backend:    {st['backend_desc']}")
        print(f"  Default Model:       {st['model_name']}")
        print(f"  Model Path:          {st['model_path']}")
        print(
            f"  Model File Exists:   {'✅ Yes (' + str(st['model_size_gb']) + ' GB)' if st['model_exists'] else '❌ Not found'}"
        )
        print(f"  Max Context Tokens:  {st['max_context_tokens']}")
        print(f"  Speculative Decode:  {st['speculative_decoding']}")
        print("-" * 45)
        models = st["imported_models"]
        print(f"  Imported Models ({len(models)}):")
        if models:
            for m in models:
                print(f"    • {m['name']} ({m['size_gb']} GB) -> {m['path']}")
        else:
            print("    (No models imported yet)")
            print("\n  💡 Tip: To download Gemma 4 26B, run:")
            print(
                "     litert-lm import --from-huggingface-repo=litert-community/gemma-4-26B-A4B-it-litert-lm gemma-4-26B-A4B-it-web.litertlm gemma4-26b"
            )
        print("=" * 45 + "\n")
    elif action == "list":
        models = engine.get_status()["imported_models"]
        if not models:
            print("No LiteRT models imported in ~/.litert-lm/models")
        else:
            for m in models:
                print(f"{m['name']}\t{m['size_gb']} GB\t{m['path']}")
    elif action == "download":
        print("📥 To download Gemma 4 26B (~16.8 GB) via LiteRT, run:")
        print(
            "litert-lm import --from-huggingface-repo=litert-community/gemma-4-26B-A4B-it-litert-lm gemma-4-26B-A4B-it-web.litertlm gemma4-26b"
        )
