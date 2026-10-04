"""
voicefi/local/supervisor.py
Apple Silicon Thermal & Hardware Resource Supervisor.

Monitors macOS thermal pressure, Unified Memory utilization, and CPU load.
Provides sleep-safe circuit breakers, model-aware memory gates, and backoff
throttlers for on-device local LLM inference (Ollama, LiteRT, MLX) and audio synthesis.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

logger = logging.getLogger("voicefi.local.supervisor")

# Calibrated Unified Memory Headroom Requirements for Apple Silicon (Weights + KV Cache)
DEFAULT_MODEL_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    # Frontier 70B Tier: 42.5 GB weights + 3.5 GB KV cache
    "llama3.3:70b": {
        "min_free_ram_gb": 46.0,
        "max_load_avg": 8.0,
        "disallow_swap": True,
        "recommended_fallback": "gemma4-26b",
    },
    "qwen2.5-coder:32b": {
        "min_free_ram_gb": 22.0,
        "max_load_avg": 10.0,
        "disallow_swap": True,
        "recommended_fallback": "qwen2.5-coder:7b",
    },
    # Mid-Tier Coders (26B - 32B)
    "gemma4-26b": {
        "min_free_ram_gb": 18.0,
        "max_load_avg": 10.0,
        "disallow_swap": True,
        "recommended_fallback": "gemma2:2b",
    },
    # Compact Coders (7B - 8B)
    "qwen2.5-coder:7b": {
        "min_free_ram_gb": 6.5,
        "max_load_avg": 12.0,
        "disallow_swap": False,
        "recommended_fallback": "qwen2.5-coder:1.5b",
    },
    "dolphin-llama3:latest": {
        "min_free_ram_gb": 6.5,
        "max_load_avg": 12.0,
        "disallow_swap": False,
        "recommended_fallback": "gemma2:2b",
    },
    # Small Scouts & Intent Distillers (0.8B - 2.6B)
    "gemma2:2b": {
        "min_free_ram_gb": 2.5,
        "max_load_avg": 14.0,
        "disallow_swap": False,
        "recommended_fallback": None,
    },
    "gemma4-2b": {
        "min_free_ram_gb": 2.5,
        "max_load_avg": 14.0,
        "disallow_swap": False,
        "recommended_fallback": None,
    },
    "qwen2.5-coder:1.5b": {
        "min_free_ram_gb": 2.0,
        "max_load_avg": 14.0,
        "disallow_swap": False,
        "recommended_fallback": None,
    },
    "llama3.2:1b": {
        "min_free_ram_gb": 1.8,
        "max_load_avg": 14.0,
        "disallow_swap": False,
        "recommended_fallback": None,
    },
    "tev1:0.8b": {
        "min_free_ram_gb": 1.2,
        "max_load_avg": 14.0,
        "disallow_swap": False,
        "recommended_fallback": None,
    },
}


@dataclass
class HardwareTelemetry:
    system: str
    thermal_state: str  # NORMAL, FAIR, SERIOUS, CRITICAL, UNKNOWN
    thermal_raw: str
    free_ram_gb: float
    total_ram_gb: float
    ram_percent: float
    load_avg_1m: float
    is_safe: bool
    swap_used_gb: float = 0.0
    throttle_reason: Optional[str] = None


class ResourceGateError(RuntimeError):
    """Raised when hardware or memory resources are insufficient to safely load a model."""

    def __init__(self, message: str, alert_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.alert_data = alert_data or {}
        self.model_name = self.alert_data.get("model", "unknown")


class ThermalSupervisor:
    """
    On-device hardware guardrail supervisor for Apple Silicon / local compute.
    Prevents thermal throttling, memory exhaustion, and macOS swap thrashing.
    """

    def __init__(
        self,
        min_free_ram_gb: float = 4.0,
        max_load_avg: float = 12.0,
        pause_on_serious: bool = True,
    ):
        self.min_free_ram_gb = min_free_ram_gb
        self.max_load_avg = max_load_avg
        self.pause_on_serious = pause_on_serious
        self.is_macos = platform.system() == "Darwin"

    def get_thermal_state_macos(self) -> Tuple[str, str]:
        """Query macOS thermal state using pmset -g therm."""
        if not self.is_macos:
            return ("NORMAL", "Non-macOS platform")

        try:
            res = subprocess.run(
                ["pmset", "-g", "therm"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            raw = res.stdout.strip()
            raw_lower = raw.lower()
            if "no thermal warning" in raw_lower:
                return ("NORMAL", raw)
            elif "critical" in raw_lower:
                return ("CRITICAL", raw)
            elif "serious" in raw_lower or "heavy" in raw_lower:
                return ("SERIOUS", raw)
            elif "fair" in raw_lower or "moderate" in raw_lower:
                return ("FAIR", raw)
            elif "speed_limit" in raw_lower:
                if "speed_limit = 100" in raw_lower:
                    return ("NORMAL", raw)
                return ("FAIR", raw)
            return ("NORMAL", raw)
        except Exception as e:
            logger.debug(f"Failed to query pmset -g therm: {e}")
            return ("UNKNOWN", str(e))

    def get_swap_usage_macos(self) -> Tuple[float, float]:
        """Query macOS swap usage (used_gb, total_gb) via sysctl vm.swapusage."""
        if not self.is_macos:
            return (0.0, 0.0)
        try:
            res = subprocess.run(
                ["sysctl", "vm.swapusage"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            raw = res.stdout.strip()
            m_total = re.search(r"total\s*=\s*([\d\.]+)M", raw)
            m_used = re.search(r"used\s*=\s*([\d\.]+)M", raw)
            used_gb = round(float(m_used.group(1)) / 1024.0, 2) if m_used else 0.0
            total_gb = round(float(m_total.group(1)) / 1024.0, 2) if m_total else 0.0
            return (used_gb, total_gb)
        except Exception as e:
            logger.debug(f"Failed to read vm.swapusage: {e}")
            return (0.0, 0.0)

    def get_telemetry(self) -> HardwareTelemetry:
        """Collect current system telemetry across thermals, memory, swap, and load."""
        thermal_state, thermal_raw = self.get_thermal_state_macos()

        free_ram_gb = 0.0
        total_ram_gb = 0.0
        ram_percent = 0.0

        if PSUTIL_AVAILABLE:
            try:
                mem = psutil.virtual_memory()
                free_ram_gb = round(mem.available / (1024**3), 2)
                total_ram_gb = round(mem.total / (1024**3), 2)
                ram_percent = mem.percent
            except Exception as e:
                logger.debug(f"psutil memory read error: {e}")

        swap_used_gb, _ = self.get_swap_usage_macos()

        # Load average (1 min)
        load_1m = 0.0
        try:
            load_1m = round(os.getloadavg()[0], 2)
        except Exception:
            pass

        # Evaluate safety
        is_safe = True
        reason = None

        if thermal_state in ("SERIOUS", "CRITICAL") and self.pause_on_serious:
            is_safe = False
            reason = f"macOS thermal state is {thermal_state} ({thermal_raw})"
        elif free_ram_gb > 0 and free_ram_gb < self.min_free_ram_gb:
            is_safe = False
            reason = (
                f"Free unified RAM ({free_ram_gb} GB) below threshold ({self.min_free_ram_gb} GB)"
            )
        elif load_1m > self.max_load_avg:
            is_safe = False
            reason = f"Load average ({load_1m}) exceeds ceiling ({self.max_load_avg})"

        return HardwareTelemetry(
            system=platform.system(),
            thermal_state=thermal_state,
            thermal_raw=thermal_raw,
            free_ram_gb=free_ram_gb,
            total_ram_gb=total_ram_gb,
            ram_percent=ram_percent,
            load_avg_1m=load_1m,
            is_safe=is_safe,
            swap_used_gb=swap_used_gb,
            throttle_reason=reason,
        )

    def is_safe_to_run(self) -> bool:
        """Instant boolean check if safe to proceed with compute."""
        return self.get_telemetry().is_safe

    def get_model_requirement(self, model_name: str) -> Dict[str, Any]:
        """Resolve hardware headroom requirement for a specific model name."""
        key = (model_name or "").lower().strip()
        if key in DEFAULT_MODEL_REQUIREMENTS:
            return dict(DEFAULT_MODEL_REQUIREMENTS[key])

        # Heuristic resolution based on parameter tier in model string
        if any(token in key for token in ("70b", "72b")):
            return {
                "min_free_ram_gb": 46.0,
                "max_load_avg": 8.0,
                "disallow_swap": True,
                "recommended_fallback": "gemma4-26b",
            }
        elif any(token in key for token in ("32b", "34b", "27b", "26b")):
            return {
                "min_free_ram_gb": 18.0,
                "max_load_avg": 10.0,
                "disallow_swap": True,
                "recommended_fallback": "gemma2:2b",
            }
        elif any(token in key for token in ("14b", "13b", "12b")):
            return {
                "min_free_ram_gb": 11.0,
                "max_load_avg": 12.0,
                "disallow_swap": False,
                "recommended_fallback": "qwen2.5-coder:7b",
            }
        elif any(token in key for token in ("7b", "8b", "9b")):
            return {
                "min_free_ram_gb": 6.5,
                "max_load_avg": 12.0,
                "disallow_swap": False,
                "recommended_fallback": "qwen2.5-coder:1.5b",
            }
        elif any(token in key for token in ("2b", "3b", "1.5b", "1b", "0.8b")):
            return {
                "min_free_ram_gb": 2.5,
                "max_load_avg": 14.0,
                "disallow_swap": False,
                "recommended_fallback": None,
            }

        return {
            "min_free_ram_gb": self.min_free_ram_gb,
            "max_load_avg": self.max_load_avg,
            "disallow_swap": False,
            "recommended_fallback": None,
        }

    def can_load_model(
        self,
        model_name: str,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Evaluate if system has sufficient hardware and unified RAM headroom to load a model.
        Returns: (can_load, reason_or_status, alert_options_dict)
        If can_load is False, alert_options_dict contains structured user choice options:
        {
            "model": model_name,
            "required_ram_gb": req["min_free_ram_gb"],
            "available_ram_gb": telem.free_ram_gb,
            "swap_used_gb": telem.swap_used_gb,
            "fallback_model": req.get("recommended_fallback"),
            "options": [
                {"id": "cloud", "label": "Route to Cloud Frontier (Antigravity/Gemini)"},
                {"id": "fallback", "label": f"Use Mid-Tier Local Model ({fallback})"},
                {"id": "free_ram", "label": "Free RAM and Retry"}
            ]
        }
        """
        telem = self.get_telemetry()
        req = self.get_model_requirement(model_name)
        required_ram = req["min_free_ram_gb"]
        fallback = req.get("recommended_fallback") or "gemma2:2b"

        # Check 1: Thermal Pressure Guard
        if telem.thermal_state in ("SERIOUS", "CRITICAL") and self.pause_on_serious:
            reason = (
                f"Blocked {model_name} spin-up: macOS thermal state is {telem.thermal_state}. "
                "Pausing to allow hardware cooling."
            )
            alert = {
                "model": model_name,
                "cause": "thermal",
                "thermal_state": telem.thermal_state,
                "required_ram_gb": required_ram,
                "available_ram_gb": telem.free_ram_gb,
                "swap_used_gb": telem.swap_used_gb,
                "fallback_model": fallback,
                "options": [
                    {"id": "cloud", "label": "Route to Cloud Frontier (Antigravity/Gemini)"},
                    {"id": "wait", "label": "Wait for hardware to cool down"},
                ],
            }
            return (False, reason, alert)

        # Check 2: Physical Unified Memory Headroom
        if telem.free_ram_gb < required_ram:
            reason = (
                f"Blocked {model_name} spin-up: Requires {required_ram:.1f} GB free unified RAM, "
                f"but only {telem.free_ram_gb:.1f} GB available (Swap in use: {telem.swap_used_gb:.1f} GB). "
                "Refusing load to prevent macOS swap thrashing."
            )
            alert = {
                "model": model_name,
                "cause": "insufficient_ram",
                "required_ram_gb": required_ram,
                "available_ram_gb": telem.free_ram_gb,
                "swap_used_gb": telem.swap_used_gb,
                "fallback_model": fallback,
                "options": [
                    {"id": "cloud", "label": "Route to Cloud Frontier (Antigravity/Gemini)"},
                    {"id": "fallback", "label": f"Use Mid-Tier Local Model ({fallback})"},
                    {"id": "free_ram", "label": "Quit background apps to free RAM and retry"},
                ],
            }
            return (False, reason, alert)

        # Check 3: Active Swap Restriction for Heavy Frontier Models
        if req.get("disallow_swap") and telem.swap_used_gb > 8.0:
            reason = (
                f"Blocked {model_name} spin-up: Active disk swap ({telem.swap_used_gb:.1f} GB) "
                "indicates high background memory pressure. Refusing frontier 70B load."
            )
            alert = {
                "model": model_name,
                "cause": "high_swap_pressure",
                "required_ram_gb": required_ram,
                "available_ram_gb": telem.free_ram_gb,
                "swap_used_gb": telem.swap_used_gb,
                "fallback_model": fallback,
                "options": [
                    {"id": "cloud", "label": "Route to Cloud Frontier (Antigravity/Gemini)"},
                    {"id": "fallback", "label": f"Use Mid-Tier Local Model ({fallback})"},
                    {"id": "free_ram", "label": "Purge memory/swap and retry"},
                ],
            }
            return (False, reason, alert)

        # Check 4: Host Load Average
        if telem.load_avg_1m > req["max_load_avg"]:
            reason = (
                f"Blocked {model_name} spin-up: 1m CPU load ({telem.load_avg_1m}) "
                f"exceeds ceiling ({req['max_load_avg']})."
            )
            alert = {
                "model": model_name,
                "cause": "high_cpu_load",
                "load_avg_1m": telem.load_avg_1m,
                "required_ram_gb": required_ram,
                "available_ram_gb": telem.free_ram_gb,
                "swap_used_gb": telem.swap_used_gb,
                "fallback_model": fallback,
                "options": [
                    {"id": "cloud", "label": "Route to Cloud Frontier (Antigravity/Gemini)"},
                    {"id": "wait", "label": "Wait for CPU load to settle"},
                ],
            }
            return (False, reason, alert)

        return (True, f"Nominal: {model_name} approved for on-device load.", None)

    def assert_can_load(self, model_name: str) -> None:
        """
        Assert that a model can be safely loaded.
        Raises ResourceGateError if hardware headroom or memory is insufficient.
        """
        approved, reason, alert = self.can_load_model(model_name)
        if not approved:
            raise ResourceGateError(reason, alert)

    def format_resource_alert(self, alert_data: Dict[str, Any]) -> str:
        """Format a human-readable developer alert with actionable choices."""
        model = alert_data.get("model", "Model")
        req_ram = alert_data.get("required_ram_gb", 0.0)
        avail_ram = alert_data.get("available_ram_gb", 0.0)
        swap_gb = alert_data.get("swap_used_gb", 0.0)
        fallback = alert_data.get("fallback_model", "gemma4-26b")

        lines = [
            f"\n⚠️  [VoiceFi ResourceGate] Memory Protection Alert for `{model}`",
            "=" * 65,
            f"  • Required Headroom:  {req_ram:.1f} GB Free Unified RAM",
            f"  • Currently Available:{avail_ram:.1f} GB Free Unified RAM",
            f"  • Active Disk Swap:   {swap_gb:.1f} GB in use",
            "-" * 65,
            "  Action Options:",
            f"  [1] ☁️  Route to Cloud Frontier (Antigravity/Gemini) - Zero local RAM",
            f"  [2] 💻 Use Mid-Tier Local Model ({fallback}) - Fits safely in RAM",
            f"  [3] 🛑 Free RAM (quit background apps/VMs) and Retry",
            "=" * 65,
        ]
        return "\n".join(lines)

    def wait_if_throttled(
        self,
        poll_interval: float = 3.0,
        max_wait: float = 60.0,
        on_pause_cb: Optional[Callable[[HardwareTelemetry], None]] = None,
    ) -> bool:
        """
        Block and sleep while thermals or memory are unsafe.
        Returns True if recovered and safe, False if timed out waiting.
        """
        start_time = time.time()
        while time.time() - start_time < max_wait:
            telem = self.get_telemetry()
            if telem.is_safe:
                return True

            logger.warning(
                f"[ThermalSupervisor] Throttling compute: {telem.throttle_reason}. Pausing {poll_interval}s..."
            )
            if on_pause_cb:
                try:
                    on_pause_cb(telem)
                except Exception:
                    pass

            time.sleep(poll_interval)

        return False

    def guarded(self, min_free_ram_gb: Optional[float] = None) -> Callable:
        """Decorator to wrap any local inference function with automatic backoff."""

        def decorator(fn: Callable) -> Callable:
            @wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                saved_min = self.min_free_ram_gb
                if min_free_ram_gb is not None:
                    self.min_free_ram_gb = min_free_ram_gb
                try:
                    self.wait_if_throttled()
                    return fn(*args, **kwargs)
                finally:
                    self.min_free_ram_gb = saved_min

            return wrapper

        return decorator


# Singleton instance
default_supervisor = ThermalSupervisor()


if __name__ == "__main__":
    telem = default_supervisor.get_telemetry()
    print("=== Apple Silicon Hardware Telemetry ===")
    print(f"System:         {telem.system}")
    print(f"Thermal State:  {telem.thermal_state}")
    print(f"Thermal Raw:    {telem.thermal_raw}")
    print(
        f"Memory:         {telem.free_ram_gb} GB free / {telem.total_ram_gb} GB total ({telem.ram_percent}% used)"
    )
    print(f"Active Swap:    {telem.swap_used_gb} GB")
    print(f"1m Load Avg:    {telem.load_avg_1m}")
    print(f"Safe to Run:    {telem.is_safe}")
    if telem.throttle_reason:
        print(f"Throttle Cause: {telem.throttle_reason}")

    print("\n=== Model Resource Headroom Gate Check ===")
    for model in ("gemma2:2b", "gemma4-26b", "llama3.3:70b"):
        approved, reason, alert = default_supervisor.can_load_model(model)
        status = "✅ APPROVED" if approved else "⛔ BLOCKED"
        print(f"{model:<16} -> {status}: {reason}")
        if alert:
            print(default_supervisor.format_resource_alert(alert))
