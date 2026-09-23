"""
VoiceFi Local Model & Recon Scout Engine.
Leverages Google AI Edge's LiteRT and Google Antigravity SDK to execute
on-device models (Gemma 4) on Apple Silicon Metal GPUs for 100% private,
zero-cost recon, code auditing, and benchmark analysis.
"""

from voicefi.local.engine import LocalModelEngine, is_litert_available
from voicefi.local.scout import ReconScout, ScoutResult
from voicefi.local.benchmark import (
    LocalBenchmarkRunner,
    BenchmarkResult,
    ToTComparisonResult,
    TurnMetrics,
    record_inference_metrics,
    measure_unified_ram_ingress,
    measure_wan_ingress,
)
from voicefi.local.intent import LocalIntentRouter

__all__ = [
    "LocalModelEngine",
    "is_litert_available",
    "ReconScout",
    "ScoutResult",
    "LocalBenchmarkRunner",
    "BenchmarkResult",
    "ToTComparisonResult",
    "TurnMetrics",
    "record_inference_metrics",
    "measure_unified_ram_ingress",
    "measure_wan_ingress",
    "LocalIntentRouter",
]
