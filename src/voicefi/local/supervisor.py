"""
voicefi/local/supervisor.py
Apple Silicon Thermal & Hardware Resource Supervisor.

Monitors macOS thermal pressure, Unified Memory utilization, and CPU load.
Provides sleep-safe circuit breakers and backoff throttlers for on-device
local LLM inference (Ollama, LiteRT, MLX) and audio synthesis engines.
"""

from __future__ import annotations

import logging
import os
import platform
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
    throttle_reason: Optional[str] = None


class ThermalSupervisor:
    """
    On-device hardware guardrail supervisor for Apple Silicon / local compute.
    Prevents thermal throttling, memory exhaustion, and fan spin during heavy batch runs.
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
            # Standard pmset output looks like:
            # Note: No thermal warning level has been reached
            # or: CPU_Speed_Limit = 100, etc.
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
                # If speed limit is < 100, throttling has occurred
                if "speed_limit = 100" in raw_lower:
                    return ("NORMAL", raw)
                return ("FAIR", raw)
            return ("NORMAL", raw)
        except Exception as e:
            logger.debug(f"Failed to query pmset -g therm: {e}")
            return ("UNKNOWN", str(e))

    def get_telemetry(self) -> HardwareTelemetry:
        """Collect current system telemetry across thermals, memory, and load."""
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
            throttle_reason=reason,
        )

    def is_safe_to_run(self) -> bool:
        """Instant boolean check if safe to proceed with compute."""
        return self.get_telemetry().is_safe

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
    import json

    telem = default_supervisor.get_telemetry()
    print("=== Apple Silicon Hardware Telemetry ===")
    print(f"System:         {telem.system}")
    print(f"Thermal State:  {telem.thermal_state}")
    print(f"Thermal Raw:    {telem.thermal_raw}")
    print(
        f"Memory:         {telem.free_ram_gb} GB free / {telem.total_ram_gb} GB total ({telem.ram_percent}% used)"
    )
    print(f"1m Load Avg:    {telem.load_avg_1m}")
    print(f"Safe to Run:    {telem.is_safe}")
    if telem.throttle_reason:
        print(f"Throttle Cause: {telem.throttle_reason}")
