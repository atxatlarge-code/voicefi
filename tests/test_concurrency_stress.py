"""
tests/test_concurrency_stress.py
Automated verification for the overnight stress harness and concurrency components.
"""

import asyncio
import tempfile
from pathlib import Path
import pytest

from scripts.overnight_stress import OvernightStressHarness, HardwareGuard


def test_hardware_guardrails():
    """Verify hardware circuit breaker checks return valid system metrics."""
    free_ram = HardwareGuard.get_free_ram_gb()
    assert free_ram > 0.0

    thermal = HardwareGuard.check_thermal_pressure()
    assert thermal in ("NORMAL", "SERIOUS", "CRITICAL")

    is_safe, reason = HardwareGuard.enforce_guardrails()
    assert isinstance(is_safe, bool)
    assert isinstance(reason, str)


def test_overnight_harness_single_cycle(tmp_path):
    """Verify all 4 tracks of the overnight harness execute cleanly."""
    async def _run():
        db_file = tmp_path / "test_stress.db"
        harness = OvernightStressHarness(
            db_path=db_file,
            max_hours=0.01,
            max_iterations=1,
            concurrency=1,
            dry_run=True,
        )

        try:
            # Track 1
            factory_res = await harness.run_factory_cycle(1)
            assert factory_res["processed"] >= 1
            assert factory_res["tokens_saved"] > 0

            # Track 2
            duplex_res = await harness.run_duplex_barge_in_cycle()
            assert duplex_res["barge_in_detected"] is True
            assert duplex_res["latency_ms"] < 200.0

            # Track 3
            lock_res = await harness.run_lock_resilience_cycle()
            assert lock_res["cycles"] > 0
            assert lock_res["failures"] == 0

            # Track 4
            mcp_res = await harness.run_mcp_probe()
            assert mcp_res["success"] is True
            assert mcp_res["tool_count"] > 0
        finally:
            harness.cleanup()

    asyncio.run(_run())
