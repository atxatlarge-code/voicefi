"""
voicefi/local/router.py
Dynamic Hardware-Aware Model Router for Hybrid Cloud + Apple Silicon Orchestration.

Automatically cascades across model tiers (70B -> 32B/26B -> 7B -> 2B/1.5B -> Cloud Frontier)
based on real-time Unified Memory headroom, active disk swap, CPU load, and thermal pressure
monitored by ThermalSupervisor, combined with installed local Ollama & LiteRT model availability.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from voicefi.local.engine import list_imported_models
from voicefi.local.supervisor import HardwareTelemetry, ThermalSupervisor, default_supervisor

logger = logging.getLogger("voicefi.local.router")

# Ordered cascade hierarchy from heaviest local frontier down to cloud fallback
CASCADE_HIERARCHY: List[str] = [
    "llama3.3:70b",
    "qwen2.5-coder:32b",
    "gemma4-26b",
    "nimble:latest",
    "qwen2.5-coder:7b",
    "dolphin-llama3:latest",
    "tev1:latest",
    "voicefi-coder-mlx",
    "voicefi-coder:1.5b",
    "qwen2.5-coder:1.5b",
    "gemma2:2b",
    "gemma4-2b",
    "tev1:0.8b",
    "embedding-gemma-2:740m",
    "embedding-gemma-2",
    "llama3.2:1b",
    "cloud:gemini-flash",
]

TASK_DEFAULT_PREFERENCES: Dict[str, List[str]] = {
    "tier0_reflex": [
        "tev1:0.8b",
        "voicefi-coder-mlx",
        "qwen2.5-coder:1.5b",
        "gemma4-2b",
    ],
    "embed": [
        "embedding-gemma-2:740m",
        "embedding-gemma-2",
    ],
    "frontier": [
        "gemma4-26b",
        "llama3.3:70b",
        "nimble:latest",
        "tev1:latest",
        "voicefi-coder-mlx",
        "voicefi-coder:1.5b",
        "qwen2.5-coder:1.5b",
        "gemma2:2b",
        "cloud:gemini-pro",
    ],
    "vision": [
        "gemma4-26b",
        "gemma2:2b",
        "cloud:gemini-flash",
    ],
    "coder": [
        "voicefi-coder-mlx",
        "voicefi-coder:1.5b",
        "qwen2.5-coder:1.5b",
        "tev1:latest",
        "nimble:latest",
        "gemma2:2b",
        "cloud:gemini-flash",
    ],
    "scout": [
        "voicefi-coder-mlx",
        "voicefi-coder:1.5b",
        "qwen2.5-coder:1.5b",
        "tev1:0.8b",
        "gemma2:2b",
        "tev1:latest",
        "llama3.2:1b",
        "cloud:gemini-flash-lite",
    ],
    "qa": [
        "voicefi-coder-mlx",
        "voicefi-coder:1.5b",
        "qwen2.5-coder:1.5b",
        "tev1:latest",
        "nimble:latest",
        "gemma2:2b",
        "cloud:gemini-flash",
    ],
    "creative": [
        "dolphin-llama3:latest",
        "nimble:latest",
        "tev1:latest",
        "gemma2:2b",
        "voicefi-coder-mlx",
        "voicefi-coder:1.5b",
        "cloud:gemini-flash",
    ],
}


def classify_model_tier(model_name: str) -> str:
    """Return a normalized tier label for a model identifier."""
    key = (model_name or "").lower().strip()
    if key.startswith("cloud:"):
        return "cloud_frontier"
    if "embed" in key:
        return "edge_tier0_embed"
    if "0.8b" in key or key == "tev1:0.8b":
        return "edge_tier0_reflex"
    if any(t in key for t in ("70b", "72b")):
        return "local_70b_frontier"
    if any(t in key for t in ("32b", "34b", "27b", "26b")):
        return "local_26b_32b_mid"
    if any(t in key for t in ("14b", "13b", "12b", "9b", "8b", "7b")) or "dolphin" in key or "nimble" in key:
        return "local_7b_9b_compact"
    if "tev1:latest" in key or "4b" in key:
        return "local_4b_reasoning"
    return "local_1b_2b_scout"


@dataclass
class RoutingDecision:
    task_type: str
    requested_model: str
    selected_model: str
    tier: str
    is_local: bool
    cascaded: bool
    cascaded_from: Optional[str]
    cascade_reason: Optional[str]
    thermal_state: str
    free_ram_gb: float
    total_ram_gb: float
    swap_used_gb: float
    load_avg_1m: float
    decision_latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HybridRouter:
    """
    Hardware-gated model router that bridges Local Apple Silicon (Ollama + LiteRT)
    and Cloud Frontier (Gemini Pro / Flash) with automatic fallback cascading.
    """

    def __init__(
        self,
        supervisor: Optional[ThermalSupervisor] = None,
        ollama_base_url: Optional[str] = None,
    ):
        self.supervisor = supervisor or default_supervisor
        self.ollama_base_url = ollama_base_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
        )
        self._installed_cache: Optional[List[str]] = None
        self._cache_ts: float = 0.0

    def get_installed_local_models(self, force_refresh: bool = False) -> List[str]:
        """Return list of locally available Ollama and LiteRT model names (cached for 15s)."""
        now = time.time()
        if not force_refresh and self._installed_cache is not None and (now - self._cache_ts) < 15.0:
            return list(self._installed_cache)

        models: List[str] = []
        # 1. Query Ollama /api/tags
        try:
            req = urllib.request.Request(f"{self.ollama_base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=1.2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for m in data.get("models", []):
                    name = m.get("name", "")
                    if name and name not in models:
                        models.append(name)
        except Exception as e:
            logger.debug(f"Ollama tags probe skipped: {e}")

        # 2. Query LiteRT models directory
        try:
            for m in list_imported_models():
                name = m.get("name", "")
                if name and name not in models:
                    models.append(name)
        except Exception as e:
            logger.debug(f"LiteRT models probe skipped: {e}")

        # 3. Check Direct-on-Metal MLX LoRA fused_model (.safetensors)
        mlx_fused = "/Users/jaketrigg/Projects/Local Models/distillation/fused_model/model.safetensors"
        if os.path.exists(mlx_fused) and "voicefi-coder-mlx" not in models:
            models.insert(0, "voicefi-coder-mlx")

        self._installed_cache = models
        self._cache_ts = now
        return list(models)

    def resolve_model(
        self,
        task_type: str = "scout",
        preferred_model: Optional[str] = None,
        require_installed: bool = True,
    ) -> RoutingDecision:
        """
        Select the optimal model for `task_type` given real-time Apple Silicon vital signs.
        Cascades down the hierarchy if the preferred model is blocked by ThermalSupervisor
        or not installed locally.
        """
        t0 = time.perf_counter()
        telem: HardwareTelemetry = self.supervisor.get_telemetry()
        installed = self.get_installed_local_models() if require_installed else []

        base_chain = list(
            TASK_DEFAULT_PREFERENCES.get(task_type.lower(), TASK_DEFAULT_PREFERENCES["scout"])
        )
        if preferred_model:
            clean_pref = preferred_model.replace("ollama/", "").strip()
            if clean_pref in base_chain:
                base_chain.remove(clean_pref)
            base_chain.insert(0, clean_pref)
            # Also ensure recommended fallback from supervisor is in chain
            req_info = self.supervisor.get_model_requirement(clean_pref)
            fb = req_info.get("recommended_fallback")
            if fb and fb not in base_chain:
                base_chain.insert(1, fb)

        requested = base_chain[0]
        first_failure_reason: Optional[str] = None

        for idx, candidate in enumerate(base_chain):
            if candidate.startswith("cloud:"):
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
                return RoutingDecision(
                    task_type=task_type,
                    requested_model=requested,
                    selected_model=candidate,
                    tier=classify_model_tier(candidate),
                    is_local=False,
                    cascaded=(idx > 0),
                    cascaded_from=requested if idx > 0 else None,
                    cascade_reason=first_failure_reason if idx > 0 else None,
                    thermal_state=telem.thermal_state,
                    free_ram_gb=telem.free_ram_gb,
                    total_ram_gb=telem.total_ram_gb,
                    swap_used_gb=telem.swap_used_gb,
                    load_avg_1m=telem.load_avg_1m,
                    decision_latency_ms=latency_ms,
                )

            # Check hardware headroom first
            approved, reason, _ = self.supervisor.can_load_model(candidate)
            if not approved:
                if first_failure_reason is None:
                    first_failure_reason = reason
                continue

            # Check local installation if required
            if require_installed and installed:
                is_present = any(
                    candidate == inst
                    or inst == f"{candidate}:latest"
                    or (":" not in candidate and inst.startswith(f"{candidate}:"))
                    for inst in installed
                )
                if not is_present:
                    if first_failure_reason is None:
                        first_failure_reason = (
                            f"Model `{candidate}` hardware-approved ({telem.free_ram_gb} GB free), "
                            f"but weights not currently loaded in local Ollama/LiteRT; cascaded to installed model."
                        )
                    continue

            # Resolved a valid local candidate
            selected = candidate
            if require_installed and installed and candidate not in installed:
                for inst in installed:
                    if inst == f"{candidate}:latest" or (
                        ":" not in candidate and inst.startswith(f"{candidate}:")
                    ):
                        selected = inst
                        break

            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            return RoutingDecision(
                task_type=task_type,
                requested_model=requested,
                selected_model=selected,
                tier=classify_model_tier(selected),
                is_local=True,
                cascaded=(selected != requested),
                cascaded_from=requested if selected != requested else None,
                cascade_reason=first_failure_reason if selected != requested else None,
                thermal_state=telem.thermal_state,
                free_ram_gb=telem.free_ram_gb,
                total_ram_gb=telem.total_ram_gb,
                swap_used_gb=telem.swap_used_gb,
                load_avg_1m=telem.load_avg_1m,
                decision_latency_ms=latency_ms,
            )

        # Ultimate fallback to Cloud Flash
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        return RoutingDecision(
            task_type=task_type,
            requested_model=requested,
            selected_model="cloud:gemini-flash",
            tier="cloud_frontier",
            is_local=False,
            cascaded=True,
            cascaded_from=requested,
            cascade_reason=first_failure_reason or "All local tiers unavailable",
            thermal_state=telem.thermal_state,
            free_ram_gb=telem.free_ram_gb,
            total_ram_gb=telem.total_ram_gb,
            swap_used_gb=telem.swap_used_gb,
            load_avg_1m=telem.load_avg_1m,
            decision_latency_ms=latency_ms,
        )


default_router = HybridRouter()
