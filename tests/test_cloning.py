"""
Unit and integration tests for Voice Training, Acoustic Analysis, Voice Cloning, and Persona Generation.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from voicefi.config import VoiceFiConfig
from voicefi.tts import (
    ElevenLabsTTS,
    VoiceCloneManager,
    analyze_audio_acoustics,
    estimate_pitch_f0,
    find_persona,
    generate_persona_prompt,
    get_tts_engine,
    list_all_available_voices,
)
from voicefi.cli import cmd_clone


@pytest.fixture
def temp_clones_dir(tmp_path):
    """Provide an isolated temporary directory for cloned voice profiles."""
    d = tmp_path / "cloned_voices"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def synthetic_wav_samples(tmp_path):
    """Create synthetic WAV files with distinct frequencies for testing."""
    sample_rate = 16000
    duration = 1.5  # seconds
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

    # 130 Hz (Baritone)
    audio1 = 0.5 * np.sin(2 * np.pi * 130 * t).astype(np.float32)
    # 200 Hz (Alto)
    audio2 = 0.5 * np.sin(2 * np.pi * 200 * t).astype(np.float32)

    path1 = tmp_path / "sample_130hz.wav"
    path2 = tmp_path / "sample_200hz.wav"

    sf.write(str(path1), audio1, sample_rate)
    sf.write(str(path2), audio2, sample_rate)

    return [path1, path2]


def test_pitch_estimation():
    """Test F0 fundamental frequency estimation on synthetic tones."""
    sample_rate = 16000
    t = np.linspace(0, 1.0, sample_rate, endpoint=False)
    # 150 Hz pure tone
    audio_150 = (0.5 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
    f0 = estimate_pitch_f0(audio_150, sample_rate=sample_rate)
    assert 135 <= f0 <= 165

    # Silence
    silence = np.zeros(sample_rate, dtype=np.float32)
    f0_silence = estimate_pitch_f0(silence, sample_rate=sample_rate)
    assert f0_silence == 140.0  # default fallback


def test_acoustic_analysis(synthetic_wav_samples):
    """Test multi-sample acoustic feature extraction."""
    metrics = analyze_audio_acoustics(synthetic_wav_samples)
    assert metrics["sample_count"] == 2
    assert metrics["total_duration_seconds"] >= 2.9
    assert metrics["avg_pitch_hz"] > 0
    assert "vocal_range" in metrics
    assert "suggested_neural_base" in metrics


def test_generate_persona_prompt():
    """Test persona prompt generation for agent pairing."""
    acoustic_info = {"vocal_range": "Baritone / Grounded"}
    traits = {
        "tone": "pragmatic and crisp",
        "catchphrases": "Ship it, tests look great",
    }
    prompt = generate_persona_prompt("Jake", acoustic_info, traits)
    assert "Persona Profile: Jake" in prompt
    assert "Baritone / Grounded" in prompt
    assert "Ship it, tests look great" in prompt


def test_voice_clone_manager_train_local(temp_clones_dir, synthetic_wav_samples):
    """Test local acoustic profile training without external API."""
    manager = VoiceCloneManager(root_dir=temp_clones_dir)
    profile = manager.train_voice(
        name="JakeLocal",
        sample_paths=synthetic_wav_samples,
        description="Local offline clone of Jake",
    )

    assert profile.name == "JakeLocal"
    assert profile.id == "cloned_jakelocal"
    assert profile.provider == "edge_tts"
    assert len(profile.sample_paths) == 2
    assert profile.calibrated_voice is not None

    # Verify persistent storage
    loaded = manager.get_cloned_voice("JakeLocal")
    assert loaded is not None
    assert loaded.id == profile.id
    assert len(manager.list_cloned_voices()) == 1


def test_voice_clone_manager_train_elevenlabs(temp_clones_dir, synthetic_wav_samples):
    """Test ElevenLabs IVC training flow with mocked API response."""
    manager = VoiceCloneManager(root_dir=temp_clones_dir)

    with patch("voicefi.tts.elevenlabs.ElevenLabsTTS.add_voice") as mock_add:
        mock_add.return_value = {"voice_id": "eleven_custom_voice_123"}

        profile = manager.train_voice(
            name="JakePro",
            sample_paths=synthetic_wav_samples,
            api_key="mock_xi_api_key",
            description="Pro tier cloned voice",
        )

        assert profile.name == "JakePro"
        assert profile.id == "eleven_custom_voice_123"
        assert profile.provider == "elevenlabs"
        mock_add.assert_called_once()


def test_assign_cloned_voice_to_agent(temp_clones_dir, synthetic_wav_samples):
    """Test assigning cloned voice to antigravity and subagents in config."""
    manager = VoiceCloneManager(root_dir=temp_clones_dir)
    profile = manager.train_voice(
        name="JakeAssign",
        sample_paths=synthetic_wav_samples,
    )

    config = VoiceFiConfig()
    tgt, vid = manager.assign_to_agent("JakeAssign", "antigravity", config)
    assert tgt == "antigravity"
    assert config.agents["antigravity"].voice == profile.calibrated_voice

    # Subagent assignment
    manager.assign_to_agent("JakeAssign", "researcher", config)
    assert "researcher" in config.subagents

    # Check profile records assigned agents
    updated_profile = manager.get_cloned_voice("JakeAssign")
    assert "antigravity" in updated_profile.assigned_agents
    assert "researcher" in updated_profile.assigned_agents


def test_catalog_find_and_list_cloned(temp_clones_dir, synthetic_wav_samples):
    """Test that cloned voices appear in find_persona and list_all_available_voices."""
    with patch("voicefi.tts.cloning.get_clones_dir", return_value=temp_clones_dir):
        manager = VoiceCloneManager(root_dir=temp_clones_dir)
        manager.train_voice("JakeCatalog", synthetic_wav_samples)

        persona = find_persona("JakeCatalog")
        assert persona is not None
        assert persona.name == "JakeCatalog"
        assert persona.recommended_role == "Personal Voice Clone"

        all_voices = list_all_available_voices()
        cloned_entries = [v for v in all_voices if v.get("cloned")]
        assert len(cloned_entries) >= 1
        assert cloned_entries[0]["name"] == "JakeCatalog"


def test_get_tts_engine_with_cloned_voice(temp_clones_dir, synthetic_wav_samples):
    """Test get_tts_engine resolution when configured with a cloned voice."""
    with patch("voicefi.tts.cloning.get_clones_dir", return_value=temp_clones_dir):
        manager = VoiceCloneManager(root_dir=temp_clones_dir)
        profile = manager.train_voice("JakeEngine", synthetic_wav_samples)

        config = VoiceFiConfig()
        manager.assign_to_agent("JakeEngine", "antigravity", config)

        engine = get_tts_engine(config, agent_name="antigravity")
        assert engine is not None


def test_cli_cmd_clone_list(temp_clones_dir, synthetic_wav_samples, capsys):
    """Test CLI 'vg clone list' output."""
    with patch("voicefi.tts.cloning.get_clones_dir", return_value=temp_clones_dir):
        manager = VoiceCloneManager(root_dir=temp_clones_dir)
        manager.train_voice("JakeCLI", synthetic_wav_samples)

        args = MagicMock()
        args.clone_action = "list"
        args.config = None

        cmd_clone(args)
        captured = capsys.readouterr()
        assert "Trained Custom Voices" in captured.out
        assert "JakeCLI" in captured.out


def test_cli_cmd_clone_delete(temp_clones_dir, synthetic_wav_samples, capsys):
    """Test CLI 'vg clone delete' command."""
    with patch("voicefi.tts.cloning.get_clones_dir", return_value=temp_clones_dir):
        manager = VoiceCloneManager(root_dir=temp_clones_dir)
        manager.train_voice("JakeDelete", synthetic_wav_samples)
        assert manager.get_cloned_voice("JakeDelete") is not None

        args = MagicMock()
        args.clone_action = "delete"
        args.name = "JakeDelete"
        args.from_provider = False
        args.config = None

        cmd_clone(args)
        assert manager.get_cloned_voice("JakeDelete") is None
