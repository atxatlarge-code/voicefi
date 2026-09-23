"""
Unit tests for VoiceFi LocalModelConfig and LocalModelEngine status.
"""

import pytest
from voicefi.config import VoiceFiConfig, LocalModelConfig, load_config
from voicefi.local.engine import LocalModelEngine, is_litert_available, detect_hardware_backend


def test_local_model_config_defaults():
    cfg = LocalModelConfig()
    assert cfg.enabled is True
    assert cfg.model_name == "gemma4-26b"
    assert "gemma4-26b" in cfg.model_path
    assert cfg.backend in ("gpu", "cpu", "npu")
    assert cfg.max_context_tokens == 65536
    assert cfg.enable_speculative_decoding is True
    # Opt-in flags must default to False
    assert cfg.distill_spoken_turns is False
    assert cfg.telegraphic_mode is False
    assert cfg.intent_routing is False
    assert cfg.airgapped_memos is False
    assert cfg.measure_latency is True


def test_voicefi_config_includes_local_model():
    cfg = VoiceFiConfig()
    assert hasattr(cfg, "local_model")
    assert isinstance(cfg.local_model, LocalModelConfig)
    assert cfg.local_model.model_name == "gemma4-26b"


def test_engine_hardware_detection():
    backend_code, backend_desc = detect_hardware_backend()
    assert backend_code in ("gpu", "cpu", "npu")
    assert len(backend_desc) > 0


def test_engine_status_dict():
    engine = LocalModelEngine()
    st = engine.get_status()
    assert "litert_available" in st
    assert "backend" in st
    assert "model_name" in st
    assert "model_path" in st
    assert "imported_models" in st
    assert isinstance(st["imported_models"], list)
