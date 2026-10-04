"""
VoiceFi Local Model & Recon Scout Engine.
Leverages Google AI Edge's LiteRT and Google Antigravity SDK to execute
on-device models (Gemma 4) on Apple Silicon Metal GPUs for 100% private,
zero-cost recon, code auditing, and benchmark analysis.
"""

from typing import Any
import importlib

from voicefi.local.engine import LocalModelEngine, is_litert_available
from voicefi.local.supervisor import ThermalSupervisor, HardwareTelemetry, default_supervisor

_LAZY_IMPORTS = {
    "ReconScout": ("voicefi.local.scout", "ReconScout"),
    "ScoutResult": ("voicefi.local.scout", "ScoutResult"),
    "ReconImplementer": ("voicefi.local.implementer", "ReconImplementer"),
    "ImplementResult": ("voicefi.local.implementer", "ImplementResult"),
    "LocalBenchmarkRunner": ("voicefi.local.benchmark", "LocalBenchmarkRunner"),
    "BenchmarkResult": ("voicefi.local.benchmark", "BenchmarkResult"),
    "ToTComparisonResult": ("voicefi.local.benchmark", "ToTComparisonResult"),
    "TurnMetrics": ("voicefi.local.benchmark", "TurnMetrics"),
    "record_inference_metrics": ("voicefi.local.benchmark", "record_inference_metrics"),
    "measure_unified_ram_ingress": ("voicefi.local.benchmark", "measure_unified_ram_ingress"),
    "measure_wan_ingress": ("voicefi.local.benchmark", "measure_wan_ingress"),
    "LocalIntentRouter": ("voicefi.local.intent", "LocalIntentRouter"),
    "parse_traceback": ("voicefi.local.trace_parser", "parse_traceback"),
    "ParsedTrace": ("voicefi.local.trace_parser", "ParsedTrace"),
    "LocalSymbolIndex": ("voicefi.local.symbols", "LocalSymbolIndex"),
    "SymbolRecord": ("voicefi.local.symbols", "SymbolRecord"),
    "LocalAutonomousLoop": ("voicefi.local.agent_loop", "LocalAutonomousLoop"),
    "AutonomousLoopResult": ("voicefi.local.agent_loop", "AutonomousLoopResult"),
    "LoopStep": ("voicefi.local.agent_loop", "LoopStep"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_IMPORTS:
        mod_name, attr_name = _LAZY_IMPORTS[name]
        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

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
