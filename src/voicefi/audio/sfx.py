"""
Comedy and dramatic sound effects player and acoustic cues for VoiceFi.
Provides instant acoustic cues: drum smashes (ba-dum-tss), horn honks, sad trombones, applauses, boings, and crickets.
Prefers bundled studio acoustic recordings (44.1 kHz 16-bit PCM WAV) with procedural synthesis fallbacks.
For artist credits, provenance, and Creative Commons licensing, see docs/AUDIO_ATTRIBUTION.md.
"""

import os
import re
import sys
import time
import wave
import shutil
import tempfile
import threading
import subprocess
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Callable

SFX_CACHE_DIR = Path.home() / ".voicefi" / "sfx"
SFX_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
SAMPLE_RATE = 44100


def _generate_rimshot(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """
    High-fidelity acoustic comedy drum smash ('ba-dum CHING!').
    Procedurally synthesizes a snappy, tight 1.15s punchline stinger:
      - Hit 1 ('Ba', 0.00s): Snappy coated snare drum with stick impact transient, drumhead tension decay, and wire rattle.
      - Hit 2 ('Bum' / 'Dum', 0.115s): Tight acoustic wooden tom with warm low-end body resonance.
      - Hit 3 ('CHING!', 0.245s): Punchy bronze crash cymbal with inharmonic Chladni plate modes,
        shimmering wash, stick bell ping, and solid bass drum (kick) weight with fast clean decay.
      - Room acoustics: Tight stage ambiance with clean cosine tail fadeout.
    """
    dur = 1.15  # Snappy, tight comedy stinger duration (~1.15s)
    total_samples = int(sample_rate * dur)
    t = np.linspace(0, dur, total_samples, False)

    def bandpass_noise(n_samples: int, f_low: float, f_high: float) -> np.ndarray:
        """Generate band-limited Gaussian noise in frequency domain (zero phase distortion)."""
        noise = np.random.normal(0.0, 1.0, n_samples)
        spectrum = np.fft.rfft(noise)
        freqs = np.fft.rfftfreq(n_samples, 1.0 / sample_rate)
        response = np.ones_like(freqs, dtype=np.float32)
        if f_low > 0:
            response *= 1.0 / (1.0 + (f_low / np.maximum(freqs, 1e-5)) ** 4)
        if f_high < sample_rate / 2:
            response *= 1.0 / (1.0 + (freqs / f_high) ** 4)
        filtered = np.fft.irfft(spectrum * response, n=n_samples)
        return filtered / (np.std(filtered) + 1e-6)

    # 1. Hit 1: Ba (0.0s) - Snappy snare tap
    dur1 = 0.18
    n1 = int(dur1 * sample_rate)
    t1 = t[:n1]
    stick1 = np.random.normal(0, 1, n1) * np.exp(-t1 / 0.002)
    f1 = 215.0 + 140.0 * np.exp(-t1 / 0.012)
    p1 = 2.0 * np.pi * np.cumsum(f1) / sample_rate
    head1 = (0.7 * np.sin(p1) + 0.28 * np.sin(p1 * 1.59) + 0.15 * np.sin(p1 * 2.14)) * np.exp(-t1 / 0.032)
    rim1 = np.sin(2 * np.pi * 840 * t1) * np.exp(-t1 / 0.010)
    wires1 = bandpass_noise(n1, 2400, 9500) * np.exp(-t1 / 0.042)
    hit1 = (0.6 * head1 + 0.45 * rim1 + 0.55 * wires1 + 0.5 * stick1) * 0.85

    # 2. Hit 2: Bum (0.115s) - Tight warm tom
    hit2_start = 0.115
    dur2 = 0.22
    n2 = int(dur2 * sample_rate)
    t2 = np.linspace(0, dur2, n2, False)
    stick2 = np.random.normal(0, 1, n2) * np.exp(-t2 / 0.003)
    f2 = 120.0 + 70.0 * np.exp(-t2 / 0.018)
    p2 = 2.0 * np.pi * np.cumsum(f2) / sample_rate
    head2 = (0.8 * np.sin(p2) + 0.3 * np.sin(p2 * 1.58) + 0.15 * np.sin(p2 * 2.24)) * np.exp(-t2 / 0.055)
    shell2 = bandpass_noise(n2, 500, 2200) * np.exp(-t2 / 0.025)
    hit2 = (0.9 * head2 + 0.25 * stick2 + 0.2 * shell2) * 0.88

    # 3. Hit 3: CHING! (0.245s) - Punchy Crash Cymbal + Kick Drum Accent
    hit3_start = 0.245
    dur3 = dur - hit3_start
    n3 = int(dur3 * sample_rate)
    t3 = np.linspace(0, dur3, n3, False)

    # Kick drum punch under crash cymbal
    f_kick = 58.0 + 105.0 * np.exp(-t3 / 0.024)
    p_kick = 2.0 * np.pi * np.cumsum(f_kick) / sample_rate
    kick_body = np.sin(p_kick) * np.exp(-t3 / 0.14)
    kick_click = np.random.normal(0, 1, n3) * np.exp(-t3 / 0.003)
    kick = (0.85 * kick_body + 0.35 * kick_click) * 0.82

    # Crash Cymbal with inharmonic bronze modes (tight, snappy decay)
    cym_modes = [
        587.0, 845.0, 1120.0, 1390.0, 1780.0, 2240.0, 2790.0,
        3450.0, 4280.0, 5260.0, 6420.0, 7750.0, 9300.0, 11500.0,
    ]
    ring = np.zeros(n3, dtype=np.float32)
    for idx, fm in enumerate(cym_modes):
        decay = 0.22 + 0.25 * (1.0 - idx / len(cym_modes))
        mod = np.sin(2 * np.pi * 4.0 * t3) * 0.01
        ring += np.sin(2 * np.pi * fm * (t3 + mod)) * np.exp(-t3 / decay) * (1.0 / (idx ** 0.35 + 1.0))
    ring /= len(cym_modes)

    burst = bandpass_noise(n3, 2200, 13000) * ((1.0 - np.exp(-t3 / 0.004)) * np.exp(-t3 / 0.20))
    shimmer = bandpass_noise(n3, 5000, 17500) * ((1.0 - np.exp(-t3 / 0.008)) * np.exp(-t3 / 0.38))
    ping = (
        np.sin(2 * np.pi * 5600 * t3) * 0.35
        + np.sin(2 * np.pi * 8100 * t3) * 0.3
        + np.random.normal(0, 1, n3) * 0.4
    ) * np.exp(-t3 / 0.006)

    cymbal = 0.58 * burst + 0.52 * shimmer + 0.38 * (ring * (1.0 + 0.75 * burst)) + 0.40 * ping
    hit3 = kick + cymbal * 1.18

    mix = np.zeros(total_samples, dtype=np.float32)
    mix[:n1] += hit1
    idx2 = int(hit2_start * sample_rate)
    mix[idx2 : idx2 + n2] += hit2
    idx3 = int(hit3_start * sample_rate)
    mix[idx3 : idx3 + n3] += hit3

    # Tight room reflections
    reverb = np.copy(mix)
    for d_sec, g in [(0.011, 0.15), (0.022, 0.10), (0.035, 0.06)]:
        ds = int(d_sec * sample_rate)
        dly = np.pad(mix[:-ds], (ds, 0))
        damped = np.convolve(dly, [0.25, 0.5, 0.25], mode="same")
        reverb += damped * g

    # Smooth cosine fadeout over the last 150ms to cleanly silence the tail
    fade_len = int(0.15 * sample_rate)
    fade_env = np.ones(total_samples, dtype=np.float32)
    fade_env[-fade_len:] = 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, fade_len)))
    reverb *= fade_env

    out = np.tanh(reverb * 1.4)
    out = (out / np.max(np.abs(out))) * 0.96
    return (np.clip(out, -1.0, 1.0) * 32767).astype(np.int16)


def _generate_honk(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Honk-honk! Corny clown / cab horn."""
    dur = 0.65
    t = np.linspace(0, dur, int(sample_rate * dur), False)
    audio = np.zeros_like(t)

    honk_segments = [
        ((t >= 0.0) & (t < 0.18), 0.0, 0.18),
        ((t >= 0.22) & (t < 0.48), 0.22, 0.26),
    ]

    for mask, t_start, seg_dur in honk_segments:
        if not np.any(mask):
            continue
        t_sub = t[mask] - t_start
        f1, f2 = 349.23, 440.0  # F4 + A4 brass horn chord
        wave_sub = (
            0.6 * np.sin(2 * np.pi * f1 * t_sub)
            + 0.5 * np.sin(2 * np.pi * f2 * t_sub)
            + 0.25 * np.sin(2 * np.pi * f1 * 2 * t_sub)
        )
        env = np.sin(np.pi * (t_sub / seg_dur)) ** 0.6
        audio[mask] = wave_sub * env * 0.8

    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def _generate_sad_trombone(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Wah-wah-wah-waaaah! Classic comedic disappointment."""
    dur = 2.4
    t = np.linspace(0, dur, int(sample_rate * dur), False)
    audio = np.zeros_like(t)

    notes = [
        (0.0, 0.42, 293.66),  # D4
        (0.48, 0.90, 277.18),  # C#4
        (0.96, 1.38, 261.63),  # C4
        (1.44, 2.35, 246.94),  # B3 with vibrato & slide
    ]

    for start, end, freq in notes:
        mask = (t >= start) & (t < end)
        if not np.any(mask):
            continue
        t_sub = t[mask] - start
        seg_dur = end - start

        # Vibrato and slight downward pitch droop on last note
        if start >= 1.44:
            vib = np.sin(2 * np.pi * 5.5 * t_sub) * 7.0
            droop = -12.0 * (t_sub / seg_dur)
            pitch = freq + vib + droop
        else:
            pitch = freq

        harmonics = (
            np.sin(2 * np.pi * pitch * t_sub) * 0.65
            + np.sin(2 * np.pi * pitch * 2 * t_sub) * 0.35
            + np.sin(2 * np.pi * pitch * 3 * t_sub) * 0.18
            + np.sin(2 * np.pi * pitch * 4 * t_sub) * 0.08
        )
        env = np.sin(np.pi * (t_sub / seg_dur)) ** 0.85
        audio[mask] = harmonics * env * 0.75

    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def _generate_applause(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Crowd cheering and enthusiastic applause."""
    dur = 2.0
    t = np.linspace(0, dur, int(sample_rate * dur), False)
    audio = np.zeros_like(t)

    # Background roar / pink noise
    noise = np.random.uniform(-0.35, 0.35, len(t))
    fade = np.minimum(t / 0.3, 1.0) * np.minimum((dur - t) / 0.5, 1.0)
    audio += noise * fade * 0.5

    # Random distinct claps scattered throughout
    num_claps = 65
    clap_times = np.random.uniform(0.05, dur - 0.15, num_claps)
    for ct in clap_times:
        mask = (t >= ct) & (t < ct + 0.04)
        if not np.any(mask):
            continue
        t_sub = t[mask] - ct
        clap_env = np.exp(-t_sub / 0.008)
        clap_snd = np.random.uniform(-0.8, 0.8, len(t_sub)) * clap_env
        audio[mask] += clap_snd * 0.45

    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def _generate_boing(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Cartoon spring boing!"""
    dur = 0.85
    t = np.linspace(0, dur, int(sample_rate * dur), False)

    # Frequency sweep up with vibrato
    freq = (
        140.0
        + 380.0 * (1.0 - np.exp(-t / 0.15))
        + np.sin(2 * np.pi * 22.0 * t) * 45.0 * np.exp(-t / 0.4)
    )
    phase = 2 * np.pi * np.cumsum(freq) / sample_rate

    wave_s = np.sin(phase) + 0.3 * np.sin(2 * phase)
    env = np.exp(-t / 0.28)
    audio = wave_s * env * 0.8
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def _generate_crickets(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Awkward silence crickets chirping."""
    dur = 2.2
    t = np.linspace(0, dur, int(sample_rate * dur), False)
    audio = np.zeros_like(t)

    chirp_groups = [0.1, 0.3, 0.9, 1.1, 1.7, 1.9]
    for cg in chirp_groups:
        mask = (t >= cg) & (t < cg + 0.08)
        if not np.any(mask):
            continue
        t_sub = t[mask] - cg
        carrier = np.sin(2 * np.pi * 4600 * t_sub)
        mod = np.sin(2 * np.pi * 65 * t_sub)
        env = np.sin(np.pi * (t_sub / 0.08))
        audio[mask] = carrier * mod * env * 0.65

    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


GENERATORS: Dict[str, Callable[[int], np.ndarray]] = {
    "drum_smash": _generate_rimshot,
    "drums": _generate_rimshot,
    "drum": _generate_rimshot,
    "rimshot": _generate_rimshot,
    "ba_dum_tss": _generate_rimshot,
    "ba_bum_ching": _generate_rimshot,
    "ba_dum_ching": _generate_rimshot,
    "ching": _generate_rimshot,
    "honk": _generate_honk,
    "horn": _generate_honk,
    "clown": _generate_honk,
    "sad_trombone": _generate_sad_trombone,
    "trombone": _generate_sad_trombone,
    "wah_wah": _generate_sad_trombone,
    "groan": _generate_sad_trombone,
    "applause": _generate_applause,
    "cheer": _generate_applause,
    "clapping": _generate_applause,
    "boing": _generate_boing,
    "spring": _generate_boing,
    "crickets": _generate_crickets,
    "silence": _generate_crickets,
}

ALIASES: Dict[str, str] = {
    "drum-smash": "drum_smash",
    "drum_smash": "drum_smash",
    "drumroll": "drum_smash",
    "drum-roll": "drum_smash",
    "drums": "drum_smash",
    "drum": "drum_smash",
    "rimshot": "drum_smash",
    "rim-shot": "drum_smash",
    "ba-dum-tss": "drum_smash",
    "ba_dum_tss": "drum_smash",
    "badumtss": "drum_smash",
    "ba-bum-ching": "drum_smash",
    "ba_bum_ching": "drum_smash",
    "babumching": "drum_smash",
    "ba-bum-tss": "drum_smash",
    "ba_bum_tss": "drum_smash",
    "ba-dum-ching": "drum_smash",
    "ba_dum_ching": "drum_smash",
    "badumching": "drum_smash",
    "ching": "drum_smash",
    "punchline": "drum_smash",
    "horn-honk": "honk",
    "clown-horn": "honk",
    "sad-trombone": "sad_trombone",
    "wah-wah": "sad_trombone",
    "fail": "sad_trombone",
    "boo": "sad_trombone",
    "claps": "applause",
    "cheers": "applause",
    "awkward": "crickets",
}

SFX_CACHE_VERSION = 5
_SFX_LOCK = threading.Lock()


def _ensure_sfx_cache_current() -> None:
    """Invalidate stale cached SFX if generator algorithms or bundled assets have been upgraded."""
    version_file = SFX_CACHE_DIR / ".version"
    try:
        if version_file.is_file():
            ver = int(version_file.read_text().strip())
            if ver >= SFX_CACHE_VERSION:
                return
    except Exception:
        pass

    SFX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Purge old generated wav files so new acoustic assets take priority
    for stale_file in SFX_CACHE_DIR.glob("*.wav"):
        try:
            stale_file.unlink()
        except Exception:
            pass

    # Copy bundled audio assets to cache if present
    if SFX_ASSETS_DIR.is_dir():
        for asset_wav in SFX_ASSETS_DIR.glob("*.wav"):
            try:
                shutil.copy2(asset_wav, SFX_CACHE_DIR / asset_wav.name)
            except Exception:
                pass

    try:
        version_file.write_text(str(SFX_CACHE_VERSION))
    except Exception:
        pass


def get_sfx_path(name: str) -> Optional[Path]:
    """Resolve and return path to cached SFX WAV file, preferring bundled acoustic assets."""
    clean_name = ALIASES.get(name.lower().strip(), name.lower().strip().replace("-", "_"))

    # 1. Prefer bundled studio acoustic recording asset if available
    bundled_file = SFX_ASSETS_DIR / f"{clean_name}.wav"
    if bundled_file.is_file() and bundled_file.stat().st_size > 1000:
        return bundled_file

    generator = GENERATORS.get(clean_name)
    if not generator:
        return None

    SFX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_sfx_cache_current()
    target_file = SFX_CACHE_DIR / f"{clean_name}.wav"

    if target_file.is_file() and target_file.stat().st_size > 100:
        return target_file

    with _SFX_LOCK:
        if target_file.is_file() and target_file.stat().st_size > 100:
            return target_file

        try:
            data = generator(SAMPLE_RATE)
            tmp_fd, tmp_path_str = tempfile.mkstemp(
                prefix=f"{clean_name}_", suffix=".tmp", dir=str(SFX_CACHE_DIR)
            )
            os.close(tmp_fd)
            tmp_path = Path(tmp_path_str)
            with wave.open(str(tmp_path), "w") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(SAMPLE_RATE)
                f.writeframes(data.tobytes())
            tmp_path.replace(target_file)
        except Exception as e:
            print(f"[SFX] Error generating SFX '{name}': {e}", file=sys.stderr)
            return None

    return target_file


def list_available_sfx() -> List[str]:
    """List distinct available sound effect names."""
    return sorted(
        list(set(["drum_smash", "honk", "sad_trombone", "applause", "boing", "crickets"]))
    )


def play_sfx(name: str, block: bool = False, volume: float = 1.0) -> bool:
    """Play a comedy or dramatic sound effect using macOS afplay with audio output lock."""
    path = get_sfx_path(name)
    if not path or not path.is_file():
        print(
            f"[SFX] Unknown sound effect: '{name}'. Available: {list_available_sfx()}",
            file=sys.stderr,
        )
        return False

    vol_str = str(max(min(volume, 2.0), 0.1))

    def _run():
        if not block and (
            os.getenv("VOICEFI_TESTING") == "1" or os.getenv("VOICEFI_HEADLESS") == "1"
        ):
            return
        try:
            from voicefi.audio.output_lock import exclusive_audio

            with exclusive_audio(timeout=10.0, owner=f"sfx_{name}"):
                subprocess.run(
                    ["afplay", "-v", vol_str, str(path)],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    if block:
        _run()
    else:
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    return True


def strip_inline_sfx_tags(text: str) -> str:
    """Remove inline SFX tags like [sfx:rimshot], [sfx:drum_smash], or [rimshot] from spoken text."""
    if not text:
        return ""
    # Strip [sfx:name], [sfx name], (sfx:name), {sfx:name}
    cleaned = re.sub(r"[\[\(\{]\s*sfx:?\s*([a-zA-Z0-9_-]+)\s*[\]\)\}]", "", text, flags=re.IGNORECASE)
    # Strip standalone [rimshot], [honk], [applause], [sad_trombone], [boing], [crickets], [drum_smash], etc.
    try:
        known = "|".join(list_available_sfx() + list(ALIASES.keys()))
        cleaned = re.sub(rf"\[({known})\]", "", cleaned, flags=re.IGNORECASE)
    except Exception:
        pass
    # Clean inline spaces while preserving newlines for markdown line-by-line structure
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    return "\n".join(lines).strip()

