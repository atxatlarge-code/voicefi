"""
Unit tests for Zero-Render Speech-to-Speech (STS) Video Dubber.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from voicefi.video.sts_dubber import ZeroRenderDubber, get_audio_duration


def test_sts_dubber_init():
    dubber = ZeroRenderDubber(whisper_model_size="base.en")
    assert dubber.whisper_model_size == "base.en"
    assert dubber._whisper_model is None


def test_align_audio_duration_filter(tmp_path):
    dubber = ZeroRenderDubber()
    # Generate 2-second test tone
    test_src = tmp_path / "test_2s.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.0",
            "-ar",
            "24000",
            str(test_src),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    # Stretch/pad to 3.0 seconds
    target_aligned = tmp_path / "test_aligned_3s.wav"
    dubber.align_audio_to_duration(
        source_duration=3.0,
        generated_wav=test_src,
        output_aligned_wav=target_aligned,
    )

    assert target_aligned.exists()
    dur = get_audio_duration(target_aligned)
    assert pytest.approx(dur, abs=0.05) == 3.0


def test_provider_auto_routing():
    dubber = ZeroRenderDubber()
    with patch("voicefi.tts.voice_acting.VoiceActingTTS.speak_to_file") as mock_speak:
        out_wav = Path(tempfile.mktemp(suffix=".wav"))
        dubber.synthesize_voice(
            text="Attention recruits!",
            voice="drill_sergeant",
            provider="auto",
            output_wav=out_wav,
        )
        assert mock_speak.called
