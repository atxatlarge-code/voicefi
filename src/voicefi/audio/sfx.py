"""
Comedy and dramatic sound effects generator and player for VoiceFi.
Provides instant acoustic cues: rimshots, horn honks, sad trombones, applauses, boings, and crickets.
"""

import os
import re
import sys
import time
import wave
import tempfile
import threading
import subprocess
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Callable

SFX_CACHE_DIR = Path.home() / ".voicefi" / "sfx"
SAMPLE_RATE = 44100


def _generate_rimshot(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Ba-dum-tss! Classic comedy drum smash and cymbal crash."""
    dur = 1.3
    t = np.linspace(0, dur, int(sample_rate * dur), False)
    
    # Hit 1: Ba (0.0s) - Snare tap
    h1 = np.exp(-t / 0.035) * np.sin(2 * np.pi * 180 * t) + np.exp(-t / 0.02) * np.random.uniform(-0.35, 0.35, len(t))
    
    # Hit 2: Dum (0.16s) - Tom tap
    t2 = t - 0.16
    mask2 = t2 >= 0
    h2 = np.zeros_like(t)
    h2[mask2] = np.exp(-t2[mask2] / 0.045) * np.sin(2 * np.pi * 140 * t2[mask2]) + np.exp(-t2[mask2] / 0.025) * np.random.uniform(-0.4, 0.4, np.sum(mask2))
    
    # Hit 3: Tss (0.34s) - Cymbal crash & shimmer
    t3 = t - 0.34
    mask3 = t3 >= 0
    h3 = np.zeros_like(t)
    noise = np.random.uniform(-0.8, 0.8, np.sum(mask3))
    shimmer = (np.sin(2 * np.pi * 4200 * t3[mask3]) + np.sin(2 * np.pi * 8400 * t3[mask3]) + 1.2)
    h3[mask3] = np.exp(-t3[mask3] / 0.4) * noise * shimmer
    
    audio = h1 * 0.7 + h2 * 0.8 + h3 * 0.95
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


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
        wave_sub = 0.6 * np.sin(2 * np.pi * f1 * t_sub) + 0.5 * np.sin(2 * np.pi * f2 * t_sub) + 0.25 * np.sin(2 * np.pi * f1 * 2 * t_sub)
        env = np.sin(np.pi * (t_sub / seg_dur)) ** 0.6
        audio[mask] = wave_sub * env * 0.8
        
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def _generate_sad_trombone(sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Wah-wah-wah-waaaah! Classic comedic disappointment."""
    dur = 2.4
    t = np.linspace(0, dur, int(sample_rate * dur), False)
    audio = np.zeros_like(t)
    
    notes = [
        (0.0, 0.42, 293.66),   # D4
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
            np.sin(2 * np.pi * pitch * t_sub) * 0.65 +
            np.sin(2 * np.pi * pitch * 2 * t_sub) * 0.35 +
            np.sin(2 * np.pi * pitch * 3 * t_sub) * 0.18 +
            np.sin(2 * np.pi * pitch * 4 * t_sub) * 0.08
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
    freq = 140.0 + 380.0 * (1.0 - np.exp(-t / 0.15)) + np.sin(2 * np.pi * 22.0 * t) * 45.0 * np.exp(-t / 0.4)
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


_SFX_LOCK = threading.Lock()


def get_sfx_path(name: str) -> Optional[Path]:
    """Resolve and return path to cached SFX WAV file, generating on first use."""
    clean_name = ALIASES.get(name.lower().strip(), name.lower().strip().replace("-", "_"))
    generator = GENERATORS.get(clean_name)
    if not generator:
        return None

    SFX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target_file = SFX_CACHE_DIR / f"{clean_name}.wav"
    
    if target_file.is_file() and target_file.stat().st_size > 100:
        return target_file

    with _SFX_LOCK:
        if target_file.is_file() and target_file.stat().st_size > 100:
            return target_file

        try:
            data = generator(SAMPLE_RATE)
            tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=f"{clean_name}_", suffix=".tmp", dir=str(SFX_CACHE_DIR))
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
    return sorted(list(set(["drum_smash", "honk", "sad_trombone", "applause", "boing", "crickets"])))


def play_sfx(name: str, block: bool = False, volume: float = 1.0) -> bool:
    """Play a comedy or dramatic sound effect using macOS afplay with audio output lock."""
    path = get_sfx_path(name)
    if not path or not path.is_file():
        print(f"[SFX] Unknown sound effect: '{name}'. Available: {list_available_sfx()}", file=sys.stderr)
        return False

    vol_str = str(max(min(volume, 2.0), 0.1))

    def _run():
        if not block and (os.getenv("VOICEFI_TESTING") == "1" or os.getenv("VOICEFI_HEADLESS") == "1"):
            return
        try:
            from voicefi.audio.output_lock import exclusive_audio
            with exclusive_audio(timeout=10.0, owner=f"sfx_{name}"):
                subprocess.run(["afplay", "-v", vol_str, str(path)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    if block:
        _run()
    else:
        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
    return True


def strip_inline_sfx_tags(text: str) -> str:
    """Remove inline SFX tags like [sfx:rimshot] or [rimshot] from spoken text."""
    if not text:
        return ""
    # Strip [sfx:name] or [sfx name]
    cleaned = re.sub(r"\[sfx:?\s*([a-zA-Z_-]+)\]", "", text, flags=re.IGNORECASE)
    # Strip standalone [rimshot], [honk], [applause], [sad_trombone], [boing], [crickets]
    known = "|".join(list_available_sfx() + list(ALIASES.keys()))
    cleaned = re.sub(rf"\[({known})\]", "", cleaned, flags=re.IGNORECASE)
    return " ".join(cleaned.split()).strip()
