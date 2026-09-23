"""
Unit tests for VoiceFi LocalBenchmarkRunner and scorecard formatting.
"""

import asyncio
from pathlib import Path
from voicefi.local.benchmark import LocalBenchmarkRunner, BenchmarkResult


def test_benchmark_runner_prompt(tmp_path: Path):
    db_file = tmp_path / "test_benchmarks.json"
    runner = LocalBenchmarkRunner(db_path=db_file)

    res = asyncio.run(runner.benchmark_prompt(prompt="Test prompt", test_name="Unit Test"))
    assert isinstance(res, BenchmarkResult)
    assert res.test_name == "Unit Test"
    assert res.ttfb_ms > 0
    assert res.tok_per_sec > 0
    assert res.cost_usd == 0.0

    # Verify persistent storage
    history = runner.load_history()
    assert len(history) == 1
    assert history[0]["test_name"] == "Unit Test"


def test_scorecard_table_formatting(tmp_path: Path):
    db_file = tmp_path / "test_benchmarks.json"
    runner = LocalBenchmarkRunner(db_path=db_file)

    dummy_result = BenchmarkResult(
        test_name="Scorecard Test",
        target_engine="Local (gemma4-26b)",
        backend_desc="Apple Silicon Metal GPU",
        ttfb_ms=120.5,
        total_seconds=1.2,
        prompt_tokens=25,
        output_tokens=75,
        tok_per_sec=62.5,
        cost_usd=0.0,
        timestamp=1700000000.0,
    )

    table = runner.format_scorecard_table([dummy_result])
    assert "Scorecard Test" in table
    assert "gemma4-26b" in table
    assert "120.5 ms" in table
    assert "62.5 tok/s" in table
    assert "$0.00" in table


def test_measure_ingress_latencies(tmp_path: Path):
    from voicefi.local.benchmark import measure_unified_ram_ingress, measure_wan_ingress

    sample_file = tmp_path / "sample.py"
    sample_file.write_text("print('hello world')\n" * 100)

    ram_ms, bytes_read = measure_unified_ram_ingress(sample_file)
    assert ram_ms >= 0.001
    assert bytes_read == sample_file.stat().st_size

    wan_ms = measure_wan_ingress(payload_bytes=bytes_read)
    assert wan_ms >= 15.0
    # Unified RAM ingress should be dramatically faster than WAN ingress
    assert ram_ms < wan_ms


def test_tot_comparison_runner(tmp_path: Path, monkeypatch):
    from voicefi.local.benchmark import LocalBenchmarkRunner, ToTComparisonResult

    # Mock telemetry to avoid network calls during test
    recorded_events = []

    def mock_record_event(name, properties=None):
        recorded_events.append((name, properties))

    monkeypatch.setattr("voicefi.telemetry.record_event", mock_record_event)

    sample_file = tmp_path / "target_code.py"
    sample_file.write_text(
        "def compute_hash(data):\n"
        "    import hashlib\n"
        "    return hashlib.sha256(data.encode()).hexdigest()\n"
        "\n"
        "def main():\n"
        "    for i in range(100):\n"
        "        compute_hash(str(i))\n"
    )

    tot_db = tmp_path / "tot_history.json"
    runner = LocalBenchmarkRunner(tot_db_path=tot_db)

    res = asyncio.run(
        runner.run_tot_comparison(
            target_path=sample_file,
            prompt="Audit for performance bottlenecks",
            turns=3,
            cloud_provider="gemini",
            live_cloud=False,
        )
    )

    assert isinstance(res, ToTComparisonResult)
    assert res.target_path == str(sample_file)
    assert res.turns_count == 3
    assert len(res.local_turns) == 3
    assert len(res.cloud_turns) == 3

    # Ingress: unified RAM vs WAN
    assert res.local_ingress_ms < res.cloud_ingress_ms

    # Context bloat and tokens saved
    assert res.cloud_prompt_tokens > res.local_prompt_tokens
    assert res.tokens_saved > 0
    assert res.tokens_saved_pct > 0.0
    assert res.bloat_factor_cloud_vs_local >= 1.0

    # End-to-end Time on Task
    assert res.local_total_seconds > 0.0
    assert res.cloud_total_seconds > 0.0
    assert res.tot_speedup_ratio > 0.0

    # Cost and bandwidth
    assert res.local_cost_usd == 0.0
    assert res.cloud_cost_usd > 0.0
    assert res.cost_saved_usd == res.cloud_cost_usd
    assert res.local_bandwidth_bytes == 0
    assert res.cloud_bandwidth_bytes > 0
    assert res.bandwidth_saved_pct == 100.0

    # Persistent storage
    history = runner.load_tot_history()
    assert len(history) == 1
    assert history[0]["task_name"] == res.task_name

    # Scorecard rendering
    scorecard = runner.format_comparison_scorecard(res)
    assert "⚡ VoiceFi Time on Task (ToT) Benchmark" in scorecard
    assert "Ingress / WAN Transport" in scorecard
    assert "Time to First Byte (TTFT)" in scorecard
    assert "Context Bloat (Final Prompt)" in scorecard
    assert "Total End-to-End ToT" in scorecard
    assert "WAN Bandwidth Consumed" in scorecard
    assert "100% Saved" in scorecard
    assert "🏆 Summary:" in scorecard

    # History table formatting
    history_table = runner.format_tot_history_table([res])
    assert "target_code.py" in history_table
    assert f"{res.tot_speedup_ratio}x" in history_table

    # Telemetry dispatch
    assert len(recorded_events) >= 1
    assert recorded_events[0][0] == "tot_benchmark_comparison"
    assert recorded_events[0][1]["target_path"] == "target_code.py"

