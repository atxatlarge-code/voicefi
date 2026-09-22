import wave
import pytest
from voicefi.audio.sfx import (
    get_sfx_path,
    list_available_sfx,
    play_sfx,
    ALIASES,
    SAMPLE_RATE,
)


def test_list_available_sfx():
    sfx_list = list_available_sfx()
    expected = ["applause", "boing", "crickets", "drum_smash", "honk", "sad_trombone"]
    assert sorted(sfx_list) == sorted(expected)


@pytest.mark.parametrize(
    "name",
    ["applause", "boing", "crickets", "drum_smash", "honk", "sad_trombone"],
)
def test_all_sfx_resolve_and_are_valid_wav(name):
    path = get_sfx_path(name)
    assert path is not None, f"SFX '{name}' failed to resolve"
    assert path.is_file(), f"SFX path '{path}' does not exist"
    assert path.stat().st_size > 1000, f"SFX '{name}' file size is unexpectedly small"

    # Verify WAV header specs (mono or stereo 16-bit, 44.1kHz)
    with wave.open(str(path), "rb") as wf:
        assert wf.getframerate() == SAMPLE_RATE
        assert wf.getsampwidth() == 2  # 16-bit PCM
        assert wf.getnframes() > int(SAMPLE_RATE * 0.2)  # At least 200ms duration


@pytest.mark.parametrize(
    "alias,target",
    [
        ("ba-bum-ching", "drum_smash.wav"),
        ("ba-dum-tss", "drum_smash.wav"),
        ("rimshot", "drum_smash.wav"),
        ("horn-honk", "honk.wav"),
        ("clown-horn", "honk.wav"),
        ("sad-trombone", "sad_trombone.wav"),
        ("wah-wah", "sad_trombone.wav"),
        ("cheers", "applause.wav"),
        ("claps", "applause.wav"),
        ("awkward", "crickets.wav"),
    ],
)
def test_sfx_aliases(alias, target):
    path = get_sfx_path(alias)
    assert path is not None
    assert path.name == target


def test_play_sfx_testing_env(monkeypatch):
    monkeypatch.setenv("VOICEFI_TESTING", "1")
    # In test mode, play_sfx returns without calling afplay when block=False
    assert play_sfx("drum_smash", block=False) is True
    assert play_sfx("nonexistent_sound_12345", block=False) is False
