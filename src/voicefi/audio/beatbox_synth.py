"""
VoiceFi™ Taras Stanin Beatbox & Vocal Modular Synthesizer.
Procedurally synthesizes the signature sounds of Taras Stanin and modular beatbox artists:
  1. Distorted Vocal Electric Guitar (False vocal fold subharmonic resonance + acoustic horn formant + tube saturation).
  2. Subharmonic Throat Bass (Period-doubling f0/2 vestibular fold vibration + proximity sub-boost).
  3. Modular Laser Whistle Zaps (Exponential pitch envelope chirp + swept bandpass).
  4. Vocal Tongue Roll / Alveolar Trill ("Rrrs" flutter).
  5. Close-Mic Proximity Beatbox Drums (Buccal air-pop kick, throat rim snare, snappy hats).
  6. Multi-Layer Beatbox Routine & Riff Compositions.
"""

import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np

SAMPLE_RATE = 44100


# --- Component Synthesizers (Pure NumPy Physical Modeling) ---


def synth_beatbox_kick(dur: float = 0.32, sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Close-mic beatbox kick:
      - 0 to 8ms: Buccal air-pressure lip pop transient.
      - 8 to 220ms: Resonant throat pitch drop (145 Hz ➔ 42 Hz) with close-proximity sub-weight.
    """
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)

    # Pitch sweep: drops exponentially from 145 Hz to 42 Hz
    freq_sweep = 115.0 * np.exp(-t / 0.032) + 40.0
    phase = 2.0 * np.pi * np.cumsum(freq_sweep) / sr

    # Deep sub-bass body
    body = np.sin(phase) * np.exp(-t / 0.16)
    # 2nd harmonic for warmth
    body += 0.22 * np.sin(phase * 2.0) * np.exp(-t / 0.08)

    # Lip pop transient (mouth air release click with sub-millisecond fade-in)
    click = np.random.uniform(-0.6, 0.6, n) * np.exp(-t / 0.005) * np.minimum(t / 0.0005, 1.0)

    kick = body * 0.88 + click * 0.25
    return np.clip(kick, -1.0, 1.0).astype(np.float32)


def synth_beatbox_snare(dur: float = 0.28, sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Crisp inward K-snare / throat rim snare:
      - Sharp tongue-palate release click.
      - Snappy filtered vocal noise tail.
      - Resonant acoustic body at 260 Hz.
    """
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)

    # Resonant tonal body (mouth cavity)
    tone_f = 260.0 + 80.0 * np.exp(-t / 0.015)
    tone_phase = 2.0 * np.pi * np.cumsum(tone_f) / sr
    tone = np.sin(tone_phase) * np.exp(-t / 0.038)

    # Tongue-palate release transient with micro-fade-in
    click = np.random.uniform(-0.8, 0.8, n) * np.exp(-t / 0.003) * np.minimum(t / 0.0005, 1.0)

    # Filtered vocal noise tail (simulating inward air rush)
    noise = np.random.normal(0, 1, n)
    # Simple high-pass / bandpass filtering in frequency domain
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    # Bandpass 1800 Hz to 8500 Hz
    bp = (1.0 / (1.0 + (1800.0 / np.maximum(freqs, 1e-4)) ** 4)) * (
        1.0 / (1.0 + (freqs / 8500.0) ** 4)
    )
    filtered_noise = np.fft.irfft(spec * bp, n=n)
    filtered_noise = (
        filtered_noise
        / (np.std(filtered_noise) + 1e-6)
        * np.exp(-t / 0.085)
        * np.minimum(t / 0.001, 1.0)
    )

    snare = 0.35 * tone + 0.35 * click + 0.55 * filtered_noise
    return np.clip(snare, -1.0, 1.0).astype(np.float32)


def synth_beatbox_hihat(
    dur: float = 0.06, open_hat: bool = False, sr: int = SAMPLE_RATE
) -> np.ndarray:
    """Snappy closed or open teeth/tongue 'ts' or 't' hi-hat."""
    d = dur if not open_hat else 0.22
    n = int(sr * d)
    t = np.linspace(0, d, n, False)

    # High frequency metallic / teeth hiss (6 kHz - 14 kHz)
    noise = np.random.normal(0, 1, n)
    spec = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    hp = 1.0 / (1.0 + (6500.0 / np.maximum(freqs, 1e-4)) ** 6)
    filtered = np.fft.irfft(spec * hp, n=n)
    filtered = filtered / (np.std(filtered) + 1e-6)

    decay = 0.015 if not open_hat else 0.09
    att = np.minimum(t / 0.001, 1.0)
    env = np.exp(-t / decay) * att
    hihat = filtered * env * 0.40
    return np.clip(hihat, -1.0, 1.0).astype(np.float32)


def synth_laser_zap(
    dur: float = 0.09,
    start_freq: float = 3800.0,
    end_freq: float = 340.0,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Modular synth / beatbox laser whistle zap.
    Steep exponential frequency plunge with resonant mouth cavity shaping.
    """
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)

    # Exponential pitch plunge
    f_sweep = (start_freq - end_freq) * np.exp(-t / 0.018) + end_freq
    phase = 2.0 * np.pi * np.cumsum(f_sweep) / sr
    phase = phase - phase[0]

    # Carrier with 2nd harmonic overtone for that 'laser' bite
    carrier = np.sin(phase) + 0.28 * np.sin(2.0 * phase)
    # Envelope with clean sub-millisecond attack and decay
    att = np.minimum(t / 0.001, 1.0)
    rel = np.minimum((dur - t) / 0.004, 1.0)
    env = np.exp(-t / 0.032) * att * rel
    zap = carrier * env * 0.65
    return np.clip(zap, -1.0, 1.0).astype(np.float32)


def synth_throat_bass(
    freq: float = 55.0,
    dur: float = 0.65,
    wobble_rate: float = 0.0,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Taras Stanin / Tuvan throat bass (subharmonic vestibular fold period-doubling).
    True cords vibrate at 2*freq, false cords flap at freq (f0/2 subharmonic).
    Creates an aggressive, buzzing analog synth bass.
    """
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)

    # Throat flutter / vocal fry modulation (around 18-24 Hz)
    flutter = 1.0 + 0.18 * np.sin(2.0 * np.pi * 22.0 * t)

    # Subharmonic fundamental + true cord harmonic + rich overtones
    phase = 2.0 * np.pi * freq * t
    if wobble_rate > 0.0:
        # LFO wobble for dubstep style bass drop
        lfo = 1.0 + 0.35 * np.sin(2.0 * np.pi * wobble_rate * t)
        phase = 2.0 * np.pi * np.cumsum(freq * lfo) / sr

    sub = np.sin(phase) * 0.70
    true_cord = np.sin(phase * 2.0) * 0.45
    harmonic3 = np.sin(phase * 3.0) * 0.25
    harmonic4 = np.sin(phase * 4.0) * 0.15

    raw = (sub + true_cord + harmonic3 + harmonic4) * flutter

    # Non-linear acoustic saturation (false fold compression)
    saturated = np.tanh(2.8 * raw)

    # Envelope
    env = np.ones(n)
    attack = int(0.02 * sr)
    decay = int(0.06 * sr)
    env[:attack] = np.linspace(0, 1, attack)
    env[-decay:] = np.linspace(1, 0, decay)

    bass = saturated * env * 0.75
    return np.clip(bass, -1.0, 1.0).astype(np.float32)


def synth_tongue_roll(
    dur: float = 0.35,
    pitch: float = 175.0,
    trill_speed: float = 24.0,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Alveolar trill / vocal tongue roll ("Rrrs" effect).
    Simulates rapid tongue fluttering against the palate modulating the voiced pitch.
    """
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)

    phase = 2.0 * np.pi * pitch * t
    voice = np.sin(phase) + 0.4 * np.sin(2 * phase) + 0.2 * np.sin(3 * phase)

    # Tongue flap amplitude modulation (22 - 28 Hz fluttering)
    trill = (np.sin(2.0 * np.pi * trill_speed * t) + 1.0) * 0.5
    trill = trill**1.8  # sharpen tongue clicks

    # Tongue impact transients
    clicks = np.random.uniform(-0.3, 0.3, n) * (trill > 0.85)

    roll = voice * trill * 0.75 + clicks * 0.35
    env = np.ones(n)
    att_len = int(0.01 * sr)
    fade_len = int(0.03 * sr)
    env[:att_len] = np.linspace(0, 1, att_len)
    env[-fade_len:] = np.linspace(1, 0, fade_len)
    return np.clip(roll * env * 0.70, -1.0, 1.0).astype(np.float32)


def synth_taras_guitar_note(
    freq: float,
    dur: float,
    gain: float = 0.85,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Taras Stanin's signature vocal electric guitar note:
      - False fold acoustic distortion (subharmonic f0/2 blend + vocal jitter).
      - Narrow mouth horn / trumpet embouchure resonant formant filter (~1400 Hz & 2600 Hz).
      - Cubic tube amp wavefolding.
      - Dynamic pick transient.
    """
    n = int(sr * dur)
    t = np.linspace(0, dur, n, False)

    # Human vibrato: 5.4 Hz with slight ramp-in after 60ms
    vib_ramp = np.minimum(t / 0.12, 1.0)
    vib = 1.0 + 0.015 * vib_ramp * np.sin(2.0 * np.pi * 5.4 * t)
    phase = 2.0 * np.pi * np.cumsum(freq * vib) / sr

    # Carrier oscillator (true vocal folds)
    carrier = (
        np.sin(phase)
        + 0.65 * np.sin(2.0 * phase)
        + 0.45 * np.sin(3.0 * phase)
        + 0.30 * np.sin(4.0 * phase)
    )

    # False cord subharmonic distortion (f0 / 2) with organic vocal jitter
    jitter = 1.0 + 0.08 * np.random.randn(n)
    subharmonic = 0.38 * np.sin(phase * 0.5) * jitter

    vocal_raw = carrier + subharmonic

    # Asymmetric tube saturation / wavefolder
    # (mimics guitar amp overdrive and vocal fold collision)
    driven = np.tanh(3.6 * vocal_raw) + 0.12 * (vocal_raw**2)

    # Vocal tract / guitar cab formant filtering (peaking around 1400 Hz & 2800 Hz)
    imp_len = 160
    t_imp = np.linspace(0, imp_len / sr, imp_len, False)
    f1 = np.sin(2.0 * np.pi * 1350.0 * t_imp) * np.exp(-t_imp * 24.0)
    f2 = 0.5 * np.sin(2.0 * np.pi * 2700.0 * t_imp) * np.exp(-t_imp * 32.0)
    cab_filter = f1 + f2
    filtered = np.convolve(driven, cab_filter, mode="same")

    # Pick attack and release envelope
    env = np.ones(n)
    att_samples = int(0.007 * sr)  # crisp pick transient
    rel_samples = int(0.045 * sr)
    env[:att_samples] = np.linspace(0, 1, att_samples)
    env[-rel_samples:] = np.linspace(1, 0, rel_samples)

    # Fast pick transient click
    pick_click = np.random.uniform(-0.4, 0.4, n) * np.exp(-t / 0.004)

    note = (filtered * 0.85 + pick_click * 0.18) * env * gain
    return np.clip(note, -1.0, 1.0).astype(np.float32)


# --- Composed Riffs & Beatbox Routines ---


def synth_taras_guitar_riff(
    riff_style: str = "rock",
    bpm: float = 95.0,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Renders an authentic Taras Stanin vocal electric guitar riff:
      - 'rock': Heavy driving power riff (E3 - G3 - A3 - Bb3 - A3 - G3 - E3) with slide & vibrato.
      - 'nirvana': Grunge power chord riff (Smells Like Teen Spirit cadence).
      - 'solo': Expressive high lead melody with bends and vibrato.
    """
    beat_sec = 60.0 / bpm

    if riff_style == "nirvana":
        # F3, Bb3, Ab3, Db4 power chord progression
        notes = [
            (174.61, beat_sec * 0.75),
            (174.61, beat_sec * 0.50),
            (233.08, beat_sec * 0.75),
            (207.65, beat_sec * 0.75),
            (207.65, beat_sec * 0.50),
            (277.18, beat_sec * 0.75),
        ]
    elif riff_style == "solo":
        # High singing lead guitar solo (E4, G4, A4, B4)
        notes = [
            (329.63, beat_sec * 0.50),
            (392.00, beat_sec * 0.50),
            (440.00, beat_sec * 1.00),
            (392.00, beat_sec * 0.50),
            (440.00, beat_sec * 0.50),
            (493.88, beat_sec * 1.00),
        ]
    else:
        # Default driving rock riff (E3, G3, A3, Bb3, A3, G3, E3)
        notes = [
            (164.81, beat_sec * 0.50),  # E3
            (164.81, beat_sec * 0.25),  # E3
            (196.00, beat_sec * 0.50),  # G3
            (220.00, beat_sec * 0.50),  # A3
            (233.08, beat_sec * 0.25),  # Bb3
            (220.00, beat_sec * 0.50),  # A3
            (196.00, beat_sec * 0.50),  # G3
            (164.81, beat_sec * 1.00),  # E3 (sustained)
        ]

    chunks = []
    for freq, dur in notes:
        note_audio = synth_taras_guitar_note(freq, dur, sr=sr)
        chunks.append(note_audio)

    return np.concatenate(chunks)


def generate_taras_beatbox_routine(
    bars: int = 2,
    bpm: float = 95.0,
    include_guitar: bool = True,
    sr: int = SAMPLE_RATE,
) -> np.ndarray:
    """
    Renders a complete, multi-layered Taras Stanin beatbox performance routine:
      - Layer 1: Close-mic Beatbox Rhythm (Kick on 1 & 3, Snare on 2 & 4, 16th Hats & Rolls).
      - Layer 2: Modular Laser Zaps & Tongue Rolls.
      - Layer 3: Subharmonic Throat Bassline.
      - Layer 4: Distorted Vocal Electric Guitar Lead soloing across the beat!
    """
    beat_sec = 60.0 / bpm
    bar_sec = beat_sec * 4.0
    total_dur = bar_sec * bars
    total_samples = int(total_dur * sr)
    mix = np.zeros(total_samples, dtype=np.float32)

    # Pre-generate elements
    kick = synth_beatbox_kick(dur=0.30, sr=sr)
    snare = synth_beatbox_snare(dur=0.26, sr=sr)
    hihat = synth_beatbox_hihat(dur=0.06, sr=sr)
    open_hat = synth_beatbox_hihat(dur=0.20, open_hat=True, sr=sr)
    laser = synth_laser_zap(dur=0.08, sr=sr)
    roll = synth_tongue_roll(dur=0.32, sr=sr)

    def _paste(src: np.ndarray, start_sec: float, vol: float = 1.0) -> None:
        idx = int(start_sec * sr)
        if idx >= total_samples:
            return
        end_idx = min(idx + len(src), total_samples)
        mix[idx:end_idx] += src[: end_idx - idx] * vol

    # --- 1. Drum & Rhythm Layer ---
    for b in range(bars):
        b_start = b * bar_sec

        # Beatbox Kicks (Beat 1, 2.75, 3)
        _paste(kick, b_start + 0.0 * beat_sec, 0.95)
        _paste(kick, b_start + 1.75 * beat_sec, 0.75)
        _paste(kick, b_start + 2.0 * beat_sec, 0.95)

        # Beatbox Snares (Beat 2 and 4)
        _paste(snare, b_start + 1.0 * beat_sec, 0.92)
        _paste(snare, b_start + 3.0 * beat_sec, 0.95)

        # Hi-Hats on 8th notes and 16ths
        for h_step in range(8):
            h_time = b_start + (h_step * 0.5) * beat_sec
            h_sample = open_hat if h_step == 3 else hihat
            _paste(h_sample, h_time, 0.38)

        # Laser Zaps on syncopated upbeats
        if b % 2 == 0:
            _paste(laser, b_start + 1.5 * beat_sec, 0.65)
            _paste(laser, b_start + 3.5 * beat_sec, 0.70)
        else:
            _paste(roll, b_start + 3.25 * beat_sec, 0.75)

    # --- 2. Throat Bass Layer ---
    throat_e = synth_throat_bass(freq=55.0, dur=beat_sec * 0.9, sr=sr)  # E1 sub
    throat_g = synth_throat_bass(freq=65.4, dur=beat_sec * 0.9, sr=sr)  # G1 sub
    throat_a = synth_throat_bass(freq=73.4, dur=beat_sec * 0.9, sr=sr)  # A1 sub

    for b in range(bars):
        b_start = b * bar_sec
        _paste(throat_e, b_start + 0.0 * beat_sec, 0.65)
        _paste(throat_e, b_start + 1.0 * beat_sec, 0.65)
        _paste(throat_g, b_start + 2.0 * beat_sec, 0.65)
        _paste(throat_a, b_start + 3.0 * beat_sec, 0.70)

    # --- 3. Taras Vocal Electric Guitar Layer ---
    if include_guitar:
        riff = synth_taras_guitar_riff(riff_style="rock", bpm=bpm, sr=sr)
        # Paste guitar over the mix with stadium presence
        _paste(riff, 0.0, vol=0.82)
        if bars > 2:
            solo = synth_taras_guitar_riff(riff_style="solo", bpm=bpm, sr=sr)
            _paste(solo, 2.0 * bar_sec, vol=0.85)

    # Final studio mastering: gentle soft-limiting to prevent clipping
    peak = np.max(np.abs(mix))
    if peak > 0.95:
        mix = mix / peak * 0.95

    return mix.astype(np.float32)


# --- File Output & Playback Utilities ---


def save_beatbox_wav(
    audio_data: np.ndarray, file_path: Union[str, Path], sr: int = SAMPLE_RATE
) -> Path:
    """Save floating-point audio data as 16-bit PCM WAV."""
    p = Path(file_path).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)

    # Convert to 16-bit integer PCM
    audio_int16 = (np.clip(audio_data, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(str(p), "wb") as wf:
        wf.setnchannels(1)  # Mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sr)
        wf.writeframes(audio_int16.tobytes())

    return p


def play_beatbox(
    preset: str = "routine",
    bpm: float = 95.0,
    block: bool = True,
    volume: float = 1.0,
) -> bool:
    """
    Synthesize and play Taras Stanin beatbox audio aloud via macOS afplay.
    Presets:
      - 'routine' / 'drop': Full multi-layered beatbox & guitar routine.
      - 'guitar' / 'riff': Distorted vocal electric guitar solo.
      - 'throat_bass' / 'bass': Subharmonic throat bass drop.
      - 'laser' / 'zap': Modular whistle laser zaps.
      - 'drums': Clean beatbox kick, snare, and hi-hat beat.
    """
    preset_clean = preset.lower().strip()

    if preset_clean in ("guitar", "riff", "rock"):
        audio = synth_taras_guitar_riff(riff_style="rock", bpm=bpm)
    elif preset_clean in ("throat_bass", "bass", "sub"):
        audio = synth_throat_bass(freq=55.0, dur=1.8, wobble_rate=3.5)
    elif preset_clean in ("laser", "zap", "lasers"):
        # Rapid triple laser zap stinger
        z1 = synth_laser_zap(dur=0.08)
        z2 = synth_laser_zap(dur=0.08, start_freq=4400.0, end_freq=400.0)
        z3 = synth_laser_zap(dur=0.12, start_freq=3200.0, end_freq=220.0)
        gap = np.zeros(int(SAMPLE_RATE * 0.05), dtype=np.float32)
        audio = np.concatenate([z1, gap, z2, gap, z3])
    elif preset_clean in ("drums", "beat"):
        audio = generate_taras_beatbox_routine(bars=2, bpm=bpm, include_guitar=False)
    else:  # routine / drop
        audio = generate_taras_beatbox_routine(bars=2, bpm=bpm, include_guitar=True)

    # Save to temporary WAV
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        save_beatbox_wav(audio, tmp_path)

        if os.getenv("VOICEFI_TESTING") == "1" or os.getenv("VOICEFI_HEADLESS") == "1":
            return True

        from voicefi.audio.output_lock import exclusive_audio

        vol_str = str(max(min(volume, 2.0), 0.1))
        cmd = ["afplay", "-v", vol_str, str(tmp_path)]

        if block:
            with exclusive_audio("taras_beatbox"):
                subprocess.run(cmd, check=True)
            return True
        else:
            import threading

            def _play_async():
                try:
                    with exclusive_audio("taras_beatbox"):
                        proc = subprocess.Popen(cmd)
                        proc.wait()
                except Exception as ex:
                    print(f"[BeatboxSynth] Async playback error: {ex}", file=sys.stderr)
                finally:
                    if tmp_path.is_file():
                        try:
                            tmp_path.unlink()
                        except Exception:
                            pass

            t = threading.Thread(target=_play_async, daemon=True, name="BeatboxAsyncPlayback")
            t.start()
            return True
    except Exception as e:
        print(f"[BeatboxSynth] Playback error: {e}", file=sys.stderr)
        return False
    finally:
        # Clean up immediately if blocking or under test mode;
        # non-blocking playback is cleaned up by _play_async once finished.
        if (
            block or os.getenv("VOICEFI_TESTING") == "1" or os.getenv("VOICEFI_HEADLESS") == "1"
        ) and tmp_path.is_file():
            try:
                tmp_path.unlink()
            except Exception:
                pass
