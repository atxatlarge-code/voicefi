import os
import pytest
from voicefi.config import VoiceFiConfig, save_config

@pytest.fixture(autouse=True)
def isolate_test_config(tmp_path, monkeypatch):
    """Isolate tests so they never read or write ~/.voicefi/config.yaml."""
    test_config_file = tmp_path / "config.yaml"
    initial_cfg = VoiceFiConfig()
    save_config(initial_cfg, target_path=test_config_file)
    monkeypatch.setenv("VOICEFI_CONFIG", str(test_config_file))
    monkeypatch.setattr("voicefi.config.get_default_config_path", lambda: test_config_file)
    yield test_config_file
