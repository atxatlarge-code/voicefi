"""
Unit tests for on-device spoken turn distillation and telegraphic mode.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

from voicefi.config import VoiceFiConfig
from voicefi.local.engine import LocalModelEngine
from voicefi.local.benchmark import BenchmarkResult, record_inference_metrics, LocalBenchmarkRunner
from voicefi.integrations.gemini_ai import GeminiIntelligenceEngine
from voicefi.integrations.antigravity import clean_markdown_for_speech


def test_record_inference_metrics(tmp_path: Path):
    db_file = tmp_path / "benchmarks_test.json"
    res = record_inference_metrics(
        test_name="Spoken Turn Distillation",
        target_engine="Local (gemma4-2b)",
        backend_desc="Apple Silicon Metal GPU (Metal 4)",
        ttfb_ms=85.2,
        total_seconds=0.45,
        prompt_tokens=40,
        output_tokens=18,
        tok_per_sec=40.0,
        cost_usd=0.0,
        notes="18 words spoken soundbite",
        db_path=db_file,
    )

    assert isinstance(res, BenchmarkResult)
    assert res.test_name == "Spoken Turn Distillation"
    assert res.ttfb_ms == 85.2
    assert res.cost_usd == 0.0

    runner = LocalBenchmarkRunner(db_path=db_file)
    history = runner.load_history()
    assert len(history) == 1
    assert history[0]["test_name"] == "Spoken Turn Distillation"


def test_distill_turn_mocked():
    engine = LocalModelEngine()

    sample_output = (
        "### Test Results\n"
        "Ran 14 tests across auth and token modules.\n"
        "```python\nassert token.valid is True\n```\n"
        "All 14 tests passed successfully in 0.42 seconds. Ready for pull request review?"
    )

    with patch.object(engine, "chat_stream") as mock_stream:
        async def _mock_tokens(*args, **kwargs):
            yield "All 14 "
            yield "tests passed. "
            yield "Ready for review?"

        mock_stream.side_effect = _mock_tokens

        clean_text, bench = asyncio.run(
            engine.distill_turn(agent_output=sample_output, max_words=20, measure=False)
        )
        assert "All 14 tests passed." in clean_text
        assert "Ready for review?" in clean_text
        assert "```" not in clean_text


def test_telegraphic_distillation_mocked():
    engine = LocalModelEngine()

    sample_output = (
        "I have completed refactoring the database connection pool. "
        "Max connections set to 50. All health checks are green."
    )

    with patch.object(engine, "chat_stream") as mock_stream:
        async def _mock_tokens(*args, **kwargs):
            yield "Refactored DB pool: "
            yield "50 max conns, "
            yield "health checks green."

        mock_stream.side_effect = _mock_tokens

        clean_text, bench = asyncio.run(
            engine.distill_turn(agent_output=sample_output, max_words=15, telegraphic=True, measure=False)
        )
        assert "Refactored DB pool" in clean_text
        assert "50 max conns" in clean_text


def test_gemini_intelligence_engine_local_routing():
    cfg = VoiceFiConfig()
    cfg.local_model.distill_spoken_turns = True
    cfg.local_model.telegraphic_mode = True

    intel = GeminiIntelligenceEngine(config=cfg)

    with patch("voicefi.local.engine.LocalModelEngine.distill_turn") as mock_distill:
        async def _fake_distill(*args, **kwargs):
            return "Refactored auth middleware. All 14 tests pass.", None

        mock_distill.side_effect = _fake_distill

        with patch("voicefi.local.engine.LocalModelEngine.is_installed", True):
            with patch("voicefi.local.engine.LocalModelEngine.model_exists", True):
                res = intel.distill_spoken_soundbite("Long markdown output from agent...")
                assert res is not None
                assert "Refactored auth middleware" in res
