"""
Unit tests for F5-TTS open-source voice cloning provider and integration.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from voicefi.config import VoiceFiConfig
from voicefi.tts.f5_tts import F5TTS
from voicefi.tts.cloning import ClonedVoiceProfile, VoiceCloneManager
from voicefi.tts import get_tts_engine


def test_f5_tts_instantiation():
    tts = F5TTS(ref_audio="/tmp/test.wav", ref_text="Hello world")
    assert tts.ref_audio == "/tmp/test.wav"
    assert tts.ref_text == "Hello world"
    assert tts.model_name == "F5TTS_v1_Base"


def test_f5_tts_fallback_on_missing_ref():
    tts = F5TTS(ref_audio="/nonexistent/path/ref.wav", ref_text="")
    with patch("voicefi.tts.f5_tts.F5TTS._resolve_reference_audio", return_value=(None, None)):
        success = tts.speak_to_file("Hello", Path("/tmp/out.wav"))
        assert success is False


def test_f5_tts_resolve_reference_from_cloned_profile(tmp_path):
    prof = ClonedVoiceProfile(
        id="cloned_ava",
        name="Ava",
        provider="f5_tts",
        sample_paths=[str(tmp_path / "sample1.wav")],
        labels={"ref_text": "Sample voice prompt for Ava"},
    )
    (tmp_path / "sample1.wav").write_bytes(b"RIFFdummydata")

    with patch.object(Path, "home", return_value=tmp_path):
        clones_dir = tmp_path / ".voicefi" / "cloned_voices" / "ava"
        clones_dir.mkdir(parents=True, exist_ok=True)
        import json
        with open(clones_dir / "profile.json", "w") as f:
            json.dump(prof.model_dump(), f)

        tts = F5TTS()
        ref_file, ref_text = tts._resolve_reference_audio()
        assert ref_file == str(tmp_path / "sample1.wav")
        assert ref_text == "Sample voice prompt for Ava"


def test_get_tts_engine_f5_tts(tmp_path):
    config = VoiceFiConfig()
    config.tts.provider = "f5_tts"
    config.tts.f5_ref_audio = str(tmp_path / "ref.wav")
    config.tts.f5_ref_text = "Testing reference speech"

    engine = get_tts_engine(config)
    assert isinstance(engine, F5TTS)
    assert engine.ref_audio == str(tmp_path / "ref.wav")
    assert engine.ref_text == "Testing reference speech"
