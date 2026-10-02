"""
VoiceFi Local Model & Recon Scout Engine.
Leverages Google AI Edge's LiteRT and Google Antigravity SDK to execute
on-device models (Gemma 4) on Apple Silicon Metal GPUs for 100% private,
zero-cost recon, code auditing, and benchmark analysis.
"""

from voicefi.local.engine import LocalModelEngine, is_litert_available
from voicefi.local.scout import ReconScout, ScoutResult
from voicefi.local.implementer import ReconImplementer, ImplementResult
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
from voicefi.local.trace_parser import parse_traceback, ParsedTrace
from voicefi.local.symbols import LocalSymbolIndex, SymbolRecord
from voicefi.local.agent_loop import LocalAutonomousLoop, AutonomousLoopResult, LoopStep
from voicefi.local.supervisor import ThermalSupervisor, HardwareTelemetry, default_supervisor

__all__ = [
    "LocalModelEngine",
    "is_litert_available",
    "ReconScout",
    "ScoutResult",
    "ReconImplementer",
    "ImplementResult",
    "LocalBenchmarkRunner",
    "BenchmarkResult",
    "ToTComparisonResult",
    "TurnMetrics",
    "record_inference_metrics",
    "measure_unified_ram_ingress",
    "measure_wan_ingress",
    "LocalIntentRouter",
    "parse_traceback",
    "ParsedTrace",
    "LocalSymbolIndex",
    "SymbolRecord",
    "LocalAutonomousLoop",
    "AutonomousLoopResult",
    "LoopStep",
    "ThermalSupervisor",
    "HardwareTelemetry",
    "default_supervisor",
]
