"""
Unit & Integration Tests for VoiceFi Audio DSP Effects, Voice Transformers & Reel Builder.
"""

import io
import json
import os
import tempfile
import wave
from pathlib import Path
import numpy as np
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from voicefi.audio.effects import VoiceFXEngine, FX_PRESETS
from voicefi.video.reel_builder import ReelBuilder, FORMAT_PRESETS, TYPOGRAPHY_PRESETS
from voicefi.companion.server import CompanionServer, RECORDINGS_DIR
from voicefi.config import VoiceFiConfig


@pytest.fixture
def sample_wav(tmp_path):
    """Generate a clean synthetic 16-bit PCM WAV test file."""
    wav_path = tmp_path / "test_sample.wav"
    sample_rate = 44100
    duration = 2.0
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    # Generate simple speech-like audio (chord + amplitude modulation)
    audio = 0.5 * np.sin(2 * np.pi * 220 * t) + 0.3 * np.sin(2 * np.pi * 440 * t)
    audio_int16 = (audio * 32767).astype(np.int16)

    with wave.open(str(wav_path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(audio_int16.tobytes())

    return wav_path


def test_list_presets():
    """Verify FX preset listing includes all expected presets."""
    presets = VoiceFXEngine.list_presets()
    preset_ids = [p["id"] for p in presets]
    assert "radio_announcer" in preset_ids
    assert "studio_podcast" in preset_ids
    assert "stadium_announcer" in preset_ids
    assert "am_radio" in preset_ids
    assert "cyber_robot" in preset_ids
    assert "deep_monster" in preset_ids
    assert "helium_chipmunk" in preset_ids
    assert "ethereal_space" in preset_ids


def test_get_audio_info(sample_wav):
    """Verify metadata and waveform peak extraction."""
    info = VoiceFXEngine.get_audio_info(sample_wav)
    assert info["filename"] == "test_sample.wav"
    assert info["duration"] >= 1.9
    assert len(info["peaks"]) == 100
    assert info["sample_rate"] in (44100, 48000)


def test_build_custom_filter():
    """Verify custom parameter filter generation."""
    f = VoiceFXEngine.build_custom_filter(
        pitch_semitones=2.0,
        bass_boost_db=6.0,
        treble_boost_db=3.0,
        compression=0.8,
        reverb=0.5,
        volume_gain=1.2
    )
    assert "asetrate=" in f
    assert "equalizer=" in f
    assert "acompressor=" in f
    assert "aecho=" in f
    assert "alimiter=" in f


@pytest.mark.parametrize("preset", [
    "radio_announcer",
    "studio_podcast",
    "stadium_announcer",
    "am_radio",
    "cyber_robot",
    "deep_monster",
    "helium_chipmunk",
    "ethereal_space"
])
def test_apply_all_presets(sample_wav, tmp_path, preset):
    """Verify audio transformation with every built-in voice FX preset."""
    out_mp3 = tmp_path / f"out_{preset}.mp3"
    res = VoiceFXEngine.apply_effect(
        input_audio=sample_wav,
        output_audio=out_mp3,
        preset=preset,
        normalize_loudness=False
    )
    assert res.is_file()
    assert res.stat().st_size > 1000


def test_apply_custom_effect_with_sfx(sample_wav, tmp_path):
    """Verify custom sliders and SFX overlay cues."""
    out_mp3 = tmp_path / "out_custom_sfx.mp3"
    res = VoiceFXEngine.apply_effect(
        input_audio=sample_wav,
        output_audio=out_mp3,
        custom_params={
            "bass_boost_db": 8.0,
            "treble_boost_db": 4.0,
            "compression": 0.7
        },
        sfx_cues=[
            {"name": "drum_smash", "start_sec": 0.5, "volume": 0.8}
        ]
    )
    assert res.is_file()
    assert res.stat().st_size > 1000


def test_auto_generate_slides_from_text():
    """Verify automatic turn segmentation into slide cards."""
    transcript = "Free your voice, free your mind, free time. Voicefi is the universal voice layer for AI agents."
    slides = ReelBuilder.auto_generate_slides_from_text(
        transcript=transcript,
        total_duration=16.0,
        speaker="Radio Host"
    )
    assert len(slides) >= 1
    assert slides[0]["speaker"] == "Radio Host"
    assert slides[0]["dur"] > 0


def test_render_html_slide():
    """Verify HTML slide card template rendering."""
    slide_data = {
        "slide_idx": 1,
        "speaker": "Radio Host",
        "counter": "1/3",
        "hook": "“Free your voice...”",
        "body": "Speak at the speed of thought",
        "dur": 4.5
    }
    html = ReelBuilder.render_html_slide(
        slide_data=slide_data,
        format_type="9:16",
        preset_config=TYPOGRAPHY_PRESETS["classic_ai"]
    )
    assert "Free your voice" in html
    assert "Radio Host" in html
    assert "1080px" in html or "1920px" in html


def test_trim_audio(sample_wav, tmp_path):
    """Verify audio trimming with fade edges."""
    out_mp3 = tmp_path / "out_trimmed.mp3"
    res = VoiceFXEngine.trim_audio(
        input_audio=sample_wav,
        output_audio=out_mp3,
        start_sec=0.5,
        end_sec=1.5
    )
    assert res.is_file()
    info = VoiceFXEngine.get_audio_info(res)
    assert 0.9 <= info["duration"] <= 1.1


class TestStudioServerEndpoints(AioHTTPTestCase):
    """Integration test suite for Companion Server Voice Recording & FX REST APIs."""

    async def get_application(self):
        cfg = VoiceFiConfig()
        self.server = CompanionServer(config=cfg, port=5199)
        return self.server.app

    async def test_get_presets_api(self):
        resp = await self.client.request("GET", "/api/studio/presets")
        assert resp.status == 200
        data = await resp.json()
        assert "presets" in data
        assert len(data["presets"]) >= 8
        assert "formats" in data
        assert "9:16" in data["formats"]

    async def test_get_recordings_api(self):
        resp = await self.client.request("GET", "/api/studio/recordings")
        assert resp.status == 200
        data = await resp.json()
        assert "recordings" in data
        assert isinstance(data["recordings"], list)

    async def test_upload_and_apply_fx_api(self):
        # 1. Upload valid 2.0s PCM WAV audio
        sample_rate = 44100
        duration = 2.0
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        audio = (0.5 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
        bio = io.BytesIO()
        with wave.open(bio, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(sample_rate)
            f.writeframes(audio.tobytes())
        raw_wav_bytes = bio.getvalue()

        import base64
        b64 = base64.b64encode(raw_wav_bytes).decode("utf-8")

        resp = await self.client.request("POST", "/api/studio/upload", json={
            "audio_base64": b64,
            "filename": "test_api_sample.wav"
        })
        assert resp.status == 200
        up_data = await resp.json()
        assert up_data["success"] is True
        rec_id = up_data["id"]

        # 2. Trim audio
        resp_trim = await self.client.request("POST", "/api/studio/trim", json={
            "recording_id": rec_id,
            "start_sec": 0.0,
            "end_sec": 0.5
        })
        assert resp_trim.status == 200
        trim_data = await resp_trim.json()
        assert trim_data["success"] is True

        # 3. Apply Radio Announcer FX
        resp_fx = await self.client.request("POST", "/api/studio/apply_fx", json={
            "recording_id": rec_id,
            "preset": "radio_announcer"
        })
        assert resp_fx.status == 200
        fx_data = await resp_fx.json()
        assert fx_data["success"] is True
        assert "radio_announcer" in fx_data["master_id"]
