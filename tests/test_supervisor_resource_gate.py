"""
Unit tests for VoiceFi Hardware ResourceGate and Air-Gap Safety Supervisor.
Verifies model-aware memory gating, swap pressure thresholds, thermal circuit breakers,
and structured developer alert generation to prevent macOS swap thrashing.
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from voicefi.local.supervisor import (
    ThermalSupervisor,
    HardwareTelemetry,
    ResourceGateError,
    default_supervisor,
)
from voicefi.local.implementer import ReconImplementer
from voicefi.local.agent_loop import LocalAutonomousLoop
from voicefi.local.engine import LocalModelEngine


def make_mock_telemetry(
    free_ram_gb: float = 48.0,
    swap_used_gb: float = 1.0,
    thermal_state: str = "NORMAL",
    load_avg_1m: float = 2.5,
    is_safe: bool = True,
) -> HardwareTelemetry:
    """Helper to synthesize hardware telemetry states."""
    return HardwareTelemetry(
        system="Darwin",
        thermal_state=thermal_state,
        thermal_raw="mock_raw",
        free_ram_gb=free_ram_gb,
        total_ram_gb=64.0,
        ram_percent=round(((64.0 - free_ram_gb) / 64.0) * 100, 1),
        load_avg_1m=load_avg_1m,
        is_safe=is_safe,
        swap_used_gb=swap_used_gb,
        throttle_reason=None,
    )


def test_supervisor_nominal_gemma2b():
    """Verify small scout/intent models pass comfortably under modest resources."""
    sup = ThermalSupervisor()
    mock_telem = make_mock_telemetry(free_ram_gb=8.0, swap_used_gb=0.5)

    with patch.object(sup, "get_telemetry", return_value=mock_telem):
        approved, reason, alert = sup.can_load_model("gemma2:2b")
        assert approved is True
        assert alert is None
        assert "approved" in reason

        # assert_can_load should not raise
        sup.assert_can_load("gemma2:2b")


def test_supervisor_70b_insufficient_ram_blocks_and_alerts():
    """Verify 70B model is blocked when free unified RAM is under 46.0 GB."""
    sup = ThermalSupervisor()
    # 38.0 GB is plenty for general tasks, but will destroy a Mac trying to run 42.5 GB weights
    mock_telem = make_mock_telemetry(free_ram_gb=38.0, swap_used_gb=2.0)

    with patch.object(sup, "get_telemetry", return_value=mock_telem):
        approved, reason, alert = sup.can_load_model("llama3.3:70b")
        assert approved is False
        assert alert is not None
        assert alert["model"] == "llama3.3:70b"
        assert alert["cause"] == "insufficient_ram"
        assert alert["required_ram_gb"] == 46.0
        assert alert["available_ram_gb"] == 38.0
        assert alert["fallback_model"] == "gemma4-26b"

        # Check action options
        option_ids = [opt["id"] for opt in alert["options"]]
        assert "cloud" in option_ids
        assert "fallback" in option_ids
        assert "free_ram" in option_ids

        # assert_can_load must raise ResourceGateError
        with pytest.raises(ResourceGateError) as exc_info:
            sup.assert_can_load("llama3.3:70b")
        assert exc_info.value.model_name == "llama3.3:70b"
        assert exc_info.value.alert_data["cause"] == "insufficient_ram"


def test_supervisor_70b_sufficient_ram_approves():
    """Verify 70B model is approved when RAM headroom >= 46.0 GB and swap is low."""
    sup = ThermalSupervisor()
    mock_telem = make_mock_telemetry(free_ram_gb=50.0, swap_used_gb=1.2)

    with patch.object(sup, "get_telemetry", return_value=mock_telem):
        approved, reason, alert = sup.can_load_model("llama3.3:70b")
        assert approved is True
        assert alert is None
        assert "approved" in reason
        sup.assert_can_load("llama3.3:70b")


def test_supervisor_70b_blocked_by_active_swap_pressure():
    """Verify 70B model is blocked if active swap > 8.0 GB even if free RAM seems high."""
    sup = ThermalSupervisor()
    # High swap indicates memory is compressed/paged to SSD; spinning up 70B would cause thrash death
    mock_telem = make_mock_telemetry(free_ram_gb=48.0, swap_used_gb=9.5)

    with patch.object(sup, "get_telemetry", return_value=mock_telem):
        approved, reason, alert = sup.can_load_model("llama3.3:70b")
        assert approved is False
        assert alert is not None
        assert alert["cause"] == "high_swap_pressure"
        assert "swap" in reason.lower()

        with pytest.raises(ResourceGateError):
            sup.assert_can_load("llama3.3:70b")


def test_supervisor_thermal_pressure_blocks():
    """Verify thermal warning blocks heavy inference."""
    sup = ThermalSupervisor()
    mock_telem = make_mock_telemetry(free_ram_gb=52.0, thermal_state="CRITICAL")

    with patch.object(sup, "get_telemetry", return_value=mock_telem):
        approved, reason, alert = sup.can_load_model("llama3.3:70b")
        assert approved is False
        assert alert["cause"] == "thermal"
        assert alert["thermal_state"] == "CRITICAL"


def test_format_resource_alert():
    """Verify formatted alert box is clean, readable, and includes options."""
    sup = ThermalSupervisor()
    alert_dict = {
        "model": "llama3.3:70b",
        "required_ram_gb": 46.0,
        "available_ram_gb": 41.5,
        "swap_used_gb": 6.8,
        "fallback_model": "gemma4-26b",
    }
    rendered = sup.format_resource_alert(alert_dict)
    assert "[VoiceFi ResourceGate] Memory Protection Alert for `llama3.3:70b`" in rendered
    assert "46.0 GB Free Unified RAM" in rendered
    assert "41.5 GB Free Unified RAM" in rendered
    assert "Route to Cloud Frontier" in rendered
    assert "gemma4-26b" in rendered


@pytest.mark.anyio
async def test_recon_implementer_resource_gate_integration(tmp_path):
    """Verify ReconImplementer halts cleanly if coder model lacks hardware headroom."""
    fake_file = tmp_path / "test.py"
    fake_file.write_text("print('hello')", encoding="utf-8")

    mock_telem = make_mock_telemetry(free_ram_gb=30.0, swap_used_gb=2.0)

    with patch.object(default_supervisor, "get_telemetry", return_value=mock_telem):
        implementer = ReconImplementer(model_scout="gemma4-2b", model_coder="llama3.3:70b")
        res = await implementer.implement(fake_file, instruction="Add greeting")

        assert res.applied is False
        assert "ResourceGate Blocked" in res.error
        assert "llama3.3:70b" in res.error
        assert "46.0 GB" in res.error


@pytest.mark.anyio
async def test_agent_loop_resource_gate_integration():
    """Verify LocalAutonomousLoop halts and outputs alert if model exceeds headroom."""
    mock_telem = make_mock_telemetry(free_ram_gb=25.0, swap_used_gb=3.0)

    with patch.object(default_supervisor, "get_telemetry", return_value=mock_telem):
        loop = LocalAutonomousLoop(model_name="llama3.3:70b", max_turns=3)
        res = await loop.execute(goal="Refactor auth token parser")

        assert res.completed is False
        assert "ResourceGate Blocked" in res.summary
        assert "llama3.3:70b" in res.summary
        assert len(res.steps) == 0


@pytest.mark.anyio
async def test_local_model_engine_assert_can_load_integration():
    """Verify LocalModelEngine raises ResourceGateError if headroom is inadequate."""
    mock_telem = make_mock_telemetry(free_ram_gb=20.0, swap_used_gb=1.0)

    with patch.object(default_supervisor, "get_telemetry", return_value=mock_telem):
        engine = LocalModelEngine(model_name="llama3.3:70b")
        with pytest.raises(ResourceGateError) as exc_info:
            await engine.chat_text(prompt="Hi")

        assert "llama3.3:70b" in str(exc_info.value)
