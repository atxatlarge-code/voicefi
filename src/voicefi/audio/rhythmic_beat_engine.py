"""
VoiceFi™ Rhythmic Beat Engine & Multi-Genre Backing Bed Synthesizer.
Standardizes musical cadence (default 90 BPM 4/4 meter) for spoken voice,
procedural beat generation (Lo-Fi boom-bap, 808 trap, half-time dub),
comedic hard-mute void drops, and sample-accurate timeline alignment.
"""

import math
from typing import Dict, List, Optional, Tuple, Union
import numpy as np

SAMPLE_RATE = 44100


class RhythmicGrid:
    """
    Standardizes musical meter and time-to-bar-beat transformations.
    Default 90.0 BPM in 4/4 meter:
      - 1 Quarter-note beat = 0.6667s (667ms)
      - 1 Bar (Measure)     = 2.6667s
      - 2 Bars (<6s loop)   = 5.3333s
      - 3.33 Bars (9s reel) = 8.8889s
      - 8 Bars (<30s reel)  = 21.3333s
    """

    def __init__(self, bpm: float = 90.0, beats_per_bar: int = 4, sample_rate: int = SAMPLE_RATE):
        self.bpm = float(bpm)
        self.beats_per_bar = int(beats_per_bar)
        self.sample_rate = int(sample_rate)
        self.beat_sec = 60.0 / self.bpm
        self.bar_sec = self.beat_sec * self.beats_per_bar

    def bar_beat_to_seconds(self, bar: int, beat: float = 1.0) -> float:
        """Convert 1-indexed (bar, beat) into exact seconds from timeline start."""
        return (bar - 1) * self.bar_sec + (beat - 1.0) * self.beat_sec

    def seconds_to_bar_beat(self, seconds: float) -> Tuple[int, float]:
        """Convert seconds into 1-indexed (bar, beat)."""
        total_beats = seconds / self.beat_sec
        bar = int(total_beats // self.beats_per_bar) + 1
        beat = (total_beats % self.beats_per_bar) + 1.0
        return bar, beat

    def snap_to_nearest_beat(self, seconds: float, division: float = 0.25) -> float:
        """Snap a timestamp to the nearest musical grid division (e.g. 0.25 = 16th note)."""
        div_sec = self.beat_sec * division
        return round(seconds / div_sec) * div_sec

    def get_bar_duration(self, bars: float) -> float:
        """Total duration in seconds for a given number of bars."""
        return bars * self.bar_sec

    def bar_to_samples(self, bar: int, beat: float = 1.0) -> int:
        """Convert (bar, beat) directly to sample index."""
        return int(round(self.bar_beat_to_seconds(bar, beat) * self.sample_rate))


# --- Procedural Drum & Instrument Synthesis (Pure NumPy) ---

def synth_808_kick(dur: float = 0.55, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Deep 808 sub kick with pitch sweep and subtle punch transient."""
    t = np.linspace(0, dur, int(sr * dur), False)
    freq_sweep = 155.0 * np.exp(-t / 0.038) + 40.0
    phase = 2 * np.pi * np.cumsum(freq_sweep) / sr
    body = np.sin(phase) * np.exp(-t / 0.22)
    click = np.random.uniform(-0.5, 0.5, len(t)) * np.exp(-t / 0.005)
    kick = body * 0.88 + click * 0.18
    return np.clip(kick, -1.0, 1.0).astype(np.float32)


def synth_punchy_kick(dur: float = 0.35, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Acoustic-style filtered boom-bap kick."""
    t = np.linspace(0, dur, int(sr * dur), False)
    freq_sweep = 110.0 * np.exp(-t / 0.025) + 55.0
    phase = 2 * np.pi * np.cumsum(freq_sweep) / sr
    body = np.sin(phase) * np.exp(-t / 0.14)
    click = np.random.uniform(-0.4, 0.4, len(t)) * np.exp(-t / 0.004)
    kick = body * 0.85 + click * 0.22
    return np.clip(kick, -1.0, 1.0).astype(np.float32)


def synth_snare(dur: float = 0.32, sr: int = SAMPLE_RATE, rim: bool = False) -> np.ndarray:
    """Crisp hip-hop snare with tonal body and snappy noise tail."""
    t = np.linspace(0, dur, int(sr * dur), False)
    tone_f = 210 if not rim else 340
    tone = np.sin(2 * np.pi * tone_f * t) * np.exp(-t / 0.045)
    noise = np.random.uniform(-0.75, 0.75, len(t)) * np.exp(-t / 0.11)
    snare = tone * 0.35 + noise * 0.65
    return np.clip(snare, -1.0, 1.0).astype(np.float32)


def synth_hihat(dur: float = 0.07, open_hat: bool = False, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Closed or open trap / boom-bap hi-hat."""
    d = dur if not open_hat else 0.28
    t = np.linspace(0, d, int(sr * d), False)
    noise = np.random.uniform(-0.9, 0.9, len(t))
    decay = 0.018 if not open_hat else 0.12
    env = np.exp(-t / decay)
    return (noise * env * 0.35).astype(np.float32)


def synth_riser_snare_roll(dur: float = 1.33, bpm: float = 90.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Accelerating snare roll build-up for pre-drop tension (quarter ➔ 8th ➔ 16th ➔ 32nd notes)."""
    total_samples = int(dur * sr)
    buffer = np.zeros(total_samples, dtype=np.float32)
    snare = synth_snare(0.2, sr=sr)

    # Accelerate hits exponentially over the duration
    hit_times = []
    curr = 0.0
    interval = (60.0 / bpm) / 2.0  # start at 8th note
    while curr < dur - 0.05:
        hit_times.append(curr)
        curr += interval
        interval = max(interval * 0.72, 0.042)  # speed up to rapid roll

    for idx, ht in enumerate(hit_times):
        s_idx = int(ht * sr)
        # Volume swells from 0.25 to 1.0
        gain = 0.25 + 0.75 * (idx / max(len(hit_times) - 1, 1))
        end_idx = min(s_idx + len(snare), total_samples)
        part = snare[: end_idx - s_idx] * gain
        buffer[s_idx:end_idx] += part

    return buffer


def synth_rhodes_chord(
    freqs: List[float], dur: float = 2.4, velocity: float = 0.5, sr: int = SAMPLE_RATE
) -> np.ndarray:
    """Warm electric piano / Rhodes chord with tremolo and gentle bell harmonic."""
    t = np.linspace(0, dur, int(sr * dur), False)
    chord = np.zeros_like(t)
    tremolo = 1.0 + 0.18 * np.sin(2 * np.pi * 4.5 * t)

    for f in freqs:
        f1 = np.sin(2 * np.pi * f * t)
        f2 = 0.28 * np.sin(2 * np.pi * (f * 2.0) * t)
        f3 = 0.09 * np.sin(2 * np.pi * (f * 3.0) * t)
        env = np.exp(-t / 1.1)
        chord += (f1 + f2 + f3) * env

    chord = (chord / len(freqs)) * tremolo * velocity
    return np.clip(chord, -1.0, 1.0).astype(np.float32)


# --- Modular Backing Bed Producers ---

def generate_lofi_boombap_bed(
    bars: int = 4,
    bpm: float = 90.0,
    drop_bar: Optional[int] = None,
    drop_duration_beats: float = 2.0,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Constructs a warm Lo-Fi boom-bap instrumental bed.
    Rhodes chords (Dm9 - G13 - Cmaj9 - Am7), filtered dusty kick, snap snare, swings.
    """
    grid = RhythmicGrid(bpm=bpm, sample_rate=sr)
    total_dur = grid.get_bar_duration(bars)
    total_samples = int(total_dur * sr)
    mix = np.zeros(total_samples, dtype=np.float32)

    kick = synth_punchy_kick(sr=sr)
    snare = synth_snare(sr=sr)
    hihat = synth_hihat(sr=sr)
    open_hat = synth_hihat(open_hat=True, sr=sr)

    # Chords: Dm9, G13, Cmaj9, A7alt
    chord_prog = [
        [146.83, 220.00, 261.63, 329.63, 349.23],  # Dm9
        [98.00, 196.00, 246.94, 293.66, 329.63],   # G13
        [130.81, 196.00, 246.94, 293.66, 329.63],  # Cmaj9
        [110.00, 164.81, 220.00, 277.18, 329.63],  # A7alt
    ]

    for bar_idx in range(1, bars + 1):
        bar_start_sec = grid.bar_beat_to_seconds(bar_idx, 1.0)
        chord_freqs = chord_prog[(bar_idx - 1) % len(chord_prog)]
        chord = synth_rhodes_chord(chord_freqs, dur=grid.bar_sec * 0.95, velocity=0.42, sr=sr)
        c_s = int(bar_start_sec * sr)
        c_e = min(c_s + len(chord), total_samples)
        mix[c_s:c_e] += chord[: c_e - c_s]

        # Drum loop: Kick on 1 & 2.75, Snare on 2 & 4, Hi-hat on eighths
        for beat in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]:
            t_sec = grid.bar_beat_to_seconds(bar_idx, beat)
            idx = int(t_sec * sr)
            if idx >= total_samples:
                continue

            # Hi-hat with gentle swing
            hat_sample = open_hat if beat == 2.5 else hihat
            hat_len = min(len(hat_sample), total_samples - idx)
            mix[idx: idx + hat_len] += hat_sample[:hat_len] * 0.32

            # Kick
            if beat in [1.0, 2.75]:
                k_len = min(len(kick), total_samples - idx)
                mix[idx: idx + k_len] += kick[:k_len] * 0.65

            # Snare
            if beat in [2.0, 4.0]:
                s_len = min(len(snare), total_samples - idx)
                mix[idx: idx + s_len] += snare[:s_len] * 0.58

    # Apply hard-mute void drop if requested
    if drop_bar is not None and drop_bar <= bars:
        drop_start_sec = grid.bar_beat_to_seconds(drop_bar, 1.0)
        drop_dur_sec = drop_duration_beats * grid.beat_sec
        mix = apply_hard_mute(mix, drop_start_sec, drop_dur_sec, sr=sr)

    return np.clip(mix, -1.0, 1.0).astype(np.float32)


def generate_808_trap_bed(
    bars: int = 4,
    bpm: float = 90.0,
    drop_bar: int = 3,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Constructs an 808 Trap cinematic bed:
    Pre-drop bars feature high-tension ambient strings + rising snare build;
    Drop bar unleashes heavy 808 sub-bass kicks, rapid hi-hat rolls, and punch.
    """
    grid = RhythmicGrid(bpm=bpm, sample_rate=sr)
    total_dur = grid.get_bar_duration(bars)
    total_samples = int(total_dur * sr)
    mix = np.zeros(total_samples, dtype=np.float32)

    kick808 = synth_808_kick(dur=0.65, sr=sr)
    snare = synth_snare(dur=0.35, sr=sr)
    hihat = synth_hihat(dur=0.06, sr=sr)

    # Ambient drone string
    t_full = np.linspace(0, total_dur, total_samples, False)
    string_drone = (
        0.18 * np.sin(2 * np.pi * 146.83 * t_full)  # D3
        + 0.14 * np.sin(2 * np.pi * 220.00 * t_full)  # A3
        + 0.10 * np.sin(2 * np.pi * 293.66 * t_full)  # D4
    ) * (1.0 + 0.08 * np.sin(2 * np.pi * 0.6 * t_full))
    mix += string_drone.astype(np.float32)

    # Bars before drop: Sparse rim/hat + riser in the bar immediately preceding drop
    for b in range(1, drop_bar):
        if b == drop_bar - 1:
            # Snare riser during the last 2 beats of pre-drop bar
            riser_start = grid.bar_beat_to_seconds(b, 2.5)
            riser = synth_riser_snare_roll(dur=grid.beat_sec * 2.5, bpm=bpm, sr=sr)
            r_idx = int(riser_start * sr)
            r_end = min(r_idx + len(riser), total_samples)
            mix[r_idx:r_end] += riser[: r_end - r_idx] * 0.85
        else:
            # Subtle quarter-note click
            for beat in [1.0, 2.0, 3.0, 4.0]:
                s_idx = grid.bar_to_samples(b, beat)
                if s_idx < total_samples:
                    h_end = min(s_idx + len(hihat), total_samples)
                    mix[s_idx:h_end] += hihat[: h_end - s_idx] * 0.22

    # Drop bar onwards: Full 808 explosion
    for b in range(drop_bar, bars + 1):
        for beat in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5]:
            idx = grid.bar_to_samples(b, beat)
            if idx >= total_samples:
                continue

            # 16th-note trap hi-hats with occasional triplets
            h_end = min(idx + len(hihat), total_samples)
            mix[idx:h_end] += hihat[: h_end - idx] * 0.38

            # Sub 808 Kick on beat 1 and syncopated beat 3.5
            if beat in [1.0, 3.5]:
                k_end = min(idx + len(kick808), total_samples)
                mix[idx:k_end] += kick808[: k_end - idx] * 0.88

            # Snare on 2.0 and 4.0
            if beat in [2.0, 4.0]:
                s_end = min(idx + len(snare), total_samples)
                mix[idx:s_end] += snare[: s_end - idx] * 0.72

    return np.clip(mix, -1.0, 1.0).astype(np.float32)


def generate_dub_reggae_bed(
    bars: int = 4,
    bpm: float = 90.0,
    drop_bar: Optional[int] = None,
    drop_duration_beats: float = 2.0,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Constructs a relaxed half-time Dub / Reggae bed.
    Offbeat guitar/organ skanks on the 'and' (beats 1.5, 2.5, 3.5, 4.5), deep sub bass, rimshots.
    """
    grid = RhythmicGrid(bpm=bpm, sample_rate=sr)
    total_dur = grid.get_bar_duration(bars)
    total_samples = int(total_dur * sr)
    mix = np.zeros(total_samples, dtype=np.float32)

    kick = synth_punchy_kick(dur=0.4, sr=sr)
    snare = synth_snare(dur=0.28, rim=True, sr=sr)

    # Skank chords (short staccato chop with tape delay)
    skank_chord = synth_rhodes_chord([174.61, 220.00, 261.63, 329.63], dur=0.18, velocity=0.55, sr=sr)

    for bar_idx in range(1, bars + 1):
        # Kick on Beat 1 and Beat 3
        for beat in [1.0, 3.0]:
            k_idx = grid.bar_to_samples(bar_idx, beat)
            if k_idx < total_samples:
                k_end = min(k_idx + len(kick), total_samples)
                mix[k_idx:k_end] += kick[: k_end - k_idx] * 0.70

        # Rimshot snare on Beat 3 (Classic One Drop)
        s_idx = grid.bar_to_samples(bar_idx, 3.0)
        if s_idx < total_samples:
            s_end = min(s_idx + len(snare), total_samples)
            mix[s_idx:s_end] += snare[: s_end - s_idx] * 0.75

        # Offbeat skanks on beats 1.5, 2.5, 3.5, 4.5
        for beat in [1.5, 2.5, 3.5, 4.5]:
            idx = grid.bar_to_samples(bar_idx, beat)
            if idx < total_samples:
                end = min(idx + len(skank_chord), total_samples)
                mix[idx:end] += skank_chord[: end - idx] * 0.45

    if drop_bar is not None and drop_bar <= bars:
        drop_start_sec = grid.bar_beat_to_seconds(drop_bar, 1.0)
        drop_dur_sec = drop_duration_beats * grid.beat_sec
        mix = apply_hard_mute(mix, drop_start_sec, drop_dur_sec, sr=sr)

    return np.clip(mix, -1.0, 1.0).astype(np.float32)


# --- Comedic Hard Mute & Dynamic Ducking ---

def apply_hard_mute(
    audio: np.ndarray,
    start_sec: float,
    duration_sec: float,
    sr: int = SAMPLE_RATE,
    fade_ms: float = 20.0,
    pre_roll_ms: float = 22.0,
) -> np.ndarray:
    """
    Applies the Comedic Hard Mute ("Void Drop") with musical precision.
    Pre-rolls the mute so the preceding kick transient does not click or truncate,
    and fades in BEFORE the return downbeat so the drum hit lands at 100% attack velocity.
    """
    out = audio.copy()
    pre_samples = int(sr * (pre_roll_ms / 1000.0))
    fade_len = max(int(sr * (fade_ms / 1000.0)), 1)

    s_nominal = int(start_sec * sr)
    e_nominal = min(int((start_sec + duration_sec) * sr), len(out))

    # Pre-roll mute start so downbeat kick is entirely prevented from clicking
    s_idx = max(0, s_nominal - pre_samples)
    f_start = max(0, s_idx - fade_len)
    if s_idx > f_start:
        fade_out = np.linspace(1.0, 0.0, s_idx - f_start, dtype=np.float32)
        out[f_start:s_idx] *= fade_out

    # Pre-roll return so fade-in completes BEFORE the return downbeat transient strikes
    e_idx = max(s_idx, e_nominal - pre_samples)
    f_in_start = max(s_idx, e_idx - fade_len)

    # Absolute digital silence during the void
    out[s_idx:f_in_start] = 0.0

    # Fade in before return transient
    if e_idx > f_in_start:
        fade_in = np.linspace(0.0, 1.0, e_idx - f_in_start, dtype=np.float32)
        out[f_in_start:e_idx] *= fade_in

    return out


def sidechain_duck(
    music: np.ndarray,
    voice: np.ndarray,
    duck_db: float = -4.5,
    sr: int = SAMPLE_RATE,
    smooth_window_ms: float = 180.0,
) -> np.ndarray:
    """
    Smooth sidechain ducking attenuating background music by duck_db whenever voice is active.
    Preserves musical groove without swallowing speech.
    """
    min_len = min(len(music), len(voice))
    m = music[:min_len].copy()
    v = voice[:min_len]

    # Envelope calculation
    env = np.abs(v)
    window = int(sr * (smooth_window_ms / 1000.0))
    if window > 1:
        kernel = np.ones(window, dtype=np.float32) / window
        env_smooth = np.convolve(env, kernel, mode="same")
    else:
        env_smooth = env

    max_val = np.max(env_smooth) if np.max(env_smooth) > 1e-6 else 1.0
    norm_env = np.clip(env_smooth / (max_val * 0.7), 0.0, 1.0)

    # Attenuation scale: e.g. -4.5 dB = 0.595
    duck_ratio = 10.0 ** (duck_db / 20.0)
    gain_curve = 1.0 - norm_env * (1.0 - duck_ratio)

    m *= gain_curve
    return m


def mix_stems_numpy(
    voice: np.ndarray,
    music: np.ndarray,
    voice_gain: float = 1.0,
    music_gain: float = 0.85,
    master_peak_db: float = -1.0,
) -> np.ndarray:
    """Mix voice and music stems directly in NumPy with true-peak safety."""
    total_len = max(len(voice), len(music))
    mix = np.zeros(total_len, dtype=np.float32)

    mix[: len(voice)] += voice * voice_gain
    mix[: len(music)] += music * music_gain

    # Normalization to master_peak_db
    peak = np.max(np.abs(mix))
    target_peak = 10.0 ** (master_peak_db / 20.0)
    if peak > target_peak:
        mix = (mix / peak) * target_peak

    return mix


def load_real_backing_bed(
    style: str = "boombap",
    bars: float = 4.0,
    bpm: float = 87.0,
    drop_bar: Optional[int] = None,
    drop_duration_beats: float = 2.0,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Loads and slices authentic studio-grade instrumental backing tracks,
    precisely aligned to RhythmicGrid downbeats with optional comedic hard mute.

    Supported Styles:
      - 'boombap' / 'lofi': Real MF DOOM / Joey Bada$$ Boom Bap beat (87 BPM)
      - 'chillhop': Real Lo-Fi Chillhop groove
      - 'acoustic': Real Acoustic Guitar fingerpicking bed
    """
    import subprocess
    from pathlib import Path

    grid = RhythmicGrid(bpm=bpm, sample_rate=sr)
    target_dur = grid.get_bar_duration(bars)
    target_samples = int(target_dur * sr)

    track_configs = {
        "boombap": {
            "path": Path("/Users/jaketrigg/Projects/vifi.co/assets/reels/baby_armadillo/Baby_Armadillo_Beat_87BPM (Prod. MerlovwBeatZ).wav"),
            "offset_sec": 11.0726,  # Downbeat of Bar 5 when drums drop
            "native_bpm": 87.0,
        },
        "lofi": {
            "path": Path("/Users/jaketrigg/Projects/vifi.co/assets/reels/baby_armadillo/Baby_Armadillo_Beat_87BPM (Prod. MerlovwBeatZ).wav"),
            "offset_sec": 11.0726,
            "native_bpm": 87.0,
        },
        "chillhop": {
            "path": Path("/Users/jaketrigg/Projects/VoiceFi/assets/audio/auditions/01_lofi_chillhop_music_only.mp3"),
            "offset_sec": 0.0,
            "native_bpm": 87.0,
        },
        "acoustic": {
            "path": Path("/Users/jaketrigg/Projects/VoiceFi/assets/audio/auditions/03_acoustic_guitar_music_only.mp3"),
            "offset_sec": 0.0,
            "native_bpm": 87.0,
        },
    }

    cfg = track_configs.get(style.lower(), track_configs["boombap"])
    track_path = cfg["path"]
    offset = cfg["offset_sec"]

    if not track_path.exists():
        # Fallback to procedural synthesis if file is missing
        print(f"[RhythmicBeatEngine] Track {track_path} not found, falling back to procedural boombap.")
        return generate_lofi_boombap_bed(bars=int(math.ceil(bars)), bpm=bpm, drop_bar=drop_bar, drop_duration_beats=drop_duration_beats, sr=sr)[:target_samples]

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{offset:.4f}",
        "-i", str(track_path),
        "-t", f"{target_dur + 1.0:.4f}",
        "-ac", "1",
        "-ar", str(sr),
        "-f", "f32le",
        "-"
    ]
    raw = subprocess.check_output(cmd)
    audio = np.frombuffer(raw, dtype=np.float32)

    if len(audio) < target_samples:
        repeats = int(math.ceil(target_samples / max(len(audio), 1)))
        audio = np.tile(audio, repeats)

    bed = audio[:target_samples].copy()

    # Apply fade out at very end
    fade_len = int(sr * 0.25)
    if len(bed) > fade_len:
        bed[-fade_len:] *= np.linspace(1.0, 0.0, fade_len, dtype=np.float32)

    # Apply hard-mute void drop if requested
    if drop_bar is not None and drop_bar <= bars:
        drop_start_sec = grid.bar_beat_to_seconds(drop_bar, 1.0)
        drop_dur_sec = drop_duration_beats * grid.beat_sec
        bed = apply_hard_mute(bed, drop_start_sec, drop_dur_sec, sr=sr)

    return bed
